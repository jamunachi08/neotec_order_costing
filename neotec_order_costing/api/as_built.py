"""As-built configuration.

The quotation promised a part number's factory specification. The invoice may
deliver something different, because add-on lines on the same document upgrade
it. This module computes what was actually delivered so the customer receives
an accurate specification.
"""

import frappe
from frappe.utils import cstr, flt

from neotec_order_costing.api.specs import (
	apply_modification,
	get_part_numbers,
	get_specifications,
	render_spec_block,
)
from neotec_order_costing.neotec_order_costing.doctype.order_costing_settings.order_costing_settings import (
	get_settings,
)


def _so_item_of(item):
	return item.get("so_detail") or item.get("sales_order_item")


def _addon_rows(doc):
	"""Add-on lines carrying a modification instruction."""
	out = []
	for item in doc.get("items", []):
		if not item.get("custom_noc_is_addon"):
			continue
		attribute = frappe.get_cached_value("Item", item.item_code, "custom_noc_modifies_attribute")
		if not attribute:
			continue
		mode = frappe.get_cached_value("Item", item.item_code, "custom_noc_modification_mode") or "Replace"
		value = frappe.get_cached_value("Item", item.item_code, "custom_noc_modification_value")
		out.append({
			"item": item,
			"attribute": attribute,
			"mode": mode,
			"value": value,
			"parent_item": item.get("custom_noc_addon_parent_item"),
		})
	return out


def _base_rows(doc):
	"""Lines that represent a delivered part number rather than an add-on."""
	return [
		item for item in doc.get("items", [])
		if not item.get("custom_noc_is_addon")
		and frappe.get_cached_value("Item", item.item_code, "is_stock_item")
	]


# ---------------------------------------------------------------------------
# Hook: on_submit for Delivery Note and Sales Invoice with update stock
# ---------------------------------------------------------------------------

def build_configurations(doc, method=None):
	settings = get_settings()
	if not settings.get("enable_as_built_configuration"):
		return
	if doc.doctype == "Sales Invoice" and not doc.get("update_stock"):
		return

	addons = _addon_rows(doc)
	created = []

	for item in _base_rows(doc):
		applicable = [
			a for a in addons
			if not a["parent_item"] or a["parent_item"] == item.item_code
		]
		config = _build_one(doc, item, applicable)
		if config:
			created.append(config.name)
			item.db_set("custom_noc_as_built_config", config.name, update_modified=False)

	if created:
		frappe.msgprint(
			"{0} as-built configuration(s) generated.".format(len(created)),
			indicator="blue", alert=True,
		)


def _build_one(doc, item, addons):
	base_specs = get_specifications(item.item_code)
	if not base_specs and not addons:
		return None

	parts = get_part_numbers(item.item_code, customer=doc.get("customer"))

	config = frappe.new_doc("As Built Configuration")
	config.base_item = item.item_code
	config.brand = frappe.get_cached_value("Item", item.item_code, "brand")
	config.manufacturer_part_no = parts.get("manufacturer_part_no")
	config.delivery_document_type = doc.doctype
	config.delivery_document = doc.name
	config.delivery_detail = item.name
	config.customer = doc.get("customer")
	config.posting_date = doc.get("posting_date")
	config.qty = flt(item.stock_qty or item.qty)
	config.batch_no = item.get("batch_no")
	config.serial_no = item.get("serial_no")
	config.order_cost_peg = item.get("custom_noc_order_cost_peg")

	index = {}
	for row in base_specs:
		child = config.append("specifications", {
			"attribute": row["attribute"],
			"label_en": row["label_en"],
			"label_ar": row["label_ar"],
			"value_en": row["value_en"],
			"value_ar": row["value_ar"],
			"base_value": row["value_en"],
			"uom": row["uom"],
			"display_order": row["display_order"],
			"show_to_customer": row["show_to_customer"],
			"is_modified": 0,
		})
		index[row["attribute"]] = child

	for addon in addons:
		attribute = addon["attribute"]
		attr_doc = frappe.get_cached_doc("Specification Attribute", attribute)
		target = index.get(attribute)

		if not target:
			target = config.append("specifications", {
				"attribute": attribute,
				"label_en": attr_doc.label_en,
				"label_ar": attr_doc.label_ar,
				"value_en": "",
				"base_value": "",
				"uom": attr_doc.uom,
				"display_order": attr_doc.display_order or 999,
				"show_to_customer": attr_doc.show_to_customer,
				"is_modified": 0,
			})
			index[attribute] = target

		previous = cstr(target.value_en)
		addon_qty = flt(addon["item"].stock_qty or addon["item"].qty)
		per_unit_qty = addon_qty / (flt(item.stock_qty or item.qty) or 1)
		new_value = apply_modification(
			previous, addon["value"], addon["mode"],
			qty=per_unit_qty, aggregatable=attr_doc.is_numeric_aggregatable,
		)
		target.value_en = new_value
		target.is_modified = 1

		config.append("modifications", {
			"addon_item": addon["item"].item_code,
			"addon_qty": addon_qty,
			"attribute": attribute,
			"modification_mode": addon["mode"],
			"previous_value": previous,
			"new_value": new_value,
		})

	config.flags.ignore_permissions = True
	config.insert(ignore_permissions=True)
	config.render()
	config.db_set("spec_html", config.spec_html, update_modified=False)
	return config


def delete_configurations(doc, method=None):
	for name in frappe.get_all(
		"As Built Configuration",
		filters={"delivery_document_type": doc.doctype, "delivery_document": doc.name},
		pluck="name",
	):
		frappe.delete_doc("As Built Configuration", name, ignore_permissions=True, force=True)


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_config_html(delivery_document_type, delivery_document, delivery_detail):
	name = frappe.db.get_value(
		"As Built Configuration",
		{
			"delivery_document_type": delivery_document_type,
			"delivery_document": delivery_document,
			"delivery_detail": delivery_detail,
		},
		"name",
	)
	if not name:
		return ""
	config = frappe.get_doc("As Built Configuration", name)
	rows = [r for r in config.specifications if r.show_to_customer]
	return render_spec_block(rows, highlight_modified=True, compact=True)
