"""Outward side.

Delivery Note and Sales Invoice with Update Stock both route through here, so
the costing behaves the same whether the client delivers then invoices or
invoices directly.
"""

import frappe
from frappe.utils import flt

from neotec_order_costing.api.batching import set_batch_on_row
from neotec_order_costing.neotec_order_costing.doctype.order_costing_settings.order_costing_settings import (
	get_settings,
	resolve_costing_mode,
)


def _is_stock_outward(doc):
	if doc.doctype == "Delivery Note":
		return True
	return doc.doctype == "Sales Invoice" and bool(doc.get("update_stock"))


def _so_item_of(item):
	return item.get("so_detail") or item.get("sales_order_item")


# ---------------------------------------------------------------------------
# before_validate
# ---------------------------------------------------------------------------

def apply_pegged_batches(doc, method=None):
	settings = get_settings()
	if not settings.enable_order_wise_cogs or not _is_stock_outward(doc):
		return

	for item in doc.items:
		mode = resolve_costing_mode(doc.company, item.item_code, doc.customer)
		so_item = _so_item_of(item)

		if not so_item:
			_handle_addon(doc, item, settings)
			continue

		peg_name = frappe.db.get_value(
			"Order Cost Peg", {"sales_order_item": so_item, "docstatus": 1}, "name"
		)
		if not peg_name:
			peg_name = _peg_by_order_and_item(item, doc)
		if not peg_name:
			item.custom_noc_cogs_source = "Default Valuation"
			continue

		peg = frappe.get_doc("Order Cost Peg", peg_name)
		_backfill_peg_batch(peg)
		item.custom_noc_order_cost_peg = peg.name
		item.custom_noc_pegged_cost_rate = flt(peg.effective_cost_rate)

		if mode == "Default Valuation":
			item.custom_noc_cogs_source = "Default Valuation"
			continue

		if mode == "Pegged PO Rate":
			item.custom_noc_cogs_source = "Pegged PO Rate"
			continue

		# Pegged Batch Valuation
		if not peg.batch_no:
			_handle_shortfall(doc, item, settings, "no batch has been received against peg {0}".format(peg.name))
			continue

		from neotec_order_costing.api.allocation import peg_available_qty

		available = _batch_qty(peg.batch_no, item.warehouse)
		if peg.get("is_consolidated"):
			allocated = peg_available_qty(peg)
			if allocated < available:
				available = allocated
		required = flt(item.stock_qty or item.qty)
		if available < required:
			_handle_shortfall(
				doc, item, settings,
				"batch {0} has {1} available to this order in {2} but {3} is required{4}".format(
					peg.batch_no, available, item.warehouse, required,
					" (shared batch, allocation limited)" if peg.get("is_consolidated") else ""
				),
			)
			continue

		if item.get("batch_no") and item.batch_no != peg.batch_no and not settings.allow_manual_batch_override:
			frappe.throw(
				"Row {0}: batch is pegged to {1} and manual override is disabled.".format(
					item.idx, peg.batch_no
				)
			)

		if not item.get("batch_no"):
			set_batch_on_row(item, peg.batch_no)
		item.custom_noc_cogs_source = "Pegged Batch Valuation"


def _peg_by_order_and_item(item, doc):
	sales_order = item.get("against_sales_order") or item.get("sales_order")
	if not sales_order:
		return None
	return frappe.db.get_value(
		"Order Cost Peg",
		{
			"sales_order": sales_order,
			"item_code": item.item_code,
			"docstatus": 1,
			"status": ["not in", ["Closed", "Cancelled"]],
		},
		"name",
		order_by="qty_open desc",
	)


def _backfill_peg_batch(peg):
	"""A peg that was never updated at receipt time still has a batch waiting
	for it, because the batch records the purchase order it came from."""
	if peg.batch_no or not peg.purchase_order:
		return
	batch = frappe.db.get_value(
		"Batch",
		{
			"item": peg.item_code,
			"custom_noc_source_purchase_order": peg.purchase_order,
			"disabled": 0,
		},
		"name",
		order_by="creation desc",
	)
	if not batch:
		return
	from neotec_order_costing.api.peg import save_peg

	peg.batch_no = batch
	save_peg(peg)


def _handle_shortfall(doc, item, settings, reason):
	message = "Row {0} ({1}): {2}.".format(item.idx, item.item_code, reason)
	behaviour = settings.shortfall_behaviour
	if behaviour == "Block Delivery":
		frappe.throw(message + " Delivery blocked by Order Costing Settings.")
	elif behaviour == "Fallback to Default Valuation with Warning":
		frappe.msgprint(message + " Falling back to default valuation.", indicator="orange",
						title="Order Costing", alert=True)
		item.custom_noc_cogs_source = "Default Valuation"
	else:
		item.custom_noc_cogs_source = "Default Valuation"


def _batch_qty(batch_no, warehouse):
	from erpnext.stock.doctype.batch.batch import get_batch_qty

	try:
		return flt(get_batch_qty(batch_no=batch_no, warehouse=warehouse))
	except Exception:
		return 0.0


