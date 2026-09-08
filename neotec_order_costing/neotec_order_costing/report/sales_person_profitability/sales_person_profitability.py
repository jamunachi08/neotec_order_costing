"""Sales Person and Sales Order profitability.

A Sales Order carries a Sales Team child table where each salesperson holds an
`allocated_percentage`. Revenue, cost and profit are therefore split across the
team rather than credited whole to one name, and an order with no team lands
under Unassigned rather than disappearing.

Three sources of value are reported per order line:

  invoiced      a submitted Sales Invoice exists
  delivered     stock has gone out but no invoice yet, so COGS is real and
                revenue is provisional at the order rate
  open          neither delivered nor invoiced, valued at the committed
                purchase rate from the cost peg

Cost is the rate actually paid to the supplier for that order, not the stock
ledger valuation. Two hundred laptops bought at 1,000 for one order and four
hundred at 850 for another blend to 900 in the ledger, which would credit both
salespeople with the same cost and hide the difference in what they earned.
The report therefore resolves cost backwards through the procurement chain and
labels every figure with the source it came from.

Profit is stated before and after sales commission, because a salesperson's
own contribution is usually judged on the latter.
"""

import frappe
from frappe import _
from frappe.utils import flt

from neotec_order_costing.api.order_cost import SOURCE_LABEL, resolve_cost
from neotec_order_costing.api import report_columns

TREE_LEVELS = ["Sales Person", "Sales Order", "Item"]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.get("company"):
		frappe.throw(_("Select a company."))

	lines = _fetch_lines(filters)
	allocations = _allocate(lines, filters)
	rows, chart = _build_tree(allocations, filters)

	extra = report_columns.parse_selection(filters.get("extra_columns"))
	report_columns.attach(rows, extra)

	return _columns(filters, extra), rows, None, chart, _summary(allocations)


# ---------------------------------------------------------------------------
# Fact collection
# ---------------------------------------------------------------------------

def _conditions(alias_so, filters, date_field):
	parts = ["{0}.docstatus = 1".format(alias_so), "{0}.company = %(company)s".format(alias_so)]
	values = {"company": filters.company}

	for key, clause in (
		("customer", "{0}.customer = %(customer)s"),
		("sales_order", "{0}.name = %(sales_order)s"),
		("territory", "{0}.territory = %(territory)s"),
		("project", "{0}.project = %(project)s"),
		("cost_center", "{0}.cost_center = %(cost_center)s"),
		("campaign", "{0}.campaign = %(campaign)s"),
		("order_type", "{0}.order_type = %(order_type)s"),
	):
		if filters.get(key):
			parts.append(clause.format(alias_so))
			values[key] = filters.get(key)

	if filters.get("from_date"):
		parts.append("{0} >= %(from_date)s".format(date_field))
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		parts.append("{0} <= %(to_date)s".format(date_field))
		values["to_date"] = filters.to_date
	if filters.get("brand"):
		parts.append("itm.brand = %(brand)s")
		values["brand"] = filters.brand
	if filters.get("item_group"):
		parts.append("itm.item_group = %(item_group)s")
		values["item_group"] = filters.item_group
	if filters.get("item_code"):
		parts.append("itm.name = %(item_code)s")
		values["item_code"] = filters.item_code
	if filters.get("supplier"):
		parts.append("peg.supplier = %(supplier)s")
		values["supplier"] = filters.supplier
	if filters.get("purchase_order"):
		parts.append("peg.purchase_order = %(purchase_order)s")
		values["purchase_order"] = filters.purchase_order
	if filters.get("batch_no"):
		parts.append("peg.batch_no = %(batch_no)s")
		values["batch_no"] = filters.batch_no

	return " and ".join(parts), values


def _fetch_lines(filters):
	"""One row per sales order line and value bucket."""
	lines = []
	lines += _invoiced(filters)
	if filters.get("include_delivered") in (None, 1, "1", True):
		lines += _delivered_uninvoiced(filters)
	if filters.get("include_open"):
		lines += _open_backlog(filters)
	return lines


