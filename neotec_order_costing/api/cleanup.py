"""One-click teardown of a linked document cycle.

Anchor on any document in the chain — a quotation, a sales order, a purchase
order, a receipt, an invoice, a delivery, a batch or a cost peg — and the
tracer walks the link graph in both directions to find the whole cycle, then
removes it in reverse dependency order.

This exists for UAT and demonstration cycles. It cancels and deletes submitted
accounting and stock documents, which is irreversible. Three guards stand in
front of it: a settings toggle that is off by default, a mandatory preview, and
a typed confirmation.
"""

import frappe
from frappe.utils import cstr, flt

# ---------------------------------------------------------------------------
# Link graph
#
# Each edge says: rows of `link_doctype` carry `link_field`, which points at a
# document of `target_doctype`. The row itself belongs to `owner_doctype` —
# the row's parent when it is a child table, or the row itself when it is a top
# level doctype.
#
# Walking an edge forwards finds owners from targets. Walking it backwards
# finds targets from owners. That gives full-cycle traversal from any anchor.
# ---------------------------------------------------------------------------

EDGES = [
	# link doctype,                     field,                 target,             owner
	("Sales Order Item",                "prevdoc_docname",     "Quotation",        "Sales Order"),
	("Material Request Item",           "sales_order",         "Sales Order",      "Material Request"),
	("Purchase Order Item",             "sales_order",         "Sales Order",      "Purchase Order"),
	("Purchase Order Item",             "material_request",    "Material Request", "Purchase Order"),
	("Supplier Quotation Item",         "material_request",    "Material Request", "Supplier Quotation"),
	("Request for Quotation Item",      "material_request",    "Material Request", "Request for Quotation"),
	("Purchase Order Item",             "supplier_quotation",  "Supplier Quotation", "Purchase Order"),
	("Order Cost Peg",                  "procurement_consolidation", "Procurement Consolidation", "Order Cost Peg"),
	("Order Cost Peg",                  "material_request",    "Material Request", "Order Cost Peg"),
	("Purchase Receipt Item",           "purchase_order",      "Purchase Order",   "Purchase Receipt"),
	("Purchase Invoice Item",           "purchase_order",      "Purchase Order",   "Purchase Invoice"),
	("Purchase Invoice Item",           "purchase_receipt",    "Purchase Receipt", "Purchase Invoice"),
	("Delivery Note Item",              "against_sales_order", "Sales Order",      "Delivery Note"),
	("Sales Invoice Item",              "sales_order",         "Sales Order",      "Sales Invoice"),
	("Sales Invoice Item",              "delivery_note",       "Delivery Note",    "Sales Invoice"),
	("Landed Cost Purchase Receipt",    "receipt_document",    "Purchase Receipt", "Landed Cost Voucher"),
	("Payment Entry Reference",         "reference_name",      "Sales Invoice",    "Payment Entry"),
	("Payment Entry Reference",         "reference_name",      "Purchase Invoice", "Payment Entry"),
	("Journal Entry Account",           "reference_name",      "Sales Invoice",    "Journal Entry"),
	("Journal Entry Account",           "reference_name",      "Purchase Invoice", "Journal Entry"),
	# app documents
	("Order Cost Peg",                  "sales_order",         "Sales Order",      "Order Cost Peg"),
	("Order Cost Peg",                  "purchase_order",      "Purchase Order",   "Order Cost Peg"),
	("Order Cost Peg",                  "batch_no",            "Batch",            "Order Cost Peg"),
	("Part Substitution Log",           "order_cost_peg",      "Order Cost Peg",   "Part Substitution Log"),
	("Batch",                           "custom_noc_source_sales_order",    "Sales Order",    "Batch"),
	("Batch",                           "custom_noc_source_purchase_order", "Purchase Order", "Batch"),
]

# Dynamic links need the companion type field checked as well.
DYNAMIC_EDGES = [
	# link doctype,             type field,               link field,          owner
	("As Built Configuration",  "delivery_document_type", "delivery_document", "As Built Configuration"),
	("Order Cost Peg",          "stock_document_type",    "stock_document",    "Order Cost Peg"),
	("Stock Reservation Entry", "voucher_type",           "voucher_no",        "Stock Reservation Entry"),
]

