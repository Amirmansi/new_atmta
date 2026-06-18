"""Site-specific naming-series guards for ATMTA multi-site benches.

This module fixes a production failure mode where layout/metadata cleanup can
remove site-specific `naming_series` property setters and new ledger documents
fall back to generic ERPNext series such as `SINV-.YYYY.-`.

The guard is intentionally conservative:
- It only runs on configured sites.
- It only changes `naming_series` before the document name is generated.
- It does not rename existing documents.
- It skips returns, because return naming can be legally/reporting sensitive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import frappe


LEDGER_SERIES_DOCTYPES = [
	"Sales Invoice",
	"POS Invoice",
	"Delivery Note",
	"Sales Order",
	"Purchase Invoice",
	"Purchase Order",
	"Purchase Receipt",
	"Stock Entry",
	"Stock Reconciliation",
	"Payment Entry",
	"Journal Entry",
]


@dataclass(frozen=True)
class SeriesRule:
	default: str
	by_cost_center_prefix: dict[str, str] = field(default_factory=dict)


SITE_SERIES_RULES: dict[str, dict[str, SeriesRule]] = {
	"gazzal.atmta-erp.com": {
		"Sales Invoice": SeriesRule(
			default="K-INV-.YYYY.-",
			by_cost_center_prefix={"2 -": "AZ-INV-.YYYY.-"},
		),
		"Purchase Invoice": SeriesRule(
			default="K-PUR-.YYYY.-",
			by_cost_center_prefix={"2 -": "AZ-PUR-.YYYY.-"},
		),
		"Payment Entry": SeriesRule(default="k-PAY-.YYYY.-"),
		"Journal Entry": SeriesRule(default="k-JV-.YYYY.-"),
	},
	"atmta-finance.atmta-erp.com": {
		"Sales Invoice": SeriesRule(default="ACC-SINV-.YYYY.-"),
		"Purchase Invoice": SeriesRule(default="ACC-PINV-.YYYY.-"),
		"Payment Entry": SeriesRule(default="ACC-PAY-.YYYY.-"),
		"Journal Entry": SeriesRule(default="ACC-JV-.YYYY.-"),
		"Delivery Note": SeriesRule(default="MAT-DN-.YYYY.-"),
		"Purchase Receipt": SeriesRule(default="MAT-PRE-.YYYY.-"),
		"Stock Entry": SeriesRule(default="MAT-STE-.YYYY.-"),
	},
	"atmta.atmta-erp.com": {
		"Sales Invoice": SeriesRule(default="atmta-SINV--.YYYY.-"),
	},
	"ayash.atmta-erp.com": {
		"Sales Invoice": SeriesRule(default="ACC-SINV-.YYYY.-"),
	},
	"btack.atmta-erp.com": {
		"Sales Invoice": SeriesRule(default="ACC-SINV-.YYYY.-"),
		"Purchase Invoice": SeriesRule(default="ACC-PINV-.YYYY.-"),
		"Payment Entry": SeriesRule(default="ACC-PAY-.YYYY.-"),
		"Delivery Note": SeriesRule(default="MAT-DN-.YYYY.-"),
		"Purchase Receipt": SeriesRule(default="MAT-PRE-.YYYY.-"),
		"Stock Entry": SeriesRule(default="MAT-STE-.YYYY.-"),
	},
}


def _site_rules() -> dict[str, SeriesRule]:
	return SITE_SERIES_RULES.get(getattr(frappe.local, "site", ""), {})


def _is_return_doc(doc) -> bool:
	return bool(getattr(doc, "is_return", 0) or getattr(doc, "return_against", None))


def _get_cost_center(doc) -> str:
	if getattr(doc, "cost_center", None):
		return doc.cost_center or ""

	for table_field in ("items", "accounts", "taxes"):
		for row in doc.get(table_field) or []:
			if getattr(row, "cost_center", None):
				return row.cost_center or ""

	return ""


def _series_for_doc(doc, rule: SeriesRule) -> str:
	cost_center = _get_cost_center(doc)
	for prefix, series in rule.by_cost_center_prefix.items():
		if cost_center.startswith(prefix):
			return series
	return rule.default


def apply_naming_series_guard(doc, method=None) -> None:
	"""DocType before_insert hook: set the intended series before autoname."""
	rule = _site_rules().get(doc.doctype)
	if not rule or _is_return_doc(doc):
		return

	series = _series_for_doc(doc, rule)
	if doc.meta.has_field("naming_series"):
		doc.naming_series = series


def _set_property_setter(doctype: str, fieldname: str, prop: str, value: str, prop_type: str = "Text") -> bool:
	name = f"{doctype}-{fieldname}-{prop}"
	values = {
		"doctype_or_field": "DocField",
		"doc_type": doctype,
		"field_name": fieldname,
		"property": prop,
		"property_type": prop_type,
		"value": value,
	}
	if frappe.db.exists("Property Setter", name):
		current = frappe.db.get_value("Property Setter", name, "value")
		if current == value:
			return False
		frappe.db.set_value("Property Setter", name, "value", value)
		return True

	doc = frappe.get_doc({"doctype": "Property Setter", "name": name, **values})
	doc.insert(ignore_permissions=True)
	return True


def _current_options(doctype: str) -> list[str]:
	meta = frappe.get_meta(doctype)
	field = meta.get_field("naming_series")
	if not field:
		return []
	return [option.strip() for option in (field.options or "").split("\n") if option.strip()]


def _configured_options(rule: SeriesRule) -> list[str]:
	options = [rule.default]
	for series in rule.by_cost_center_prefix.values():
		if series not in options:
			options.append(series)
	return options


def ensure_series_property_setters() -> dict:
	"""Restore site-specific naming series options/defaults after migrations."""
	stats = {"site": frappe.local.site, "updated": 0, "doctypes": []}
	for doctype, rule in _site_rules().items():
		if not frappe.db.exists("DocType", doctype):
			continue

		options = _current_options(doctype)
		for series in _configured_options(rule):
			if series not in options:
				options.insert(0, series)

		if _set_property_setter(doctype, "naming_series", "options", "\n".join(options)):
			stats["updated"] += 1
		if _set_property_setter(doctype, "naming_series", "default", rule.default):
			stats["updated"] += 1

		frappe.clear_cache(doctype=doctype)
		stats["doctypes"].append(doctype)

	frappe.db.commit()
	return stats


_SERIES_NAME_RE = re.compile(r"^(?P<prefix>.*?)(?P<year>\d{4})-(?P<num>\d+)(?:-\d+)?$")


def _series_key_and_number(name: str) -> tuple[str, int] | None:
	match = _SERIES_NAME_RE.match(name or "")
	if not match:
		return None
	return f"{match.group('prefix')}{match.group('year')}-", int(match.group("num"))


def sync_series_current_from_documents() -> dict:
	"""Raise tabSeries.current to the max number already present in documents.

	This prevents a restored series from starting again at 1. Existing documents
	are never renamed.
	"""
	stats = {"site": frappe.local.site, "series_checked": 0, "series_updated": 0}
	for doctype in LEDGER_SERIES_DOCTYPES:
		if not frappe.db.table_exists(doctype):
			continue
		max_by_key: dict[str, int] = {}
		for row in frappe.get_all(doctype, fields=["name"], limit_page_length=0):
			parsed = _series_key_and_number(row.name)
			if not parsed:
				continue
			key, number = parsed
			max_by_key[key] = max(max_by_key.get(key, 0), number)

		for key, number in max_by_key.items():
			stats["series_checked"] += 1
			current = frappe.db.sql("select current from tabSeries where name=%s", (key,))
			if current:
				if int(current[0][0] or 0) < number:
					frappe.db.sql("update tabSeries set current=%s where name=%s", (number, key))
					stats["series_updated"] += 1
			else:
				frappe.db.sql("insert into tabSeries (name, current) values (%s, %s)", (key, number))
				stats["series_updated"] += 1

	frappe.db.commit()
	return stats


def apply_series_integrity_fixes() -> dict:
	return {
		"property_setters": ensure_series_property_setters(),
		"series_current": sync_series_current_from_documents(),
	}
