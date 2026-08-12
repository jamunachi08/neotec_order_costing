"""Brand-wise procurement split.

A single Sales Order can carry HP, Dell and Lenovo lines. Procurement has to
go to three different vendors, so this module fans the order out into one
Material Request and one Purchase Order per split group.
"""

import frappe
from frappe.utils import flt, nowdate

from neotec_order_costing.neotec_order_costing.doctype.order_costing_settings.order_costing_settings import (
	get_settings,
)


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

def _default_supplier(item_code, company):
	from neotec_order_costing.api.parts import resolve_supplier

	return resolve_supplier(item_code, company)


def split_key(item_code, company, settings=None):
	settings = settings or get_settings()
	basis = settings.split_basis or "Brand"
	brand, item_group = frappe.get_cached_value("Item", item_code, ["brand", "item_group"])
	supplier = _default_supplier(item_code, company)

	if basis == "Brand":
		return brand or "NO-BRAND", {"brand": brand, "supplier": supplier}
	if basis == "Supplier":
		return supplier or "NO-SUPPLIER", {"brand": brand, "supplier": supplier}
	if basis == "Brand and Supplier":
		return "{0}::{1}".format(brand or "NO-BRAND", supplier or "NO-SUPPLIER"), {
			"brand": brand, "supplier": supplier
		}
	if basis == "Item Group":
		return item_group or "NO-GROUP", {"brand": brand, "supplier": supplier}
	return supplier or "NO-SUPPLIER", {"brand": brand, "supplier": supplier}


@frappe.whitelist()
def preview_split(sales_order):
	"""Feeds the confirmation dialog on the Sales Order so the user sees
	exactly how many documents will be created before anything is written."""
	settings = get_settings()
	so = frappe.get_doc("Sales Order", sales_order)
	groups = {}
	for item in so.items:
		if not frappe.get_cached_value("Item", item.item_code, "is_stock_item"):
			continue
		key, meta = split_key(item.item_code, so.company, settings)
		g = groups.setdefault(key, {
			"key": key,
			"brand": meta["brand"],
			"supplier": meta["supplier"],
			"supplier_name": frappe.db.get_value("Supplier", meta["supplier"], "supplier_name")
			if meta["supplier"] else None,
			"items": [],
			"total_qty": 0.0,
		})
		g["items"].append({
			"item_code": item.item_code,
			"item_name": item.item_name,
			"qty": flt(item.qty),
			"uom": item.uom,
			"rate": flt(item.rate),
			"so_detail": item.name,
			"warehouse": item.warehouse,
			"delivery_date": str(item.delivery_date or so.delivery_date or nowdate()),
		})
		g["total_qty"] += flt(item.qty)

	return {
		"enabled": bool(settings.enable_procurement_split),
		"basis": settings.split_basis,
		"target": settings.split_target,
		"groups": list(groups.values()),
	}


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------

@frappe.whitelist()
def make_split_material_requests(sales_order, selected_keys=None):
	frappe.only_for(["System Manager", "Stock Manager", "Purchase Manager", "Purchase User"])
	settings = get_settings()
	if not settings.enable_procurement_split:
		frappe.throw("Brand-wise procurement split is disabled in Order Costing Settings.")

	selected_keys = frappe.parse_json(selected_keys) if isinstance(selected_keys, str) else selected_keys
	data = preview_split(sales_order)
	so = frappe.get_doc("Sales Order", sales_order)
	created = []

	for group in data["groups"]:
		if selected_keys and group["key"] not in selected_keys:
			continue
		mr = frappe.new_doc("Material Request")
		mr.material_request_type = "Purchase"
		mr.company = so.company
		mr.transaction_date = nowdate()
		mr.schedule_date = so.delivery_date or nowdate()
		for row in group["items"]:
			mr.append("items", {
				"item_code": row["item_code"],
				"qty": row["qty"],
				"uom": row["uom"],
				"schedule_date": row["delivery_date"],
				"warehouse": row["warehouse"],
				"sales_order": sales_order if settings.carry_sales_order_link else None,
				"custom_noc_split_group": group["key"],
			})
		mr.flags.ignore_permissions = True
		mr.insert(ignore_permissions=True)
		created.append({"name": mr.name, "key": group["key"], "brand": group["brand"]})

		for row in group["items"]:
			frappe.db.set_value(
				"Sales Order Item", row["so_detail"],
				"custom_noc_split_group", group["key"], update_modified=False
			)

	return created


