import frappe
from frappe.model.document import Document


class SpecificationAttribute(Document):
	def validate(self):
		if self.datatype == "Select" and not self.options:
			frappe.throw("Select attributes need a list of options.")
		if self.is_numeric_aggregatable and self.datatype not in ("Float", "Int"):
			frappe.throw(
				"Only Float or Int attributes can be aggregatable. "
				"An add-on cannot arithmetically add to a text value."
			)
