import frappe
from frappe.model.document import Document


class AsBuiltConfiguration(Document):
	def validate(self):
		for idx, row in enumerate(self.specifications):
			if not row.display_order:
				row.display_order = (idx + 1) * 10

	def render(self):
		from neotec_order_costing.api.specs import render_spec_block

		rows = [r for r in self.specifications if r.show_to_customer]
		self.spec_html = render_spec_block(rows, highlight_modified=True)
		return self.spec_html
