"""
Revit Mechanical Equipment Variants Creator
Creates multiple equipment variants with different dimensions as type parameters
"""

import clr
from typing import Dict, List, Optional

# Add references with error handling
try:
    clr.AddReference("RevitServices")
    clr.AddReference("RevitAPI")
    clr.AddReference("RevitNodes")

    from RevitServices.Persistence import DocumentManager
    from RevitServices.Transactions import TransactionManager
    from Autodesk.Revit.DB import *
    from Autodesk.Revit.DB.Mechanical import *

    REVIT_AVAILABLE = True
except Exception as e:
    print(f"Error loading Revit references: {e}")
    REVIT_AVAILABLE = False


class MechanicalEquipmentVariantCreator:
    """Creates mechanical equipment variants with dimensional type parameters"""

    def __init__(self):
        if not REVIT_AVAILABLE:
            raise Exception("Revit API not available")

        try:
            self.doc = DocumentManager.Instance.CurrentDBDocument
            if self.doc is None:
                raise Exception("No active Revit document found")

            self.created_types = []
            self.failed_types = []
            self.dimension_parameters = [
                "JAL_Height",
                "JAL_Width",
                "JAL_Length",
                "Height",
                "Width",
                "Length",
            ]

        except Exception as e:
            raise Exception(f"Error initializing creator: {e}")

    def check_family_parameters(self, equipment_family_symbol: FamilySymbol) -> Dict:
        """
        Check which dimension parameters exist in the family

        Args:
            equipment_family_symbol: FamilySymbol to check

        Returns:
            Dictionary with parameter availability
        """
        try:
            param_status = {
                "available_parameters": [],
                "missing_parameters": [],
                "family_name": (
                    equipment_family_symbol.Family.Name
                    if equipment_family_symbol.Family
                    else "Unknown"
                ),
            }

            for param_name in self.dimension_parameters:
                param = equipment_family_symbol.LookupParameter(param_name)
                if param:
                    # Determine parameter type (Type vs Instance)
                    parameter_type = "Type"
                    try:
                        # Check if parameter is shared and instance-level
                        if hasattr(param.Definition, "ParameterType"):
                            # Most family symbol parameters are Type parameters
                            # Instance parameters would only be available on placed instances
                            if param.Definition.VariesAcrossGroups:
                                parameter_type = "Instance"
                            else:
                                parameter_type = "Type"

                        # Additional check using parameter binding
                        if hasattr(param, "IsShared") and param.IsShared:
                            # Shared parameters can be either type or instance
                            parameter_type = "Type (Shared)"

                    except:
                        # Default to Type for family symbol parameters
                        parameter_type = "Type"

                    param_status["available_parameters"].append(
                        {
                            "name": param_name,
                            "parameter": param,
                            "is_readonly": param.IsReadOnly,
                            "storage_type": str(param.StorageType),
                            "parameter_type": parameter_type,
                            "is_shared": getattr(param, "IsShared", False),
                        }
                    )
                else:
                    param_status["missing_parameters"].append(param_name)

            return param_status

        except Exception as e:
            return {
                "error": f"Error checking parameters: {e}",
                "available_parameters": [],
                "missing_parameters": self.dimension_parameters,
                "family_name": "Error",
            }

    def find_mech_equipment_by_family_name(
        self, base_name: str
    ) -> Optional[FamilySymbol]:
        """
        Find a mechanical equipment family symbol by family name only

        Args:
            base_name: Family name to search for

        Returns:
            FamilySymbol if found, None otherwise
        """
        try:
            print(f"Searching for mechanical equipment by family name: '{base_name}'")

            collector = FilteredElementCollector(self.doc)
            family_symbols = collector.OfClass(FamilySymbol).OfCategory(
                BuiltInCategory.OST_MechanicalEquipment
            )

            symbols_list = list(family_symbols)
            print(f"Found {len(symbols_list)} total mechanical equipment types")

            # Print all available equipment for debugging
            print("Available equipment:")
            for i, symbol in enumerate(symbols_list):
                family_name = symbol.Family.Name if symbol.Family else "Unknown"

                print(f"{i+1:3d}. Family: '{family_name}' | Active: {symbol.IsActive}")

            # Search only by family name
            base_name_lower = base_name.lower().strip()

            # 1. Exact family name match (case insensitive)
            for symbol in symbols_list:
                if symbol.Family and symbol.Family.Name.lower() == base_name_lower:
                    print(
                        f"Found exact family name match: (Family: '{symbol.FamilyName}')"
                    )
                    return symbol

            # 2. Partial family name match (case insensitive)
            for symbol in symbols_list:
                if symbol.Family and base_name_lower in symbol.Family.Name.lower():
                    print(
                        f"Found partial family name match: (Family: '{symbol.FamilyName}')"
                    )
                    return symbol

            print(f"No equipment found with family name matching '{base_name}'")
            return None

        except Exception as e:
            print(f"Error searching for equipment: {e}")
            return None

    def get_all_mechanical_equipment_types(self) -> List[FamilySymbol]:
        """
        Get all mechanical equipment family symbols

        Returns:
            List of mechanical equipment FamilySymbols
        """
        try:
            collector = FilteredElementCollector(self.doc)
            family_symbols = collector.OfClass(FamilySymbol).OfCategory(
                BuiltInCategory.OST_MechanicalEquipment
            )

            return list(family_symbols)

        except Exception as e:
            print(f"Error getting equipment types: {e}")
            return []

    def list_all_mechanical_equipment(self) -> List[Dict]:
        """
        Get detailed list of all mechanical equipment for debugging

        Returns:
            List of equipment info dictionaries
        """
        try:
            collector = FilteredElementCollector(self.doc)
            family_symbols = collector.OfClass(FamilySymbol).OfCategory(
                BuiltInCategory.OST_MechanicalEquipment
            )

            print(
                f"Found {family_symbols.GetElementCount()} mechanical equipment types"
            )

            equipment_info = []
            for symbol in family_symbols:
                info = {
                    "family_name": (
                        symbol.FamilyName
                        if hasattr(symbol, "FamilyName")
                        else "No Family Name"
                    ),
                    "element_id": symbol.Id.IntegerValue if symbol.Id else "No ID",
                }
                equipment_info.append(info)

            print(f"Collected equipment info for {len(equipment_info)} types")

            return equipment_info

        except Exception as e:
            print(f"Error listing equipment: {e}")
            return []

    def create_equipment_variant(
        self, base_symbol: FamilySymbol, variant_config: Dict
    ) -> Dict:
        """
        Create a new equipment variant with specified dimensions

        Args:
            base_symbol: Base FamilySymbol to duplicate
            variant_config: Configuration with keys:
                - name: New type name
                - height: Height in feet
                - width: Width in feet
                - length: Length in feet
                - description: Optional description

        Returns:
            Creation result dictionary
        """

        try:
            # Check family parameters first
            param_status = self.check_family_parameters(base_symbol)

            # Start transaction
            TransactionManager.Instance.EnsureInTransaction(self.doc)

            # Duplicate the family symbol
            new_symbol = base_symbol.Duplicate(variant_config["name"])

            # Set dimension parameters if they exist in the family
            dimensions = {
                "JAL_Height": variant_config.get("height", 3.0),
                "JAL_Width": variant_config.get("width", 2.0),
                "JAL_Length": variant_config.get("length", 4.0),
            }

            set_parameters = []
            failed_parameters = []

            # Only try to set parameters that exist in the family
            for param_info in param_status["available_parameters"]:
                param_name = param_info["name"]
                param = param_info["parameter"]

                if param_name in dimensions:
                    value = dimensions[param_name]
                    try:
                        if not param.IsReadOnly:
                            param.Set(value)
                            set_parameters.append(f"{param_name}: {value:.2f}ft")
                        else:
                            failed_parameters.append(f"{param_name} (read-only)")
                    except Exception as e:
                        failed_parameters.append(f"{param_name} (error: {str(e)})")

            # Report missing parameters
            for missing_param in param_status["missing_parameters"]:
                failed_parameters.append(f"{missing_param} (not found in family)")

            # Set description if provided
            description = variant_config.get("description", "")
            if description:
                try:
                    desc_param = new_symbol.LookupParameter("Type Comments")
                    if desc_param and not desc_param.IsReadOnly:
                        desc_param.Set(description)
                        set_parameters.append(f"Description: {description}")
                except:
                    pass

            # Commit transaction
            TransactionManager.Instance.TransactionTaskDone()

            result = {
                "success": True,
                "symbol": new_symbol,
                "name": variant_config["name"],
                "base_name": base_symbol.Name,
                "family_name": param_status["family_name"],
                "dimensions": dimensions,
                "set_parameters": set_parameters,
                "failed_parameters": failed_parameters,
                "available_family_parameters": [
                    p["name"] for p in param_status["available_parameters"]
                ],
                "missing_family_parameters": param_status["missing_parameters"],
                "message": f"Created variant '{variant_config['name']}' successfully",
            }

            self.created_types.append(result)
            return result

        except Exception as e:
            # Ensure transaction is closed
            if TransactionManager.Instance.IsInTransaction:
                TransactionManager.Instance.TransactionTaskDone()

            error_result = {
                "success": False,
                "name": variant_config.get("name", "Unknown"),
                "base_name": base_symbol.Name if base_symbol else "Unknown",
                "message": f"Error creating variant: {str(e)}",
            }

            self.failed_types.append(error_result)
            return error_result

    def create_multiple_variants(
        self, base_symbol: FamilySymbol, variant_configs: List[Dict]
    ) -> Dict:
        """
        Create multiple equipment variants from a base symbol

        Args:
            base_symbol: Base FamilySymbol to duplicate
            variant_configs: List of variant configuration dictionaries

        Returns:
            Batch creation results
        """

        results = {
            "success": True,
            "base_symbol": base_symbol.Name if base_symbol else "None",
            "total_count": len(variant_configs),
            "created_count": 0,
            "failed_count": 0,
            "variants": [],
        }

        if not base_symbol:
            results["success"] = False
            results["message"] = "Base symbol not provided"
            return results

        # Check family parameters before processing
        param_status = self.check_family_parameters(base_symbol)
        results["family_parameter_status"] = param_status

        for config in variant_configs:
            result = self.create_equipment_variant(base_symbol, config)
            results["variants"].append(result)

            if result["success"]:
                results["created_count"] += 1
            else:
                results["failed_count"] += 1

        results["success"] = results["failed_count"] == 0
        results["success_rate"] = (
            f"{(results['created_count']/results['total_count']*100):.1f}%"
        )

        return results

    def get_standard_size_templates(self) -> Dict[str, List[Dict]]:
        """Get predefined size templates for common equipment types"""

        return {
            "hvac_units": [
                {
                    "name": "HVAC-RTU-10",
                    "height": 4.0,
                    "width": 6.0,
                    "length": 8.0,
                    "description": "10 ton rooftop unit",
                },
                {
                    "name": "HVAC-RTU-15",
                    "height": 4.5,
                    "width": 7.0,
                    "length": 10.0,
                    "description": "15 ton rooftop unit",
                },
                {
                    "name": "HVAC-RTU-20",
                    "height": 5.0,
                    "width": 8.0,
                    "length": 12.0,
                    "description": "20 ton rooftop unit",
                },
                {
                    "name": "HVAC-AHU-Small",
                    "height": 6.0,
                    "width": 4.0,
                    "length": 8.0,
                    "description": "Small air handling unit",
                },
                {
                    "name": "HVAC-AHU-Large",
                    "height": 8.0,
                    "width": 6.0,
                    "length": 12.0,
                    "description": "Large air handling unit",
                },
            ],
        }

    def create_equipment_variants_from_template(
        self, base_symbol_name: str, template_name: str
    ) -> Dict:
        """
        Create equipment variants using a predefined template

        Args:
            base_symbol_name: Name of base equipment symbol
            template_name: Name of size template

        Returns:
            Creation results
        """

        # Find base symbol
        base_symbol = self.find_mech_equipment_by_family_name(base_symbol_name)
        if not base_symbol:
            return {
                "success": False,
                "message": f"Base equipment '{base_symbol_name}' not found",
            }

        # Get template
        templates = self.get_standard_size_templates()
        if template_name not in templates:
            return {
                "success": False,
                "message": f"Template '{template_name}' not found. Available: {list(templates.keys())}",
            }

        # Modify variant names to include base name
        variant_configs = []
        base_name = base_symbol.Name
        for config in templates[template_name]:
            new_config = config.copy()
            new_config["name"] = f"{base_name}_{config['name']}"
            variant_configs.append(new_config)

        return self.create_multiple_variants(base_symbol, variant_configs)

    def print_family_parameter_status(self, symbol: FamilySymbol) -> None:
        """Print the status of dimension parameters in a family"""

        param_status = self.check_family_parameters(symbol)

        print(f"\nFamily Parameter Status for '{symbol.Name}':")
        print(f"Family: {param_status['family_name']}")
        print("=" * 50)

        if param_status["available_parameters"]:
            print("✓ Available Parameters:")
            for param_info in param_status["available_parameters"]:
                readonly_status = " (READ-ONLY)" if param_info["is_readonly"] else ""
                print(f"  • {param_info['name']}{readonly_status}")

        if param_status["missing_parameters"]:
            print("✗ Missing Parameters:")
            for param_name in param_status["missing_parameters"]:
                print(f"  • {param_name}")

    def print_summary(self) -> None:
        """Print a summary of variant creation results"""

        total = len(self.created_types) + len(self.failed_types)

        print(f"\n{'='*60}")
        print("MECHANICAL EQUIPMENT VARIANTS SUMMARY")
        print(f"{'='*60}")
        print(f"Total Processed: {total}")
        print(f"✓ Successfully Created: {len(self.created_types)}")
        print(f"✗ Failed: {len(self.failed_types)}")

        if self.failed_types:
            print(f"\nFailed Variants:")
            for item in self.failed_types:
                print(f"  ✗ {item['name']}: {item['message']}")

        if self.created_types:
            print(f"\nSuccessfully Created:")
            for item in self.created_types:
                dims = item["dimensions"]
                set_params = len(item.get("set_parameters", []))
                failed_params = len(item.get("failed_parameters", []))
                print(
                    f"  ✓ {item['name']} (H:{dims['JAL_Height']:.1f}' W:{dims['JAL_Width']:.1f}' L:{dims['JAL_Length']:.1f}') - {set_params} params set, {failed_params} failed"
                )

        print(f"{'='*60}")


