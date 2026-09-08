"""Configurable batch identity.

The implementor decides what a batch number should look like by stacking
components in Order Costing Settings. A composition of

    Static Text "BT" | Item Code | Sales Order (last 4) | Serial Counter (3)

produces BT-HPLAP14-0142-001 for the first receipt against SAL-ORD-2026-00142.
"""

import re

import frappe
from frappe.utils import cint, cstr, flt, getdate

SEP_DEFAULT = "-"


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def _clean(value, uppercase=True, max_length=0):
	value = re.sub(r"[^A-Za-z0-9]", "", cstr(value))
	if uppercase:
		value = value.upper()
	if max_length and len(value) > max_length:
		value = value[-max_length:]
	return value


def _component_value(component, ctx, row):
	posting = getdate(ctx.get("posting_date")) if ctx.get("posting_date") else None

	mapping = {
		"Static Text": row.get("static_value"),
		"Item Code": ctx.get("item_code"),
		"Item Group": ctx.get("item_group"),
		"Brand": ctx.get("brand"),
		"Manufacturer Part No": ctx.get("manufacturer_part_no"),
		"Supplier Part No": ctx.get("supplier_part_no"),
		"Customer Part No": ctx.get("customer_part_no"),
		"Supplier": ctx.get("supplier"),
		"Customer": ctx.get("customer"),
		"Sales Order": ctx.get("sales_order"),
		"Sales Order (last 4)": _last(ctx.get("sales_order"), 4),
		"Purchase Order": ctx.get("purchase_order"),
		"Purchase Order (last 4)": _last(ctx.get("purchase_order"), 4),
		"Stock Document": ctx.get("stock_document"),
		"Stock Document (last 4)": _last(ctx.get("stock_document"), 4),
		"Sales Person": ctx.get("sales_person"),
		"Fiscal Year": ctx.get("fiscal_year"),
		"Purchase Rate": cint(flt(ctx.get("purchase_rate"))) if ctx.get("purchase_rate") else None,
		"Posting Date (YYYYMMDD)": posting.strftime("%Y%m%d") if posting else None,
		"Posting Date (YYMM)": posting.strftime("%y%m") if posting else None,
		"Posting Date (DDMMYY)": posting.strftime("%d%m%y") if posting else None,
	}
	return mapping.get(component)


def _last(value, n):
	digits = re.sub(r"[^A-Za-z0-9]", "", cstr(value))
	return digits[-n:] if digits else None


def build_batch_id(ctx, settings=None, dry_run=False):
	"""ctx carries whatever the calling document knows. Missing components are
	silently skipped so a partially populated context still yields a batch."""
	settings = settings or frappe.get_cached_doc("Order Costing Settings")
	sep = settings.batch_separator or SEP_DEFAULT

	parts = []
	counter_row = None
	for row in sorted(settings.batch_naming_components, key=lambda r: r.idx or 0):
		if row.component == "Serial Counter":
			counter_row = row
			parts.append(None)  # placeholder, resolved after the prefix is known
			continue
		value = _component_value(row.component, ctx, row.as_dict() if hasattr(row, "as_dict") else row)
		if value in (None, ""):
			continue
		parts.append(_clean(value, uppercase=cint(row.uppercase), max_length=cint(row.max_length)))

	if counter_row is None:
		batch_id = sep.join([p for p in parts if p])
		return _ensure_unique(batch_id, sep, dry_run)

	idx = parts.index(None)
	prefix = sep.join([p for p in parts[:idx] if p])
	suffix = sep.join([p for p in parts[idx + 1:] if p])
	width = cint(counter_row.counter_length) or 3

	if dry_run:
		counter = 1
	else:
		counter = _next_counter(prefix, sep, width)

	number = cstr(counter).zfill(width)
	batch_id = sep.join([p for p in (prefix, number, suffix) if p])
	return batch_id


def _next_counter(prefix, sep, width):
	pattern = "{0}{1}%".format(prefix, sep) if prefix else "%"
	existing = frappe.db.sql(
		"select name from `tabBatch` where name like %s order by creation desc limit 200",
		pattern,
	)
	highest = 0
	for (name,) in existing:
		tail = name[len(prefix) + len(sep):] if prefix else name
		token = tail.split(sep)[0]
		if token.isdigit():
			highest = max(highest, int(token))
	return highest + 1


def _ensure_unique(batch_id, sep, dry_run):
	if dry_run or not batch_id:
		return batch_id
	candidate, n = batch_id, 1
	while frappe.db.exists("Batch", candidate):
		n += 1
		candidate = "{0}{1}{2}".format(batch_id, sep, cstr(n).zfill(2))
	return candidate


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

def build_context(doc, item):
	sales_order = None
	sales_person = None
	customer = None

	po_item = getattr(item, "purchase_order_item", None)
	if po_item:
		sales_order = frappe.db.get_value("Purchase Order Item", po_item, "sales_order")
	if not sales_order and getattr(item, "sales_order", None):
		sales_order = item.sales_order

	if sales_order:
		customer = frappe.db.get_value("Sales Order", sales_order, "customer")
		sales_person = frappe.db.get_value(
			"Sales Team", {"parent": sales_order, "parenttype": "Sales Order"}, "sales_person"
		)

	item_group, brand = frappe.get_cached_value("Item", item.item_code, ["item_group", "brand"])

	from neotec_order_costing.api.specs import get_part_numbers

	parts = get_part_numbers(
		item.item_code, customer=customer, supplier=getattr(doc, "supplier", None)
	)

	return {
		"manufacturer_part_no": parts.get("manufacturer_part_no"),
		"supplier_part_no": parts.get("supplier_part_no"),
		"customer_part_no": parts.get("customer_part_no"),
		"item_code": item.item_code,
		"item_group": item_group,
		"brand": brand,
		"supplier": getattr(doc, "supplier", None),
		"customer": customer,
		"sales_order": sales_order,
		"purchase_order": getattr(item, "purchase_order", None),
		"stock_document": doc.name,
		"sales_person": sales_person,
		"posting_date": getattr(doc, "posting_date", None),
		"fiscal_year": getattr(doc, "fiscal_year", None),
		"purchase_rate": getattr(item, "rate", None),
	}


