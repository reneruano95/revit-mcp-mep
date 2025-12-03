"""
Remove Duplicate Tags in Views
Identifies and removes duplicate tags that reference the same element in a view.
Compatible with Revit 2024+
"""

import clr

clr.AddReference("RevitServices")
clr.AddReference("RevitAPI")
clr.AddReference("RevitNodes")

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from Autodesk.Revit.DB import *

# Add System assembly reference for collections
clr.AddReference("System")
from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument


class DuplicateTagRemover:
    """Removes duplicate tags from Revit views"""

    def __init__(self, doc=None):
        self.doc = doc or DocumentManager.Instance.CurrentDBDocument
        self.removed_count = 0
        self.processed_views = []
        self.errors = []
        
        # Initialize tag category mapping (done in __init__ to avoid issues with class-level API calls)
        self._init_tag_categories()

    def _init_tag_categories(self):
        """Initialize tag category mapping - called at instance creation time"""
        # Tag category mapping for easy reference by name
        self.TAG_CATEGORY_MAP = {
            # MEP - Mechanical
            "mechanical_equipment": BuiltInCategory.OST_MechanicalEquipmentTags,
            "duct": BuiltInCategory.OST_DuctTags,
            "duct_fitting": BuiltInCategory.OST_DuctFittingTags,
            "duct_accessory": BuiltInCategory.OST_DuctAccessoryTags,
            "duct_terminal": BuiltInCategory.OST_DuctTerminalTags,
            "air_terminal": BuiltInCategory.OST_DuctTerminalTags,  # Alias for duct_terminal
            # MEP - Electrical
            "electrical_equipment": BuiltInCategory.OST_ElectricalEquipmentTags,
            "electrical_fixture": BuiltInCategory.OST_ElectricalFixtureTags,
            "lighting_fixture": BuiltInCategory.OST_LightingFixtureTags,
            "cable_tray": BuiltInCategory.OST_CableTrayTags,
            "conduit": BuiltInCategory.OST_ConduitTags,
            # MEP - Plumbing
            "plumbing_fixture": BuiltInCategory.OST_PlumbingFixtureTags,
            "pipe": BuiltInCategory.OST_PipeTags,
            "pipe_fitting": BuiltInCategory.OST_PipeFittingTags,
            "pipe_accessory": BuiltInCategory.OST_PipeAccessoryTags,
            "sprinkler": BuiltInCategory.OST_SprinklerTags,
            # Architectural
            "door": BuiltInCategory.OST_DoorTags,
            "window": BuiltInCategory.OST_WindowTags,
            "room": BuiltInCategory.OST_RoomTags,
            "area": BuiltInCategory.OST_AreaTags,
            "wall": BuiltInCategory.OST_WallTags,
            "floor": BuiltInCategory.OST_FloorTags,
            "ceiling": BuiltInCategory.OST_CeilingTags,
            "furniture": BuiltInCategory.OST_FurnitureTags,
            "casework": BuiltInCategory.OST_CaseworkTags,
            # Structural
            "structural_column": BuiltInCategory.OST_StructuralColumnTags,
            "structural_framing": BuiltInCategory.OST_StructuralFramingTags,
            "structural_foundation": BuiltInCategory.OST_StructuralFoundationTags,
            # Other
            "generic_model": BuiltInCategory.OST_GenericModelTags,
            "specialty_equipment": BuiltInCategory.OST_SpecialityEquipmentTags,
        }

        # Predefined tag groups for convenience
        self.TAG_GROUPS = {
            "all_mep": [
                "mechanical_equipment", "duct", "duct_fitting", "duct_accessory",
                "duct_terminal", "electrical_equipment",
                "electrical_fixture", "lighting_fixture", "cable_tray", "conduit",
                "plumbing_fixture", "pipe", "pipe_fitting", "pipe_accessory", "sprinkler",
            ],
            "mechanical": [
                "mechanical_equipment", "duct", "duct_fitting", "duct_accessory",
                "duct_terminal",
            ],
            "electrical": [
                "electrical_equipment", "electrical_fixture", "lighting_fixture",
                "cable_tray", "conduit",
            ],
            "plumbing": [
                "plumbing_fixture", "pipe", "pipe_fitting", "pipe_accessory", "sprinkler",
            ],
            "architectural": [
                "door", "window", "room", "area", "wall", "floor", "ceiling",
                "furniture", "casework",
            ],
            "structural": [
                "structural_column", "structural_framing", "structural_foundation",
            ],
        }

    def get_all_tag_categories(self):
        """Get all tag categories available in Revit"""
        return list(self.TAG_CATEGORY_MAP.values())

    def resolve_tag_filter(self, tag_filter):
        """
        Resolve tag filter to list of BuiltInCategory values

        Args:
            tag_filter: Can be:
                - None: returns all tag categories
                - str: single tag type name (e.g., "duct") or group name (e.g., "all_mep")
                - list: list of tag type names or BuiltInCategory values

        Returns:
            List of BuiltInCategory values
        """
        if tag_filter is None:
            return self.get_all_tag_categories()

        # If it's a string, check if it's a group or single category
        if isinstance(tag_filter, str):
            tag_filter_lower = tag_filter.lower().replace(" ", "_")
            
            # Check if it's a predefined group
            if tag_filter_lower in self.TAG_GROUPS:
                group_names = self.TAG_GROUPS[tag_filter_lower]
                return [self.TAG_CATEGORY_MAP[name] for name in group_names]
            
            # Check if it's a single category name
            if tag_filter_lower in self.TAG_CATEGORY_MAP:
                return [self.TAG_CATEGORY_MAP[tag_filter_lower]]
            
            # Unknown filter
            raise ValueError(
                f"Unknown tag filter '{tag_filter}'. "
                f"Available types: {list(self.TAG_CATEGORY_MAP.keys())}. "
                f"Available groups: {list(self.TAG_GROUPS.keys())}"
            )

        # If it's a list, resolve each item
        if isinstance(tag_filter, list):
            resolved = []
            for item in tag_filter:
                if isinstance(item, str):
                    item_lower = item.lower().replace(" ", "_")
                    if item_lower in self.TAG_CATEGORY_MAP:
                        resolved.append(self.TAG_CATEGORY_MAP[item_lower])
                    elif item_lower in self.TAG_GROUPS:
                        group_names = self.TAG_GROUPS[item_lower]
                        resolved.extend([self.TAG_CATEGORY_MAP[name] for name in group_names])
                    else:
                        raise ValueError(f"Unknown tag type '{item}'")
                else:
                    # Assume it's already a BuiltInCategory
                    resolved.append(item)
            return resolved

        # If it's already a BuiltInCategory or list of them
        return tag_filter if isinstance(tag_filter, list) else [tag_filter]

    def list_available_tag_types(self):
        """List all available tag type names and groups"""
        return {
            "tag_types": list(self.TAG_CATEGORY_MAP.keys()),
            "tag_groups": {k: v for k, v in self.TAG_GROUPS.items()},
        }

    def get_tags_in_view(self, view, tag_filter=None):
        """
        Get all tags in a specific view

        Args:
            view: The view to search for tags
            tag_filter: Filter for tag types. Can be:
                - None: all tag categories
                - str: tag type name (e.g., "duct") or group (e.g., "all_mep", "mechanical")
                - list: list of tag type names (e.g., ["duct", "pipe"])

        Returns:
            List of IndependentTag elements
        """
        categories = self.resolve_tag_filter(tag_filter)

        all_tags = []

        for category in categories:
            try:
                collector = (
                    FilteredElementCollector(self.doc, view.Id)
                    .OfCategory(category)
                    .WhereElementIsNotElementType()
                )
                tags = list(collector.ToElements())
                all_tags.extend(tags)
            except Exception as e:
                # Some categories may not exist in all projects
                pass

        return all_tags

    def find_duplicate_tags_in_view(self, view, tag_filter=None):
        """
        Find duplicate tags in a view (tags referencing the same element)

        Args:
            view: The view to check
            tag_filter: Filter for tag types. Can be:
                - None: all tag categories
                - str: tag type name (e.g., "duct") or group (e.g., "all_mep", "mechanical")
                - list: list of tag type names (e.g., ["duct", "pipe"])

        Returns:
            Dictionary with hosted element ID as key and list of duplicate tags as value
        """
        tags = self.get_tags_in_view(view, tag_filter)
        
        # Group tags by the element they reference
        tags_by_host = {}
        
        for tag in tags:
            try:
                # Get the element(s) that the tag references
                # Different tag types have different ways to get the host
                host_ids = []
                
                # Try to get tagged element references
                if hasattr(tag, 'GetTaggedLocalElements'):
                    # For multi-reference tags (Revit 2022+)
                    host_elements = tag.GetTaggedLocalElements()
                    for elem in host_elements:
                        host_ids.append(elem.Id.IntegerValue)
                elif hasattr(tag, 'TaggedLocalElementId'):
                    # For single-reference tags
                    host_id = tag.TaggedLocalElementId
                    if host_id and host_id != ElementId.InvalidElementId:
                        host_ids.append(host_id.IntegerValue)
                
                # If we found host elements, group the tags
                for host_id in host_ids:
                    key = (host_id, tag.GetTypeId().IntegerValue)  # Group by host element AND tag type
                    if key not in tags_by_host:
                        tags_by_host[key] = []
                    tags_by_host[key].append(tag)
                    
            except Exception as e:
                self.errors.append(f"Error processing tag {tag.Id}: {str(e)}")

        # Find duplicates (more than one tag for the same element)
        duplicates = {}
        for key, tag_list in tags_by_host.items():
            if len(tag_list) > 1:
                duplicates[key] = tag_list

        return duplicates

    def remove_duplicate_tags_in_view(self, view, tag_filter=None, keep_first=True):
        """
        Remove duplicate tags in a specific view

        Args:
            view: The view to clean
            tag_filter: Filter for tag types. Can be:
                - None: all tag categories
                - str: tag type name (e.g., "duct") or group (e.g., "all_mep", "mechanical")
                - list: list of tag type names (e.g., ["duct", "pipe"])
            keep_first: If True, keep the first tag found; if False, keep the last

        Returns:
            Dictionary with removal statistics
        """
        duplicates = self.find_duplicate_tags_in_view(view, tag_filter)
        
        removed_tags = []
        kept_tags = []
        
        if not duplicates:
            return {
                "view_name": view.Name,
                "duplicates_found": 0,
                "tags_removed": 0,
                "tags_kept": 0,
            }

        TransactionManager.Instance.EnsureInTransaction(self.doc)
        
        try:
            for key, tag_list in duplicates.items():
                # Sort tags by Id to ensure consistent behavior
                tag_list.sort(key=lambda t: t.Id.IntegerValue)
                
                # Determine which tag to keep
                if keep_first:
                    tag_to_keep = tag_list[0]
                    tags_to_remove = tag_list[1:]
                else:
                    tag_to_keep = tag_list[-1]
                    tags_to_remove = tag_list[:-1]
                
                kept_tags.append(tag_to_keep)
                
                # Delete duplicate tags
                for tag in tags_to_remove:
                    try:
                        self.doc.Delete(tag.Id)
                        removed_tags.append(tag.Id.IntegerValue)
                        self.removed_count += 1
                    except Exception as e:
                        self.errors.append(f"Failed to delete tag {tag.Id}: {str(e)}")
                        
        finally:
            TransactionManager.Instance.TransactionTaskDone()
        
        self.processed_views.append(view.Name)
        
        return {
            "view_name": view.Name,
            "duplicates_found": len(duplicates),
            "tags_removed": len(removed_tags),
            "tags_kept": len(kept_tags),
            "removed_tag_ids": removed_tags,
        }

    def remove_duplicates_from_active_view(self, tag_filter=None):
        """
        Remove duplicate tags from the currently active view
        
        Args:
            tag_filter: Filter for tag types. Can be:
                - None: all tag categories
                - str: tag type name (e.g., "duct") or group (e.g., "all_mep", "mechanical")
                - list: list of tag type names (e.g., ["duct", "pipe"])
        """
        active_view = self.doc.ActiveView
        
        if active_view is None:
            return {"success": False, "message": "No active view found"}
        
        # Check if the view supports tags
        if not self._view_supports_tags(active_view):
            return {
                "success": False,
                "message": f"View '{active_view.Name}' does not support tags (e.g., schedules, legends)",
            }
        
        result = self.remove_duplicate_tags_in_view(active_view, tag_filter)
        result["success"] = True
        result["tag_filter"] = str(tag_filter) if tag_filter else "all"
        return result

    def remove_duplicates_from_all_views(self, tag_filter=None, view_types=None):
        """
        Remove duplicate tags from all views in the project

        Args:
            tag_filter: Filter for tag types. Can be:
                - None: all tag categories
                - str: tag type name (e.g., "duct") or group (e.g., "all_mep", "mechanical")
                - list: list of tag type names (e.g., ["duct", "pipe"])
            view_types: Optional list of ViewType to filter (e.g., [ViewType.FloorPlan, ViewType.CeilingPlan])

        Returns:
            Summary of all removals
        """
        # Get all views
        collector = (
            FilteredElementCollector(self.doc)
            .OfClass(View)
            .WhereElementIsNotElementType()
        )
        
        all_views = list(collector.ToElements())
        
        results = []
        total_removed = 0
        total_duplicates = 0
        
        for view in all_views:
            # Skip views that don't support tags
            if not self._view_supports_tags(view):
                continue
            
            # Filter by view type if specified
            if view_types and view.ViewType not in view_types:
                continue
            
            try:
                result = self.remove_duplicate_tags_in_view(view, tag_filter)
                if result["duplicates_found"] > 0:
                    results.append(result)
                    total_removed += result["tags_removed"]
                    total_duplicates += result["duplicates_found"]
            except Exception as e:
                self.errors.append(f"Error processing view '{view.Name}': {str(e)}")
        
        return {
            "success": True,
            "tag_filter": str(tag_filter) if tag_filter else "all",
            "views_processed": len(self.processed_views),
            "views_with_duplicates": len(results),
            "total_duplicates_found": total_duplicates,
            "total_tags_removed": total_removed,
            "details": results,
            "errors": self.errors if self.errors else None,
        }

    def remove_duplicates_from_selected_views(self, view_names, tag_filter=None):
        """
        Remove duplicate tags from specified views by name

        Args:
            view_names: List of view names to process
            tag_filter: Filter for tag types. Can be:
                - None: all tag categories
                - str: tag type name (e.g., "duct") or group (e.g., "all_mep", "mechanical")
                - list: list of tag type names (e.g., ["duct", "pipe"])

        Returns:
            Summary of removals
        """
        collector = (
            FilteredElementCollector(self.doc)
            .OfClass(View)
            .WhereElementIsNotElementType()
        )
        
        all_views = list(collector.ToElements())
        views_to_process = [v for v in all_views if v.Name in view_names]
        
        if not views_to_process:
            return {
                "success": False,
                "message": f"No views found with names: {view_names}",
            }
        
        results = []
        total_removed = 0
        
        for view in views_to_process:
            if not self._view_supports_tags(view):
                self.errors.append(f"View '{view.Name}' does not support tags")
                continue
            
            try:
                result = self.remove_duplicate_tags_in_view(view, tag_filter)
                results.append(result)
                total_removed += result["tags_removed"]
            except Exception as e:
                self.errors.append(f"Error processing view '{view.Name}': {str(e)}")
        
        return {
            "success": True,
            "tag_filter": str(tag_filter) if tag_filter else "all",
            "views_processed": len(views_to_process),
            "total_tags_removed": total_removed,
            "details": results,
            "errors": self.errors if self.errors else None,
        }

    def preview_duplicates_in_view(self, view, tag_filter=None):
        """
        Preview duplicate tags without removing them

        Args:
            view: The view to check
            tag_filter: Filter for tag types. Can be:
                - None: all tag categories
                - str: tag type name (e.g., "duct") or group (e.g., "all_mep", "mechanical")
                - list: list of tag type names (e.g., ["duct", "pipe"])

        Returns:
            Information about duplicate tags found
        """
        duplicates = self.find_duplicate_tags_in_view(view, tag_filter)
        
        if not duplicates:
            return {
                "view_name": view.Name,
                "duplicates_found": 0,
                "details": [],
            }
        
        details = []
        for key, tag_list in duplicates.items():
            host_id, tag_type_id = key
            host_element = self.doc.GetElement(ElementId(host_id))
            
            host_info = "Unknown Element"
            if host_element:
                host_info = f"{host_element.Category.Name if host_element.Category else 'No Category'} - ID: {host_id}"
            
            tag_info = {
                "host_element": host_info,
                "duplicate_count": len(tag_list),
                "tag_ids": [t.Id.IntegerValue for t in tag_list],
            }
            details.append(tag_info)
        
        return {
            "view_name": view.Name,
            "duplicates_found": len(duplicates),
            "total_duplicate_tags": sum(len(t) for t in duplicates.values()),
            "details": details,
        }

    def preview_duplicates_in_all_views(self, tag_filter=None, view_types=None):
        """
        Preview duplicate tags in all views without removing them

        Args:
            tag_filter: Filter for tag types. Can be:
                - None: all tag categories
                - str: tag type name (e.g., "duct") or group (e.g., "all_mep", "mechanical")
                - list: list of tag type names (e.g., ["duct", "pipe"])
            view_types: Optional list of ViewType to filter (e.g., [ViewType.FloorPlan, ViewType.CeilingPlan])

        Returns:
            Summary of all duplicates found across views
        """
        # Get all views
        collector = (
            FilteredElementCollector(self.doc)
            .OfClass(View)
            .WhereElementIsNotElementType()
        )
        
        all_views = list(collector.ToElements())
        
        results = []
        total_duplicates = 0
        total_duplicate_tags = 0
        views_checked = 0
        
        for view in all_views:
            # Skip views that don't support tags
            if not self._view_supports_tags(view):
                continue
            
            # Filter by view type if specified
            if view_types and view.ViewType not in view_types:
                continue
            
            views_checked += 1
            
            try:
                result = self.preview_duplicates_in_view(view, tag_filter)
                if result["duplicates_found"] > 0:
                    results.append(result)
                    total_duplicates += result["duplicates_found"]
                    total_duplicate_tags += result["total_duplicate_tags"]
            except Exception as e:
                self.errors.append(f"Error processing view '{view.Name}': {str(e)}")
        
        return {
            "success": True,
            "tag_filter": str(tag_filter) if tag_filter else "all",
            "views_checked": views_checked,
            "views_with_duplicates": len(results),
            "total_duplicates_found": total_duplicates,
            "total_duplicate_tags": total_duplicate_tags,
            "details": results,
            "errors": self.errors if self.errors else None,
        }

    def _view_supports_tags(self, view):
        """Check if a view type supports tags"""
        # Views that don't support tags
        unsupported_types = [
            ViewType.Schedule,
            ViewType.Legend,
            ViewType.DraftingView,
            ViewType.DrawingSheet,
            ViewType.Report,
            ViewType.Undefined,
        ]
        
        # Check if view is a template
        if view.IsTemplate:
            return False
        
        # Check view type
        try:
            if view.ViewType in unsupported_types:
                return False
        except:
            return False
        
        return True


