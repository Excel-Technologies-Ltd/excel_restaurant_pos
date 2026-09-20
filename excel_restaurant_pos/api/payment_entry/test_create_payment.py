# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.api.payment_entry.create_payment import (
    PAYMENT_ROLES,
    ROLES_CONFIG_KEY,
    allowed_roles,
    guard_payment_permission,
)

MODULE = "excel_restaurant_pos.api.payment_entry.create_payment"


def _as_user(user):
    """frappe.session is a thread-local proxy, so patch the module's view of it."""
    return patch(f"{MODULE}.frappe.session", frappe._dict(user=user))


class TestPaymentPermission(FrappeTestCase):
    """Marking an invoice paid without money moving was open to any account.

    api.payment_entry.create carried a bare @frappe.whitelist(), so anyone who
    self registered through the guest sign_up/verify_otp pair could record a
    payment against any invoice for any amount -- no gateway involved. The
    storefront never calls this endpoint; only the staff POS does.
    """

    def setUp(self):
        frappe.local.form_dict = frappe._dict(cmd="api.payment_entry.create")
        patcher = patch(f"{MODULE}.frappe.log_error")
        self.log_error = patcher.start()
        self.addCleanup(patcher.stop)

    @patch(f"{MODULE}.frappe.get_roles", return_value=["Customer", "Sales User"])
    def test_a_self_registered_customer_is_refused(self, _roles):
        # Exactly the roles verify_otp grants a new web signup.
        with _as_user("attacker@example.com"):
            with self.assertRaises(frappe.PermissionError):
                guard_payment_permission()

    @patch(f"{MODULE}.frappe.get_roles", return_value=["Guest"])
    def test_a_guest_is_refused(self, _roles):
        with _as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                guard_payment_permission()

    @patch(f"{MODULE}.frappe.get_roles", return_value=["Customer"])
    def test_a_refusal_is_logged_with_the_target(self, _roles):
        with _as_user("attacker@example.com"):
            with self.assertRaises(frappe.PermissionError):
                guard_payment_permission()

        logged = self.log_error.call_args.kwargs["message"]
        self.assertIn("attacker@example.com", logged)

    def test_every_staff_role_is_allowed(self):
        for role in PAYMENT_ROLES:
            with self.subTest(role=role):
                with patch(f"{MODULE}.frappe.get_roles", return_value=[role, "Customer"]):
                    with _as_user("cashier@example.com"):
                        guard_payment_permission()

    @patch(f"{MODULE}.frappe.get_roles", return_value=[])
    def test_administrator_is_always_allowed(self, _roles):
        # Background jobs and bench execute run as Administrator.
        with _as_user("Administrator"):
            guard_payment_permission()

    @patch(f"{MODULE}.frappe.get_roles", return_value=["Some Local Role"])
    def test_site_config_can_add_a_role(self, _roles):
        """A site with its own role names must not be locked out of taking payments."""
        with patch.dict(frappe.conf, {ROLES_CONFIG_KEY: ["Some Local Role"]}):
            with _as_user("cashier@example.com"):
                guard_payment_permission()

    def test_site_config_only_widens_never_narrows(self):
        with patch.dict(frappe.conf, {ROLES_CONFIG_KEY: ["Some Local Role"]}):
            self.assertTrue(set(PAYMENT_ROLES).issubset(allowed_roles()))
            self.assertIn("Some Local Role", allowed_roles())

    def test_a_single_string_is_accepted(self):
        with patch.dict(frappe.conf, {ROLES_CONFIG_KEY: "Some Local Role"}):
            self.assertIn("Some Local Role", allowed_roles())


class TestNoPrivilegeEscalation(FrappeTestCase):
    def test_create_payment_entry_does_not_become_administrator(self):
        """It used to set_user("Administrator") and never restore the session."""
        import inspect

        from excel_restaurant_pos.doc_event.sales_invoice.handlers import (
            create_payment_entry as module,
        )

        source = inspect.getsource(module.create_payment_entry)
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        self.assertNotIn("set_user", code)
