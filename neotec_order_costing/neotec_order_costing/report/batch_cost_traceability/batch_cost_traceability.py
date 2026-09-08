import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return _columns(), _data(filters)


def _columns():
	return [
		{"label": _("Batch"), "fieldname": "batch_no", "fieldtype": "Link", "options": "Batch", "width": 170},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 140},
		{"label": _("Source Sales Order"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 155},
		{"label": _("Source Purchase Order"), "fieldname": "purchase_order", "fieldtype": "Link", "options": "Purchase Order", "width": 160},
		{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 140},
		{"label": _("Inward Doc"), "fieldname": "stock_document", "fieldtype": "Data", "width": 150},
		{"label": _("Qty In"), "fieldname": "qty_in", "fieldtype": "Float", "width": 90},
		{"label": _("Qty Out"), "fieldname": "qty_out", "fieldtype": "Float", "width": 90},
		{"label": _("Balance"), "fieldname": "balance", "fieldtype": "Float", "width": 90},
		{"label": _("Incoming Rate"), "fieldname": "incoming_rate", "fieldtype": "Currency", "width": 120},
		{"label": _("Batch Stock Value"), "fieldname": "stock_value", "fieldtype": "Currency", "width": 140},
	]


def _data(filters):
	conds = ["sle.is_cancelled = 0", "sle.batch_no is not null"]
	values = {}
	if filters.get("company"):
		conds.append("sle.company = %(company)s")
		values["company"] = filters.company
	if filters.get("item_code"):
		conds.append("sle.item_code = %(item_code)s")
		values["item_code"] = filters.item_code
	if filters.get("batch_no"):
		conds.append("sle.batch_no = %(batch_no)s")
		values["batch_no"] = filters.batch_no
	if filters.get("sales_order"):
		conds.append("peg.sales_order = %(sales_order)s")
		values["sales_order"] = filters.sales_order

	rows = frappe.db.sql(
		"""
		select sle.batch_no, sle.item_code,
			peg.sales_order, peg.purchase_order, peg.supplier, peg.stock_document,
			sum(case when sle.actual_qty > 0 then sle.actual_qty else 0 end) as qty_in,
			sum(case when sle.actual_qty < 0 then -sle.actual_qty else 0 end) as qty_out,
			sum(sle.actual_qty) as balance,
			sum(case when sle.actual_qty > 0 then sle.stock_value_difference else 0 end)
				/ nullif(sum(case when sle.actual_qty > 0 then sle.actual_qty else 0 end), 0) as incoming_rate,
			sum(sle.stock_value_difference) as stock_value
		from `tabStock Ledger Entry` sle
		left join `tabOrder Cost Peg` peg on peg.batch_no = sle.batch_no and peg.docstatus = 1
		where {conds}
		group by sle.batch_no, sle.item_code, peg.sales_order, peg.purchase_order,
			peg.supplier, peg.stock_document
		order by sle.batch_no
		""".format(conds=" and ".join(conds)),
		values,
		as_dict=True,
	)
	for r in rows:
		r["incoming_rate"] = flt(r.get("incoming_rate"))
	return rows
