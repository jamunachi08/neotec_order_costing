"""Cross-order demand consolidation.

Three sales orders each needing HP laptops should not produce three purchase
orders at three separate prices. This module pulls open Material Request lines
across every sales order, groups them by brand, and raises one bulk purchase
order per group — which is where the vendor discount comes from.

The cost pegs stay intact. Several pegs then share one purchase order line, and
`allocation.py` divides the receipt back out across them.
"""

import frappe
from frappe.utils import add_days, flt, getdate, nowdate

from neotec_order_costing.api.parts import resolve_supplier
from neotec_order_costing.neotec_order_costing.doctype.order_costing_settings.order_costing_settings import (
	get_settings,
)

PATH_DOCTYPE = {
	"Direct Purchase Order": "Purchase Order",
	"Supplier Quotation then Purchase Order": "Supplier Quotation",
	"Request for Quotation then Purchase Order": "Request for Quotation",
}


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

def group_key(row, group_by, company):
	brand = row.get("brand")
	item_group = row.get("item_group")
	supplier = row.get("supplier") or resolve_supplier(row["item_code"], company)

	if group_by == "Brand":
		return brand or "NO-BRAND", brand, supplier
	if group_by == "Supplier":
		return supplier or "NO-SUPPLIER", brand, supplier
	if group_by == "Item Group":
		return item_group or "NO-GROUP", brand, supplier
	return "{0}::{1}".format(brand or "NO-BRAND", supplier or "NO-SUPPLIER"), brand, supplier


# ---------------------------------------------------------------------------
# Demand
# ---------------------------------------------------------------------------

def fetch_demand(company, brand=None, item_group=None, supplier=None,
				 from_date=None, to_date=None, warehouse=None,
				 include_unlinked_requests=0):
	"""Open Material Request lines that still need a purchase order.

	`ordered_qty` on Material Request Item is what the platform already tracks,
	so pending demand is simply qty minus ordered_qty.
	"""
	conditions = [
		"mr.docstatus = 1",
		"mr.material_request_type = 'Purchase'",
		"mr.status not in ('Stopped', 'Cancelled')",
		"mr.company = %(company)s",
		"(mri.qty - ifnull(mri.ordered_qty, 0)) > 0.001",
	]
	values = {"company": company}

	if brand:
		conditions.append("itm.brand = %(brand)s")
		values["brand"] = brand
	if item_group:
		conditions.append("itm.item_group = %(item_group)s")
		values["item_group"] = item_group
	if warehouse:
		conditions.append("mri.warehouse = %(warehouse)s")
		values["warehouse"] = warehouse
	if from_date:
		conditions.append("mri.schedule_date >= %(from_date)s")
		values["from_date"] = from_date
	if to_date:
		conditions.append("mri.schedule_date <= %(to_date)s")
		values["to_date"] = to_date
	if not int(include_unlinked_requests or 0):
		conditions.append("mri.sales_order is not null and mri.sales_order != ''")

	rows = frappe.db.sql(
		"""
		select
			mri.name as material_request_item,
			mri.parent as material_request,
			mri.item_code, mri.item_name, mri.uom, mri.warehouse,
			mri.schedule_date as required_by,
			mri.sales_order,
			(mri.qty - ifnull(mri.ordered_qty, 0)) as qty_pending,
			itm.brand, itm.item_group,
			so.customer
		from `tabMaterial Request Item` mri
		inner join `tabMaterial Request` mr on mr.name = mri.parent
		inner join `tabItem` itm on itm.name = mri.item_code
		left join `tabSales Order` so on so.name = mri.sales_order
		where {conditions}
		order by mri.schedule_date asc, mri.creation asc
		""".format(conditions=" and ".join(conditions)),
		values, as_dict=True,
	)

	for row in rows:
		row["qty_to_order"] = flt(row["qty_pending"])
		row["order_cost_peg"] = _peg_for(row)
		if supplier:
			row["supplier"] = supplier
	return rows


