import frappe
from frappe.model.document import Document

from neotec_order_costing.api.field_catalog import FIELD_CATALOG, is_valid_field


class ProfitabilityReportProfile(Document):
	def validate(self):
		self.validate_fields()
		self.set_labels()
		self.enforce_single_default()

	def validate_fields(self):
		seen = set()
		for row in self.fields:
			key = (row.source_document, row.fieldname)
			if key in seen:
				frappe.throw(
					"Duplicate column {0} from {1} in row {2}".format(
						row.fieldname, row.source_document, row.idx
					)
				)
			seen.add(key)
			if not is_valid_field(row.source_document, row.fieldname):
				frappe.throw(
					"{0} is not an available field on {1} (row {2}). "
					"Use the Add Columns button to pick from the catalog.".format(
						row.fieldname, row.source_document, row.idx
					)
				)

	def set_labels(self):
		for row in self.fields:
			if row.label:
				continue
			meta = FIELD_CATALOG.get(row.source_document, {}).get(row.fieldname, {})
			row.label = meta.get("label") or frappe.unscrub(row.fieldname)
			row.fieldtype = row.fieldtype or meta.get("fieldtype") or "Data"
			row.options = row.options or meta.get("options")

	def enforce_single_default(self):
		if not self.is_default:
			return
		frappe.db.sql(
			"update `tabProfitability Report Profile` set is_default = 0 where name != %s",
			self.name,
		)


@frappe.whitelist()
def get_catalog():
	"""Feeds the column picker dialog."""
	out = {}
	for doctype, fields in FIELD_CATALOG.items():
		out[doctype] = [
			{
				"fieldname": fieldname,
				"label": meta.get("label") or frappe.unscrub(fieldname),
				"fieldtype": meta.get("fieldtype", "Data"),
				"options": meta.get("options"),
				"width": meta.get("width", 120),
			}
			for fieldname, meta in fields.items()
		]
	return out


@frappe.whitelist()
def add_fields(profile, selections):
	"""selections is a list of {source_document, fieldname}."""
	frappe.only_for(["System Manager", "Sales Manager", "Accounts Manager", "Stock Manager"])
	selections = frappe.parse_json(selections) if isinstance(selections, str) else selections
	doc = frappe.get_doc("Profitability Report Profile", profile)
	existing = {(r.source_document, r.fieldname) for r in doc.fields}
	added = 0
	for sel in selections:
		key = (sel.get("source_document"), sel.get("fieldname"))
		if key in existing:
			continue
		meta = FIELD_CATALOG.get(key[0], {}).get(key[1], {})
		doc.append(
			"fields",
			{
				"source_document": key[0],
				"fieldname": key[1],
				"label": meta.get("label") or frappe.unscrub(key[1]),
				"fieldtype": meta.get("fieldtype", "Data"),
				"options": meta.get("options"),
				"width": meta.get("width", 120),
				"is_visible": 1,
			},
		)
		added += 1
	doc.save()
	return {"added": added, "total": len(doc.fields)}
