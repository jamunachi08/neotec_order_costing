"""Order-wise Profitability.

Columns are not hardcoded. The implementor builds a Profitability Report
Profile by picking fields from any document in the cycle, and this report
assembles the SELECT list, joins and grouping from that profile at runtime.
"""

import frappe
from frappe import _
from frappe.utils import flt

from neotec_order_costing.api.field_catalog import (
	COMPUTED,
	FIELD_CATALOG,
	column_alias,
	sql_expression,
)

BASE_FROM = """
	from `tabSales Invoice Item` sii
	inner join `tabSales Invoice` si on si.name = sii.parent
	left join `tabSales Order Item` soi on soi.name = sii.so_detail
	left join `tabSales Order` so on so.name = soi.parent
	left join `tabDelivery Note Item` dni on dni.name = sii.dn_detail
	left join `tabDelivery Note` dn on dn.name = dni.parent
	left join `tabOrder Cost Peg` peg on peg.name = sii.custom_noc_order_cost_peg
	left join `tabPurchase Order Item` poi on poi.name = peg.purchase_order_item
	left join `tabPurchase Order` po on po.name = peg.purchase_order
	left join `tabBatch` bat on bat.name = coalesce(sii.batch_no, dni.batch_no, peg.batch_no)
	left join `tabItem` itm on itm.name = sii.item_code
	left join `tabCustomer` cust on cust.name = si.customer
	left join `tabSupplier` sup on sup.name = peg.supplier
	left join `tabItem Manufacturer` imf on imf.item_code = sii.item_code
	left join `tabAs Built Configuration` abc on abc.delivery_detail = sii.dn_detail
	left join `tabPart Substitution Log` psl on psl.order_cost_peg = peg.name
	left join `tabPurchase Receipt` pr on pr.name = (
		case when peg.stock_document_type = 'Purchase Receipt' then peg.stock_document end)
	left join `tabPurchase Invoice` pi on pi.name = (
		case when peg.stock_document_type = 'Purchase Invoice' then peg.stock_document end)
"""

# Delivery Note spine. COGS posts at delivery, revenue at invoicing, so a
# delivered-but-unbilled line has real cost and no invoice yet. Provisional
# revenue comes from the sales order rate.
DN_FROM = """
	from `tabDelivery Note Item` dni
	inner join `tabDelivery Note` dn on dn.name = dni.parent
	left join `tabSales Order Item` soi on soi.name = dni.so_detail
	left join `tabSales Order` so on so.name = soi.parent
	left join `tabOrder Cost Peg` peg on peg.name = dni.custom_noc_order_cost_peg
	left join `tabPurchase Order Item` poi on poi.name = peg.purchase_order_item
	left join `tabPurchase Order` po on po.name = peg.purchase_order
	left join `tabBatch` bat on bat.name = coalesce(dni.batch_no, peg.batch_no)
	left join `tabItem` itm on itm.name = dni.item_code
	left join `tabCustomer` cust on cust.name = dn.customer
	left join `tabSupplier` sup on sup.name = peg.supplier
	left join `tabItem Manufacturer` imf on imf.item_code = dni.item_code
	left join `tabAs Built Configuration` abc on abc.delivery_detail = dni.name
	left join `tabPart Substitution Log` psl on psl.order_cost_peg = peg.name
	left join `tabPurchase Receipt` pr on pr.name = (
		case when peg.stock_document_type = 'Purchase Receipt' then peg.stock_document end)
	left join `tabPurchase Invoice` pi on pi.name = (
		case when peg.stock_document_type = 'Purchase Invoice' then peg.stock_document end)
"""

DN_ALWAYS = [
	"dni.name as _row",
	"null as _invoice",
	"so.name as _sales_order",
	"dn.customer as _customer",
	"peg.sales_person as _sales_person",
	"dni.item_code as _item",
	"itm.item_group as _item_group",
	"itm.brand as _brand",
	"peg.supplier as _supplier",
	"po.name as _purchase_order",
	"bat.name as _batch",
	"dni.stock_qty as _qty",
	"(dni.stock_qty * coalesce(soi.base_net_rate, dni.base_net_rate, 0)) as _revenue",
	"coalesce(dni.custom_noc_pegged_cost_rate, peg.effective_cost_rate, 0) as _pegged_rate",
	"coalesce(dni.custom_noc_is_addon, 0) as _is_addon",
	"dni.custom_noc_addon_parent_item as _addon_parent",
	"dn.currency as _currency",
	"1 as _uninvoiced",
]

