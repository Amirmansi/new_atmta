app_name = "new_atmta"
app_title = "ATMTA Multi-Site"
app_publisher = "ATMTA"
app_description = "ATMTA Multi-Site Customizations - All sites, all custom fields, scripts, and print formats"
app_email = "amirahmd12300@gmail.com"
app_license = "mit"

# After app install: auto-import this site's fixtures
after_install = "new_atmta.install.after_install"
after_migrate = "new_atmta.install.after_migrate"

# Desk UX — faster route transitions, smart forms, workspace prefetch.
app_include_js = [
	"/assets/new_atmta/js/atmta_desk.js",
	"/assets/new_atmta/js/atmta_forms.js",
]
app_include_css = "/assets/new_atmta/css/atmta_desk.css"

# Faster desk: cached workspace sidebar (overrides nxt_theme heavy query).
override_whitelisted_methods = {
	"frappe.desk.desktop.get_workspace_sidebar_items": (
		"new_atmta.desk_cache.get_workspace_sidebar_items"
	),
}

boot_session = "new_atmta.desk_cache.boot_session"

before_request = ["new_atmta.desk_cache.ensure_sidebar_patch"]

doc_events = {
	"Workspace": {
		"on_update": "new_atmta.desk_cache.on_workspace_change",
		"on_trash": "new_atmta.desk_cache.on_workspace_change",
	},
}

# Unified customizations shipped to ALL sites (core master + ledger DocTypes).
# These are imported from new_atmta/fixtures/*.json on every `bench migrate`.
_LEDGER_DOCTYPES = [
    "Item",
    "Customer",
    "Supplier",
    "Sales Invoice",
    "Purchase Invoice",
    "Delivery Note",
    "Purchase Receipt",
    "Sales Order",
    "Purchase Order",
]

fixtures = [
    {
        "doctype": "Custom Field",
        "filters": {"dt": ["in", _LEDGER_DOCTYPES]},
    },
    {
        "doctype": "Property Setter",
        "filters": {"doc_type": ["in", _LEDGER_DOCTYPES + ["Expense Entry"]]},
    },
]
