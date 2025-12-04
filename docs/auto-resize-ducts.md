# Auto-Resize Ducts on Equipment Capacity Change

## Overview

This feature automatically recalculates and resizes duct dimensions when the connected mechanical equipment's capacity or CFM changes, while preserving the existing duct layout geometry and terminal device positions.

## Use Case

When working in a space with:

- A mechanical unit (e.g., 1.0 ton, 800 CFM)
- A fully modeled duct layout (trunks, branches, diffusers, grilles)

If the mechanical unit is later changed (e.g., to 1.5 tons and 1000 CFM), the system should:

1. **Recalculate duct sizes** based on the new total CFM from the equipment
2. **Preserve terminal positions** — all diffuser and grille 3D positions remain exactly where they are
3. **Resize ducts only** — adjust width/height to match new airflow while maintaining connections
4. **Support dimension locking** — allow locking either height or width so only the other dimension changes

## Feature Requirements

### Core Behavior

```python
from dataclasses import dataclass, field
from typing import List, Optional, Literal
from Autodesk.Revit.DB import ElementId

@dataclass
class DuctAutoResizeOptions:
    """Options for auto-resizing ducts when equipment CFM changes."""
    system_id: ElementId                    # The HVAC system to recalculate
    new_equipment_cfm: float                # New equipment CFM that triggers recalculation
    lock_dimension: Literal["width", "height", "none"] = "none"  # Which dimension to lock
    sizing_method: Literal["velocity", "equal_friction", "static_regain"] = "velocity"
    preview_mode: bool = False              # Whether to preview changes before applying

@dataclass
class DuctDimensions:
    """Duct cross-section dimensions."""
    width: float   # inches
    height: float  # inches

@dataclass
class ResizedDuct:
    """Information about a resized duct segment."""
    duct_id: ElementId
    previous_dimensions: DuctDimensions
    new_dimensions: DuctDimensions
    new_velocity: float        # FPM (feet per minute)
    new_pressure_loss: float   # in. w.g. (inches water gauge)

@dataclass
class DuctAutoResizeResult:
    """Results from the auto-resize operation."""
    resized_ducts: List[ResizedDuct] = field(default_factory=list)
    preserved_terminals: List[ElementId] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    total_ducts_resized: int = 0
    average_velocity_change: float = 0.0
    total_pressure_loss_change: float = 0.0
```

### Dimension Locking

The dimension locking feature addresses real-world constraints:

| Lock Mode        | Behavior                   | Use Case                                           |
| ---------------- | -------------------------- | -------------------------------------------------- |
| `height` locked  | Only width changes         | Limited ceiling space / plenum height constraints  |
| `width` locked   | Only height changes        | Architectural clearance constraints / chase widths |
| `none` (default) | Both dimensions can change | Optimize for best aspect ratio                     |

```python
@dataclass
class DuctDimensionLock:
    """Lock settings for a duct segment during auto-resize."""
    duct_id: ElementId
    locked_dimension: Literal["width", "height", "none"]
    locked_value: Optional[float] = None  # inches, the fixed dimension value
```

### Workflow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Equipment Capacity Change                         │
│                                                                      │
│   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐        │
│   │  Detect CFM  │────▶│  Calculate   │────▶│   Validate   │        │
│   │    Change    │     │  New Sizes   │     │  Constraints │        │
│   └──────────────┘     └──────────────┘     └──────────────┘        │
│                                                    │                 │
│                                                    ▼                 │
│   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐        │
│   │   Commit     │◀────│   Preview    │◀────│ Check Locks  │        │
│   │   Changes    │     │   Results    │     │  & Limits    │        │
│   └──────────────┘     └──────────────┘     └──────────────┘        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Implementation Approach

### 1. Determining Current Equipment CFM

The script needs to know the current/old CFM to calculate scale factors. There are multiple approaches:

#### Method 1: Sum Terminal Flows (Recommended)

Read the current state directly from the model — the sum of all terminal CFMs equals equipment output:

```python
def get_current_cfm_from_terminals(doc: Document, system: MechanicalSystem) -> float:
    """
    Get current total CFM by summing all terminal flows in the system.
    This is the most reliable method as it reflects actual model state.

    Args:
        doc: Revit Document
        system: MEP MechanicalSystem

    Returns:
        Total CFM from all terminals
    """
    total_cfm = 0.0

    for element_id in system.Elements:
        element = doc.GetElement(element_id)

        # Only count terminals (diffusers, grilles)
        if element.Category.Id.IntegerValue == int(BuiltInCategory.OST_DuctTerminal):
            flow_param = element.get_Parameter(BuiltInParameter.RBS_DUCT_FLOW_PARAM)
            if flow_param and flow_param.HasValue:
                total_cfm += flow_param.AsDouble() * 60  # ft³/s to CFM

    return total_cfm
```

#### Method 2: Read Equipment Parameter

Get the CFM directly from the mechanical equipment's airflow parameter:

```python
def get_equipment_cfm(equipment: FamilyInstance) -> Optional[float]:
    """
    Get current CFM from mechanical equipment parameter.
    Tries multiple common parameter names.

    Args:
        equipment: The mechanical equipment family instance

    Returns:
        CFM value or None if not found
    """
    # Try built-in flow parameter first
    flow_param = equipment.get_Parameter(BuiltInParameter.RBS_DUCT_FLOW_PARAM)

    # Try common shared/family parameter names
    if not flow_param or not flow_param.HasValue:
        param_names = [
            "Airflow", "Air Flow", "CFM",
            "Supply Air Flow", "Supply Airflow",
            "Total Airflow", "Nominal Airflow",
            "Cooling Airflow", "Heating Airflow"
        ]
        for name in param_names:
            flow_param = equipment.LookupParameter(name)
            if flow_param and flow_param.HasValue:
                break

    if flow_param and flow_param.HasValue:
        value = flow_param.AsDouble()
        # If value < 50, it's likely in ft³/s, convert to CFM
        if value < 50:
            return value * 60
        return value

    return None
```

#### Method 3: Combined Approach (Most Robust)

Use equipment parameter as primary, fall back to terminal sum:

