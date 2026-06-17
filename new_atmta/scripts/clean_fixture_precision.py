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
]

FIELDNAMES_TO_STRIP_FROM_ORDER = {
	"custom_document_no",
	"document_no",
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


def _process_custom_field_file(filepath: str) -> set[str]:
	with open(filepath, encoding="utf-8") as f:
		records = json.load(f)
	if not isinstance(records, list):
		return set()

	removed_names: set[str] = set()
	kept = []
	for record in records:
		fieldname = record.get("fieldname") or ""
		dt = record.get("dt") or ""
		if any(r["dt"] == dt and r["fieldname"] == fieldname for r in REDUNDANT_CUSTOM_FIELDS):
			removed_names.add(fieldname)
			continue
		kept.append(record)

	if len(kept) != len(records):
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

		if property_name == "precision":
			updated += 1
			continue

		if field_name.startswith("posa_"):
			updated += 1
			continue

		if property_name == "field_order":
			new_value = _clean_field_order_value(record.get("value"), removed_fieldnames)
			if new_value != record.get("value"):
				record["value"] = new_value
				updated += 1

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
