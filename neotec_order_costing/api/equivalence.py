"""Part equivalence and supersession.

A manufacturer discontinues a part mid-order and ships the replacement. The
purchase order and the cost peg both point at the dead part number. Without
handling, the peg silently breaks and the customer receives a part whose
specification differs from what was quoted.
"""

import frappe
from frappe.utils import flt, now_datetime

from neotec_order_costing.api.specs import render_comparison
from neotec_order_costing.neotec_order_costing.doctype.order_costing_settings.order_costing_settings import (
	get_settings,
)


def get_equivalents(item_code, relations=None):
	rows = frappe.get_all(
		"Part Equivalence",
		filters={"parent": item_code, "parenttype": "Item"},
		fields=["equivalent_item", "relation", "effective_from", "notes"],
		order_by="effective_from desc",
	)
	if relations:
		rows = [r for r in rows if r.relation in relations]
	return rows


def find_relation(ordered_item, supplied_item):
	"""Direct row on the ordered part, or the reverse row on the supplied part."""
	for row in get_equivalents(ordered_item):
		if row.equivalent_item == supplied_item:
			return row.relation
	for row in get_equivalents(supplied_item):
		if row.equivalent_item == ordered_item:
			return {"Supersedes": "Superseded By", "Superseded By": "Supersedes"}.get(
				row.relation, row.relation
			)
	return None


# ---------------------------------------------------------------------------
# Hook: before_validate on Purchase Receipt and Purchase Invoice
# ---------------------------------------------------------------------------

def check_substitutions(doc, method=None):
	settings = get_settings()
	if not settings.enable_order_wise_cogs:
		return
	if doc.doctype == "Purchase Invoice" and not doc.get("update_stock"):
		return

	mode = settings.get("allow_superseded_substitution") or "Prompt"
	if mode == "Forbidden":
		_block_mismatches(doc)
		return

	for item in doc.get("items", []):
		if not item.get("purchase_order_item"):
			continue
		ordered = frappe.db.get_value("Purchase Order Item", item.purchase_order_item, "item_code")
		if not ordered or ordered == item.item_code:
			continue

		relation = find_relation(ordered, item.item_code)
		if not relation:
			frappe.throw(
				"Row {0}: purchase order line is for part number {1} but {2} is being received, "
				"and no equivalence is recorded between them. Add a Part Equivalence row on the "
				"item, or correct the line.".format(item.idx, ordered, item.item_code)
			)
		if mode == "Prompt":
			frappe.msgprint(
				"Row {0}: {1} is being supplied against ordered part number {2} "
				"({3}). The cost peg will be re-pointed and a substitution log created.".format(
					item.idx, item.item_code, ordered, relation
				),
				indicator="orange", title="Part Substitution", alert=True,
			)
		item.flags.noc_substituted_from = ordered
		item.flags.noc_relation = relation


def _block_mismatches(doc):
	for item in doc.get("items", []):
		if not item.get("purchase_order_item"):
			continue
		ordered = frappe.db.get_value("Purchase Order Item", item.purchase_order_item, "item_code")
		if ordered and ordered != item.item_code:
			frappe.throw(
				"Row {0}: part substitution is disabled. Ordered {1}, receiving {2}.".format(
					item.idx, ordered, item.item_code
				)
			)


# ---------------------------------------------------------------------------
# Hook: on_submit, after the peg has been updated
# ---------------------------------------------------------------------------

def record_substitutions(doc, method=None):
	settings = get_settings()
	if not settings.enable_order_wise_cogs:
		return
	if doc.doctype == "Purchase Invoice" and not doc.get("update_stock"):
		return

	for item in doc.get("items", []):
		if not item.get("purchase_order_item"):
			continue
		ordered = frappe.db.get_value("Purchase Order Item", item.purchase_order_item, "item_code")
		if not ordered or ordered == item.item_code:
			continue
		relation = find_relation(ordered, item.item_code) or "Manual Override"
		_repoint_peg(doc, item, ordered, relation)


def _repoint_peg(doc, item, ordered_item, relation):
	peg_name = item.get("custom_noc_order_cost_peg") or frappe.db.get_value(
		"Order Cost Peg", {"purchase_order_item": item.purchase_order_item, "docstatus": 1}, "name"
	)
	if not peg_name:
		return

	peg = frappe.get_doc("Order Cost Peg", peg_name)

	log = frappe.new_doc("Part Substitution Log")
	log.substitution_date = now_datetime()
	log.company = doc.company
	log.original_item = ordered_item
	log.substituted_item = item.item_code
	log.relation_used = relation
	log.order_cost_peg = peg.name
	log.sales_order = peg.sales_order
	log.purchase_order = peg.purchase_order
	log.inward_document_type = doc.doctype
	log.inward_document = doc.name
	log.qty = flt(item.stock_qty or item.qty)
	log.spec_delta = render_comparison(ordered_item, item.item_code)
	log.flags.ignore_permissions = True
	log.insert(ignore_permissions=True)

	peg.substituted_from_item = ordered_item
	peg.substitution_log = log.name
	peg.item_code = item.item_code
	peg.brand = frappe.get_cached_value("Item", item.item_code, "brand")
	from neotec_order_costing.api.peg import save_peg

	save_peg(peg)

	if peg.sales_order_item:
		frappe.db.set_value(
			"Sales Order Item", peg.sales_order_item,
			"custom_noc_substituted_part_no", item.item_code,
			update_modified=False,
		)

	frappe.msgprint(
		"Substitution log {0} created. Review the specification differences before "
		"delivering to the customer.".format(
			frappe.utils.get_link_to_form("Part Substitution Log", log.name)
		),
		indicator="blue", title="Part Substitution",
	)


# ---------------------------------------------------------------------------
# UI helper
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_substitution_options(item_code):
	rows = get_equivalents(item_code, relations=["Alternate", "Superseded By"])
	for r in rows:
		r["item_name"] = frappe.get_cached_value("Item", r["equivalent_item"], "item_name")
		r["brand"] = frappe.get_cached_value("Item", r["equivalent_item"], "brand")
	return rows


@frappe.whitelist()
def compare_parts(item_a, item_b):
	frappe.has_permission("Item", throw=True)
	return render_comparison(item_a, item_b)