```python
def get_current_system_cfm(
    doc: Document,
    equipment: FamilyInstance,
    system: MechanicalSystem
) -> Tuple[float, str]:
    """
    Get current CFM using best available method.

    Args:
        doc: Revit Document
        equipment: The mechanical equipment
        system: Connected MEP system

    Returns:
        Tuple of (cfm_value, source_method)
    """
    # Try equipment parameter first
    equipment_cfm = get_equipment_cfm(equipment)
    if equipment_cfm and equipment_cfm > 0:
        return (equipment_cfm, "equipment_parameter")

    # Fall back to terminal sum
    terminal_cfm = get_current_cfm_from_terminals(doc, system)
    if terminal_cfm > 0:
        return (terminal_cfm, "terminal_sum")

    # Last resort: try to read from trunk duct
    for elem_id in system.Elements:
        elem = doc.GetElement(elem_id)
        if isinstance(elem, Duct):
            flow_param = elem.get_Parameter(BuiltInParameter.RBS_DUCT_FLOW_PARAM)
            if flow_param and flow_param.HasValue:
                return (flow_param.AsDouble() * 60, "trunk_duct")

    return (0.0, "not_found")
```

#### Method 4: User Provides Both Values

Simple approach where user explicitly provides old and new CFM values:

```python
def resize_ducts_with_user_values(
    equipment_id: ElementId,
    old_cfm: float,
    new_cfm: float,
    lock_dimension: str = "height"
) -> Dict:
    """
    Resize ducts using user-provided CFM values.
    Use when automatic detection is unreliable or user wants explicit control.

    Args:
        equipment_id: ElementId of mechanical equipment
        old_cfm: Current CFM (user input)
        new_cfm: Target CFM (user input)
        lock_dimension: "height", "width", or "none"

    Returns:
        Dictionary with results summary
    """
    doc = DocumentManager.Instance.CurrentDBDocument

    # Validate user inputs
    if old_cfm <= 0 or new_cfm <= 0:
        return {"error": "CFM values must be positive"}

    scale_factor = new_cfm / old_cfm

    print(f"User provided values:")
    print(f"  Old CFM: {old_cfm}")
    print(f"  New CFM: {new_cfm}")
    print(f"  Scale factor: {scale_factor:.3f}")

    # Get equipment and system
    equipment = doc.GetElement(equipment_id)
    system = get_supply_system(equipment)

    if not system:
        return {"error": "No connected system found"}

    # Proceed with resize using the user-provided scale factor
    # ... (rest of resize logic)

    return {
        "success": True,
        "old_cfm": old_cfm,
        "new_cfm": new_cfm,
        "scale_factor": scale_factor,
        "source": "user_input"
    }


# === DYNAMO INTERFACE FOR USER INPUT ===
# Use this when you want explicit user control:

# equipment_id = UnwrapElement(IN[0]).Id  # Equipment element
# old_cfm = IN[1]                          # User enters: 800
# new_cfm = IN[2]                          # User enters: 1000

# OUT = resize_ducts_with_user_values(equipment_id, old_cfm, new_cfm)
```

#### CFM Source Comparison

| Method                  | Pros                                   | Cons                                   |
| ----------------------- | -------------------------------------- | -------------------------------------- |
| **Terminal Sum**        | Always accurate, reflects actual model | Requires terminals to have Flow values |
| **Equipment Parameter** | Direct from source, single read        | Parameter name varies by family        |
| **Trunk Duct Flow**     | Quick single value                     | May not include all branches           |
| **User Input**          | Explicit control, works always         | User might enter wrong value           |

### 2. Equipment Change Detection

```python
@dataclass
class EquipmentCapacity:
    """Equipment capacity information."""
    tons: float
    cfm: float  # L/s internally, displayed as CFM

@dataclass
class EquipmentChangeEvent:
    """Event triggered when equipment capacity changes."""
    equipment_id: ElementId
    previous_capacity: EquipmentCapacity
    new_capacity: EquipmentCapacity
    connected_system_id: ElementId
```

When equipment parameters are updated, the system should:

1. Detect if CFM/capacity changed
2. Identify all connected duct systems via MEP connectors
3. Trigger auto-resize calculation (with user confirmation or auto-apply based on settings)

### 3. Duct Network Traversal

```python
import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Mechanical import *
from typing import Dict

class DuctNetworkAnalyzer:
    """Analyzes duct networks to calculate airflow requirements per segment."""

    def __init__(self, doc: Document):
        self.doc = doc

    def calculate_segment_airflows(self, system: MechanicalSystem, equipment_cfm: float) -> Dict[ElementId, float]:
        """
        Traverse the duct network from equipment to terminals,
        calculating required CFM at each segment based on
        downstream terminal requirements.

        Args:
            system: The MEP MechanicalSystem
            equipment_cfm: Total CFM from equipment

        Returns:
            Dictionary mapping duct ElementId to required CFM
        """
        segment_cfms = {}

        # 1. Find all terminals (diffusers, grilles) in system
        terminals = self._get_system_terminals(system)

        # 2. Walk upstream from terminals to equipment
        for terminal in terminals:
            terminal_cfm = self._get_terminal_cfm(terminal)
            upstream_ducts = self._trace_upstream(terminal)

            # 3. Sum CFM requirements at each junction
            for duct_id in upstream_ducts:
                if duct_id in segment_cfms:
                    segment_cfms[duct_id] += terminal_cfm
                else:
                    segment_cfms[duct_id] = terminal_cfm

        return segment_cfms

    def _get_system_terminals(self, system: MechanicalSystem) -> List[FamilyInstance]:
        """Get all air terminals in the system."""
        terminals = []
        for element_id in system.Elements:
            element = self.doc.GetElement(element_id)
            if element.Category.Id.IntegerValue == int(BuiltInCategory.OST_DuctTerminal):
                terminals.append(element)
        return terminals

    def _get_terminal_cfm(self, terminal: FamilyInstance) -> float:
        """Get the CFM value from a terminal's Flow parameter."""
        flow_param = terminal.get_Parameter(BuiltInParameter.RBS_DUCT_FLOW_PARAM)
        if flow_param:
            # Convert from ft³/s to CFM (multiply by 60)
            return flow_param.AsDouble() * 60
        return 0.0

    def _trace_upstream(self, terminal: FamilyInstance) -> List[ElementId]:
        """Trace upstream ducts from a terminal to equipment."""
        upstream_ducts = []
        connectors = terminal.MEPModel.ConnectorManager.Connectors

        for connector in connectors:
            if connector.IsConnected:
                for ref in connector.AllRefs:
                    owner = ref.Owner
                    if isinstance(owner, Duct):
                        upstream_ducts.append(owner.Id)
                        # Continue tracing upstream...

        return upstream_ducts
```

