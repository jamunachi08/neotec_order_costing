"""Item and quantity profitability.

Groups the same order-line facts by item rather than by salesperson, so a buyer
can see which part numbers earn money and at what volume. Quantities are broken
into ordered, delivered, invoiced and open, because an item that looks
profitable on invoiced volume may have a large open backlog costed at a rate
nobody has committed to yet.

Cost is the rate actually paid for each sales order, never blended valuation.
"""

import frappe
from frappe import _
from frappe.utils import flt

from neotec_order_costing.api.order_cost import SOURCE_LABEL, resolve_cost
from neotec_order_costing.api import report_columns

LEVELS = ["Item", "Sales Order", "Sales Person"]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.get("company"):
		frappe.throw(_("Select a company."))

	lines = _fetch(filters)
	rows, chart = _build(lines, filters)

	extra = report_columns.parse_selection(filters.get("extra_columns"))
	report_columns.attach(rows, extra)

	return _columns(filters, extra), rows, None, chart, _summary(lines)


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------

def _conditions(filters, date_field):
	parts = ["so.docstatus = 1", "so.company = %(company)s"]
	values = {"company": filters.company}

	mapping = {
		"customer": "so.customer = %(customer)s",
		"sales_order": "so.name = %(sales_order)s",
		"territory": "so.territory = %(territory)s",
		"project": "so.project = %(project)s",
		"cost_center": "so.cost_center = %(cost_center)s",
		"campaign": "so.campaign = %(campaign)s",
		"order_type": "so.order_type = %(order_type)s",
		"item_code": "itm.name = %(item_code)s",
		"brand": "itm.brand = %(brand)s",
		"item_group": "itm.item_group = %(item_group)s",
		"supplier": "peg.supplier = %(supplier)s",
		"purchase_order": "peg.purchase_order = %(purchase_order)s",
		"batch_no": "peg.batch_no = %(batch_no)s",
	}
	for key, clause in mapping.items():
		if filters.get(key):
			parts.append(clause)
			values[key] = filters.get(key)

	if filters.get("from_date"):
		parts.append("{0} >= %(from_date)s".format(date_field))
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		parts.append("{0} <= %(to_date)s".format(date_field))
		values["to_date"] = filters.to_date

	return " and ".join(parts), values


SELECT_COMMON = """
	so.name as sales_order, so.transaction_date, so.customer, so.customer_name,
	so.territory, so.project, so.status as order_status,
	itm.name as item_code, itm.item_name, itm.brand, itm.item_group, itm.stock_uom,
	peg.name as order_cost_peg, peg.supplier, peg.purchase_order, peg.batch_no,
	peg.landed_rate, peg.received_rate, peg.purchase_rate, peg.quoted_rate
"""


def _fetch(filters):
	lines = _invoiced(filters) + _delivered(filters)
	if filters.get("include_open"):
		lines += _open(filters)

	basis = filters.get("cost_basis") or "Actual Purchase Cost"
	people = _sales_people({l["sales_order"] for l in lines})

	for line in lines:
		cost, rate, source, is_actual = resolve_cost(line, basis)
		line["cost"] = cost
		line["unit_cost"] = rate
		line["cost_source"] = SOURCE_LABEL.get(source, source)
		line["is_actual_cost"] = 1 if is_actual else 0
		line["sales_person"] = people.get(line["sales_order"]) or _("Unassigned")

	if filters.get("sales_person"):
		lines = [l for l in lines if l["sales_person"] == filters.sales_person]
	return lines


def _sales_people(sales_orders):
	"""Largest allocation wins for grouping. The Sales Person Profitability
	report splits by percentage; here one label per order keeps the item view
	readable."""
	if not sales_orders:
		return {}
	rows = frappe.get_all(
		"Sales Team",
		filters={"parent": ["in", list(sales_orders)], "parenttype": "Sales Order"},
		fields=["parent", "sales_person", "allocated_percentage"],
		order_by="allocated_percentage desc",
	)
	out = {}
	for row in rows:
		out.setdefault(row.parent, row.sales_person)
	return out


