"""Open demand grouped by brand and item, showing what a bulk purchase order
would look like against what separate orders would cost."""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from neotec_order_costing.api.consolidation import fetch_demand


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.get("company"):
		frappe.throw(_("Select a company."))

	rows = fetch_demand(
		filters.company,
		brand=filters.get("brand"),
		item_group=filters.get("item_group"),
		from_date=filters.get("from_date"),
		to_date=filters.get("to_date"),
		warehouse=filters.get("warehouse"),
		include_unlinked_requests=filters.get("include_unlinked_requests"),
	)

	buckets = {}
	for row in rows:
		key = (row.get("brand") or _("No Brand"), row["item_code"])
		b = buckets.setdefault(key, {
			"brand": key[0], "item_code": row["item_code"], "item_name": row.get("item_name"),
			"uom": row.get("uom"), "total_qty": 0.0,
			"sales_orders": set(), "requests": set(), "earliest": None,
		})
		b["total_qty"] += flt(row["qty_pending"])
		if row.get("sales_order"):
			b["sales_orders"].add(row["sales_order"])
		b["requests"].add(row["material_request"])
		req = row.get("required_by")
		if req and (not b["earliest"] or getdate(req) < getdate(b["earliest"])):
			b["earliest"] = req

	data = []
	for b in buckets.values():
		last_rate = flt(frappe.db.get_value("Item", b["item_code"], "last_purchase_rate"))
		data.append({
			"brand": b["brand"],
			"item_code": b["item_code"],
			"item_name": b["item_name"],
			"uom": b["uom"],
			"total_qty": b["total_qty"],
			"order_count": len(b["sales_orders"]),
			"request_count": len(b["requests"]),
			"earliest_required_by": b["earliest"],
			"last_purchase_rate": last_rate,
			"value_at_last_rate": last_rate * b["total_qty"],
		})

	data.sort(key=lambda r: (-flt(r["value_at_last_rate"]), r["item_code"]))
	return _columns(), data, None, _chart(data)


def _columns():
	return [
		{"label": _("Brand"), "fieldname": "brand", "fieldtype": "Data", "width": 110},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
		{"label": _("Description"), "fieldname": "item_name", "fieldtype": "Data", "width": 200},
		{"label": _("Consolidated Qty"), "fieldname": "total_qty", "fieldtype": "Float", "width": 130},
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Link", "options": "UOM", "width": 70},
		{"label": _("Sales Orders"), "fieldname": "order_count", "fieldtype": "Int", "width": 110},
		{"label": _("Requests"), "fieldname": "request_count", "fieldtype": "Int", "width": 90},
		{"label": _("Earliest Required"), "fieldname": "earliest_required_by", "fieldtype": "Date", "width": 120},
		{"label": _("Last Rate"), "fieldname": "last_purchase_rate", "fieldtype": "Currency", "width": 110},
		{"label": _("Value at Last Rate"), "fieldname": "value_at_last_rate", "fieldtype": "Currency", "width": 140},
	]


def _chart(data):
	top = data[:10]
	if not top:
		return None
	return {
		"data": {
			"labels": [r["item_code"] for r in top],
			"datasets": [{"name": _("Consolidated Qty"), "values": [flt(r["total_qty"]) for r in top]}],
		},
		"type": "bar",
		"colors": ["#1D9E75"],
	}
