"""Drop the cached item search term index when an item changes.

The index is a name/code/group snapshot, so anything that renames, adds,
disables or removes an item makes it stale. It has a short TTL as well; this
hook is what keeps a menu edit visible in search straight away rather than up
to five minutes later.
"""

from excel_restaurant_pos.api.item.search import clear_item_search_index


def clear_item_search_index_cache(doc=None, method=None):
    clear_item_search_index()