def _invoiced(filters):
	conditions, values = _conditions("so", filters, "si.posting_date")
	return frappe.db.sql(
		"""
		select
			'Invoiced' as bucket,
			so.name as sales_order, so.transaction_date, so.customer, so.customer_name,
			so.territory, so.project, so.status as order_status,
			so.per_delivered, so.per_billed,
			so.sales_partner, so.commission_rate as partner_commission_rate,
			peg.name as order_cost_peg,
			sii.item_code, sii.item_name, itm.brand, itm.item_group,
			sii.stock_qty as qty,
			sii.base_net_amount as revenue,
			sii.custom_noc_pegged_cost_rate as stamped_rate,
			peg.landed_rate, peg.received_rate, peg.purchase_rate, peg.quoted_rate,
			(select abs(coalesce(sum(sle.stock_value_difference), 0))
			 from `tabStock Ledger Entry` sle
			 where sle.is_cancelled = 0
			   and ((sle.voucher_type = 'Delivery Note' and sle.voucher_detail_no = sii.dn_detail)
			     or (sle.voucher_type = 'Sales Invoice' and sle.voucher_detail_no = sii.name))
			) as cogs_ledger,
			peg.supplier, peg.purchase_order, peg.batch_no
		from `tabSales Invoice Item` sii
		inner join `tabSales Invoice` si on si.name = sii.parent and si.docstatus = 1
		inner join `tabSales Order Item` soi on soi.name = sii.so_detail
		inner join `tabSales Order` so on so.name = soi.parent
		left join `tabItem` itm on itm.name = sii.item_code
		left join `tabOrder Cost Peg` peg on peg.name = sii.custom_noc_order_cost_peg
		where {conditions}
		""".format(conditions=conditions),
		values, as_dict=True,
	)


def _delivered_uninvoiced(filters):
	conditions, values = _conditions("so", filters, "dn.posting_date")
	return frappe.db.sql(
		"""
		select
			'Delivered' as bucket,
			so.name as sales_order, so.transaction_date, so.customer, so.customer_name,
			so.territory, so.project, so.status as order_status,
			so.per_delivered, so.per_billed,
			so.sales_partner, so.commission_rate as partner_commission_rate,
			peg.name as order_cost_peg,
			dni.item_code, dni.item_name, itm.brand, itm.item_group,
			dni.stock_qty as qty,
			(dni.stock_qty * coalesce(soi.base_net_rate, dni.base_net_rate, 0)) as revenue,
			dni.custom_noc_pegged_cost_rate as stamped_rate,
			peg.landed_rate, peg.received_rate, peg.purchase_rate, peg.quoted_rate,
			(select abs(coalesce(sum(sle.stock_value_difference), 0))
			 from `tabStock Ledger Entry` sle
			 where sle.is_cancelled = 0
			   and sle.voucher_type = 'Delivery Note'
			   and sle.voucher_detail_no = dni.name
			) as cogs_ledger,
			peg.supplier, peg.purchase_order, peg.batch_no
		from `tabDelivery Note Item` dni
		inner join `tabDelivery Note` dn on dn.name = dni.parent and dn.docstatus = 1
		inner join `tabSales Order Item` soi on soi.name = dni.so_detail
		inner join `tabSales Order` so on so.name = soi.parent
		left join `tabItem` itm on itm.name = dni.item_code
		left join `tabOrder Cost Peg` peg on peg.name = dni.custom_noc_order_cost_peg
		where {conditions}
		  and not exists (
			select 1 from `tabSales Invoice Item` x
			inner join `tabSales Invoice` xp on xp.name = x.parent
			where x.dn_detail = dni.name and xp.docstatus = 1
		  )
		""".format(conditions=conditions),
		values, as_dict=True,
	)


