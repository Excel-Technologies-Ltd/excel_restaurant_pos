"""Loyalty API endpoints. The contract is documented in docs/loyalty-api.md."""

_BASE = "excel_restaurant_pos.api.loyalty"

loyalty_api_routes = {
	# Customer (storefront / app)
	"api.loyalty.me": f"{_BASE}.customer.me",
	"api.loyalty.enrol": f"{_BASE}.customer.enrol",
	"api.loyalty.transactions": f"{_BASE}.customer.transactions",
	"api.loyalty.campaigns": f"{_BASE}.customer.campaigns",
	"api.loyalty.rewards": f"{_BASE}.customer.rewards_catalogue",
	"api.loyalty.redeem_reward": f"{_BASE}.customer.redeem_reward",
	"api.loyalty.preview_earning": f"{_BASE}.customer.preview_earning",
	"api.loyalty.redemption_options": f"{_BASE}.customer.redemption_options",
	"api.loyalty.apply_points": f"{_BASE}.customer.apply_points",
	"api.loyalty.remove_points": f"{_BASE}.customer.remove_points",
	"api.loyalty.preferences": f"{_BASE}.customer.preferences",
	# Staff (POS)
	"api.loyalty.lookup": f"{_BASE}.staff.lookup",
	"api.loyalty.staff_enrol": f"{_BASE}.staff.staff_enrol",
	"api.loyalty.request_otp": f"{_BASE}.staff.request_otp",
	"api.loyalty.verify_otp": f"{_BASE}.staff.verify_otp",
	"api.loyalty.adjust": f"{_BASE}.staff.adjust",
	"api.loyalty.reissue_pass": f"{_BASE}.staff.reissue_pass",
	# Integrations
	"api.loyalty.events.emit": f"{_BASE}.events.emit",
	# Wallets
	"api.loyalty.wallet.google_save_url": f"{_BASE}.wallet.google_save_url",
	"api.loyalty.wallet.apple_pass": f"{_BASE}.wallet.apple_pass",
	"api.loyalty.wallet.apple_pass_link": f"{_BASE}.wallet.apple_pass_link",
	"api.loyalty.wallet.apple_pass_download": f"{_BASE}.wallet.apple_pass_download",
	"api.loyalty.wallet.google_callback": f"{_BASE}.wallet.google_callback",
}
