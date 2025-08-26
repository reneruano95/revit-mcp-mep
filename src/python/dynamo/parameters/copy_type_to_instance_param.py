import clr

clr.AddReference("RevitServices")
clr.AddReference("RevitAPI")
clr.AddReference("RevitNodes")

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from Autodesk.Revit.DB import *
from Revit.Elements import *

doc = DocumentManager.Instance.CurrentDBDocument

# Define parameters to work with
SOURCE_TYPE_PARAM = (
    BuiltInParameter.ALL_MODEL_MODEL
)  # Source built-in type parameter (Model)
# Alternatively, use a string name for a non-built-in parameter:
# SOURCE_TYPE_PARAM = "YourSourceParamName"
TARGET_INSTANCE_PARAM = "JAL Model"  # Target instance parameter

# Filter criteria
FILTER_TYPE_PARAM = "JAL Equipment ID"
FILTER_TYPE_VALUE = "WSHP RESIDENTIAL"

# Get all mechanical equipment
all_elements = (
    FilteredElementCollector(doc)
    .OfCategory(BuiltInCategory.OST_MechanicalEquipment)
    .WhereElementIsNotElementType()
    .ToElements()
)

print(f"Found {len(all_elements)} total mechanical equipment elements")

# Filter equipment by TYPE parameter "JAL Equipment ID" = "WSHP RESIDENTIAL"
elements = []
for eq in all_elements:
    # Get the type element for each instance
    type_id = eq.GetTypeId()
    eq_type = doc.GetElement(type_id)

    # Check the type parameter
    type_id_param = eq_type.LookupParameter(FILTER_TYPE_PARAM)
    if type_id_param and type_id_param.AsString() == FILTER_TYPE_VALUE:
        elements.append(eq)

print(
    f"Filtered down to {len(elements)} elements with Type {FILTER_TYPE_PARAM} = {FILTER_TYPE_VALUE}"
)

# Group elements by type to avoid redundant parameter lookups
elements_by_type = {}
for element in elements:
    type_id = element.GetTypeId()
    if type_id not in elements_by_type:
        elements_by_type[type_id] = []
    elements_by_type[type_id].append(element)

print(f"Found {len(elements_by_type)} unique element types")

# Statistics
successful_updates = 0
failed_updates = 0
skipped_types = 0
total_instances_updated = 0

# Start transaction
TransactionManager.Instance.EnsureInTransaction(doc)

# Process each type and its elements
for type_id, type_elements in elements_by_type.items():
    element_type = doc.GetElement(type_id)

    # Get element type name safely
    type_name = "Unknown Type"
    try:
        type_name = element_type.Name
    except:
        type_name = f"TypeId: {type_id.IntegerValue}"

    # Get source parameter value from the type
    if isinstance(SOURCE_TYPE_PARAM, int) or isinstance(
        SOURCE_TYPE_PARAM, BuiltInParameter
    ):
        # For built-in parameters
        source_param = element_type.get_Parameter(SOURCE_TYPE_PARAM)
    else:
        # For custom parameters
        source_param = element_type.LookupParameter(SOURCE_TYPE_PARAM)

    if not source_param or not source_param.HasValue:
        print(f"Type {type_name}: Source parameter missing or empty, skipping")
        skipped_types += 1
        continue

    # Get parameter value based on storage type
    if source_param.StorageType == StorageType.String:
        param_value = source_param.AsString()
    elif source_param.StorageType == StorageType.Integer:
        param_value = source_param.AsInteger()
    elif source_param.StorageType == StorageType.Double:
        param_value = source_param.AsDouble()
    elif source_param.StorageType == StorageType.ElementId:
        param_value = source_param.AsElementId()
    else:
        print(f"Type {type_name}: Unsupported parameter type")
        failed_updates += 1
        continue

    # Apply the type parameter value to all instances of this type
    successful_instances = 0
    failed_instances = 0

    for instance in type_elements:
        # Get target parameter on instance
        target_param = instance.LookupParameter(TARGET_INSTANCE_PARAM)

        if not target_param:
            print(f"Element {instance.Id.IntegerValue}: Target parameter not found")
            failed_instances += 1
            continue

        # Set the parameter value
        try:
            target_param.Set(param_value)
            successful_instances += 1
        except Exception as e:
            print(f"Element {instance.Id.IntegerValue}: Error - {str(e)}")
            failed_instances += 1

    print(
        f"Type {type_name}: Updated {successful_instances} instances with value '{param_value}', {failed_instances} failed"
    )

    total_instances_updated += successful_instances
    if successful_instances > 0:
        successful_updates += 1
    else:
        failed_updates += 1

# Complete transaction
TransactionManager.Instance.TransactionTaskDone()

# Output results
OUT = {
    "total_elements": len(elements),
    "unique_types": len(elements_by_type),
    "successful_updates": successful_updates,
    "failed_updates": failed_updates,
    "skipped_types": skipped_types,
    "total_instances_updated": total_instances_updated,
}
