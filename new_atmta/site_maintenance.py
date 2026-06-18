"""
Site-wide maintenance for ATMTA ERP sites.

Fixes broken workspace shortcuts/links, remaps legacy DocType names (Vendor → Supplier),
creates missing expense dashboard charts, disables broken custom reports, and clears caches.

Usage:
    bench --site <site> execute new_atmta.site_maintenance.run_all
    bench --site <site> execute new_atmta.site_maintenance.scan_broken
"""

from __future__ import annotations

import json
import re

import frappe

# Legacy names that should point to ERPNext standard DocTypes.
DOCTYPE_ALIASES = {
	"Vendor": "Supplier",
	"Vendors": "Supplier",
}

EXPENSES_WORKSPACE = "Expenses | المصروفات"
EXPENSE_CHART_NAME = "Paid Amount by Supplier"
EXPENSE_CHART_LEGACY_NAME = "Paid Amount Base On Vendor"
STRIANGLE_SITE = "striangle.atmta-erp.com"
STRIANGLE_TAX_ID = "302019019900003"

# Workspace content labels that were renamed during maintenance.
CONTENT_LABEL_REMAPS = {
	"New Vendor": "New Supplier",
	"Vendor": "Supplier",
}
CONTENT_CHART_REMAPS = {
	EXPENSE_CHART_LEGACY_NAME: EXPENSE_CHART_NAME,
}

LEDGER_DOCTYPES = [
	"Item",
	"Customer",
	"Supplier",
	"Sales Invoice",
	"Purchase Invoice",
	"Payment Entry",
	"Journal Entry",
	"Delivery Note",
	"Purchase Receipt",
	"Sales Order",
	"Purchase Order",
]

ACCOUNTING_RESET_DOCTYPES = [
	"Account",
	"Journal Entry",
	"Journal Entry Account",
	"Advance Taxes and Charges",
]

BROKEN_ACCOUNT_ARABIC_FIELD = "account_name_in_arabic"

LINK_FIELD_TYPES = {"Link", "Table", "Table MultiSelect", "Dynamic Link"}

# DocTypes created by new_atmta — never delete fields linking here.
KEEP_LINK_DOCTYPES = {"Customer Types"}

# Workspaces hidden on all ATMTA V15 sites.
HIDDEN_WORKSPACES = [
	"Quality",
	"Support",
	"Website",
	"CRM",
	"Tools",
	"Integrations",
	"Projects",
	"Build",
]


def _exists_doctype(name: str | None) -> bool:
	return bool(name and frappe.db.exists("DocType", name))


def _exists_report(name: str | None) -> bool:
	return bool(name and frappe.db.exists("Report", name))


def _exists_page(name: str | None) -> bool:
	return bool(name and frappe.db.exists("Page", name))


def _exists_chart(name: str | None) -> bool:
	return bool(name and frappe.db.exists("Dashboard Chart", name))


def resolve_doctype(name: str | None) -> str | None:
	if not name:
		return name
	if _exists_doctype(name):
		return name
	alias = DOCTYPE_ALIASES.get(name)
	if alias and _exists_doctype(alias):
		return alias
	return name


def _link_target_exists(link_type: str | None, link_to: str | None) -> bool:
	if not link_to:
		return True
	if link_type in (None, "DocType"):
		return _exists_doctype(link_to)
	if link_type == "Report":
		return _exists_report(link_to)
	if link_type == "Page":
		return _exists_page(link_to)
	if link_type == "Dashboard":
		return _exists_chart(link_to)
	return True


def scan_broken() -> dict:
	"""Return a diagnostic summary without modifying data."""
	broken_shortcuts = []
	for row in frappe.db.sql(
		"""
		SELECT parent, label, link_to, type
		FROM `tabWorkspace Shortcut`
		WHERE link_to IS NOT NULL AND link_to != ''
		""",
		as_dict=True,
	):
		if row.type == "DocType" and not _exists_doctype(row.link_to):
			broken_shortcuts.append(row)
		elif row.type == "Report" and not _exists_report(row.link_to):
			broken_shortcuts.append(row)

	broken_quick_lists = []
	for row in frappe.db.sql(
		"""
		SELECT parent, label, document_type
		FROM `tabWorkspace Quick List`
		WHERE document_type IS NOT NULL AND document_type != ''
		""",
		as_dict=True,
	):
		if not _exists_doctype(row.document_type):
			broken_quick_lists.append(row)

	broken_links = []
	for row in frappe.db.sql(
		"""
		SELECT parent, label, link_to, link_type
		FROM `tabWorkspace Link`
		WHERE link_to IS NOT NULL AND link_to != ''
		""",
		as_dict=True,
	):
		if not _link_target_exists(row.link_type, row.link_to):
			broken_links.append(row)

	broken_reports = frappe.db.sql(
		"""
		SELECT name, ref_doctype
		FROM `tabReport`
		WHERE disabled = 0
			AND ref_doctype IS NOT NULL
			AND ref_doctype != ''
			AND ref_doctype NOT IN (SELECT name FROM `tabDocType`)
		""",
		as_dict=True,
	)

	broken_charts = []
	for row in frappe.get_all(
		"Dashboard Chart",
		fields=["name", "document_type", "chart_name"],
	):
		if row.document_type and not _exists_doctype(row.document_type):
			broken_charts.append(row)

	missing_expense_chart = not _exists_chart(EXPENSE_CHART_NAME) and not _exists_chart(
		EXPENSE_CHART_LEGACY_NAME
	)

	broken_custom_fields = scan_orphan_custom_fields()

	return {
		"site": frappe.local.site,
		"broken_shortcuts": broken_shortcuts,
		"broken_quick_lists": broken_quick_lists,
		"broken_links": broken_links,
		"broken_reports": broken_reports,
		"broken_charts": broken_charts,
		"broken_custom_fields": broken_custom_fields,
		"hidden_workspaces_pending": _hidden_workspaces_pending(),
		"missing_expense_chart": missing_expense_chart,
	}


