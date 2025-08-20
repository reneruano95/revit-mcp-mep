import clr

clr.AddReference("RevitServices")
clr.AddReference("RevitAPI")
clr.AddReference("RevitNodes")

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from Autodesk.Revit.DB import *
from Revit.Elements import *

doc = DocumentManager.Instance.CurrentDBDocument

# Parameter names
EQUIPMENT_ID_PARAM = "JAL Equipment ID"  # Type parameter to filter by
EQUIPMENT_ID_VALUE = "WSHP RESIDENTIAL"  # Value to filter for
PARAM_ROOM_NAME = "JAL_Room Name"  # Output parameter
PARAM_ROOM_NUMBER = "JAL_Room Number"  # Output parameter
LINKED_MODEL_NAME = "2321 - HoW - SW 9th St - A"  # Linked architectural model

# Get all mechanical equipment
all_equipment = (
    FilteredElementCollector(doc)
    .OfCategory(BuiltInCategory.OST_MechanicalEquipment)
    .WhereElementIsNotElementType()
    .ToElements()
)

print(f"Found {len(all_equipment)} total mechanical equipment elements")

# Filter equipment by TYPE parameter Equipment ID
filtered_equipment = []
for eq in all_equipment:
    # Get the type element for each instance
    type_id = eq.GetTypeId()
    eq_type = doc.GetElement(type_id)

    # Check the type parameter
    type_id_param = eq_type.LookupParameter(EQUIPMENT_ID_PARAM)
    if type_id_param and type_id_param.AsString() == EQUIPMENT_ID_VALUE:
        filtered_equipment.append(eq)

print(
    f"Found {len(filtered_equipment)} equipment with Type Equipment ID = {EQUIPMENT_ID_VALUE}"
)

# Get linked architectural model
link_instances = FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()
linked_doc = None
transform = None

for link in link_instances:
    print(f"Found link: {link.Name}")
    if LINKED_MODEL_NAME in link.Name:
        linked_doc = link.GetLinkDocument()
        transform = link.GetTotalTransform()
        print(f"Using linked model: {link.Name}")
        break

if not linked_doc:
    print("Error: No linked architectural model found.")
    OUT = "No linked architectural model found."
else:
    # Get all rooms from the linked model
    rooms = (
        FilteredElementCollector(linked_doc)
        .OfCategory(BuiltInCategory.OST_Rooms)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    print(f"Total rooms found in linked model: {len(rooms)}")

    # Group rooms by level for faster lookup
    rooms_by_level = {}
    for room in rooms:
        level_id = room.LevelId
        if level_id not in rooms_by_level:
            rooms_by_level[level_id] = []
        rooms_by_level[level_id].append(room)

    print(f"Rooms organized by {len(rooms_by_level)} levels")

    # Stats for reporting
    updated_elements = []
    processed_count = 0
    updated_count = 0
    error_count = 0
    not_found_count = 0

    # Start transaction
    TransactionManager.Instance.EnsureInTransaction(doc)

    # Process each filtered equipment
    for eq in filtered_equipment:
        location = eq.Location
        if not hasattr(location, "Point") or location.Point is None:
            print(f"Equipment {eq.Id} has no valid location point")
            error_count += 1
            continue

        point = location.Point
        transformed_point = transform.Inverse.OfPoint(point)

        # Get equipment level
        eq_level_id = eq.LevelId
        room_found = False

        # First check rooms on the same level as the equipment
        if eq_level_id in rooms_by_level:
            for room in rooms_by_level[eq_level_id]:
                if room.IsPointInRoom(transformed_point):
                    room_name = room.LookupParameter("Name").AsString()
                    room_number = room.LookupParameter("Number").AsString()
                    print(
                        f"Equipment in room: {room_name} ({room_number}) - same level"
                    )

                    name_param = eq.LookupParameter(PARAM_ROOM_NAME)
                    number_param = eq.LookupParameter(PARAM_ROOM_NUMBER)

                    if name_param:
                        name_param.Set(room_name)
                    else:
                        print(
                            f"Missing '{PARAM_ROOM_NAME}' parameter on equipment: {eq.Id}"
                        )
                        error_count += 1

                    if number_param:
                        number_param.Set(room_number)
                    else:
                        print(
                            f"Missing '{PARAM_ROOM_NUMBER}' parameter on equipment: {eq.Id}"
                        )
                        error_count += 1

                    updated_elements.append(eq)
                    updated_count += 1
                    room_found = True
                    break

        # If no room found on the same level, check other levels
        if not room_found:
            print(
                f"No room found on same level for equipment {eq.Id}, checking other levels"
            )
            for level_id, level_rooms in rooms_by_level.items():
                if level_id == eq_level_id:
                    continue  # Skip already checked level

                for room in level_rooms:
                    if room.IsPointInRoom(transformed_point):
                        room_name = room.LookupParameter("Name").AsString()
                        room_number = room.LookupParameter("Number").AsString()
                        print(
                            f"Equipment in room: {room_name} ({room_number}) - different level"
                        )

                        name_param = eq.LookupParameter(PARAM_ROOM_NAME)
                        number_param = eq.LookupParameter(PARAM_ROOM_NUMBER)

                        if name_param:
                            name_param.Set(room_name)
                        else:
                            print(
                                f"Missing '{PARAM_ROOM_NAME}' parameter on equipment: {eq.Id}"
                            )
                            error_count += 1

                        if number_param:
                            number_param.Set(room_number)
                        else:
                            print(
                                f"Missing '{PARAM_ROOM_NUMBER}' parameter on equipment: {eq.Id}"
                            )
                            error_count += 1

                        updated_elements.append(eq)
                        updated_count += 1
                        room_found = True
                        break

                if room_found:
                    break

        if not room_found:
            print(f"No room found for equipment {eq.Id}")
            not_found_count += 1

        processed_count += 1

    # Complete transaction
    TransactionManager.Instance.TransactionTaskDone()

    # Output results
    OUT = {
        "updated_elements": updated_elements,
        "stats": {
            "total_equipment": len(all_equipment),
            "filtered_equipment": len(filtered_equipment),
            "processed": processed_count,
            "updated": updated_count,
            "not_found": not_found_count,
            "errors": error_count,
            "rooms_by_level": {str(k): len(v) for k, v in rooms_by_level.items()},
        },
    }