# Convenience functions for Dynamo usage
def remove_duplicate_tags_active_view(tag_filter=None):
    """
    Remove duplicate tags from the active view
    
    Args:
        tag_filter: Filter for tag types. Can be:
            - None: all tag categories
            - str: tag type name (e.g., "duct") or group (e.g., "all_mep", "mechanical")
            - list: list of tag type names (e.g., ["duct", "pipe"])
    """
    remover = DuplicateTagRemover()
    return remover.remove_duplicates_from_active_view(tag_filter)


def remove_duplicate_tags_all_views(tag_filter=None):
    """
    Remove duplicate tags from all views in the project
    
    Args:
        tag_filter: Filter for tag types. Can be:
            - None: all tag categories
            - str: tag type name (e.g., "duct") or group (e.g., "all_mep", "mechanical")
            - list: list of tag type names (e.g., ["duct", "pipe"])
    """
    remover = DuplicateTagRemover()
    return remover.remove_duplicates_from_all_views(tag_filter)


def remove_duplicate_tags_floor_plans(tag_filter=None):
    """
    Remove duplicate tags from all floor plan views
    
    Args:
        tag_filter: Filter for tag types. Can be:
            - None: all tag categories
            - str: tag type name (e.g., "duct") or group (e.g., "all_mep", "mechanical")
            - list: list of tag type names (e.g., ["duct", "pipe"])
    """
    remover = DuplicateTagRemover()
    return remover.remove_duplicates_from_all_views(tag_filter, view_types=[ViewType.FloorPlan])


