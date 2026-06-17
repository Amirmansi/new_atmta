"""
Desk form enhancements for ATMTA ERP (bench V15).

- Auto-select first naming series on new documents
- Smart float/currency display (2 decimals default, up to 6 on input)
"""

(function () {
	"use strict";

	const NAMING_SERIES_DOCTYPES = [
		"Expense Entry",
		"Purchase Order",
		"Purchase Invoice",
		"Quotation",
		"Sales Order",
		"Sales Invoice",
	];

	const PRECISION_DOCTYPES = [
		"Quotation",
		"Sales Order",
		"Sales Invoice",
		"Purchase Order",
		"Purchase Invoice",
		"Delivery Note",
		"Purchase Receipt",
		"Expense Entry",
	];

	const CHILD_TABLES = [
		"items",
		"expense_entry_account",
	];

	const CALC_FIELD_TYPES = new Set(["Float", "Currency", "Percent"]);
	const MAX_PRECISION = 6;
	const DISPLAY_PRECISION = 2;

	function get_first_naming_series(frm) {
		const field = frm.fields_dict.naming_series;
		if (!field || !field.df.options) return null;
		const first = field.df.options
			.split("\n")
			.map((v) => v.trim())
			.find(Boolean);
		return first || null;
	}

	function set_default_naming_series(frm) {
		if (!frm.is_new() || frm.doc.naming_series) return;
		const first = get_first_naming_series(frm);
		if (first) frm.set_value("naming_series", first);
	}

	function count_decimals(value) {
		if (value === null || value === undefined || value === "") return 0;
		const parts = String(value).split(".");
		return parts.length > 1 ? parts[1].replace(/0+$/, "").length : 0;
	}

	function effective_precision(value) {
		const decimals = count_decimals(value);
		if (!decimals) return DISPLAY_PRECISION;
		return Math.min(Math.max(decimals, DISPLAY_PRECISION), MAX_PRECISION);
	}

	function apply_smart_precision(frm) {
		Object.keys(frm.fields_dict).forEach((fieldname) => {
			const field = frm.fields_dict[fieldname];
			if (!field || !field.df) return;
			if (!CALC_FIELD_TYPES.has(field.df.fieldtype)) return;
			if (field.df.fieldtype === "Currency" && field.df.options && !field.df.precision) {
				field.df.precision = MAX_PRECISION;
			} else if (field.df.fieldtype === "Float" && !field.df.precision) {
				field.df.precision = MAX_PRECISION;
			} else if (!field.df.precision || field.df.precision < MAX_PRECISION) {
				field.df.precision = MAX_PRECISION;
			}
		});

		CHILD_TABLES.forEach((table_field) => {
			const grid = frm.fields_dict[table_field];
			if (!grid || !grid.grid) return;
			grid.grid.update_docfield_property = function (fieldname, property, value) {
				frappe.ui.form.Grid.prototype.update_docfield_property.call(
					this,
					fieldname,
					property,
					value
				);
				if (property === "precision" && value < MAX_PRECISION) {
					frappe.ui.form.Grid.prototype.update_docfield_property.call(
						this,
						fieldname,
						"precision",
						MAX_PRECISION
					);
				}
			};
			Object.values(grid.grid.docfields || {}).forEach((df) => {
				if (!df || !CALC_FIELD_TYPES.has(df.fieldtype)) return;
				df.precision = MAX_PRECISION;
			});
		});
	}

	function bind_child_precision_events(frm) {
		CHILD_TABLES.forEach((table_field) => {
			if (!frm.fields_dict[table_field]) return;
			const child_doctype = frm.fields_dict[table_field].df.options;
			if (!child_doctype || frappe.ui.form._atmta_precision_bound?.[child_doctype]) return;
			frappe.ui.form._atmta_precision_bound = frappe.ui.form._atmta_precision_bound || {};
			frappe.ui.form._atmta_precision_bound[child_doctype] = true;

			frappe.ui.form.on(child_doctype, {
				qty(frm, cdt, cdn) {
					atmta_refresh_child_display(frm, cdt, cdn, "qty");
				},
				rate(frm, cdt, cdn) {
					atmta_refresh_child_display(frm, cdt, cdn, "rate");
				},
				amount(frm, cdt, cdn) {
					atmta_refresh_child_display(frm, cdt, cdn, "amount");
				},
			});
		});
	}

	function atmta_refresh_child_display(frm, cdt, cdn, fieldname) {
		const row = locals[cdt][cdn];
		if (row[fieldname] === undefined || row[fieldname] === null || row[fieldname] === "") return;
		const df = frappe.meta.get_docfield(cdt, fieldname, cdn);
		if (!df || !CALC_FIELD_TYPES.has(df.fieldtype)) return;
		df.precision = effective_precision(row[fieldname]);
	}

	function register_doctype_handlers() {
		const form_hooks = {
			onload(frm) {
				set_default_naming_series(frm);
				if (PRECISION_DOCTYPES.includes(frm.doctype)) {
					apply_smart_precision(frm);
					bind_child_precision_events(frm);
				}
			},
			refresh(frm) {
				set_default_naming_series(frm);
			},
		};

		NAMING_SERIES_DOCTYPES.forEach((doctype) => {
			frappe.ui.form.on(doctype, form_hooks);
		});

		// Purchase / sales child tables on other parent doctypes
		["Delivery Note", "Purchase Receipt"].forEach((doctype) => {
			frappe.ui.form.on(doctype, {
				onload(frm) {
					apply_smart_precision(frm);
					bind_child_precision_events(frm);
				},
			});
		});
	}

	$(document).on("app_ready", register_doctype_handlers);
})();
