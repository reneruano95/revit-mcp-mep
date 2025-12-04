"""
Auto-Resize Ducts on Equipment Capacity Change
===============================================
This Dynamo script automatically resizes ducts when HVAC equipment capacity changes.
It recalculates duct dimensions based on the new CFM requirements while maintaining
velocity limits and using standard duct sizes.

Duct Selection Methods:
    - "direct":     IN[0] = Selected ducts directly (no equipment needed)
    - "equipment":  IN[0] = Mechanical equipment (finds connected ducts)
    - "system":     IN[0] = System name string (e.g., "Supply Air 1")
    - "level":      IN[0] = Level element (all ducts on that level)
    - "all":        IN[0] = Not used (processes all ducts in project)

Usage:
    1. Set DUCT_SELECTION_METHOD to your preferred method
    2. Provide the old and new CFM values
    3. Connect appropriate input to IN[0]
    4. Run the script

Apartment Mode:
    - Locks duct height (ceiling constraint)
    - Only adjusts width to accommodate new airflow
    - Uses lower velocity limits for residential noise control
"""

import clr

clr.AddReference("RevitServices")
clr.AddReference("RevitAPI")
clr.AddReference("RevitNodes")

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Mechanical import *
from Autodesk.Revit.DB.Plumbing import *  # For PlumbingUtils if needed

doc = DocumentManager.Instance.CurrentDBDocument

# =============================================================================
# CONFIGURATION - Modify these values as needed
# =============================================================================

# Duct Selection Method: "direct", "equipment", "system", "level", "all"
#   - "direct":    Select ducts directly in Revit (no equipment connection needed)
#   - "equipment": Select mechanical equipment (finds connected ducts via MEP system)
#   - "system":    Provide system name as string (e.g., "Supply Air 1")
#   - "level":     Select a level (resizes all ducts on that level)
#   - "all":       Resize all ducts in the project (use with caution!)
DUCT_SELECTION_METHOD = "system"

# CFM Source Method: "terminals", "equipment_param", "user_input"
CFM_SOURCE_METHOD = "user_input"

# User-provided values (used when CFM_SOURCE_METHOD = "user_input")
OLD_CFM = 400  # Previous equipment capacity
NEW_CFM = 600  # New equipment capacity

# Equipment parameter name for CFM (used when CFM_SOURCE_METHOD = "equipment_param")
EQUIPMENT_CFM_PARAM = "Airflow"

# Filter by system name (optional, works with any selection method)
# Set to None or "" to disable filtering
FILTER_BY_SYSTEM_NAME = "Mechanical Supply Air 16"  # e.g., "Supply Air 1"

# Operating Mode: "commercial" or "apartment"
OPERATING_MODE = "apartment"

# Fitting Update Mode: "report_only", "delete_and_recreate", "try_update"
#   - "report_only":        Just report which fittings need attention (safest)
#   - "delete_and_recreate": Delete old fittings and create new ones with correct sizes
#   - "try_update":         Try to update fitting parameters if possible
FITTING_UPDATE_MODE = "delete_and_recreate"

# Velocity limits in FPM (Feet Per Minute)
VELOCITY_LIMITS = {
    "commercial": {"trunk": 1500, "branch": 1200, "runout": 800},
    "apartment": {"trunk": 1200, "branch": 1000, "runout": 700},
}

# Duct classification by size (cross-sectional area in sq inches)
DUCT_SIZE_THRESHOLDS = {
    "trunk_min_area": 144,  # >= 144 sq in (e.g., 12x12) is trunk
    "branch_min_area": 48,  # >= 48 sq in (e.g., 8x6) is branch
    # Below branch_min_area is runout
}

# Standard duct size increment (inches)
STANDARD_SIZE_INCREMENT = 2

# Minimum duct dimensions (inches)
MIN_DUCT_WIDTH = 6
MIN_DUCT_HEIGHT = 6

# Unit conversion constants
FEET_TO_INCHES = 12
INCHES_TO_FEET = 1 / 12

# Connector matching tolerance (feet)
CONNECTOR_MATCH_TOLERANCE = 0.01

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_duct_type(duct):
    """Classify duct as trunk, branch, or runout based on cross-sectional area."""
    height_param = duct.get_Parameter(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)
    width_param = duct.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM)

    if not height_param or not width_param:
        # Round duct - use diameter
        diameter_param = duct.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
        if diameter_param:
            diameter_in = diameter_param.AsDouble() * FEET_TO_INCHES
            area = 3.14159 * (diameter_in / 2) ** 2
        else:
            return "runout"
    else:
        height_in = height_param.AsDouble() * FEET_TO_INCHES
        width_in = width_param.AsDouble() * FEET_TO_INCHES
        area = height_in * width_in

    if area >= DUCT_SIZE_THRESHOLDS["trunk_min_area"]:
        return "trunk"
    elif area >= DUCT_SIZE_THRESHOLDS["branch_min_area"]:
        return "branch"
    else:
        return "runout"


def get_velocity_limit(duct_type, mode):
    """Get the velocity limit for a duct type and operating mode."""
    return VELOCITY_LIMITS[mode][duct_type]


def round_to_standard(dimension_in, increment=STANDARD_SIZE_INCREMENT):
    """Round dimension to nearest standard duct size."""
    return round(dimension_in / increment) * increment


def calculate_required_area(cfm, max_velocity_fpm):
    """Calculate required duct area in square inches for given CFM and velocity."""
    # Area (ft²) = CFM / FPM
    area_ft2 = cfm / max_velocity_fpm
    # Convert to square inches
    area_in2 = area_ft2 * 144
    return area_in2


def calculate_width_for_height(required_area_in2, height_in):
    """Calculate width given a fixed height and required area."""
    if height_in <= 0:
        return MIN_DUCT_WIDTH
    width_in = required_area_in2 / height_in
    return max(MIN_DUCT_WIDTH, width_in)


def calculate_velocity(cfm, width_in, height_in):
    """Calculate air velocity in FPM."""
    area_ft2 = (width_in / 12) * (height_in / 12)
    if area_ft2 <= 0:
        return 0
    return cfm / area_ft2


def get_connector_manager(element):
    """Return the connector manager for any MEP element, if available."""
    if not element:
        return None
    try:
        if hasattr(element, "ConnectorManager") and element.ConnectorManager:
            return element.ConnectorManager
    except:
        pass
    try:
        if hasattr(element, "MEPModel") and element.MEPModel:
            return element.MEPModel.ConnectorManager
    except:
        pass
    return None