def scan_orphan_custom_fields() -> list[dict]:
	"""Custom fields pointing to missing DocTypes or POS Awesome leftovers."""
	orphans = []
	for row in frappe.db.sql(
		"""
		SELECT name, dt, fieldname, fieldtype, options
		FROM `tabCustom Field`
		""",
		as_dict=True,
	):
		if _is_orphan_custom_field(row):
			orphans.append(row)
	return orphans


def _is_orphan_custom_field(row: dict) -> bool:
	fieldname = row.get("fieldname") or ""
	if fieldname.startswith("posa_"):
		return True

	fieldtype = row.get("fieldtype")
	options = row.get("options")
	if fieldtype in LINK_FIELD_TYPES and options:
		if options in KEEP_LINK_DOCTYPES:
			return False
		if not _exists_doctype(options):
			return True
	return False


def _hidden_workspaces_pending() -> list[str]:
	pending = []
	for name in HIDDEN_WORKSPACES:
		if not frappe.db.exists("Workspace", name):
			continue
		if not frappe.db.get_value("Workspace", name, "is_hidden"):
			pending.append(name)
	return pending


def remove_orphan_custom_fields() -> dict:
	"""Delete custom fields referencing missing DocTypes (POS Awesome, etc.)."""
	from new_atmta.install import ensure_common_doctypes

	ensure_common_doctypes()

	stats = {"fields_removed": 0, "removed_fieldnames": []}
	for row in scan_orphan_custom_fields():
		try:
			frappe.delete_doc("Custom Field", row.name, force=True, ignore_permissions=True)
			stats["fields_removed"] += 1
			stats["removed_fieldnames"].append(row.fieldname)
		except Exception as e:
			frappe.logger().error(f"new_atmta: failed to delete Custom Field {row.name} — {e}")

	if stats["removed_fieldnames"]:
		clean_property_setters_field_order(set(stats["removed_fieldnames"]))

	frappe.db.commit()
	return stats


def clean_property_setters_field_order(removed_fieldnames: set[str]) -> dict:
	"""Remove deleted fieldnames from field_order property setters."""
	stats = {"property_setters_updated": 0, "property_setters_removed": 0}
	if not removed_fieldnames:
		removed_fieldnames = set()

	# Remove property setters for deleted/orphan fields (e.g. posa_*).
	generic_removed_fieldnames = removed_fieldnames - {"cost_center"}
	if generic_removed_fieldnames:
		for row in frappe.get_all(
			"Property Setter",
			filters=[["field_name", "in", list(generic_removed_fieldnames)]],
			pluck="name",
		):
			frappe.delete_doc("Property Setter", row, ignore_permissions=True)
			stats["property_setters_removed"] += 1

	for row in frappe.get_all(
		"Property Setter",
		filters=[["field_name", "like", "posa_%"]],
		pluck="name",
	):
		frappe.delete_doc("Property Setter", row, ignore_permissions=True)
		stats["property_setters_removed"] += 1

	for row in frappe.get_all(
		"Property Setter",
		filters={"property": "field_order"},
		fields=["name", "doc_type", "value"],
	):
		if row.doc_type in MASTER_LAYOUT_DOCTYPES:
			frappe.delete_doc("Property Setter", row.name, ignore_permissions=True)
			stats["property_setters_removed"] += 1
			continue
		try:
			fields = json.loads(row.value or "[]")
		except json.JSONDecodeError:
			continue
		if not isinstance(fields, list):
			continue
		new_fields = [field for field in fields if field not in removed_fieldnames]
		if new_fields != fields:
			frappe.db.set_value("Property Setter", row.name, "value", json.dumps(new_fields))
			stats["property_setters_updated"] += 1

	frappe.db.commit()
	return stats


def remove_accounting_doctype_customizations() -> dict:
	"""Reset accounting/payment forms to ERPNext v15 standard metadata.

	These DocTypes had stale custom fields and field_order setters (for example
	``account_name_in_arabic`` on Account) that break link validation. Deleting
	the custom fields and property setters lets ERPNext's standard layout win.
	"""
	stats = {
		"custom_fields_removed": 0,
		"property_setters_removed": 0,
		"custom_fields": [],
		"property_setters": [],
	}

	custom_field_names = set(
		frappe.get_all(
			"Custom Field",
			filters={"dt": ["in", ACCOUNTING_RESET_DOCTYPES]},
			pluck="name",
		)
	)
	for row in frappe.db.sql(
		"""
		SELECT name
		FROM `tabCustom Field`
		WHERE fieldname = %(fieldname)s
			OR fetch_from LIKE %(field_pattern)s
			OR depends_on LIKE %(field_pattern)s
			OR mandatory_depends_on LIKE %(field_pattern)s
			OR read_only_depends_on LIKE %(field_pattern)s
		""",
		{
			"fieldname": BROKEN_ACCOUNT_ARABIC_FIELD,
			"field_pattern": f"%{BROKEN_ACCOUNT_ARABIC_FIELD}%",
		},
		as_dict=True,
	):
		custom_field_names.add(row.name)

	for name in sorted(custom_field_names):
		try:
			frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)
			stats["custom_fields_removed"] += 1
			stats["custom_fields"].append(name)
		except Exception as e:
			frappe.logger().error(f"new_atmta: failed to delete Custom Field {name} — {e}")

	property_setter_names = set(
		frappe.get_all(
			"Property Setter",
			filters={"doc_type": ["in", ACCOUNTING_RESET_DOCTYPES]},
			pluck="name",
		)
	)
	for row in frappe.db.sql(
		"""
		SELECT name
		FROM `tabProperty Setter`
		WHERE field_name = %(fieldname)s
			OR value LIKE %(field_pattern)s
		""",
		{
			"fieldname": BROKEN_ACCOUNT_ARABIC_FIELD,
			"field_pattern": f"%{BROKEN_ACCOUNT_ARABIC_FIELD}%",
		},
		as_dict=True,
	):
		property_setter_names.add(row.name)

	for name in sorted(property_setter_names):
		try:
			frappe.delete_doc("Property Setter", name, force=True, ignore_permissions=True)
			stats["property_setters_removed"] += 1
			stats["property_setters"].append(name)
		except Exception as e:
			frappe.logger().error(f"new_atmta: failed to delete Property Setter {name} — {e}")

	frappe.db.commit()
	for doctype in ACCOUNTING_RESET_DOCTYPES:
		if frappe.db.exists("DocType", doctype):
			frappe.clear_cache(doctype=doctype)
	return stats


