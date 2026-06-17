"""
Install / migrate hooks for new_atmta.
These run automatically on: bench install-app new_atmta
                            bench migrate
"""

import json
import os
from copy import deepcopy

import frappe


def after_install():
    """Called once when app is installed on a site."""
    ensure_common_doctypes()
    _clean_fixture_files(context="install")
    _run_import(context="install")
    _run_maintenance(context="install")


def after_migrate():
    """Called on every bench migrate — keeps fixtures in sync."""
    ensure_common_doctypes()
    _clean_fixture_files(context="migrate")
    _run_import(context="migrate")
    _run_maintenance(context="migrate")


def ensure_common_doctypes():
    """Create shared custom DocTypes (e.g. 'Customer Types') on every site.

    These back Link custom fields shipped via fixtures (custom_field.json).
    They are created programmatically — not via the fixtures importer — because
    importing a new custom DocType through the fixtures path validates field
    columns before the table exists and fails. ``frappe.get_doc(...).insert()``
    treats the record as local and creates the table correctly.
    """
    base = frappe.get_app_path("new_atmta", "common_doctypes")
    if not os.path.exists(base):
        return
    for fname in sorted(os.listdir(base)):
        if not fname.endswith(".json"):
            continue
        try:
            records = json.load(open(os.path.join(base, fname), encoding="utf-8"))
        except Exception as e:
            frappe.logger().error(f"new_atmta: cannot read {fname} — {e}")
            continue
        for d in records:
            name = d.get("name")
            if not name or frappe.db.exists("DocType", name):
                continue
            try:
                doc_data = _strip_child_row_names(d)
                frappe.get_doc(doc_data).insert(ignore_permissions=True)
                frappe.db.commit()
                frappe.logger().info(f"new_atmta: created shared DocType '{name}'")
            except Exception as e:
                frappe.logger().error(f"new_atmta: failed to create DocType '{name}' — {e}")


def _strip_child_row_names(doc_data):
    """Make fixture child rows local so new custom DocTypes can create tables."""
    cleaned = deepcopy(doc_data)
    for child_table in ("fields", "permissions", "actions", "links", "states"):
        for row in cleaned.get(child_table) or []:
            row.pop("name", None)
    return cleaned


def _run_import(context="migrate"):
    try:
        from new_atmta.scripts.import_site import run as import_run, get_site_key, get_fixtures_dir

        site_key = get_site_key()
        fixtures_dir = get_fixtures_dir()

        if not os.path.exists(fixtures_dir):
            frappe.logger().info(
                f"new_atmta [{context}]: No fixtures found for site '{site_key}' — skipping."
            )
            return

        frappe.logger().info(
            f"new_atmta [{context}]: Importing fixtures for site '{site_key}' from {fixtures_dir}"
        )
        import_run(force=False)

    except Exception as e:
        frappe.logger().error(f"new_atmta [{context}]: Failed to import fixtures — {e}")


def _run_maintenance(context="migrate"):
    try:
        from new_atmta.site_maintenance import run_all

        frappe.logger().info(f"new_atmta [{context}]: Running site maintenance")
        run_all()
    except Exception as e:
        frappe.logger().error(f"new_atmta [{context}]: Site maintenance failed — {e}")


def _clean_fixture_files(context="migrate"):
	"""One-time cleanup of orphan/redundant fields in app fixture JSON (idempotent)."""
	try:
		from new_atmta.scripts.clean_orphan_fixtures import run as clean_orphans
		from new_atmta.scripts.clean_fixture_precision import run as clean_precision

		frappe.logger().info(f"new_atmta [{context}]: Cleaning orphan fixture fields")
		clean_orphans()
		frappe.logger().info(f"new_atmta [{context}]: Cleaning precision/redundant fixture fields")
		clean_precision()
	except Exception as e:
		frappe.logger().error(f"new_atmta [{context}]: Fixture cleanup failed — {e}")
