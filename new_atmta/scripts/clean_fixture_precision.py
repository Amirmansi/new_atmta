"""
Clean fixture JSON files: remove precision property setters, redundant fields, etc.
"""

from __future__ import annotations

import json
import os

import frappe

LINK_NUMERIC_TYPES = {"Float", "Currency", "Percent", "Int"}

# Custom fields that duplicate a standard field — remove custom, keep standard.
REDUNDANT_CUSTOM_FIELDS = [
	{"dt": "Purchase Invoice", "fieldname": "custom_document_no", "primary_field": "bill_no"},
	{"dt": "Customer", "fieldname": "customer_names", "primary_field": "customer_name"},
	{"dt": "Customer", "fieldname": "cost_center", "primary_field": None},
	{"dt": "Customer", "fieldname": "custom_whatsapp_phone_nubmer", "primary_field": "custom_whatsapp_no"},
	{"dt": "Customer", "fieldname": "custom_customer_name_in_arabic", "primary_field": "customer_name_in_arabic"},
	{"dt": "Customer", "fieldname": "custom_customer_name_english", "primary_field": "customer_name"},
	{"dt": "Supplier", "fieldname": "cost_center", "primary_field": None},
	{"dt": "Supplier", "fieldname": "custom_supplier_name_english", "primary_field": "supplier_name"},
	{"dt": "Item", "fieldname": "custom_item_series_no", "primary_field": None},
	{"dt": "Item", "fieldname": "cost_center", "primary_field": None},
]

FIELDNAMES_TO_STRIP_FROM_ORDER = {
	"custom_document_no",
	"document_no",
	"customer_names",
	"cost_center",
	"custom_item_series_no",
	"custom_customer_name_in_arabic",
	"custom_customer_name_english",
	"custom_supplier_name_english",
	"custom_whatsapp_phone_nubmer",
}

CANONICAL_INSERT_AFTER = {
	("Customer", "customer_name_in_arabic"): "customer_name",
	("Customer", "custom_customer_types"): "customer_type",
	("Customer", "custom_whatsapp_no"): "mobile_no",
	("Customer", "custom_section_break_nxdgf"): "tax_id",
	("Customer", "custom_vat_registration_number"): "custom_section_break_nxdgf",
	("Customer", "custom_crn"): "custom_vat_registration_number",
	("Customer", "custom_additional_ids"): "custom_crn",
	("Customer", "default_warehouse"): "default_price_list",
	("Supplier", "supplier_name_in_arabic"): "supplier_name",
	("Supplier", "custom_crn_no"): "tax_id",
	("Supplier", "default_warehouse"): "default_price_list",
	("Item", "item_name_in_arabic"): "item_name",
	("Item", "sku_code"): "item_name_in_arabic",
	("Item", "is_zero_rated"): "item_tax_section_break",
	("Item", "is_exempt"): "is_zero_rated",
	("Item", "print_item_order"): "brand",
	("Item", "custom_section_break_m5v83"): "print_item_order",
	("Item", "packaging"): "sales_details",
	("Item", "custom_discount_allowed"): "is_sales_item",
	("Item", "supplier_item_code"): "supplier_details",
}

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

MASTER_LAYOUT_DOCTYPES = {"Customer", "Supplier", "Item"}

IMPORTANT_FIELD_VISIBILITY_SETTERS = {
	("Customer", "default_price_list", "hidden"),
	("Sales Invoice", "set_warehouse", "hidden"),
}


def _clean_field_order_value(value: str, extra_remove: set[str]) -> str | None:
	if not value:
		return value
	try:
		fields = json.loads(value)
	except json.JSONDecodeError:
		return value
	if not isinstance(fields, list):
		return value
	remove = FIELDNAMES_TO_STRIP_FROM_ORDER | extra_remove
	new_fields = [f for f in fields if f not in remove]
	if new_fields == fields:
		return value
	return json.dumps(new_fields)


def _fix_insert_after(record: dict) -> bool:
	key = (record.get("dt"), record.get("fieldname"))
	insert_after = CANONICAL_INSERT_AFTER.get(key)
	if insert_after and record.get("insert_after") != insert_after:
		record["insert_after"] = insert_after
		return True
	insert_after = REMOVED_INSERT_AFTER_TARGETS.get(record.get("insert_after"))
	if insert_after:
		record["insert_after"] = insert_after
		return True
	return False


