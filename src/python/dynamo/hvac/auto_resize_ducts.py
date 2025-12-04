"""
Auto-Resize Ducts on Equipment Capacity Change
===============================================
This Dynamo script automatically resizes ducts when HVAC equipment capacity changes.
It recalculates duct dimensions based on the new CFM requirements using either:
  - Velocity Method: Maintains velocity within specified limits
  - Equal Friction Method: Maintains constant pressure drop per unit length

Duct Selection:
        - Provide a system name (FILTER_BY_SYSTEM_NAME or IN[0]) and the script
            processes only ducts in that mechanical system.

Sizing Methods:
    - "velocity":       Size ducts based on maximum velocity limits (FPM)
    - "equal_friction": Size ducts based on friction rate (in. w.g. per 100 ft)

Usage:
    1. Provide the target system name via FILTER_BY_SYSTEM_NAME (or a string in IN[0])
    2. Set SIZING_METHOD to "velocity" or "equal_friction"
    3. Provide the old and new CFM values
    4. Run the script

Apartment Mode:
    - Locks duct height (ceiling constraint)
    - Only adjusts width to accommodate new airflow
    - Uses lower velocity limits for residential noise control
"""

import clr
import math

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


# User-provided values
OLD_CFM = 400  # Previous equipment capacity
NEW_CFM = 600  # New equipment capacity

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

# Sizing Method: "velocity" or "equal_friction"
#   - "velocity":       Size ducts based on maximum velocity limits (traditional method)
#   - "equal_friction": Size ducts based on constant friction rate (pressure drop method)
SIZING_METHOD = "equal_friction"

# =============================================================================
# EQUAL FRICTION METHOD SETTINGS
# =============================================================================

# Target friction rate in inches of water gauge per 100 feet of duct
# Typical values:
#   - Low velocity systems: 0.05 - 0.08 in. w.g./100 ft
#   - Medium velocity systems: 0.08 - 0.15 in. w.g./100 ft  
#   - High velocity systems: 0.15 - 0.40 in. w.g./100 ft
# Residential typically uses 0.08, commercial 0.08-0.10
FRICTION_RATE = {
    "commercial": 0.10,  # in. w.g. per 100 ft
    "apartment": 0.08,   # in. w.g. per 100 ft (lower for noise control)
}

# Maximum velocity limits (used as upper bound even in equal friction method)
# These prevent excessive noise even if friction allows higher velocity
MAX_VELOCITY_LIMIT = {
    "commercial": 2500,  # FPM absolute max
    "apartment": 700,    # FPM absolute max for residential
}

# In equal friction mode, should velocity be enforced as a hard limit?
#   - True:  Size duct larger if needed to meet BOTH friction AND velocity limits
#   - False: Size based on friction only, warn if velocity exceeds limit
# Set to False to match typical ductulator behavior (friction-only sizing)
ENFORCE_VELOCITY_IN_EQUAL_FRICTION = False

# Air properties (standard conditions at 70°F, sea level)
AIR_DENSITY = 0.075  # lb/ft³

# Duct roughness factor for galvanized steel
# Absolute roughness in feet (0.0003 ft = 0.0036 inches for galvanized)
DUCT_ROUGHNESS = 0.0003  # feet

# =============================================================================
# VELOCITY METHOD SETTINGS
# =============================================================================