def _open_backlog(filters):
	"""Ordered but not yet delivered. Valued at the committed purchase rate so
	the pipeline shows its expected margin."""
	conditions, values = _conditions("so", filters, "so.transaction_date")
	return frappe.db.sql(
		"""
		select
			'Open' as bucket,
			so.name as sales_order, so.transaction_date, so.customer, so.customer_name,
			so.territory, so.project, so.status as order_status,
			so.per_delivered, so.per_billed,
			so.sales_partner, so.commission_rate as partner_commission_rate,
			peg.name as order_cost_peg,
			soi.item_code, soi.item_name, itm.brand, itm.item_group,
			(soi.stock_qty - (ifnull(soi.delivered_qty, 0) * ifnull(soi.conversion_factor, 1))) as qty,
			((soi.stock_qty - (ifnull(soi.delivered_qty, 0) * ifnull(soi.conversion_factor, 1)))
				* ifnull(soi.base_net_rate, 0)) as revenue,
			coalesce(soi.custom_noc_pegged_cost_rate,
					 soi.custom_noc_committed_cost_rate) as stamped_rate,
			peg.landed_rate, peg.received_rate, peg.purchase_rate, peg.quoted_rate,
			0 as cogs_ledger,
			peg.supplier, peg.purchase_order, peg.batch_no
		from `tabSales Order Item` soi
		inner join `tabSales Order` so on so.name = soi.parent
		left join `tabItem` itm on itm.name = soi.item_code
		left join `tabOrder Cost Peg` peg on peg.name = soi.custom_noc_order_cost_peg
		where {conditions}
		  and so.status not in ('Closed', 'Cancelled')
		  and (soi.stock_qty - (ifnull(soi.delivered_qty, 0) * ifnull(soi.conversion_factor, 1))) > 0.001
		""".format(conditions=conditions),
		values, as_dict=True,
	)


# ---------------------------------------------------------------------------
# Allocation across the sales team
# ---------------------------------------------------------------------------

def _team_map(sales_orders):
	"""Sales Team rows keyed by order. allocated_percentage is what splits the
	credit; an order with no team is credited to Unassigned."""
	if not sales_orders:
		return {}
	rows = frappe.get_all(
		"Sales Team",
		filters={"parent": ["in", list(sales_orders)], "parenttype": "Sales Order"},
		fields=["parent", "sales_person", "allocated_percentage", "commission_rate",
				"incentives"],
	)
	teams = {}
	for row in rows:
		teams.setdefault(row.parent, []).append(row)

	for order, members in teams.items():
		total = sum(flt(m.allocated_percentage) for m in members)
		if total <= 0:
			# equal split when percentages were never filled in
			share = 100.0 / len(members)
			for m in members:
				m.allocated_percentage = share
		elif abs(total - 100.0) > 0.01:
			# normalise so profit never over or under counts
			for m in members:
				m.allocated_percentage = flt(m.allocated_percentage) * 100.0 / total
	return teams


def _allocate(lines, filters):
	teams = _team_map({l["sales_order"] for l in lines})
	wanted = filters.get("sales_person")
	basis = filters.get("cost_basis") or "Actual Purchase Cost"
	out = []

	for line in lines:
		total_cost, unit_rate, source, is_actual = resolve_cost(line, basis)
		ledger_cost = flt(line["cogs_ledger"])
		members = teams.get(line["sales_order"]) or [
			frappe._dict({"sales_person": None, "allocated_percentage": 100.0,
						  "commission_rate": 0, "incentives": 0})
		]
		for member in members:
			person = member.sales_person or _("Unassigned")
			if wanted and person != wanted:
				continue
			share = flt(member.allocated_percentage) / 100.0

			revenue = flt(line["revenue"]) * share
			cost = total_cost * share
			ledger = ledger_cost * share
			commission_rate = flt(member.commission_rate) or flt(line.get("partner_commission_rate"))
			commission = revenue * commission_rate / 100.0

			out.append({
				"sales_person": person,
				"allocated_percentage": flt(member.allocated_percentage),
				"sales_order": line["sales_order"],
				"transaction_date": line["transaction_date"],
				"customer": line["customer"],
				"customer_name": line["customer_name"],
				"territory": line["territory"],
				"project": line.get("project"),
				"order_cost_peg": line.get("order_cost_peg"),
				"order_status": line["order_status"],
				"per_delivered": line["per_delivered"],
				"per_billed": line["per_billed"],
				"bucket": line["bucket"],
				"item_code": line["item_code"],
				"item_name": line["item_name"],
				"brand": line["brand"],
				"item_group": line["item_group"],
				"supplier": line.get("supplier"),
				"purchase_order": line.get("purchase_order"),
				"batch_no": line.get("batch_no"),
				"qty": flt(line["qty"]) * share,
				"revenue": revenue,
				"cost": cost,
				"unit_cost": unit_rate,
				"cost_source": SOURCE_LABEL.get(source, source),
				"is_actual_cost": 1 if is_actual else 0,
				"ledger_cost": ledger,
				"cost_variance": cost - ledger if ledger else 0,
				"commission": commission,
				"gross_profit": revenue - cost,
				"net_profit": revenue - cost - commission,
			})
	return out


