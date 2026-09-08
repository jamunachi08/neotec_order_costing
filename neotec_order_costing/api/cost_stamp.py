"""Purchase cost visibility across the sales cycle.

Order-wise COGS changes what the stock ledger posts. Cost visibility is a
separate, lighter thing: it copies the pegged purchase rate onto Sales Order,
Delivery Note, Sales Invoice and Quotation rows so margin is visible everywhere,
without touching valuation at all.

That separation matters. A client can run standard moving-average valuation and
still see, on every sales document, what the goods actually cost to buy.
"""

import frappe
from frappe.utils import flt

from neotec_order_costing.neotec_order_costing.doctype.order_costing_settings.order_costing_settings import (
	get_settings,
	is_cost_visibility_enabled,
)

# Fields the implementor can pull from the peg onto a sales row.
PEG_SOURCES = {
	"effective_cost_rate": "Effective Cost Rate",
	"purchase_rate": "Purchase Order Rate",
	"received_rate": "Received Rate",
	"landed_rate": "Landed Rate",
	"quoted_rate": "Quoted Rate",
	"last_purchase_rate": "Item Last Purchase Rate",
	"valuation_rate": "Current Valuation Rate",
}

SALES_ROWS = {
	"Quotation": "Quotation Item",
	"Sales Order": "Sales Order Item",
	"Delivery Note": "Delivery Note Item",
	"Sales Invoice": "Sales Invoice Item",
}


def _so_item_of(item):
	return (item.get("so_detail") or item.get("sales_order_item")
			or (item.name if item.parenttype == "Sales Order" else None))


def _sales_order_of(doc, item):
	return (item.get("against_sales_order") or item.get("sales_order")
			or (doc.name if doc.doctype == "Sales Order" else None))


def _assert_saved(doctype, name):
	"""A document being created has a client-side temporary name such as
	new-sales-invoice-abc123. It does not exist on the server, so any backend
	call using it must fail with an explanation rather than a Not Found page."""
	if not name or str(name).startswith("new-"):
		frappe.throw(
			"Save the {0} before fetching purchase rates.".format(
				frappe.bold(doctype)
			),
			title="Document Not Saved",
		)
	if not frappe.db.exists(doctype, name):
		frappe.throw(
			"{0} {1} does not exist. It may have been renamed or deleted.".format(
				doctype, name
			),
			title="Not Found",
		)


def find_peg(doc, item):
	"""Resolve the peg for a sales row, by row link first and then by order and
	item, so a Delivery Note created outside the standard flow still resolves."""
	so_item = _so_item_of(item)
	if so_item:
		name = frappe.db.get_value(
			"Order Cost Peg", {"sales_order_item": so_item, "docstatus": 1}, "name"
		)
		if name:
			return name

	sales_order = _sales_order_of(doc, item)
	if not sales_order:
		return None
	return frappe.db.get_value(
		"Order Cost Peg",
		{"sales_order": sales_order, "item_code": item.item_code, "docstatus": 1},
		"name", order_by="qty_open desc",
	)


def _fallback_rate(item, source, company):
	"""No peg yet, or the peg has no rate. Fall back so the field is never blank
	when a usable cost exists elsewhere."""
	if source == "valuation_rate" or source == "effective_cost_rate":
		rate = frappe.db.get_value(
			"Bin",
			{"item_code": item.item_code, "warehouse": item.get("warehouse")},
			"valuation_rate",
		)
		if flt(rate):
			return flt(rate), "Current Valuation Rate"
	rate = frappe.db.get_value("Item", item.item_code, "last_purchase_rate")
	if flt(rate):
		return flt(rate), "Item Last Purchase Rate"
	rate = frappe.db.get_value("Item", item.item_code, "valuation_rate")
	return flt(rate), "Item Valuation Rate" if flt(rate) else None


def stamp_costs(doc, method=None):
	"""before_validate on every sales document."""
	if not is_cost_visibility_enabled():
		return
	if doc.doctype not in SALES_ROWS:
		return

	settings = get_settings()
	source = settings.get("cost_visibility_source") or "effective_cost_rate"
	extra_fields = [
		r for r in settings.get("cost_visibility_fields", []) if r.get("enabled")
	]
	overwrite = bool(settings.get("cost_visibility_overwrite"))

	for item in doc.get("items", []):
		if not item.get("item_code"):
			continue
		if not overwrite and flt(item.get("custom_noc_pegged_cost_rate")):
			continue

		peg_name = find_peg(doc, item)
		rate, origin = 0.0, None

		if peg_name:
			peg = frappe.db.get_value(
				"Order Cost Peg", peg_name,
				["effective_cost_rate", "purchase_rate", "received_rate",
				 "landed_rate", "quoted_rate", "purchase_order", "supplier",
				 "batch_no", "is_consolidated"],
				as_dict=True,
			)
			if hasattr(item, "custom_noc_order_cost_peg"):
				item.custom_noc_order_cost_peg = peg_name
			rate = flt(peg.get(source)) if source in peg else 0.0
			if not rate:
				# walk down the chain: landed, received, ordered, quoted
				for key in ("landed_rate", "received_rate", "purchase_rate", "quoted_rate"):
					if flt(peg.get(key)):
						rate = flt(peg[key])
						origin = PEG_SOURCES[key]
						break
			else:
				origin = PEG_SOURCES.get(source)
			_stamp_extras(item, peg, extra_fields)

		if not rate:
			rate, origin = _fallback_rate(item, source, doc.get("company"))

		if hasattr(item, "custom_noc_pegged_cost_rate"):
			item.custom_noc_pegged_cost_rate = flt(rate)
		if hasattr(item, "custom_noc_cost_source_used"):
			item.custom_noc_cost_source_used = origin
		_set_margin(item, rate)