DN_COGS = """
	(select abs(coalesce(sum(sle.stock_value_difference), 0))
	 from `tabStock Ledger Entry` sle
	 where sle.is_cancelled = 0
	   and sle.voucher_type = 'Delivery Note'
	   and sle.voucher_detail_no = dni.name
	) as cogs_actual
"""

# Sales Invoice fields have no direct equivalent on the delivery spine. These
# map across; anything else is reported as null rather than guessed.
DN_FIELD_MAP = {
	("Sales Invoice", "name"): "dn.name",
	("Sales Invoice", "posting_date"): "dn.posting_date",
	("Sales Invoice", "customer"): "dn.customer",
	("Sales Invoice", "customer_name"): "dn.customer_name",
	("Sales Invoice", "company"): "dn.company",
	("Sales Invoice", "currency"): "dn.currency",
	("Sales Invoice", "conversion_rate"): "dn.conversion_rate",
	("Sales Invoice", "territory"): "dn.territory",
	("Sales Invoice", "project"): "dn.project",
	("Sales Invoice", "status"): "dn.status",
	("Sales Invoice Item", "item_code"): "dni.item_code",
	("Sales Invoice Item", "item_name"): "dni.item_name",
	("Sales Invoice Item", "item_group"): "itm.item_group",
	("Sales Invoice Item", "brand"): "itm.brand",
	("Sales Invoice Item", "description"): "dni.description",
	("Sales Invoice Item", "qty"): "dni.qty",
	("Sales Invoice Item", "stock_qty"): "dni.stock_qty",
	("Sales Invoice Item", "uom"): "dni.uom",
	("Sales Invoice Item", "rate"): "coalesce(soi.rate, dni.rate)",
	("Sales Invoice Item", "amount"): "(dni.qty * coalesce(soi.rate, dni.rate, 0))",
	("Sales Invoice Item", "base_amount"): "(dni.stock_qty * coalesce(soi.base_net_rate, 0))",
	("Sales Invoice Item", "warehouse"): "dni.warehouse",
	("Sales Invoice Item", "batch_no"): "dni.batch_no",
	("Sales Invoice Item", "cost_center"): "dni.cost_center",
	("Sales Invoice Item", "custom_noc_pegged_cost_rate"): "dni.custom_noc_pegged_cost_rate",
	("Sales Invoice Item", "custom_noc_cogs_source"): "dni.custom_noc_cogs_source",
	("Sales Invoice Item", "custom_noc_is_addon"): "dni.custom_noc_is_addon",
	("Sales Invoice Item", "custom_noc_addon_parent_item"): "dni.custom_noc_addon_parent_item",
	("Sales Invoice Item", "custom_noc_manufacturer_part_no"): "dni.custom_noc_manufacturer_part_no",
	("Sales Invoice Item", "custom_noc_supplier_part_no"): "dni.custom_noc_supplier_part_no",
	("Sales Invoice Item", "customer_item_code"): "dni.customer_item_code",
	("Sales Invoice Item", "custom_noc_as_built_config"): "dni.custom_noc_as_built_config",
}

COGS_SUBQUERY = """
	(select abs(coalesce(sum(sle.stock_value_difference), 0))
	 from `tabStock Ledger Entry` sle
	 where sle.is_cancelled = 0
	   and ((sle.voucher_type = 'Delivery Note' and sle.voucher_detail_no = sii.dn_detail)
	     or (sle.voucher_type = 'Sales Invoice' and sle.voucher_detail_no = sii.name))
	) as cogs_actual
"""

