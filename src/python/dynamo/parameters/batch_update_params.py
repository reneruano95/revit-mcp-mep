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

# Get all mechanical equipment
mech_equipment = (
    FilteredElementCollector(doc)
    .OfCategory(BuiltInCategory.OST_MechanicalEquipment)
    .WhereElementIsNotElementType()
    .ToElements()
)

print(f"Found {len(mech_equipment)} mechanical equipment elements")

# Start transaction
TransactionManager.Instance.EnsureInTransaction(doc)

# Update parameters
updated_count = 0
for eq in mech_equipment:
    name_param = eq.LookupParameter(PARAM_ROOM_NAME)
    number_param = eq.LookupParameter(PARAM_ROOM_NUMBER)

    if name_param and number_param:
        # Example: Set parameter values based on some logic
        # Here we're just setting sample values
        name_param.Set("Sample Room")
        number_param.Set("R101")
        updated_count += 1

# Complete transaction
TransactionManager.Instance.TransactionTaskDone()

print(f"Updated {updated_count} equipment elements")
OUT = updated_count