def hide_default_workspaces() -> dict:
	"""Hide standard workspaces not used by ATMTA clients."""
	stats = {"workspaces_hidden": 0, "hidden": []}
	for name in HIDDEN_WORKSPACES:
		if not frappe.db.exists("Workspace", name):
			continue
		if frappe.db.get_value("Workspace", name, "is_hidden"):
			continue
		frappe.db.set_value("Workspace", name, "is_hidden", 1)
		stats["workspaces_hidden"] += 1
		stats["hidden"].append(name)

	frappe.db.commit()
	return stats


def ensure_expense_dashboard_chart() -> bool:
	"""Create the expense chart referenced by the Expenses workspace."""
	if not _exists_doctype("Expense Entry"):
		return False

	chart_name = EXPENSE_CHART_NAME
	if frappe.db.exists("Dashboard Chart", chart_name):
		chart = frappe.get_doc("Dashboard Chart", chart_name)
	else:
		chart = frappe.new_doc("Dashboard Chart")
		chart.chart_name = chart_name
		chart.name = chart_name

	chart.update(
		{
			"module": "Erp Expenses" if frappe.db.exists("Module Def", "Erp Expenses") else "ATMTA Multi-Site",
			"chart_type": "Group By",
			"document_type": "Expense Entry",
			"group_by_based_on": "vendor_name",
			"group_by_type": "Sum",
			"aggregate_function_based_on": "paid_amount",
			"type": "Bar",
			"is_public": 1,
			"timeseries": 0,
			"use_report_chart": 0,
			"filters_json": json.dumps(
				[["Expense Entry", "docstatus", "=", "1", False]]
			),
		}
	)

	if chart.is_new():
		chart.insert(ignore_permissions=True)
	else:
		chart.save(ignore_permissions=True)

	# Remove legacy broken chart name if it exists with bad config.
	if frappe.db.exists("Dashboard Chart", EXPENSE_CHART_LEGACY_NAME):
		legacy = frappe.get_doc("Dashboard Chart", EXPENSE_CHART_LEGACY_NAME)
		if legacy.document_type == "Vendor" or not _exists_doctype(legacy.document_type):
			frappe.delete_doc("Dashboard Chart", EXPENSE_CHART_LEGACY_NAME, ignore_permissions=True)

	return True


def fix_workspaces() -> dict:
	stats = {
		"workspaces_updated": 0,
		"shortcuts_fixed": 0,
		"shortcuts_removed": 0,
		"quick_lists_fixed": 0,
		"quick_lists_removed": 0,
		"links_fixed": 0,
		"links_removed": 0,
		"content_blocks_removed": 0,
	}

	for ws_name in frappe.get_all("Workspace", pluck="name"):
		ws = frappe.get_doc("Workspace", ws_name)
		changed = False

		valid_shortcut_labels: set[str] = set()
		shortcut_label_remap: dict[str, str] = {}
		for shortcut in list(ws.shortcuts):
			if shortcut.type == "DocType" and shortcut.link_to:
				old_label = shortcut.label
				resolved = resolve_doctype(shortcut.link_to)
				if resolved != shortcut.link_to and _exists_doctype(resolved):
					shortcut.link_to = resolved
					if "Vendor" in (shortcut.label or ""):
						shortcut.label = (shortcut.label or "").replace("Vendor", "Supplier")
					if old_label and old_label != shortcut.label:
						shortcut_label_remap[old_label] = shortcut.label
					stats["shortcuts_fixed"] += 1
					changed = True
				elif not _exists_doctype(shortcut.link_to):
					ws.remove(shortcut)
					stats["shortcuts_removed"] += 1
					changed = True
					continue
			elif shortcut.type == "Report" and shortcut.link_to and not _exists_report(shortcut.link_to):
				ws.remove(shortcut)
				stats["shortcuts_removed"] += 1
				changed = True
				continue
			valid_shortcut_labels.add(shortcut.label)

		valid_quick_list_labels: set[str] = set()
		quick_list_label_remap: dict[str, str] = {}
		for quick_list in list(ws.quick_lists):
			if quick_list.document_type:
				old_label = quick_list.label
				resolved = resolve_doctype(quick_list.document_type)
				if resolved != quick_list.document_type and _exists_doctype(resolved):
					quick_list.document_type = resolved
					if quick_list.label == "Vendor":
						quick_list.label = "Supplier"
					if old_label and old_label != quick_list.label:
						quick_list_label_remap[old_label] = quick_list.label
					stats["quick_lists_fixed"] += 1
					changed = True
				elif not _exists_doctype(quick_list.document_type):
					ws.remove(quick_list)
					stats["quick_lists_removed"] += 1
					changed = True
					continue
			valid_quick_list_labels.add(quick_list.label)

		for link in list(ws.links):
			if link.link_to:
				if link.link_type == "DocType":
					resolved = resolve_doctype(link.link_to)
					if resolved != link.link_to and _exists_doctype(resolved):
						link.link_to = resolved
						stats["links_fixed"] += 1
						changed = True
					elif not _exists_doctype(link.link_to):
						ws.remove(link)
						stats["links_removed"] += 1
						changed = True
				elif not _link_target_exists(link.link_type, link.link_to):
					ws.remove(link)
					stats["links_removed"] += 1
					changed = True

		if ws.content:
			try:
				blocks = json.loads(ws.content)
			except json.JSONDecodeError:
				blocks = []

			new_blocks = []
			for block in blocks:
				block_type = block.get("type")
				data = block.get("data") or {}
				keep = True

				if block_type == "shortcut":
					name = data.get("shortcut_name")
					if name in shortcut_label_remap:
						data["shortcut_name"] = shortcut_label_remap[name]
						changed = True
						name = data["shortcut_name"]
					elif name in CONTENT_LABEL_REMAPS:
						mapped = CONTENT_LABEL_REMAPS[name]
						if mapped in valid_shortcut_labels:
							data["shortcut_name"] = mapped
							changed = True
							name = mapped
					keep = name in valid_shortcut_labels
				elif block_type == "quick_list":
					name = data.get("quick_list_name")
					if name in quick_list_label_remap:
						data["quick_list_name"] = quick_list_label_remap[name]
						changed = True
						name = data["quick_list_name"]
					elif name in CONTENT_LABEL_REMAPS:
						mapped = CONTENT_LABEL_REMAPS[name]
						if mapped in valid_quick_list_labels:
							data["quick_list_name"] = mapped
							changed = True
							name = mapped
					keep = name in valid_quick_list_labels
				elif block_type == "chart":
					chart_name = data.get("chart_name")
					if chart_name in CONTENT_CHART_REMAPS:
						data["chart_name"] = CONTENT_CHART_REMAPS[chart_name]
						chart_name = data["chart_name"]
						changed = True
					keep = not chart_name or _exists_chart(chart_name)

				if keep:
					new_blocks.append(block)
				else:
					stats["content_blocks_removed"] += 1
					changed = True

			if changed:
				ws.content = json.dumps(new_blocks, separators=(",", ":"))

		if changed:
			ws.save(ignore_permissions=True)
			stats["workspaces_updated"] += 1

	frappe.db.commit()
	return stats


