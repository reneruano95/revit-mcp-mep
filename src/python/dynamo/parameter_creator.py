"""
Revit Parameter Creator Module
Creates individual parameters with configurable name and scope (instance/type)
Compatible with Revit 2022+ using modern ForgeTypeId API
"""

import clr

clr.AddReference("RevitServices")
clr.AddReference("RevitAPI")
clr.AddReference("RevitNodes")

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from Autodesk.Revit.DB import *


class ParameterCreator:
    """Creates individual parameters with specified name and scope"""

    def __init__(self, doc=None):
        self.doc = doc or DocumentManager.Instance.CurrentDBDocument
        self.app = self.doc.Application

        # Common parameter data types using modern API
        self.data_types = {
            "text": SpecTypeId.String.Text,
            "number": SpecTypeId.Number,
            "yesno": SpecTypeId.Boolean.YesNo,
        }

        # Parameter groups using modern GroupTypeId (Revit 2024+)
        self.parameter_groups = {
            "general": BuiltInParameterGroup.PG_GENERAL,
            "identity": BuiltInParameterGroup.PG_IDENTITY_DATA,
            "mechanical": BuiltInParameterGroup.PG_MECHANICAL,
            "electrical": BuiltInParameterGroup.PG_ELECTRICAL,
            "plumbing": BuiltInParameterGroup.PG_PLUMBING,
            "dimensions": BuiltInParameterGroup.PG_GEOMETRY,
            "phasing": BuiltInParameterGroup.PG_PHASING,
            "construction": BuiltInParameterGroup.PG_CONSTRUCTION,
            "graphics": BuiltInParameterGroup.PG_GRAPHICS,
        }

    def check_shared_parameter_file(self):
        """Check if shared parameter file is configured"""
        shared_param_file = self.app.SharedParametersFilename
        if not shared_param_file:
            return (
                False,
                "No shared parameter file is set. Please configure one in Revit: Manage > Shared Parameters > Create/Browse.",
            )

        try:
            def_file = self.app.OpenSharedParameterFile()
            if not def_file:
                return False, f"Cannot open shared parameter file: {shared_param_file}"
            return True, "Shared parameter file is accessible"
        except Exception as e:
            return False, f"Error accessing shared parameter file: {str(e)}"

    def get_or_create_parameter_group(self, group_name="JAL_Parameters"):
        """Get existing or create new parameter group in shared parameter file"""
        def_file = self.app.OpenSharedParameterFile()
        if not def_file:
            return None, "Cannot open shared parameter file"

        # Look for existing group
        for group in def_file.Groups:
            if group.Name == group_name:
                return group, f"Found existing group: {group_name}"

        # Create new group
        try:
            new_group = def_file.Groups.Create(group_name)
            return new_group, f"Created new group: {group_name}"
        except Exception as e:
            return None, f"Error creating group: {str(e)}"

    def parameter_exists_in_category(self, param_name, category):
        """Check if parameter exists in a specific category"""
        sample_element = (
            FilteredElementCollector(self.doc)
            .OfCategory(category)
            .WhereElementIsNotElementType()
            .FirstElement()
        )

        if sample_element:
            return sample_element.LookupParameter(param_name) is not None
        return False

    def create_parameter(
        self,
        param_name,
        param_type="text",
        scope="instance",
        categories=None,
        group_name="JAL_Parameters",
        parameter_group="identity",
    ):
        """
        Create a new shared parameter

        Args:
            param_name (str): Name of the parameter
            param_type (str): Data type (text, number, integer, etc.)
            scope (str): "instance" or "type"
            categories (list): List of BuiltInCategory values
            group_name (str): Shared parameter group name
            parameter_group (str): Revit parameter group for organization

        Returns:
            dict: Result with success status and details
        """

        # Validate inputs
        if not param_name:
            return {"success": False, "message": "Parameter name cannot be empty"}

        if param_type.lower() not in self.data_types:
            available_types = ", ".join(self.data_types.keys())
            return {
                "success": False,
                "message": f"Invalid parameter type. Available: {available_types}",
            }

        if scope.lower() not in ["instance", "type"]:
            return {"success": False, "message": "Scope must be 'instance' or 'type'"}

        if parameter_group.lower() not in self.parameter_groups:
            available_groups = ", ".join(self.parameter_groups.keys())
            return {
                "success": False,
                "message": f"Invalid parameter group. Available: {available_groups}",
            }

        # Default to mechanical equipment if no categories specified
        if categories is None:
            categories = [BuiltInCategory.OST_MechanicalEquipment]

        # Check shared parameter file
        file_ok, file_msg = self.check_shared_parameter_file()
        if not file_ok:
            return {"success": False, "message": file_msg}

        # Check if parameter already exists
        existing_params = []
        for category in categories:
            if self.parameter_exists_in_category(param_name, category):
                cat_name = str(category).replace("BuiltInCategory.OST_", "")
                existing_params.append(cat_name)

        if existing_params:
            return {
                "success": False,
                "message": f"Parameter '{param_name}' already exists in categories: {', '.join(existing_params)}",
            }

        try:
            # Get or create parameter group
            param_group, group_msg = self.get_or_create_parameter_group(group_name)
            if not param_group:
                return {"success": False, "message": group_msg}

            # Check if definition already exists in group
            existing_def = None
            for definition in param_group.Definitions:
                if definition.Name == param_name:
                    existing_def = definition
                    break

            # Create external definition if needed
            if not existing_def:
                spec_type_id = self.data_types[param_type.lower()]
                options = ExternalDefinitionCreationOptions(param_name, spec_type_id)
                external_def = param_group.Definitions.Create(options)

                if not external_def:
                    return {
                        "success": False,
                        "message": f"Failed to create parameter definition for '{param_name}'",
                    }
            else:
                external_def = existing_def

            # Start transaction for binding
            TransactionManager.Instance.EnsureInTransaction(self.doc)

            try:
                # Create category set
                category_set = self.app.Create.NewCategorySet()
                bound_categories = []

                for cat in categories:
                    category = Category.GetCategory(self.doc, cat)
                    if category:
                        category_set.Insert(category)
                        bound_categories.append(
                            str(cat).replace("BuiltInCategory.OST_", "")
                        )

                if category_set.Size == 0:
                    TransactionManager.Instance.TransactionTaskDone()
                    return {"success": False, "message": "No valid categories found"}

                # Create binding based on scope
                if scope.lower() == "instance":
                    binding = self.app.Create.NewInstanceBinding(category_set)
                else:
                    binding = self.app.Create.NewTypeBinding(category_set)

                # Get parameter group enum
                param_group_enum = self.parameter_groups[parameter_group.lower()]

                # Bind parameter
                success = self.doc.ParameterBindings.Insert(
                    external_def, binding, param_group_enum
                )

                if not success:
                    # Try rebind if insert failed
                    success = self.doc.ParameterBindings.ReInsert(
                        external_def, binding, param_group_enum
                    )

                TransactionManager.Instance.TransactionTaskDone()

                if success:
                    return {
                        "success": True,
                        "message": f"Successfully created parameter '{param_name}'",
                        "details": {
                            "name": param_name,
                            "type": param_type,
                            "scope": scope,
                            "categories": bound_categories,
                            "group": group_name,
                            "parameter_group": parameter_group,
                        },
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Failed to bind parameter '{param_name}' to categories",
                    }

            except Exception as e:
                TransactionManager.Instance.TransactionTaskDone()
                return {
                    "success": False,
                    "message": f"Error during parameter binding: {str(e)}",
                }

        except Exception as e:
            return {"success": False, "message": f"Error creating parameter: {str(e)}"}

    def list_available_types(self):
        """Return list of available parameter data types"""
        return list(self.data_types.keys())

    def list_available_groups(self):
        """Return list of available parameter groups"""
        return list(self.parameter_groups.keys())


