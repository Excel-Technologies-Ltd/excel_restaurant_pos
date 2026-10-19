"""Keeping wallet passes in step with the ledger: debounced, hash-skipped, retried, reconciled."""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, cint, now_datetime

from excel_restaurant_pos.shared.loyalty.settings import ACCOUNT, WALLET_PASS, get_programme, is_enabled
from excel_restaurant_pos.shared.loyalty.wallet import apple, google
from excel_restaurant_pos.shared.loyalty.wallet.base import payload_hash, render

DEBOUNCE_SECONDS = 30
BACKOFF_MINUTES = (1, 5, 30, 120)
MAX_RETRIES = 8  # about 11 hours of retries, then parked until the nightly reconcile
MAX_PASSES_PER_RUN = 2000
LIVE = ("Issued", "Installed")
ADAPTERS = {"Google": google, "Apple": apple}


def wallets_enabled() -> bool:
	return google.enabled() or apple.enabled()


def _live_passes(account: str) -> list[str]:
	return frappe.get_all(WALLET_PASS, filters={"account": account, "status": ["in", LIVE]}, pluck="name")


def schedule_sync(account: str, force: bool = False):
	"""Queue a push of the account's passes, at most one job per 30 seconds.

	A change inside the window sets a dirty flag; the running job sees it and
	renders once more, so the last change is never lost to the debounce.
	"""
	if not account or not is_enabled() or not wallets_enabled() or not _live_passes(account):
		return
	cache = frappe.cache()
	if cache.set(cache.make_key(f"loyalty:wallet-sync:{account}"), 1, ex=DEBOUNCE_SECONDS, nx=True):
		frappe.enqueue(
			"excel_restaurant_pos.shared.loyalty.wallet.sync.sync_account",
			queue="short",
			enqueue_after_commit=True,
			account=account,
			force=force,
		)
	else:
		cache.set(cache.make_key(f"loyalty:wallet-dirty:{account}"), 1, ex=DEBOUNCE_SECONDS * 10)


def sync_account(account: str, force: bool = False):
	cache = frappe.cache()
	debounce = cache.make_key(f"loyalty:wallet-sync:{account}")
	dirty = cache.make_key(f"loyalty:wallet-dirty:{account}")
	try:
		for _round in range(3):
			cache.delete(dirty)
			view = render(account)
			for name in _live_passes(account):
				push_pass(name, view, force=force, commit=True)
			frappe.db.commit()
			if not cache.get(dirty):
				break
	finally:
		# Release the debounce now instead of letting it run out: a change made
		# after this job finished would otherwise only set the dirty flag, with
		# no job left to read it, and the pass would stay stale.
		cache.delete(debounce)
	# A change that landed between the last round and the release above.
	if cache.get(dirty):
		cache.delete(dirty)
		schedule_sync(account)


def _record_failure(pass_doc, exc):
	retries = cint(pass_doc.retry_count) + 1
	values = {"retry_count": retries, "last_error": str(exc)[:1000]}
	if retries <= MAX_RETRIES:
		delay = BACKOFF_MINUTES[min(retries, len(BACKOFF_MINUTES)) - 1]
		values["next_retry_at"] = add_to_date(now_datetime(), minutes=delay)
	else:
		# Parked: a missing image or a bad certificate fails every time. The
		# nightly reconcile still tries once a day.
		values["next_retry_at"] = None
	frappe.db.set_value(WALLET_PASS, pass_doc.name, values, update_modified=False)
	if retries == MAX_RETRIES:
		frappe.log_error(title="Loyalty wallet sync failing", message=f"{pass_doc.name}: {exc}")