def _peg_for(row):
	if not row.get("sales_order"):
		return None
	return frappe.db.get_value(
		"Order Cost Peg",
		{
			"sales_order": row["sales_order"],
			"item_code": row["item_code"],
			"docstatus": 1,
			"status": ["not in", ["Closed", "Cancelled"]],
		},
		"name", order_by="qty_open desc",
	)


@frappe.whitelist()
def get_demand(company, **kwargs):
	frappe.only_for(["System Manager", "Purchase Manager", "Purchase User"])
	return fetch_demand(company, **kwargs)


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def resolve_path(company, brand=None, item_group=None, supplier=None, amount=0):
	settings = get_settings()
	if not settings.get("enable_procurement_policy"):
		return "Direct Purchase Order", 1

	rows = sorted(
		[r for r in settings.get("procurement_policies", []) if r.enabled],
		key=lambda r: (r.priority or 999, r.idx),
	)
	for row in rows:
		if row.company and row.company != company:
			continue
		if row.brand and row.brand != brand:
			continue
		if row.item_group and row.item_group != item_group:
			continue
		if row.supplier and row.supplier != supplier:
			continue
		if row.min_amount and flt(amount) < flt(row.min_amount):
			continue
		return row.required_path, (row.min_quotations or 1)

	return settings.get("default_procurement_path") or "Direct Purchase Order", 1


@frappe.whitelist()
def preview_path(company, brand=None, item_group=None, supplier=None, amount=0):
	path, minq = resolve_path(company, brand, item_group, supplier, amount)
	return {"path": path, "doctype": PATH_DOCTYPE[path], "min_quotations": minq}


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def build_summary(rows, group_by, company):
	buckets = {}
	for row in rows:
		if not row.get("select_row", 1) or flt(row.get("qty_to_order")) <= 0:
			continue
		key, brand, supplier = group_key(row, group_by, company)
		bucket_key = (key, row["item_code"])
		b = buckets.setdefault(bucket_key, {
			"brand": brand, "item_code": row["item_code"], "uom": row.get("uom"),
			"supplier": supplier, "total_qty": 0.0, "orders": set(),
			"earliest_required_by": None,
		})
		b["total_qty"] += flt(row["qty_to_order"])
		if row.get("sales_order"):
			b["orders"].add(row["sales_order"])
		req = row.get("required_by")
		if req and (not b["earliest_required_by"] or getdate(req) < getdate(b["earliest_required_by"])):
			b["earliest_required_by"] = req

	summary = []
	for b in buckets.values():
		last_rate = _last_purchase_rate(b["item_code"], b["supplier"])
		summary.append({
			"brand": b["brand"], "item_code": b["item_code"], "uom": b["uom"],
			"supplier": b["supplier"], "total_qty": b["total_qty"],
			"order_count": len(b["orders"]),
			"last_purchase_rate": last_rate,
			"target_rate": last_rate,
			"expected_saving": 0.0,
			"earliest_required_by": b["earliest_required_by"],
		})
	return sorted(summary, key=lambda r: (-flt(r["total_qty"]), r["item_code"]))


def _last_purchase_rate(item_code, supplier=None):
	filters = {"item_code": item_code, "docstatus": 1}
	if supplier:
		parents = frappe.get_all(
			"Purchase Order", filters={"supplier": supplier, "docstatus": 1}, pluck="name"
		)
		if parents:
			filters["parent"] = ["in", parents]
	row = frappe.get_all(
		"Purchase Order Item", filters=filters, fields=["base_rate", "conversion_factor"],
		order_by="creation desc", limit=1,
	)
	if not row:
		return flt(frappe.db.get_value("Item", item_code, "last_purchase_rate"))
	return flt(row[0].base_rate) / (flt(row[0].conversion_factor) or 1)


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------