def _invoiced(filters):
	conditions, values = _conditions(filters, "si.posting_date")
	return frappe.db.sql(
		"""
		select 'Invoiced' as bucket, {common},
			sii.stock_qty as qty, sii.stock_qty as qty_invoiced,
			0 as qty_open,
			sii.base_net_amount as revenue,
			sii.custom_noc_pegged_cost_rate as stamped_rate,
			(select abs(coalesce(sum(sle.stock_value_difference), 0))
			 from `tabStock Ledger Entry` sle
			 where sle.is_cancelled = 0
			   and ((sle.voucher_type = 'Delivery Note' and sle.voucher_detail_no = sii.dn_detail)
			     or (sle.voucher_type = 'Sales Invoice' and sle.voucher_detail_no = sii.name))
			) as cogs_ledger
		from `tabSales Invoice Item` sii
		inner join `tabSales Invoice` si on si.name = sii.parent and si.docstatus = 1
		inner join `tabSales Order Item` soi on soi.name = sii.so_detail
		inner join `tabSales Order` so on so.name = soi.parent
		inner join `tabItem` itm on itm.name = sii.item_code
		left join `tabOrder Cost Peg` peg on peg.name = sii.custom_noc_order_cost_peg
		where {conditions}
		""".format(common=SELECT_COMMON, conditions=conditions),
		values, as_dict=True,
	)


def _delivered(filters):
	conditions, values = _conditions(filters, "dn.posting_date")
	return frappe.db.sql(
		"""
		select 'Delivered' as bucket, {common},
			dni.stock_qty as qty, 0 as qty_invoiced, 0 as qty_open,
			(dni.stock_qty * coalesce(soi.base_net_rate, dni.base_net_rate, 0)) as revenue,
			dni.custom_noc_pegged_cost_rate as stamped_rate,
			(select abs(coalesce(sum(sle.stock_value_difference), 0))
			 from `tabStock Ledger Entry` sle
			 where sle.is_cancelled = 0
			   and sle.voucher_type = 'Delivery Note'
			   and sle.voucher_detail_no = dni.name
			) as cogs_ledger
		from `tabDelivery Note Item` dni
		inner join `tabDelivery Note` dn on dn.name = dni.parent and dn.docstatus = 1
		inner join `tabSales Order Item` soi on soi.name = dni.so_detail
		inner join `tabSales Order` so on so.name = soi.parent
		inner join `tabItem` itm on itm.name = dni.item_code
		left join `tabOrder Cost Peg` peg on peg.name = dni.custom_noc_order_cost_peg
		where {conditions}
		  and not exists (
			select 1 from `tabSales Invoice Item` x
			inner join `tabSales Invoice` xp on xp.name = x.parent
			where x.dn_detail = dni.name and xp.docstatus = 1
		  )
		""".format(common=SELECT_COMMON, conditions=conditions),
		values, as_dict=True,
	)


def _open(filters):
	conditions, values = _conditions(filters, "so.transaction_date")
	return frappe.db.sql(
		"""
		select 'Open' as bucket, {common},
			(soi.stock_qty - (ifnull(soi.delivered_qty, 0) * ifnull(soi.conversion_factor, 1))) as qty,
			0 as qty_invoiced,
			(soi.stock_qty - (ifnull(soi.delivered_qty, 0) * ifnull(soi.conversion_factor, 1))) as qty_open,
			((soi.stock_qty - (ifnull(soi.delivered_qty, 0) * ifnull(soi.conversion_factor, 1)))
				* ifnull(soi.base_net_rate, 0)) as revenue,
			coalesce(soi.custom_noc_pegged_cost_rate,
					 soi.custom_noc_committed_cost_rate) as stamped_rate,
			0 as cogs_ledger
		from `tabSales Order Item` soi
		inner join `tabSales Order` so on so.name = soi.parent
		inner join `tabItem` itm on itm.name = soi.item_code
		left join `tabOrder Cost Peg` peg on peg.name = soi.custom_noc_order_cost_peg
		where {conditions}
		  and so.status not in ('Closed', 'Cancelled')
		  and (soi.stock_qty - (ifnull(soi.delivered_qty, 0) * ifnull(soi.conversion_factor, 1))) > 0.001
		""".format(common=SELECT_COMMON, conditions=conditions),
		values, as_dict=True,
	)


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

KEYS = ("qty", "qty_invoiced", "qty_delivered", "qty_open",
		"revenue", "cost", "gross_profit")

