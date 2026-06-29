"""Clear cached item group visibility snapshots when configuration changes."""

from excel_restaurant_pos.api.item_group.visibility import clear_visible_item_group_cache


def clear_item_group_visibility_cache(doc=None, method=None):
    clear_visible_item_group_cache()