def create_documents(doc):
	"""One document per group, carrying every contributing sales order line."""
	settings = get_settings()
	company = doc.company
	group_by = doc.group_by

	groups = {}
	for row in doc.items:
		if not row.select_row or flt(row.qty_to_order) <= 0:
			continue
		key, brand, supplier = group_key(row.as_dict(), group_by, company)
		summary_row = next(
			(s for s in doc.summary
			 if s.item_code == row.item_code and (s.brand or "") == (brand or "")), None
		)
		if summary_row and summary_row.supplier:
			supplier = summary_row.supplier
		groups.setdefault((key, supplier), {"brand": brand, "supplier": supplier, "rows": []})
		groups[(key, supplier)]["rows"].append((row, summary_row))

	created = []
	for (key, supplier), group in groups.items():
		amount = sum(
			flt(r.qty_to_order) * flt(s.target_rate if s else 0)
			for r, s in group["rows"]
		)
		path, _minq = resolve_path(company, group["brand"], None, supplier, amount)
		target = PATH_DOCTYPE[path]

		if target in ("Purchase Order", "Supplier Quotation") and not supplier:
			frappe.msgprint(
				"No supplier resolved for group {0}. Set one on the summary row.".format(key),
				indicator="orange",
			)
			continue

		builder = {
			"Purchase Order": _build_purchase_order,
			"Supplier Quotation": _build_supplier_quotation,
			"Request for Quotation": _build_rfq,
		}[target]
		created_doc = builder(doc, group, supplier, key)
		if not created_doc:
			continue

		created.append({"doctype": target, "name": created_doc.name,
						"group": key, "path": path})
		_link_pegs(doc, group, created_doc, target, settings)

	return created


def _line_values(row, summary_row):
	return {
		"item_code": row.item_code,
		"qty": flt(row.qty_to_order),
		"uom": row.uom,
		"warehouse": row.warehouse,
		"schedule_date": row.required_by or add_days(nowdate(), 7),
		"material_request": row.material_request,
		"material_request_item": row.material_request_item,
		"sales_order": row.sales_order,
		"sales_order_item": row.sales_order_item,
		"rate": flt(summary_row.target_rate) if summary_row else 0,
	}


def _merge_lines(group):
	"""Consolidation means one purchase order line per item, not one per
	sales order. The peg allocation is what preserves order-wise costing."""
	merged = {}
	for row, summary_row in group["rows"]:
		key = (row.item_code, row.uom, row.warehouse)
		if key not in merged:
			merged[key] = _line_values(row, summary_row)
			merged[key]["_sources"] = []
		else:
			merged[key]["qty"] += flt(row.qty_to_order)
			existing = merged[key]["schedule_date"]
			candidate = row.required_by
			if candidate and existing and getdate(candidate) < getdate(existing):
				merged[key]["schedule_date"] = candidate
			# a merged line can only carry one link, so drop the specific ones
			merged[key]["sales_order"] = None
			merged[key]["sales_order_item"] = None
			merged[key]["material_request_item"] = None
		merged[key]["_sources"].append(row)
	return merged


def _build_purchase_order(doc, group, supplier, key):
	po = frappe.new_doc("Purchase Order")
	po.supplier = supplier
	po.company = doc.company
	po.transaction_date = doc.consolidation_date or nowdate()
	po.custom_noc_split_brand = group["brand"]
	for values in _merge_lines(group).values():
		sources = values.pop("_sources")
		po.append("items", values)
		values["_sources"] = sources
	po.schedule_date = min(
		[i.schedule_date for i in po.items if i.schedule_date] or [add_days(nowdate(), 7)]
	)
	po.flags.ignore_permissions = True
	po.insert(ignore_permissions=True)
	return po