# Collected but never expanded from. A batch or a payment can be shared across
# unrelated orders, so expanding outward from one would drag in documents the
# user never asked to touch.
TERMINAL = {"Batch", "Payment Entry", "Journal Entry"}

# Reverse dependency order. Anything referencing another document goes first.
DELETION_ORDER = [
	"Payment Entry",
	"Journal Entry",
	"Sales Invoice",
	"As Built Configuration",
	"Delivery Note",
	"Landed Cost Voucher",
	"Purchase Invoice",
	"Purchase Receipt",
	"Part Substitution Log",
	"Order Cost Peg",
	"Stock Reservation Entry",
	"Purchase Order",
	"Supplier Quotation",
	"Request for Quotation",
	"Procurement Consolidation",
	"Material Request",
	"Sales Order",
	"Quotation",
	"Batch",
]

ANCHOR_DOCTYPES = [
	"Quotation", "Sales Order", "Material Request", "Supplier Quotation",
	"Request for Quotation", "Purchase Order", "Purchase Receipt",
	"Purchase Invoice", "Delivery Note", "Sales Invoice",
	"Order Cost Peg", "Procurement Consolidation", "Batch",
]

DATE_FIELD = {
	"Quotation": "transaction_date",
	"Sales Order": "transaction_date",
	"Material Request": "transaction_date",
	"Purchase Order": "transaction_date",
	"Purchase Receipt": "posting_date",
	"Purchase Invoice": "posting_date",
	"Delivery Note": "posting_date",
	"Sales Invoice": "posting_date",
	"Order Cost Peg": "transaction_date",
	"Supplier Quotation": "transaction_date",
	"Request for Quotation": "transaction_date",
	"Procurement Consolidation": "consolidation_date",
	"Batch": "creation",
}

MAX_NODES = 5000


# ---------------------------------------------------------------------------
# Guards and metadata helpers
# ---------------------------------------------------------------------------

def _assert_allowed(confirmation=None):
	frappe.only_for("System Manager")

	settings = frappe.get_single("Order Costing Settings")
	if not settings.get("allow_destructive_cleanup"):
		frappe.throw(
			"Destructive cleanup is disabled. Switch on 'Allow Destructive Cleanup' in "
			"Order Costing Settings first, and switch it off again afterwards.",
			title="Cleanup Disabled",
		)

	if cstr(confirmation).strip() != "DELETE":
		frappe.throw(
			"Type DELETE in the confirmation box to proceed.", title="Confirmation Required"
		)


def _exists(doctype):
	return bool(frappe.db.exists("DocType", doctype))


def _is_child(doctype):
	try:
		return bool(frappe.get_meta(doctype).istable)
	except Exception:
		return False


def _has_field(doctype, fieldname):
	try:
		return bool(frappe.get_meta(doctype).get_field(fieldname))
	except Exception:
		return False


def _usable(doctype, fieldname=None):
	if not _exists(doctype):
		return False
	return _has_field(doctype, fieldname) if fieldname else True


# ---------------------------------------------------------------------------
# Traversal primitives
# ---------------------------------------------------------------------------

def _owners_from_targets(edge, names):
	"""Forward: given target documents, find documents that reference them."""
	link_doctype, link_field, _target, _owner = edge
	if not _usable(link_doctype, link_field):
		return []
	field = "parent" if _is_child(link_doctype) else "name"
	return frappe.get_all(
		link_doctype, filters={link_field: ["in", list(names)]},
		pluck=field, distinct=True,
	) or []


def _targets_from_owners(edge, names):
	"""Backward: given referencing documents, find what they point at."""
	link_doctype, link_field, _target, _owner = edge
	if not _usable(link_doctype, link_field):
		return []
	filters = {"parent": ["in", list(names)]} if _is_child(link_doctype) \
		else {"name": ["in", list(names)]}
	return frappe.get_all(
		link_doctype, filters=filters, pluck=link_field, distinct=True
	) or []


