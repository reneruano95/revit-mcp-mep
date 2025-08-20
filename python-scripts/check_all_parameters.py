import clr

clr.AddReference("RevitServices")
clr.AddReference("RevitAPI")
clr.AddReference("RevitNodes")

from RevitServices.Persistence import DocumentManager
from Autodesk.Revit.DB import *

doc = DocumentManager.Instance.CurrentDBDocument

# Parameter names to find
PARAM_ROOM_NAME = "JAL_Room Name"
PARAM_ROOM_NUMBER = "JAL_Room Number"

# Get first mechanical equipment and its type
mech_eq = (
    FilteredElementCollector(doc)
    .OfCategory(BuiltInCategory.OST_MechanicalEquipment)
    .WhereElementIsNotElementType()
    .FirstElement()
)

if mech_eq:
    # Get element type
    type_id = mech_eq.GetTypeId()
    mech_type = doc.GetElement(type_id)

    # Check instance parameters
    instance_params = {}
    print("\n=== INSTANCE PARAMETERS ===")
    for param in mech_eq.Parameters:
        param_name = param.Definition.Name
        instance_params[param_name] = param
        print(f"- {param_name}")

    # Check type parameters
    type_params = {}
    print("\n=== TYPE PARAMETERS ===")
    for param in mech_type.Parameters:
        param_name = param.Definition.Name
        type_params[param_name] = param
        print(f"- {param_name}")

    # Check for our specific parameters
    print("\n=== PARAMETER CHECK ===")
    room_name_instance = PARAM_ROOM_NAME in instance_params
    room_name_type = PARAM_ROOM_NAME in type_params
    room_number_instance = PARAM_ROOM_NUMBER in instance_params
    room_number_type = PARAM_ROOM_NUMBER in type_params

    print(f"{PARAM_ROOM_NAME} as instance parameter: {room_name_instance}")
    print(f"{PARAM_ROOM_NAME} as type parameter: {room_name_type}")
    print(f"{PARAM_ROOM_NUMBER} as instance parameter: {room_number_instance}")
    print(f"{PARAM_ROOM_NUMBER} as type parameter: {room_number_type}")

    # Check project parameters
    print("\n=== PROJECT PARAMETERS ===")
    project_params = doc.ParameterBindings
    param_count = project_params.Size
    print(f"Total project parameters: {param_count}")

    param_iterator = project_params.ForwardIterator()
    param_iterator.Reset()

    found_room_name = False
    found_room_number = False

    while param_iterator.MoveNext():
        definition = param_iterator.Key
        binding = param_iterator.Current

        param_name = definition.Name
        if param_name == PARAM_ROOM_NAME:
            found_room_name = True
        if param_name == PARAM_ROOM_NUMBER:
            found_room_number = True

        # Check if this parameter is bound to mechanical equipment
        is_bound_to_mech = False
        if isinstance(binding, InstanceBinding) or isinstance(binding, TypeBinding):
            if binding.Categories.Contains(
                ElementId(BuiltInCategory.OST_MechanicalEquipment)
            ):
                is_bound_to_mech = True

        print(f"- {param_name} (Bound to mech equipment: {is_bound_to_mech})")

    print(f"\n{PARAM_ROOM_NAME} found as project parameter: {found_room_name}")
    print(f"{PARAM_ROOM_NUMBER} found as project parameter: {found_room_number}")

    OUT = {
        "instance_parameters": list(instance_params.keys()),
        "type_parameters": list(type_params.keys()),
        "found_room_name": room_name_instance or room_name_type or found_room_name,
        "found_room_number": room_number_instance
        or room_number_type
        or found_room_number,
    }
else:
    print("No mechanical equipment found")
    OUT = None
