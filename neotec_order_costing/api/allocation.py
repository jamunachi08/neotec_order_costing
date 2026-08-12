"""Receipt allocation for consolidated purchases.

One purchase order line can serve several sales orders. When the goods arrive
they land in one batch at one rate, which is correct — every order in that
tranche was bought at the same price. What still has to be divided is the
quantity, so no order can consume another order's share.
"""

import frappe
from frappe.utils import flt, getdate

from neotec_order_costing.neotec_order_costing.doctype.order_costing_settings.order_costing_settings import (
	get_settings,
)


def pegs_for_po_item(po_item):
	names = frappe.get_all(
		"Order Cost Peg",
		filters={"purchase_order_item": po_item, "docstatus": 1},
		fields=["name", "sales_order", "transaction_date", "qty_allocated",
				"qty_pegged", "qty_received"],
	)
	return names


def _sort_key(method):
	if method == "Earliest Order Date":
		return lambda p: (getdate(p.get("transaction_date") or "2100-01-01"), p["name"])
	if method == "Largest Order First":
		return lambda p: (-flt(p.get("qty_allocated") or p.get("qty_pegged")), p["name"])
	return None


def allocate_receipt(po_item, received_qty, method=None):
	"""Returns [(peg_name, qty)] summing to received_qty, or as close as the
	outstanding allocations allow."""
	settings = get_settings()
	method = method or settings.get("allocation_method") or "Earliest Required Date"

	pegs = pegs_for_po_item(po_item)
	if not pegs:
		return []
	if len(pegs) == 1:
		return [(pegs[0]["name"], flt(received_qty))]

	outstanding = []
	for p in pegs:
		want = flt(p.get("qty_allocated")) or flt(p.get("qty_pegged"))
		remaining = want - flt(p.get("qty_received"))
		if remaining > 0.0001:
			outstanding.append(dict(p, remaining=remaining))
	if not outstanding:
		return [(pegs[0]["name"], flt(received_qty))]

	if method == "Pro Rata":
		total = sum(flt(p["remaining"]) for p in outstanding)
		out = []
		assigned = 0.0
		for p in outstanding[:-1]:
			share = round(flt(received_qty) * flt(p["remaining"]) / total, 6)
			out.append((p["name"], share))
			assigned += share
		out.append((outstanding[-1]["name"], flt(received_qty) - assigned))
		return out

	key = _sort_key(method)
	if key:
		outstanding.sort(key=key)
	else:
		outstanding.sort(key=lambda p: (
			getdate(_required_by(p["name"]) or "2100-01-01"), p["name"]
		))

	out, left = [], flt(received_qty)
	for p in outstanding:
		if left <= 0.0001:
			break
		take = min(left, flt(p["remaining"]))
		out.append((p["name"], take))
		left -= take
	if left > 0.0001 and out:
		# over-receipt goes to the first order in sequence
		out[0] = (out[0][0], out[0][1] + left)
	return out


def _required_by(peg_name):
	so_item = frappe.db.get_value("Order Cost Peg", peg_name, "sales_order_item")
	if not so_item:
		return None
	return frappe.db.get_value("Sales Order Item", so_item, "delivery_date")


def peg_available_qty(peg):
	"""What this sales order may still draw from the shared batch."""
	settings = get_settings()
	received = flt(peg.qty_received)
	delivered = flt(peg.qty_delivered)
	if not settings.get("block_partial_allocation"):
		return received - delivered
	ceiling = flt(peg.qty_allocated) or flt(peg.qty_pegged)
	return min(received, ceiling) - delivered


def describe_allocation(po_item):
	rows = []
	for peg in pegs_for_po_item(po_item):
		rows.append({
			"peg": peg["name"],
			"sales_order": peg["sales_order"],
			"allocated": flt(peg.get("qty_allocated")) or flt(peg.get("qty_pegged")),
			"received": flt(peg.get("qty_received")),
		})
	return rows


@frappe.whitelist()
def get_allocation(purchase_order_item):
	frappe.only_for(["System Manager", "Purchase Manager", "Stock Manager", "Purchase User"])
	return describe_allocation(purchase_order_item)
