import clr

clr.AddReference("RevitServices")
clr.AddReference("RevitAPI")
clr.AddReference("RevitNodes")

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Plumbing import *
from Revit.Elements import *

doc = DocumentManager.Instance.CurrentDBDocument

# Parameter names
EQUIPMENT_ID_PARAM = "JAL Equipment ID"  # Type parameter to filter by
EQUIPMENT_ID_VALUE = "WSHP RESIDENTIAL"  # Value to filter for
RISER_ID_PARAM = "JAL Riser ID"  # Parameter to transfer from pipes to equipment
LINKED_MODEL_NAME = "2321 - HoW - SW 9th St - A"  # Linked architectural model


def filter_equipment_by_type(doc, param_name, param_value):
    """Filter equipment by type parameter."""
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
        type_id_param = eq_type.LookupParameter(param_name)
        if type_id_param and type_id_param.AsString() == param_value:
            filtered_equipment.append(eq)

    print(
        f"Found {len(filtered_equipment)} equipment with Type Equipment ID = {param_value}"
    )
    return filtered_equipment


def filter_pipes_by_system(doc, riser_id_param_name, systems=["CWS", "CWR"]):
    """Filter pipes by system abbreviation using ElementQuickFilter for better performance."""
    # Start with a collector for all pipes
    collector = (
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_PipeCurves)
        .WhereElementIsNotElementType()
    )

    # Get all pipes for statistics
    all_pipes = collector.ToElements()
    print(f"Found {len(all_pipes)} total pipe elements")

    # Create a filter for each system type and combine them with OR
    system_filters = []
    for system in systems:
        system_filter = ElementParameterFilter(
            ParameterFilterRuleFactory.CreateEqualsRule(
                ElementId(BuiltInParameter.RBS_DUCT_PIPE_SYSTEM_ABBREVIATION_PARAM),
                system,
                True,  # Case insensitive
            )
        )
        system_filters.append(system_filter)

    # Combine system filters with OR if there are multiple systems
    if len(system_filters) > 1:
        combined_filter = LogicalOrFilter(*system_filters)
    else:
        combined_filter = system_filters[0]

    # Apply the filter to get pipes with the correct system abbreviations
    collector = (
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_PipeCurves)
        .WhereElementIsNotElementType()
    )
    filtered_by_system = collector.WherePasses(combined_filter).ToElements()

    print(
        f"Found {len(filtered_by_system)} pipes with System Abbreviation ({'/'.join(systems)})"
    )

    # We still need to check for the Riser ID parameter since we can't filter for custom parameters efficiently
    filtered_pipes = []
    for pipe in filtered_by_system:
        riser_id_param = pipe.LookupParameter(riser_id_param_name)
        if riser_id_param and riser_id_param.AsString():
            filtered_pipes.append(pipe)

    print(
        f"Found {len(filtered_pipes)} pipes with System Abbreviation ({'/'.join(systems)}) and Riser ID"
    )

    return filtered_pipes, all_pipes


def map_pipes_to_rooms(pipes, rooms, transform):
    """Create mapping of pipes to rooms."""
    # Create a dictionary to store pipes by room
    pipes_by_room = {}

    # Find which room each pipe is in
    for pipe in pipes:
        # Get the pipe curve
        curve = pipe.Location.Curve
        # Get the midpoint of the pipe
        pipe_point = curve.Evaluate(0.5, True)
        transformed_point = transform.Inverse.OfPoint(pipe_point)

        # Get pipe level
        pipe_level_id = pipe.ReferenceLevel.Id
        room_found = False

        # First check rooms on the same level as the pipe
        if pipe_level_id in rooms:
            for room in rooms[pipe_level_id]:
                if room.IsPointInRoom(transformed_point):
                    room_id = room.Id.IntegerValue
                    if room_id not in pipes_by_room:
                        pipes_by_room[room_id] = []
                    pipes_by_room[room_id].append(pipe)
                    room_found = True
                    break

        # If no room found on the same level, check other levels
        if not room_found:
            for level_id, level_rooms in rooms.items():
                if level_id == pipe_level_id:
                    continue  # Skip already checked level

                for room in level_rooms:
                    if room.IsPointInRoom(transformed_point):
                        room_id = room.Id.IntegerValue
                        if room_id not in pipes_by_room:
                            pipes_by_room[room_id] = []
                        pipes_by_room[room_id].append(pipe)
                        room_found = True
                        break

                if room_found:
                    break

    print(f"Found pipes in {len(pipes_by_room)} rooms")
    return pipes_by_room