CARRY = ("item_name", "brand", "item_group", "stock_uom", "customer",
		 "customer_name", "territory", "project", "order_status",
		 "transaction_date", "supplier", "purchase_order", "batch_no",
		 "order_cost_peg", "cost_source", "sales_person", "item_code",
		 "sales_order")


def _blank():
	return {k: 0.0 for k in KEYS} | {"_estimated": 0}


def _add(node, line):
	node["qty"] += flt(line["qty"])
	node["qty_invoiced"] += flt(line.get("qty_invoiced"))
	node["qty_open"] += flt(line.get("qty_open"))
	if line["bucket"] == "Delivered":
		node["qty_delivered"] += flt(line["qty"])
	elif line["bucket"] == "Invoiced":
		node["qty_delivered"] += flt(line["qty"])
	node["revenue"] += flt(line["revenue"])
	node["cost"] += flt(line["cost"])
	node["gross_profit"] += flt(line["revenue"]) - flt(line["cost"])
	if not line.get("is_actual_cost"):
		node["_estimated"] += 1


def _finish(node):
	qty = flt(node["qty"])
	revenue = flt(node["revenue"])
	node["avg_selling_rate"] = (revenue / qty) if qty else 0
	node["avg_cost_rate"] = (flt(node["cost"]) / qty) if qty else 0
	node["unit_margin"] = node["avg_selling_rate"] - node["avg_cost_rate"]
	node["gross_margin_pct"] = (node["gross_profit"] / revenue * 100) if revenue else 0
	node["markup_pct"] = (node["unit_margin"] / node["avg_cost_rate"] * 100) \
		if node["avg_cost_rate"] else 0
	if node.get("_estimated"):
		node["cost_source"] = _("{0} line(s) estimated").format(node["_estimated"])
	return node


def _build(lines, filters):
	depth = int(filters.get("depth") or 2)
	group_by = filters.get("group_by") or "Item"
	second = {"Item": "sales_order", "Brand": "item_code",
			  "Item Group": "item_code", "Customer": "item_code",
			  "Project": "item_code"}.get(group_by, "sales_order")
	first = {"Item": "item_code", "Brand": "brand", "Item Group": "item_group",
			 "Customer": "customer", "Project": "project"}.get(group_by, "item_code")

	tree = {}
	for line in lines:
		top = line.get(first) or _("Unassigned")
		node = tree.setdefault(top, {"totals": _blank(), "children": {},
									 "meta": {k: line.get(k) for k in CARRY}})
		_add(node["totals"], line)

		child_key = line.get(second) or _("Unassigned")
		child = node["children"].setdefault(child_key, {
			"totals": _blank(), "meta": {k: line.get(k) for k in CARRY},
			"grandchildren": {},
		})
		_add(child["totals"], line)

		gk = line.get("sales_person") if second != "sales_person" else line.get("item_code")
		grand = child["grandchildren"].setdefault(gk or _("Unassigned"), {
			"totals": _blank(), "meta": {k: line.get(k) for k in CARRY},
		})
		_add(grand["totals"], line)

	rows = []
	for top in sorted(tree, key=lambda t: -flt(tree[t]["totals"]["gross_profit"])):
		node = tree[top]
		rows.append(_finish(dict(node["totals"], **node["meta"], **{
			"indent": 0, "entity": top, "entity_type": group_by,
		})))
		if depth < 2:
			continue
		for child in sorted(node["children"],
							key=lambda c: -flt(node["children"][c]["totals"]["gross_profit"])):
			cnode = node["children"][child]
			rows.append(_finish(dict(cnode["totals"], **cnode["meta"], **{
				"indent": 1, "entity": child,
				"entity_type": "Sales Order" if second == "sales_order" else "Item",
			})))
			if depth < 3:
				continue
			for grand in sorted(cnode["grandchildren"],
								key=lambda g: -flt(cnode["grandchildren"][g]["totals"]["gross_profit"])):
				gnode = cnode["grandchildren"][grand]
				rows.append(_finish(dict(gnode["totals"], **gnode["meta"], **{
					"indent": 2, "entity": grand, "entity_type": "Sales Person",
				})))

	return rows, _chart(tree, group_by)