ALWAYS = [
	"sii.name as _row",
	"si.name as _invoice",
	"so.name as _sales_order",
	"si.customer as _customer",
	"peg.sales_person as _sales_person",
	"sii.item_code as _item",
	"sii.item_group as _item_group",
	"sii.brand as _brand",
	"peg.supplier as _supplier",
	"po.name as _purchase_order",
	"bat.name as _batch",
	"sii.stock_qty as _qty",
	"sii.base_net_amount as _revenue",
	"coalesce(sii.custom_noc_pegged_cost_rate, peg.effective_cost_rate, 0) as _pegged_rate",
	"coalesce(sii.custom_noc_is_addon, 0) as _is_addon",
	"sii.custom_noc_addon_parent_item as _addon_parent",
	"si.currency as _currency",
]

GROUP_MAP = {
	"Sales Order": "_sales_order",
	"Customer": "_customer",
	"Sales Person": "_sales_person",
	"Brand": "_brand",
	"Item Group": "_item_group",
	"Item": "_item",
	"Supplier": "_supplier",
	"Purchase Order": "_purchase_order",
	"Batch": "_batch",
}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	profile = _get_profile(filters)
	selected = [r for r in profile.fields if r.is_visible]

	columns = _build_columns(selected, filters)
	rows = _fetch(selected, filters)
	if (filters.get("revenue_basis") or "Invoiced Only") != "Invoiced Only":
		rows += _fetch_uninvoiced(selected, filters)
	rows = _compute(rows, selected)

	group_by = filters.get("group_by") or profile.group_by
	if group_by and group_by != "None":
		rows = _aggregate(rows, GROUP_MAP.get(group_by), selected, group_by)
		columns = _build_columns(selected, filters, group_by=group_by)

	data = _project(rows, selected)
	return columns, data, None, _chart(rows, group_by), _summary(rows)


# ---------------------------------------------------------------------------
def _get_profile(filters):
	name = filters.get("report_profile")
	if not name:
		name = frappe.db.get_value("Order Costing Settings", None, "default_report_profile")
	if not name:
		name = frappe.db.get_value("Profitability Report Profile", {"is_default": 1}, "name")
	if not name:
		name = _bootstrap_profile()
	return frappe.get_doc("Profitability Report Profile", name)


def _bootstrap_profile():
	"""First run with no profile configured gets a sensible starter set that
	the implementor can then add to or strip down."""
	doc = frappe.new_doc("Profitability Report Profile")
	doc.profile_name = "Standard Order Profitability"
	doc.is_default = 1
	doc.group_by = "Sales Order"
	starter = [
		("Sales Order", "name"), ("Sales Order", "transaction_date"),
		("Order Cost Peg", "sales_person"), ("Sales Invoice", "customer"),
		("Sales Invoice Item", "item_code"), ("Sales Invoice Item", "brand"),
		("Sales Invoice Item", "stock_qty"), ("Sales Invoice Item", "rate"),
		("Purchase Order", "name"), ("Purchase Order", "supplier"),
		("Order Cost Peg", "purchase_rate"), ("Order Cost Peg", "effective_cost_rate"),
		("Batch", "name"),
		("Computed", "revenue"), ("Computed", "cogs_actual"),
		("Computed", "gross_profit"), ("Computed", "gross_margin_pct"),
	]
	for doctype, fieldname in starter:
		meta = FIELD_CATALOG[doctype][fieldname]
		doc.append("fields", {
			"source_document": doctype, "fieldname": fieldname,
			"label": meta.get("label"), "fieldtype": meta.get("fieldtype", "Data"),
			"options": meta.get("options"), "width": meta.get("width", 120), "is_visible": 1,
		})
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


# ---------------------------------------------------------------------------
def _build_columns(selected, filters, group_by=None):
	columns = []
	if group_by:
		columns.append({
			"label": _(group_by), "fieldname": "_group",
			"fieldtype": "Link" if group_by in ("Sales Order", "Customer", "Item", "Batch",
											   "Purchase Order", "Supplier", "Brand")
			else "Data",
			"options": {"Sales Order": "Sales Order", "Customer": "Customer", "Item": "Item",
						"Batch": "Batch", "Purchase Order": "Purchase Order",
						"Supplier": "Supplier", "Brand": "Brand"}.get(group_by),
			"width": 170,
		})
	for row in selected:
		if group_by and row.source_document != "Computed":
			continue
		columns.append({
			"label": _(row.label or row.fieldname),
			"fieldname": column_alias(row.source_document, row.fieldname),
			"fieldtype": row.fieldtype or "Data",
			"options": row.options,
			"width": row.width or 120,
		})
	return columns


