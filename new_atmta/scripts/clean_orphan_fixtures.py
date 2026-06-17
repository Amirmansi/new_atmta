"""
Remove orphan custom fields from new_atmta fixture JSON files.

Strips POS Awesome leftovers (posa_*), Link/Table fields pointing to missing
DocTypes, and cleans property setter field_order lists.

Usage:
    bench --site <site> execute new_atmta.scripts.clean_orphan_fixtures.run
"""

from __future__ import annotations

import json
import os
import re

import frappe

LINK_FIELD_TYPES = {"Link", "Table", "Table MultiSelect", "Dynamic Link"}

# DocTypes created by new_atmta — never strip fields linking here.
KEEP_LINK_DOCTYPES = {"Customer Types"}

ORPHAN_DOCTYPES = {
	"Delivery Charges",
	"POS Offer",
	"POS Coupon Detail",
	"POS Offer Detail",
	"Branch Allowed Account",
	"Branch Default Account Payable",
	"Branch Default Account Receivable",
	"Branch Default Bank Account",
	"Branch Default Cash Account",
	"Branch Default Cost Center",
	"Branch Default Expense Account",
	"Branch Default Income Account",
	"Branch Default Warehouse",
	"Branch User",
}


def _should_remove_field(record: dict, existing_doctypes: set[str]) -> bool:
	fieldname = record.get("fieldname") or ""
	if fieldname.startswith("posa_"):
		return True

	fieldtype = record.get("fieldtype")
	options = record.get("options")
	if fieldtype in LINK_FIELD_TYPES and options:
		if options in KEEP_LINK_DOCTYPES:
			return False
		if options in ORPHAN_DOCTYPES:
			return True
		if options not in existing_doctypes:
			return True
	return False


def _clean_field_order_value(value: str, removed_fieldnames: set[str]) -> str | None:
	if not value or not removed_fieldnames:
		return value
	try:
		fields = json.loads(value)
	except json.JSONDecodeError:
		return value
	if not isinstance(fields, list):
		return value
	new_fields = [f for f in fields if f not in removed_fieldnames]
	if new_fields == fields:
		return value
	return json.dumps(new_fields)


def _process_custom_field_file(filepath: str, existing_doctypes: set[str]) -> set[str]:
	with open(filepath, encoding="utf-8") as f:
		records = json.load(f)
	if not isinstance(records, list):
		return set()

	removed_names: set[str] = set()
	kept = []
	for record in records:
		if _should_remove_field(record, existing_doctypes):
			if record.get("fieldname"):
				removed_names.add(record["fieldname"])
			if record.get("name"):
				removed_names.add(record["name"].split("-", 1)[-1] if "-" in record.get("name", "") else "")
		else:
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
		if field_name.startswith("posa_"):
			updated += 1
			continue
		if record.get("property") == "field_order":
			new_value = _clean_field_order_value(record.get("value"), removed_fieldnames)
			if new_value != record.get("value"):
				record["value"] = new_value
				updated += 1
		kept.append(record)

	if len(kept) != len(records) or updated:
		with open(filepath, "w", encoding="utf-8") as f:
			json.dump(kept, f, indent=2, ensure_ascii=False)
			f.write("\n")

	return updated


def _collect_fixture_paths(base: str) -> list[tuple[str, str | None]]:
	paths = []
	for root, _dirs, files in os.walk(base):
		for fname in files:
			if fname == "custom_field.json":
				paths.append((os.path.join(root, fname), os.path.join(root, "property_setter.json")))
	return paths


def run():
	existing_doctypes = set(frappe.get_all("DocType", pluck="name"))
	app_path = frappe.get_app_path("new_atmta")

	stats = {"files_cleaned": 0, "fields_removed": 0, "property_setters_updated": 0}

	for cf_path, ps_path in _collect_fixture_paths(app_path):
		removed = _process_custom_field_file(cf_path, existing_doctypes)
		if removed:
			stats["files_cleaned"] += 1
			stats["fields_removed"] += len(removed)
			if ps_path and os.path.exists(ps_path):
				stats["property_setters_updated"] += _process_property_setter_file(ps_path, removed)

	print(json.dumps(stats, indent=2))
	return stats