def _build_supplier_quotation(doc, group, supplier, key):
	sq = frappe.new_doc("Supplier Quotation")
	sq.supplier = supplier
	sq.company = doc.company
	sq.transaction_date = doc.consolidation_date or nowdate()
	for values in _merge_lines(group).values():
		values.pop("_sources", None)
		values.pop("sales_order", None)
		values.pop("sales_order_item", None)
		sq.append("items", values)
	sq.flags.ignore_permissions = True
	sq.insert(ignore_permissions=True)
	return sq


def _build_rfq(doc, group, supplier, key):
	rfq = frappe.new_doc("Request for Quotation")
	rfq.company = doc.company
	rfq.transaction_date = doc.consolidation_date or nowdate()
	rfq.message_for_supplier = "Please quote for the consolidated quantity below."
	suppliers = _candidate_suppliers(group)
	if not suppliers:
		frappe.msgprint(
			"No suppliers available for RFQ group {0}.".format(key), indicator="orange"
		)
		return None
	for s in suppliers:
		rfq.append("suppliers", {"supplier": s})
	for values in _merge_lines(group).values():
		values.pop("_sources", None)
		values.pop("sales_order", None)
		values.pop("sales_order_item", None)
		values.pop("rate", None)
		rfq.append("items", values)
	rfq.flags.ignore_permissions = True
	rfq.insert(ignore_permissions=True)
	return rfq


def _candidate_suppliers(group):
	suppliers = []
	for row, _s in group["rows"]:
		for s in frappe.get_all(
			"Item Supplier", filters={"parent": row.item_code, "parenttype": "Item"},
			pluck="supplier",
		):
			if s not in suppliers:
				suppliers.append(s)
	if group.get("supplier") and group["supplier"] not in suppliers:
		suppliers.insert(0, group["supplier"])
	return suppliers[:5]


def _link_pegs(doc, group, created_doc, target, settings):
	"""Every contributing peg records its share of the consolidated line."""
	from neotec_order_costing.api.peg import save_peg

	merged = _merge_lines(group)
	for values in merged.values():
		sources = values.get("_sources") or []
		line = next(
			(i for i in created_doc.items if i.item_code == values["item_code"]), None
		)
		consolidated = len({r.sales_order for r in sources if r.sales_order}) > 1

		for row in sources:
			if not row.order_cost_peg:
				continue
			peg = frappe.get_doc("Order Cost Peg", row.order_cost_peg)
			peg.procurement_consolidation = doc.name
			peg.is_consolidated = 1 if consolidated else 0
			peg.qty_allocated = flt(row.qty_to_order)

			if target == "Purchase Order":
				peg.purchase_order = created_doc.name
				peg.purchase_order_item = line.name if line else None
				peg.supplier = created_doc.supplier
				peg.purchase_rate = flt(line.base_rate or line.rate) if line else 0
				peg.status = "Ordered"
			else:
				peg.procurement_document_type = target
				peg.procurement_document = created_doc.name
				peg.status = "Quoting"
			peg.material_request = row.material_request
			save_peg(peg)


# ---------------------------------------------------------------------------
# Quotation feedback
# ---------------------------------------------------------------------------

def capture_quoted_rates(doc, method=None):
	"""Supplier Quotation submit writes the expected cost onto every peg it
	covers, so sales can see margin before the purchase order exists."""
	if not get_settings().enable_order_wise_cogs:
		return
	from neotec_order_costing.api.peg import save_peg

	for item in doc.items:
		pegs = frappe.get_all(
			"Order Cost Peg",
			filters={
				"procurement_document_type": "Supplier Quotation",
				"procurement_document": doc.name,
				"item_code": item.item_code,
				"docstatus": 1,
			},
			pluck="name",
		)
		rate = flt(item.base_rate) / (flt(item.conversion_factor) or 1)
		for name in pegs:
			peg = frappe.get_doc("Order Cost Peg", name)
			peg.quoted_rate = rate
			peg.expected_margin = flt(peg.selling_rate) - rate
			peg.status = "Quoted"
			save_peg(peg)
