"""
Install / migrate hooks for new_atmta.
These run automatically on: bench install-app new_atmta
                            bench migrate
"""

import os
import frappe


def after_install():
    """Called once when app is installed on a site."""
    _run_import(context="install")


def after_migrate():
    """Called on every bench migrate — keeps fixtures in sync."""
    _run_import(context="migrate")


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