def _dynamic_owners(edge, target_doctype, names):
	link_doctype, type_field, link_field, _owner = edge
	if not _usable(link_doctype, link_field):
		return []
	return frappe.get_all(
		link_doctype,
		filters={type_field: target_doctype, link_field: ["in", list(names)]},
		pluck="name", distinct=True,
	) or []


def _dynamic_targets(edge, names):
	link_doctype, type_field, link_field, _owner = edge
	if not _usable(link_doctype, link_field):
		return {}
	rows = frappe.get_all(
		link_doctype, filters={"name": ["in", list(names)]},
		fields=[type_field, link_field],
	)
	out = {}
	for row in rows:
		dt, dn = row.get(type_field), row.get(link_field)
		if dt and dn:
			out.setdefault(dt, set()).add(dn)
	return out


# ---------------------------------------------------------------------------
# Closure
# ---------------------------------------------------------------------------

def trace(anchors=None, anchor_doctype=None, company=None,
		  from_date=None, to_date=None, exclude_doctypes=None):
	"""Breadth-first closure over the link graph from any anchor."""
	exclude = set(frappe.parse_json(exclude_doctypes)
				  if isinstance(exclude_doctypes, str) else (exclude_doctypes or []))

	if isinstance(anchors, str):
		anchors = (frappe.parse_json(anchors) if anchors.strip().startswith("[")
				   else [anchors])
	anchors = [a for a in (anchors or []) if a]
	anchor_doctype = anchor_doctype or "Sales Order"

	if not anchors:
		filters = {}
		if _has_field(anchor_doctype, "docstatus"):
			filters["docstatus"] = ["<", 3]
		if company and _has_field(anchor_doctype, "company"):
			filters["company"] = company
		date_field = DATE_FIELD.get(anchor_doctype)
		if date_field and from_date and to_date:
			filters[date_field] = ["between", [from_date, to_date]]
		elif date_field and from_date:
			filters[date_field] = [">=", from_date]
		elif date_field and to_date:
			filters[date_field] = ["<=", to_date]
		anchors = frappe.get_all(anchor_doctype, filters=filters, pluck="name")

	found = {dt: set() for dt in DELETION_ORDER}
	found.setdefault(anchor_doctype, set()).update(anchors)

	frontier = [(anchor_doctype, set(anchors))]
	visited = {anchor_doctype: set(anchors)}
	total = len(anchors)
	truncated = False

	while frontier:
		if total >= MAX_NODES:
			truncated = True
			break
		doctype, names = frontier.pop(0)
		if not names or doctype in TERMINAL:
			continue

		discovered = {}

		for edge in EDGES:
			_ld, _lf, target, owner = edge
			if target == doctype and owner not in exclude:
				for n in _owners_from_targets(edge, names):
					discovered.setdefault(owner, set()).add(n)
			if owner == doctype and target not in exclude:
				for n in _targets_from_owners(edge, names):
					discovered.setdefault(target, set()).add(n)

		for edge in DYNAMIC_EDGES:
			_ld, _tf, _lf, owner = edge
			if owner not in exclude:
				for n in _dynamic_owners(edge, doctype, names):
					discovered.setdefault(owner, set()).add(n)
			if owner == doctype:
				for target_dt, targets in _dynamic_targets(edge, names).items():
					if target_dt in DELETION_ORDER and target_dt not in exclude:
						discovered.setdefault(target_dt, set()).update(targets)

		for dt, new_names in discovered.items():
			fresh = {n for n in new_names if n} - visited.get(dt, set())
			if not fresh:
				continue
			visited.setdefault(dt, set()).update(fresh)
			found.setdefault(dt, set()).update(fresh)
			total += len(fresh)
			frontier.append((dt, fresh))

	if truncated:
		frappe.msgprint(
			"Traversal stopped at {0} documents. Narrow the anchor or the date "
			"range.".format(MAX_NODES),
			indicator="orange", title="Trace Truncated",
		)

	ordered = list(DELETION_ORDER) + [d for d in found if d not in DELETION_ORDER]
	return {dt: sorted(found.get(dt, set())) for dt in ordered}


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