def fix_dashboard_charts() -> dict:
	stats = {"charts_fixed": 0, "charts_removed": 0}
	for row in frappe.get_all("Dashboard Chart", fields=["name", "document_type"]):
		if not row.document_type:
			continue
		resolved = resolve_doctype(row.document_type)
		if resolved != row.document_type and _exists_doctype(resolved):
			frappe.db.set_value("Dashboard Chart", row.name, "document_type", resolved)
			stats["charts_fixed"] += 1
		elif not _exists_doctype(row.document_type):
			frappe.delete_doc("Dashboard Chart", row.name, ignore_permissions=True)
			stats["charts_removed"] += 1

	frappe.db.commit()
	return stats


def fix_number_cards() -> dict:
	stats = {"cards_fixed": 0, "cards_removed": 0}
	for row in frappe.get_all("Number Card", fields=["name", "document_type"]):
		if not row.document_type:
			continue
		resolved = resolve_doctype(row.document_type)
		if resolved != row.document_type and _exists_doctype(resolved):
			frappe.db.set_value("Number Card", row.name, "document_type", resolved)
			stats["cards_fixed"] += 1
		elif not _exists_doctype(row.document_type):
			frappe.delete_doc("Number Card", row.name, ignore_permissions=True)
			stats["cards_removed"] += 1

	frappe.db.commit()
	return stats


def disable_broken_reports() -> dict:
	stats = {"reports_disabled": 0}
	for row in frappe.db.sql(
		"""
		SELECT name, ref_doctype
		FROM `tabReport`
		WHERE disabled = 0
			AND ref_doctype IS NOT NULL
			AND ref_doctype != ''
			AND ref_doctype NOT IN (SELECT name FROM `tabDocType`)
		""",
		as_dict=True,
	):
		frappe.db.set_value("Report", row.name, "disabled", 1)
		stats["reports_disabled"] += 1

	frappe.db.commit()
	return stats


REDUNDANT_CUSTOM_FIELDS = [
	{"dt": "Purchase Invoice", "fieldname": "custom_document_no", "primary_field": "bill_no"},
	{"dt": "Cost Center", "fieldname": "abbr", "primary_field": None},
	{"dt": "Sales Invoice", "fieldname": "cost_center_abbr", "primary_field": None},
	{"dt": "Customer", "fieldname": "customer_names", "primary_field": "customer_name"},
	{"dt": "Customer", "fieldname": "cost_center", "primary_field": None},
	{"dt": "Customer", "fieldname": "custom_whatsapp_phone_nubmer", "primary_field": "custom_whatsapp_no"},
	{
		"dt": "Customer",
		"fieldname": "custom_customer_name_in_arabic",
		"primary_field": "customer_name_in_arabic",
	},
	{"dt": "Customer", "fieldname": "custom_customer_name_english", "primary_field": "customer_name"},
	{"dt": "Supplier", "fieldname": "cost_center", "primary_field": None},
	{"dt": "Supplier", "fieldname": "custom_supplier_name_english", "primary_field": "supplier_name"},
	{"dt": "Item", "fieldname": "custom_item_series_no", "primary_field": None},
	{"dt": "Item", "fieldname": "cost_center", "primary_field": None},
]

IMPORTANT_FIELD_VISIBILITY_SETTERS = [
	{"doc_type": "Customer", "field_name": "default_price_list", "property": "hidden"},
	{"doc_type": "Sales Invoice", "field_name": "set_warehouse", "property": "hidden"},
]

MASTER_LAYOUT_DOCTYPES = ("Customer", "Supplier", "Item")

CUSTOM_FIELD_INSERT_AFTER_FIXES = [
	{"dt": "Customer", "fieldname": "customer_name_in_arabic", "insert_after": "customer_name"},
	{"dt": "Customer", "fieldname": "custom_customer_types", "insert_after": "customer_type"},
	{"dt": "Customer", "fieldname": "custom_whatsapp_no", "insert_after": "mobile_no"},
	{"dt": "Customer", "fieldname": "custom_section_break_nxdgf", "insert_after": "tax_id"},
	{"dt": "Customer", "fieldname": "custom_vat_registration_number", "insert_after": "custom_section_break_nxdgf"},
	{"dt": "Customer", "fieldname": "custom_crn", "insert_after": "custom_vat_registration_number"},
	{"dt": "Customer", "fieldname": "custom_additional_ids", "insert_after": "custom_crn"},
	{"dt": "Customer", "fieldname": "default_warehouse", "insert_after": "default_price_list"},
	{"dt": "Supplier", "fieldname": "supplier_name_in_arabic", "insert_after": "supplier_name"},
	{"dt": "Supplier", "fieldname": "custom_crn_no", "insert_after": "tax_id"},
	{"dt": "Supplier", "fieldname": "default_warehouse", "insert_after": "default_price_list"},
	{"dt": "Item", "fieldname": "item_name_in_arabic", "insert_after": "item_name"},
	{"dt": "Item", "fieldname": "sku_code", "insert_after": "item_name_in_arabic"},
	{"dt": "Item", "fieldname": "is_zero_rated", "insert_after": "item_tax_section_break"},
	{"dt": "Item", "fieldname": "is_exempt", "insert_after": "is_zero_rated"},
	{"dt": "Item", "fieldname": "print_item_order", "insert_after": "brand"},
	{"dt": "Item", "fieldname": "custom_section_break_m5v83", "insert_after": "print_item_order"},
	{"dt": "Item", "fieldname": "packaging", "insert_after": "sales_details"},
	{"dt": "Item", "fieldname": "custom_discount_allowed", "insert_after": "is_sales_item"},
	{"dt": "Item", "fieldname": "supplier_item_code", "insert_after": "supplier_details"},
]