# ---------------------------------------------------------------------------
# Tree
# ---------------------------------------------------------------------------

def _blank_totals():
	return {"qty": 0.0, "revenue": 0.0, "cost": 0.0, "ledger_cost": 0.0,
			"cost_variance": 0.0, "commission": 0.0,
			"gross_profit": 0.0, "net_profit": 0.0,
			"revenue_invoiced": 0.0, "revenue_delivered": 0.0, "revenue_open": 0.0,
			"_estimated": 0}


def _accumulate(target, row):
	for key in ("qty", "revenue", "cost", "ledger_cost", "cost_variance",
				"commission", "gross_profit", "net_profit"):
		target[key] += flt(row[key])
	target["revenue_" + row["bucket"].lower()] += flt(row["revenue"])
	if not row.get("is_actual_cost"):
		target["_estimated"] += 1


def _finalise(node):
	revenue = flt(node["revenue"])
	qty = flt(node["qty"])
	node["gross_margin_pct"] = (node["gross_profit"] / revenue * 100) if revenue else 0
	node["net_margin_pct"] = (node["net_profit"] / revenue * 100) if revenue else 0
	if not node.get("unit_cost"):
		node["unit_cost"] = (flt(node["cost"]) / qty) if qty else 0
	if node.get("_estimated"):
		node["cost_source"] = _("{0} line(s) estimated").format(node["_estimated"])
	return node


def _build_tree(allocations, filters):
	people = {}
	for row in allocations:
		person = people.setdefault(row["sales_person"], {
			"totals": _blank_totals(), "orders": {}
		})
		_accumulate(person["totals"], row)

		order = person["orders"].setdefault(row["sales_order"], {
			"totals": _blank_totals(), "items": {},
			"meta": {k: row.get(k) for k in ("transaction_date", "customer", "customer_name",
										 "territory", "project", "order_cost_peg",
										 "order_status", "per_delivered",
										 "per_billed", "allocated_percentage")},
		})
		_accumulate(order["totals"], row)

		item = order["items"].setdefault(row["item_code"], {
			"totals": _blank_totals(),
			"meta": {k: row.get(k) for k in ("item_name", "brand", "item_group", "supplier",
										 "purchase_order", "batch_no", "item_code",
										 "order_cost_peg")},
		})
		_accumulate(item["totals"], row)

	depth = int(filters.get("depth") or 3)
	rows = []
	for person in sorted(people, key=lambda p: -flt(people[p]["totals"]["net_profit"])):
		node = people[person]
		rows.append(_finalise(dict(node["totals"], **{
			"indent": 0, "entity": person, "entity_type": "Sales Person",
			"sales_person": person,
		})))
		if depth < 2:
			continue

		for order in sorted(node["orders"],
							key=lambda o: -flt(node["orders"][o]["totals"]["net_profit"])):
			onode = node["orders"][order]
			rows.append(_finalise(dict(onode["totals"], **onode["meta"], **{
				"indent": 1, "entity": order, "entity_type": "Sales Order",
				"sales_order": order, "sales_person": person,
			})))
			if depth < 3:
				continue

			for item in sorted(onode["items"],
							   key=lambda i: -flt(onode["items"][i]["totals"]["net_profit"])):
				inode = onode["items"][item]
				rows.append(_finalise(dict(inode["totals"], **inode["meta"], **{
					"indent": 2, "entity": item, "entity_type": "Item",
					"item_code": item, "sales_order": order, "sales_person": person,
				})))

	return rows, _chart(people)


def _chart(people):
	top = sorted(people, key=lambda p: -flt(people[p]["totals"]["net_profit"]))[:10]
	if not top:
		return None
	return {
		"data": {
			"labels": top,
			"datasets": [
				{"name": _("Revenue"), "values": [flt(people[p]["totals"]["revenue"]) for p in top]},
				{"name": _("Net Profit"), "values": [flt(people[p]["totals"]["net_profit"]) for p in top]},
			],
		},
		"type": "bar",
		"colors": ["#7F77DD", "#1D9E75"],
	}


