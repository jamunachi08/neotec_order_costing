import frappe
from frappe.model.document import Document


class BatchNamingComponent(Document):
	def validate(self):
		if self.component == "Static Text" and not self.static_value:
			frappe.throw("Static Text component needs a value in row {0}".format(self.idx))