# Velocity limits in FPM (Feet Per Minute)
VELOCITY_LIMITS = {
    "commercial": {"trunk": 1500, "branch": 1200, "runout": 800},
    "apartment": {"trunk": 700, "branch": 600, "runout": 500},
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
    """Calculate air velocity in FPM for rectangular duct."""
    area_ft2 = (width_in / 12) * (height_in / 12)
    if area_ft2 <= 0:
        return 0
    return cfm / area_ft2


def calculate_equiv_round_velocity(cfm, equiv_diameter_in):
    """
    Calculate air velocity through equivalent round duct.
    Some ductulating software displays this velocity instead of the rectangular duct velocity.
    
    Args:
        cfm: Airflow in CFM
        equiv_diameter_in: Equivalent diameter in inches
    
    Returns:
        Velocity in FPM through the equivalent round duct
    """
    if cfm <= 0 or equiv_diameter_in <= 0:
        return 0
    # Area of round duct = π * (D/2)² with D in inches, converted to ft²
    area_ft2 = math.pi * (equiv_diameter_in / 24) ** 2  # /24 = /2 for radius, /12 for feet
    return cfm / area_ft2


# =============================================================================
# EQUAL FRICTION METHOD HELPER FUNCTIONS
# =============================================================================


def calculate_equivalent_diameter(width_in, height_in):
    """
    Calculate the equivalent circular diameter for a rectangular duct.
    
    Uses the Huebscher equation:
    De = 1.30 * (a*b)^0.625 / (a+b)^0.25
    
    Where:
        a = width (inches)
        b = height (inches)
        De = equivalent diameter (inches)
    
    This gives the diameter of a round duct with the same friction loss
    per unit length at the same airflow rate.
    """
    if width_in <= 0 or height_in <= 0:
        return 0
    
    # Huebscher equation for equivalent diameter
    numerator = (width_in * height_in) ** 0.625
    denominator = (width_in + height_in) ** 0.25
    de = 1.30 * numerator / denominator
    
    return de


def calculate_friction_rate(cfm, diameter_in):
    """
    Calculate friction rate (pressure drop per 100 ft) for a given CFM and duct diameter.
    
    Uses the simplified Darcy-Weisbach equation for air in ducts:
    ΔP/100ft = 0.109136 * Q^1.9 / D^5.02
    
    Where:
        Q = airflow in CFM
        D = duct diameter in inches
        ΔP = pressure drop in inches of water gauge per 100 ft
    
    This is an approximation valid for standard air conditions and
    typical duct roughness (galvanized steel).
    """
    if cfm <= 0 or diameter_in <= 0:
        return 0
    
    # Simplified friction equation for air in ducts
    # This empirical formula is widely used in HVAC industry
    friction = 0.109136 * (cfm ** 1.9) / (diameter_in ** 5.02)
    
    return friction


def calculate_diameter_for_friction(cfm, target_friction_rate):
    """
    Calculate required duct diameter for a given CFM and target friction rate.
    
    Rearranging the friction equation:
    D = (0.109136 * Q^1.9 / ΔP)^(1/5.02)
    
    Args:
        cfm: Airflow in cubic feet per minute
        target_friction_rate: Target pressure drop in in. w.g. per 100 ft
    
    Returns:
        Required equivalent diameter in inches
    """
    if cfm <= 0 or target_friction_rate <= 0:
        return 0
    
    # Solve for diameter
    diameter = (0.109136 * (cfm ** 1.9) / target_friction_rate) ** (1 / 5.02)
    
    return diameter


def find_width_for_friction(cfm, height_in, target_friction, tolerance=1.02, min_width=MIN_DUCT_WIDTH, max_width=120):
    """
    Find the smallest standard width that achieves the target friction rate or better.
    
    Args:
        cfm: Airflow in CFM
        height_in: Fixed duct height in inches
        target_friction: Target friction rate in in.wg/100ft
        tolerance: Acceptable friction tolerance (1.02 = up to 2% over target is OK)
        min_width: Minimum width to consider
        max_width: Maximum width to consider
    
    Returns:
        Width in inches (standard 2" increment) that achieves acceptable friction
    """
    if cfm <= 0 or height_in <= 0 or target_friction <= 0:
        return min_width
    
    # Iterate through standard widths (2" increments)
    for w in range(int(min_width), int(max_width) + 1, STANDARD_SIZE_INCREMENT):
        de = calculate_equivalent_diameter(w, height_in)
        friction = calculate_friction_rate(cfm, de)
        # Accept if friction is at or below target (with small tolerance)
        if friction <= target_friction * tolerance:
            return w
    
    # If we couldn't find one, return the max width
    return max_width


def find_width_for_equiv_diameter(target_de, height_in, min_width=MIN_DUCT_WIDTH, max_width=120):
    """
    Find the width needed to achieve a target equivalent diameter with a fixed height.
    Uses direct iteration over standard duct widths.
    
    Args:
        target_de: Target equivalent diameter in inches
        height_in: Fixed duct height in inches
        min_width: Minimum width to consider
        max_width: Maximum width to consider
    
    Returns:
        Width in inches that achieves or exceeds the target De
    """
    if target_de <= 0 or height_in <= 0:
        return min_width
    
    # Start from minimum and find first width that meets or exceeds target De
    for w in range(int(min_width), int(max_width) + 1):
        de = calculate_equivalent_diameter(w, height_in)
        if de >= target_de:
            return w
    
    # If we couldn't find one, return the max width
    return max_width


def calculate_rectangular_dims_for_diameter(equiv_diameter_in, fixed_height_in=None, aspect_ratio_max=4.0):
    """
    Calculate rectangular duct dimensions for a given equivalent diameter.
    
    If fixed_height is provided (apartment mode), calculates width to achieve
    the equivalent diameter. Otherwise, optimizes for reasonable aspect ratio.
    
    Args:
        equiv_diameter_in: Required equivalent diameter in inches
        fixed_height_in: If set, height is locked (apartment mode)
        aspect_ratio_max: Maximum allowed aspect ratio (default 4:1)
    
    Returns:
        tuple: (width_in, height_in)
    """
    if equiv_diameter_in <= 0:
        return (MIN_DUCT_WIDTH, MIN_DUCT_HEIGHT)
    
    if fixed_height_in and fixed_height_in > 0:
        # Apartment mode: height is locked, find width to achieve target De
        # Use direct iteration for accurate results
        width = find_width_for_equiv_diameter(equiv_diameter_in, fixed_height_in)
        
        # Ensure minimum
        width = max(MIN_DUCT_WIDTH, width)
        
        # CRITICAL: Enforce aspect ratio limit
        # If width would create excessive aspect ratio, cap it
        max_width = fixed_height_in * aspect_ratio_max
        if width > max_width:
            width = max_width
        
        return (width, fixed_height_in)
    
    else:
        # Commercial mode: optimize both dimensions
        # Start with square duct approximation derived from Huebscher equation
        # De = 1.093 * side  =>  side = De / 1.093
        side = equiv_diameter_in / 1.093
        
        # Round to standard sizes
        width = round_to_standard(side)
        height = round_to_standard(side)
        
        # Ensure minimum sizes
        width = max(MIN_DUCT_WIDTH, width)
        height = max(MIN_DUCT_HEIGHT, height)
        
        # Verify equivalent diameter is close
        actual_de = calculate_equivalent_diameter(width, height)
        
        # If we need more capacity, increase dimensions
        # Use a tighter tolerance (99%) to ensure we meet the friction requirement
        while actual_de < equiv_diameter_in * 0.99:
            # Increase the smaller dimension to maintain aspect ratio
            if width <= height:
                width += STANDARD_SIZE_INCREMENT
            else:
                height += STANDARD_SIZE_INCREMENT
            actual_de = calculate_equivalent_diameter(width, height)
            
            # Enforce aspect ratio limit
            aspect = max(width, height) / min(width, height) if min(width, height) > 0 else 1
            if aspect > aspect_ratio_max:
                # Increase the smaller dimension
                if width < height:
                    width += STANDARD_SIZE_INCREMENT
                else:
                    height += STANDARD_SIZE_INCREMENT
            
            # Prevent infinite loop
            if width > 60 or height > 60:
                break
        
        return (width, height)


def calculate_pressure_drop(cfm, width_in, height_in, length_ft=100):
    """
    Calculate total pressure drop for a duct section.
    
    Args:
        cfm: Airflow in CFM
        width_in: Duct width in inches
        height_in: Duct height in inches
        length_ft: Duct length in feet (default 100 for friction rate)
    
    Returns:
        Pressure drop in inches of water gauge
    """
    equiv_dia = calculate_equivalent_diameter(width_in, height_in)
    if equiv_dia <= 0:
        return 0
    
    friction_per_100ft = calculate_friction_rate(cfm, equiv_dia)
    total_drop = friction_per_100ft * (length_ft / 100)
    
    return total_drop


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
        return flow_param.AsDouble()
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

    # Use constant CFM values supplied by user
    current_cfm = OLD_CFM
    new_cfm = NEW_CFM

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

    # Use constant CFM values supplied by user
    current_cfm = OLD_CFM
    new_cfm = NEW_CFM
    
    # Store CFM values for debugging
    result["current_cfm"] = round(current_cfm, 0)
    result["new_cfm"] = round(new_cfm, 0)

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

    # Calculate resulting velocity
    velocity = calculate_velocity(new_cfm, new_width_in, height_in)
    
    # Check velocity limits and try to fix if exceeded
    if velocity > max_velocity:
        # Calculate required width for acceptable velocity
        required_area_ft2 = new_cfm / max_velocity
        required_width = (required_area_ft2 * 144) / height_in
        
        # Check if achievable with 4:1 aspect ratio
        max_width_for_aspect = height_in * 4.0
        
        if required_width > max_width_for_aspect:
            # Cannot achieve target velocity - duct height too small
            new_width_in = round_to_standard(max_width_for_aspect)
            new_width_in = max(MIN_DUCT_WIDTH, new_width_in)
            velocity = calculate_velocity(new_cfm, new_width_in, height_in)
            
            # Calculate what height would be needed
            required_height = (required_area_ft2 * 144 / 4.0) ** 0.5
            
            result["warning"] = (
                f"DUCT HEIGHT TOO SMALL: Velocity {velocity:.0f} FPM exceeds {max_velocity} FPM. "
                f"Need {required_width:.0f}\" width or increase height to ~{required_height:.0f}\"."
            )
        else:
            # Can fix by increasing width
            new_width_in = round_to_standard(required_width)
            new_width_in = max(MIN_DUCT_WIDTH, new_width_in)
            velocity = calculate_velocity(new_cfm, new_width_in, height_in)
            
            # Only warn if still slightly over
            if velocity > max_velocity * 1.05:
                result["warning"] = f"Velocity {velocity:.0f} FPM slightly exceeds {max_velocity} FPM limit"

    result["new_dims"] = f'{new_width_in:.0f}×{height_in:.0f}"'
    result["velocity_fpm"] = round(velocity, 0)

    # Check aspect ratio
    aspect_ratio = max(new_width_in, height_in) / min(new_width_in, height_in) if min(new_width_in, height_in) > 0 else 1
    if aspect_ratio > 4:
        if result["warning"]:
            result["warning"] += f"; Aspect ratio {aspect_ratio:.1f}:1 exceeds 4:1"
        else:
            result["warning"] = f"Aspect ratio {aspect_ratio:.1f}:1 exceeds 4:1"

    # Apply new width (height stays the same)
    if not width_param.IsReadOnly:
        width_param.Set(new_width_in * INCHES_TO_FEET)

    return result


# =============================================================================
# EQUAL FRICTION RESIZE FUNCTIONS
# =============================================================================


def resize_duct_equal_friction_commercial(duct, scale_factor):
    """
    Resize a duct for commercial applications using the equal friction method.
    Both width and height can change to achieve target friction rate.
    
    The equal friction method sizes ducts to maintain a constant pressure drop
    per unit length (typically 0.08-0.10 in. w.g. per 100 ft for commercial).
    """
    result = {
        "id": str(duct.Id.IntegerValue),
        "old_dims": "",
        "new_dims": "",
        "velocity_fpm": 0,
        "friction_rate": 0,
        "duct_type": "",
        "sizing_method": "equal_friction",
        "warning": None,
    }

    # Get current dimensions
    height_param = duct.get_Parameter(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)
    width_param = duct.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
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

    # Use constant CFM values supplied by user
    current_cfm = OLD_CFM
    new_cfm = NEW_CFM

    # Determine duct type
    duct_type = get_duct_type(duct)
    result["duct_type"] = duct_type

    # Get target friction rate for commercial
    target_friction = FRICTION_RATE["commercial"]
    
    # Calculate required equivalent diameter for the target friction rate
    required_equiv_dia = calculate_diameter_for_friction(new_cfm, target_friction)
    
    # Calculate rectangular dimensions to achieve this equivalent diameter
    new_width, new_height = calculate_rectangular_dims_for_diameter(required_equiv_dia)
    
    # Round to standard sizes
    new_height = round_to_standard(new_height)
    new_width = round_to_standard(new_width)

    # Ensure minimum sizes
    new_height = max(MIN_DUCT_HEIGHT, new_height)
    new_width = max(MIN_DUCT_WIDTH, new_width)

    result["new_dims"] = f'{new_width:.0f}×{new_height:.0f}"'

    # Calculate actual friction rate with the new dimensions
    actual_equiv_dia = calculate_equivalent_diameter(new_width, new_height)
    actual_friction = calculate_friction_rate(new_cfm, actual_equiv_dia)
    result["friction_rate"] = round(actual_friction, 3)

    # Calculate resulting velocity
    velocity = calculate_velocity(new_cfm, new_width, new_height)
    result["velocity_fpm"] = round(velocity, 0)

    # Check velocity limits (even with equal friction, we have max velocity limits)
    max_velocity = MAX_VELOCITY_LIMIT["commercial"]
    if velocity > max_velocity:
        result["warning"] = (
            f"Velocity {velocity:.0f} FPM exceeds {max_velocity} FPM absolute limit"
        )
        # Increase duct size to reduce velocity
        # required_area_ft2 = new_cfm / max_velocity
        # required_area_in2 = required_area_ft2 * 144
        # # Increase both dimensions proportionally
        # current_area = new_width * new_height
        # scale_up = (required_area_in2 / current_area) ** 0.5
        # new_width = round_to_standard(new_width * scale_up)
        # new_height = round_to_standard(new_height * scale_up)
        # result["new_dims"] = f'{new_width:.0f}×{new_height:.0f}"'
        # result["warning"] += f" - upsized to {new_width:.0f}×{new_height:.0f}\""

    # Apply new dimensions
    if not height_param.IsReadOnly:
        height_param.Set(new_height * INCHES_TO_FEET)
    if not width_param.IsReadOnly:
        width_param.Set(new_width * INCHES_TO_FEET)

    return result


def resize_duct_equal_friction_apartment(duct, scale_factor):
    """
    Resize a duct for apartment applications using the equal friction method.
    Height is locked (ceiling constraint), only width changes.
    
    Uses lower friction rate for residential (0.08 in. w.g. per 100 ft typical)
    to minimize noise.
    """
    result = {
        "id": str(duct.Id.IntegerValue),
        "old_dims": "",
        "new_dims": "",
        "velocity_fpm": 0,           # Rectangular duct velocity
        "velocity_equiv_fpm": 0,     # Equivalent round duct velocity (what some ductulators show)
        "equiv_diameter": 0,
        "friction_rate": 0,
        "duct_type": "",
        "sizing_method": "equal_friction",
        "warning": None,
    }

    # Get current dimensions
    height_param = duct.get_Parameter(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)
    width_param = duct.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
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

    # Use constant CFM values supplied by user
    current_cfm = OLD_CFM
    new_cfm = NEW_CFM
    
    # Store CFM values for debugging
    result["current_cfm"] = round(current_cfm, 0)
    result["new_cfm"] = round(new_cfm, 0)

    # Determine duct type
    duct_type = get_duct_type(duct)
    result["duct_type"] = duct_type

    # Get target friction rate for apartment
    target_friction = FRICTION_RATE["apartment"]
    max_velocity = MAX_VELOCITY_LIMIT["apartment"]
    
    # Find the smallest standard width that achieves target friction
    # Uses 2% tolerance to match typical ductulator behavior (0.0808 ≈ 0.08)
    width_for_friction = find_width_for_friction(new_cfm, height_in, target_friction, tolerance=1.02)
    
    # Also calculate width required for max velocity
    required_area_ft2 = new_cfm / max_velocity
    width_for_velocity = round_to_standard(max(MIN_DUCT_WIDTH, (required_area_ft2 * 144) / height_in))
    
    # Determine final width based on configuration
    if ENFORCE_VELOCITY_IN_EQUAL_FRICTION:
        # Use the LARGER width (more restrictive requirement governs)
        new_width_in = max(width_for_friction, width_for_velocity)
    else:
        # Size based on friction only (matches typical ductulator behavior)
        new_width_in = width_for_friction

    # Ensure minimum size
    new_width_in = max(MIN_DUCT_WIDTH, new_width_in)
    
    # Check aspect ratio constraint
    max_width_for_aspect = height_in * 4.0
    aspect_ratio_exceeded = new_width_in > max_width_for_aspect
    
    if aspect_ratio_exceeded:
        new_width_in = round_to_standard(max_width_for_aspect)
        new_width_in = max(MIN_DUCT_WIDTH, new_width_in)

    result["new_dims"] = f'{new_width_in:.0f}×{height_in:.0f}"'

    # Calculate actual values with the final dimensions
    actual_equiv_dia = calculate_equivalent_diameter(new_width_in, height_in)
    actual_friction = calculate_friction_rate(new_cfm, actual_equiv_dia)
    velocity_rect = calculate_velocity(new_cfm, new_width_in, height_in)
    velocity_equiv = calculate_equiv_round_velocity(new_cfm, actual_equiv_dia)
    
    result["equiv_diameter"] = round(actual_equiv_dia, 2)
    result["friction_rate"] = round(actual_friction, 3)
    result["velocity_fpm"] = round(velocity_rect, 0)
    result["velocity_equiv_fpm"] = round(velocity_equiv, 0)
    
    # Check if we have issues
    if velocity_rect > max_velocity:
        # Calculate what would actually be needed
        required_width_for_velocity = (required_area_ft2 * 144) / height_in
        
        if required_width_for_velocity > height_in * 4.0:
            # Cannot achieve target velocity with 4:1 aspect ratio
            required_height = (required_area_ft2 * 144 / 4.0) ** 0.5
            
            result["warning"] = (
                f"DUCT HEIGHT TOO SMALL: Velocity {velocity_rect:.0f} FPM exceeds {max_velocity} FPM limit. "
                f"Need {required_width_for_velocity:.0f}\" width (or increase height to ~{required_height:.0f}\"). "
                f"Max width at 4:1 aspect ratio is {new_width_in:.0f}\"."
            )
        else:
            # Velocity is over but could be fixed with more width (should not happen)
            result["warning"] = (
                f"Velocity {velocity_rect:.0f} FPM slightly exceeds {max_velocity} FPM limit."
            )
    elif aspect_ratio_exceeded:
        # Aspect ratio was capped but velocity is OK
        result["warning"] = (
            f"Aspect ratio capped at 4:1. "
            f"Actual friction: {actual_friction:.3f} in.wg/100ft vs target {target_friction:.3f}"
        )

    # Final aspect ratio info
    aspect_ratio = max(new_width_in, height_in) / min(new_width_in, height_in) if min(new_width_in, height_in) > 0 else 1
    result["aspect_ratio"] = round(aspect_ratio, 1)

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

        current_cfm = flow_param.AsDouble()

        if distribution_method == "proportional":
            new_cfm = current_cfm * scale_factor
        else:  # equal
            new_cfm = current_cfm + equal_change

        flow_param.Set(new_cfm)

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
# IN[0]: Optional system name string (e.g., "Supply Air 1")

# Debug: Show what we received
print(f"IN[0] type: {type(IN[0])}")
print(f"IN[0] value: {IN[0]}")

# Resolve target system name
system_name = FILTER_BY_SYSTEM_NAME
if IN[0] and isinstance(IN[0], str) and IN[0].strip():
    system_name = str(IN[0]).strip()

if not system_name:
    raise ValueError("Provide a system name via FILTER_BY_SYSTEM_NAME or connect one to IN[0].")

# Calculate scale factor from CFM values
if OLD_CFM <= 0:
    raise ValueError("OLD_CFM must be greater than 0")

scale_factor = NEW_CFM / OLD_CFM
print(f"Scale factor: {scale_factor:.3f} ({OLD_CFM} CFM -> {NEW_CFM} CFM)")
print(f"Operating mode: {OPERATING_MODE}")
print(f"Sizing method: {SIZING_METHOD}")
print(f"System name: {system_name}")

# Show friction rate if using equal friction method
if SIZING_METHOD == "equal_friction":
    friction_rate = FRICTION_RATE.get(OPERATING_MODE, 0.08)
    print(f"Target friction rate: {friction_rate} in. w.g. per 100 ft")

# Results storage
all_results = {
    "selection_method": "system",
    "system_name": system_name,
    "operating_mode": OPERATING_MODE,
    "sizing_method": SIZING_METHOD,
    "old_cfm": OLD_CFM,
    "new_cfm": NEW_CFM,
    "scale_factor": round(scale_factor, 3),
    "friction_rate": FRICTION_RATE.get(OPERATING_MODE, 0.08) if SIZING_METHOD == "equal_friction" else None,
    "ducts_processed": 0,
    "ducts_resized": 0,
    "warnings": [],
    "details": [],
}

# Collect ducts based on system name only
ducts_to_resize = get_ducts_by_system_name(system_name)
print(f"System '{system_name}': {len(ducts_to_resize)} ducts")

all_results["ducts_processed"] = len(ducts_to_resize)

# Start transaction
TransactionManager.Instance.EnsureInTransaction(doc)

# Resize each duct
for duct in ducts_to_resize:
    if not duct:
        continue

    # Resize based on sizing method and operating mode
    if SIZING_METHOD == "equal_friction":
        # Equal friction method
        if OPERATING_MODE == "apartment":
            duct_result = resize_duct_equal_friction_apartment(duct, scale_factor)
        else:
            duct_result = resize_duct_equal_friction_commercial(duct, scale_factor)
    else:
        # Velocity method (default)
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

    # Print output varies based on sizing method
    if SIZING_METHOD == "equal_friction":
        friction_info = f", {duct_result.get('friction_rate', 0):.3f} in.wg/100ft"
    else:
        friction_info = ""
    
    # Include CFM info in output
    cfm_info = ""
    if "current_cfm" in duct_result and "new_cfm" in duct_result:
        cfm_info = f" [CFM: {duct_result['current_cfm']:.0f} -> {duct_result['new_cfm']:.0f}]"
    
    print(
        f"  Duct {duct_result['id']}: {duct_result['old_dims']} -> {duct_result['new_dims']} "
        f"({duct_result['duct_type']}, {duct_result['velocity_fpm']} FPM{friction_info}){cfm_info}"
    )

# Regenerate the document to update fittings
doc.Regenerate()

# Update air terminal (diffuser) CFM values
terminals_updated = []
if system_name:
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
                                    current_cfm = flow_param.AsDouble()
                                    new_cfm = current_cfm * scale_factor
                                    flow_param.Set(new_cfm)
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
                                    current_cfm = flow_param.AsDouble()
                                    new_cfm = current_cfm * scale_factor
                                    flow_param.Set(new_cfm)
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
if system_name:
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
            
            # Determine fitting type by family name
            family_lower = family_name.lower()
            is_transition = "transition" in family_lower or "reducer" in family_lower
            is_elbow = "elbow" in family_lower or "bend" in family_lower
            is_tee = "tee" in family_lower or "wye" in family_lower or "takeoff" in family_lower
            is_tap = "tap" in family_lower
            
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
            
            # Determine if this fitting should be processed or skipped
            # Taps should be LEFT ALONE - they connect to trunk ducts in complex ways
            # Elbows and Tees need to be deleted and recreated to get new sizes
            # Transitions need to be deleted and recreated
            should_skip = is_tap  # Only skip taps
            
            # Determine if we can auto-recreate this fitting
            # - Transitions: need 2 ducts, use NewTransitionFitting
            # - Elbows: need 2 ducts at an angle, use NewElbowFitting  
            # - Tees: need 3 ducts, use NewTeeFitting (complex, skip for now)
            can_recreate_transition = is_transition and len(connected_ducts_info) >= 2
            can_recreate_elbow = is_elbow and len(connected_ducts_info) >= 2
            can_recreate = (can_recreate_transition or can_recreate_elbow) and not should_skip
            
            fittings_to_recreate.append({
                "fitting_id": fitting.Id,
                "fitting_id_str": fitting_id,
                "family_name": family_name,
                "type_id": type_id,
                "is_transition": is_transition,
                "is_elbow": is_elbow,
                "is_tee": is_tee,
                "is_tap": is_tap,
                "should_skip": should_skip,
                "connected_ducts": connected_ducts_info,
                "can_recreate": can_recreate,
                "can_recreate_elbow": can_recreate_elbow if 'can_recreate_elbow' in dir() else False,
                "can_recreate_transition": can_recreate_transition if 'can_recreate_transition' in dir() else False
            })
            
        except Exception as e:
            print(f"  Error collecting info for fitting {fitting_id}: {e}")
    
    # Now delete fittings and try to recreate them
    for fit_info in fittings_to_recreate:
        fitting_id_str = fit_info["fitting_id_str"]
        family_name = fit_info["family_name"]

        # Skip taps - they connect to trunk ducts in complex ways
        if fit_info.get("should_skip", False) or fit_info.get("is_tap", False):
            fittings_skipped.append({
                "id": fitting_id_str,
                "family": family_name,
                "status": "preserved",
                "reason": "tap fitting - requires manual handling"
            })
            print(
                f"  Preserving tap {fitting_id_str} ({family_name}) - "
                "requires manual handling"
            )
            continue
        
        # Skip tees for now - they have 3+ connections and are complex to recreate
        if fit_info.get("is_tee", False):
            fittings_skipped.append({
                "id": fitting_id_str,
                "family": family_name,
                "status": "preserved", 
                "reason": "tee fitting - complex recreation not yet supported"
            })
            print(
                f"  Preserving tee {fitting_id_str} ({family_name}) - "
                "complex recreation not yet supported"
            )
            continue
        
        # Skip fittings that can't be auto-recreated (non-transitions with complex connections)
        if not fit_info.get("can_recreate", False):
            fittings_skipped.append({
                "id": fitting_id_str,
                "family": family_name,
                "status": "skipped",
                "reason": "auto recreation not supported - requires manual handling"
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
        
        # Need at least 2 connected ducts to recreate any fitting
        if len(fit_info["connected_ducts"]) < 2:
            continue
            
        try:
            # Get the two ducts that were connected
            duct1_id = fit_info["connected_ducts"][0]["duct_id"]
            duct2_id = fit_info["connected_ducts"][1]["duct_id"]
            
            duct1 = doc.GetElement(duct1_id)
            duct2 = doc.GetElement(duct2_id)
            
            if not duct1 or not duct2:
                print(f"  Could not find ducts for fitting {fit_info['fitting_id_str']}")
                fittings_recreated.append({
                    "old_id": fit_info["fitting_id_str"],
                    "new_id": "manual",
                    "family": fit_info["family_name"],
                    "status": "needs_manual_creation"
                })
                continue
            
            # Find the open connectors on each duct (closest to original connection points)
            conn1 = find_connector_near_point(duct1, fit_info["connected_ducts"][0].get("connection_point"))
            conn2 = find_connector_near_point(duct2, fit_info["connected_ducts"][1].get("connection_point"))
            
            if not conn1 or not conn2:
                print(f"  Could not find open connectors for fitting {fit_info['fitting_id_str']}")
                fittings_recreated.append({
                    "old_id": fit_info["fitting_id_str"],
                    "new_id": "manual",
                    "family": fit_info["family_name"],
                    "status": "needs_manual_creation"
                })
                continue
            
            new_fitting = None
            fitting_type_created = ""
            
            # Try to create the appropriate fitting type
            if fit_info.get("is_elbow", False):
                # For elbows - try NewElbowFitting first
                try:
                    new_fitting = doc.Create.NewElbowFitting(conn1, conn2)
                    fitting_type_created = "elbow"
                except Exception as e:
                    print(f"    NewElbowFitting failed: {e}")
                    # Fallback to transition if elbow fails (might be a reducing elbow situation)
                    try:
                        new_fitting = doc.Create.NewTransitionFitting(conn1, conn2)
                        fitting_type_created = "transition (fallback)"
                    except Exception as e2:
                        print(f"    NewTransitionFitting fallback also failed: {e2}")
                        
            elif fit_info.get("is_transition", False):
                # For transitions - use NewTransitionFitting
                try:
                    new_fitting = doc.Create.NewTransitionFitting(conn1, conn2)
                    fitting_type_created = "transition"
                except Exception as e:
                    print(f"    NewTransitionFitting failed: {e}")
                    # Try elbow as fallback (in case connectors are at angle)
                    try:
                        new_fitting = doc.Create.NewElbowFitting(conn1, conn2)
                        fitting_type_created = "elbow (fallback)"
                    except Exception as e2:
                        print(f"    NewElbowFitting fallback also failed: {e2}")
            else:
                # Unknown fitting type - try both methods
                try:
                    new_fitting = doc.Create.NewTransitionFitting(conn1, conn2)
                    fitting_type_created = "transition"
                except:
                    try:
                        new_fitting = doc.Create.NewElbowFitting(conn1, conn2)
                        fitting_type_created = "elbow"
                    except:
                        pass
            
            if new_fitting:
                fittings_recreated.append({
                    "old_id": fit_info["fitting_id_str"],
                    "new_id": str(new_fitting.Id.IntegerValue),
                    "family": fit_info["family_name"],
                    "status": "recreated",
                    "type_created": fitting_type_created
                })
                print(f"  Created new {fitting_type_created} fitting between ducts {duct1_id.IntegerValue} and {duct2_id.IntegerValue}")
            else:
                fittings_recreated.append({
                    "old_id": fit_info["fitting_id_str"],
                    "new_id": "manual",
                    "family": fit_info["family_name"],
                    "status": "needs_manual_creation"
                })
                print(f"  Could not auto-create fitting for {fit_info['fitting_id_str']} - manual creation needed")
                
        except Exception as e:
            print(f"  Error recreating fitting {fit_info['fitting_id_str']}: {e}")
            fittings_recreated.append({
                "old_id": fit_info["fitting_id_str"],
                "new_id": "error",
                "family": fit_info["family_name"],
                "status": f"error: {e}"
            })
    
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
print(f"Selection method: system (name='{system_name}')")
print(f"Operating mode: {OPERATING_MODE}")
print(f"Sizing method: {SIZING_METHOD}")
if SIZING_METHOD == "equal_friction":
    print(f"Target friction rate: {FRICTION_RATE.get(OPERATING_MODE, 0.08)} in. w.g./100 ft")
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