def iter_connectors(element):
    """Safely iterate connectors on an element."""
    connector_manager = get_connector_manager(element)
    if not connector_manager or not connector_manager.Connectors:
        return []
    return [conn for conn in connector_manager.Connectors]


def ensure_open_connector(connector):
    """Make sure a connector is open before reusing it."""
    if connector and connector.IsConnected:
        try:
            connector.DisconnectAll()
        except:
            pass
    return connector


def find_connector_near_point(element, target_point, tolerance=CONNECTOR_MATCH_TOLERANCE):
    """Find the connector on an element closest to a target point."""
    if not element or not target_point:
        return None

    connectors = iter_connectors(element)
    if not connectors:
        return None

    best_match = None
    best_dist = None
    for connector in connectors:
        try:
            dist = connector.Origin.DistanceTo(target_point)
        except:
            continue

        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_match = connector

        if dist <= tolerance and not connector.IsConnected:
            return ensure_open_connector(connector)

    if best_match and (best_dist is None or best_dist <= tolerance * 5):
        return ensure_open_connector(best_match)

    # As a last resort, return any open connector
    for connector in connectors:
        if not connector.IsConnected:
            return ensure_open_connector(connector)

    return ensure_open_connector(best_match)


def get_connected_ducts(equipment):
    """Get all ducts connected to the mechanical equipment via its duct system."""
    connected_ducts = []

    # Get the connector manager for the equipment
    try:
        connector_set = equipment.MEPModel.ConnectorManager.Connectors
    except:
        print(f"Equipment {equipment.Id} has no connector manager")
        return connected_ducts

    # Find all connected duct systems
    duct_systems = set()
    for connector in connector_set:
        if connector.Domain == Domain.DomainHvac:
            if connector.MEPSystem:
                duct_systems.add(connector.MEPSystem.Id)

    # Get all ducts from each connected system
    for system_id in duct_systems:
        system = doc.GetElement(system_id)
        if system:
            try:
                duct_network = system.DuctNetwork
                if duct_network:
                    for item in duct_network:
                        # Check if item is an ElementId or an Element
                        if hasattr(item, "IntegerValue"):
                            # It's an ElementId, get the element
                            element = doc.GetElement(item)
                        else:
                            # It's already an element
                            element = item
                        
                        if element and hasattr(element, "Category") and element.Category:
                            if element.Category.Id.IntegerValue == int(BuiltInCategory.OST_DuctCurves):
                                connected_ducts.append(element)
            except Exception as e:
                print(f"Error getting ducts from system: {e}")

    return connected_ducts


def get_ducts_by_system_name(system_name):
    """Get all ducts belonging to a named mechanical system."""
    ducts = []

    # Get all mechanical systems
    systems = FilteredElementCollector(doc).OfClass(MechanicalSystem).ToElements()

    for system in systems:
        if system.Name == system_name or system_name in system.Name:
            try:
                # DuctNetwork may return elements directly or ElementIds depending on Revit version
                duct_network = system.DuctNetwork
                if duct_network:
                    for item in duct_network:
                        # Check if item is an ElementId or an Element
                        if hasattr(item, "IntegerValue"):
                            # It's an ElementId, get the element
                            element = doc.GetElement(item)
                        else:
                            # It's already an element
                            element = item
                        
                        if element and hasattr(element, "Category") and element.Category:
                            if element.Category.Id.IntegerValue == int(BuiltInCategory.OST_DuctCurves):
                                ducts.append(element)
            except Exception as e:
                print(f"Error getting ducts from system {system.Name}: {e}")

    return ducts


def get_ducts_by_level(level):
    """Get all ducts on a specific level."""
    ducts = []

    # Get the level ID
    level_id = level.Id if hasattr(level, "Id") else level

    # Get all ducts
    all_ducts = (
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_DuctCurves)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    for duct in all_ducts:
        # Check reference level
        ref_level_param = duct.get_Parameter(BuiltInParameter.RBS_START_LEVEL_PARAM)
        if ref_level_param and ref_level_param.AsElementId() == level_id:
            ducts.append(duct)

    return ducts


def get_all_ducts():
    """Get all ducts in the project."""
    return list(
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_DuctCurves)
        .WhereElementIsNotElementType()
        .ToElements()
    )


def filter_ducts_by_system(ducts, system_name):
    """Filter ducts to only those belonging to a specific system name."""
    if not system_name:
        return ducts

    filtered = []
    for duct in ducts:
        try:
            # Get the duct's MEP system
            connector_set = duct.ConnectorManager.Connectors
            for connector in connector_set:
                if connector.MEPSystem:
                    sys_name = connector.MEPSystem.Name
                    if system_name in sys_name or sys_name == system_name:
                        filtered.append(duct)
                        break
        except:
            continue

    return filtered


def get_duct_system_name(duct):
    """Get the system name for a duct."""
    try:
        connector_set = duct.ConnectorManager.Connectors
        for connector in connector_set:
            if connector.MEPSystem:
                return connector.MEPSystem.Name
    except:
        pass
    return "Unknown"


def get_connected_terminals(equipment):
    """Get all air terminals connected to the equipment's duct system."""
    terminals = []

    try:
        connector_set = equipment.MEPModel.ConnectorManager.Connectors
    except:
        return terminals

    # Find connected duct systems
    duct_systems = set()
    for connector in connector_set:
        if connector.Domain == Domain.DomainHvac:
            if connector.MEPSystem:
                duct_systems.add(connector.MEPSystem.Id)

    # Get terminals from each system
    for system_id in duct_systems:
        system = doc.GetElement(system_id)
        if system:
            # Get terminal elements
            terminal_set = system.Elements
            for elem in terminal_set:
                if elem.Category.Id.IntegerValue == int(
                    BuiltInCategory.OST_DuctTerminal
                ):
                    terminals.append(elem)

    return terminals


def get_terminal_cfm(terminal):
    """Get the CFM value from an air terminal."""
    flow_param = terminal.get_Parameter(BuiltInParameter.RBS_DUCT_FLOW_PARAM)
    if flow_param:
        # Revit stores flow in ft³/s, convert to CFM
        return flow_param.AsDouble() * 60
    return 0


def sum_terminal_cfm(terminals):
    """Sum up CFM from all terminals."""
    total_cfm = 0
    for terminal in terminals:
        total_cfm += get_terminal_cfm(terminal)
    return total_cfm


def get_equipment_cfm(equipment, param_name):
    """Get CFM from equipment parameter."""
    param = equipment.LookupParameter(param_name)
    if param:
        if param.StorageType == StorageType.Double:
            return param.AsDouble()
        elif param.StorageType == StorageType.Integer:
            return float(param.AsInteger())
    return 0


