"""Order Cost Peg lifecycle.

The peg is the record that says "this Sales Order line is served by that
Purchase Order line, which landed in that batch at that rate". Every costing
decision downstream reads from it.
"""

import frappe
from frappe.utils import flt

from neotec_order_costing.neotec_order_costing.doctype.order_costing_settings.order_costing_settings import (
	get_settings,
	resolve_costing_mode,
)


# ---------------------------------------------------------------------------
# Sales Order
# ---------------------------------------------------------------------------

def on_sales_order_submit(doc, method=None):
	settings = get_settings()
	if not settings.enable_order_wise_cogs:
		return

	# A Sales Order can be shared across several salespeople via the Sales Team
	# table. The peg records the largest allocation for convenience; the Sales
	# Person Profitability report reads the full table so credit is split by
	# allocated_percentage rather than given whole to one name.
	sales_person = None
	if doc.get("sales_team"):
		primary = max(
			doc.sales_team, key=lambda m: flt(m.allocated_percentage or 0)
		)
		sales_person = primary.sales_person

	for item in doc.items:
		mode = resolve_costing_mode(doc.company, item.item_code, doc.customer)
		if mode == "Default Valuation":
			item.db_set("custom_noc_procurement_status", "Not Required", update_modified=False)
			continue

		peg = frappe.new_doc("Order Cost Peg")
		peg.company = doc.company
		peg.item_code = item.item_code
		peg.uom = item.uom
		peg.stock_uom = item.stock_uom
		peg.brand = frappe.get_cached_value("Item", item.item_code, "brand")
		peg.sales_order = doc.name
		peg.sales_order_item = item.name
		peg.customer = doc.customer
		peg.sales_person = sales_person
		peg.transaction_date = doc.transaction_date
		peg.qty_pegged = flt(item.stock_qty or item.qty)
		peg.selling_rate = flt(item.rate)
		peg.costing_mode_applied = mode
		peg.flags.ignore_permissions = True
		peg.insert(ignore_permissions=True)
		peg.submit()

		item.db_set("custom_noc_order_cost_peg", peg.name, update_modified=False)
		item.db_set("custom_noc_procurement_status", "Pending", update_modified=False)


def on_sales_order_cancel(doc, method=None):
	for peg in frappe.get_all(
		"Order Cost Peg", filters={"sales_order": doc.name, "docstatus": 1}, pluck="name"
	):
		peg_doc = frappe.get_doc("Order Cost Peg", peg)
		if flt(peg_doc.qty_delivered):
			frappe.throw(
				"Order Cost Peg {0} already has deliveries. Cancel those first.".format(peg)
			)
		peg_doc.cancel()


# ---------------------------------------------------------------------------
# Purchase Order
# ---------------------------------------------------------------------------

def on_purchase_order_submit(doc, method=None):
	if not get_settings().enable_order_wise_cogs:
		return

	for item in doc.items:
		peg = resolve_peg_for_purchase_line(item)
		if not peg:
			continue

		peg.material_request = item.get("material_request")
		peg.purchase_order = doc.name
		peg.purchase_order_item = item.name
		peg.supplier = doc.supplier
		peg.purchase_rate = flt(item.base_rate) / (flt(item.conversion_factor) or 1)
		save_peg(peg)

		item.db_set("custom_noc_order_cost_peg", peg.name, update_modified=False)
		if peg.sales_order_item:
			frappe.db.set_value(
				"Sales Order Item", peg.sales_order_item,
				{
					"custom_noc_procurement_status": "Ordered",
					"custom_noc_committed_cost_rate": peg.purchase_rate,
				},
				update_modified=False,
			)


def on_purchase_order_cancel(doc, method=None):
	for item in doc.items:
		if not item.get("custom_noc_order_cost_peg"):
			continue
		peg = frappe.get_doc("Order Cost Peg", item.custom_noc_order_cost_peg)
		peg.purchase_order = None
		peg.purchase_order_item = None
		peg.supplier = None
		peg.purchase_rate = 0
		save_peg(peg)


# ---------------------------------------------------------------------------
# Stock inward: Purchase Receipt OR Purchase Invoice with Update Stock
# ---------------------------------------------------------------------------

def _is_stock_inward(doc):
	if doc.doctype == "Purchase Receipt":
		return True
	return doc.doctype == "Purchase Invoice" and bool(doc.get("update_stock"))


