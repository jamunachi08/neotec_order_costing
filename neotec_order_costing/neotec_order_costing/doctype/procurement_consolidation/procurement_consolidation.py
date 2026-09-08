import frappe
from frappe.model.document import Document
from frappe.utils import flt, nowdate

from neotec_order_costing.api.consolidation import (
	build_summary,
	create_documents,
	fetch_demand,
)


class ProcurementConsolidation(Document):
	def validate(self):
		self.consolidation_date = self.consolidation_date or nowdate()
		self.refresh_summary()
		self.set_totals()
		if self.docstatus == 0:
			self.status = "Demand Fetched" if self.items else "Draft"

	def on_submit(self):
		if not self.items:
			frappe.throw("Fetch demand before submitting.")
		created = create_documents(self)
		if not created:
			frappe.throw(
				"No documents could be created. Check that each summary row has a supplier."
			)
		self.db_set("created_documents", "\n".join(
			"{0}: {1} ({2})".format(c["doctype"], c["name"], c["group"]) for c in created
		))
		self.db_set("status", "Ordered")
		frappe.msgprint(
			"<br>".join(
				frappe.utils.get_link_to_form(c["doctype"], c["name"]) for c in created
			),
			title="Created {0} Document(s)".format(len(created)), indicator="green",
		)

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	# ------------------------------------------------------------------
	@frappe.whitelist()
	def fetch(self):
		"""Pull open material request demand matching the filters."""
		self.check_permission("write")
		rows = fetch_demand(
			self.company,
			brand=self.brand,
			item_group=self.item_group,
			supplier=self.supplier,
			from_date=self.from_date,
			to_date=self.to_date,
			warehouse=self.warehouse,
			include_unlinked_requests=self.include_unlinked_requests,
		)
		self.items = []
		for row in rows:
			row["select_row"] = 1
			self.append("items", row)
		self.refresh_summary()
		self.set_totals()
		self.status = "Demand Fetched" if self.items else "Draft"
		return len(rows)

	def refresh_summary(self):
		rows = [r.as_dict() for r in self.items]
		self.summary = []
		for row in build_summary(rows, self.group_by, self.company):
			self.append("summary", row)
		self.recalculate_savings()

	@frappe.whitelist()
	def recalculate_savings(self):
		for row in self.summary:
			last = flt(row.last_purchase_rate)
			target = flt(row.target_rate)
			row.expected_saving = (last - target) * flt(row.total_qty) if last and target else 0

	def set_totals(self):
		self.total_qty = sum(flt(r.qty_to_order) for r in self.items if r.select_row)
		self.total_orders = len({r.sales_order for r in self.items if r.sales_order and r.select_row})
		self.total_expected_saving = sum(flt(r.expected_saving) for r in self.summary)