### 3. Size Calculation with Locks

```python
class LockedDimensionSizer:
    """Calculates new duct dimensions respecting dimension locks."""

    # Target velocities by sizing method (FPM - feet per minute)
    VELOCITY_TARGETS = {
        "velocity": {"trunk": 1500, "branch": 1200, "runout": 800},
        "equal_friction": {"trunk": 1200, "branch": 1000, "runout": 700},
        "static_regain": {"trunk": 1600, "branch": 1300, "runout": 900},
    }

    def calculate_new_dimensions(
        self,
        duct: Duct,
        required_cfm: float,
        lock: DuctDimensionLock,
        sizing_method: str,
        duct_type: str = "branch"
    ) -> DuctDimensions:
        """
        Calculate new duct dimensions based on required CFM and lock settings.

        Args:
            duct: The Revit Duct element
            required_cfm: Required airflow in CFM
            lock: Dimension lock settings
            sizing_method: Sizing method to use
            duct_type: Type of duct (trunk, branch, runout)

        Returns:
            New duct dimensions
        """
        target_velocity = self.VELOCITY_TARGETS[sizing_method][duct_type]

        # Required area in ft² (CFM / FPM = ft²)
        required_area_ft2 = required_cfm / target_velocity

        # Convert to in² for dimension calculation (1 ft² = 144 in²)
        required_area_in2 = required_area_ft2 * 144

        if lock.locked_dimension == "height":
            # Height fixed, calculate new width
            new_width = required_area_in2 / lock.locked_value
            return DuctDimensions(width=new_width, height=lock.locked_value)

        elif lock.locked_dimension == "width":
            # Width fixed, calculate new height
            new_height = required_area_in2 / lock.locked_value
            return DuctDimensions(width=lock.locked_value, height=new_height)

        else:
            # No lock, optimize aspect ratio (target 2:1 or better)
            return self._optimize_aspect_ratio(required_area_in2)

    def _optimize_aspect_ratio(self, area_in2: float, max_ratio: float = 4.0) -> DuctDimensions:
        """Calculate dimensions with optimal aspect ratio."""
        import math
        # Start with square root for equal dimensions
        side = math.sqrt(area_in2)
        # Round to standard increments (2 inches)
        width = self._round_to_standard(side * 1.4)   # Wider
        height = self._round_to_standard(side * 0.7)  # Shorter
        return DuctDimensions(width=width, height=height)

    def _round_to_standard(self, dimension: float, increment: float = 2.0) -> float:
        """Round dimension to nearest standard size (2-inch increments)."""
        return round(dimension / increment) * increment
```

### 4. Geometry Preservation

Key constraint: **Terminal positions must not move**

```python
@dataclass
class GeometryPreservation:
    """Settings for preserving geometry during resize."""
    preserve_terminal_positions: bool = True   # Terminals keep exact 3D coordinates
    preserve_duct_centerlines: bool = True     # Duct centerlines remain unchanged
    modify_only: str = "cross_section"         # Only cross-sectional dimensions change
    auto_adjust_fittings: bool = True          # Connections/fittings auto-adjust to new sizes

def update_duct_dimensions(doc: Document, duct: Duct, new_dims: DuctDimensions) -> None:
    """
    Update duct dimensions while preserving centerline position.
    Revit automatically preserves centerline when changing Width/Height parameters.

    Args:
        doc: Revit Document
        duct: The duct element to resize
        new_dims: New dimensions to apply
    """
    # Get dimension parameters (values in feet internally)
    width_param = duct.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
    height_param = duct.get_Parameter(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)

    # Convert inches to feet for Revit API
    INCHES_TO_FEET = 1/12  # 0.0833333

    if width_param and not width_param.IsReadOnly:
        width_param.Set(new_dims.width * INCHES_TO_FEET)

    if height_param and not height_param.IsReadOnly:
        height_param.Set(new_dims.height * INCHES_TO_FEET)
```

### 5. Main Auto-Resize Function

Complete implementation for Dynamo/pyRevit:

