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
DUCT_SELECTION_METHOD = "direct"

# CFM Source Method: "terminals", "equipment_param", "user_input"
CFM_SOURCE_METHOD = "user_input"

# User-provided values (used when CFM_SOURCE_METHOD = "user_input")
OLD_CFM = 1200  # Previous equipment capacity
NEW_CFM = 1500  # New equipment capacity

# Equipment parameter name for CFM (used when CFM_SOURCE_METHOD = "equipment_param")
EQUIPMENT_CFM_PARAM = "Airflow"

# Filter by system name (optional, works with any selection method)
# Set to None or "" to disable filtering
FILTER_BY_SYSTEM_NAME = None  # e.g., "Supply Air 1"

# Operating Mode: "commercial" or "apartment"
OPERATING_MODE = "apartment"

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
        if system and hasattr(system, "DuctNetwork"):
            for element_id in system.DuctNetwork:
                element = doc.GetElement(element_id)
                if element and element.Category.Id.IntegerValue == int(
                    BuiltInCategory.OST_DuctCurves
                ):
                    connected_ducts.append(element)

    return connected_ducts


def get_ducts_by_system_name(system_name):
    """Get all ducts belonging to a named mechanical system."""
    ducts = []

    # Get all mechanical systems
    systems = FilteredElementCollector(doc).OfClass(MechanicalSystem).ToElements()

    for system in systems:
        if system.Name == system_name or system_name in system.Name:
            if hasattr(system, "DuctNetwork"):
                for element_id in system.DuctNetwork:
                    element = doc.GetElement(element_id)
                    if element and element.Category.Id.IntegerValue == int(
                        BuiltInCategory.OST_DuctCurves
                    ):
                        ducts.append(element)

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

    result["old_dims"] = f'{width_in:.0f}×{height_in:.0f}"'

    # Get current flow and scale it
    current_cfm = flow_param.AsDouble() * 60 if flow_param else 0
    new_cfm = current_cfm * scale_factor

    # Determine duct type and velocity limit
    duct_type = get_duct_type(duct)
    result["duct_type"] = duct_type
    max_velocity = get_velocity_limit(duct_type, "commercial")

    # Calculate required area
    required_area = calculate_required_area(new_cfm, max_velocity)

    # Calculate new dimensions maintaining aspect ratio
    current_ratio = width_in / height_in if height_in > 0 else 1
    new_height = (required_area / current_ratio) ** 0.5
    new_width = new_height * current_ratio

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

    result["old_dims"] = f'{current_width_in:.0f}×{height_in:.0f}"'

    # Get current flow and scale it
    current_cfm = flow_param.AsDouble() * 60 if flow_param else 0
    new_cfm = current_cfm * scale_factor

    # Determine duct type and velocity limit
    duct_type = get_duct_type(duct)
    result["duct_type"] = duct_type
    max_velocity = get_velocity_limit(duct_type, "apartment")

    # Calculate required area and new width (height locked)
    required_area = calculate_required_area(new_cfm, max_velocity)
    new_width_in = calculate_width_for_height(required_area, height_in)

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
input_elements = UnwrapElement(IN[0]) if IN[0] else []

# Ensure it's a list for direct/equipment methods
if not isinstance(input_elements, list):
    input_elements = [input_elements]

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
        if elem and elem.Category.Id.IntegerValue == int(
            BuiltInCategory.OST_DuctCurves
        ):
            ducts_to_resize.append(elem)
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
    # IN[0] = System name string
    system_name = str(IN[0]) if IN[0] else ""
    if system_name:
        ducts_to_resize = get_ducts_by_system_name(system_name)
        print(f"System '{system_name}': {len(ducts_to_resize)} ducts")
    else:
        print("ERROR: No system name provided")

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

# Complete transaction
TransactionManager.Instance.TransactionTaskDone()

# Summary output
print("\n" + "=" * 50)
print("RESIZE SUMMARY")
print("=" * 50)
print(f"Selection method: {DUCT_SELECTION_METHOD}")
print(f"Operating mode: {OPERATING_MODE}")
print(f"CFM change: {OLD_CFM} -> {NEW_CFM} (scale: {scale_factor:.3f})")
print(f"Ducts processed: {all_results['ducts_processed']}")
print(f"Ducts resized successfully: {all_results['ducts_resized']}")
print(f"Warnings: {len(all_results['warnings'])}")

if all_results["warnings"]:
    print("\nWARNINGS:")
    for warning in all_results["warnings"]:
        print(f"  - {warning}")

# Output for Dynamo
OUT = all_results
