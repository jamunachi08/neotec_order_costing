import frappe

from neotec_order_costing.api import repair


def execute():
	"""0.2.0 could not update a peg after submit, so pegs were left at their
	creation values and batches were created without batchwise valuation."""
	if not frappe.db.exists("DocType", "Order Cost Peg"):
		return
	repair.fix_batchwise_valuation()
	repair.relink_pegs()