```python
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Mechanical import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

def auto_resize_ducts(
    equipment_id: ElementId,
    new_cfm: float,
    lock_dimension: str = "none",
    sizing_method: str = "velocity",
    preview_only: bool = False
) -> DuctAutoResizeResult:
    """
    Main function to auto-resize ducts when equipment CFM changes.

    Args:
        equipment_id: ElementId of the mechanical equipment
        new_cfm: New total CFM from equipment
        lock_dimension: "width", "height", or "none"
        sizing_method: "velocity", "equal_friction", or "static_regain"
        preview_only: If True, returns preview without making changes

    Returns:
        DuctAutoResizeResult with all changes made or previewed
    """
    doc = DocumentManager.Instance.CurrentDBDocument
    result = DuctAutoResizeResult()

    # Get the equipment and its connected system
    equipment = doc.GetElement(equipment_id)
    system = get_connected_system(equipment)

    if not system:
        result.warnings.append("No connected duct system found")
        return result

    # Analyze network and calculate segment airflows
    analyzer = DuctNetworkAnalyzer(doc)
    segment_cfms = analyzer.calculate_segment_airflows(system, new_cfm)

    # Get terminals for preservation list
    terminals = analyzer._get_system_terminals(system)
    result.preserved_terminals = [t.Id for t in terminals]

    # Calculate new sizes for each duct
    sizer = LockedDimensionSizer()
    changes = []

    for duct_id, required_cfm in segment_cfms.items():
        duct = doc.GetElement(duct_id)

        # Get current dimensions
        current_dims = get_duct_dimensions(duct)

        # Create lock settings
        lock = DuctDimensionLock(
            duct_id=duct_id,
            locked_dimension=lock_dimension,
            locked_value=current_dims.height if lock_dimension == "height" else
                        current_dims.width if lock_dimension == "width" else None
        )

        # Calculate new dimensions
        new_dims = sizer.calculate_new_dimensions(
            duct, required_cfm, lock, sizing_method
        )

        # Track the change
        changes.append({
            "duct": duct,
            "duct_id": duct_id,
            "current_dims": current_dims,
            "new_dims": new_dims,
            "cfm": required_cfm
        })

        result.resized_ducts.append(ResizedDuct(
            duct_id=duct_id,
            previous_dimensions=current_dims,
            new_dimensions=new_dims,
            new_velocity=calculate_velocity(required_cfm, new_dims),
            new_pressure_loss=0.0  # Would need pressure calc
        ))

    # Apply changes if not preview only
    if not preview_only:
        TransactionManager.Instance.EnsureInTransaction(doc)

        for change in changes:
            update_duct_dimensions(doc, change["duct"], change["new_dims"])

        TransactionManager.Instance.TransactionTaskDone()

    result.total_ducts_resized = len(changes)
    return result

def get_connected_system(equipment: FamilyInstance) -> MechanicalSystem:
    """Get the MEP system connected to equipment."""
    connectors = equipment.MEPModel.ConnectorManager.Connectors
    for connector in connectors:
        if connector.MEPSystem:
            return connector.MEPSystem
    return None

def get_duct_dimensions(duct: Duct) -> DuctDimensions:
    """Get current duct dimensions in mm."""
    FEET_TO_MM = 304.8
    width = duct.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM).AsDouble() * FEET_TO_MM
    height = duct.get_Parameter(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM).AsDouble() * FEET_TO_MM
    return DuctDimensions(width=width, height=height)

def calculate_velocity(cfm: float, dims: DuctDimensions) -> float:
    """Calculate velocity in m/s."""
    area_m2 = (dims.width / 1000) * (dims.height / 1000)
    flow_m3s = cfm * 0.000471947
    return flow_m3s / area_m2 if area_m2 > 0 else 0
```

This enables full undo/redo support through Revit's transaction system.

## User Interface

### Equipment Inspector Panel

When editing equipment capacity:

```
┌─────────────────────────────────────────┐
│ Mechanical Unit Properties              │
├─────────────────────────────────────────┤
│ Name: AHU-01                            │
│ Capacity: [1.5    ] tons                │
│ Airflow:  [1000   ] CFM                 │
│                                         │
│ ┌─────────────────────────────────────┐ │
│ │ ⚠️ Airflow changed from 800 CFM     │ │
│ │                                     │ │
│ │ Connected ducts will be resized.    │ │
│ │                                     │ │
│ │ Dimension Lock:                     │ │
│ │ ○ None (optimize both)              │ │
│ │ ○ Lock Height (adjust width only)   │ │
│ │ ● Lock Width (adjust height only)   │ │
│ │                                     │ │
│ │ [Preview Changes] [Apply Resize]    │ │
│ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

### Duct Segment Lock Settings

Individual ducts can have lock settings in their inspector:

```
┌─────────────────────────────────────────┐
│ Duct Segment Properties                 │
├─────────────────────────────────────────┤
│ ID: duct-trunk-01                       │
│ Width:  400 mm    🔓 [Lock]             │
│ Height: 300 mm    🔒 Locked             │
│                                         │
│ Auto-Resize Behavior:                   │
│ When equipment CFM changes, this duct   │
│ will adjust WIDTH only (height locked). │
└─────────────────────────────────────────┘
```

### Preview Mode

Before applying changes, users can preview:

```
┌─────────────────────────────────────────────────────────────────┐
│ Auto-Resize Preview                                    [×]      │
├─────────────────────────────────────────────────────────────────┤
│ Equipment: AHU-01 (800 CFM → 1000 CFM)                          │
│                                                                 │
│ Affected Ducts: 12                                              │
│                                                                 │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ Segment        │ Current    │ New        │ Velocity │ Lock  │ │
│ ├─────────────────────────────────────────────────────────────┤ │
│ │ Main Trunk     │ 400×300mm  │ 450×300mm  │ 7.4 m/s  │ H 🔒  │ │
│ │ Branch-01      │ 300×250mm  │ 340×250mm  │ 6.8 m/s  │ H 🔒  │ │
│ │ Branch-02      │ 250×200mm  │ 280×200mm  │ 7.1 m/s  │ H 🔒  │ │
│ │ ...            │            │            │          │       │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ ⚠️ 2 segments exceed recommended velocity (8 m/s max)           │
│                                                                 │
│               [Cancel]  [Adjust Locks]  [Apply All]             │
└─────────────────────────────────────────────────────────────────┘
```

## Validation Rules

Validation functions to support this feature:

```python
from typing import List, Tuple

class DuctResizeValidator:
    """Validates duct resize operations."""

    # Velocity limits (FPM - feet per minute)
    MAX_VELOCITY = {"trunk": 2000, "branch": 1600, "runout": 1200}
    MIN_DIMENSION_IN = 4  # inches
    MAX_ASPECT_RATIO = 4.0
    STANDARD_SIZES_IN = [4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 28, 32, 36]

    def validate_resize(self, result: DuctAutoResizeResult) -> List[Tuple[str, str, str]]:
        """
        Validate resize results and return warnings/errors.

        Returns:
            List of tuples: (rule_id, severity, message)
        """
        issues = []

        for duct in result.resized_ducts:
            # Check velocity limits
            if duct.new_velocity > self.MAX_VELOCITY["branch"]:
                issues.append((
                    "DUCT_RESIZE_VELOCITY_CHECK",
                    "warning",
                    f"Duct {duct.duct_id} velocity {duct.new_velocity:.0f} FPM exceeds limit"
                ))

            # Check aspect ratio
            dims = duct.new_dimensions
            ratio = max(dims.width, dims.height) / min(dims.width, dims.height)
            if ratio > self.MAX_ASPECT_RATIO:
                issues.append((
                    "DUCT_RESIZE_ASPECT_RATIO",
                    "warning",
                    f"Duct {duct.duct_id} aspect ratio {ratio:.1f}:1 exceeds {self.MAX_ASPECT_RATIO}:1"
                ))

            # Check minimum dimension
            if dims.width < self.MIN_DIMENSION_IN or dims.height < self.MIN_DIMENSION_IN:
                issues.append((
                    "DUCT_RESIZE_MIN_DIMENSION",
                    "error",
                    f"Duct {duct.duct_id} dimension below minimum {self.MIN_DIMENSION_IN} inches"
                ))

            # Check standard sizes
            if not self._is_standard_size(dims.width) or not self._is_standard_size(dims.height):
                issues.append((
                    "DUCT_RESIZE_STANDARD_SIZE",
                    "info",
                    f"Duct {duct.duct_id} dimensions not standard sizes"
                ))

        return issues

    def _is_standard_size(self, dimension: float) -> bool:
        """Check if dimension matches a standard duct size."""
        return any(abs(dimension - std) < 0.5 for std in self.STANDARD_SIZES_IN)
