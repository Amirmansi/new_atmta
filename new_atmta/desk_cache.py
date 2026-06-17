"""
Desk performance: cached workspace sidebar (with content for page rendering).
"""

from __future__ import annotations

import hashlib

import frappe
from frappe import _
from frappe.desk.desktop import Workspace

CACHE_TTL = 300  # 5 minutes
SIDEBAR_FIELDS = [
	"name",
	"title",
	"for_user",
	"parent_page",
	"content",
	"public",
	"module",
	"icon",
	"indicator_color",
	"is_hidden",
	"svg",
]


def _cache_version() -> str:
	return frappe.cache.get_value("atmta:sidebar_cache_version") or "1"


def _cache_key(user: str | None = None) -> str:
	user = user or frappe.session.user
	roles = ",".join(sorted(frappe.get_roles(user)))
	domains = ",".join(sorted(frappe.get_active_domains() or []))
	raw = f"{_cache_version()}|{user}|{roles}|{domains}"
	return f"atmta:workspace_sidebar:{hashlib.md5(raw.encode()).hexdigest()}"


def clear_workspace_cache(user: str | None = None) -> None:
	if user:
		frappe.cache.delete_value(_cache_key(user))
		frappe.cache.hdel("bootinfo", user)
	else:
		frappe.cache.set_value("atmta:sidebar_cache_version", str(frappe.utils.now_datetime()))
		frappe.cache.delete_key("bootinfo")


def _build_sidebar_items() -> dict:
	has_access = "Workspace Manager" in frappe.get_roles()
	blocked_modules = frappe.get_cached_doc("User", frappe.session.user).get_blocked_modules()
	blocked_modules.append("Dummy Module")

	allowed_domains = [None, *frappe.get_active_domains()]
	filters = {
		"restrict_to_domain": ["in", allowed_domains],
		"module": ["not in", blocked_modules],
	}
	if has_access:
		filters = {}

	all_pages = frappe.get_all(
		"Workspace",
		fields=SIDEBAR_FIELDS,
		filters=filters,
		order_by="sequence_id asc",
		ignore_permissions=True,
	)

	pages: list[dict] = []
	private_pages: list[dict] = []

	for page in all_pages:
		try:
			workspace = Workspace(page, True)
			if has_access or workspace.is_permitted():
				if page.public and (has_access or not page.is_hidden) and page.title != "Welcome Workspace":
					pages.append(page)
				elif page.for_user == frappe.session.user:
					private_pages.append(page)
				page["label"] = _(page.get("name"))
		except frappe.PermissionError:
			pass

	if private_pages:
		pages.extend(private_pages)

	if not pages:
		welcome = frappe.get_doc("Workspace", "Welcome Workspace").as_dict()
		welcome["label"] = _("Welcome Workspace")
		pages = [welcome]

	return {
		"pages": pages,
		"has_access": has_access,
		"has_create_access": frappe.has_permission(doctype="Workspace", ptype="create"),
	}


@frappe.whitelist()
def get_workspace_sidebar_items():
	"""Fast cached sidebar for nxt_theme + ATMTA sites."""
	cache_key = _cache_key()
	cached = frappe.cache.get_value(cache_key)
	if cached:
		return cached

	result = _build_sidebar_items()
	frappe.cache.set_value(cache_key, result, expires_in_sec=CACHE_TTL)
	return result


def on_workspace_change(doc, method=None):
	clear_workspace_cache()


def boot_session(bootinfo):
	ensure_sidebar_patch()
	result = get_workspace_sidebar_items()
	bootinfo.allowed_workspaces = result.get("pages")
	bootinfo["atmta_desk_perf"] = True


_PATCHED = False


def ensure_sidebar_patch():
	"""Patch frappe boot + API to use cached sidebar (boot.py imports directly)."""
	global _PATCHED
	if _PATCHED:
		return
	import frappe.desk.desktop as desktop

	desktop.get_workspace_sidebar_items = get_workspace_sidebar_items
	_PATCHED = True


def verify_home_content():
	frappe.set_user("Administrator")
	r = get_workspace_sidebar_items()
	home = [p for p in r["pages"] if p.get("title") == "Home"]
	if not home:
		return {"error": "Home workspace not found", "pages": len(r["pages"])}
	page = home[0]
	content = page.get("content") or ""
	return {
		"home_content_length": len(content),
		"has_content": bool(content),
		"content_preview": content[:80] if content else None,
	}


def verify_workspace_render(title: str = "Accounting"):
	"""Diagnostic: confirm sidebar + desktop payload can render a workspace."""
	import json

	from frappe.desk.desktop import get_desktop_page

	frappe.set_user("Administrator")
	r = get_workspace_sidebar_items()
	matches = [p for p in r["pages"] if p.get("title") == title or p.get("name") == title]
	if not matches:
		return {"error": "Workspace not found", "title": title, "pages": len(r["pages"])}

	page = matches[0]
	content = page.get("content") or ""
	payload = get_desktop_page(json.dumps(page))
	return {
		"title": page.get("title"),
		"name": page.get("name"),
		"content_length": len(content),
		"content_valid_json": bool(json.loads(content)) if content else False,
		"shortcuts": len((payload or {}).get("shortcuts", {}).get("items", [])),
		"cards": len((payload or {}).get("cards", {}).get("items", [])),
		"charts": len((payload or {}).get("charts", {}).get("items", [])),
		"quick_lists": len((payload or {}).get("quick_lists", {}).get("items", [])),
		"number_cards": len((payload or {}).get("number_cards", {}).get("items", [])),
	}
