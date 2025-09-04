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

    def check_equipment_parameter_status(
        self, equipment_family_symbol: FamilySymbol
    ) -> Dict:
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
            # Collect all mechanical equipment family symbols
            collector = FilteredElementCollector(self.doc)
            family_symbols = collector.OfClass(FamilySymbol).OfCategory(
                BuiltInCategory.OST_MechanicalEquipment
            )

            symbols_list = list(
                family_symbols
            )  # Convert to list for multiple iterations
            print(f"Found {len(symbols_list)} total mechanical equipment types")

            # Print all available equipment for debugging
            print("Available equipment:")
            for i, symbol in enumerate(symbols_list):
                family_name = symbol.Family.Name if symbol.Family else "Unknown"

                print(f"{i+1:3d}. Family: '{family_name}'")

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

    def create_equipment_variant(
        self, base_symbol: FamilySymbol, variant_config: Dict, param_status: Dict = None
    ) -> Dict:
        """
        Create a new equipment variant with specified dimensions

        Args:
            base_symbol: Base FamilySymbol to duplicate
            variant_config: Configuration with keys:
                - name: New type name

        Returns:
            Creation result dictionary
        """

        try:
            # Check family parameters only if not provided
            if param_status is None:
                param_status = self.check_equipment_parameter_status(base_symbol)

            # Start transaction
            TransactionManager.Instance.EnsureInTransaction(self.doc)

            # Duplicate the family symbol
            new_symbol = base_symbol.Duplicate(variant_config["name"])

            # # Set dimension parameters if they exist in the family
            # dimensions = {
            #     "Height": variant_config.get("height", 3.0),
            #     "Width": variant_config.get("width", 2.0),
            #     "Length": variant_config.get("length", 4.0),
            # }

            # set_parameters = []
            # failed_parameters = []

            # # Only try to set parameters that exist in the family
            # for param_info in param_status["available_parameters"]:
            #     param_name = param_info["name"]
            #     param = param_info["parameter"]

            #     if param_name in dimensions:
            #         value = dimensions[param_name]
            #         try:
            #             if not param.IsReadOnly:
            #                 param.Set(value)
            #                 set_parameters.append(f"{param_name}: {value:.2f}ft")
            #             else:
            #                 failed_parameters.append(f"{param_name} (read-only)")
            #         except Exception as e:
            #             failed_parameters.append(f"{param_name} (error: {str(e)})")

            # # Report missing parameters
            # for missing_param in param_status["missing_parameters"]:
            #     failed_parameters.append(f"{missing_param} (not found in family)")

            # # Set description if provided
            # description = variant_config.get("description", "")
            # if description:
            #     try:
            #         desc_param = new_symbol.LookupParameter("Type Comments")
            #         if desc_param and not desc_param.IsReadOnly:
            #             desc_param.Set(description)
            #             set_parameters.append(f"Description: {description}")
            #     except:
            #         pass

            # Commit transaction
            TransactionManager.Instance.TransactionTaskDone()

            result = {
                "success": True,
                "symbol": new_symbol,
                "name": variant_config["name"],
                "family_name": param_status["family_name"],
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
            "base_symbol": base_symbol.FamilyName if base_symbol else "None",
            "total_count": len(variant_configs),
            "created_count": 0,
            "failed_count": 0,
            "variants": [],
        }

        if not base_symbol:
            results["success"] = False
            results["message"] = "Base symbol not provided"
            return results

        # Check family parameters once before processing
        param_status = self.check_equipment_parameter_status(base_symbol)

        for config in variant_configs:
            # Create each variant and collect results
            result = self.create_equipment_variant(base_symbol, config, param_status)
            results["variants"].append(result)

            if result["success"]:
                results["created_count"] += 1
            else:
                results["failed_count"] += 1

        results["success"] = results["failed_count"] == 0

        return results


# Dynamo wrapper functions with error handling
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
        family_params = creator.check_equipment_parameter_status(symbol)
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
    # OUT = check_family_parameters_safe("hvac_schematic-box")

    # creator = MechanicalEquipmentVariantCreator()
    # OUT = creator.get_all_mechanical_equipment_types()

    # Example variant creation
    variant_configs = [
        {
            "name": "WSHP-A",
            "height": 4.0,
            "width": 6.0,
            "length": 8.0,
            "description": "1 Ton water source heat pump",
        },
        {
            "name": "WSHP-B",
            "height": 4.5,
            "width": 7.0,
            "length": 10.0,
            "description": "1.5 Ton water source heat pump",
        },
        {
            "name": "WSHP-C",
            "height": 5.0,
            "width": 8.0,
            "length": 12.0,
            "description": "2 Ton water source heat pump",
        },
    ]
    OUT = create_equipment_variants_safe("hvac_schematic-box", variant_configs)

    # Also provide the result in a format Dynamo can handle
    if OUT is None:
        OUT = {"success": False, "message": "Script returned None"}

except Exception as e:
    OUT = {"success": False, "message": f"Script execution error: {e}", "error": str(e)}
