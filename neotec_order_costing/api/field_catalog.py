"""Catalog of every field an implementor can pull into the profitability
report, from any document in the sales or purchase cycle.

Each entry carries the SQL expression used in the dynamic SELECT, so adding a
new field to the picker is a one-line change here.
"""

import frappe

ALIASES = {
	"Item Manufacturer": "imf",
	"Item Specification": "ispec",
	"As Built Configuration": "abc",
	"Part Substitution Log": "psl",
	"Sales Invoice": "si",
	"Sales Invoice Item": "sii",
	"Sales Order": "so",
	"Sales Order Item": "soi",
	"Delivery Note": "dn",
	"Delivery Note Item": "dni",
	"Purchase Order": "po",
	"Purchase Order Item": "poi",
	"Purchase Receipt": "pr",
	"Purchase Invoice": "pi",
	"Order Cost Peg": "peg",
	"Batch": "bat",
	"Item": "itm",
	"Customer": "cust",
	"Supplier": "sup",
}


def _b(alias, spec):
	"""spec: (fieldname, label, fieldtype, options, width)"""
	out = {}
	for fieldname, label, fieldtype, options, width in spec:
		out[fieldname] = {
			"label": label,
			"fieldtype": fieldtype,
			"options": options,
			"width": width,
			"sql": "{0}.`{1}`".format(alias, fieldname),
		}
	return out