```

## Configuration Options

Project-level settings for auto-resize behavior:

```python
@dataclass
class AutoResizeSettings:
    """Project-level settings for auto-resize behavior."""

    # Automatically resize on equipment change vs manual trigger
    auto_trigger: bool = False

    # Default sizing method: "velocity", "equal_friction", "static_regain"
    default_sizing_method: str = "velocity"

    # Default dimension lock for new ducts: "width", "height", "none"
    default_dimension_lock: str = "none"

    # Round to standard duct sizes
    round_to_standard_sizes: bool = True

    # Standard duct size increments (inches)
    standard_size_increment: float = 2.0

    # Maximum allowed aspect ratio
    max_aspect_ratio: float = 4.0

    # Velocity limits by duct location (FPM)
    velocity_limit_trunk: float = 1500
    velocity_limit_branch: float = 1200
    velocity_limit_runout: float = 800

# Example usage with JSON configuration file
import json

def load_settings(config_path: str) -> AutoResizeSettings:
    """Load settings from JSON configuration file."""
    with open(config_path, 'r') as f:
        data = json.load(f)
    return AutoResizeSettings(**data)

def save_settings(settings: AutoResizeSettings, config_path: str) -> None:
    """Save settings to JSON configuration file."""
    from dataclasses import asdict
    with open(config_path, 'w') as f:
        json.dump(asdict(settings), f, indent=2)
```

## Integration Points

### With Analysis Modules

- Uses `DuctSizingResult` from `analysis-modules.md`
- Feeds into `SystemBalancer` for pressure recalculation
- Triggers `DUCT_VELOCITY_MAX` validation after resize

### With Store Actions

- Creates `AUTO_RESIZE_DUCTS` action for undo/redo
- Batch updates via single history entry
- Preserves `modifiedAt` timestamps per duct

### With Relations Graph

- Traverses equipment → duct connections
- Identifies terminal devices to preserve
- Maintains connection integrity during resize

## Benefits

1. **Time Savings** — No need to manually resize every duct segment when equipment changes
2. **Layout Preservation** — Terminal devices stay in place, maintaining coordination with architectural elements
3. **Constraint Respect** — Dimension locking handles real-world height/width limitations
4. **Full Undo Support** — Entire resize operation can be undone in one step
5. **Preview Capability** — Review changes before committing
6. **Validation Integration** — Immediate feedback on velocity/sizing issues

## Terminal CFM Distribution

When equipment CFM changes, the air terminals (diffusers and grilles) need updated CFM values. The system supports multiple distribution strategies:

### Distribution Methods

| Method         | Description                                         | Use Case                                               |
| -------------- | --------------------------------------------------- | ------------------------------------------------------ |
| `proportional` | Each terminal keeps its percentage of total airflow | Default — maintains balance between terminals          |
| `fixed`        | Terminals keep original CFM values                  | When terminals are sized to specific room requirements |
| `roomBased`    | Recalculate from room load requirements             | Most accurate — requires space/load data               |

### Proportional Scaling Example

```
Original: Equipment = 800 CFM
  - Diffuser A: 200 CFM (25%)
  - Diffuser B: 300 CFM (37.5%)
  - Grille C: 300 CFM (37.5%)

New: Equipment = 1000 CFM (scale factor = 1.25)
  - Diffuser A: 250 CFM (25%)    ← scaled proportionally
  - Diffuser B: 375 CFM (37.5%)
  - Grille C: 375 CFM (37.5%)
```

### Terminal Update Interface

```python
@dataclass
class TerminalCFMUpdate:
    """Information about a terminal CFM update."""
    terminal_id: ElementId
    previous_cfm: float
    new_cfm: float
    distribution_method: Literal["proportional", "fixed", "room_based"]

@dataclass
class TerminalDistributionOptions:
    """Options for distributing CFM to terminals."""
    method: Literal["proportional", "fixed", "room_based"] = "proportional"
    cfm_per_sq_ft: Optional[float] = None      # For room_based method
    cfm_per_person: Optional[float] = None     # For room_based method
    min_terminal_cfm: Optional[float] = None   # Minimum CFM per terminal
    max_terminal_cfm: Optional[float] = None   # Maximum CFM per terminal (device capacity)

