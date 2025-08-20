import clr

clr.AddReference("RevitServices")
clr.AddReference("RevitAPI")
clr.AddReference("RevitNodes")

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from Autodesk.Revit.DB import *

doc = DocumentManager.Instance.CurrentDBDocument

# Parameter names
PARAM_ROOM_NAME = "JAL_Room Name"
PARAM_ROOM_NUMBER = "JAL_Room Number"

# Check if parameters already exist on any mechanical equipment
mech_eq = (
    FilteredElementCollector(doc)
    .OfCategory(BuiltInCategory.OST_MechanicalEquipment)
    .WhereElementIsNotElementType()
    .FirstElement()
)

if mech_eq:
    has_room_name = mech_eq.LookupParameter(PARAM_ROOM_NAME) is not None
    has_room_number = mech_eq.LookupParameter(PARAM_ROOM_NUMBER) is not None

    print(f"Room Name parameter exists: {has_room_name}")
    print(f"Room Number parameter exists: {has_room_number}")

    # To create these parameters, you need to:
    # 1. Add them to a shared parameter file
    # 2. Bind them to the Mechanical Equipment category

    # This is typically done through the Revit UI or through
    # a more complex API workflow that requires file system access
    # and application-level operations

    OUT = {"has_room_name": has_room_name, "has_room_number": has_room_number}
else:
    print("No mechanical equipment found")
    OUT = None