def map_equipment_to_rooms(equipment, rooms, transform):
    """Create mapping of equipment to rooms."""
    # Create a dictionary to store equipment by room
    equipment_by_room = {}

    # Find which room each equipment is in
    for eq in equipment:
        location = eq.Location
        if not hasattr(location, "Point") or location.Point is None:
            print(f"Equipment {eq.Id} has no valid location point")
            continue

        point = location.Point
        transformed_point = transform.Inverse.OfPoint(point)

        # Get equipment level
        eq_level_id = eq.LevelId
        room_found = False

        # First check rooms on the same level as the equipment
        if eq_level_id in rooms:
            for room in rooms[eq_level_id]:
                if room.IsPointInRoom(transformed_point):
                    room_id = room.Id.IntegerValue
                    if room_id not in equipment_by_room:
                        equipment_by_room[room_id] = []
                    equipment_by_room[room_id].append(eq)
                    room_found = True
                    break

        # If no room found on the same level, check other levels
        if not room_found:
            for level_id, level_rooms in rooms.items():
                if level_id == eq_level_id:
                    continue  # Skip already checked level

                for room in level_rooms:
                    if room.IsPointInRoom(transformed_point):
                        room_id = room.Id.IntegerValue
                        if room_id not in equipment_by_room:
                            equipment_by_room[room_id] = []
                        equipment_by_room[room_id].append(eq)
                        room_found = True
                        break

                if room_found:
                    break

    print(f"Found equipment in {len(equipment_by_room)} rooms")
    return equipment_by_room


def get_rooms_by_level(rooms):
    """
    Group rooms by their level ID.

    Args:
        rooms: Collection of room elements.

    Returns:
        Dictionary with level IDs as keys and lists of room elements as values.
    """
    rooms_by_level = {}
    for room in rooms:
        level_id = room.LevelId
        if level_id not in rooms_by_level:
            rooms_by_level[level_id] = []
        rooms_by_level[level_id].append(room)
    return rooms_by_level