# =============================================================================
# MAIN RESIZE FUNCTIONS
# =============================================================================


def resize_duct_commercial(duct, scale_factor):
    """
    Resize a duct for commercial applications.
    Both width and height can change to optimize dimensions.
    Scales dimensions proportionally based on CFM scale factor.
    """
    result = {
        "id": str(duct.Id.IntegerValue),
        "old_dims": "",
        "new_dims": "",
        "velocity_fpm": 0,
        "duct_type": "",
        "warning": None,
    }

    # Get current dimensions
    height_param = duct.get_Parameter(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)
    width_param = duct.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
    flow_param = duct.get_Parameter(BuiltInParameter.RBS_DUCT_FLOW_PARAM)

    if not all([height_param, width_param]):
        result["warning"] = (
            f"Duct {duct.Id} missing dimension parameters (may be round duct)"
        )
        return result

    # Get current values in inches
    height_in = height_param.AsDouble() * FEET_TO_INCHES
    width_in = width_param.AsDouble() * FEET_TO_INCHES

    if height_in <= 0 or width_in <= 0:
        result["warning"] = f"Duct {duct.Id} has zero dimensions"
        return result

    result["old_dims"] = f'{width_in:.0f}×{height_in:.0f}"'

    # Get current flow and calculate new flow
    current_cfm = flow_param.AsDouble() * 60 if flow_param else 0
    new_cfm = current_cfm * scale_factor

    # Determine duct type and velocity limit
    duct_type = get_duct_type(duct)
    result["duct_type"] = duct_type
    max_velocity = get_velocity_limit(duct_type, "commercial")

    # Scale dimensions proportionally to maintain velocity
    # Area scales linearly with CFM, so each dimension scales by sqrt(scale_factor)
    dimension_scale = scale_factor ** 0.5
    
    new_height = height_in * dimension_scale
    new_width = width_in * dimension_scale

    # Round to standard sizes
    new_height = round_to_standard(new_height)
    new_width = round_to_standard(new_width)

    # Ensure minimum sizes
    new_height = max(MIN_DUCT_HEIGHT, new_height)
    new_width = max(MIN_DUCT_WIDTH, new_width)

    result["new_dims"] = f'{new_width:.0f}×{new_height:.0f}"'

    # Calculate resulting velocity
    velocity = calculate_velocity(new_cfm, new_width, new_height)
    result["velocity_fpm"] = round(velocity, 0)

    # Check velocity limits
    if velocity > max_velocity:
        result["warning"] = (
            f"Velocity {velocity:.0f} FPM exceeds {max_velocity} FPM limit"
        )

    # Apply new dimensions
    if not height_param.IsReadOnly:
        height_param.Set(new_height * INCHES_TO_FEET)
    if not width_param.IsReadOnly:
        width_param.Set(new_width * INCHES_TO_FEET)

    return result


def resize_duct_apartment(duct, scale_factor):
    """
    Resize a duct for apartment applications.
    Height is locked (ceiling constraint), only width changes.
    Scales the current duct dimensions based on the CFM scale factor.
    """
    result = {
        "id": str(duct.Id.IntegerValue),
        "old_dims": "",
        "new_dims": "",
        "velocity_fpm": 0,
        "duct_type": "",
        "warning": None,
    }

    # Get current dimensions
    height_param = duct.get_Parameter(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)
    width_param = duct.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
    flow_param = duct.get_Parameter(BuiltInParameter.RBS_DUCT_FLOW_PARAM)

    if not all([height_param, width_param]):
        result["warning"] = f"Duct {duct.Id} missing dimension parameters"
        return result

    # Get current values in inches
    height_in = height_param.AsDouble() * FEET_TO_INCHES
    current_width_in = width_param.AsDouble() * FEET_TO_INCHES

    if height_in <= 0 or current_width_in <= 0:
        result["warning"] = f"Duct {duct.Id} has zero dimensions"
        return result

    result["old_dims"] = f'{current_width_in:.0f}×{height_in:.0f}"'

    # Get current flow and calculate new flow
    current_cfm = flow_param.AsDouble() * 60 if flow_param else 0
    new_cfm = current_cfm * scale_factor

    # Determine duct type and velocity limit
    duct_type = get_duct_type(duct)
    result["duct_type"] = duct_type
    max_velocity = get_velocity_limit(duct_type, "apartment")

    # Calculate new width to maintain velocity within limits
    # For apartment mode: scale width proportionally to CFM increase (height is locked)
    # New area needed = Current area * scale_factor (to maintain same velocity)
    # Since height is locked: new_width = current_width * scale_factor
    new_width_in = current_width_in * scale_factor

    # Round to standard size
    new_width_in = round_to_standard(new_width_in)

    # Ensure minimum size
    new_width_in = max(MIN_DUCT_WIDTH, new_width_in)

    result["new_dims"] = f'{new_width_in:.0f}×{height_in:.0f}"'

    # Calculate resulting velocity
    velocity = calculate_velocity(new_cfm, new_width_in, height_in)
    result["velocity_fpm"] = round(velocity, 0)

    # Check velocity limits
    if velocity > max_velocity:
        result["warning"] = (
            f"Velocity {velocity:.0f} FPM exceeds {max_velocity} FPM limit for residential"
        )

    # Check aspect ratio (shouldn't exceed 4:1 typically)
    aspect_ratio = max(new_width_in, height_in) / min(new_width_in, height_in)
    if aspect_ratio > 4:
        if result["warning"]:
            result["warning"] += f"; Aspect ratio {aspect_ratio:.1f}:1 exceeds 4:1"
        else:
            result["warning"] = f"Aspect ratio {aspect_ratio:.1f}:1 exceeds 4:1"

    # Apply new width (height stays the same)
    if not width_param.IsReadOnly:
        width_param.Set(new_width_in * INCHES_TO_FEET)

    return result


def update_terminal_cfm(
    terminals, old_total_cfm, new_total_cfm, distribution_method="proportional"
):
    """
    Update terminal CFM values after equipment capacity change.

    distribution_method options:
        - "proportional": Scale each terminal proportionally
        - "equal": Distribute change equally
    """
    results = []

    if old_total_cfm <= 0:
        return results

    scale_factor = new_total_cfm / old_total_cfm
    cfm_change = new_total_cfm - old_total_cfm
    equal_change = cfm_change / len(terminals) if terminals else 0

    for terminal in terminals:
        flow_param = terminal.get_Parameter(BuiltInParameter.RBS_DUCT_FLOW_PARAM)
        if not flow_param or flow_param.IsReadOnly:
            continue

        current_cfm = flow_param.AsDouble() * 60

        if distribution_method == "proportional":
            new_cfm = current_cfm * scale_factor
        else:  # equal
            new_cfm = current_cfm + equal_change

        # Convert back to ft³/s for Revit
        flow_param.Set(new_cfm / 60)

        results.append(
            {
                "id": str(terminal.Id.IntegerValue),
                "old_cfm": round(current_cfm, 0),
                "new_cfm": round(new_cfm, 0),
            }
        )

    return results