def main():
    """
    Safe main function with comprehensive error handling for Dynamo
    """
    try:
        print("=== Mechanical Equipment Variants Creator ===")

        # Check if Revit API is available
        if not REVIT_AVAILABLE:
            return {
                "success": False,
                "message": "Revit API not available",
                "error": "Missing Revit references",
            }

        # Check document availability
        try:
            doc = DocumentManager.Instance.CurrentDBDocument
            if doc is None:
                return {
                    "success": False,
                    "message": "No active Revit document",
                    "error": "Document is None",
                }
        except Exception as e:
            return {
                "success": False,
                "message": "Error accessing document",
                "error": str(e),
            }

        # Initialize creator
        try:
            creator = MechanicalEquipmentVariantCreator()
        except Exception as e:
            return {
                "success": False,
                "message": "Error initializing creator",
                "error": str(e),
            }

        # List equipment
        try:
            equipment_list = creator.list_all_mechanical_equipment()
            print(f"Found {len(equipment_list)} mechanical equipment types")

            result = {
                "success": True,
                "message": f"Found {len(equipment_list)} equipment types",
                "equipment_count": len(equipment_list),
                "equipment_list": equipment_list[:10],  # First 10 for debugging
            }

            # Print equipment list
            print("=== ALL MECHANICAL EQUIPMENT ===")
            for i, eq in enumerate(equipment_list, 1):
                print(
                    f"{i:2d}. Symbol: '{eq['symbol_name']}' | Family: '{eq['family_name']}' | Active: {eq['is_active']}"
                )

            # Test search if equipment exists
            if equipment_list:
                first_equipment_name = equipment_list[0]["symbol_name"]
                found_symbol = creator.find_mech_equipment_by_family_name(
                    first_equipment_name
                )
                result["test_search"] = {
                    "searched_name": first_equipment_name,
                    "found": found_symbol is not None,
                }
                print(
                    f"\nTest search result: {'Found' if found_symbol else 'Not found'}"
                )

            return result

        except Exception as e:
            return {
                "success": False,
                "message": "Error listing equipment",
                "error": str(e),
            }

    except Exception as e:
        return {
            "success": False,
            "message": "Unexpected error in main",
            "error": str(e),
        }


