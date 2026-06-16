"""
Export all customizations from a Frappe site into new_atmta/site_fixtures/{site_key}/

Usage:
    bench --site <site> execute new_atmta.scripts.export_site.run
"""

import json
import os
import frappe


SITE_KEY_MAP = {
    "andal.atmta-erp.com": "andal",
    "atmta.atmta-erp.com": "atmta",
    "atmta-finance.atmta-erp.com": "atmta_finance",
    "ayash.atmta-erp.com": "ayash",
    "btack.atmta-erp.com": "btack",
    "gazzal.atmta-erp.com": "gazzal",
    "hila.atmta-erp.com": "hila",
    "striangle.atmta-erp.com": "striangle",
    "tagmira.atmta-erp.com": "tagmira",
    "tagmir.atmta-erp.com": "tagmir",
    "training.atmta-erp.com": "training",
}

FIXTURES_CONFIG = [
    {
        "doctype": "Custom Field",
        "fields": ["name", "dt", "module", "label", "fieldname", "fieldtype",
                   "options", "insert_after", "hidden", "reqd", "bold",
                   "in_list_view", "in_filter", "no_copy", "read_only",
                   "allow_on_submit", "description", "default", "depends_on",
                   "mandatory_depends_on", "read_only_depends_on", "translatable",
                   "print_hide", "report_hide", "search_index", "unique",
                   "ignore_user_permissions", "in_global_search", "precision",
                   "columns", "width", "fetch_from", "fetch_if_empty",
                   "permlevel", "idx", "collapsible", "collapsible_depends_on"],
        "order_by": "dt, idx",
    },
    {
        "doctype": "Property Setter",
        "fields": ["name", "doc_type", "doctype_or_field", "field_name",
                   "property", "property_type", "value", "module", "is_system_generated"],
        "order_by": "doc_type, field_name, property",
    },
    {
        "doctype": "Client Script",
        "fields": ["name", "dt", "script_type", "script", "enabled",
                   "module", "view", "class_name"],
        "order_by": "dt, name",
    },
    {
        "doctype": "Server Script",
        "fields": ["name", "script_type", "reference_doctype", "doctype_event",
                   "script", "enabled", "allow_guest", "module",
                   "api_method", "event_frequency", "cron_format"],
        "order_by": "name",
    },
    {
        "doctype": "Print Format",
        "fields": ["name", "doc_type", "html", "css", "format_data",
                   "module", "standard", "custom_format", "print_format_type",
                   "font", "font_size", "margin_top", "margin_bottom",
                   "margin_left", "margin_right", "line_breaks", "align_labels_left",
                   "show_section_headings", "page_break_based_on",
                   "landscape", "raw_printing", "raw_commands"],
        "filters": {"standard": "No"},
        "order_by": "doc_type, name",
    },
    {
        "doctype": "Custom DocPerm",
        "fields": ["name", "parent", "parenttype", "parentfield", "idx",
                   "role", "read", "write", "create", "delete", "submit",
                   "cancel", "amend", "report", "export", "import",
                   "set_user_permissions", "share", "print", "email",
                   "permlevel", "match"],
        "order_by": "parent, role",
    },
    {
        "doctype": "Report",
        "fields": ["name", "report_name", "ref_doctype", "report_type",
                   "is_standard", "module", "query", "script", "json",
                   "add_total_row", "disabled", "letter_head", "filters_json",
                   "columns"],
        "filters": {"is_standard": "No"},
        "order_by": "ref_doctype, report_name",
    },
]


def get_site_key():
    site = frappe.local.site
    return SITE_KEY_MAP.get(site, site.replace(".", "_").replace("-", "_").split("_atmta")[0])


def get_fixtures_dir():
    app_path = frappe.get_app_path("new_atmta")
    site_key = get_site_key()
    fixtures_dir = os.path.join(app_path, "site_fixtures", site_key)
    os.makedirs(fixtures_dir, exist_ok=True)
    return fixtures_dir


def export_doctype(config, fixtures_dir):
    doctype = config["doctype"]
    fields = config.get("fields", ["*"])
    filters = config.get("filters", {})
    order_by = config.get("order_by", "name")

    filename = doctype.lower().replace(" ", "_") + ".json"
    filepath = os.path.join(fixtures_dir, filename)

    try:
        records = frappe.get_all(
            doctype,
            fields=fields,
            filters=filters,
            order_by=order_by,
            limit_page_length=0,
        )

        # Convert datetime objects to strings
        clean_records = []
        for r in records:
            clean = {}
            for k, v in r.items():
                if hasattr(v, "isoformat"):
                    clean[k] = v.isoformat()
                else:
                    clean[k] = v
            clean["doctype"] = doctype
            clean_records.append(clean)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(clean_records, f, ensure_ascii=False, indent=2, default=str)

        print(f"  ✓ {doctype}: {len(clean_records)} records → {filename}")
        return len(clean_records)

    except Exception as e:
        print(f"  ✗ {doctype}: ERROR - {e}")
        return 0


def export_custom_doctypes(fixtures_dir):
    """Export full Custom DocType definitions (not standard ones)."""
    custom_doctypes = frappe.get_all(
        "DocType",
        filters={"custom": 1},
        fields=["name"],
        limit_page_length=0,
    )

    if not custom_doctypes:
        print("  - Custom DocTypes: none found")
        return 0

    all_docs = []
    for dt in custom_doctypes:
        try:
            doc = frappe.get_doc("DocType", dt.name)
            all_docs.append(doc.as_dict())
        except Exception as e:
            print(f"  ✗ DocType {dt.name}: {e}")

    filepath = os.path.join(fixtures_dir, "custom_doctype.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(all_docs, f, ensure_ascii=False, indent=2, default=str)

    print(f"  ✓ Custom DocTypes: {len(all_docs)} records → custom_doctype.json")
    return len(all_docs)


def run():
    site = frappe.local.site
    site_key = get_site_key()
    fixtures_dir = get_fixtures_dir()

    print(f"\n{'='*60}")
    print(f"Exporting site: {site}")
    print(f"Site key:       {site_key}")
    print(f"Output dir:     {fixtures_dir}")
    print(f"{'='*60}")

    totals = {}
    for config in FIXTURES_CONFIG:
        count = export_doctype(config, fixtures_dir)
        totals[config["doctype"]] = count

    count = export_custom_doctypes(fixtures_dir)
    totals["Custom DocType"] = count

    # Write manifest
    manifest = {
        "site": site,
        "site_key": site_key,
        "exported_at": frappe.utils.now(),
        "totals": totals,
    }
    manifest_path = os.path.join(fixtures_dir, "_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print("Summary:")
    for dt, count in totals.items():
        print(f"  {dt:<25} {count:>5} records")
    print(f"{'='*60}")
    print(f"Manifest: {manifest_path}")
    print("Export complete!\n")
