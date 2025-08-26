import clr
from enum import Enum
from typing import List, Dict, Optional, Any

clr.AddReference("RevitServices")
clr.AddReference("RevitAPI")
clr.AddReference("RevitNodes")

from Autodesk.Revit.DB import Element, BuiltInCategory
from RevitServices.Persistence import DocumentManager
from Autodesk.Revit.DB import *


class ParameterTypeFilter(Enum):
    """Filter for parameter types."""

    ALL = "all"
    TYPE = "type"
    INSTANCE = "instance"


class ElementParameterExtractor:
    """Extract and analyze parameters from Revit elements."""

    def __init__(self, doc=None):
        self.doc = doc or DocumentManager.Instance.CurrentDBDocument
        self.storage_type_names = {
            0: "None",
            1: "Integer",
            2: "Double",
            3: "String",
            4: "ElementId",
        }

    def get_element_parameters(self, element: Element) -> List[Dict[str, Any]]:
        """Extract all parameters from a single element."""
        if not element:
            return []

        param_list = []

        for param in element.Parameters:
            param_name = param.Definition.Name
            storage_type = param.StorageType
            storage_type_name = self.storage_type_names.get(
                int(storage_type), "Unknown"
            )

            # Get parameter value based on storage type
            if param.HasValue:
                if storage_type == StorageType.String:
                    value = param.AsString()
                elif storage_type == StorageType.Integer:
                    value = param.AsInteger()
                elif storage_type == StorageType.Double:
                    value = param.AsDouble()
                elif storage_type == StorageType.ElementId:
                    value = param.AsElementId().IntegerValue
                else:
                    value = (
                        str(param.AsValueString())
                        if param.AsValueString()
                        else "No Value"
                    )
            else:
                value = "No Value"

            param_info = {
                "name": param_name,
                "storage_type": storage_type_name,
                "value": value,
            }
            param_list.append(param_info)

        # Sort by parameter name for easier reading
        param_list.sort(key=lambda x: x["name"])
        return param_list

    def get_category_parameters(
        self, category: BuiltInCategory, param_filter=ParameterTypeFilter.TYPE
    ) -> Optional[List[Dict[str, Any]]]:
        """Get parameters from first element of specified category."""

        if not self.doc:
            print("No document available")
            return None

        # Create a filtered element collector
        collector = FilteredElementCollector(self.doc)
        collector.OfCategory(category)

        # Apply parameter type filter
        if param_filter == ParameterTypeFilter.TYPE:
            collector.WhereElementIsElementType()
        elif param_filter == ParameterTypeFilter.INSTANCE:
            collector.WhereElementIsNotElementType()
        elif param_filter == ParameterTypeFilter.ALL:
            pass  # No filter applied, get both types and instances

        # Get the first element
        elements = list(collector)

        if not elements:
            category_name = (
                category.ToString() if hasattr(category, "ToString") else str(category)
            )
            print(f"No elements found in category: {category_name}")
            return None

        first_element = elements[0]

        element_type_name = first_element.GetType().Name
        print(
            f"Found {len(elements)} elements. Analyzing first element: {first_element.Id} (Type: {element_type_name})"
        )

        # Extract parameters from the first element
        param_list = self.get_element_parameters(first_element)

        # Print results
        if param_list:
            print(f"\nParameters for element {first_element.Id}:")
            for i, param in enumerate(param_list, 1):
                print(
                    f"{i}. {param['name']} ({param['storage_type']}): {param['value']}"
                )
        else:
            print("No parameters found")

        return param_list

    def get_mechanical_equipment_parameters(self):
        """Convenience method for mechanical equipment."""
        return self.get_category_parameters(BuiltInCategory.OST_MechanicalEquipment)

    def get_electrical_equipment_parameters(self):
        """Get electrical equipment parameters."""
        return self.get_category_parameters(BuiltInCategory.OST_ElectricalEquipment)

    def get_plumbing_fixtures_parameters(self):
        """Get plumbing fixture parameters."""
        return self.get_category_parameters(BuiltInCategory.OST_PlumbingFixtures)

    def export_to_json(self, parameters, filename):
        """Export parameter data to JSON file."""
        import json

        with open(filename, "w") as f:
            json.dump(parameters, f, indent=2)


# For backward compatibility and Dynamo usage
try:
    extractor = ElementParameterExtractor()

    # Default behavior
    OUT = extractor.get_mechanical_equipment_parameters()

except Exception as e:
    print(f"Error extracting parameters: {type(e).__name__}: {e}")
    import traceback

    traceback.print_exc()  # For debugging
    OUT = None