def _summary(allocations):
	revenue = sum(flt(r["revenue"]) for r in allocations)
	cost = sum(flt(r["cost"]) for r in allocations)
	commission = sum(flt(r["commission"]) for r in allocations)
	estimated = sum(1 for r in allocations if not r.get("is_actual_cost"))
	net = revenue - cost - commission
	out = [
		{"label": _("Revenue"), "value": revenue, "datatype": "Currency", "indicator": "Blue"},
		{"label": _("Actual Cost"), "value": cost, "datatype": "Currency", "indicator": "Orange"},
		{"label": _("Commission"), "value": commission, "datatype": "Currency", "indicator": "Grey"},
		{"label": _("Net Profit"), "value": net, "datatype": "Currency",
		 "indicator": "Green" if net >= 0 else "Red"},
		{"label": _("Net Margin"), "value": (net / revenue * 100) if revenue else 0,
		 "datatype": "Percent", "indicator": "Green" if net >= 0 else "Red"},
	]
	if estimated:
		out.append({"label": _("Estimated Lines"), "value": estimated,
					"datatype": "Int", "indicator": "Red"})
	return out


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------

def _columns(filters, extra=None):
	columns = [
		{"label": _("Sales Person / Order / Item"), "fieldname": "entity",
		 "fieldtype": "Data", "width": 260},
		{"label": _("Type"), "fieldname": "entity_type", "fieldtype": "Data", "width": 100},
		{"label": _("Customer"), "fieldname": "customer_name", "fieldtype": "Data", "width": 170},
		{"label": _("Order Date"), "fieldname": "transaction_date", "fieldtype": "Date", "width": 95},
		{"label": _("Status"), "fieldname": "order_status", "fieldtype": "Data", "width": 110},
		{"label": _("Alloc %"), "fieldname": "allocated_percentage", "fieldtype": "Percent", "width": 80},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 90},
		{"label": _("Revenue"), "fieldname": "revenue", "fieldtype": "Currency", "width": 130},
		{"label": _("Unit Cost"), "fieldname": "unit_cost", "fieldtype": "Currency", "width": 110},
		{"label": _("Actual Cost"), "fieldname": "cost", "fieldtype": "Currency", "width": 130},
		{"label": _("Gross Profit"), "fieldname": "gross_profit", "fieldtype": "Currency", "width": 130},
		{"label": _("Gross %"), "fieldname": "gross_margin_pct", "fieldtype": "Percent", "width": 85},
		{"label": _("Commission"), "fieldname": "commission", "fieldtype": "Currency", "width": 110},
		{"label": _("Net Profit"), "fieldname": "net_profit", "fieldtype": "Currency", "width": 130},
		{"label": _("Net %"), "fieldname": "net_margin_pct", "fieldtype": "Percent", "width": 85},
	]
	if filters.get("show_cost_source"):
		columns.append({"label": _("Cost Source"), "fieldname": "cost_source",
						"fieldtype": "Data", "width": 180})
	if filters.get("compare_ledger"):
		columns += [
			{"label": _("Ledger COGS"), "fieldname": "ledger_cost",
			 "fieldtype": "Currency", "width": 130},
			{"label": _("Variance"), "fieldname": "cost_variance",
			 "fieldtype": "Currency", "width": 120},
		]
	if filters.get("show_buckets"):
		columns += [
			{"label": _("Invoiced"), "fieldname": "revenue_invoiced", "fieldtype": "Currency", "width": 120},
			{"label": _("Delivered"), "fieldname": "revenue_delivered", "fieldtype": "Currency", "width": 120},
			{"label": _("Open"), "fieldname": "revenue_open", "fieldtype": "Currency", "width": 120},
		]
	if filters.get("show_fulfilment"):
		columns += [
			{"label": _("% Delivered"), "fieldname": "per_delivered", "fieldtype": "Percent", "width": 95},
			{"label": _("% Billed"), "fieldname": "per_billed", "fieldtype": "Percent", "width": 90},
		]
	if filters.get("show_procurement"):
		columns += [
			{"label": _("Brand"), "fieldname": "brand", "fieldtype": "Link", "options": "Brand", "width": 100},
			{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 140},
			{"label": _("Purchase Order"), "fieldname": "purchase_order", "fieldtype": "Link",
			 "options": "Purchase Order", "width": 150},
			{"label": _("Batch"), "fieldname": "batch_no", "fieldtype": "Link", "options": "Batch", "width": 150},
		]
	if filters.get("show_territory"):
		columns.insert(3, {"label": _("Territory"), "fieldname": "territory",
						   "fieldtype": "Link", "options": "Territory", "width": 120})
	columns += report_columns.columns(extra or [])
	return columns