@frappe.whitelist()
def make_split_purchase_orders(sales_order, selected_keys=None):
	frappe.only_for(["System Manager", "Purchase Manager", "Purchase User"])
	settings = get_settings()
	if not settings.enable_procurement_split:
		frappe.throw("Brand-wise procurement split is disabled in Order Costing Settings.")
	if settings.require_material_request:
		frappe.throw(
			"Order Costing Settings require a Material Request before a Purchase Order. "
			"Use Create > Material Requests by Brand first."
		)

	selected_keys = frappe.parse_json(selected_keys) if isinstance(selected_keys, str) else selected_keys
	data = preview_split(sales_order)
	so = frappe.get_doc("Sales Order", sales_order)
	created = []

	for group in data["groups"]:
		if selected_keys and group["key"] not in selected_keys:
			continue
		if not group["supplier"]:
			frappe.msgprint(
				"No default supplier set for group {0}. Skipped.".format(group["key"]),
				indicator="orange",
			)
			continue

		po = frappe.new_doc("Purchase Order")
		po.supplier = group["supplier"]
		po.company = so.company
		po.transaction_date = nowdate()
		po.schedule_date = so.delivery_date or nowdate()
		po.custom_noc_split_brand = group["brand"]
		po.custom_noc_split_from_sales_order = sales_order
		for row in group["items"]:
			po.append("items", {
				"item_code": row["item_code"],
				"qty": row["qty"],
				"uom": row["uom"],
				"schedule_date": row["delivery_date"],
				"warehouse": row["warehouse"],
				"sales_order": sales_order if settings.carry_sales_order_link else None,
				"sales_order_item": row["so_detail"] if settings.carry_sales_order_link else None,
			})
		po.flags.ignore_permissions = True
		po.insert(ignore_permissions=True)
		created.append({"name": po.name, "key": group["key"], "brand": group["brand"],
						"supplier": group["supplier"]})

	return created


# ---------------------------------------------------------------------------
# Guard rail
# ---------------------------------------------------------------------------

def validate_split_grouping(doc, method=None):
	settings = get_settings()
	if not settings.enable_procurement_split or not settings.block_mixed_brand_po:
		return
	if doc.doctype == "Material Request" and settings.split_target == "Purchase Order Only":
		return
	if doc.doctype == "Purchase Order" and settings.split_target == "Material Request Only":
		return

	keys = set()
	for item in doc.items:
		key, _meta = split_key(item.item_code, doc.company, settings)
		keys.add(key)
	if len(keys) > 1:
		frappe.throw(
			"This {0} mixes {1} procurement groups ({2}). Order Costing Settings require "
			"one document per group.".format(doc.doctype, len(keys), ", ".join(sorted(keys)))
		)


# ---------------------------------------------------------------------------
# Split from a Material Request
#
# The salesman converts the sales order as-is: one material request carrying
# every brand. Procurement then splits from there, which is where the brand and
# supplier knowledge actually lives.
# ---------------------------------------------------------------------------