FIELD_CATALOG = {
	"Sales Invoice": _b("si", [
		("name", "Sales Invoice", "Link", "Sales Invoice", 150),
		("posting_date", "Invoice Date", "Date", None, 100),
		("customer", "Customer", "Link", "Customer", 140),
		("customer_name", "Customer Name", "Data", None, 160),
		("company", "Company", "Link", "Company", 140),
		("currency", "Currency", "Link", "Currency", 80),
		("conversion_rate", "Exchange Rate", "Float", None, 100),
		("territory", "Territory", "Link", "Territory", 120),
		("project", "Project", "Link", "Project", 120),
		("cost_center", "Cost Center", "Link", "Cost Center", 130),
		("status", "Invoice Status", "Data", None, 110),
		("remarks", "Invoice Remarks", "Small Text", None, 180),
	]),
	"Sales Invoice Item": _b("sii", [
		("item_code", "Item", "Link", "Item", 140),
		("item_name", "Item Name", "Data", None, 180),
		("item_group", "Item Group", "Link", "Item Group", 130),
		("brand", "Brand", "Link", "Brand", 100),
		("description", "Description", "Small Text", None, 200),
		("qty", "Invoiced Qty", "Float", None, 100),
		("stock_qty", "Stock Qty", "Float", None, 100),
		("uom", "UOM", "Link", "UOM", 70),
		("rate", "Selling Rate", "Currency", None, 110),
		("amount", "Selling Amount", "Currency", None, 120),
		("base_amount", "Selling Amount (Base)", "Currency", None, 130),
		("discount_percentage", "Discount %", "Percent", None, 90),
		("warehouse", "Warehouse", "Link", "Warehouse", 140),
		("batch_no", "Delivered Batch", "Link", "Batch", 150),
		("cost_center", "Line Cost Center", "Link", "Cost Center", 130),
		("custom_noc_pegged_cost_rate", "Pegged Cost Rate", "Currency", None, 120),
		("custom_noc_cogs_source", "COGS Source", "Data", None, 150),
		("custom_noc_is_addon", "Is Add-on", "Check", None, 80),
		("custom_noc_addon_parent_item", "Add-on For", "Data", None, 130),
		("custom_noc_manufacturer_part_no", "Manufacturer Part No", "Data", None, 150),
		("custom_noc_supplier_part_no", "Supplier Part No", "Data", None, 140),
		("customer_item_code", "Customer Part No", "Data", None, 140),
		("custom_noc_as_built_config", "As-Built Config", "Link", "As Built Configuration", 150),
	]),
	"Sales Order": _b("so", [
		("name", "Sales Order", "Link", "Sales Order", 150),
		("transaction_date", "Order Date", "Date", None, 100),
		("delivery_date", "Promised Date", "Date", None, 100),
		("po_no", "Customer PO", "Data", None, 130),
		("order_type", "Order Type", "Data", None, 100),
		("status", "Order Status", "Data", None, 110),
		("grand_total", "Order Value", "Currency", None, 130),
	]),
	"Sales Order Item": _b("soi", [
		("qty", "Ordered Qty", "Float", None, 100),
		("rate", "Ordered Rate", "Currency", None, 110),
		("delivered_qty", "Delivered Qty", "Float", None, 100),
		("custom_noc_procurement_status", "Procurement Status", "Data", None, 140),
		("custom_noc_committed_cost_rate", "Committed Cost Rate", "Currency", None, 130),
		("custom_noc_split_group", "Split Group", "Data", None, 120),
	]),
	"Delivery Note": _b("dn", [
		("name", "Delivery Note", "Link", "Delivery Note", 150),
		("posting_date", "Delivery Date", "Date", None, 100),
		("lr_no", "LR No", "Data", None, 110),
		("transporter_name", "Transporter", "Data", None, 140),
	]),
	"Delivery Note Item": _b("dni", [
		("qty", "Delivered Qty", "Float", None, 100),
		("batch_no", "Batch Delivered", "Link", "Batch", 150),
		("incoming_rate", "Valuation Rate", "Currency", None, 120),
		("custom_noc_cogs_source", "DN COGS Source", "Data", None, 150),
	]),
	"Purchase Order": _b("po", [
		("name", "Purchase Order", "Link", "Purchase Order", 150),
		("transaction_date", "PO Date", "Date", None, 100),
		("supplier", "Supplier", "Link", "Supplier", 140),
		("supplier_name", "Supplier Name", "Data", None, 160),
		("status", "PO Status", "Data", None, 110),
		("custom_noc_split_brand", "PO Brand", "Link", "Brand", 100),
	]),
	"Purchase Order Item": _b("poi", [
		("qty", "Ordered Qty (Buy)", "Float", None, 110),
		("rate", "PO Rate", "Currency", None, 110),
		("base_rate", "PO Rate (Base)", "Currency", None, 120),
		("amount", "PO Amount", "Currency", None, 120),
		("discount_percentage", "Bulk Discount %", "Percent", None, 110),
		("received_qty", "Received Qty", "Float", None, 100),
	]),
	"Order Cost Peg": _b("peg", [
		("name", "Cost Peg", "Link", "Order Cost Peg", 150),
		("status", "Peg Status", "Data", None, 120),
		("purchase_rate", "Peg PO Rate", "Currency", None, 110),
		("received_rate", "Peg Received Rate", "Currency", None, 120),
		("landed_rate", "Peg Landed Rate", "Currency", None, 120),
		("effective_cost_rate", "Effective Cost Rate", "Currency", None, 130),
		("costing_mode_applied", "Costing Mode", "Data", None, 150),
		("manufacturer_part_no", "Peg Manufacturer Part No", "Data", None, 160),
		("supplier_part_no", "Peg Supplier Part No", "Data", None, 150),
		("substituted_from_item", "Substituted From", "Link", "Item", 140),
		("substitution_log", "Substitution Log", "Link", "Part Substitution Log", 150),
		("qty_pegged", "Qty Pegged", "Float", None, 100),
		("qty_received", "Qty Received", "Float", None, 100),
		("qty_delivered", "Qty Delivered", "Float", None, 100),
		("qty_open", "Qty Open", "Float", None, 90),
		("sales_person", "Sales Person", "Link", "Sales Person", 140),
		("stock_document_type", "Inward Doc Type", "Data", None, 130),
		("stock_document", "Inward Document", "Data", None, 150),
	]),
	"Batch": _b("bat", [
		("name", "Batch", "Link", "Batch", 150),
		("expiry_date", "Batch Expiry", "Date", None, 100),
		("custom_noc_source_sales_order", "Batch Source SO", "Link", "Sales Order", 150),
		("custom_noc_source_purchase_order", "Batch Source PO", "Link", "Purchase Order", 150),
	]),
	"Item": _b("itm", [
		("stock_uom", "Stock UOM", "Link", "UOM", 80),
		("has_batch_no", "Batched Item", "Check", None, 90),
		("is_stock_item", "Stock Item", "Check", None, 90),
		("shelf_life_in_days", "Shelf Life (Days)", "Int", None, 110),
	]),
	"Customer": _b("cust", [
		("customer_group", "Customer Group", "Link", "Customer Group", 140),
		("customer_type", "Customer Type", "Data", None, 110),
		("tax_id", "Customer VAT No", "Data", None, 130),
	]),
	"Supplier": _b("sup", [
		("supplier_group", "Supplier Group", "Link", "Supplier Group", 140),
		("tax_id", "Supplier VAT No", "Data", None, 130),
	]),
	"Purchase Receipt": _b("pr", [
		("name", "Purchase Receipt", "Link", "Purchase Receipt", 150),
		("posting_date", "Receipt Date", "Date", None, 100),
	]),
	"Item Manufacturer": _b("imf", [
		("manufacturer", "Manufacturer", "Link", "Manufacturer", 130),
		("manufacturer_part_no", "Manufacturer Part No", "Data", None, 150),
	]),
	"As Built Configuration": _b("abc", [
		("name", "As-Built Config", "Link", "As Built Configuration", 150),
		("manufacturer_part_no", "Delivered Part No", "Data", None, 150),
	]),
	"Part Substitution Log": _b("psl", [
		("name", "Substitution Log", "Link", "Part Substitution Log", 150),
		("original_item", "Ordered Part No", "Link", "Item", 140),
		("substituted_item", "Supplied Part No", "Link", "Item", 140),
		("relation_used", "Substitution Relation", "Data", None, 140),
	]),
	"Purchase Invoice": _b("pi", [
		("name", "Purchase Invoice", "Link", "Purchase Invoice", 150),
		("posting_date", "Bill Date", "Date", None, 100),
		("bill_no", "Supplier Bill No", "Data", None, 130),
		("update_stock", "Stock Updated on PI", "Check", None, 120),
	]),
}