def remove_duplicate_tags_selected_views(view_names, tag_filter=None):
    """
    Remove duplicate tags from views with specified names
    
    Args:
        view_names: List of view names to process
        tag_filter: Filter for tag types. Can be:
            - None: all tag categories
            - str: tag type name (e.g., "duct") or group (e.g., "all_mep", "mechanical")
            - list: list of tag type names (e.g., ["duct", "pipe"])
    """
    remover = DuplicateTagRemover()
    return remover.remove_duplicates_from_selected_views(view_names, tag_filter)


def preview_duplicates_active_view(tag_filter=None):
    """
    Preview duplicate tags in the active view without removing them
    
    Args:
        tag_filter: Filter for tag types. Can be:
            - None: all tag categories
            - str: tag type name (e.g., "duct") or group (e.g., "all_mep", "mechanical")
            - list: list of tag type names (e.g., ["duct", "pipe"])
    """
    remover = DuplicateTagRemover()
    active_view = doc.ActiveView
    if active_view:
        return remover.preview_duplicates_in_view(active_view, tag_filter)
    return {"success": False, "message": "No active view"}


def preview_duplicates_all_views(tag_filter=None):
    """
    Preview duplicate tags in all views without removing them
    
    Args:
        tag_filter: Filter for tag types. Can be:
            - None: all tag categories
            - str: tag type name (e.g., "duct") or group (e.g., "all_mep", "mechanical")
            - list: list of tag type names (e.g., ["duct", "pipe"])
    """
    remover = DuplicateTagRemover()
    return remover.preview_duplicates_in_all_views(tag_filter)


