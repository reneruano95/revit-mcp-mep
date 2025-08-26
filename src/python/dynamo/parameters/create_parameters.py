"""
Revit Custom Parameter Creation Script
Flexible parameter creation with configurable inputs
"""

import clr
import json
from typing import Dict, List, Union, Optional

clr.AddReference("RevitServices")
clr.AddReference("RevitAPI")
clr.AddReference("RevitNodes")

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from Autodesk.Revit.DB import *

# Import parameter creator module
try:
    import sys
    import os

    sys.path.append(os.path.dirname(__file__))
    from python.dynamo.parameters.parameter_creator import ParameterCreator, create_single_parameter

    MODULE_AVAILABLE = True
except ImportError:
    MODULE_AVAILABLE = False
    print("⚠️ Parameter creator module not available")

doc = DocumentManager.Instance.CurrentDBDocument


class CustomParameterManager:
    """Manages custom parameter creation with flexible configurations"""

    def __init__(self):
        self.creator = ParameterCreator() if MODULE_AVAILABLE else None
        self.created_parameters = []
        self.failed_parameters = []

    def create_single_custom_parameter(self, config: Dict) -> Dict:
        """
        Create a single custom parameter from configuration

        Args:
            config: Parameter configuration dict with keys:
                   - name: Parameter name (required)
                   - type: Parameter type (default: "text")
                   - scope: "instance" or "type" (default: "instance")
                   - categories: List of categories or single category (default: ["mechanical_equipment"])
                   - group: Parameter group (default: "JAL_Parameters")
                   - description: Optional description

        Returns:
            Creation result dictionary
        """

        if not MODULE_AVAILABLE:
            return {
                "success": False,
                "message": "Parameter creator module not available",
            }

        # Extract and validate configuration
        param_name = config.get("name", "").strip()
        param_type = config.get("type", "text").lower()
        scope = config.get("scope", "instance").lower()
        categories = config.get("categories", ["mechanical_equipment"])
        group_name = config.get("group", "JAL_Parameters")

        # Ensure categories is a list
        if isinstance(categories, str):
            categories = [categories]

        # Validate required fields
        if not param_name:
            return {"success": False, "message": "Parameter name is required"}

        # Create the parameter
        try:
            result = create_single_parameter(
                param_name=param_name,
                param_type=param_type,
                scope=scope,
                categories=categories,
                group_name=group_name,
            )

            # Track results
            if result["success"]:
                self.created_parameters.append(
                    {"name": param_name, "config": config, "result": result}
                )
            else:
                self.failed_parameters.append(
                    {"name": param_name, "config": config, "result": result}
                )

            return result

        except Exception as e:
            error_result = {
                "success": False,
                "message": f"Error creating parameter '{param_name}': {str(e)}",
            }
            self.failed_parameters.append(
                {"name": param_name, "config": config, "result": error_result}
            )
            return error_result

    def create_multiple_parameters(self, parameter_configs: List[Dict]) -> Dict:
        """
        Create multiple parameters from a list of configurations

        Args:
            parameter_configs: List of parameter configuration dictionaries

        Returns:
            Batch creation results
        """

        results = {
            "success": True,
            "total_count": len(parameter_configs),
            "created_count": 0,
            "failed_count": 0,
            "parameters": [],
        }

        for config in parameter_configs:
            result = self.create_single_custom_parameter(config)
            results["parameters"].append({"config": config, "result": result})

            if result["success"]:
                results["created_count"] += 1
            else:
                results["failed_count"] += 1

        results["success"] = results["failed_count"] == 0
        results["success_rate"] = (
            f"{(results['created_count']/results['total_count']*100):.1f}%"
        )

        return results

    def get_parameter_templates(self) -> Dict[str, List[Dict]]:
        """Get predefined parameter templates for common use cases"""

        return {
            "room_parameters": [
                {
                    "name": "JAL_Room Name",
                    "type": "text",
                    "scope": "instance",
                    "categories": ["all_mep"],
                    "description": "Name of the room where equipment is located",
                },
                {
                    "name": "JAL_Room Number",
                    "type": "text",
                    "scope": "instance",
                    "categories": ["all_mep"],
                    "description": "Number/ID of the room",
                },
                {
                    "name": "JAL_Room Area",
                    "type": "area",
                    "scope": "instance",
                    "categories": ["all_mep"],
                    "description": "Area of the room",
                },
            ],
            "equipment_parameters": [
                {
                    "name": "JAL_Equipment Tag",
                    "type": "text",
                    "scope": "instance",
                    "categories": ["all_mep"],
                    "description": "Unique equipment identifier",
                },
                {
                    "name": "JAL_Manufacturer",
                    "type": "text",
                    "scope": "type",
                    "categories": ["all_mep"],
                    "description": "Equipment manufacturer",
                },
                {
                    "name": "JAL_Model Number",
                    "type": "text",
                    "scope": "type",
                    "categories": ["all_mep"],
                    "description": "Manufacturer model number",
                },
            ],
            "electrical_parameters": [
                {
                    "name": "JAL_Power Rating",
                    "type": "electrical_power",
                    "scope": "instance",
                    "categories": ["electrical_equipment"],
                    "description": "Electrical power rating",
                },
                {
                    "name": "JAL_Voltage",
                    "type": "electrical_voltage",
                    "scope": "instance",
                    "categories": ["electrical_equipment"],
                    "description": "Operating voltage",
                },
                {
                    "name": "JAL_Current",
                    "type": "electrical_current",
                    "scope": "instance",
                    "categories": ["electrical_equipment"],
                    "description": "Operating current",
                },
            ],
            "mechanical_parameters": [
                {
                    "name": "JAL_Flow Rate",
                    "type": "flow",
                    "scope": "instance",
                    "categories": ["mechanical_equipment"],
                    "description": "Fluid flow rate",
                },
                {
                    "name": "JAL_Operating Pressure",
                    "type": "pressure",
                    "scope": "instance",
                    "categories": ["mechanical_equipment"],
                    "description": "Operating pressure",
                },
                {
                    "name": "JAL_Operating Temperature",
                    "type": "temperature",
                    "scope": "instance",
                    "categories": ["mechanical_equipment"],
                    "description": "Operating temperature",
                },
            ],
        }

    def print_summary(self) -> None:
        """Print a summary of parameter creation results"""

        total = len(self.created_parameters) + len(self.failed_parameters)

        print(f"\n{'='*60}")
        print("CUSTOM PARAMETER CREATION SUMMARY")
        print(f"{'='*60}")
        print(f"Total Processed: {total}")
        print(f"✓ Successfully Created: {len(self.created_parameters)}")
        print(f"✗ Failed: {len(self.failed_parameters)}")

        if self.failed_parameters:
            print(f"\nFailed Parameters:")
            for item in self.failed_parameters:
                print(f"  ✗ {item['name']}: {item['result']['message']}")

        if self.created_parameters:
            print(f"\nSuccessfully Created:")
            for item in self.created_parameters:
                config = item["config"]
                print(f"  ✓ {item['name']} ({config['type']}, {config['scope']})")

        print(f"{'='*60}")