# ---------------------------------------------------------------------------
# Hook: before_validate on Purchase Receipt and Purchase Invoice
# ---------------------------------------------------------------------------

def apply_auto_batch(doc, method=None):
	"""Runs on both inward document types, so a client posting a direct
	Purchase Invoice with Update Stock gets identical batch behaviour to one
	that raises a Purchase Receipt first."""
	settings = frappe.get_cached_doc("Order Costing Settings")
	if not settings.enable_auto_batch:
		return
	if doc.doctype == "Purchase Invoice" and not doc.get("update_stock"):
		return
	if settings.auto_batch_applies_to and settings.auto_batch_applies_to != "Stock Inward Document":
		# Legacy values from 0.2.0 were never implemented. Rather than silently
		# doing nothing, run the supported behaviour and tell the implementor.
		frappe.msgprint(
			"Create Batch On is set to '{0}', which is not a supported mode. "
			"Batches are being created on the stock inward document. Change the "
			"setting to Stock Inward Document to clear this message.".format(
				settings.auto_batch_applies_to
			),
			indicator="orange", alert=True, title="Order Costing",
		)

	for item in doc.get("items", []):
		if not frappe.get_cached_value("Item", item.item_code, "has_batch_no"):
			continue
		if settings.skip_if_batch_supplied and (
			item.get("batch_no") or item.get("serial_and_batch_bundle")
		):
			continue

		ctx = build_context(doc, item)
		if settings.get("enable_consolidation") and _is_consolidated_line(item):
			identity = settings.get("batch_identity") or "Per Purchase Order"
			if identity == "Per Purchase Order":
				# a shared batch serves several orders, so a sales order number
				# in the batch id would be misleading
				ctx["sales_order"] = None
				ctx["customer"] = None
				ctx["sales_person"] = None
		batch_id = build_batch_id(ctx, settings=settings)
		if not batch_id:
			continue

		batch = _create_batch(batch_id, item, ctx, settings)
		set_batch_on_row(item, batch.name)
		if hasattr(item, "custom_noc_batch_template_used"):
			item.custom_noc_batch_template_used = batch_id


def _create_batch(batch_id, item, ctx, settings):
	if frappe.db.exists("Batch", batch_id):
		return frappe.get_doc("Batch", batch_id)

	_warn_if_prebatch_stock(item.item_code)

	batch = frappe.new_doc("Batch")
	batch.batch_id = batch_id
	batch.item = item.item_code
	batch.use_batchwise_valuation = 1
	batch.custom_noc_generated = 1
	batch.custom_noc_source_sales_order = ctx.get("sales_order")
	batch.custom_noc_source_purchase_order = ctx.get("purchase_order")
	batch.description = "Auto-created by Neotec Order Costing"

	if settings.set_batch_expiry_from_item:
		shelf_life = frappe.get_cached_value("Item", item.item_code, "shelf_life_in_days")
		if shelf_life:
			batch.manufacturing_date = ctx.get("posting_date")
	batch.flags.ignore_permissions = True
	batch.insert(ignore_permissions=True)

	# The ERP platform resets use_batchwise_valuation during insert when the item has
	# pre-existing stock that was never batched. Without it the batch carries no
	# valuation of its own and every costing decision falls back to the item's
	# moving average, which defeats the entire purpose of pegging.
	if not batch.use_batchwise_valuation:
		frappe.db.set_value("Batch", batch.name, "use_batchwise_valuation", 1,
							update_modified=False)
		batch.reload()
	return batch


def _warn_if_prebatch_stock(item_code):
	"""Stock that exists without a batch blocks batchwise valuation in
	the ERP platform. It has to be cleared into an opening batch first."""
	if frappe.flags.get("noc_prebatch_checked_{0}".format(item_code)):
		return
	frappe.flags["noc_prebatch_checked_{0}".format(item_code)] = True

	exists = frappe.db.exists(
		"Stock Ledger Entry",
		{"item_code": item_code, "is_cancelled": 0, "batch_no": ["in", ["", None]]},
	)
	if exists:
		frappe.msgprint(
			"Item {0} has stock ledger entries with no batch. The ERP platform will not apply "
			"batchwise valuation while that is true, so order-wise COGS will fall back "
			"to the moving average. Clear the un-batched balance with a Stock "
			"Reconciliation into an opening batch first.".format(item_code),
			indicator="red", title="Batchwise Valuation Blocked",
		)


# ---------------------------------------------------------------------------
# Row-level batch assignment
# ---------------------------------------------------------------------------

def set_batch_on_row(item, batch_no):
	"""ERP v15 routes batches through a Serial and Batch Bundle unless the
	row opts into the plain fields. Setting batch_no alone leaves the mandatory
	check unsatisfied, which is why users were being asked to pick manually."""
	if not batch_no:
		return False
	item.batch_no = batch_no
	if hasattr(item, "use_serial_batch_fields"):
		item.use_serial_batch_fields = 1
	if item.get("serial_and_batch_bundle"):
		item.serial_and_batch_bundle = None
	return True


def _is_consolidated_line(item):
	po_item = item.get("purchase_order_item")
	if not po_item:
		return False
	return frappe.db.count(
		"Order Cost Peg", {"purchase_order_item": po_item, "docstatus": 1}
	) > 1