# =============================================================================
# MAIN SCRIPT EXECUTION
# =============================================================================

# Get input from Dynamo
# IN[0] depends on DUCT_SELECTION_METHOD:
#   - "direct":    List of duct elements
#   - "equipment": List of mechanical equipment elements
#   - "system":    System name string (e.g., "Supply Air 1")
#   - "level":     Level element
#   - "all":       Not used (can be None)

# Debug: Show what we received
print(f"IN[0] type: {type(IN[0])}")
print(f"IN[0] value: {IN[0]}")

# Handle empty input
if IN[0] is None or IN[0] == "" or (isinstance(IN[0], list) and len(IN[0]) == 0):
    print("WARNING: No input provided to IN[0]. Please connect ducts to the input.")
    input_elements = []
else:
    input_elements = UnwrapElement(IN[0]) if IN[0] else []

# Ensure it's a list for direct/equipment methods
if not isinstance(input_elements, list):
    input_elements = [input_elements]

print(f"Input elements count: {len(input_elements)}")

# Calculate scale factor from CFM values
if OLD_CFM <= 0:
    raise ValueError("OLD_CFM must be greater than 0")

scale_factor = NEW_CFM / OLD_CFM
print(f"Scale factor: {scale_factor:.3f} ({OLD_CFM} CFM -> {NEW_CFM} CFM)")
print(f"Operating mode: {OPERATING_MODE}")
print(f"Duct selection method: {DUCT_SELECTION_METHOD}")

# Results storage
all_results = {
    "selection_method": DUCT_SELECTION_METHOD,
    "operating_mode": OPERATING_MODE,
    "old_cfm": OLD_CFM,
    "new_cfm": NEW_CFM,
    "scale_factor": round(scale_factor, 3),
    "ducts_processed": 0,
    "ducts_resized": 0,
    "warnings": [],
    "details": [],
}

# Collect ducts based on selection method
ducts_to_resize = []

if DUCT_SELECTION_METHOD == "direct":
    # IN[0] = Selected ducts directly
    for elem in input_elements:
        if not elem:
            continue
        # Check if element has Category attribute (is a Revit element)
        if not hasattr(elem, "Category"):
            print(f"  Skipping non-element: {type(elem)}")
            continue
        # Some elements may have None category
        if not elem.Category:
            print(f"  Element {elem.Id} has no category")
            continue
        # Check if it's a duct
        try:
            cat_id = elem.Category.Id.IntegerValue
            if cat_id == int(BuiltInCategory.OST_DuctCurves):
                ducts_to_resize.append(elem)
            else:
                print(f"  Element {elem.Id} is category {elem.Category.Name}, not a duct")
        except Exception as e:
            print(f"  Error checking element: {e}")
    print(f"Direct selection: {len(ducts_to_resize)} ducts")

elif DUCT_SELECTION_METHOD == "equipment":
    # IN[0] = Mechanical equipment (find connected ducts)
    for equipment in input_elements:
        if equipment:
            connected = get_connected_ducts(equipment)
            ducts_to_resize.extend(connected)
            print(f"Equipment {equipment.Id}: {len(connected)} connected ducts")
    # Remove duplicates
    seen_ids = set()
    unique_ducts = []
    for duct in ducts_to_resize:
        if duct.Id.IntegerValue not in seen_ids:
            seen_ids.add(duct.Id.IntegerValue)
            unique_ducts.append(duct)
    ducts_to_resize = unique_ducts
    print(f"Total unique ducts from equipment: {len(ducts_to_resize)}")

elif DUCT_SELECTION_METHOD == "system":
    # Use FILTER_BY_SYSTEM_NAME config, or IN[0] if provided
    system_name = FILTER_BY_SYSTEM_NAME
    if IN[0] and isinstance(IN[0], str) and IN[0].strip():
        system_name = str(IN[0]).strip()
    
    if system_name:
        ducts_to_resize = get_ducts_by_system_name(system_name)
        print(f"System '{system_name}': {len(ducts_to_resize)} ducts")
    else:
        print("ERROR: No system name provided. Set FILTER_BY_SYSTEM_NAME or connect system name to IN[0]")

elif DUCT_SELECTION_METHOD == "level":
    # IN[0] = Level element
    if input_elements and len(input_elements) > 0:
        level = input_elements[0]
        ducts_to_resize = get_ducts_by_level(level)
        level_name = level.Name if hasattr(level, "Name") else str(level.Id)
        print(f"Level '{level_name}': {len(ducts_to_resize)} ducts")
    else:
        print("ERROR: No level provided")

elif DUCT_SELECTION_METHOD == "all":
    # Get all ducts in project
    ducts_to_resize = get_all_ducts()
    print(f"All ducts in project: {len(ducts_to_resize)}")

else:
    print(f"ERROR: Unknown selection method '{DUCT_SELECTION_METHOD}'")

# Apply optional system name filter
if FILTER_BY_SYSTEM_NAME and ducts_to_resize:
    original_count = len(ducts_to_resize)
    ducts_to_resize = filter_ducts_by_system(ducts_to_resize, FILTER_BY_SYSTEM_NAME)
    print(
        f"Filtered by system '{FILTER_BY_SYSTEM_NAME}': {original_count} -> {len(ducts_to_resize)} ducts"
    )

all_results["ducts_processed"] = len(ducts_to_resize)

# Start transaction
TransactionManager.Instance.EnsureInTransaction(doc)

# Resize each duct
for duct in ducts_to_resize:
    if not duct:
        continue

    # Resize based on operating mode
    if OPERATING_MODE == "apartment":
        duct_result = resize_duct_apartment(duct, scale_factor)
    else:
        duct_result = resize_duct_commercial(duct, scale_factor)

    # Add system name to result
    duct_result["system"] = get_duct_system_name(duct)

    all_results["details"].append(duct_result)

    if duct_result["warning"]:
        all_results["warnings"].append(
            f"Duct {duct_result['id']}: {duct_result['warning']}"
        )
    else:
        all_results["ducts_resized"] += 1

    print(
        f"  Duct {duct_result['id']}: {duct_result['old_dims']} -> {duct_result['new_dims']} "
        f"({duct_result['duct_type']}, {duct_result['velocity_fpm']} FPM)"
    )