# Filter equipment
filtered_equipment = filter_equipment_by_type(
    doc, EQUIPMENT_ID_PARAM, EQUIPMENT_ID_VALUE
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
    OUT = {
        "error": "No linked architectural model found.",
        "stats": {
            "total_equipment": len(filtered_equipment),
            "filtered_equipment": len(filtered_equipment),
        },
    }
    # Return early
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
    rooms_by_level = get_rooms_by_level(rooms)

    print(f"Rooms organized by {len(rooms_by_level)} levels")

    # Filter pipes
    filtered_pipes, all_pipes = filter_pipes_by_system(doc, RISER_ID_PARAM)

    # Map pipes to rooms
    pipes_by_room = map_pipes_to_rooms(filtered_pipes, rooms_by_level, transform)
    
    # Map equipment to rooms (new function to group equipment by room)
    equipment_by_room = map_equipment_to_rooms(filtered_equipment, rooms_by_level, transform)

    # Stats for reporting
    updated_elements = []
    processed_count = 0
    updated_count = 0
    error_count = 0
    not_found_count = 0

    # Start transaction
    TransactionManager.Instance.EnsureInTransaction(doc)

    # Process each room that has both equipment and pipes
    rooms_with_both = set(pipes_by_room.keys()).intersection(set(equipment_by_room.keys()))
    print(f"Found {len(rooms_with_both)} rooms with both equipment and pipes")
    
    for room_id in rooms_with_both:
        # Get room object by searching through all rooms (could be optimized)
        room = None
        for level_rooms in rooms_by_level.values():
            for r in level_rooms:
                if r.Id.IntegerValue == room_id:
                    room = r
                    break
            if room:
                break
                
        if not room:
            print(f"Could not find room with ID {room_id}")
            continue
            
        room_number = room.LookupParameter("Number").AsString()
        room_name = room.LookupParameter("Name").AsString()
        print(f"Processing room {room_number}: {room_name}")
        
        # Get pipes in this room
        pipes_in_room = pipes_by_room[room_id]
        
        # Prioritize CWS pipes over CWR pipes
        cws_pipes = [
            p for p in pipes_in_room
            if p.get_Parameter(BuiltInParameter.RBS_DUCT_PIPE_SYSTEM_ABBREVIATION_PARAM).AsString() == "CWS"
        ]
        
        if cws_pipes:
            pipe = cws_pipes[0]
        else:
            pipe = pipes_in_room[0]
            
        riser_id = pipe.LookupParameter(RISER_ID_PARAM).AsString()
        system_abbr = pipe.get_Parameter(BuiltInParameter.RBS_DUCT_PIPE_SYSTEM_ABBREVIATION_PARAM).AsString()
        
        # Apply to all equipment in this room
        equipment_in_room = equipment_by_room[room_id]
        for eq in equipment_in_room:
            riser_id_param = eq.LookupParameter(RISER_ID_PARAM)
            if riser_id_param:
                # Get current riser ID value from equipment (if any)
                current_riser_id = riser_id_param.AsString()
                
                # Check if equipment already has a riser ID and if it matches the pipe's riser ID
                if current_riser_id and current_riser_id != riser_id:
                    # Riser IDs don't match - set to "Riser ID not Equals"
                    riser_id_param.Set("Riser ID not Equals")
                    print(f"Riser ID mismatch in room {room_number}: Equipment had '{current_riser_id}', pipe has '{riser_id}'. Set to 'Riser ID not Equals'")
                else:
                    # Either no existing riser ID or they match - set to pipe's riser ID
                    riser_id_param.Set(riser_id)
                    print(f"Set Riser ID '{riser_id}' from {system_abbr} pipe to equipment {eq.Id} in room {room_number}")
                
                updated_count += 1
                updated_elements.append(eq)
            else:
                print(f"Missing '{RISER_ID_PARAM}' parameter on equipment: {eq.Id}")
                error_count += 1
                
            processed_count += 1
    
    # Also process equipment in rooms without pipes (mark as not found)
    rooms_with_eq_only = set(equipment_by_room.keys()) - set(pipes_by_room.keys())
    for room_id in rooms_with_eq_only:
        # Get room object
        room = None
        for level_rooms in rooms_by_level.values():
            for r in level_rooms:
                if r.Id.IntegerValue == room_id:
                    room = r
                    break
            if room:
                break
                
        if not room:
            continue
            
        room_number = room.LookupParameter("Number").AsString()
        equipment_in_room = equipment_by_room[room_id]
        for eq in equipment_in_room:
            print(f"No CWS/CWR pipes found in room {room_number} for equipment {eq.Id}")
            not_found_count += 1
            processed_count += 1

    # Complete transaction
    TransactionManager.Instance.TransactionTaskDone()

    # Output results
    OUT = {
        "updated_elements": updated_elements,
        "stats": {
            "total_equipment": len(filtered_equipment),
            "filtered_equipment": len(filtered_equipment),
            "total_pipes": len(all_pipes),
            "filtered_pipes": len(filtered_pipes),
            "rooms_with_pipes": len(pipes_by_room),
            "rooms_with_equipment": len(equipment_by_room),
            "rooms_with_both": len(rooms_with_both),
            "processed": processed_count,
            "updated": updated_count,
            "not_found": not_found_count,
            "errors": error_count,
        },
    }