REMOVED_INSERT_AFTER_TARGETS = {
	"customer_names": "customer_name",
	"custom_customer_name_in_arabic": "customer_name",
	"custom_customer_name_english": "customer_name_in_arabic",
	"custom_supplier_name_english": "supplier_name_in_arabic",
	"custom_whatsapp_phone_nubmer": "customer_name",
	"custom_item_series_no": "naming_series",
	"cost_center": "default_price_list",
	"custom_document_no": "bill_no",
	"document_no": "bill_no",
}

CALC_PARENT_DOCTYPES = [
	"Quotation",
	"Sales Order",
	"Sales Invoice",
	"Purchase Order",
	"Purchase Invoice",
	"Delivery Note",
	"Purchase Receipt",
	"Expense Entry",
]

CALC_CHILD_DOCTYPES = [
	"Quotation Item",
	"Sales Order Item",
	"Sales Invoice Item",
	"Purchase Order Item",
	"Purchase Invoice Item",
	"Delivery Note Item",
	"Purchase Receipt Item",
	"Expense Entry Account",
]

CALC_FIELD_NAMES = [
	"qty",
	"stock_qty",
	"rate",
	"net_rate",
	"amount",
	"net_amount",
	"base_rate",
	"base_amount",
	"price_list_rate",
	"discount_percentage",
	"discount_amount",
	"conversion_factor",
	"taxable_amount",
	"vat_amount",
	"paid_amount",
	"total_taxable_amount",
	"total_vat",
]

CALC_FIELD_TYPES = ("Float", "Currency", "Percent")
SMART_PRECISION = "6"


def enable_server_scripts() -> dict:
	"""Enable server scripts via bench common_site_config (required by Frappe)."""
	import os

	from frappe.utils import get_bench_path

	config_path = os.path.join(get_bench_path(), "sites", "common_site_config.json")
	config = {}
	if os.path.exists(config_path):
		with open(config_path, encoding="utf-8") as f:
			config = json.load(f)

	changed = config.get("server_script_enabled") not in (True, 1, "1", "true")
	config["server_script_enabled"] = True

	with open(config_path, "w", encoding="utf-8") as f:
		json.dump(config, f, indent=1, ensure_ascii=False)
		f.write("\n")

	# Per-site flag for visibility in site_config.json
	from frappe.installer import update_site_config

	update_site_config("server_script_enabled", 1)

	return {"common_site_config_updated": changed, "server_script_enabled": True}


def remove_redundant_custom_fields() -> dict:
	"""Remove custom fields that duplicate standard fields (e.g. Document No vs bill_no)."""
	stats = {"fields_removed": 0, "data_migrated": 0, "insert_after_fixed": 0, "removed": []}

	for spec in REDUNDANT_CUSTOM_FIELDS:
		dt = spec["dt"]
		fieldname = spec["fieldname"]
		primary = spec["primary_field"]
		cf_names = frappe.get_all(
			"Custom Field",
			filters={"dt": dt, "fieldname": fieldname},
			pluck="name",
		)

		if not cf_names:
			continue

		table = f"tab{dt}"
		if primary and frappe.db.has_column(dt, fieldname) and frappe.db.has_column(dt, primary):
			migrated = frappe.db.sql(
				f"""
				UPDATE `{table}`
				SET `{primary}` = `{fieldname}`
				WHERE (`{primary}` IS NULL OR `{primary}` = '')
					AND `{fieldname}` IS NOT NULL AND `{fieldname}` != ''
				"""
			)
			stats["data_migrated"] += migrated or 0

		for cf_name in cf_names:
			try:
				frappe.delete_doc("Custom Field", cf_name, force=True, ignore_permissions=True)
				stats["fields_removed"] += 1
				stats["removed"].append(cf_name)
			except Exception as e:
				frappe.logger().error(f"new_atmta: cannot delete {cf_name} — {e}")

	if stats["removed"]:
		clean_property_setters_field_order(
			{spec["fieldname"] for spec in REDUNDANT_CUSTOM_FIELDS}
			| {"document_no", "custom_document_no"}
		)

	for spec in CUSTOM_FIELD_INSERT_AFTER_FIXES:
		stats["insert_after_fixed"] += frappe.db.set_value(
			"Custom Field",
			{"dt": spec["dt"], "fieldname": spec["fieldname"]},
			"insert_after",
			spec["insert_after"],
		) or 0

	for old_target, new_target in REMOVED_INSERT_AFTER_TARGETS.items():
		stats["insert_after_fixed"] += frappe.db.sql(
			"""
			UPDATE `tabCustom Field`
			SET insert_after = %s
			WHERE insert_after = %s
			""",
			(new_target, old_target),
		) or 0

	frappe.db.commit()
	for doctype in ("Customer", "Supplier", "Item", "Purchase Invoice"):
		if frappe.db.exists("DocType", doctype):
			frappe.clear_cache(doctype=doctype)
	return stats


