import frappe
from frappe.model.document import Document


class SpecificationTemplate(Document):
	def validate(self):
		self.validate_scope()
		self.dedupe()

	def validate_scope(self):
		if self.applies_to in ("Item Group", "Item Group and Brand") and not self.item_group:
			frappe.throw("Item Group is required for this scope.")
		if self.applies_to in ("Brand", "Item Group and Brand") and not self.brand:
			frappe.throw("Brand is required for this scope.")

	def dedupe(self):
		seen = set()
		for row in self.attributes:
			if row.attribute in seen:
				frappe.throw("Attribute {0} appears twice.".format(row.attribute))
			seen.add(row.attribute)
			if not row.display_order:
				row.display_order = row.idx * 10

	def on_update(self):
		frappe.cache().delete_key("noc_spec_templates")


def resolve_template(item_group=None, brand=None):
	"""Most specific scope wins: Item Group and Brand, then Brand, then Item
	Group, then All Items."""
	candidates = frappe.get_all(
		"Specification Template",
		filters={"enabled": 1},
		fields=["name", "applies_to", "item_group", "brand"],
	)
	ranked = []
	for c in candidates:
		if c.applies_to == "Item Group and Brand":
			if c.item_group == item_group and c.brand == brand:
				ranked.append((0, c.name))
		elif c.applies_to == "Brand":
			if c.brand == brand:
				ranked.append((1, c.name))
		elif c.applies_to == "Item Group":
			if c.item_group == item_group:
				ranked.append((2, c.name))
		elif c.applies_to == "All Items":
			ranked.append((3, c.name))
	if not ranked:
		return None
	return sorted(ranked)[0][1]
