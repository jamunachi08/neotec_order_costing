"""Extra columns from related documents.

Both profitability reports aggregate. Their rows are groups, not documents, so
an arbitrary SQL join would fan out the totals. Instead an extra column names a
source document and the row key that reaches it, and values are batch-fetched
once per source and attached to the finished rows.

That keeps the aggregation correct and lets an implementor add any field from
anywhere in the cycle without touching the report.
"""

import frappe
from frappe import _

# source doctype -> the row key that identifies one of its records
SOURCE_KEY = {
	"Sales Order": "sales_order",
	"Customer": "customer",
	"Item": "item_code",
	"Item Group": "item_group",
	"Brand": "brand",
	"Supplier": "supplier",
	"Purchase Order": "purchase_order",
	"Batch": "batch_no",
	"Project": "project",
	"Sales Person": "sales_person",
	"Territory": "territory",
	"Order Cost Peg": "order_cost_peg",
}

# fields offered per source. Anything not listed is still reachable by typing
# the fieldname, but these are the ones the picker shows.
EXTRA_FIELDS = {
	"Sales Order": [
		("transaction_date", "Order Date", "Date", None),
		("delivery_date", "Promised Date", "Date", None),
		("po_no", "Customer PO", "Data", None),
		("po_date", "Customer PO Date", "Date", None),
		("order_type", "Order Type", "Data", None),
		("status", "Order Status", "Data", None),
		("project", "Project", "Link", "Project"),
		("cost_center", "Cost Center", "Link", "Cost Center"),
		("territory", "Territory", "Link", "Territory"),
		("campaign", "Campaign", "Link", "Campaign"),
		("source", "Lead Source", "Link", "Lead Source"),
		("sales_partner", "Sales Partner", "Link", "Sales Partner"),
		("currency", "Currency", "Link", "Currency"),
		("conversion_rate", "Exchange Rate", "Float", None),
		("grand_total", "Order Value", "Currency", None),
		("advance_paid", "Advance Paid", "Currency", None),
		("per_delivered", "% Delivered", "Percent", None),
		("per_billed", "% Billed", "Percent", None),
		("per_picked", "% Picked", "Percent", None),
		("delivery_status", "Delivery Status", "Data", None),
		("billing_status", "Billing Status", "Data", None),
		("payment_terms_template", "Payment Terms", "Link", "Payment Terms Template"),
		("tc_name", "Terms", "Link", "Terms and Conditions"),
		("incoterm", "Incoterm", "Link", "Incoterm"),
		("named_place", "Named Place", "Data", None),
		("company_address", "Company Address", "Link", "Address"),
		("shipping_address_name", "Shipping Address", "Link", "Address"),
		("contact_person", "Contact Person", "Link", "Contact"),
		("contact_mobile", "Contact Mobile", "Data", None),
		("total_commission", "Total Commission", "Currency", None),
		("amount_eligible_for_commission", "Commissionable Amount", "Currency", None),
	],
	"Customer": [
		("customer_name", "Customer Name", "Data", None),
		("customer_group", "Customer Group", "Link", "Customer Group"),
		("customer_type", "Customer Type", "Data", None),
		("territory", "Customer Territory", "Link", "Territory"),
		("tax_id", "Customer VAT No", "Data", None),
		("default_currency", "Customer Currency", "Link", "Currency"),
		("payment_terms", "Customer Payment Terms", "Link", "Payment Terms Template"),
	],
	"Item": [
		("item_name", "Item Name", "Data", None),
		("item_group", "Item Group", "Link", "Item Group"),
		("brand", "Brand", "Link", "Brand"),
		("stock_uom", "Stock UOM", "Link", "UOM"),
		("description", "Item Description", "Small Text", None),
		("has_batch_no", "Batched", "Check", None),
		("last_purchase_rate", "Last Purchase Rate", "Currency", None),
		("valuation_rate", "Item Valuation Rate", "Currency", None),
		("custom_noc_spec_template", "Spec Template", "Link", "Specification Template"),
	],
	"Supplier": [
		("supplier_name", "Supplier Name", "Data", None),
		("supplier_group", "Supplier Group", "Link", "Supplier Group"),
		("tax_id", "Supplier VAT No", "Data", None),
		("default_currency", "Supplier Currency", "Link", "Currency"),
	],
	"Purchase Order": [
		("transaction_date", "PO Date", "Date", None),
		("schedule_date", "PO Required By", "Date", None),
		("status", "PO Status", "Data", None),
		("supplier", "PO Supplier", "Link", "Supplier"),
		("grand_total", "PO Value", "Currency", None),
		("per_received", "% Received", "Percent", None),
		("per_billed", "% Billed (PO)", "Percent", None),
		("custom_noc_split_brand", "PO Brand", "Link", "Brand"),
	],
	"Batch": [
		("expiry_date", "Batch Expiry", "Date", None),
		("manufacturing_date", "Batch Mfg Date", "Date", None),
		("use_batchwise_valuation", "Batchwise Valuation", "Check", None),
		("custom_noc_source_purchase_order", "Batch Source PO", "Link", "Purchase Order"),
	],
	"Project": [
		("project_name", "Project Name", "Data", None),
		("status", "Project Status", "Data", None),
		("expected_end_date", "Project End Date", "Date", None),
		("project_type", "Project Type", "Link", "Project Type"),
		("customer", "Project Customer", "Link", "Customer"),
	],
	"Sales Person": [
		("parent_sales_person", "Reports To", "Link", "Sales Person"),
		("employee", "Employee", "Link", "Employee"),
		("commission_rate", "Default Commission Rate", "Float", None),
		("enabled", "Active", "Check", None),
	],
	"Order Cost Peg": [
		("status", "Peg Status", "Data", None),
		("purchase_rate", "Peg PO Rate", "Currency", None),
		("received_rate", "Peg Received Rate", "Currency", None),
		("landed_rate", "Peg Landed Rate", "Currency", None),
		("quoted_rate", "Peg Quoted Rate", "Currency", None),
		("qty_pegged", "Qty Pegged", "Float", None),
		("qty_received", "Qty Received", "Float", None),
		("qty_delivered", "Qty Delivered", "Float", None),
		("qty_open", "Qty Open", "Float", None),
		("is_consolidated", "Consolidated", "Check", None),
		("costing_mode_applied", "Costing Mode", "Data", None),
	],
}