def remove_bad_layout_property_setters() -> dict:
	"""Remove brittle form layout setters and restore critical standard fields."""
	stats = {
		"field_order_removed": 0,
		"master_standard_setters_removed": 0,
		"visibility_setters_removed": 0,
	}

	for name in frappe.get_all("Property Setter", filters={"property": "field_order"}, pluck="name"):
		frappe.delete_doc("Property Setter", name, ignore_permissions=True)
		stats["field_order_removed"] += 1

	custom_fields = {
		(row.dt, row.fieldname)
		for row in frappe.get_all(
			"Custom Field",
			filters={"dt": ["in", MASTER_LAYOUT_DOCTYPES]},
			fields=["dt", "fieldname"],
		)
	}
	for row in frappe.get_all(
		"Property Setter",
		filters={"doc_type": ["in", MASTER_LAYOUT_DOCTYPES]},
		fields=["name", "doc_type", "field_name"],
	):
		if row.field_name and (row.doc_type, row.field_name) in custom_fields:
			continue
		frappe.delete_doc("Property Setter", row.name, ignore_permissions=True)
		stats["master_standard_setters_removed"] += 1

	for spec in IMPORTANT_FIELD_VISIBILITY_SETTERS:
		for name in frappe.get_all("Property Setter", filters=spec, pluck="name"):
			frappe.delete_doc("Property Setter", name, ignore_permissions=True)
			stats["visibility_setters_removed"] += 1

	frappe.db.commit()
	for doctype in ("Customer", "Supplier", "Item", "Sales Invoice", "Purchase Invoice"):
		if frappe.db.exists("DocType", doctype):
			frappe.clear_cache(doctype=doctype)
	return stats


def restore_ksa_payment_entry_customizations() -> dict:
	"""Restore Payment Entry customizations owned by ksa_compliance.

	new_atmta must not own or delete these fields, but it repairs sites where an
	older cleanup removed them so ksa_compliance can validate prepayment invoices.
	"""
	stats = {
		"applied": False,
		"custom_fields_created": 0,
		"custom_fields_existing": 0,
		"property_setters_created": 0,
		"property_setters_existing": 0,
	}

	if "ksa_compliance" not in frappe.get_installed_apps():
		stats["reason"] = "ksa_compliance not installed"
		return stats

	try:
		path = frappe.get_app_path("ksa_compliance", "ksa_compliance", "custom", "payment_entry.json")
	except Exception as e:
		stats["reason"] = f"cannot resolve ksa_compliance path: {e}"
		return stats

	try:
		with open(path, encoding="utf-8") as f:
			data = json.load(f)
	except Exception as e:
		stats["reason"] = f"cannot read payment_entry.json: {e}"
		return stats

	for record in data.get("custom_fields") or []:
		name = record.get("name")
		if not name:
			continue
		doc_data = _clean_import_record(record, "Custom Field")
		if frappe.db.exists("Custom Field", name):
			stats["custom_fields_existing"] += 1
		else:
			frappe.get_doc(doc_data).insert(ignore_permissions=True)
			stats["custom_fields_created"] += 1

	for record in data.get("property_setters") or []:
		name = record.get("name")
		if not name:
			continue
		doc_data = _clean_import_record(record, "Property Setter")
		if frappe.db.exists("Property Setter", name):
			stats["property_setters_existing"] += 1
		else:
			frappe.get_doc(doc_data).insert(ignore_permissions=True)
			stats["property_setters_created"] += 1

	frappe.db.commit()
	frappe.clear_cache(doctype="Payment Entry")
	stats["applied"] = True
	return stats


def _clean_import_record(record: dict, doctype: str) -> dict:
	doc_data = {
		key: value
		for key, value in record.items()
		if key
		not in {
			"_assign",
			"_comments",
			"_liked_by",
			"_user_tags",
			"docstatus",
			"idx",
			"parent",
			"parentfield",
			"parenttype",
		}
	}
	doc_data["doctype"] = doctype
	return doc_data


def ensure_shared_link_doctypes() -> dict:
	"""Create shared DocTypes required by shipped Link custom fields."""
	try:
		from new_atmta.install import ensure_common_doctypes

		ensure_common_doctypes()
	except Exception as e:
		frappe.logger().error(f"new_atmta: shared DocType creation failed — {e}")

	return {
		"customer_types_exists": bool(frappe.db.exists("DocType", "Customer Types")),
	}


def remove_broken_link_custom_fields() -> dict:
	"""Delete Custom Fields that point to missing DocTypes.

	These fields block DocType loading with "Missing DocType" dialogs. Shared
	DocTypes are created first, so we only delete genuinely orphaned references.
	"""
	ensure_shared_link_doctypes()
	stats = {"fields_removed": 0, "removed": []}
	link_fieldtypes = ("Link", "Dynamic Link", "Table", "Table MultiSelect")

	rows = frappe.db.sql(
		"""
		SELECT name, dt, fieldname, fieldtype, options
		FROM `tabCustom Field`
		WHERE fieldtype IN %s
			AND options IS NOT NULL
			AND options != ''
			AND options NOT IN (SELECT name FROM `tabDocType`)
		ORDER BY dt, fieldname
		""",
		(link_fieldtypes,),
		as_dict=True,
	)

	for row in rows:
		# Dynamic Link options points to a fieldname that stores the DocType name,
		# not to a DocType. Keep it unless the referenced field itself is missing.
		if row.fieldtype == "Dynamic Link":
			parent_has_field = bool(
				frappe.db.exists("DocField", {"parent": row.dt, "fieldname": row.options})
				or frappe.db.exists("Custom Field", {"dt": row.dt, "fieldname": row.options})
			)
			if parent_has_field:
				continue

		try:
			frappe.delete_doc("Custom Field", row.name, force=True, ignore_permissions=True)
			stats["fields_removed"] += 1
			stats["removed"].append(
				{
					"name": row.name,
					"dt": row.dt,
					"fieldname": row.fieldname,
					"fieldtype": row.fieldtype,
					"missing_doctype": row.options,
				}
			)
		except Exception as e:
			frappe.logger().error(f"new_atmta: cannot delete broken field {row.name} — {e}")

	if stats["removed"]:
		clean_property_setters_field_order({row["fieldname"] for row in stats["removed"]})

	frappe.db.commit()
	for row in stats["removed"]:
		frappe.clear_cache(doctype=row["dt"])
	return stats


