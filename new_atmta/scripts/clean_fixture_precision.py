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
	{"dt": "Customer", "fieldname": "custom_customer_name_in_arabic", "primary_field": "customer_name_in_arabic"},
	{"dt": "Customer", "fieldname": "custom_customer_name_english", "primary_field": "customer_name"},
]

FIELDNAMES_TO_STRIP_FROM_ORDER = {
	"custom_document_no",
	"document_no",
	"customer_names",
	"custom_customer_name_in_arabic",
	"custom_customer_name_english",
}

CANONICAL_INSERT_AFTER = {
	("Customer", "customer_name_in_arabic"): "customer_name",
}

REMOVED_INSERT_AFTER_TARGETS = {
	"customer_names": "customer_name",
	"custom_customer_name_in_arabic": "customer_name",
	"custom_customer_name_english": "customer_name_in_arabic",
	"custom_document_no": "bill_no",
	"document_no": "bill_no",
}

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
	for record in records:
		field_name = record.get("field_name") or ""
		property_name = record.get("property") or ""

		if property_name == "field_order":
			updated += 1
			continue

		if property_name == "precision":
			updated += 1
			continue

		if field_name.startswith("posa_"):
			updated += 1
			continue

		if (record.get("doc_type"), field_name, property_name) in IMPORTANT_FIELD_VISIBILITY_SETTERS:
			updated += 1
			continue

		kept.append(record)

	if updated:
		with open(filepath, "w", encoding="utf-8") as f:
			json.dump(kept, f, indent=2, ensure_ascii=False)
			f.write("\n")

	return updated


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