def push_pass(name: str, view=None, force: bool = False, commit: bool = False) -> bool:
	"""Push one pass. `commit` (background jobs only) commits the new sync
	stamp before an Apple push: the device asks what changed the moment the
	push lands, and an uncommitted stamp would answer "nothing"."""
	pass_doc = frappe.get_doc(WALLET_PASS, name)
	adapter = ADAPTERS.get(pass_doc.platform)
	if not adapter or not adapter.enabled():
		return False
	view = view or render(pass_doc.account)
	digest = payload_hash(view, pass_doc.platform)
	if not force and pass_doc.last_synced_hash == digest and not pass_doc.last_error:
		return True

	values = {
		"last_synced_at": now_datetime(),
		"last_synced_hash": digest,
		"retry_count": 0,
		"last_error": None,
		"next_retry_at": None,
	}
	if view.state == "voided":
		values["status"] = "Voided"
	stamp_first = commit and pass_doc.platform == "Apple"
	if stamp_first:
		frappe.db.set_value(WALLET_PASS, name, values, update_modified=False)
		frappe.db.commit()

	try:
		if view.state == "voided":
			adapter.void(pass_doc, view)
		else:
			adapter.update(pass_doc, view)
	except Exception as exc:
		_record_failure(pass_doc, exc)
		return False

	if not stamp_first:
		frappe.db.set_value(WALLET_PASS, name, values, update_modified=False)
	return True


def retry_failed_passes():
	"""Every 5 minutes: passes whose last push failed and whose backoff has passed."""
	if not is_enabled() or not wallets_enabled():
		return
	platforms = [platform for platform, adapter in ADAPTERS.items() if adapter.enabled()]
	names = frappe.get_all(
		WALLET_PASS,
		filters={
			"status": ["in", LIVE],
			"platform": ["in", platforms],
			"next_retry_at": ["<=", now_datetime()],
			"last_error": ["is", "set"],
		},
		pluck="name",
		limit=200,
	)
	for name in names:
		push_pass(name, commit=True)
		frappe.db.commit()


def reconcile_wallet_passes():
	"""Daily 03:00: re-render every live pass and push where it drifted."""
	if not is_enabled() or not wallets_enabled():
		return
	rows = frappe.get_all(
		WALLET_PASS, filters={"status": ["in", LIVE]}, fields=["name", "account"], limit=MAX_PASSES_PER_RUN
	)
	views = {}
	for row in rows:
		try:
			if row.account not in views:
				views[row.account] = render(row.account)
			push_pass(row.name, views[row.account], commit=True)
		except Exception:
			frappe.log_error(title="Loyalty wallet reconcile failed", message=f"{row.name}\n{frappe.get_traceback()}")
		frappe.db.commit()


def void_passes(account: str):
	"""A closed account: its passes show as voided / inactive.

	The pushes run in a job after commit, never inside the request that closed
	the account: they are network calls, and Apple's must follow a commit.
	"""
	if not wallets_enabled() or not _live_passes(account):
		frappe.db.set_value(WALLET_PASS, {"account": account}, "status", "Voided", update_modified=False)
		return
	frappe.enqueue(
		"excel_restaurant_pos.shared.loyalty.wallet.sync.void_passes_now",
		queue="short",
		enqueue_after_commit=True,
		account=account,
	)


def void_passes_now(account: str):
	view = render(account)
	for name in _live_passes(account):
		push_pass(name, view, force=True, commit=True)
	frappe.db.set_value(WALLET_PASS, {"account": account}, "status", "Voided", update_modified=False)
	frappe.db.commit()


def send_pass_message(account: str, header: str, body: str) -> bool:
	"""A Google pass message. Apple shows changes through the fields' changeMessage instead."""
	if not google.enabled():
		return False
	names = frappe.get_all(
		WALLET_PASS, filters={"account": account, "platform": "Google", "status": "Installed"}, pluck="name"
	)
	for name in names:
		google.add_message(frappe.get_doc(WALLET_PASS, name), header, body)
	return bool(names)


def sync_programme(programme: str):
	"""A programme's branding or status changed: upsert its Google class."""
	if not google.enabled():
		return
	account = frappe.db.get_value(ACCOUNT, {"programme": programme}, "name")
	if account:
		google.ensure_class(get_programme(programme), render(account), patch=True)