def _fetch(selected, filters):
	select_parts = list(ALWAYS) + [COGS_SUBQUERY.strip()]
	for row in selected:
		if row.source_document == "Computed":
			continue
		expr = sql_expression(row.source_document, row.fieldname,
							  column_alias(row.source_document, row.fieldname))
		if expr:
			select_parts.append(expr)

	conditions, values = _conditions(filters)
	query = "select {0} {1} where {2}".format(
		",\n\t".join(select_parts), BASE_FROM, conditions
	)
	return frappe.db.sql(query, values, as_dict=True)


def _fetch_uninvoiced(selected, filters):
	"""Delivered lines with no submitted sales invoice against them."""
	from neotec_order_costing.api.field_catalog import FIELD_CATALOG

	select_parts = list(DN_ALWAYS) + [DN_COGS.strip()]
	for row in selected:
		if row.source_document == "Computed":
			continue
		alias = column_alias(row.source_document, row.fieldname)
		mapped = DN_FIELD_MAP.get((row.source_document, row.fieldname))
		if mapped:
			select_parts.append("{0} as `{1}`".format(mapped, alias))
			continue
		meta = FIELD_CATALOG.get(row.source_document, {}).get(row.fieldname)
		if not meta or not meta.get("sql"):
			continue
		if meta["sql"].startswith(("sii.", "si.")):
			select_parts.append("null as `{0}`".format(alias))
		else:
			select_parts.append("{0} as `{1}`".format(meta["sql"], alias))

	conditions, values = _dn_conditions(filters)
	query = "select {0} {1} where {2}".format(
		",\n\t".join(select_parts), DN_FROM, conditions
	)
	return frappe.db.sql(query, values, as_dict=True)


def _dn_conditions(filters):
	parts = [
		"dn.docstatus = 1",
		"""not exists (
			select 1 from `tabSales Invoice Item` x
			inner join `tabSales Invoice` xp on xp.name = x.parent
			where x.dn_detail = dni.name and xp.docstatus = 1
		)""",
	]
	values = {}
	mapping = {
		"company": "dn.company = %(company)s",
		"customer": "dn.customer = %(customer)s",
		"sales_order": "so.name = %(sales_order)s",
		"sales_person": "peg.sales_person = %(sales_person)s",
		"brand": "itm.brand = %(brand)s",
		"item_group": "itm.item_group = %(item_group)s",
		"supplier": "peg.supplier = %(supplier)s",
		"purchase_order": "po.name = %(purchase_order)s",
	}
	for key, clause in mapping.items():
		if filters.get(key):
			parts.append(clause)
			values[key] = filters.get(key)
	if filters.get("from_date"):
		parts.append("dn.posting_date >= %(from_date)s")
		values["from_date"] = filters.get("from_date")
	if filters.get("to_date"):
		parts.append("dn.posting_date <= %(to_date)s")
		values["to_date"] = filters.get("to_date")
	if filters.get("only_pegged"):
		parts.append("peg.name is not null")
	if filters.get("hide_addons"):
		parts.append("coalesce(dni.custom_noc_is_addon, 0) = 0")
	return " and ".join(parts), values


def _conditions(filters):
	settings = frappe.get_cached_doc("Order Costing Settings")
	parts = ["si.docstatus = 1"] if not settings.include_draft_documents else ["si.docstatus < 2"]
	values = {}

	mapping = {
		"company": "si.company = %(company)s",
		"customer": "si.customer = %(customer)s",
		"sales_order": "so.name = %(sales_order)s",
		"sales_person": "peg.sales_person = %(sales_person)s",
		"brand": "sii.brand = %(brand)s",
		"item_group": "sii.item_group = %(item_group)s",
		"supplier": "peg.supplier = %(supplier)s",
		"purchase_order": "po.name = %(purchase_order)s",
	}
	for key, clause in mapping.items():
		if filters.get(key):
			parts.append(clause)
			values[key] = filters.get(key)

	if filters.get("from_date"):
		parts.append("si.posting_date >= %(from_date)s")
		values["from_date"] = filters.get("from_date")
	if filters.get("to_date"):
		parts.append("si.posting_date <= %(to_date)s")
		values["to_date"] = filters.get("to_date")
	if filters.get("only_pegged"):
		parts.append("peg.name is not null")
	if filters.get("hide_addons"):
		parts.append("coalesce(sii.custom_noc_is_addon, 0) = 0")

	return " and ".join(parts), values