def remove_duplicate_mep_tags_active_view():
    """Remove duplicate MEP tags from the active view (all MEP categories)"""
    return remove_duplicate_tags_active_view("all_mep")


def list_available_tag_filters():
    """List all available tag type names and groups for filtering"""
    remover = DuplicateTagRemover()
    return remover.list_available_tag_types()


# Dynamo/pyRevit compatibility
# Initialize OUT variable
OUT = None

try:
    # OPTION 1: Remove duplicates from active view (all tag types)
    # result = remove_duplicate_tags_active_view()
    
    # OPTION 2: Preview duplicates without removing (safer first step)
    # result = preview_duplicates_active_view()
    
    # OPTION 3: Remove duplicates from all views
    # result = remove_duplicate_tags_all_views()
    
    # OPTION 4: Remove duplicates from all views (MEP tags only)
    # result = remove_duplicate_tags_all_views("all_mep")
    
    # OPTION 5: Remove duplicates from floor plans only
    # result = remove_duplicate_tags_floor_plans()
    
    # OPTION 6: Remove duplicates from specific views
    # result = remove_duplicate_tags_selected_views(["Level 1 - Mechanical", "Level 2 - Mechanical"])
    
    # OPTION 7: Remove MEP tags only from active view
    # result = remove_duplicate_mep_tags_active_view()
    
    # ============================================
    # TAG FILTER EXAMPLES
    # ============================================
    
    # OPTION 8: Filter by single tag type
    # result = remove_duplicate_tags_active_view("duct")  # Only duct tags
    # result = remove_duplicate_tags_active_view("pipe")  # Only pipe tags
    # result = remove_duplicate_tags_active_view("mechanical_equipment")  # Only mech equipment tags
    
    # OPTION 9: Filter by tag group (active view)
    # result = remove_duplicate_tags_active_view("mechanical")  # All mechanical tags
    # result = remove_duplicate_tags_active_view("electrical")  # All electrical tags
    # result = remove_duplicate_tags_active_view("plumbing")    # All plumbing tags
    # result = remove_duplicate_tags_active_view("all_mep")     # All MEP tags
    # result = remove_duplicate_tags_active_view("architectural")  # All architectural tags
    
    # OPTION 10: Filter by tag group (all views)
    # result = remove_duplicate_tags_all_views("mechanical")  # All mechanical tags in all views
    # result = remove_duplicate_tags_all_views("electrical")  # All electrical tags in all views
    # result = remove_duplicate_tags_all_views("plumbing")    # All plumbing tags in all views
    
    # OPTION 11: Filter by multiple specific tag types
    # result = remove_duplicate_tags_active_view(["duct", "pipe", "mechanical_equipment"])
    # result = remove_duplicate_tags_all_views(["duct", "pipe", "mechanical_equipment"])
    
    # OPTION 12: Preview with filter
    # result = preview_duplicates_active_view("mechanical")
    
    # OPTION 13: Preview duplicates in all views
    # result = preview_duplicates_all_views()
    # result = preview_duplicates_all_views("duct") # Preview duct tags only
    result = preview_duplicates_all_views("pipe")  # Preview pipe tags only
    # result = preview_duplicates_all_views("all_mep")  # Preview MEP tags only
    # result = preview_duplicates_all_views("mechanical")  # Preview mechanical tags only
    
    # OPTION 14: List all available tag filters
    # result = list_available_tag_filters()
    
    OUT = result
    
except Exception as e:
    import traceback
    OUT = {
        "success": False,
        "error": str(e),
        "error_type": type(e).__name__,
        "traceback": traceback.format_exc()
    }