def validate_inward_flow(doc, method=None):
	"""Optional guard rail for clients who insist on a receipt every time."""
	settings = get_settings()
	if doc.doctype != "Purchase Invoice":
		return
	if not settings.require_purchase_receipt:
		return
	if doc.get("update_stock"):
		return
	for item in doc.items:
		if item.get("purchase_order") and not item.get("purchase_receipt"):
			frappe.throw(
				"Order Costing Settings require a Purchase Receipt before invoicing "
				"Purchase Order {0} (row {1}).".format(item.purchase_order, item.idx)
			)


def on_stock_inward(doc, method=None):
	validate_inward_flow(doc)
	if not _is_stock_inward(doc):
		return
	if not get_settings().enable_order_wise_cogs:
		return

	for item in doc.items:
		if item.get("purchase_order_item"):
			shared = _allocate_shared_receipt(doc, item)
			if shared:
				continue
		peg = _peg_for_inward_line(item)
		if not peg:
			continue
		if not peg.purchase_order and item.get("purchase_order"):
			peg.purchase_order = item.purchase_order
			peg.purchase_order_item = item.get("purchase_order_item")
			peg.supplier = doc.supplier
			peg.purchase_rate = peg.purchase_rate or _incoming_rate(item)

		peg.stock_document_type = doc.doctype
		peg.stock_document = doc.name
		peg.qty_received = flt(peg.qty_received) + flt(item.stock_qty or item.qty)
		peg.received_rate = _incoming_rate(item)
		peg.batch_no = _batch_of(item) or peg.batch_no
		save_peg(peg)

		item.db_set("custom_noc_order_cost_peg", peg.name, update_modified=False)
		if peg.sales_order_item:
			frappe.db.set_value(
				"Sales Order Item", peg.sales_order_item,
				"custom_noc_procurement_status",
				"Received" if flt(peg.qty_received) >= flt(peg.qty_pegged) else "Partially Received",
				update_modified=False,
			)

		if peg.batch_no:
			frappe.db.set_value(
				"Batch", peg.batch_no,
				{
					"custom_noc_order_cost_peg": peg.name,
					"custom_noc_source_sales_order": peg.sales_order,
					"custom_noc_source_purchase_order": peg.purchase_order,
				},
				update_modified=False,
			)


def on_stock_inward_cancel(doc, method=None):
	if not _is_stock_inward(doc):
		return
	for item in doc.items:
		if not item.get("custom_noc_order_cost_peg"):
			continue
		peg = frappe.get_doc("Order Cost Peg", item.custom_noc_order_cost_peg)
		peg.qty_received = max(flt(peg.qty_received) - flt(item.stock_qty or item.qty), 0.0)
		if not peg.qty_received:
			peg.stock_document = None
			peg.stock_document_type = None
			peg.batch_no = None
			peg.received_rate = 0
		save_peg(peg)


# ---------------------------------------------------------------------------
# Landed cost
# ---------------------------------------------------------------------------

def refresh_landed_rates(doc, method=None):
	if not get_settings().enable_order_wise_cogs:
		return
	for item in doc.items:
		peg_name = frappe.db.get_value(
			"Order Cost Peg",
			{"stock_document": item.receipt_document, "item_code": item.item_code, "docstatus": 1},
			"name",
		)
		if not peg_name:
			continue
		peg = frappe.get_doc("Order Cost Peg", peg_name)
		qty = flt(item.qty) or 1
		peg.landed_rate = flt(item.valuation_rate) or (
			(flt(item.amount) + flt(item.applicable_charges)) / qty
		)
		save_peg(peg)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def save_peg(peg):
	"""The peg is designed to be updated throughout its lifecycle after
	submit. The doctype now allows this, and the flag keeps working even if a
	site has not yet migrated the updated field definitions."""
	peg.flags.ignore_permissions = True
	peg.flags.ignore_validate_update_after_submit = True
	peg.save(ignore_permissions=True)
	return peg


