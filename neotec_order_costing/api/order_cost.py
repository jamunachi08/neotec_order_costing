"""Actual purchase cost per sales order.

The stock ledger blends. Two hundred laptops bought at 1,000 for one order and
four hundred at 850 for another value every unit at 900, so both orders report
the same cost and neither reports its real margin.

This module resolves the cost that was actually paid to serve a specific sales
order line, by walking the procurement chain backwards from the order rather
than reading valuation forwards from the ledger.

Resolution order, most specific first:

  1  the cost peg's effective rate  landed, else received, else ordered
  2  the rate stamped on the sales row at the time
  3  the purchase order raised against this sales order for this item
  4  a consolidated purchase order that this order drew from
  5  the item's last purchase rate
  6  stock ledger valuation, as a last resort

Every result carries the source that produced it, so a number can always be
explained and a fallback is never mistaken for a real purchase rate.
"""

import frappe
from frappe.utils import flt

SOURCE_LABEL = {
	"landed_rate": "Landed Cost",
	"received_rate": "Receipt Rate",
	"purchase_rate": "Purchase Order Rate",
	"quoted_rate": "Quoted Rate",
	"stamped": "Stamped on Document",
	"po_direct": "Purchase Order (direct link)",
	"po_consolidated": "Consolidated Purchase Order",
	"last_purchase": "Item Last Purchase Rate",
	"ledger": "Stock Ledger Valuation",
	"none": "Not Available",
}

# Rates that represent money actually committed to a supplier for this order.
ACTUAL_SOURCES = {"landed_rate", "received_rate", "purchase_rate",
				  "stamped", "po_direct", "po_consolidated"}


def peg_rate(peg):
	"""Best actual rate held on a cost peg, with its origin."""
	if not peg:
		return 0.0, "none"
	for key in ("landed_rate", "received_rate", "purchase_rate", "quoted_rate"):
		if flt(peg.get(key)):
			return flt(peg[key]), key
	return 0.0, "none"


def purchase_order_rate(sales_order, item_code):
	"""A purchase order raised against this sales order for this item.

	Consolidated purchase orders serve several sales orders from one line, but
	every order in that line paid the same rate, so the line rate is correct
	for all of them.
	"""
	row = frappe.db.sql(
		"""
		select poi.base_rate, poi.conversion_factor, poi.parent
		from `tabPurchase Order Item` poi
		inner join `tabPurchase Order` po on po.name = poi.parent
		where poi.sales_order = %(so)s and poi.item_code = %(item)s
		  and po.docstatus = 1
		order by poi.creation asc
		limit 1
		""",
		{"so": sales_order, "item": item_code}, as_dict=True,
	)
	if row:
		r = row[0]
		return flt(r.base_rate) / (flt(r.conversion_factor) or 1), "po_direct"

	# consolidated: reach the purchase order through the cost peg
	row = frappe.db.sql(
		"""
		select poi.base_rate, poi.conversion_factor
		from `tabOrder Cost Peg` peg
		inner join `tabPurchase Order Item` poi on poi.name = peg.purchase_order_item
		where peg.sales_order = %(so)s and peg.item_code = %(item)s
		  and peg.docstatus = 1
		order by peg.creation asc
		limit 1
		""",
		{"so": sales_order, "item": item_code}, as_dict=True,
	)
	if row:
		r = row[0]
		return flt(r.base_rate) / (flt(r.conversion_factor) or 1), "po_consolidated"

	return 0.0, "none"


def resolve_rate(line, basis="Actual Purchase Cost"):
	"""Unit cost for one sales order line, plus the source that produced it.

	`line` needs: sales_order, item_code, qty, and optionally peg fields,
	stamped_rate and cogs_ledger.
	"""
	qty = flt(line.get("qty"))

	if basis == "Stock Ledger Valuation":
		ledger = flt(line.get("cogs_ledger"))
		if ledger and qty:
			return ledger / qty, "ledger"

	rate, source = peg_rate(line)
	if rate:
		return rate, source

	if flt(line.get("stamped_rate")):
		return flt(line["stamped_rate"]), "stamped"

	rate, source = purchase_order_rate(line.get("sales_order"), line.get("item_code"))
	if rate:
		return rate, source

	rate = flt(frappe.db.get_value("Item", line.get("item_code"), "last_purchase_rate"))
	if rate:
		return rate, "last_purchase"

	ledger = flt(line.get("cogs_ledger"))
	if ledger and qty:
		return ledger / qty, "ledger"

	return 0.0, "none"


def resolve_cost(line, basis="Actual Purchase Cost"):
	"""Returns (total_cost, unit_rate, source_key, is_actual)."""
	rate, source = resolve_rate(line, basis)
	qty = flt(line.get("qty"))
	return rate * qty, rate, source, source in ACTUAL_SOURCES


@frappe.whitelist()
def explain(sales_order, item_code):
	"""Shows every rate available for a line and which one the report uses.
	Useful when someone asks why two orders for the same item cost differently."""
	frappe.has_permission("Sales Order", doc=sales_order, throw=True)

	peg = frappe.db.get_value(
		"Order Cost Peg",
		{"sales_order": sales_order, "item_code": item_code, "docstatus": 1},
		["name", "landed_rate", "received_rate", "purchase_rate", "quoted_rate",
		 "purchase_order", "supplier", "batch_no", "is_consolidated"],
		as_dict=True,
	)
	po_rate, po_source = purchase_order_rate(sales_order, item_code)
	last = flt(frappe.db.get_value("Item", item_code, "last_purchase_rate"))
	valuation = flt(frappe.db.get_value("Item", item_code, "valuation_rate"))

	candidates = []
	if peg:
		for key in ("landed_rate", "received_rate", "purchase_rate", "quoted_rate"):
			if flt(peg.get(key)):
				candidates.append({"source": SOURCE_LABEL[key], "rate": flt(peg[key])})
	if po_rate:
		candidates.append({"source": SOURCE_LABEL[po_source], "rate": po_rate})
	if last:
		candidates.append({"source": SOURCE_LABEL["last_purchase"], "rate": last})
	if valuation:
		candidates.append({"source": "Item Valuation Rate (blended)", "rate": valuation})

	line = dict(peg or {})
	line.update({"sales_order": sales_order, "item_code": item_code, "qty": 1})
	chosen_rate, chosen_source = resolve_rate(line)

	return {
		"sales_order": sales_order,
		"item_code": item_code,
		"chosen_rate": chosen_rate,
		"chosen_source": SOURCE_LABEL.get(chosen_source, chosen_source),
		"is_actual": chosen_source in ACTUAL_SOURCES,
		"peg": peg,
		"candidates": candidates,
	}
