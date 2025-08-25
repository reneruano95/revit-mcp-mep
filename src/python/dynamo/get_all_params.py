import clr

clr.AddReference("RevitServices")
clr.AddReference("RevitAPI")
clr.AddReference("RevitNodes")

from RevitServices.Persistence import DocumentManager
from Autodesk.Revit.DB import *

doc = DocumentManager.Instance.CurrentDBDocument

# Get first mechanical equipment as an example
mech_equipment = (
    FilteredElementCollector(doc)
    .OfCategory(BuiltInCategory.OST_MechanicalEquipment)
    .WhereElementIsNotElementType()
    .FirstElement()
)

if mech_equipment:
    # Get all parameters
    parameters = mech_equipment.Parameters

    # Create a list to store parameter details
    param_details = []

    # Map for storage type values
    storage_type_names = {
        0: "None",
        1: "Integer",
        2: "Double",
        3: "String",
        4: "ElementId",
    }

    # Loop through each parameter
    for param in parameters:
        # Get parameter details
        param_name = param.Definition.Name
        # Use dictionary to map integer to string name
        param_storage_type = storage_type_names.get(
            param.StorageType, f"Unknown({param.StorageType})"
        )

        # Get parameter value based on storage type
        param_value = None
        if param.HasValue:
            if param.StorageType == StorageType.String:
                param_value = param.AsString()
            elif param.StorageType == StorageType.Integer:
                param_value = param.AsInteger()
            elif param.StorageType == StorageType.Double:
                param_value = param.AsDouble()
            elif param.StorageType == StorageType.ElementId:
                param_value = param.AsElementId().IntegerValue

        # Add to list
        param_details.append(
            {
                "name": param_name,
                "storage_type": param_storage_type,
                "value": param_value,
            }
        )

    # Sort by parameter name
    param_details.sort(key=lambda x: x["name"])

    # Print parameter details
    for i, param in enumerate(param_details):
        print(f"{i+1}. {param['name']} ({param['storage_type']}): {param['value']}")

    OUT = param_details
else:
    print("No mechanical equipment found in the model")
    OUT = None