def update_terminal_cfms(
    doc: Document,
    system: MechanicalSystem,
    new_equipment_cfm: float,
    options: TerminalDistributionOptions
) -> List[TerminalCFMUpdate]:
    """
    Update air terminal CFMs when equipment capacity changes.

    Args:
        doc: Revit Document
        system: MEP MechanicalSystem
        new_equipment_cfm: New total CFM from equipment
        options: Distribution options

    Returns:
        List of terminal updates performed
    """
    updates = []

    # Get all air terminals in the system
    terminals = []
    terminal_cfms = {}
    current_total_cfm = 0.0

    for element_id in system.Elements:
        element = doc.GetElement(element_id)
        if element.Category.Id.IntegerValue == int(BuiltInCategory.OST_DuctTerminal):
            terminals.append(element)
            flow_param = element.get_Parameter(BuiltInParameter.RBS_DUCT_FLOW_PARAM)
            if flow_param:
                cfm = flow_param.AsDouble() * 60  # Convert ft³/s to CFM
                terminal_cfms[element.Id] = cfm
                current_total_cfm += cfm

    if options.method == "proportional" and current_total_cfm > 0:
        scale_factor = new_equipment_cfm / current_total_cfm

        for terminal in terminals:
            old_cfm = terminal_cfms[terminal.Id]
            new_cfm = old_cfm * scale_factor

            # Apply min/max limits
            if options.min_terminal_cfm:
                new_cfm = max(new_cfm, options.min_terminal_cfm)
            if options.max_terminal_cfm:
                new_cfm = min(new_cfm, options.max_terminal_cfm)

            # Update the terminal's Flow parameter
            flow_param = terminal.get_Parameter(BuiltInParameter.RBS_DUCT_FLOW_PARAM)
            flow_param.Set(new_cfm / 60)  # Convert CFM back to ft³/s

            updates.append(TerminalCFMUpdate(
                terminal_id=terminal.Id,
                previous_cfm=old_cfm,
                new_cfm=new_cfm,
                distribution_method="proportional"
            ))

    elif options.method == "fixed":
        # Terminals unchanged - just track for reporting
        for terminal in terminals:
            cfm = terminal_cfms[terminal.Id]
            updates.append(TerminalCFMUpdate(
                terminal_id=terminal.Id,
                previous_cfm=cfm,
                new_cfm=cfm,
                distribution_method="fixed"
            ))

    return updates
```

### Revit Parameter Mapping

| Revit Parameter | Description              | Units                           |
| --------------- | ------------------------ | ------------------------------- |
| `Flow`          | Scheduled/design airflow | ft³/s (internal), CFM (display) |
| `Actual Flow`   | Calculated system flow   | ft³/s                           |
| `Size`          | Neck size of terminal    | inches                          |
| `Pressure Drop` | Static pressure loss     | in. w.g.                        |

### Terminal Update Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│           Terminal CFM Update Workflow                          │
│                                                                 │
│  1. Equipment CFM changes (800 → 1000)                          │
│                          │                                      │
│                          ▼                                      │
│  2. Collect all terminals in connected system                   │
│     └─ Filter by OST_DuctTerminal category                      │
│     └─ Read current Flow parameter values                       │
│                          │                                      │
│                          ▼                                      │
│  3. Calculate new terminal CFMs based on method                 │
│     ○ Proportional: terminal_new = terminal_old × (new/old)     │
│     ○ Fixed: keep terminal CFMs unchanged                       │
│     ○ Room-based: recalc from space loads                       │
│                          │                                      │
│                          ▼                                      │
│  4. Validate terminal capacities                                │
│     └─ Check min/max CFM for each device type                   │
│     └─ Warn if terminal needs to be upsized                     │
│                          │                                      │
│                          ▼                                      │
│  5. Update terminal Flow parameters                             │
│                          │                                      │
│                          ▼                                      │
│  6. Resize ducts based on new segment airflows                  │
│     └─ Each duct segment = sum of downstream terminal CFMs      │
└─────────────────────────────────────────────────────────────────┘
```

### Terminal Validation Rules

```python
class TerminalValidator:
    """Validates terminal CFM updates."""

    def validate_terminal_update(
        self,
        terminal: FamilyInstance,
        new_cfm: float
    ) -> List[Tuple[str, str, str]]:
        """
        Validate a terminal CFM update.

        Args:
            terminal: The air terminal element
            new_cfm: Proposed new CFM value

        Returns:
            List of tuples: (rule_id, severity, message)
        """
        issues = []

        # Get terminal type parameters for capacity limits
        terminal_type = terminal.Symbol
        max_cfm_param = terminal_type.LookupParameter("Max Airflow")
        min_cfm_param = terminal_type.LookupParameter("Min Airflow")

        # Check capacity limits
        if max_cfm_param and new_cfm > max_cfm_param.AsDouble() * 60:
            max_cfm = max_cfm_param.AsDouble() * 60
            issues.append((
                "TERMINAL_CFM_CAPACITY",
                "warning",
                f"Terminal {terminal.Id} new CFM {new_cfm:.0f} exceeds max capacity {max_cfm:.0f}"
            ))

        # Check minimum CFM
        if min_cfm_param and new_cfm < min_cfm_param.AsDouble() * 60:
            min_cfm = min_cfm_param.AsDouble() * 60
            issues.append((
                "TERMINAL_CFM_MINIMUM",
                "warning",
                f"Terminal {terminal.Id} new CFM {new_cfm:.0f} below minimum {min_cfm:.0f}"
            ))

        # Check noise level (NC rating estimate based on velocity)
        neck_size = terminal.LookupParameter("Size")
        if neck_size:
            # Simplified noise check - real implementation would use manufacturer data
            area_sqft = (neck_size.AsDouble() ** 2) * 0.785  # Circular area
            velocity_fpm = new_cfm / area_sqft if area_sqft > 0 else 0

            if velocity_fpm > 700:  # Typical noise threshold
                issues.append((
                    "TERMINAL_VELOCITY_NOISE",
                    "info",
                    f"Terminal {terminal.Id} velocity {velocity_fpm:.0f} FPM may cause noise"
                ))

        return issues
```

## Future Enhancements

- **Batch Equipment Changes** — Handle multiple equipment changes in one operation
- **Proportional Distribution** — Smart CFM distribution when adding/removing terminals
- **Zone-Based Locking** — Apply lock settings to entire zones or branches
- **AI Suggestions** — Recommend optimal lock settings based on spatial constraints
- **Change Impact Analysis** — Show downstream effects on system balance and pressure
- **Terminal Sizing Suggestions** — Recommend terminal upgrades when CFM exceeds capacity
- **Noise Level Prediction** — Calculate NC ratings based on new terminal velocities

## Apartment-Specific Workflow

For residential apartments with single mechanical units serving multiple rooms, use this optimized approach.

### Recommended Strategy for Apartments

| Apartment Constraint               | Solution                           |
| ---------------------------------- | ---------------------------------- |
| Fixed ceiling heights              | Lock duct height, vary width only  |
| Pre-coordinated diffuser locations | Preserve terminal positions        |
| Single equipment serves all rooms  | Proportional scaling keeps balance |
| Limited space for transitions      | Round to standard sizes            |
| Noise sensitivity                  | Lower velocity limits              |

