from .create_pnl_entry import create_pnl_entry
from .update_pnl_entry import update_pnl_entry
from .delete_pnl_attachment import delete_pnl_attachment
from .cancel_pnl_entry import cancel_pnl_entry

__all__ = [
	"create_pnl_entry",
	"update_pnl_entry",
	"delete_pnl_attachment",
	"cancel_pnl_entry",
]

pnl_entry_api_routes = {
	"api.pnl.create": "excel_restaurant_pos.api.pnl_entry.create_pnl_entry.create_pnl_entry",
	"api.pnl.update": "excel_restaurant_pos.api.pnl_entry.update_pnl_entry.update_pnl_entry",
	"api.pnl.delete_attachment": "excel_restaurant_pos.api.pnl_entry.delete_pnl_attachment.delete_pnl_attachment",
	"api.pnl.cancel": "excel_restaurant_pos.api.pnl_entry.cancel_pnl_entry.cancel_pnl_entry",
}