FIELD_META = {
	(doctype, fieldname): {"label": label, "fieldtype": fieldtype, "options": options}
	for doctype, fields in EXTRA_FIELDS.items()
	for fieldname, label, fieldtype, options in fields
}


def alias(doctype, fieldname):
	return "x_{0}_{1}".format(doctype.lower().replace(" ", "_"), fieldname)


# ---------------------------------------------------------------------------
# Picker
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_extra_catalog():
	tree = []
	for doctype in EXTRA_FIELDS:
		if not frappe.db.exists("DocType", doctype):
			continue
		tree.append({
			"doctype_label": doctype,
			"key_field": SOURCE_KEY.get(doctype),
			"fields": [
				{
					"fieldname": fieldname,
					"label": label,
					"fieldtype": fieldtype,
					"value": "{0}||{1}".format(doctype, fieldname),
				}
				for fieldname, label, fieldtype, _o in EXTRA_FIELDS[doctype]
			],
		})
	return tree


def parse_selection(raw):
	"""Accepts a list of 'Doctype||fieldname' strings from the filter."""
	if not raw:
		return []
	if isinstance(raw, str):
		raw = frappe.parse_json(raw) if raw.strip().startswith("[") else [raw]
	out = []
	for entry in raw:
		if "||" not in entry:
			continue
		doctype, fieldname = entry.split("||", 1)
		if (doctype, fieldname) in FIELD_META:
			out.append((doctype, fieldname))
	return out


# ---------------------------------------------------------------------------
# Attachment
# ---------------------------------------------------------------------------

def attach(rows, selection):
	"""Fetches each source once and attaches the values to every row that
	carries the matching key."""
	selection = selection if isinstance(selection, list) else parse_selection(selection)
	if not selection or not rows:
		return rows

	by_source = {}
	for doctype, fieldname in selection:
		by_source.setdefault(doctype, []).append(fieldname)

	for doctype, fieldnames in by_source.items():
		key = SOURCE_KEY.get(doctype)
		if not key:
			continue
		names = {r.get(key) for r in rows if r.get(key)}
		if not names:
			continue

		try:
			records = frappe.get_all(
				doctype, filters={"name": ["in", list(names)]},
				fields=["name"] + fieldnames,
			)
		except Exception:
			# a field removed from the site should not break the whole report
			frappe.log_error(
				"Extra columns unavailable for {0}: {1}".format(doctype, fieldnames),
				"Neotec Order Costing",
			)
			continue

		lookup = {r["name"]: r for r in records}
		for row in rows:
			record = lookup.get(row.get(key))
			if not record:
				continue
			for fieldname in fieldnames:
				row[alias(doctype, fieldname)] = record.get(fieldname)
	return rows


def columns(selection):
	selection = selection if isinstance(selection, list) else parse_selection(selection)
	out = []
	for doctype, fieldname in selection:
		meta = FIELD_META[(doctype, fieldname)]
		out.append({
			"label": _(meta["label"]),
			"fieldname": alias(doctype, fieldname),
			"fieldtype": meta["fieldtype"],
			"options": meta["options"],
			"width": 140,
		})
	return out
