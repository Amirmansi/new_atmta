"""
Import customizations from site_fixtures/{site_key}/ into the current site.

Usage (after app is installed on site):
    bench --site <site> execute new_atmta.scripts.import_site.run
    bench --site <site> execute new_atmta.scripts.import_site.run --kwargs '{"force": true}'

Standalone (no app install needed):
    env/bin/python import_new_atmta.py <site>
    env/bin/python import_new_atmta.py <site> --force
"""

import json
import os
import frappe

APP_FIXTURES_BASE = "/home/frappe/frappe-bench/apps/new_atmta/new_atmta/site_fixtures"

SITE_KEY_MAP = {
    "andal.atmta-erp.com":          "andal",
    "atmta.atmta-erp.com":          "atmta",
    "atmta-finance.atmta-erp.com":  "atmta_finance",
    "ayash.atmta-erp.com":          "ayash",
    "btack.atmta-erp.com":          "btack",
    "gazzal.atmta-erp.com":         "gazzal",
    "hila.atmta-erp.com":           "hila",
    "striangle.atmta-erp.com":      "striangle",
    "tagmira.atmta-erp.com":        "tagmira",
    "tagmir.atmta-erp.com":         "tagmir",
    "training.atmta-erp.com":       "training",
}

IMPORT_ORDER = [
    ("custom_doctype.json",   None),
    ("custom_field.json",     "Custom Field"),
    ("property_setter.json",  "Property Setter"),
    ("print_format.json",     "Print Format"),
    ("client_script.json",    "Client Script"),
    ("server_script.json",    "Server Script"),
    ("custom_docperm.json",   "Custom DocPerm"),
    ("report.json",           "Report"),
]


def get_site_key():
    site = frappe.local.site
    return SITE_KEY_MAP.get(site, site.replace(".", "_").replace("-", "_"))


def get_fixtures_dir():
    site_key = get_site_key()
    return os.path.join(APP_FIXTURES_BASE, site_key)


def _import_custom_doctypes(filepath, force=False):
    with open(filepath, "r", encoding="utf-8") as f:
        docs = json.load(f)
    if not docs:
        print("  - Custom DocType: none")
        return
    created = updated = skipped = errors = 0
    for doc_data in docs:
        name = doc_data.get("name")
        try:
            if frappe.db.exists("DocType", name):
                if force:
                    doc = frappe.get_doc("DocType", name)
                    doc.update(doc_data)
                    doc.save(ignore_permissions=True)
                    updated += 1
                else:
                    skipped += 1
            else:
                doc = frappe.get_doc(doc_data)
                doc.insert(ignore_permissions=True)
                created += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"    ✗ DocType {name}: {e}")
    frappe.db.commit()
    print(f"  ✓ Custom DocType:  created={created}, updated={updated}, skipped={skipped}, errors={errors}")


def _import_records(filepath, doctype, force=False):
    with open(filepath, "r", encoding="utf-8") as f:
        records = json.load(f)
    if not records:
        print(f"  - {doctype}: empty")
        return
    created = updated = skipped = errors = 0
    for record in records:
        record.pop("doctype", None)
        name = record.get("name")
        if not name:
            continue
        try:
            if frappe.db.exists(doctype, name):
                if force:
                    doc = frappe.get_doc(doctype, name)
                    doc.update(record)
                    doc.save(ignore_permissions=True)
                    updated += 1
                else:
                    skipped += 1
            else:
                record["doctype"] = doctype
                doc = frappe.get_doc(record)
                doc.insert(ignore_permissions=True)
                created += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"    ✗ {name}: {e}")
    frappe.db.commit()
    print(f"  ✓ {doctype:<25} created={created}, updated={updated}, skipped={skipped}, errors={errors}")


def run(force=False):
    site = frappe.local.site
    site_key = get_site_key()
    fixtures_dir = get_fixtures_dir()

    print(f"\n{'='*60}")
    print(f"Importing → {site}  (key: {site_key})")
    print(f"Source:     {fixtures_dir}")
    print(f"Force:      {bool(force)}")
    print(f"{'='*60}")

    if not os.path.exists(fixtures_dir):
        print(f"ERROR: No fixtures for site '{site_key}'")
        print(f"  Run export first: env/bin/python export_new_atmta.py {site}")
        return

    manifest_path = os.path.join(fixtures_dir, "_manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            m = json.load(f)
        print(f"Fixtures exported: {m.get('exported_at','?')}")
        print(f"Total records:     {m.get('grand_total','?')}")
        print(f"{'─'*60}")

    for filename, doctype in IMPORT_ORDER:
        filepath = os.path.join(fixtures_dir, filename)
        if not os.path.exists(filepath):
            print(f"  - {filename}: not found")
            continue
        if doctype is None:
            _import_custom_doctypes(filepath, force=force)
        else:
            _import_records(filepath, doctype, force=force)

    print(f"\n{'='*60}")
    print("Import complete! Run bench migrate to apply schema changes.")
    print(f"{'='*60}\n")