@frappe.whitelist()
def preview_material_request_split(material_request):
	from neotec_order_costing.api.consolidation import PATH_DOCTYPE, resolve_path

	settings = get_settings()
	mr = frappe.get_doc("Material Request", material_request)
	groups = {}

	for item in mr.items:
		pending = flt(item.qty) - flt(item.ordered_qty)
		if pending <= 0.0001:
			continue
		key, meta = split_key(item.item_code, mr.company, settings)
		g = groups.setdefault(key, {
			"key": key, "brand": meta["brand"], "supplier": meta["supplier"],
			"supplier_name": frappe.db.get_value("Supplier", meta["supplier"], "supplier_name")
			if meta["supplier"] else None,
			"items": [], "total_qty": 0.0, "amount": 0.0,
		})
		rate = flt(frappe.db.get_value("Item", item.item_code, "last_purchase_rate"))
		g["items"].append({
			"item_code": item.item_code, "item_name": item.item_name,
			"qty": pending, "uom": item.uom, "warehouse": item.warehouse,
			"schedule_date": str(item.schedule_date or mr.schedule_date or nowdate()),
			"material_request_item": item.name,
			"sales_order": item.get("sales_order"),
			"rate": rate,
		})
		g["total_qty"] += pending
		g["amount"] += pending * rate

	for g in groups.values():
		path, minq = resolve_path(mr.company, g["brand"], None, g["supplier"], g["amount"])
		g["path"] = path
		g["target_doctype"] = PATH_DOCTYPE[path]
		g["min_quotations"] = minq

	return {
		"enabled": bool(settings.enable_procurement_split),
		"basis": settings.split_basis,
		"policy_on": bool(settings.get("enable_procurement_policy")),
		"groups": list(groups.values()),
	}


@frappe.whitelist()
def make_documents_from_material_request(material_request, selected_keys=None,
										 override_doctype=None):
	"""Creates one Purchase Order, Supplier Quotation or Request for Quotation
	per brand group, as the policy dictates."""
	frappe.only_for(["System Manager", "Purchase Manager", "Purchase User"])
	selected_keys = (frappe.parse_json(selected_keys)
					 if isinstance(selected_keys, str) else selected_keys)

	data = preview_material_request_split(material_request)
	mr = frappe.get_doc("Material Request", material_request)
	created = []

	for group in data["groups"]:
		if selected_keys and group["key"] not in selected_keys:
			continue
		target = override_doctype or group["target_doctype"]

		if target in ("Purchase Order", "Supplier Quotation") and not group["supplier"]:
			frappe.msgprint(
				"No supplier set for group {0}. Skipped.".format(group["key"]),
				indicator="orange",
			)
			continue

		doc = frappe.new_doc(target)
		doc.company = mr.company
		doc.transaction_date = nowdate()
		if target == "Request for Quotation":
			doc.message_for_supplier = "Please quote for the quantities below."
			for supplier in _rfq_suppliers(group):
				doc.append("suppliers", {"supplier": supplier})
		else:
			doc.supplier = group["supplier"]
		if target == "Purchase Order":
			doc.custom_noc_split_brand = group["brand"]
			doc.schedule_date = mr.schedule_date or nowdate()

		for row in group["items"]:
			line = {
				"item_code": row["item_code"], "qty": row["qty"], "uom": row["uom"],
				"warehouse": row["warehouse"], "schedule_date": row["schedule_date"],
				"material_request": material_request,
				"material_request_item": row["material_request_item"],
			}
			if target != "Request for Quotation":
				line["rate"] = row["rate"]
			if target == "Purchase Order" and settings_carry_link():
				line["sales_order"] = row.get("sales_order")
			doc.append("items", line)

		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		created.append({"doctype": target, "name": doc.name, "key": group["key"],
						"brand": group["brand"]})

	return created


def settings_carry_link():
	return bool(get_settings().carry_sales_order_link)


def _rfq_suppliers(group):
	suppliers = []
	for row in group["items"]:
		for s in frappe.get_all(
			"Item Supplier", filters={"parent": row["item_code"], "parenttype": "Item"},
			pluck="supplier",
		):
			if s not in suppliers:
				suppliers.append(s)
	if group.get("supplier") and group["supplier"] not in suppliers:
		suppliers.insert(0, group["supplier"])
	return suppliers[:5]