# Regenerate the document to update fittings
doc.Regenerate()

# Update air terminal (diffuser) CFM values
terminals_updated = []
if DUCT_SELECTION_METHOD == "system" and FILTER_BY_SYSTEM_NAME:
    # Get terminals from the system
    systems = FilteredElementCollector(doc).OfClass(MechanicalSystem).ToElements()
    for system in systems:
        if system.Name == FILTER_BY_SYSTEM_NAME or FILTER_BY_SYSTEM_NAME in system.Name:
            try:
                # Get all elements in the system
                system_elements = system.Elements
                if system_elements:
                    for elem in system_elements:
                        if hasattr(elem, "Category") and elem.Category:
                            if elem.Category.Id.IntegerValue == int(BuiltInCategory.OST_DuctTerminal):
                                # Update terminal CFM
                                flow_param = elem.get_Parameter(BuiltInParameter.RBS_DUCT_FLOW_PARAM)
                                if flow_param and not flow_param.IsReadOnly:
                                    current_cfm = flow_param.AsDouble() * 60
                                    new_cfm = current_cfm * scale_factor
                                    flow_param.Set(new_cfm / 60)  # Convert back to ft³/s
                                    terminals_updated.append({
                                        "id": str(elem.Id.IntegerValue),
                                        "old_cfm": round(current_cfm, 0),
                                        "new_cfm": round(new_cfm, 0)
                                    })
                                    print(f"  Terminal {elem.Id}: {current_cfm:.0f} CFM -> {new_cfm:.0f} CFM")
            except Exception as e:
                print(f"Error updating terminals in system {system.Name}: {e}")

# Also get terminals connected to the ducts we resized
if not terminals_updated:
    print("Searching for terminals connected to resized ducts...")
    terminal_ids_found = set()
    for duct in ducts_to_resize:
        try:
            connector_set = duct.ConnectorManager.Connectors
            for connector in connector_set:
                for ref in connector.AllRefs:
                    owner = ref.Owner
                    if hasattr(owner, "Category") and owner.Category:
                        if owner.Category.Id.IntegerValue == int(BuiltInCategory.OST_DuctTerminal):
                            if owner.Id.IntegerValue not in terminal_ids_found:
                                terminal_ids_found.add(owner.Id.IntegerValue)
                                flow_param = owner.get_Parameter(BuiltInParameter.RBS_DUCT_FLOW_PARAM)
                                if flow_param and not flow_param.IsReadOnly:
                                    current_cfm = flow_param.AsDouble() * 60
                                    new_cfm = current_cfm * scale_factor
                                    flow_param.Set(new_cfm / 60)
                                    terminals_updated.append({
                                        "id": str(owner.Id.IntegerValue),
                                        "old_cfm": round(current_cfm, 0),
                                        "new_cfm": round(new_cfm, 0)
                                    })
                                    print(f"  Terminal {owner.Id}: {current_cfm:.0f} CFM -> {new_cfm:.0f} CFM")
        except Exception as e:
            pass

all_results["terminals_updated"] = terminals_updated
print(f"\nTerminals updated: {len(terminals_updated)}")

# Update duct fittings (transitions, elbows, tees, etc.)
# =============================================================================
# IMPORTANT: Revit duct fittings get their dimensions from connected duct connectors.
# Transitions specifically connect two different duct sizes.
# 
# Strategy:
#   1. Identify all fittings connected to resized ducts
#   2. For TRANSITIONS: They should auto-update because one side connects to the 
#      resized duct and the other side to the unchanged duct
#   3. For ELBOWS/TEES: They need their connector sizes to match the duct
#   4. Use disconnect/reconnect pattern if auto-update doesn't work
# =============================================================================

fittings_updated = []
fittings_failed = []
fittings_info = []
fitting_ids_processed = set()
fittings_to_process = []

print("\nCollecting duct fittings...")

# Collect all fittings connected to our resized ducts
for duct in ducts_to_resize:
    try:
        connector_set = duct.ConnectorManager.Connectors
        for connector in connector_set:
            if connector.AllRefs:
                for ref in connector.AllRefs:
                    owner = ref.Owner
                    if owner and hasattr(owner, "Category") and owner.Category:
                        if owner.Category.Id.IntegerValue == int(BuiltInCategory.OST_DuctFitting):
                            if owner.Id.IntegerValue not in fitting_ids_processed:
                                fitting_ids_processed.add(owner.Id.IntegerValue)
                                fittings_to_process.append({
                                    "element": owner,
                                    "connected_duct": duct,
                                    "connector": connector
                                })
    except:
        pass

# Also get fittings from system's DuctNetwork
if DUCT_SELECTION_METHOD == "system" and FILTER_BY_SYSTEM_NAME:
    systems = FilteredElementCollector(doc).OfClass(MechanicalSystem).ToElements()
    for system in systems:
        if system.Name == FILTER_BY_SYSTEM_NAME or FILTER_BY_SYSTEM_NAME in system.Name:
            try:
                duct_network = system.DuctNetwork
                if duct_network:
                    for item in duct_network:
                        if hasattr(item, "IntegerValue"):
                            element = doc.GetElement(item)
                        else:
                            element = item
                        
                        if element and hasattr(element, "Category") and element.Category:
                            if element.Category.Id.IntegerValue == int(BuiltInCategory.OST_DuctFitting):
                                if element.Id.IntegerValue not in fitting_ids_processed:
                                    fitting_ids_processed.add(element.Id.IntegerValue)
                                    fittings_to_process.append({
                                        "element": element,
                                        "connected_duct": None,
                                        "connector": None
                                    })
            except:
                pass

print(f"Found {len(fittings_to_process)} fittings connected to resized ducts")
print(f"Fitting update mode: {FITTING_UPDATE_MODE}")

# First, regenerate to let Revit try to auto-update fittings
doc.Regenerate()

# If delete_and_recreate mode, delete fittings and create new ones
fittings_deleted = []
fittings_recreated = []
fittings_skipped = []