def _process_custom_field_file(filepath: str) -> set[str]:
	with open(filepath, encoding="utf-8") as f:
		records = json.load(f)
	if not isinstance(records, list):
		return set()

	removed_names: set[str] = set()
	kept = []
	changed = False
	for record in records:
		fieldname = record.get("fieldname") or ""
		dt = record.get("dt") or ""
		if any(r["dt"] == dt and r["fieldname"] == fieldname for r in REDUNDANT_CUSTOM_FIELDS):
			removed_names.add(fieldname)
			if record.get("name"):
				removed_names.add(record["name"])
			continue
		if _fix_insert_after(record):
			changed = True
		kept.append(record)

	if len(kept) != len(records) or changed:
		with open(filepath, "w", encoding="utf-8") as f:
			json.dump(kept, f, indent=2, ensure_ascii=False)
			f.write("\n")

	return removed_names


def _process_property_setter_file(filepath: str, removed_fieldnames: set[str]) -> int:
	if not os.path.exists(filepath):
		return 0
	with open(filepath, encoding="utf-8") as f:
		records = json.load(f)
	if not isinstance(records, list):
		return 0

	updated = 0
	kept = []
	custom_fields = _custom_fields_by_doctype(os.path.join(os.path.dirname(filepath), "custom_field.json"))
	for record in records:
		field_name = record.get("field_name") or ""
		property_name = record.get("property") or ""
		doc_type = record.get("doc_type")

		if property_name == "field_order":
			updated += 1
			continue

		if property_name == "precision":
			updated += 1
			continue

		if field_name.startswith("posa_"):
			updated += 1
			continue

		if (doc_type, field_name, property_name) in IMPORTANT_FIELD_VISIBILITY_SETTERS:
			updated += 1
			continue

		if doc_type in MASTER_LAYOUT_DOCTYPES and (
			not field_name or field_name not in custom_fields.get(doc_type, set())
		):
			updated += 1
			continue

		kept.append(record)

	if updated:
		with open(filepath, "w", encoding="utf-8") as f:
			json.dump(kept, f, indent=2, ensure_ascii=False)
			f.write("\n")

	return updated


def _custom_fields_by_doctype(filepath: str) -> dict[str, set[str]]:
	if not os.path.exists(filepath):
		return {}
	with open(filepath, encoding="utf-8") as f:
		records = json.load(f)
	if not isinstance(records, list):
		return {}
	result: dict[str, set[str]] = {}
	for record in records:
		result.setdefault(record.get("dt"), set()).add(record.get("fieldname"))
	return result


def _collect_fixture_paths(base: str) -> list[tuple[str, str | None]]:
	paths = []
	for root, _dirs, files in os.walk(base):
		if "custom_field.json" in files:
			paths.append((os.path.join(root, "custom_field.json"), os.path.join(root, "property_setter.json")))
		elif "property_setter.json" in files and "custom_field.json" not in files:
			paths.append((None, os.path.join(root, "property_setter.json")))
	return paths


def run():
	app_path = frappe.get_app_path("new_atmta")
	stats = {
		"custom_field_files": 0,
		"fields_removed": 0,
		"property_setter_files": 0,
		"property_setters_cleaned": 0,
	}

	all_removed: set[str] = set()
	for cf_path, ps_path in _collect_fixture_paths(app_path):
		if cf_path and os.path.exists(cf_path):
			removed = _process_custom_field_file(cf_path)
			if removed:
				stats["custom_field_files"] += 1
				stats["fields_removed"] += len(removed)
				all_removed |= removed

	for cf_path, ps_path in _collect_fixture_paths(app_path):
		if ps_path and os.path.exists(ps_path):
			cleaned = _process_property_setter_file(ps_path, all_removed)
			if cleaned:
				stats["property_setter_files"] += 1
				stats["property_setters_cleaned"] += cleaned

	# Unified fixtures folder (no custom_field sibling in same dir for property only)
	ps_unified = os.path.join(app_path, "fixtures", "property_setter.json")
	if os.path.exists(ps_unified):
		cleaned = _process_property_setter_file(ps_unified, all_removed)
		if cleaned:
			stats["property_setters_cleaned"] += cleaned

	print(json.dumps(stats, indent=2))
	return stats