# ---------------------------------------------------------------------------
def _compute(rows, selected):
	for r in rows:
		qty = flt(r.get("_qty"))
		revenue = flt(r.get("_revenue"))
		cogs_actual = flt(r.get("cogs_actual"))
		cogs_pegged = flt(r.get("_pegged_rate")) * qty

		r["revenue_status"] = ("Delivered, not invoiced" if r.get("_uninvoiced")
							   else "Invoiced")
		r["revenue"] = revenue
		r["cogs_actual"] = cogs_actual
		r["cogs_pegged"] = cogs_pegged
		r["cogs_variance"] = cogs_pegged - cogs_actual
		r["gross_profit"] = revenue - (cogs_pegged or cogs_actual)
		r["gross_margin_pct"] = (r["gross_profit"] / revenue * 100) if revenue else 0
		r["unit_cost"] = ((cogs_pegged or cogs_actual) / qty) if qty else 0
		r["unit_margin"] = (r["gross_profit"] / qty) if qty else 0
		r["markup_pct"] = (
			(r["unit_margin"] / r["unit_cost"] * 100) if r["unit_cost"] else 0
		)
	return rows


def _aggregate(rows, key, selected, group_by):
	buckets = {}
	for r in rows:
		k = r.get(key) or _("Unassigned")
		b = buckets.setdefault(k, {"_group": k, "_qty": 0.0})
		b["_qty"] += flt(r.get("_qty"))
		for metric in COMPUTED:
			if metric == "revenue_status":
				continue
			b[metric] = flt(b.get(metric)) + flt(r.get(metric))
	for b in buckets.values():
		b["gross_margin_pct"] = (b["gross_profit"] / b["revenue"] * 100) if b["revenue"] else 0
		b["unit_cost"] = (b["cogs_actual"] / b["_qty"]) if b["_qty"] else 0
		b["unit_margin"] = (b["gross_profit"] / b["_qty"]) if b["_qty"] else 0
		b["markup_pct"] = (b["unit_margin"] / b["unit_cost"] * 100) if b["unit_cost"] else 0
	return sorted(buckets.values(), key=lambda x: -flt(x.get("gross_profit")))


def _project(rows, selected):
	out = []
	for r in rows:
		row = {}
		if "_group" in r:
			row["_group"] = r["_group"]
		for f in selected:
			alias = column_alias(f.source_document, f.fieldname)
			if f.source_document == "Computed":
				row[alias] = r.get(f.fieldname)
			else:
				row[alias] = r.get(alias)
		out.append(row)
	return out


def _chart(rows, group_by):
	if not rows or not group_by or group_by == "None":
		return None
	top = rows[:10]
	return {
		"data": {
			"labels": [str(r.get("_group")) for r in top],
			"datasets": [
				{"name": _("Revenue"), "values": [flt(r.get("revenue")) for r in top]},
				{"name": _("Gross Profit"), "values": [flt(r.get("gross_profit")) for r in top]},
			],
		},
		"type": "bar",
		"colors": ["#7F77DD", "#1D9E75"],
	}


def _summary(rows):
	revenue = sum(flt(r.get("revenue")) for r in rows)
	cogs = sum(flt(r.get("cogs_actual")) for r in rows)
	profit = sum(flt(r.get("gross_profit")) for r in rows)
	return [
		{"label": _("Revenue"), "value": revenue, "datatype": "Currency", "indicator": "Blue"},
		{"label": _("COGS"), "value": cogs, "datatype": "Currency", "indicator": "Orange"},
		{"label": _("Gross Profit"), "value": profit, "datatype": "Currency",
		 "indicator": "Green" if profit >= 0 else "Red"},
		{"label": _("Margin %"), "value": (profit / revenue * 100) if revenue else 0,
		 "datatype": "Percent", "indicator": "Green" if profit >= 0 else "Red"},
	]