# Convenience functions for specific use cases
def create_custom_parameter(
    name: str,
    param_type: str = "text",
    scope: str = "instance",
    categories: Union[str, List[str]] = "mechanical_equipment",
) -> Dict:
    """
    Quick function to create a single custom parameter

    Args:
        name: Parameter name
        param_type: Parameter type (text, number, electrical_power, etc.)
        scope: "instance" or "type"
        categories: Category or list of categories

    Returns:
        Creation result
    """

    manager = CustomParameterManager()
    config = {
        "name": name,
        "type": param_type,
        "scope": scope,
        "categories": categories,
    }

    return manager.create_single_custom_parameter(config)


def create_parameter_set(template_name: str) -> Dict:
    """
    Create a predefined set of parameters

    Args:
        template_name: Name of template set (room_parameters, equipment_parameters, etc.)

    Returns:
        Batch creation results
    """

    manager = CustomParameterManager()
    templates = manager.get_parameter_templates()

    if template_name not in templates:
        return {
            "success": False,
            "message": f"Template '{template_name}' not found. Available: {list(templates.keys())}",
        }

    return manager.create_multiple_parameters(templates[template_name])


def create_parameters_from_config(config_data: Union[Dict, str]) -> Dict:
    """
    Create parameters from configuration data (dict or JSON string)

    Args:
        config_data: Configuration as dict or JSON string

    Returns:
        Creation results
    """

    if isinstance(config_data, str):
        try:
            config_data = json.loads(config_data)
        except json.JSONDecodeError as e:
            return {"success": False, "message": f"Invalid JSON: {str(e)}"}

    manager = CustomParameterManager()

    # Handle single parameter or list of parameters
    if isinstance(config_data, list):
        return manager.create_multiple_parameters(config_data)
    else:
        return manager.create_single_custom_parameter(config_data)