if FITTING_UPDATE_MODE == "delete_and_recreate":
    print("\nProcessing fittings for recreation...")
    
    # First, collect connector info BEFORE deleting fittings
    fittings_to_recreate = []
    
    for fit_data in fittings_to_process:
        fitting = fit_data["element"]
        fitting_id = str(fitting.Id.IntegerValue)
        
        try:
            # Get fitting info
            fitting_type = doc.GetElement(fitting.GetTypeId())
            family_name = fitting_type.FamilyName if fitting_type and hasattr(fitting_type, "FamilyName") else "Unknown"
            type_id = fitting.GetTypeId()
            
            # Determine if it's a transition (connects two different duct sizes)
            is_transition = "transition" in family_name.lower() or "reducer" in family_name.lower()
            
            # Get connectors and connected ducts
            connected_ducts_info = []
            if hasattr(fitting, "MEPModel") and fitting.MEPModel:
                conn_mgr = fitting.MEPModel.ConnectorManager
                if conn_mgr and conn_mgr.Connectors:
                    for conn in conn_mgr.Connectors:
                        try:
                            if conn.IsConnected and conn.AllRefs:
                                for ref in conn.AllRefs:
                                    owner = ref.Owner
                                    if owner and hasattr(owner, "Category") and owner.Category:
                                        if owner.Category.Id.IntegerValue == int(BuiltInCategory.OST_DuctCurves):
                                            # Store the duct ID and which connector it connects to
                                            connected_ducts_info.append({
                                                "duct_id": owner.Id,
                                                "connection_point": conn.Origin,
                                                "width": conn.Width if hasattr(conn, "Width") else 0,
                                                "height": conn.Height if hasattr(conn, "Height") else 0
                                            })
                        except:
                            pass
            
            fittings_to_recreate.append({
                "fitting_id": fitting.Id,
                "fitting_id_str": fitting_id,
                "family_name": family_name,
                "type_id": type_id,
                "is_transition": is_transition,
                "connected_ducts": connected_ducts_info,
                "can_recreate": is_transition and len(connected_ducts_info) >= 2
            })
            
        except Exception as e:
            print(f"  Error collecting info for fitting {fitting_id}: {e}")
    
    # Now delete fittings and try to recreate them
    for fit_info in fittings_to_recreate:
        fitting_id_str = fit_info["fitting_id_str"]
        family_name = fit_info["family_name"]

        if not fit_info.get("can_recreate", False):
            fittings_skipped.append({
                "id": fitting_id_str,
                "family": family_name,
                "status": "skipped",
                "reason": "auto recreation not supported"
            })
            print(
                f"  Skipping delete for fitting {fitting_id_str} ({family_name}) - "
                "requires manual handling"
            )
            continue

        try:
            # Delete the fitting
            doc.Delete(fit_info["fitting_id"])
            fittings_deleted.append({
                "id": fitting_id_str,
                "family": family_name,
                "status": "deleted"
            })
            print(f"  Deleted fitting {fitting_id_str} ({family_name})")
            
        except Exception as e:
            print(f"  Failed to delete fitting {fitting_id_str}: {e}")
    
    # Regenerate after deletions
    doc.Regenerate()
    
    # Now try to create new fittings by connecting the ducts
    print("\nRecreating fittings...")
    
    for fit_info in fittings_to_recreate:
        if not fit_info.get("can_recreate", False):
            continue

        if len(fit_info["connected_ducts"]) >= 2 and fit_info["is_transition"]:
            try:
                # Get the two ducts that were connected
                duct1_id = fit_info["connected_ducts"][0]["duct_id"]
                duct2_id = fit_info["connected_ducts"][1]["duct_id"]
                
                duct1 = doc.GetElement(duct1_id)
                duct2 = doc.GetElement(duct2_id)
                
                if duct1 and duct2:
                    # Find the open connectors on each duct
                    conn1 = None
                    conn2 = None
                    
                    for conn in duct1.ConnectorManager.Connectors:
                        if not conn.IsConnected:
                            conn1 = conn
                            break
                    
                    for conn in duct2.ConnectorManager.Connectors:
                        if not conn.IsConnected:
                            conn2 = conn
                            break
                    
                    if conn1 and conn2:
                        # Create a new transition fitting between the two connectors
                        try:
                            new_fitting = doc.Create.NewTransitionFitting(conn1, conn2)
                            if new_fitting:
                                fittings_recreated.append({
                                    "old_id": fit_info["fitting_id_str"],
                                    "new_id": str(new_fitting.Id.IntegerValue),
                                    "family": fit_info["family_name"],
                                    "status": "recreated"
                                })
                                print(f"  Created new transition between ducts {duct1_id.IntegerValue} and {duct2_id.IntegerValue}")
                        except Exception as e:
                            # Try alternative method - NewElbowFitting or NewTeeFitting might work
                            print(f"  Could not create transition automatically: {e}")
                            fittings_recreated.append({
                                "old_id": fit_info["fitting_id_str"],
                                "new_id": "manual",
                                "family": fit_info["family_name"],
                                "status": "needs_manual_creation"
                            })
                    else:
                        print(f"  Could not find open connectors for fitting {fit_info['fitting_id_str']}")
                        fittings_recreated.append({
                            "old_id": fit_info["fitting_id_str"],
                            "new_id": "manual",
                            "family": fit_info["family_name"],
                            "status": "needs_manual_creation"
                        })
                        
            except Exception as e:
                print(f"  Error recreating fitting {fit_info['fitting_id_str']}: {e}")
                fittings_recreated.append({
                    "old_id": fit_info["fitting_id_str"],
                    "new_id": "error",
                    "family": fit_info["family_name"],
                    "status": f"error: {e}"
                })
        else:
            # For non-transitions (elbows, tees), try to connect open connectors
            if len(fit_info["connected_ducts"]) >= 1:
                try:
                    duct1_id = fit_info["connected_ducts"][0]["duct_id"]
                    duct1 = doc.GetElement(duct1_id)
                    
                    if duct1 and len(fit_info["connected_ducts"]) >= 2:
                        duct2_id = fit_info["connected_ducts"][1]["duct_id"]
                        duct2 = doc.GetElement(duct2_id)
                        
                        # Find open connectors
                        conn1 = None
                        conn2 = None
                        
                        for conn in duct1.ConnectorManager.Connectors:
                            if not conn.IsConnected:
                                conn1 = conn
                                break
                        
                        if duct2:
                            for conn in duct2.ConnectorManager.Connectors:
                                if not conn.IsConnected:
                                    conn2 = conn
                                    break
                        
                        if conn1 and conn2:
                            try:
                                # Try to create elbow fitting
                                new_fitting = doc.Create.NewElbowFitting(conn1, conn2)
                                if new_fitting:
                                    fittings_recreated.append({
                                        "old_id": fit_info["fitting_id_str"],
                                        "new_id": str(new_fitting.Id.IntegerValue),
                                        "family": fit_info["family_name"],
                                        "status": "recreated"
                                    })
                                    print(f"  Created new elbow between ducts")
                            except:
                                # Try transition as fallback
                                try:
                                    new_fitting = doc.Create.NewTransitionFitting(conn1, conn2)
                                    if new_fitting:
                                        fittings_recreated.append({
                                            "old_id": fit_info["fitting_id_str"],
                                            "new_id": str(new_fitting.Id.IntegerValue),
                                            "family": fit_info["family_name"],
                                            "status": "recreated"
                                        })
                                        print(f"  Created new fitting between ducts")
                                except Exception as e:
                                    print(f"  Could not auto-create fitting: {e}")
                                    fittings_recreated.append({
                                        "old_id": fit_info["fitting_id_str"],
                                        "new_id": "manual",
                                        "family": fit_info["family_name"],
                                        "status": "needs_manual_creation"
                                    })
                except Exception as e:
                    print(f"  Error handling fitting {fit_info['fitting_id_str']}: {e}")
    
    doc.Regenerate()
    
    print(f"\nDeleted {len(fittings_deleted)} fittings")
    recreated_count = len([f for f in fittings_recreated if f["status"] == "recreated"])
    manual_count = len([f for f in fittings_recreated if f["status"] == "needs_manual_creation"])
    print(f"Recreated {recreated_count} fittings automatically")
    if manual_count > 0:
        print(f"Fittings needing manual recreation: {manual_count}")
        print("  -> Select the open duct ends and use 'Duct Fitting' tool to add transitions")
    
    all_results["fittings_deleted"] = fittings_deleted
    all_results["fittings_recreated"] = fittings_recreated
    all_results["fittings_skipped"] = fittings_skipped
    all_results["fittings_updated"] = [f["new_id"] for f in fittings_recreated if f["status"] == "recreated"]
    all_results["fittings_info"] = []
    all_results["fittings_need_attention"] = [
        {"id": f["old_id"], "family": f["family"], "error": "Needs manual fitting creation"} 
        for f in fittings_recreated if f["status"] == "needs_manual_creation"
    ] + [
        {"id": f["id"], "family": f.get("family", ""), "error": f.get("reason", "Skipped automatic recreation")}
        for f in fittings_skipped
    ]

