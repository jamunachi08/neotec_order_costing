"""Part number identity on transaction rows.

Manufacturer and supplier part numbers are stamped onto each row at validate
time so print formats read them directly rather than doing a lookup per line.
Customer part number is native platform (`customer_item_code`) and is left
alone.
"""

import frappe

from neotec_order_costing.api.specs import get_part_numbers
from neotec_order_costing.neotec_order_costing.doctype.order_costing_settings.order_costing_settings import (
	get_settings,
)

SUPPLIER_DOCS = ("Purchase Order", "Purchase Receipt", "Purchase Invoice")


def stamp_part_numbers(doc, method=None):
	if not get_settings().get("enable_specifications"):
		return

	supplier = doc.get("supplier") if doc.doctype in SUPPLIER_DOCS else None
	customer = doc.get("customer")

	for item in doc.get("items", []):
		if not item.get("item_code"):
			continue
		if item.get("custom_noc_manufacturer_part_no") and item.get("custom_noc_supplier_part_no"):
			continue
		parts = get_part_numbers(item.item_code, customer=customer, supplier=supplier)
		if hasattr(item, "custom_noc_manufacturer_part_no"):
			item.custom_noc_manufacturer_part_no = parts.get("manufacturer_part_no")
		if hasattr(item, "custom_noc_supplier_part_no"):
			item.custom_noc_supplier_part_no = parts.get("supplier_part_no")


def resolve_supplier(item_code, company, settings=None):
	"""Different part numbers of the same brand often come from different
	distributors, so Item Supplier is checked before the company default."""
	settings = settings or get_settings()
	order = settings.get("supplier_resolution") or "Item Supplier then Item Default"

	item_supplier = frappe.db.get_value(
		"Item Supplier", {"parent": item_code, "parenttype": "Item"}, "supplier"
	)
	item_default = frappe.db.get_value(
		"Item Default", {"parent": item_code, "company": company}, "default_supplier"
	)

	if order == "Item Supplier then Item Default":
		return item_supplier or item_default
	return item_default or item_supplier