def _allocate_shared_receipt(doc, item):
	"""A consolidated purchase order line serves several sales orders. The
	receipt lands in one batch at one rate, and the quantity is divided so no
	order can consume another order's share."""
	from neotec_order_costing.api.allocation import allocate_receipt, pegs_for_po_item

	pegs = pegs_for_po_item(item.purchase_order_item)
	if len(pegs) < 2:
		return False

	qty = flt(item.stock_qty or item.qty)
	rate = _incoming_rate(item)
	batch = _batch_of(item)

	for peg_name, share in allocate_receipt(item.purchase_order_item, qty):
		peg = frappe.get_doc("Order Cost Peg", peg_name)
		peg.stock_document_type = doc.doctype
		peg.stock_document = doc.name
		peg.qty_received = flt(peg.qty_received) + flt(share)
		peg.received_rate = rate
		peg.batch_no = batch or peg.batch_no
		peg.is_consolidated = 1
		save_peg(peg)

		if peg.sales_order_item:
			target = flt(peg.qty_allocated) or flt(peg.qty_pegged)
			frappe.db.set_value(
				"Sales Order Item", peg.sales_order_item,
				"custom_noc_procurement_status",
				"Received" if flt(peg.qty_received) >= target else "Partially Received",
				update_modified=False,
			)

	if batch:
		frappe.db.set_value(
			"Batch", batch,
			{"custom_noc_source_purchase_order": item.get("purchase_order")},
			update_modified=False,
		)
	item.db_set("custom_noc_order_cost_peg", pegs[0]["name"], update_modified=False)
	frappe.msgprint(
		"Receipt of {0} allocated across {1} sales orders.".format(qty, len(pegs)),
		indicator="blue", alert=True,
	)
	return True


def _peg_for_so_item(so_item):
	name = frappe.db.get_value(
		"Order Cost Peg", {"sales_order_item": so_item, "docstatus": 1}, "name"
	)
	return frappe.get_doc("Order Cost Peg", name) if name else None


def resolve_peg_for_purchase_line(item):
	"""The ERP platform does not always carry sales_order_item down to the purchase
	order line. Native Sales Order to Material Request to Purchase Order keeps
	only sales_order on many paths, so fall back to matching on the order plus
	the item, taking the peg with the largest open quantity."""
	if item.get("sales_order_item"):
		peg = _peg_for_so_item(item.sales_order_item)
		if peg:
			return peg

	sales_order = item.get("sales_order")
	if not sales_order and item.get("material_request_item"):
		sales_order = frappe.db.get_value(
			"Material Request Item", item.material_request_item, "sales_order"
		)
	if not sales_order:
		return None

	candidates = frappe.get_all(
		"Order Cost Peg",
		filters={
			"sales_order": sales_order,
			"item_code": item.item_code,
			"docstatus": 1,
			"status": ["not in", ["Closed", "Cancelled"]],
		},
		fields=["name", "qty_open"],
		order_by="qty_open desc",
	)
	if not candidates:
		return None
	if len(candidates) > 1:
		frappe.msgprint(
			"Several open cost pegs exist for {0} on {1}. Pegging to {2}, which has "
			"the largest open quantity. Set Sales Order Item on the purchase line "
			"to remove the ambiguity.".format(item.item_code, sales_order, candidates[0].name),
			indicator="orange", alert=True,
		)
	return frappe.get_doc("Order Cost Peg", candidates[0].name)


def _peg_for_po_item(po_item):
	name = frappe.db.get_value(
		"Order Cost Peg", {"purchase_order_item": po_item, "docstatus": 1}, "name"
	)
	return frappe.get_doc("Order Cost Peg", name) if name else None


def _peg_for_inward_line(item):
	if item.get("purchase_order_item"):
		peg = _peg_for_po_item(item.purchase_order_item)
		if peg:
			return peg
		po_line = frappe.db.get_value(
			"Purchase Order Item", item.purchase_order_item,
			["sales_order", "sales_order_item", "item_code", "material_request_item"],
			as_dict=True,
		)
		if po_line:
			po_line["item_code"] = po_line.get("item_code") or item.item_code
			return resolve_peg_for_purchase_line(frappe._dict(po_line))
	return None


def _batch_of(item):
	if item.get("batch_no"):
		return item.batch_no
	bundle = item.get("serial_and_batch_bundle")
	if not bundle:
		return None
	return frappe.db.get_value(
		"Serial and Batch Entry", {"parent": bundle}, "batch_no"
	)


def _incoming_rate(item):
	base = flt(item.get("valuation_rate")) or flt(item.get("base_net_rate")) or flt(item.get("base_rate"))
	cf = flt(item.get("conversion_factor")) or 1
	return base / cf if item.get("uom") != item.get("stock_uom") else base
