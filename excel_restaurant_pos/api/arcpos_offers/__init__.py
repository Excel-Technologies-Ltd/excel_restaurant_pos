from .get_next_available_offers import get_next_available_offers

__all__ = ["get_next_available_offers"]

arcpos_offers_api_routes = {
    "api.arcpos_offers.get_next_available": (
        "excel_restaurant_pos.api.arcpos_offers.get_next_available_offers"
    ),
}