def create_equipment_variants_safe(
    base_equipment_name: str, variant_configs: List[Dict]
) -> Dict:
    """
    Safe wrapper for creating equipment variants
    """
    try:
        if not REVIT_AVAILABLE:
            return {"success": False, "message": "Revit API not available"}

        creator = MechanicalEquipmentVariantCreator()

        # Find base equipment
        base_symbol = creator.find_mech_equipment_by_family_name(base_equipment_name)
        if not base_symbol:
            return {
                "success": False,
                "message": f"Base equipment '{base_equipment_name}' not found",
            }

        return creator.create_multiple_variants(base_symbol, variant_configs)

    except Exception as e:
        return {
            "success": False,
            "message": f"Error creating variants: {e}",
            "error": str(e),
        }


def list_equipment_safe() -> Dict:
    """
    Safe function to list equipment
    """
    try:
        if not REVIT_AVAILABLE:
            return {"success": False, "message": "Revit API not available"}

        creator = MechanicalEquipmentVariantCreator()
        equipment_list = creator.list_all_mechanical_equipment()

        return {
            "success": True,
            "equipment_count": len(equipment_list),
            "equipment_list": equipment_list,
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Error listing equipment: {e}",
            "error": str(e),
        }


def find_mech_equipment_by_family_name_safe(name: str) -> Dict:
    """
    Safe function to find mechanical equipment by name
    """
    try:
        if not REVIT_AVAILABLE:
            return {"success": False, "message": "Revit API not available"}

        creator = MechanicalEquipmentVariantCreator()
        symbol = creator.find_mech_equipment_by_family_name(name)

        if symbol:
            return {"success": True, "equipment": symbol}

        return {"success": False, "message": "Equipment not found"}

    except Exception as e:
        return {
            "success": False,
            "message": f"Error finding equipment: {e}",
            "error": str(e),
        }


def check_family_parameters_safe(name: str) -> Dict:
    """Check family parameters for mechanical equipment"""

    try:
        if not REVIT_AVAILABLE:
            return {"success": False, "message": "Revit API not available"}

        creator = MechanicalEquipmentVariantCreator()
        symbol = creator.find_mech_equipment_by_family_name(name)

        if not symbol:
            return {"success": False, "message": "Equipment not found"}

        # Check family parameters
        family_params = creator.check_family_parameters(symbol)
        return {"success": True, "family_parameters": family_params}

    except Exception as e:
        return {
            "success": False,
            "message": f"Error checking family parameters: {e}",
            "error": str(e),
        }


# Dynamo compatibility with better error handling
try:
    # use example function
    # OUT = find_mech_equipment_by_family_name_safe("hvac_schematic-box")
    # OUT = find_mech_equipment_by_name_safe("HeatRecoveryUnit")
    OUT = check_family_parameters_safe("hvac_schematic-box")

    # Also provide the result in a format Dynamo can handle
    if OUT is None:
        OUT = {"success": False, "message": "Script returned None"}

except Exception as e:
    OUT = {"success": False, "message": f"Script execution error: {e}", "error": str(e)}
