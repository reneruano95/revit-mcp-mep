import clr

clr.AddReference("RevitServices")
clr.AddReference("RevitAPI")
clr.AddReference("RevitNodes")
# Add System assembly reference for collections
clr.AddReference("System")

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from Autodesk.Revit.DB import *
from Revit.Elements import *
from Autodesk.Revit.DB import Level as DBLevel

# Add this import for the List generic collection
from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument

# Parameter names and filter criteria
EQUIPMENT_ID_PARAM = "JAL Equipment ID"  # Type parameter to filter by
EQUIPMENT_ID_VALUE = "WSHP RESIDENTIAL"  # Value to filter for
MIN_LEVEL = 9
MAX_LEVEL = 33

# Get all mechanical equipment
all_equipment = (
    FilteredElementCollector(doc)
    .OfCategory(BuiltInCategory.OST_MechanicalEquipment)
    .WhereElementIsNotElementType()
    .ToElements()
)

print(f"Found {len(all_equipment)} total mechanical equipment elements")

# Use Level directly since we already imported * from Autodesk.Revit.DB
all_levels = FilteredElementCollector(doc).OfClass(DBLevel).ToElements()
level_map = {}

for level in all_levels:
    # Try to get level number from name (assuming format like "Level 9")
    level_name = level.Name
    try:
        # Extract level number - different approaches depending on naming convention
        if "Level " in level_name:
            level_num = int(level_name.replace("Level ", ""))
        else:
            # Try to extract any number from the level name
            import re

            numbers = re.findall(r"\d+", level_name)
            if numbers:
                level_num = int(numbers[0])
            else:
                level_num = -1  # No number found

        level_map[level.Id] = level_num
        print(f"Level: {level_name}, Number: {level_num}")
    except ValueError:
        # If we can't extract a number, assign -1
        level_map[level.Id] = -1
        print(f"Level: {level_name}, Number: Could not determine")

# Filter equipment by TYPE parameter Equipment ID and level
filtered_equipment = []
for eq in all_equipment:
    # Get the type element for each instance
    type_id = eq.GetTypeId()
    eq_type = doc.GetElement(type_id)

    # Check the type parameter
    type_id_param = eq_type.LookupParameter(EQUIPMENT_ID_PARAM)
    if type_id_param and type_id_param.AsString() == EQUIPMENT_ID_VALUE:
        # Check if equipment is on levels 9-33
        eq_level_id = eq.LevelId
        if eq_level_id in level_map:
            level_num = level_map[eq_level_id]
            if MIN_LEVEL <= level_num <= MAX_LEVEL:
                filtered_equipment.append(eq)
                print(f"Found equipment to delete on Level {level_num}")

print(
    f"Found {len(filtered_equipment)} equipment with Type Equipment ID = {EQUIPMENT_ID_VALUE} on levels {MIN_LEVEL}-{MAX_LEVEL}"
)

# Delete the filtered equipment
if filtered_equipment:
    delete_count = 0
    error_count = 0

    # Start transaction
    TransactionManager.Instance.EnsureInTransaction(doc)

    # Create a list of element IDs to delete
    ids_to_delete = List[ElementId]()
    for eq in filtered_equipment:
        try:
            # Get element ID for reporting
            eq_id = eq.Id
            eq_level_id = eq.LevelId
            level_num = level_map[eq_level_id]

            # Add to deletion list
            ids_to_delete.Add(eq_id)
            print(
                f"Adding equipment {eq_id.IntegerValue} on level {level_num} to deletion list"
            )
        except Exception as e:
            error_count += 1
            print(f"Error processing equipment: {str(e)}")

    # Perform the deletion
    try:
        deleted_ids = doc.Delete(ids_to_delete)
        delete_count = deleted_ids.Count
        print(f"Successfully deleted {delete_count} equipment elements")
    except Exception as e:
        error_count += 1
        print(f"Error during bulk deletion: {str(e)}")

    # Complete transaction
    TransactionManager.Instance.TransactionTaskDone()

    OUT = {
        "total_equipment": len(all_equipment),
        "filtered_equipment": len(filtered_equipment),
        "deleted": delete_count,
        "errors": error_count,
    }
else:
    print("No equipment found matching the criteria")
    OUT = {
        "total_equipment": len(all_equipment),
        "filtered_equipment": 0,
        "deleted": 0,
        "errors": 0,
    }
