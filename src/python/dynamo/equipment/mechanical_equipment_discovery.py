import clr

clr.AddReference("RevitServices")
clr.AddReference("RevitAPI")

from RevitServices.Persistence import DocumentManager
from Autodesk.Revit.DB import *

doc = DocumentManager.Instance.CurrentDBDocument


def safe_get_property(obj, property_name, default="Unknown"):
    """Safely get a property value with fallback"""
    try:
        if obj is None:
            return "None"
        return getattr(obj, property_name, default)
    except:
        return default


def safe_get_name(obj):
    """Safely get Name property"""
    try:
        if obj is None:
            return "None"
        return obj.Name if hasattr(obj, "Name") else "No Name"
    except:
        return "Error Getting Name"


def safe_get_family_name(symbol):
    """Safely get family name from symbol"""
    try:
        if symbol is None:
            return "None"
        if hasattr(symbol, "Family") and symbol.Family is not None:
            return (
                symbol.Family.Name
                if hasattr(symbol.Family, "Name")
                else "No Family Name"
            )
        return "No Family"
    except:
        return "Error Getting Family"


def discover_mechanical_equipment_methods():
    """Explore different ways to find mechanical equipment"""

    results = {}

    try:
        # Check if document is available
        if doc is None:
            return {"success": False, "error": "No active document"}

        # Method 1: FamilySymbol (Types) - What we want for creating variants
        try:
            collector1 = FilteredElementCollector(doc)
            family_symbols = collector1.OfClass(FamilySymbol).OfCategory(
                BuiltInCategory.OST_MechanicalEquipment
            )
            symbol_list = list(family_symbols)

            examples = []
            for s in symbol_list[:5]:  # Limit to first 5 symbols
                try:
                    example = {
                        "name": safe_get_name(s),
                        "family": safe_get_family_name(s),
                        "element_id": s.Id.IntegerValue if s.Id else "No ID",
                    }
                    examples.append(example)
                except Exception as e:
                    examples.append({"error": f"Error processing symbol: {str(e)}"})

            results["family_symbols"] = {
                "count": len(symbol_list),
                "description": "Equipment TYPES available for duplication",
                "examples": examples,
            }
        except Exception as e:
            results["family_symbols"] = {
                "error": f"Error getting family symbols: {str(e)}"
            }

        # Method 2: FamilyInstance (Placed equipment)
        try:
            collector2 = FilteredElementCollector(doc)
            family_instances = collector2.OfClass(FamilyInstance).OfCategory(
                BuiltInCategory.OST_MechanicalEquipment
            )
            instance_list = list(family_instances)

            examples = []
            for inst in instance_list[:5]:  # Limit to first 5 instances
                try:
                    symbol = None
                    try:
                        symbol = inst.Symbol if hasattr(inst, "Symbol") else None
                    except:
                        pass

                    example = {
                        "element_id": inst.Id.IntegerValue if inst.Id else "No ID",
                        "type_name": safe_get_name(symbol),
                        "family": safe_get_family_name(symbol),
                    }
                    examples.append(example)
                except Exception as e:
                    examples.append({"error": f"Error processing instance: {str(e)}"})

            results["family_instances"] = {
                "count": len(instance_list),
                "description": "Equipment INSTANCES placed in the model",
                "examples": examples,
            }
        except Exception as e:
            results["family_instances"] = {
                "error": f"Error getting family instances: {str(e)}"
            }

        # Method 3: All Families in the project
        try:
            collector3 = FilteredElementCollector(doc)
            all_families = collector3.OfClass(Family)
            mech_families = []

            for family in all_families:
                try:
                    if (
                        hasattr(family, "FamilyCategory")
                        and family.FamilyCategory is not None
                    ):
                        cat_id = family.FamilyCategory.Id.IntegerValue
                        if cat_id == int(BuiltInCategory.OST_MechanicalEquipment):
                            mech_families.append(family)
                except:
                    continue

            examples = []
            for f in mech_families[:5]:  # Limit to first 5 families
                try:
                    symbol_ids = []
                    try:
                        symbol_ids = (
                            list(f.GetFamilySymbolIds())
                            if hasattr(f, "GetFamilySymbolIds")
                            else []
                        )
                    except:
                        pass

                    example = {
                        "name": safe_get_name(f),
                        "symbol_count": len(symbol_ids),
                    }
                    examples.append(example)
                except Exception as e:
                    examples.append({"error": f"Error processing family: {str(e)}"})

            results["families"] = {
                "count": len(mech_families),
                "description": "Equipment FAMILIES (.rfa files) loaded in project",
                "examples": examples,
            }
        except Exception as e:
            results["families"] = {"error": f"Error getting families: {str(e)}"}

        return {
            "success": True,
            "recommendation": "Use FamilySymbol for creating variants (duplicating types)",
            "document_title": safe_get_property(doc, "Title", "Unknown Document"),
            "methods": results,
        }

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


# Run the exploration
try:
    OUT = discover_mechanical_equipment_methods()
except Exception as e:
    OUT = {"success": False, "error": f"Failed to run exploration: {str(e)}"}

# Ensure we always return something
if OUT is None:
    OUT = {"success": False, "error": "Function returned None"}