# Computed columns are not simple field reads. They are evaluated in Python
# after the rows come back so currency conversion and add-on roll-ups apply.
COMPUTED = {
	"revenue": {"label": "Revenue", "fieldtype": "Currency", "width": 130},
	"cogs_actual": {"label": "COGS (Ledger)", "fieldtype": "Currency", "width": 130},
	"cogs_pegged": {"label": "COGS (Pegged)", "fieldtype": "Currency", "width": 130},
	"cogs_variance": {"label": "COGS Variance", "fieldtype": "Currency", "width": 120},
	"gross_profit": {"label": "Gross Profit", "fieldtype": "Currency", "width": 130},
	"gross_margin_pct": {"label": "Margin %", "fieldtype": "Percent", "width": 90},
	"unit_cost": {"label": "Unit Cost", "fieldtype": "Currency", "width": 110},
	"unit_margin": {"label": "Unit Margin", "fieldtype": "Currency", "width": 110},
	"markup_pct": {"label": "Markup %", "fieldtype": "Percent", "width": 90},
	"revenue_status": {"label": "Revenue Status", "fieldtype": "Data", "width": 160},
	"cogs_effective": {"label": "Cost Used", "fieldtype": "Currency", "width": 130},
}
FIELD_CATALOG["Computed"] = {
	k: dict(v, options=None, sql=None) for k, v in COMPUTED.items()
}


def is_valid_field(source_document, fieldname):
	return fieldname in FIELD_CATALOG.get(source_document, {})


def sql_expression(source_document, fieldname, alias):
	meta = FIELD_CATALOG.get(source_document, {}).get(fieldname)
	if not meta or not meta.get("sql"):
		return None
	return "{0} as `{1}`".format(meta["sql"], alias)


def column_alias(source_document, fieldname):
	return "{0}__{1}".format(ALIASES.get(source_document, "x"), fieldname)


@frappe.whitelist()
def get_catalog_tree():
	"""Grouped payload for the column picker dialog."""
	tree = []
	for doctype in FIELD_CATALOG:
		tree.append({
			"doctype_label": doctype,
			"fields": sorted(
				[
					{
						"fieldname": fn,
						"label": meta.get("label"),
						"fieldtype": meta.get("fieldtype"),
						"value": "{0}||{1}".format(doctype, fn),
					}
					for fn, meta in FIELD_CATALOG[doctype].items()
				],
				key=lambda x: x["label"] or "",
			),
		})
	return tree
