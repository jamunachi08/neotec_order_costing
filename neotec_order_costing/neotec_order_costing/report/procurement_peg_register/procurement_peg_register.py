import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return _columns(), _data(filters)


def _columns():
	return [
		{"label": _("Peg"), "fieldname": "name", "fieldtype": "Link", "options": "Order Cost Peg", "width": 150},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 120},
		{"label": _("Sales Order"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 150},
		{"label": _("Order Date"), "fieldname": "transaction_date", "fieldtype": "Date", "width": 95},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 140},
		{"label": _("Sales Person"), "fieldname": "sales_person", "fieldtype": "Link", "options": "Sales Person", "width": 130},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 140},
		{"label": _("Brand"), "fieldname": "brand", "fieldtype": "Link", "options": "Brand", "width": 90},
		{"label": _("Material Request"), "fieldname": "material_request", "fieldtype": "Link", "options": "Material Request", "width": 150},
		{"label": _("Purchase Order"), "fieldname": "purchase_order", "fieldtype": "Link", "options": "Purchase Order", "width": 150},
		{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 140},
		{"label": _("Inward Doc Type"), "fieldname": "stock_document_type", "fieldtype": "Data", "width": 130},
		{"label": _("Inward Document"), "fieldname": "stock_document", "fieldtype": "Data", "width": 150},
		{"label": _("Batch"), "fieldname": "batch_no", "fieldtype": "Link", "options": "Batch", "width": 150},
		{"label": _("Pegged"), "fieldname": "qty_pegged", "fieldtype": "Float", "width": 85},
		{"label": _("Received"), "fieldname": "qty_received", "fieldtype": "Float", "width": 85},
		{"label": _("Delivered"), "fieldname": "qty_delivered", "fieldtype": "Float", "width": 85},
		{"label": _("Open"), "fieldname": "qty_open", "fieldtype": "Float", "width": 80},
		{"label": _("PO Rate"), "fieldname": "purchase_rate", "fieldtype": "Currency", "width": 105},
		{"label": _("Landed Rate"), "fieldname": "landed_rate", "fieldtype": "Currency", "width": 110},
		{"label": _("Effective Cost"), "fieldname": "effective_cost_rate", "fieldtype": "Currency", "width": 120},
		{"label": _("Selling Rate"), "fieldname": "selling_rate", "fieldtype": "Currency", "width": 110},
		{"label": _("Unit Margin"), "fieldname": "unit_margin", "fieldtype": "Currency", "width": 110},
		{"label": _("Costing Mode"), "fieldname": "costing_mode_applied", "fieldtype": "Data", "width": 150},
	]


def _data(filters):
	conds = {"docstatus": 1}
	for key in ("company", "sales_order", "purchase_order", "customer", "supplier",
				"item_code", "brand", "status", "sales_person"):
		if filters.get(key):
			conds[key] = filters.get(key)
	if filters.get("only_open"):
		conds["status"] = ["not in", ["Closed", "Cancelled"]]

	rows = frappe.get_all(
		"Order Cost Peg",
		filters=conds,
		fields=[c["fieldname"] for c in _columns() if c["fieldname"] != "unit_margin"],
		order_by="transaction_date asc, name asc",
		limit_page_length=0,
	)
	for r in rows:
		r["unit_margin"] = flt(r.get("selling_rate")) - flt(r.get("effective_cost_rate"))
	return rows
