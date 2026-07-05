from .apply_coupon import apply_coupon
from .discard_coupon import discard_coupon
from .generate_coupon import generate_coupon
from .get_generated_coupon import get_generated_coupon
from .validate_coupon import validate_coupon
from .verify_coupon import verify_coupon

__all__ = [
    "apply_coupon",
    "discard_coupon",
    "generate_coupon",
    "get_generated_coupon",
    "validate_coupon",
    "verify_coupon",
]

coupon_api_routes = {
    "api.coupons.generate": "excel_restaurant_pos.api.coupon.generate_coupon",
    "api.coupons.get_by_invoice": "excel_restaurant_pos.api.coupon.get_generated_coupon",
    "api.coupons.discard": "excel_restaurant_pos.api.coupon.discard_coupon",
    "api.coupons.validate": "excel_restaurant_pos.api.coupon.validate_coupon",
    "api.coupons.verify": "excel_restaurant_pos.api.coupon.verify_coupon",
    "api.coupons.apply": "excel_restaurant_pos.api.coupon.apply_coupon",
}