elif FITTING_UPDATE_MODE == "report_only":
    print("\nReporting fittings (no changes)...")
    for fit_data in fittings_to_process:
        fitting = fit_data["element"]
        fitting_id = str(fitting.Id.IntegerValue)
        
        fitting_type = doc.GetElement(fitting.GetTypeId())
        family_name = fitting_type.FamilyName if fitting_type and hasattr(fitting_type, "FamilyName") else "Unknown"
        
        # Get connector sizes
        conn_sizes = []
        if hasattr(fitting, "MEPModel") and fitting.MEPModel:
            conn_mgr = fitting.MEPModel.ConnectorManager
            if conn_mgr and conn_mgr.Connectors:
                for conn in conn_mgr.Connectors:
                    try:
                        if hasattr(conn, "Width") and hasattr(conn, "Height"):
                            w = conn.Width * FEET_TO_INCHES
                            h = conn.Height * FEET_TO_INCHES
                            conn_sizes.append(f"{w:.0f}x{h:.0f}")
                    except:
                        pass
        
        fittings_info.append({
            "id": fitting_id,
            "family": family_name,
            "connector_sizes": conn_sizes,
            "status": "reported"
        })
        print(f"  Fitting {fitting_id} ({family_name}): {conn_sizes}")
    
    all_results["fittings_updated"] = []
    all_results["fittings_info"] = fittings_info
    all_results["fittings_need_attention"] = [{
        "id": f["id"],
        "family": f["family"],
        "error": "Manual update needed - delete and recreate"
    } for f in fittings_info]

else:
    # try_update mode - attempt to update fitting parameters
    # Process each fitting
    for fit_data in fittings_to_process:
        fitting = fit_data["element"]
        fitting_id = str(fitting.Id.IntegerValue)
        
        try:
            # Get fitting type info
            fitting_type = doc.GetElement(fitting.GetTypeId())
            family_name = ""
            type_name = ""
            if fitting_type:
                family_name = fitting_type.FamilyName if hasattr(fitting_type, "FamilyName") else ""
                type_name = Element.Name.GetValue(fitting_type) if hasattr(fitting_type, "Name") else ""
            
            # Determine fitting type (transition, elbow, tee, etc.)
            is_transition = "transition" in family_name.lower() or "reducer" in family_name.lower()
            is_elbow = "elbow" in family_name.lower() or "bend" in family_name.lower()
            is_tee = "tee" in family_name.lower() or "wye" in family_name.lower()
            
            fitting_info = {
                "id": fitting_id,
                "family": family_name,
                "type": type_name,
                "is_transition": is_transition,
                "connector_sizes": [],
                "status": "pending"
            }
            
            # Get all connectors on the fitting
            if hasattr(fitting, "MEPModel") and fitting.MEPModel:
                connector_mgr = fitting.MEPModel.ConnectorManager
                if connector_mgr and connector_mgr.Connectors:
                    for conn in connector_mgr.Connectors:
                        try:
                            if hasattr(conn, "Width") and hasattr(conn, "Height"):
                                w = conn.Width * FEET_TO_INCHES
                                h = conn.Height * FEET_TO_INCHES
                                fitting_info["connector_sizes"].append(f"{w:.0f}x{h:.0f}")
                        except:
                            pass
            
            # For transitions - they should auto-update based on connected ducts
            # The transition connects two different sizes, so after duct resize,
            # one end should still match the old size (if connected to non-resized duct)
            # and one end should match the new size (connected to resized duct)
            
            if is_transition:
                # Check if the fitting's connectors match the expected sizes
                # After resize, we expect the transition to connect the old and new sizes
                print(f"  Transition {fitting_id}: Connectors {fitting_info['connector_sizes']}")
                
                # Try to disconnect and reconnect to force size update
                try:
                    # Get the fitting's connectors
                    if hasattr(fitting, "MEPModel") and fitting.MEPModel:
                        conn_mgr = fitting.MEPModel.ConnectorManager
                        if conn_mgr:
                            for conn in conn_mgr.Connectors:
                                if conn.IsConnected:
                                    # Get connected element
                                    for ref in conn.AllRefs:
                                        connected_elem = ref.Owner
                                        if connected_elem:
                                            # Get the connected duct's size
                                            if connected_elem.Category.Id.IntegerValue == int(BuiltInCategory.OST_DuctCurves):
                                                duct_w_param = connected_elem.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
                                                if duct_w_param:
                                                    duct_w = duct_w_param.AsDouble() * FEET_TO_INCHES
                                                    conn_w = conn.Width * FEET_TO_INCHES if hasattr(conn, "Width") else 0
                                                    
                                                    # If connector size doesn't match duct size, there's a mismatch
                                                    if abs(duct_w - conn_w) > 0.1:
                                                        print(f"    Connector mismatch: fitting={conn_w:.0f}, duct={duct_w:.0f}")
                                                        # The fitting needs to be replaced or reconnected
                                                        fitting_info["status"] = "needs_reconnect"
                                                    else:
                                                        fitting_info["status"] = "matched"
                except Exception as e:
                    print(f"    Error checking transition: {e}")
            
            # For elbows and tees - all connectors should have the same size as connected ducts
            elif is_elbow or is_tee:
                print(f"  {('Elbow' if is_elbow else 'Tee')} {fitting_id}: Connectors {fitting_info['connector_sizes']}")
                fitting_info["status"] = "check_manually"
            
            else:
                print(f"  Fitting {fitting_id} ({family_name}): Connectors {fitting_info['connector_sizes']}")
                fitting_info["status"] = "unknown_type"
            
            # Determine final status
            if fitting_info["status"] in ["matched", "auto-adjust"]:
                fittings_updated.append(fitting_id)
            elif fitting_info["status"] == "needs_reconnect":
                fittings_failed.append({
                    "id": fitting_id,
                    "family": family_name,
                    "error": "Connector size mismatch - delete and recreate fitting, or use 'Justify' tool"
                })
            else:
                # Check if the fitting has editable parameters
                param_updated = False
                
                # Try common dimension parameters
                for param_name in ["Width 1", "Width 2", "Height 1", "Height 2", "Nominal Width", "Nominal Height"]:
                    try:
                        param = fitting.LookupParameter(param_name)
                        if param and not param.IsReadOnly and param.StorageType == StorageType.Double:
                            old_val = param.AsDouble() * FEET_TO_INCHES
                            if old_val > 0:
                                # Only scale width parameters in apartment mode
                                if "Width" in param_name:
                                    new_val = round_to_standard(old_val * scale_factor)
                                    param.Set(new_val * INCHES_TO_FEET)
                                    param_updated = True
                                    print(f"    Updated {param_name}: {old_val:.0f} -> {new_val:.0f}")
                    except:
                        pass
                
                if param_updated:
                    fitting_info["status"] = "updated"
                    fittings_updated.append(fitting_id)
                else:
                    fittings_failed.append({
                        "id": fitting_id,
                        "family": family_name,
                        "error": "No editable dimension parameters found"
                    })
            
            fittings_info.append(fitting_info)
            
        except Exception as e:
            fittings_failed.append({
                "id": fitting_id,
                "family": "",
                "error": str(e)
            })
            print(f"  Fitting {fitting_id}: Error - {e}")
    
    # Set results for try_update mode
    all_results["fittings_updated"] = fittings_updated
    all_results["fittings_info"] = fittings_info
    all_results["fittings_need_attention"] = fittings_failed