def _stamp_extras(item, peg, extra_fields):
	"""Implementor-chosen peg fields copied onto the sales row."""
	for row in extra_fields:
		target = row.get("target_fieldname")
		source = row.get("peg_fieldname")
		if not (target and source):
			continue
		if not hasattr(item, target):
			continue
		value = peg.get(source)
		if value is not None:
			setattr(item, target, value)


def _set_margin(item, cost_rate):
	if not hasattr(item, "custom_noc_unit_margin"):
		return
	selling = flt(item.get("base_net_rate") or item.get("net_rate") or item.get("rate"))
	item.custom_noc_unit_margin = selling - flt(cost_rate)
	if hasattr(item, "custom_noc_margin_percent"):
		item.custom_noc_margin_percent = (
			(item.custom_noc_unit_margin / selling * 100) if selling else 0
		)


# ---------------------------------------------------------------------------
# Refresh on demand
# ---------------------------------------------------------------------------

@frappe.whitelist()
def refresh_document(doctype, name):
	"""Re-stamps a submitted document after the purchase rate has changed,
	which is the normal case: the sales order exists before the purchase order.
	Only the reporting fields are touched, never the ledger."""
	frappe.only_for(["System Manager", "Sales Manager", "Accounts Manager",
					 "Stock Manager", "Purchase Manager"])
	_assert_saved(doctype, name)
	doc = frappe.get_doc(doctype, name)
	settings = get_settings()
	source = settings.get("cost_visibility_source") or "effective_cost_rate"
	updated = 0
	missing = False

	for item in doc.items:
		peg_name = find_peg(doc, item)
		if not peg_name:
			continue
		peg = frappe.db.get_value(
			"Order Cost Peg", peg_name,
			["effective_cost_rate", "purchase_rate", "received_rate",
			 "landed_rate", "quoted_rate"], as_dict=True,
		)
		rate = flt(peg.get(source))
		if not rate:
			for key in ("landed_rate", "received_rate", "purchase_rate", "quoted_rate"):
				if flt(peg.get(key)):
					rate = flt(peg[key])
					break
		if not rate:
			continue

		selling = flt(item.get("base_net_rate") or item.get("rate"))
		values = {
			"custom_noc_order_cost_peg": peg_name,
			"custom_noc_pegged_cost_rate": rate,
			"custom_noc_unit_margin": selling - rate,
			"custom_noc_margin_percent": ((selling - rate) / selling * 100) if selling else 0,
		}
		values = _existing_only(item.doctype, values)
		if not values:
			missing = True
			continue
		frappe.db.set_value(item.doctype, item.name, values, update_modified=False)
		updated += 1

	frappe.db.commit()
	if missing:
		frappe.throw(
			"The cost visibility fields are not present on {0}. Run bench migrate, "
			"or use Repair Schema in Order Costing Settings.".format(
				doc.items[0].doctype if doc.items else doc.doctype
			),
			title="Fields Not Installed",
		)
	return {"updated": updated, "total": len(doc.items)}


def _existing_only(doctype, values):
	"""Writing a column that was never created raises an opaque SQL error, so
	filter against what the table actually has."""
	try:
		columns = set(frappe.db.get_table_columns(doctype))
	except Exception:
		return values
	return {k: v for k, v in values.items() if k in columns}


@frappe.whitelist()
def refresh_sales_order_chain(sales_order):
	"""Pushes the purchase rate through every sales document for an order:
	the order itself, then its deliveries and invoices."""
	frappe.only_for(["System Manager", "Sales Manager", "Accounts Manager",
					 "Stock Manager", "Purchase Manager"])
	_assert_saved("Sales Order", sales_order)
	results = {"Sales Order": refresh_document("Sales Order", sales_order)}

	for doctype, child, field in (
		("Delivery Note", "Delivery Note Item", "against_sales_order"),
		("Sales Invoice", "Sales Invoice Item", "sales_order"),
	):
		names = frappe.get_all(
			child, filters={field: sales_order}, pluck="parent", distinct=True
		)
		for name in set(names):
			results.setdefault(doctype, []).append(refresh_document(doctype, name))
	return results


@frappe.whitelist()
def get_peg_field_options():
	"""Feeds the field picker in settings."""
	meta = frappe.get_meta("Order Cost Peg")
	skip = {"naming_series", "amended_from"}
	return [
		{"fieldname": f.fieldname, "label": f.label or f.fieldname, "fieldtype": f.fieldtype}
		for f in meta.fields
		if f.fieldname not in skip
		and f.fieldtype not in ("Section Break", "Column Break", "Table", "HTML")
	]


# ---------------------------------------------------------------------------
# Propagation
# ---------------------------------------------------------------------------

def on_purchase_rate_change(doc, method=None):
	"""The sales order almost always exists before the purchase order, so the
	cost has to flow backwards once procurement commits to a rate."""
	if not is_cost_visibility_enabled():
		return

	orders = set()
	for item in doc.get("items", []):
		peg_name = item.get("custom_noc_order_cost_peg")
		if not peg_name:
			continue
		sales_order = frappe.db.get_value("Order Cost Peg", peg_name, "sales_order")
		if sales_order:
			orders.add(sales_order)

	if not orders:
		return

	frappe.enqueue(
		"neotec_order_costing.api.cost_stamp.refresh_orders_background",
		queue="short", orders=list(orders), enqueue_after_commit=True,
	)


def refresh_orders_background(orders):
	for sales_order in orders or []:
		try:
			refresh_sales_order_chain(sales_order)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				"Cost visibility refresh failed for {0}".format(sales_order),
			)