### Step-by-Step Apartment Workflow

```
1. Select the mechanical unit (WSHP, mini-split, etc.)
   └─ Get its new CFM value

2. Identify the system type
   └─ Supply or Return

3. Lock ALL duct heights to current values
   └─ Apartments rarely have height flexibility

4. Scale terminal CFMs proportionally
   └─ Each room keeps same % of total

5. Resize ducts from trunk → branches → runouts
   └─ Only width changes

6. Validate velocities
   └─ Branch ducts: max 1200 FPM (6 m/s)
   └─ Runouts: max 800 FPM (4 m/s) for low noise
```

### Typical Apartment Sizing Reference

| Apartment Size | Typical Tons | Typical CFM | Common Trunk Size |
| -------------- | ------------ | ----------- | ----------------- |
| Studio/1BR     | 1.0 - 1.5    | 400 - 600   | 10×8"             |
| 2BR            | 1.5 - 2.0    | 600 - 800   | 12×8"             |
| 3BR            | 2.0 - 2.5    | 800 - 1000  | 14×10"            |
| Large 3BR+     | 2.5 - 3.0    | 1000 - 1200 | 16×10"            |

### Apartment Auto-Resize Script

Complete script optimized for apartment/residential use:

```python
"""
Auto-resize ducts for apartment unit.
Optimized for residential with height-locked approach.

For use with Dynamo Python Script node.
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Mechanical import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from typing import List, Dict, Tuple, Optional

# === CONSTANTS ===
INCHES_TO_FEET = 1/12  # 0.0833333
FEET_TO_INCHES = 12

# Lower velocity limits for residential (noise consideration) - in FPM
MAX_TRUNK_VELOCITY_FPM = 1200    # FPM (vs 1500 commercial)
MAX_BRANCH_VELOCITY_FPM = 1000   # FPM (vs 1200 commercial)
MAX_RUNOUT_VELOCITY_FPM = 700    # FPM (vs 800 commercial)

STANDARD_SIZE_INCREMENT = 2   # inches


def resize_apartment_ducts(
    equipment_id: ElementId,
    new_cfm: float,
    old_cfm: float = None
) -> Dict:
    """
    Resize all ducts connected to apartment equipment.
    Uses height-locked approach suitable for residential.

    Args:
        equipment_id: ElementId of mechanical equipment
        new_cfm: Target CFM after resize
        old_cfm: Optional current CFM. If None, reads from model.

    Returns:
        Dictionary with results summary
    """
    doc = DocumentManager.Instance.CurrentDBDocument
    results = {
        "success": False,
        "old_cfm": 0,
        "new_cfm": new_cfm,
        "scale_factor": 0,
        "terminals_updated": [],
        "ducts_resized": [],
        "warnings": []
    }

    # Get equipment and connected system
    equipment = doc.GetElement(equipment_id)
    system = get_supply_system(equipment)

    if not system:
        results["warnings"].append("No supply system found connected to equipment")
        return results

    # Collect ducts and terminals from system
    ducts = []
    terminals = []

    for elem_id in system.Elements:
        elem = doc.GetElement(elem_id)
        cat_id = elem.Category.Id.IntegerValue

        if cat_id == int(BuiltInCategory.OST_DuctCurves):
            ducts.append(elem)
        elif cat_id == int(BuiltInCategory.OST_DuctTerminal):
            terminals.append(elem)

    # Determine old CFM if not provided
    if old_cfm is None or old_cfm <= 0:
        # Method 1: Try equipment parameter
        old_cfm = get_equipment_cfm(equipment)

        # Method 2: Fall back to terminal sum
        if old_cfm is None or old_cfm <= 0:
            old_cfm = sum(get_terminal_cfm(t) for t in terminals)

    if old_cfm <= 0:
        results["warnings"].append("Could not determine current CFM from model")
        return results

    results["old_cfm"] = old_cfm
    scale_factor = new_cfm / old_cfm
    results["scale_factor"] = scale_factor

    # Start transaction
    TransactionManager.Instance.EnsureInTransaction(doc)

    try:
        # 1. Update terminal CFMs (proportional scaling)
        for terminal in terminals:
            terminal_old_cfm = get_terminal_cfm(terminal)
            terminal_new_cfm = terminal_old_cfm * scale_factor

            set_terminal_cfm(terminal, terminal_new_cfm)

            results["terminals_updated"].append({
                "id": str(terminal.Id.IntegerValue),
                "old_cfm": round(terminal_old_cfm, 1),
                "new_cfm": round(terminal_new_cfm, 1)
            })

        # 2. Resize ducts (height locked, adjust width only)
        for duct in ducts:
            duct_result = resize_single_duct(duct, scale_factor)
            results["ducts_resized"].append(duct_result)

            if duct_result.get("warning"):
                results["warnings"].append(duct_result["warning"])

        TransactionManager.Instance.TransactionTaskDone()
        results["success"] = True

    except Exception as e:
        results["warnings"].append(f"Error during resize: {str(e)}")
        TransactionManager.Instance.ForceCloseTransaction()

    return results


def resize_single_duct(duct: Duct, scale_factor: float) -> Dict:
    """
    Resize a single duct segment with height locked.

    Args:
        duct: The duct element
        scale_factor: CFM scale factor (new/old)

    Returns:
        Dictionary with duct resize details
    """
    result = {
        "id": str(duct.Id.IntegerValue),
        "old_dims": "",
        "new_dims": "",
        "velocity_fpm": 0,
        "warning": None
    }

    # Get current dimensions
    height_param = duct.get_Parameter(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)
    width_param = duct.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
    flow_param = duct.get_Parameter(BuiltInParameter.RBS_DUCT_FLOW_PARAM)

    if not all([height_param, width_param]):
        result["warning"] = f"Duct {duct.Id} missing dimension parameters"
        return result

    height_in = height_param.AsDouble() * FEET_TO_INCHES
    current_width_in = width_param.AsDouble() * FEET_TO_INCHES

    # Get current flow and scale it
    current_cfm = flow_param.AsDouble() * 60 if flow_param else 0
    new_cfm = current_cfm * scale_factor

    result["old_dims"] = f"{current_width_in:.0f}×{height_in:.0f}\""

    # Calculate new width (height stays locked)
    new_width_in = calculate_width_for_cfm(new_cfm, height_in, MAX_BRANCH_VELOCITY_FPM)

    # Round to standard size (2-inch increments)
    new_width_in = round_to_standard(new_width_in)

    # Ensure minimum size
    new_width_in = max(4, new_width_in)

    result["new_dims"] = f"{new_width_in:.0f}×{height_in:.0f}\""

    # Calculate resulting velocity in FPM
    area_ft2 = (new_width_in / 12) * (height_in / 12)
    velocity_fpm = new_cfm / area_ft2 if area_ft2 > 0 else 0
    result["velocity_fpm"] = round(velocity_fpm, 0)

    # Check velocity limits
    if velocity_fpm > MAX_BRANCH_VELOCITY_FPM:
        result["warning"] = f"Duct {duct.Id} velocity {velocity_fpm:.0f} FPM exceeds {MAX_BRANCH_VELOCITY_FPM} FPM limit"

    # Apply new width
    if not width_param.IsReadOnly:
        width_param.Set(new_width_in * INCHES_TO_FEET)

    return result


def get_supply_system(equipment: FamilyInstance) -> Optional[MechanicalSystem]:
    """Get supply air system from equipment."""
    try:
        connectors = equipment.MEPModel.ConnectorManager.Connectors
        for conn in connectors:
            if conn.Direction == FlowDirectionType.Out and conn.MEPSystem:
                return conn.MEPSystem
    except:
        pass
    return None


def get_equipment_cfm(equipment: FamilyInstance) -> Optional[float]:
    """Get CFM from equipment parameter."""
    param_names = [
        "Airflow", "Air Flow", "CFM",
        "Supply Air Flow", "Supply Airflow",
        "Total Airflow", "Nominal Airflow"
    ]

    # Try built-in parameter
    flow_param = equipment.get_Parameter(BuiltInParameter.RBS_DUCT_FLOW_PARAM)

    # Try common parameter names
    if not flow_param or not flow_param.HasValue:
        for name in param_names:
            flow_param = equipment.LookupParameter(name)
            if flow_param and flow_param.HasValue:
                break

    if flow_param and flow_param.HasValue:
        value = flow_param.AsDouble()
        return value * 60 if value < 50 else value  # Convert if ft³/s

    return None


def get_terminal_cfm(terminal: FamilyInstance) -> float:
    """Get terminal flow in CFM."""
    param = terminal.get_Parameter(BuiltInParameter.RBS_DUCT_FLOW_PARAM)
    return param.AsDouble() * 60 if param and param.HasValue else 0


def set_terminal_cfm(terminal: FamilyInstance, cfm: float) -> None:
    """Set terminal flow from CFM value."""
    param = terminal.get_Parameter(BuiltInParameter.RBS_DUCT_FLOW_PARAM)
    if param and not param.IsReadOnly:
        param.Set(cfm / 60)  # CFM to ft³/s


def calculate_width_for_cfm(cfm: float, height_in: float, max_velocity_fpm: float) -> float:
    """Calculate required width (inches) given locked height and velocity limit."""
    # Required area in ft² = CFM / FPM
    required_area_ft2 = cfm / max_velocity_fpm
    # Convert to in² (1 ft² = 144 in²)
    required_area_in2 = required_area_ft2 * 144
    # Width = Area / Height
    width_in = required_area_in2 / height_in if height_in > 0 else 0
    return width_in


def round_to_standard(dimension_in: float, increment: float = 2) -> float:
    """Round to nearest standard duct size (2-inch increments)."""
    return round(dimension_in / increment) * increment


# === DYNAMO INTERFACE ===
# Uncomment these lines when using in Dynamo:

# equipment_id = UnwrapElement(IN[0]).Id  # Equipment element from Dynamo
# new_cfm = IN[1]                          # New target CFM
# old_cfm = IN[2] if len(IN) > 2 else None # Optional: current CFM

# OUT = resize_apartment_ducts(equipment_id, new_cfm, old_cfm)
```

