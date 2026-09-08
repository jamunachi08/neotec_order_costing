"""Custom field installation.

Every custom field the app reads or writes is declared here. Nothing else in
the codebase may assume a field exists without it appearing in this module —
`verify_tree.py` enforces that.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

PEG_LINK = {
	"fieldname": "custom_noc_order_cost_peg",
	"label": "Order Cost Peg",
	"fieldtype": "Link",
	"options": "Order Cost Peg",
	"read_only": 1,
	"allow_on_submit": 1,
	"no_copy": 1,
}


# ---------------------------------------------------------------------------
# Reusable field groups
# ---------------------------------------------------------------------------

def _part_no_fields(after):
	"""Manufacturer and supplier part numbers echoed onto transaction rows so
	they print without a lookup. Customer part number is native
	(customer_item_code) and is not duplicated."""
	return [
		{
			"fieldname": "custom_noc_manufacturer_part_no",
			"label": "Manufacturer Part No",
			"fieldtype": "Data",
			"read_only": 1,
			"allow_on_submit": 1,
			"insert_after": after,
		},
		{
			"fieldname": "custom_noc_supplier_part_no",
			"label": "Supplier Part No",
			"fieldtype": "Data",
			"read_only": 1,
			"allow_on_submit": 1,
			"insert_after": "custom_noc_manufacturer_part_no",
		},
	]


def _cost_fields(after):
	"""Cost visibility. Present on every sales row so purchase cost and margin
	are visible at quotation, order, delivery and invoice."""
	return [
		{
			"fieldname": "custom_noc_pegged_cost_rate",
			"label": "Pegged Cost Rate",
			"fieldtype": "Currency",
			"options": "currency",
			"read_only": 1,
			"allow_on_submit": 1,
			"insert_after": after,
		},
		{
			"fieldname": "custom_noc_cost_source_used",
			"label": "Cost Source Used",
			"fieldtype": "Data",
			"read_only": 1,
			"allow_on_submit": 1,
			"insert_after": "custom_noc_pegged_cost_rate",
		},
		{
			"fieldname": "custom_noc_unit_margin",
			"label": "Unit Margin",
			"fieldtype": "Currency",
			"options": "currency",
			"read_only": 1,
			"allow_on_submit": 1,
			"insert_after": "custom_noc_cost_source_used",
		},
		{
			"fieldname": "custom_noc_margin_percent",
			"label": "Margin %",
			"fieldtype": "Percent",
			"read_only": 1,
			"allow_on_submit": 1,
			"insert_after": "custom_noc_unit_margin",
		},
	]


def _addon_fields(after):
	return [
		{
			"fieldname": "custom_noc_cogs_source",
			"label": "COGS Source",
			"fieldtype": "Select",
			"options": "\nPegged Batch Valuation\nPegged PO Rate\nDefault Valuation\nAdd-on Item",
			"read_only": 1,
			"allow_on_submit": 1,
			"insert_after": after,
		},
		{
			"fieldname": "custom_noc_is_addon",
			"label": "Is Add-on Item",
			"fieldtype": "Check",
			"read_only": 1,
			"allow_on_submit": 1,
			"insert_after": "custom_noc_cogs_source",
		},
		{
			"fieldname": "custom_noc_addon_parent_item",
			"label": "Add-on For Item",
			"fieldtype": "Data",
			"read_only": 1,
			"allow_on_submit": 1,
			"insert_after": "custom_noc_is_addon",
		},
		{
			"fieldname": "custom_noc_as_built_config",
			"label": "As-Built Configuration",
			"fieldtype": "Link",
			"options": "As Built Configuration",
			"read_only": 1,
			"allow_on_submit": 1,
			"insert_after": "custom_noc_addon_parent_item",
		},
	]


def _section(fieldname, label, after):
	return {
		"fieldname": fieldname,
		"label": label,
		"fieldtype": "Section Break",
		"insert_after": after,
		"collapsible": 1,
	}


# ---------------------------------------------------------------------------
# Declaration
# ---------------------------------------------------------------------------

def _custom_fields():
	return {
		# ---------------------------------------------------------- selling
		"Quotation Item": (
			[_section("custom_noc_costing_section", "Order Costing", "page_break")]
			+ _part_no_fields("custom_noc_costing_section")
			+ [dict(PEG_LINK, insert_after="custom_noc_supplier_part_no")]
			+ _cost_fields("custom_noc_order_cost_peg")
		),
		"Sales Order Item": (
			[_section("custom_noc_costing_section", "Order Costing", "page_break")]
			+ _part_no_fields("custom_noc_costing_section")
			+ [
				dict(PEG_LINK, insert_after="custom_noc_supplier_part_no"),
				{
					"fieldname": "custom_noc_procurement_status",
					"label": "Procurement Status",
					"fieldtype": "Select",
					"options": "\nNot Required\nPending\nOrdered\nReceived\nPartially Received\nClosed",
					"read_only": 1,
					"allow_on_submit": 1,
					"insert_after": "custom_noc_order_cost_peg",
				},
				{
					"fieldname": "custom_noc_committed_cost_rate",
					"label": "Committed Cost Rate",
					"fieldtype": "Currency",
					"options": "currency",
					"read_only": 1,
					"allow_on_submit": 1,
					"insert_after": "custom_noc_procurement_status",
				},
				{
					"fieldname": "custom_noc_split_group",
					"label": "Procurement Split Group",
					"fieldtype": "Data",
					"read_only": 1,
					"allow_on_submit": 1,
					"insert_after": "custom_noc_committed_cost_rate",
				},
				{
					"fieldname": "custom_noc_substituted_part_no",
					"label": "Substituted Part No",
					"fieldtype": "Link",
					"options": "Item",
					"read_only": 1,
					"allow_on_submit": 1,
					"insert_after": "custom_noc_split_group",
				},
			]
			+ _cost_fields("custom_noc_substituted_part_no")
		),
		"Delivery Note Item": (
			[_section("custom_noc_costing_section", "Order Costing", "page_break")]
			+ _part_no_fields("custom_noc_costing_section")
			+ [dict(PEG_LINK, insert_after="custom_noc_supplier_part_no")]
			+ _cost_fields("custom_noc_order_cost_peg")
			+ _addon_fields("custom_noc_margin_percent")
		),
		"Sales Invoice Item": (
			[_section("custom_noc_costing_section", "Order Costing", "page_break")]
			+ _part_no_fields("custom_noc_costing_section")
			+ [dict(PEG_LINK, insert_after="custom_noc_supplier_part_no")]
			+ _cost_fields("custom_noc_order_cost_peg")
			+ _addon_fields("custom_noc_margin_percent")
		),
		# ---------------------------------------------------------- buying
		"Purchase Order": [
			{
				"fieldname": "custom_noc_split_brand",
				"label": "Split Brand",
				"fieldtype": "Link",
				"options": "Brand",
				"read_only": 1,
				"allow_on_submit": 1,
				"insert_after": "supplier_name",
			},
			{
				"fieldname": "custom_noc_split_from_sales_order",
				"label": "Split From Sales Order",
				"fieldtype": "Link",
				"options": "Sales Order",
				"read_only": 1,
				"allow_on_submit": 1,
				"insert_after": "custom_noc_split_brand",
			},
		],
		"Purchase Order Item": (
			[dict(PEG_LINK, insert_after="sales_order_item")]
			+ _part_no_fields("custom_noc_order_cost_peg")
		),
		"Purchase Receipt Item": (
			[dict(PEG_LINK, insert_after="purchase_order_item")]
			+ _part_no_fields("custom_noc_order_cost_peg")
			+ [
				{
					"fieldname": "custom_noc_batch_template_used",
					"label": "Batch Template Used",
					"fieldtype": "Data",
					"read_only": 1,
					"allow_on_submit": 1,
					"insert_after": "custom_noc_supplier_part_no",
				}
			]
		),
		"Purchase Invoice Item": (
			[dict(PEG_LINK, insert_after="purchase_order_item")]
			+ _part_no_fields("custom_noc_order_cost_peg")
			+ [
				{
					"fieldname": "custom_noc_batch_template_used",
					"label": "Batch Template Used",
					"fieldtype": "Data",
					"read_only": 1,
					"allow_on_submit": 1,
					"insert_after": "custom_noc_supplier_part_no",
				}
			]
		),
		"Material Request Item": [
			{
				"fieldname": "custom_noc_split_group",
				"label": "Procurement Split Group",
				"fieldtype": "Data",
				"read_only": 1,
				"allow_on_submit": 1,
				"insert_after": "sales_order",
			}
		],
		# ---------------------------------------------------------- masters
		"Item": [
			_section("custom_noc_part_section", "Part Number and Specifications", "brand"),
			{
				"fieldname": "custom_noc_spec_template",
				"label": "Specification Template",
				"fieldtype": "Link",
				"options": "Specification Template",
				"insert_after": "custom_noc_part_section",
			},
			{
				"fieldname": "custom_noc_specifications",
				"label": "Specifications",
				"fieldtype": "Table",
				"options": "Item Specification",
				"insert_after": "custom_noc_spec_template",
			},
			_section("custom_noc_equivalence_section", "Equivalent and Superseded Parts",
					 "custom_noc_specifications"),
			{
				"fieldname": "custom_noc_part_equivalence",
				"label": "Part Equivalence",
				"fieldtype": "Table",
				"options": "Part Equivalence",
				"insert_after": "custom_noc_equivalence_section",
			},
			_section("custom_noc_addon_section", "Add-on Behaviour",
					 "custom_noc_part_equivalence"),
			{
				"fieldname": "custom_noc_modifies_attribute",
				"label": "Modifies Attribute",
				"fieldtype": "Link",
				"options": "Specification Attribute",
				"insert_after": "custom_noc_addon_section",
			},
			{
				"fieldname": "custom_noc_modification_mode",
				"label": "Modification Mode",
				"fieldtype": "Select",
				"options": "Replace\nAdd\nAppend\nRemove",
				"default": "Replace",
				"insert_after": "custom_noc_modifies_attribute",
				"depends_on": "custom_noc_modifies_attribute",
			},
			{
				"fieldname": "custom_noc_modification_value",
				"label": "Modification Value",
				"fieldtype": "Data",
				"insert_after": "custom_noc_modification_mode",
				"depends_on": "custom_noc_modifies_attribute",
				"description": "For a 16GB module on an aggregatable RAM attribute, enter 16.",
			},
		],
		"Batch": [
			_section("custom_noc_section", "Order Costing", "description"),
			dict(PEG_LINK, insert_after="custom_noc_section"),
			{
				"fieldname": "custom_noc_source_sales_order",
				"label": "Source Sales Order",
				"fieldtype": "Link",
				"options": "Sales Order",
				"read_only": 1,
				"insert_after": "custom_noc_order_cost_peg",
			},
			{
				"fieldname": "custom_noc_source_purchase_order",
				"label": "Source Purchase Order",
				"fieldtype": "Link",
				"options": "Purchase Order",
				"read_only": 1,
				"insert_after": "custom_noc_source_sales_order",
			},
			{
				"fieldname": "custom_noc_generated",
				"label": "Generated by Order Costing",
				"fieldtype": "Check",
				"read_only": 1,
				"insert_after": "custom_noc_source_purchase_order",
			},
		],
	}


# ---------------------------------------------------------------------------
# Install and migrate
# ---------------------------------------------------------------------------

def after_install():
	_install()


def after_migrate():
	_install()


def _install():
	create_custom_fields(_custom_fields(), ignore_validate=True)
	_ensure_settings()
	create_visibility_targets()
	frappe.db.commit()
	verify_schema(log_only=True)


def create_visibility_targets():
	"""Creates the custom fields named in the Cost Visibility field mapper, so
	picking a field in settings is all the implementor has to do."""
	if not frappe.db.exists("DocType", "Cost Visibility Field"):
		return
	rows = frappe.get_all(
		"Cost Visibility Field",
		filters={"parenttype": "Order Costing Settings"},
		fields=["target_doctype", "target_fieldname", "target_fieldtype",
				"target_options", "enabled"],
	)
	pending = {}
	for row in rows:
		if not row.enabled or not (row.target_doctype and row.target_fieldname):
			continue
		if frappe.db.exists("Custom Field",
							{"dt": row.target_doctype, "fieldname": row.target_fieldname}):
			continue
		pending.setdefault(row.target_doctype, []).append({
			"fieldname": row.target_fieldname,
			"label": frappe.unscrub(row.target_fieldname.replace("custom_noc_", "")),
			"fieldtype": row.target_fieldtype or "Currency",
			"options": row.target_options,
			"read_only": 1,
			"allow_on_submit": 1,
		})
	if pending:
		create_custom_fields(pending, ignore_validate=True)


def _ensure_settings():
	"""Create the Single with safe defaults. Everything off until an
	implementor explicitly switches it on."""
	settings = frappe.get_single("Order Costing Settings")
	if not settings.batch_naming_components:
		for row in (
			{"component": "Static Text", "static_value": "BT", "idx": 1},
			{"component": "Item Code", "idx": 2},
			{"component": "Sales Order (last 4)", "idx": 3},
			{"component": "Serial Counter", "counter_length": 3, "idx": 4},
		):
			settings.append("batch_naming_components", row)
		settings.batch_separator = "-"
	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

@frappe.whitelist()
def verify_schema(log_only=False):
	"""Confirms every declared field is really in the database. A declaration
	that never reached the table is exactly the failure that produces an
	'Unknown column' error at runtime."""
	if not log_only:
		frappe.only_for(["System Manager", "Stock Manager"])

	missing = {}
	for doctype, fields in _custom_fields().items():
		if not frappe.db.exists("DocType", doctype):
			continue
		try:
			columns = set(frappe.db.get_table_columns(doctype))
		except Exception:
			continue
		meta_fields = {f.fieldname for f in frappe.get_meta(doctype).fields}
		for field in fields:
			fieldname = field["fieldname"]
			if field["fieldtype"] in ("Section Break", "Column Break", "Table"):
				if fieldname not in meta_fields:
					missing.setdefault(doctype, []).append(fieldname)
				continue
			if fieldname not in columns:
				missing.setdefault(doctype, []).append(fieldname)

	if missing and log_only:
		frappe.log_error(
			frappe.as_json(missing),
			"Neotec Order Costing: custom fields missing after migrate",
		)
	return {"ok": not missing, "missing": missing}


@frappe.whitelist()
def repair_schema():
	"""Force-creates anything the verifier reports as missing."""
	frappe.only_for(["System Manager", "Stock Manager"])
	before = verify_schema(log_only=True)
	create_custom_fields(_custom_fields(), ignore_validate=True)
	create_visibility_targets()
	frappe.db.commit()
	frappe.clear_cache()
	after = verify_schema(log_only=True)
	return {"before": before["missing"], "after": after["missing"],
			"fixed": not after["missing"]}
