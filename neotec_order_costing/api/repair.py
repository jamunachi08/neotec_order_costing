"""Repair utilities for sites that ran 0.2.0.

Three defects in 0.2.0 left data in an inconsistent state:

1. Order Cost Peg fields were not marked allow_on_submit, so every post-submit
   update to a peg threw and the peg stayed at its creation values.
2. The peg was only linked to a purchase line when sales_order_item was carried
   down, which The ERP platform does not always do.
3. Batches were created with use_batchwise_valuation left at 0, so costing fell
   back to the moving average.

Run after upgrading and migrating:

	bench --site <site> execute neotec_order_costing.api.repair.run

or use the Repair Pegs button on Order Costing Settings.
"""

import frappe
from frappe.utils import flt


def _log(msg):
	print("[order-costing repair] {0}".format(msg))
	frappe.msgprint(msg, indicator="blue", alert=True)


# ---------------------------------------------------------------------------

def relink_pegs(company=None):
	"""Reconnect open pegs to their purchase order, receipt and batch."""
	filters = {"docstatus": 1, "status": ["not in", ["Closed", "Cancelled"]]}
	if company:
		filters["company"] = company

	fixed = 0
	for name in frappe.get_all("Order Cost Peg", filters=filters, pluck="name"):
		peg = frappe.get_doc("Order Cost Peg", name)
		changed = False

		if not peg.purchase_order:
			po_line = _find_purchase_line(peg)
			if po_line:
				peg.purchase_order = po_line.parent
				peg.purchase_order_item = po_line.name
				peg.supplier = frappe.db.get_value("Purchase Order", po_line.parent, "supplier")
				peg.purchase_rate = flt(po_line.base_rate) / (flt(po_line.conversion_factor) or 1)
				changed = True

		if peg.purchase_order and not peg.batch_no:
			batch = frappe.db.get_value(
				"Batch",
				{
					"item": peg.item_code,
					"custom_noc_source_purchase_order": peg.purchase_order,
					"disabled": 0,
				},
				"name",
				order_by="creation desc",
			)
			if batch:
				peg.batch_no = batch
				changed = True

		if peg.batch_no and not peg.qty_received:
			received = _received_against(peg)
			if received:
				peg.qty_received = received["qty"]
				peg.received_rate = received["rate"]
				peg.stock_document_type = received["doctype"]
				peg.stock_document = received["name"]
				changed = True

		if changed:
			from neotec_order_costing.api.peg import save_peg

			save_peg(peg)
			fixed += 1

	_log("Relinked {0} cost peg(s).".format(fixed))
	return fixed


def _find_purchase_line(peg):
	rows = frappe.get_all(
		"Purchase Order Item",
		filters={
			"item_code": peg.item_code,
			"sales_order": peg.sales_order,
			"docstatus": 1,
		},
		fields=["name", "parent", "base_rate", "conversion_factor"],
		order_by="creation asc",
		limit=1,
	)
	if rows:
		return rows[0]

	if not peg.sales_order_item:
		return None
	rows = frappe.get_all(
		"Purchase Order Item",
		filters={"sales_order_item": peg.sales_order_item, "docstatus": 1},
		fields=["name", "parent", "base_rate", "conversion_factor"],
		limit=1,
	)
	return rows[0] if rows else None


def _received_against(peg):
	for doctype, child in (("Purchase Receipt", "Purchase Receipt Item"),
						   ("Purchase Invoice", "Purchase Invoice Item")):
		rows = frappe.get_all(
			child,
			filters={"purchase_order_item": peg.purchase_order_item, "docstatus": 1},
			fields=["name", "parent", "stock_qty", "qty", "valuation_rate", "base_rate"],
			limit=1,
		)
		if rows:
			row = rows[0]
			qty = flt(row.stock_qty or row.qty)
			return {
				"doctype": doctype,
				"name": row.parent,
				"qty": qty,
				"rate": flt(row.valuation_rate) or flt(row.base_rate),
			}
	return None


# ---------------------------------------------------------------------------

def fix_batchwise_valuation():
	"""Batches this app created must value themselves, otherwise pegging is
	cosmetic and the moving average still applies."""
	names = frappe.get_all(
		"Batch",
		filters={"custom_noc_generated": 1, "use_batchwise_valuation": 0},
		pluck="name",
	)
	blocked = []
	for name in names:
		item = frappe.db.get_value("Batch", name, "item")
		if frappe.db.exists(
			"Stock Ledger Entry",
			{"item_code": item, "is_cancelled": 0, "batch_no": ["in", ["", None]]},
		):
			blocked.append((name, item))
			continue
		frappe.db.set_value("Batch", name, "use_batchwise_valuation", 1, update_modified=False)

	_log("Enabled batchwise valuation on {0} batch(es).".format(len(names) - len(blocked)))
	if blocked:
		items = sorted({i for _n, i in blocked})
		frappe.msgprint(
			"These items still hold stock with no batch, so batchwise valuation cannot "
			"be enabled for them: {0}. Clear the un-batched balance with a Stock "
			"Reconciliation into an opening batch, then run the repair again.".format(
				", ".join(items)
			),
			indicator="red", title="Batchwise Valuation Blocked",
		)
	return {"fixed": len(names) - len(blocked), "blocked": blocked}