### Apartment Workflow Summary

```
┌─────────────────────────────────────────────────────────────────┐
│              Apartment Duct Resize Workflow                     │
│                                                                 │
│  1. Select mechanical unit (WSHP, FCU, mini-split)              │
│     └─ Script reads current CFM from terminals or equipment     │
│                          │                                      │
│                          ▼                                      │
│  2. User provides new target CFM                                │
│     └─ Based on new equipment selection or load calc            │
│                          │                                      │
│                          ▼                                      │
│  3. Calculate scale factor automatically                        │
│     └─ scale = new_cfm / current_cfm                            │
│                          │                                      │
│                          ▼                                      │
│  4. Scale all terminal CFMs proportionally                      │
│     └─ Maintains room-to-room balance                           │
│                          │                                      │
│                          ▼                                      │
│  5. Resize ducts with HEIGHT LOCKED                             │
│     └─ Only width changes (apartment ceiling constraint)        │
│     └─ Round to 2-inch increments                               │
│                          │                                      │
│                          ▼                                      │
│  6. Validate velocities                                         │
│     └─ Warn if > 1000 FPM (noise in residential)                │
│                          │                                      │
│                          ▼                                      │
│  7. Return summary report                                       │
└─────────────────────────────────────────────────────────────────┘
```

### Recommended Settings for Apartments

```python
# Apartment-specific configuration
APARTMENT_SETTINGS = {
    "lock_dimension": "height",          # Always lock height in apartments
    "sizing_method": "velocity",
    "round_to_standard_sizes": True,
    "standard_size_increment": 2,        # inches
    "max_aspect_ratio": 4.0,

    # Lower velocities for residential (noise) - in FPM
    "velocity_limits": {
        "trunk": 1200,    # FPM (vs 1500 commercial)
        "branch": 1000,   # FPM (vs 1200 commercial)
        "runout": 700     # FPM (vs 800 commercial)
    },

    # Terminal distribution
    "terminal_distribution": "proportional",
    "min_terminal_cfm": 50,    # CFM
    "max_terminal_cfm": 400    # CFM
}
```