def _paid_invoices(plan):
	risky = []
	for doctype in ("Sales Invoice", "Purchase Invoice"):
		for name in plan.get(doctype) or []:
			row = frappe.db.get_value(
				doctype, name,
				["outstanding_amount", "grand_total", "docstatus"], as_dict=True,
			)
			if row and row.docstatus == 1 and flt(row.outstanding_amount) < flt(row.grand_total):
				risky.append("{0} {1}".format(doctype, name))
	return risky


@frappe.whitelist()
def preview(anchors=None, anchor_doctype=None, company=None,
			from_date=None, to_date=None, exclude_doctypes=None):
	frappe.only_for("System Manager")
	plan = trace(anchors, anchor_doctype, company, from_date, to_date, exclude_doctypes)
	risky = _paid_invoices(plan)

	rows, total = [], 0
	for doctype in DELETION_ORDER:
		names = plan.get(doctype) or []
		if not names:
			continue
		total += len(names)
		sample = ", ".join(names[:5])
		if len(names) > 5:
			sample += " and {0} more".format(len(names) - 5)
		rows.append(
			"<tr><td>{0}</td><td class='text-right'>{1}</td>"
			"<td class='text-muted small'>{2}</td></tr>".format(
				frappe.utils.escape_html(doctype), len(names),
				frappe.utils.escape_html(sample)
			)
		)

	html = (
		"<table class='table table-bordered'><thead><tr>"
		"<th>Document Type</th><th class='text-right'>Count</th><th>Documents</th>"
		"</tr></thead><tbody>{0}</tbody></table>".format("".join(rows))
		if rows else "<p>Nothing matched. Widen the filters or pick a different anchor.</p>"
	)

	if risky:
		html += (
			"<div style='margin-top:8px;padding:8px;border-left:3px solid #A32D2D'>"
			"<b>These invoices are partly or fully paid.</b> Deleting them removes the "
			"payment allocation as well: {0}</div>".format(
				frappe.utils.escape_html(", ".join(risky[:10]))
			)
		)

	return {"plan": plan, "html": html, "total": total, "risky": risky}


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

@frappe.whitelist()
def execute_cleanup(anchors=None, anchor_doctype=None, company=None,
					from_date=None, to_date=None, exclude_doctypes=None,
					confirmation=None):
	_assert_allowed(confirmation)

	plan = trace(anchors, anchor_doctype, company, from_date, to_date, exclude_doctypes)
	deleted, failed = [], []

	pending = [(dt, n) for dt in DELETION_ORDER for n in (plan.get(dt) or [])]

	# Two passes. A first-pass failure is nearly always a dependency that had
	# not been removed yet, and it clears on the retry.
	for attempt in (1, 2):
		retry, failed = [], []
		for doctype, name in pending:
			try:
				_remove(doctype, name)
				deleted.append("{0} {1}".format(doctype, name))
				frappe.db.commit()
			except Exception as exc:
				frappe.db.rollback()
				if attempt == 1:
					retry.append((doctype, name))
				failed.append("{0} {1}: {2}".format(doctype, name, exc))
		if not retry:
			break
		pending = retry

	log = frappe.new_doc("Comment")
	log.comment_type = "Info"
	log.reference_doctype = "Order Costing Settings"
	log.reference_name = "Order Costing Settings"
	log.content = "Cleanup removed {0} document(s), {1} failure(s). Anchor: {2} {3}".format(
		len(deleted), len(failed), cstr(anchor_doctype), cstr(anchors or company)
	)
	log.flags.ignore_permissions = True
	log.insert(ignore_permissions=True)
	frappe.db.commit()

	return {"deleted": deleted, "failed": failed,
			"deleted_count": len(deleted), "failed_count": len(failed)}


# Links that point at a document which may already have been removed earlier in
# the run. Clearing them stops the platform raising "not found" while cancelling.
STALE_LINK_FIELDS = {
	"Purchase Order Item": ["material_request", "material_request_item",
							"sales_order", "sales_order_item"],
	"Purchase Receipt Item": ["material_request", "material_request_item",
							  "purchase_order", "purchase_order_item"],
	"Purchase Invoice Item": ["purchase_order", "purchase_order_item",
							  "purchase_receipt", "pr_detail"],
	"Delivery Note Item": ["against_sales_order", "so_detail"],
	"Sales Invoice Item": ["sales_order", "so_detail", "delivery_note", "dn_detail"],
	"Supplier Quotation Item": ["material_request", "material_request_item"],
	"Request for Quotation Item": ["material_request", "material_request_item"],
	"Material Request Item": ["sales_order", "sales_order_item"],
}