# ---------------------------------------------------------------------------

def check_configuration():
	"""Flags settings combinations that cannot work together."""
	s = frappe.get_single("Order Costing Settings")
	issues = []

	if s.enable_auto_batch and s.auto_batch_applies_to != "Stock Inward Document":
		issues.append(
			"Create Batch On is '{0}'. Only Stock Inward Document is implemented; "
			"set it to that.".format(s.auto_batch_applies_to)
		)
	if s.enable_procurement_split and s.require_material_request and \
			s.split_target == "Purchase Order Only":
		issues.append(
			"Require Material Request Before PO is on while Split Applies To is "
			"'Purchase Order Only'. Purchase order creation will be blocked with no "
			"way to raise the material request. Set Split Applies To to 'Material "
			"Request and Purchase Order', or turn off the material request requirement."
		)
	if s.enable_addon_handling and not (s.addon_item_groups or "").strip():
		issues.append(
			"Add-on Item Groups is blank, so every invoice line without a sales order "
			"link is treated as an add-on. Name the upgrade item groups explicitly."
		)
	if s.include_draft_documents:
		issues.append(
			"Include Draft Documents in Report is on. Profitability will include "
			"unsubmitted invoices."
		)
	if s.costing_mode == "Pegged PO Rate" and not s.post_cost_variance:
		issues.append(
			"Pegged PO Rate without a variance journal leaves reported COGS and the "
			"general ledger disagreeing."
		)

	if issues:
		frappe.msgprint(
			"<ol>{0}</ol>".format("".join("<li>{0}</li>".format(i) for i in issues)),
			title="Configuration Issues", indicator="orange",
		)
	else:
		_log("Configuration looks consistent.")
	return issues


# ---------------------------------------------------------------------------

@frappe.whitelist()
def run(company=None):
	frappe.only_for(["System Manager", "Stock Manager"])
	result = {
		"configuration": check_configuration(),
		"batches": fix_batchwise_valuation(),
		"pegs": relink_pegs(company),
	}
	frappe.db.commit()
	return result


# ---------------------------------------------------------------------------
# Installed version and schema health
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_app_info():
	"""Reports the installed code version alongside the fields that actually
	exist in the database, so a missing feature can be diagnosed as a skipped
	migration rather than a missing build."""
	import neotec_order_costing

	meta = frappe.get_meta("Order Costing Settings")
	present = {f.fieldname for f in meta.fields}

	expected = {
		"0.2.0": ["enable_specifications", "allow_superseded_substitution", "supplier_resolution"],
		"0.2.2": ["allow_destructive_cleanup"],
	}
	missing = {}
	for version, fields in expected.items():
		gap = [f for f in fields if f not in present]
		if gap:
			missing[version] = gap

	from neotec_order_costing.install import verify_schema

	field_check = verify_schema(log_only=True)
	if field_check.get("missing"):
		missing["custom fields"] = [
			"{0}: {1}".format(dt, ", ".join(f))
			for dt, f in field_check["missing"].items()
		]

	return {
		"code_version": neotec_order_costing.__version__,
		"schema_current": not missing,
		"missing_fields": missing,
		"doctypes_installed": frappe.db.count(
			"DocType", {"module": "Neotec Order Costing"}
		),
	}


# ---------------------------------------------------------------------------
# Batch diagnostics
# ---------------------------------------------------------------------------

@frappe.whitelist()
def diagnose_batches(batches):
	"""Explains why a batch has no quantity or no valuation."""
	frappe.only_for(["System Manager", "Stock Manager", "Stock User"])
	batches = frappe.parse_json(batches) if isinstance(batches, str) else batches

	out = []
	for name in batches or []:
		row = frappe.db.get_value(
			"Batch", name, ["item", "use_batchwise_valuation", "disabled"], as_dict=True
		)
		if not row:
			out.append({"batch": name, "item": None, "qty_in": 0, "qty_out": 0,
						"incoming_rate": 0, "batchwise": 0, "note": "Batch does not exist"})
			continue

		sle = frappe.db.sql(
			"""
			select
				sum(case when actual_qty > 0 then actual_qty else 0 end) as qty_in,
				sum(case when actual_qty < 0 then -actual_qty else 0 end) as qty_out,
				sum(case when actual_qty > 0 then stock_value_difference else 0 end) as value_in
			from `tabStock Ledger Entry`
			where batch_no = %s and is_cancelled = 0
			""", name, as_dict=True,
		)[0]

		qty_in = flt(sle.qty_in)
		rate = (flt(sle.value_in) / qty_in) if qty_in else 0

		notes = []
		if not qty_in:
			notes.append(
				"No inward stock ledger entry. The receipt was never submitted, was "
				"cancelled, or posted against a different batch."
			)
		if not row.use_batchwise_valuation:
			notes.append(
				"Batchwise valuation is off, so this batch has no rate of its own and "
				"costing falls back to the item's moving average."
			)
		if row.disabled:
			notes.append("Batch is disabled.")

		out.append({
			"batch": name,
			"item": row.item,
			"qty_in": qty_in,
			"qty_out": flt(sle.qty_out),
			"incoming_rate": round(rate, 4),
			"batchwise": int(row.use_batchwise_valuation or 0),
			"note": " ".join(notes),
		})
	return out
