import frappe
from frappe.model.document import Document
from frappe.utils import flt


class OrderCostPeg(Document):
	def validate(self):
		self.set_effective_cost_rate()
		self.set_open_qty()
		self.set_status()

	def on_submit(self):
		self.db_set("status", self.status)

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	# ------------------------------------------------------------------ costing
	def set_effective_cost_rate(self):
		"""Landed rate beats received rate beats purchase order rate. In
		Pegged PO Rate mode we deliberately stay on the PO rate."""
		if self.costing_mode_applied == "Pegged PO Rate":
			self.effective_cost_rate = flt(self.purchase_rate)
		else:
			self.effective_cost_rate = (
				flt(self.landed_rate) or flt(self.received_rate) or flt(self.purchase_rate)
			)

	def set_open_qty(self):
		self.qty_open = flt(self.qty_pegged) - flt(self.qty_delivered)

	def set_status(self):
		if self.docstatus == 2:
			self.status = "Cancelled"
		elif self.docstatus == 0:
			self.status = "Draft"
		elif flt(self.qty_delivered) >= flt(self.qty_pegged) and flt(self.qty_pegged) > 0:
			self.status = "Closed"
		elif flt(self.qty_delivered) > 0:
			self.status = "Partially Delivered"
		elif flt(self.qty_received) > 0:
			self.status = "Received"
		elif self.purchase_order:
			self.status = "Ordered"
		else:
			self.status = "Open"

	# ------------------------------------------------------------------ helpers
	def save_update(self):
		"""Persist a post-submit change to the peg.

		Deliberately not named _save: frappe.model.document.Document.save()
		delegates to self._save(ignore_permissions, ignore_version), so a
		controller method of that name shadows the base class and breaks every
		save, submit and cancel on the doctype.
		"""
		self.flags.ignore_permissions = True
		self.flags.ignore_validate_update_after_submit = True
		self.save(ignore_permissions=True)

	def register_delivery(self, doc, item, batch_no, qty, cost_rate):
		self.append(
			"deliveries",
			{
				"delivery_document_type": doc.doctype,
				"delivery_document": doc.name,
				"delivery_detail": item.name,
				"batch_no": batch_no,
				"qty": flt(qty),
				"cost_rate": flt(cost_rate),
				"posting_date": doc.posting_date,
			},
		)
		self.qty_delivered = flt(self.qty_delivered) + flt(qty)
		self.set_open_qty()
		self.set_status()
		self.save_update()

	def release_delivery(self, doc):
		remaining = []
		released = 0.0
		for row in self.deliveries:
			if row.delivery_document_type == doc.doctype and row.delivery_document == doc.name:
				released += flt(row.qty)
			else:
				remaining.append(row)
		if not released:
			return
		self.deliveries = []
		for row in remaining:
			self.append("deliveries", row.as_dict())
		self.qty_delivered = max(flt(self.qty_delivered) - released, 0.0)
		self.set_open_qty()
		self.set_status()
		self.save_update()


def get_peg(sales_order_item=None, purchase_order_item=None, docstatus=1):
	filters = {"docstatus": docstatus}
	if sales_order_item:
		filters["sales_order_item"] = sales_order_item
	if purchase_order_item:
		filters["purchase_order_item"] = purchase_order_item
	name = frappe.db.get_value("Order Cost Peg", filters, "name")
	return frappe.get_doc("Order Cost Peg", name) if name else None