def _chart(tree, group_by):
	top = sorted(tree, key=lambda t: -flt(tree[t]["totals"]["gross_profit"]))[:10]
	if not top:
		return None
	return {
		"data": {
			"labels": [str(t) for t in top],
			"datasets": [
				{"name": _("Qty"), "values": [flt(tree[t]["totals"]["qty"]) for t in top]},
				{"name": _("Gross Profit"), "values": [flt(tree[t]["totals"]["gross_profit"]) for t in top]},
			],
		},
		"type": "bar",
		"colors": ["#7F77DD", "#1D9E75"],
	}


def _summary(lines):
	qty = sum(flt(l["qty"]) for l in lines)
	revenue = sum(flt(l["revenue"]) for l in lines)
	cost = sum(flt(l["cost"]) for l in lines)
	profit = revenue - cost
	estimated = sum(1 for l in lines if not l.get("is_actual_cost"))
	out = [
		{"label": _("Quantity"), "value": qty, "datatype": "Float", "indicator": "Grey"},
		{"label": _("Revenue"), "value": revenue, "datatype": "Currency", "indicator": "Blue"},
		{"label": _("Actual Cost"), "value": cost, "datatype": "Currency", "indicator": "Orange"},
		{"label": _("Gross Profit"), "value": profit, "datatype": "Currency",
		 "indicator": "Green" if profit >= 0 else "Red"},
		{"label": _("Margin"), "value": (profit / revenue * 100) if revenue else 0,
		 "datatype": "Percent", "indicator": "Green" if profit >= 0 else "Red"},
	]
	if estimated:
		out.append({"label": _("Estimated Lines"), "value": estimated,
					"datatype": "Int", "indicator": "Red"})
	return out


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------

def _columns(filters, extra):
	columns = [
		{"label": _("Item / Order / Person"), "fieldname": "entity", "fieldtype": "Data", "width": 250},
		{"label": _("Type"), "fieldname": "entity_type", "fieldtype": "Data", "width": 100},
		{"label": _("Description"), "fieldname": "item_name", "fieldtype": "Data", "width": 190},
		{"label": _("UOM"), "fieldname": "stock_uom", "fieldtype": "Link", "options": "UOM", "width": 70},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 95},
		{"label": _("Delivered"), "fieldname": "qty_delivered", "fieldtype": "Float", "width": 95},
		{"label": _("Invoiced"), "fieldname": "qty_invoiced", "fieldtype": "Float", "width": 95},
		{"label": _("Open"), "fieldname": "qty_open", "fieldtype": "Float", "width": 90},
		{"label": _("Avg Selling Rate"), "fieldname": "avg_selling_rate", "fieldtype": "Currency", "width": 130},
		{"label": _("Avg Cost Rate"), "fieldname": "avg_cost_rate", "fieldtype": "Currency", "width": 125},
		{"label": _("Unit Margin"), "fieldname": "unit_margin", "fieldtype": "Currency", "width": 120},
		{"label": _("Revenue"), "fieldname": "revenue", "fieldtype": "Currency", "width": 130},
		{"label": _("Actual Cost"), "fieldname": "cost", "fieldtype": "Currency", "width": 130},
		{"label": _("Gross Profit"), "fieldname": "gross_profit", "fieldtype": "Currency", "width": 130},
		{"label": _("Margin %"), "fieldname": "gross_margin_pct", "fieldtype": "Percent", "width": 90},
	]
	if filters.get("show_markup"):
		columns.append({"label": _("Markup %"), "fieldname": "markup_pct",
						"fieldtype": "Percent", "width": 90})
	if filters.get("show_cost_source"):
		columns.append({"label": _("Cost Source"), "fieldname": "cost_source",
						"fieldtype": "Data", "width": 180})
	if filters.get("show_procurement"):
		columns += [
			{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link",
			 "options": "Supplier", "width": 150},
			{"label": _("Purchase Order"), "fieldname": "purchase_order", "fieldtype": "Link",
			 "options": "Purchase Order", "width": 150},
			{"label": _("Batch"), "fieldname": "batch_no", "fieldtype": "Link",
			 "options": "Batch", "width": 150},
		]
	columns += report_columns.columns(extra)
	return columns