# Force regeneration to apply all changes
print("\nRegenerating document...")
doc.Regenerate()

print(f"\nFittings processed: {len(fittings_to_process)}")
print(f"Fittings updated/matched: {len(all_results.get('fittings_updated', []))}")
print(f"Fittings needing attention: {len(all_results.get('fittings_need_attention', []))}")

if all_results.get("fittings_need_attention"):
    print("\n" + "-" * 50)
    print("FITTINGS REQUIRING MANUAL ACTION:")
    print("-" * 50)
    print("The following fittings could not be auto-resized.")
    print("For each fitting, you can:")
    print("  1. SELECT the fitting -> DELETE -> Route ducts to auto-create new fitting")
    print("  2. Or use the 'Justify' tool to reconnect")
    print("  3. Or manually edit fitting dimensions if family supports it")
    print("")
    for f in all_results["fittings_need_attention"][:10]:  # Show first 10
        print(f"  - ID {f['id']}: {f.get('family', '')} - {f['error']}")
    if len(all_results["fittings_need_attention"]) > 10:
        print(f"  ... and {len(all_results['fittings_need_attention']) - 10} more")
    print("-" * 50)

# Final regeneration to update all geometry
doc.Regenerate()

# Complete transaction
TransactionManager.Instance.TransactionTaskDone()

# Summary output
print("\n" + "=" * 50)
print("RESIZE SUMMARY")
print("=" * 50)
print(f"Selection method: {DUCT_SELECTION_METHOD}")
print(f"Operating mode: {OPERATING_MODE}")
print(f"Fitting update mode: {FITTING_UPDATE_MODE}")
print(f"CFM change: {OLD_CFM} -> {NEW_CFM} (scale: {scale_factor:.3f})")
print(f"Ducts processed: {all_results['ducts_processed']}")
print(f"Ducts resized successfully: {all_results['ducts_resized']}")
print(f"Terminals updated: {len(terminals_updated)}")
print(f"Fittings processed: {len(fittings_to_process)}")

if FITTING_UPDATE_MODE == "delete_and_recreate":
    print(f"Fittings deleted: {len(all_results.get('fittings_deleted', []))}")
    recreated = all_results.get('fittings_recreated', [])
    auto_created = len([f for f in recreated if f.get('status') == 'recreated'])
    manual_needed = len([f for f in recreated if f.get('status') == 'needs_manual_creation'])
    skipped = len(all_results.get('fittings_skipped', []))
    print(f"Fittings auto-recreated: {auto_created}")
    if manual_needed > 0:
        print(f"Fittings needing manual creation: {manual_needed}")
        print("  -> Select open duct ends and use 'Duct Fitting' tool")
    if skipped > 0:
        print(f"Fittings skipped (left as-is): {skipped}")
else:
    print(f"Fittings updated: {len(all_results.get('fittings_updated', []))}")
    print(f"Fittings needing attention: {len(all_results.get('fittings_need_attention', []))}")

print(f"Warnings: {len(all_results['warnings'])}")

if all_results.get("fittings_need_attention"):
    print("\nFITTINGS NEEDING MANUAL ADJUSTMENT:")
    for fitting in all_results["fittings_need_attention"][:5]:
        print(f"  - Fitting {fitting['id']}: {fitting.get('family', '')} - {fitting['error']}")
    if len(all_results["fittings_need_attention"]) > 5:
        print(f"  ... and {len(all_results['fittings_need_attention']) - 5} more")

if all_results["warnings"]:
    print("\nWARNINGS:")
    for warning in all_results["warnings"][:5]:
        print(f"  - {warning}")
    if len(all_results["warnings"]) > 5:
        print(f"  ... and {len(all_results['warnings']) - 5} more")

# Output for Dynamo
OUT = all_results