# ---------------------------------------------------------------------------
# Add-on items (RAM, SSD, memory upgrades added at invoice time)
# ---------------------------------------------------------------------------

def _handle_addon(doc, item, settings):
	if not settings.enable_addon_handling:
		item.custom_noc_cogs_source = "Default Valuation"
		return

	groups = [g.strip() for g in (settings.addon_item_groups or "").split(",") if g.strip()]
	item_group = frappe.get_cached_value("Item", item.item_code, "item_group")
	if groups and item_group not in groups:
		item.custom_noc_cogs_source = "Default Valuation"
		return

	item.custom_noc_is_addon = 1
	item.custom_noc_addon_parent_item = _guess_parent(doc, item)

	if settings.addon_costing == "Own Peg If Available":
		peg_name = frappe.db.get_value(
			"Order Cost Peg",
			{"item_code": item.item_code, "docstatus": 1, "status": ["in", ["Received", "Partially Delivered"]]},
			"name",
			order_by="creation asc",
		)
		if peg_name:
			peg = frappe.get_doc("Order Cost Peg", peg_name)
			item.custom_noc_order_cost_peg = peg.name
			item.custom_noc_pegged_cost_rate = flt(peg.effective_cost_rate)
			if peg.batch_no and not item.get("batch_no"):
				set_batch_on_row(item, peg.batch_no)
			item.custom_noc_cogs_source = "Pegged Batch Valuation"
			return

	item.custom_noc_cogs_source = "Add-on Item"


def _guess_parent(doc, item):
	"""An add-on is attributed to the first non-add-on line on the same
	document that carries a Sales Order link. Good enough for reporting and
	fully overridable by the user."""
	for other in doc.items:
		if other.name == item.name:
			continue
		if _so_item_of(other):
			return other.item_code
	return None


# ---------------------------------------------------------------------------
# on_submit / on_cancel
# ---------------------------------------------------------------------------

def consume_peg(doc, method=None):
	settings = get_settings()
	if not settings.enable_order_wise_cogs or not _is_stock_outward(doc):
		return

	variance_rows = []
	for item in doc.items:
		if not item.get("custom_noc_order_cost_peg"):
			continue
		peg = frappe.get_doc("Order Cost Peg", item.custom_noc_order_cost_peg)
		qty = flt(item.stock_qty or item.qty)
		peg.register_delivery(doc, item, item.get("batch_no"), qty, flt(item.custom_noc_pegged_cost_rate))

		if peg.sales_order_item:
			frappe.db.set_value(
				"Sales Order Item", peg.sales_order_item,
				"custom_noc_procurement_status", peg.status,
				update_modified=False,
			)

		if item.custom_noc_cogs_source == "Pegged PO Rate" and settings.post_cost_variance:
			actual = _actual_cogs(doc, item)
			pegged = flt(item.custom_noc_pegged_cost_rate) * qty
			if abs(pegged - actual) > 0.005:
				variance_rows.append((item, pegged - actual))

	if variance_rows:
		_post_variance_journal(doc, variance_rows, settings)


def release_peg(doc, method=None):
	if not _is_stock_outward(doc):
		return
	seen = set()
	for item in doc.items:
		peg_name = item.get("custom_noc_order_cost_peg")
		if not peg_name or peg_name in seen:
			continue
		seen.add(peg_name)
		frappe.get_doc("Order Cost Peg", peg_name).release_delivery(doc)


def _actual_cogs(doc, item):
	value = frappe.db.get_value(
		"Stock Ledger Entry",
		{"voucher_type": doc.doctype, "voucher_no": doc.name, "voucher_detail_no": item.name},
		"stock_value_difference",
	)
	return abs(flt(value))


def _post_variance_journal(doc, rows, settings):
	"""Stock has already posted at real valuation. This entry moves the
	difference so management reporting sees the pegged rate while the stock
	ledger and the GL stay in agreement."""
	company = doc.company
	expense_account = frappe.get_cached_value(
		"Company", company, "default_expense_account"
	)
	if not expense_account or not settings.cost_variance_account:
		frappe.log_error("Cost variance accounts not configured", "Neotec Order Costing")
		return

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = company
	je.posting_date = doc.posting_date
	je.user_remark = "Order costing variance for {0} {1}".format(doc.doctype, doc.name)

	total = 0.0
	for item, delta in rows:
		total += flt(delta)
	if not total:
		return

	je.append("accounts", {
		"account": expense_account,
		"debit_in_account_currency": total if total > 0 else 0,
		"credit_in_account_currency": -total if total < 0 else 0,
		"cost_center": settings.variance_cost_center,
	})
	je.append("accounts", {
		"account": settings.cost_variance_account,
		"credit_in_account_currency": total if total > 0 else 0,
		"debit_in_account_currency": -total if total < 0 else 0,
		"cost_center": settings.variance_cost_center,
	})
	je.flags.ignore_permissions = True
	je.insert(ignore_permissions=True)
	je.submit()
	frappe.msgprint(
		"Cost variance journal {0} posted.".format(je.name), indicator="blue", alert=True
	)