def remove_broken_fetch_custom_fields() -> dict:
	"""Delete derived custom fields whose fetch_from points to missing metadata."""
	stats = {"fields_removed": 0, "removed": []}

	for row in frappe.get_all(
		"Custom Field",
		filters=[["fetch_from", "is", "set"]],
		fields=["name", "dt", "fieldname", "fetch_from"],
	):
		if not _is_broken_fetch_from(row.dt, row.fetch_from):
			continue
		try:
			frappe.delete_doc("Custom Field", row.name, force=True, ignore_permissions=True)
			stats["fields_removed"] += 1
			stats["removed"].append(
				{
					"name": row.name,
					"dt": row.dt,
					"fieldname": row.fieldname,
					"fetch_from": row.fetch_from,
				}
			)
		except Exception as e:
			frappe.logger().error(f"new_atmta: cannot delete broken fetch field {row.name} — {e}")

	if stats["removed"]:
		clean_property_setters_field_order({row["fieldname"] for row in stats["removed"]})

	frappe.db.commit()
	for row in stats["removed"]:
		frappe.clear_cache(doctype=row["dt"])
	return stats


def _is_broken_fetch_from(parent_dt: str, fetch_from: str | None) -> bool:
	if not fetch_from or "." not in fetch_from:
		return False
	source_field, target_field = fetch_from.split(".", 1)
	if not source_field or not target_field:
		return False

	source_df = _get_field_definition(parent_dt, source_field)
	if not source_df:
		return True

	target_dt = source_df.get("options") if source_df.get("fieldtype") == "Link" else None
	if not target_dt:
		return False
	if not frappe.db.exists("DocType", target_dt):
		return True
	return not _get_field_definition(target_dt, target_field)


def _get_field_definition(parent_dt: str, fieldname: str) -> dict | None:
	docfield = frappe.db.get_value(
		"DocField",
		{"parent": parent_dt, "fieldname": fieldname},
		["fieldname", "fieldtype", "options"],
		as_dict=True,
	)
	if docfield:
		return docfield
	return frappe.db.get_value(
		"Custom Field",
		{"dt": parent_dt, "fieldname": fieldname},
		["fieldname", "fieldtype", "options"],
		as_dict=True,
	)


def scan_broken_link_custom_fields() -> dict:
	"""Report Custom Fields whose options point to missing DocTypes."""
	link_fieldtypes = ("Link", "Dynamic Link", "Table", "Table MultiSelect")
	broken = []
	for row in frappe.db.sql(
		"""
		SELECT name, dt, fieldname, fieldtype, options
		FROM `tabCustom Field`
		WHERE fieldtype IN %s
			AND options IS NOT NULL
			AND options != ''
			AND options NOT IN (SELECT name FROM `tabDocType`)
		ORDER BY dt, fieldname
		""",
		(link_fieldtypes,),
		as_dict=True,
	):
		if row.fieldtype == "Dynamic Link":
			parent_has_field = bool(
				frappe.db.exists("DocField", {"parent": row.dt, "fieldname": row.options})
				or frappe.db.exists("Custom Field", {"dt": row.dt, "fieldname": row.options})
			)
			if parent_has_field:
				continue
		broken.append(row)

	return {"count": len(broken), "broken": broken}


def remove_precision_property_setters() -> dict:
	"""Delete precision property setters that break currency/qty calculations."""
	names = frappe.get_all("Property Setter", filters={"property": "precision"}, pluck="name")
	stats = {"removed": 0}
	for name in names:
		frappe.delete_doc("Property Setter", name, ignore_permissions=True)
		stats["removed"] += 1

	frappe.db.commit()
	return stats


def ensure_calculation_field_precision() -> dict:
	"""Set precision=6 on qty/rate/amount fields for accurate totals."""
	stats = {"docfields_updated": 0, "custom_fields_updated": 0}
	doctypes = list({*CALC_PARENT_DOCTYPES, *CALC_CHILD_DOCTYPES})

	for dt in doctypes:
		for fieldname in CALC_FIELD_NAMES:
			updated = frappe.db.sql(
				"""
				UPDATE `tabDocField`
				SET `precision` = %s
				WHERE parent = %s
					AND fieldname = %s
					AND fieldtype IN %s
					AND (`precision` IS NULL OR `precision` = '' OR CAST(`precision` AS UNSIGNED) < %s)
				""",
				(SMART_PRECISION, dt, fieldname, CALC_FIELD_TYPES, int(SMART_PRECISION)),
			)
			stats["docfields_updated"] += updated or 0

		for fieldname in CALC_FIELD_NAMES:
			updated = frappe.db.sql(
				"""
				UPDATE `tabCustom Field`
				SET `precision` = %s
				WHERE dt = %s
					AND fieldname = %s
					AND fieldtype IN %s
					AND (`precision` IS NULL OR `precision` = '' OR CAST(`precision` AS UNSIGNED) < %s)
				""",
				(SMART_PRECISION, dt, fieldname, CALC_FIELD_TYPES, int(SMART_PRECISION)),
			)
			stats["custom_fields_updated"] += updated or 0

	frappe.db.commit()
	for dt in doctypes:
		frappe.clear_cache(doctype=dt)
	return stats


def ensure_expense_entry_ref_no_required() -> dict:
	"""Make ref_no mandatory on Expense Entry (erp_expenses sites)."""
	if not frappe.db.exists("DocType", "Expense Entry"):
		return {"applied": False, "reason": "Expense Entry not installed"}

	name = "Expense Entry-ref_no-reqd"
	values = {
		"doc_type": "Expense Entry",
		"doctype_or_field": "DocField",
		"field_name": "ref_no",
		"property": "reqd",
		"property_type": "Check",
		"value": "1",
	}

	if frappe.db.exists("Property Setter", name):
		frappe.db.set_value("Property Setter", name, "value", "1")
	else:
		doc = frappe.get_doc({"doctype": "Property Setter", "name": name, **values})
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
	frappe.clear_cache(doctype="Expense Entry")
	return {"applied": True, "property_setter": name}