def list_available_templates() -> None:
    """Print available parameter templates"""

    manager = CustomParameterManager()
    templates = manager.get_parameter_templates()

    print("Available Parameter Templates:")
    print("=" * 40)

    for template_name, params in templates.items():
        print(f"\n{template_name.upper()}:")
        for param in params:
            print(f"  • {param['name']} ({param['type']}, {param['scope']})")


def main():
    """
    Enhanced main function focused on custom parameter creation
    """

    print("=== Revit Custom Parameter Creator ===")

    if not MODULE_AVAILABLE:
        print("❌ Parameter creator module not available")
        return {"success": False, "message": "Module not available"}

    # Show available options
    creator = ParameterCreator()
    print(f"\n📋 Available Types: {', '.join(creator.list_available_types()[:8])}...")
    print(f"📂 Available Groups: {', '.join(creator.list_available_groups()[:6])}...")

    # Example usage scenarios:
    print(f"\n🔧 Example Usage Scenarios:")

    # 1. Create room parameters
    print(f"\n1. Creating Room Parameters...")
    room_result = create_parameter_set("room_parameters")
    print(
        f"   Room Parameters: {room_result['created_count']}/{room_result['total_count']} created"
    )

    # 2. Create equipment parameters
    print(f"\n2. Creating Equipment Parameters...")
    equipment_result = create_parameter_set("equipment_parameters")
    print(
        f"   Equipment Parameters: {equipment_result['created_count']}/{equipment_result['total_count']} created"
    )

    # 3. Create custom parameter
    print(f"\n3. Creating Custom Parameter...")
    custom_result = create_custom_parameter(
        name="JAL_Custom_Field",
        param_type="text",
        scope="instance",
        categories="all_mep",
    )
    print(f"   Custom Parameter: {'✓' if custom_result['success'] else '✗'}")

    return {
        "success": True,
        "room_parameters": room_result,
        "equipment_parameters": equipment_result,
        "custom_parameter": custom_result,
    }


# Dynamo/pyRevit compatibility with flexible options
if __name__ == "__main__" or "OUT" in globals():

    # OPTION 1: Create a single custom parameter
    # OUT = create_custom_parameter(
    #     name="JAL_Your_Parameter",
    #     param_type="text",
    #     scope="instance",
    #     categories="mechanical_equipment"
    # )

    # OPTION 2: Create a predefined parameter set
    # OUT = create_parameter_set("room_parameters")  # or equipment_parameters, electrical_parameters, etc.

    # OPTION 3: Create from custom configuration
    # custom_config = [
    #     {"name": "JAL_Custom_1", "type": "text", "scope": "instance", "categories": ["mechanical_equipment"]},
    #     {"name": "JAL_Custom_2", "type": "number", "scope": "type", "categories": ["all_mep"]}
    # ]
    # OUT = create_parameters_from_config(custom_config)

    # OPTION 4: Run interactive examples
    OUT = main()
