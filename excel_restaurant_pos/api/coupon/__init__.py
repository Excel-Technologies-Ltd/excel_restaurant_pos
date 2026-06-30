from .generate_coupon import generate_coupon
from .get_generated_coupon import get_generated_coupon

__all__ = ["generate_coupon", "get_generated_coupon"]

coupon_api_routes = {
    "api.coupons.generate": "excel_restaurant_pos.api.coupon.generate_coupon",
    "api.coupons.get_by_invoice": "excel_restaurant_pos.api.coupon.get_generated_coupon"
}