def _clear_stale_links(doctype, name):
	"""A partially completed run leaves child rows pointing at documents that
	no longer exist. The platform then refuses to cancel the parent because it
	cannot load the link target."""
	child = "{0} Item".format(doctype)
	fields = STALE_LINK_FIELDS.get(child)
	if not fields:
		return
	if not frappe.db.exists("DocType", child):
		return

	meta = frappe.get_meta(child)
	for fieldname in fields:
		field = meta.get_field(fieldname)
		if not field:
			continue
		rows = frappe.get_all(
			child, filters={"parent": name, fieldname: ["is", "set"]},
			fields=["name", fieldname],
		)
		for row in rows:
			value = row.get(fieldname)
			if not value:
				continue
			target = field.options
			if field.fieldtype == "Data" or not target:
				# row-level link such as sales_order_item; resolve its parent doctype
				target = _row_parent_doctype(fieldname)
			if not target:
				continue
			if not frappe.db.exists(target, value):
				frappe.db.set_value(child, row["name"], fieldname, None,
									update_modified=False)


ROW_PARENT = {
	"material_request_item": "Material Request Item",
	"sales_order_item": "Sales Order Item",
	"so_detail": "Sales Order Item",
	"purchase_order_item": "Purchase Order Item",
	"pr_detail": "Purchase Receipt Item",
	"dn_detail": "Delivery Note Item",
}


def _row_parent_doctype(fieldname):
	return ROW_PARENT.get(fieldname)


def _remove(doctype, name):
	if not frappe.db.exists(doctype, name):
		return

	_clear_stale_links(doctype, name)

	doc = frappe.get_doc(doctype, name)
	if getattr(doc.meta, "is_submittable", 0) and doc.docstatus == 1:
		doc.flags.ignore_permissions = True
		doc.flags.ignore_links = True
		doc.flags.ignore_validate = True
		try:
			doc.cancel()
		except frappe.DoesNotExistError:
			# a link target vanished mid-cancel; drop straight to docstatus 2
			frappe.db.set_value(doctype, name, "docstatus", 2, update_modified=False)
			frappe.db.commit()

	frappe.delete_doc(
		doctype, name, force=True, ignore_permissions=True,
		ignore_missing=True, delete_permanently=True,
	)


# ---------------------------------------------------------------------------
# Simulation teardown
# ---------------------------------------------------------------------------

@frappe.whitelist()
def reset_simulation(confirmation=None):
	_assert_allowed(confirmation)

	anchors = frappe.get_all(
		"Sales Order", filters={"customer": "SIM-CORP-CUSTOMER"}, pluck="name"
	)
	result = (
		execute_cleanup(anchors=anchors, anchor_doctype="Sales Order", confirmation="DELETE")
		if anchors else {"deleted": [], "failed": []}
	)

	masters = [
		("Item", {"item_code": ["like", "SIM-%"]}),
		("Customer", {"name": ["like", "SIM-%"]}),
		("Supplier", {"name": ["like", "SIM-%"]}),
		("Specification Template", {"template_name": "Business Laptop"}),
	]
	for doctype, filters in masters:
		for name in frappe.get_all(doctype, filters=filters, pluck="name"):
			try:
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True,
								  ignore_missing=True)
				result["deleted"].append("{0} {1}".format(doctype, name))
			except Exception as exc:
				result["failed"].append("{0} {1}: {2}".format(doctype, name, exc))

	frappe.db.commit()
	result["deleted_count"] = len(result["deleted"])
	result["failed_count"] = len(result["failed"])
	return result


@frappe.whitelist()
def get_anchor_doctypes():
	return [dt for dt in ANCHOR_DOCTYPES if _exists(dt)]