def create_single_parameter(
    param_name,
    param_type="text",
    scope="instance",
    categories=None,
    group_name="JAL_Parameters",
):
    """
    Convenience function to create a single parameter

    Args:
        param_name (str): Name of the parameter
        param_type (str): Data type (default: "text")
        scope (str): "instance" or "type" (default: "instance")
        categories (list): List of category names or BuiltInCategory values
        group_name (str): Shared parameter group name

    Returns:
        dict: Creation result
    """

    creator = ParameterCreator()

    # Convert category names to BuiltInCategory if needed
    if categories:
        builtin_categories = []
        category_mapping = {
            "mechanical_equipment": BuiltInCategory.OST_MechanicalEquipment,
            "electrical_equipment": BuiltInCategory.OST_ElectricalEquipment,
            "plumbing_fixtures": BuiltInCategory.OST_PlumbingFixtures,
            "duct_terminal": BuiltInCategory.OST_DuctTerminal,
            "lighting_fixtures": BuiltInCategory.OST_LightingFixtures,
            "air_terminals": BuiltInCategory.OST_DuctTerminal,
            "mechanical": BuiltInCategory.OST_MechanicalEquipment,
            "electrical": BuiltInCategory.OST_ElectricalEquipment,
            "plumbing": BuiltInCategory.OST_PlumbingFixtures,
        }

        for cat in categories:
            if isinstance(cat, str):
                cat_lower = cat.lower().replace(" ", "_")
                if cat_lower in category_mapping:
                    builtin_categories.append(category_mapping[cat_lower])
                else:
                    print(f"Warning: Unknown category '{cat}', skipping")
            else:
                builtin_categories.append(cat)

        categories = builtin_categories if builtin_categories else None

    return creator.create_parameter(
        param_name=param_name,
        param_type=param_type,
        scope=scope,
        categories=categories,
        group_name=group_name,
    )


# Example usage functions
def create_room_name_parameter(scope="instance"):
    """Create JAL_Room Name parameter"""
    return create_single_parameter("JAL_Room Name", "text", scope)


def create_room_number_parameter(scope="instance"):
    """Create JAL_Room Number parameter"""
    return create_single_parameter("JAL_Room Number", "text", scope)


def create_power_rating_parameter(scope="instance"):
    """Create power rating parameter for electrical equipment"""
    return create_single_parameter(
        "JAL_Power Rating",
        "electrical_power",
        scope,
        ["electrical_equipment", "mechanical_equipment"],
    )