def enforce_striangle_tax_id() -> dict:
	"""Pin Striangle company VAT number and invoice print formats.

	This is intentionally site-specific because Striangle's VAT number must not
	be overwritten by fixtures/imports during future migrate runs.
	"""
	if frappe.local.site != STRIANGLE_SITE:
		return {"applied": False, "reason": "not striangle site"}

	stats = {
		"applied": True,
		"companies_updated": 0,
		"print_formats_updated": 0,
		"tax_id": STRIANGLE_TAX_ID,
	}

	for company in frappe.get_all("Company", pluck="name"):
		if frappe.db.get_value("Company", company, "tax_id") != STRIANGLE_TAX_ID:
			frappe.db.set_value("Company", company, "tax_id", STRIANGLE_TAX_ID)
			stats["companies_updated"] += 1

	invoice_doctypes = ("Sales Invoice", "POS Invoice", "Purchase Invoice")
	for pf in frappe.get_all(
		"Print Format",
		filters={"doc_type": ["in", invoice_doctypes]},
		fields=["name", "html", "format_data"],
	):
		changed = False
		for field in ("html", "format_data"):
			value = pf.get(field)
			if not value or STRIANGLE_TAX_ID in value:
				continue
			if "Company" in value and "tax_id" in value:
				# Keep the format dynamic, but make future renders use the pinned
				# Company.tax_id maintained above instead of hard-coding many places.
				continue
			new_value = re.sub(r"\b3\d{14}\b", STRIANGLE_TAX_ID, value)
			if new_value != value:
				value = new_value
				changed = True
			if changed:
				frappe.db.set_value("Print Format", pf.name, field, value)

		if changed:
			stats["print_formats_updated"] += 1

	frappe.db.commit()
	frappe.clear_cache(doctype="Company")
	frappe.cache.delete_key("print_format")
	return stats


def apply_performance_settings() -> dict:
	"""Apply safe site-level performance defaults."""
	from frappe.installer import update_site_config

	from new_atmta.bench_performance import tune_v15_bench

	bench_tune = tune_v15_bench()
	hooks_order = ensure_new_atmta_hooks_last()

	updates = {
		"developer_mode": 0,
		"disable_website_cache": 0,
		"enable_frappe_logger": 0,
		"maintenance_mode": 0,
		"pause_scheduler": 0,
	}
	for key, value in updates.items():
		update_site_config(key, value)

	# System-level cache flags
	for field, value in (
		("enable_scheduler", 1),
		("deny_multiple_sessions", 0),
	):
		if frappe.db.exists("DocType", "System Settings"):
			try:
				frappe.db.set_single_value("System Settings", field, value)
			except Exception:
				pass

	frappe.db.commit()
	frappe.cache.delete_key("bootinfo")
	return {
		"site_config_updated": list(updates.keys()),
		"bench_tune": bench_tune,
		"hooks_order": hooks_order,
	}


def ensure_new_atmta_hooks_last() -> dict:
	"""Load new_atmta after nxt_theme so desk_cache override wins."""
	apps = frappe.get_installed_apps()
	if "new_atmta" not in apps:
		return {"changed": False, "reason": "new_atmta not installed"}

	ordered = [app for app in apps if app != "new_atmta"]
	ordered.append("new_atmta")
	if ordered == apps:
		return {"changed": False, "apps": apps}

	frappe.db.set_global("installed_apps", json.dumps(ordered))
	frappe.cache.delete_key("app_hooks")
	frappe.cache.delete_key("installed_apps")
	return {"changed": True, "before": apps, "after": ordered}


def clear_all_caches() -> None:
	from new_atmta.desk_cache import clear_workspace_cache

	clear_workspace_cache()
	frappe.clear_cache()
	for key in ("bootinfo", "app_hooks", "installed_apps"):
		frappe.cache.delete_key(key)


def run_integrity_fixes() -> dict:
	"""Focused data integrity repair for missing DocType references."""
	results = {
		"before": scan_broken_link_custom_fields(),
		"shared_doctypes": ensure_shared_link_doctypes(),
		"accounting_doctype_reset": remove_accounting_doctype_customizations(),
		"redundant_fields": remove_redundant_custom_fields(),
		"layout_property_setters": remove_bad_layout_property_setters(),
		"ksa_payment_entry": restore_ksa_payment_entry_customizations(),
		"broken_fetch_fields": remove_broken_fetch_custom_fields(),
		"broken_link_fields": remove_broken_link_custom_fields(),
		"orphan_fields": remove_orphan_custom_fields(),
		"striangle_tax_id": enforce_striangle_tax_id(),
	}
	clear_all_caches()
	results["after"] = scan_broken_link_custom_fields()
	return results


def run_all() -> dict:
	"""Run all maintenance tasks. Called automatically on migrate."""
	frappe.logger().info(f"new_atmta: running site maintenance on {frappe.local.site}")

	results = {
		"before": scan_broken(),
		"server_scripts": enable_server_scripts(),
		"shared_doctypes": ensure_shared_link_doctypes(),
		"accounting_doctype_reset": remove_accounting_doctype_customizations(),
		"redundant_fields": remove_redundant_custom_fields(),
		"layout_property_setters": remove_bad_layout_property_setters(),
		"ksa_payment_entry": restore_ksa_payment_entry_customizations(),
		"broken_fetch_fields": remove_broken_fetch_custom_fields(),
		"broken_link_fields": remove_broken_link_custom_fields(),
		"precision_setters": remove_precision_property_setters(),
		"field_precision": ensure_calculation_field_precision(),
		"orphan_fields": remove_orphan_custom_fields(),
		"expense_chart": ensure_expense_dashboard_chart(),
		"workspaces": fix_workspaces(),
		"hidden_workspaces": hide_default_workspaces(),
		"dashboard_charts": fix_dashboard_charts(),
		"number_cards": fix_number_cards(),
		"reports": disable_broken_reports(),
		"expense_entry": ensure_expense_entry_ref_no_required(),
		"striangle_tax_id": enforce_striangle_tax_id(),
		"performance": apply_performance_settings(),
	}

	clear_all_caches()
	results["after"] = scan_broken()

	frappe.logger().info(f"new_atmta: maintenance complete — {results}")
	return results
