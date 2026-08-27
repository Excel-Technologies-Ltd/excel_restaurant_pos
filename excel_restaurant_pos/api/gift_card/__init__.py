"""Gift card API endpoints."""

from .apply_gift_card import apply_gift_card
from .discard_gift_card import discard_gift_card
from .generate_bulk import generate_bulk_gift_cards
from .import_gift_cards import import_gift_cards
from .list_gift_cards import list_gift_cards, list_inactive_gift_cards
from .verify_gift_card import verify_gift_card

__all__ = [
	"apply_gift_card",
	"discard_gift_card",
	"generate_bulk_gift_cards",
	"import_gift_cards",
	"list_gift_cards",
	"list_inactive_gift_cards",
	"verify_gift_card",
]

gift_card_api_routes = {
	"api.gift_cards.verify": "excel_restaurant_pos.api.gift_card.verify_gift_card",
	"api.gift_cards.apply": "excel_restaurant_pos.api.gift_card.apply_gift_card",
	"api.gift_cards.discard": "excel_restaurant_pos.api.gift_card.discard_gift_card",
	"api.gift_cards.list_inactive": "excel_restaurant_pos.api.gift_card.list_inactive_gift_cards",
	"api.gift_cards.list": "excel_restaurant_pos.api.gift_card.list_gift_cards",
	"api.gift_cards.generate_bulk": "excel_restaurant_pos.api.gift_card.generate_bulk_gift_cards",
	"api.gift_cards.import": "excel_restaurant_pos.api.gift_card.import_gift_cards",
}
