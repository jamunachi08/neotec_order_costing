"""Part number specifications.

A part number is an Item. Its specification is a structured, bilingual,
ordered list of attribute/value pairs that can be printed, compared against
another part number, and modified by add-on items at delivery time.
"""

import frappe
from frappe.utils import cint, cstr, flt

from neotec_order_costing.neotec_order_costing.doctype.specification_template.specification_template import (
	resolve_template,
)


# ---------------------------------------------------------------------------
# Template application
# ---------------------------------------------------------------------------

def apply_template(doc, method=None):
	"""Hook on Item validate. Seeds missing attribute rows from the template
	so no part number is created half-specified."""
	if doc.get("is_stock_item") is not None and not doc.is_stock_item:
		return

	template_name = doc.get("custom_noc_spec_template") or resolve_template(
		doc.item_group, doc.get("brand")
	)
	if not template_name:
		return

	template = frappe.get_cached_doc("Specification Template", template_name)
	if doc.is_new() and template.auto_apply_on_item_insert:
		doc.custom_noc_spec_template = template_name
	if doc.get("custom_noc_spec_template") != template_name:
		return

	existing = {r.attribute for r in doc.get("custom_noc_specifications", [])}
	for row in sorted(template.attributes, key=lambda r: r.display_order or r.idx):
		if row.attribute in existing:
			continue
		attr = frappe.get_cached_doc("Specification Attribute", row.attribute)
		doc.append("custom_noc_specifications", {
			"attribute": row.attribute,
			"label_en": attr.label_en,
			"label_ar": attr.label_ar,
			"value_en": row.default_value,
			"uom": attr.uom,
			"display_order": row.display_order or (row.idx * 10),
			"show_to_customer": attr.show_to_customer,
		})

	if template.enforce_mandatory:
		mandatory = {r.attribute for r in template.attributes if r.is_mandatory}
		filled = {
			r.attribute for r in doc.get("custom_noc_specifications", [])
			if cstr(r.value_en).strip()
		}
		missing = mandatory - filled
		if missing:
			labels = [
				frappe.get_cached_value("Specification Attribute", a, "label_en")
				for a in sorted(missing)
			]
			frappe.throw(
				"Specification template {0} requires these attributes on part number {1}: {2}".format(
					template_name, doc.name or doc.item_code, ", ".join(labels)
				)
			)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def get_specifications(item_code, customer_visible_only=False, key_only=False):
	rows = frappe.get_all(
		"Item Specification",
		filters={"parent": item_code, "parenttype": "Item"},
		fields=["attribute", "label_en", "label_ar", "value_en", "value_ar",
				"uom", "display_order", "show_to_customer"],
		order_by="display_order asc, idx asc",
	)
	out = []
	for r in rows:
		if customer_visible_only and not r.show_to_customer:
			continue
		if not cstr(r.value_en).strip():
			continue
		if key_only:
			if not frappe.get_cached_value("Specification Attribute", r.attribute, "is_key_spec"):
				continue
		out.append(r)
	return out


def get_part_numbers(item_code, customer=None, supplier=None):
	"""Every identifier this part is known by."""
	out = {"item_code": item_code}
	out["manufacturer_part_no"] = frappe.db.get_value(
		"Item Manufacturer", {"item_code": item_code}, "manufacturer_part_no"
	)
	out["manufacturer"] = frappe.db.get_value(
		"Item Manufacturer", {"item_code": item_code}, "manufacturer"
	)
	filters = {"parent": item_code, "parenttype": "Item"}
	if supplier:
		filters["supplier"] = supplier
	out["supplier_part_no"] = frappe.db.get_value("Item Supplier", filters, "supplier_part_no")
	cust_filters = {"parent": item_code, "parenttype": "Item"}
	if customer:
		cust_filters["customer_name"] = customer
	out["customer_part_no"] = frappe.db.get_value("Item Customer Detail", cust_filters, "ref_code")
	return out


@frappe.whitelist()
def get_part_numbers_for_print(item_code, customer=None, supplier=None):
	return get_part_numbers(item_code, customer=customer, supplier=supplier)


@frappe.whitelist()
def get_item_specifications(item_code, customer_visible_only=1):
	return get_specifications(item_code, customer_visible_only=cint(customer_visible_only))


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def compare(item_a, item_b):
	"""Used by the substitution log to show the customer what changed."""
	a = {r["attribute"]: r for r in get_specifications(item_a)}
	b = {r["attribute"]: r for r in get_specifications(item_b)}
	rows = []
	for attribute in sorted(set(a) | set(b), key=lambda k: (a.get(k) or b.get(k)).get("display_order") or 0):
		va = (a.get(attribute) or {}).get("value_en")
		vb = (b.get(attribute) or {}).get("value_en")
		if cstr(va) == cstr(vb):
			continue
		label = (a.get(attribute) or b.get(attribute)).get("label_en")
		rows.append({"attribute": attribute, "label": label, "ordered": va, "supplied": vb})
	return rows


def render_comparison(item_a, item_b):
	rows = compare(item_a, item_b)
	if not rows:
		return "<p>No specification differences.</p>"
	body = "".join(
		"<tr><td>{0}</td><td>{1}</td><td>{2}</td></tr>".format(
			frappe.utils.escape_html(cstr(r["label"])),
			frappe.utils.escape_html(cstr(r["ordered"] or "-")),
			frappe.utils.escape_html(cstr(r["supplied"] or "-")),
		)
		for r in rows
	)
	return (
		"<table class='table table-bordered'><thead><tr>"
		"<th>Attribute</th><th>Ordered ({0})</th><th>Supplied ({1})</th>"
		"</tr></thead><tbody>{2}</tbody></table>".format(
			frappe.utils.escape_html(item_a), frappe.utils.escape_html(item_b), body
		)
	)


# ---------------------------------------------------------------------------
# Arithmetic for add-on modifications
# ---------------------------------------------------------------------------

def apply_modification(current_value, addon_value, mode, qty=1, aggregatable=False):
	if mode == "Replace":
		return cstr(addon_value)
	if mode == "Append":
		parts = [p for p in (cstr(current_value), cstr(addon_value)) if p]
		return " + ".join(parts)
	if mode == "Remove":
		return ""
	if mode == "Add":
		if not aggregatable:
			parts = [p for p in (cstr(current_value), cstr(addon_value)) if p]
			return " + ".join(parts)
		base = _numeric(current_value)
		delta = _numeric(addon_value) * flt(qty or 1)
		total = base + delta
		return "{0:g}".format(total)
	return cstr(current_value)


def _numeric(value):
	import re

	match = re.search(r"-?\d+(?:\.\d+)?", cstr(value))
	return flt(match.group()) if match else 0.0


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_spec_block(rows, bilingual=True, highlight_modified=False, compact=False):
	if not rows:
		return ""
	cells = []
	for r in rows:
		get = r.get if isinstance(r, dict) else lambda k, d=None: getattr(r, k, d)
		label = get("label_en") or ""
		label_ar = get("label_ar") or ""
		value = cstr(get("value_en") or "")
		value_ar = cstr(get("value_ar") or "")
		uom = get("uom") or ""
		if uom and value:
			value = "{0} {1}".format(value, uom)
		modified = highlight_modified and cint(get("is_modified") or 0)

		label_html = frappe.utils.escape_html(label)
		if bilingual and label_ar:
			label_html += " <span dir='rtl' style='color:#73726c'>{0}</span>".format(
				frappe.utils.escape_html(label_ar)
			)
		value_html = frappe.utils.escape_html(value)
		if bilingual and value_ar:
			value_html += " <span dir='rtl' style='color:#73726c'>{0}</span>".format(
				frappe.utils.escape_html(value_ar)
			)
		if modified:
			value_html = "<b>{0}</b> <span style='color:#185FA5;font-size:90%'>(upgraded)</span>".format(
				value_html
			)
		cells.append(
			"<tr><td style='width:38%;color:#5F5E5A'>{0}</td><td>{1}</td></tr>".format(
				label_html, value_html
			)
		)

	style = "font-size:90%" if compact else ""
	return (
		"<table class='noc-spec-block' style='width:100%;border-collapse:collapse;{0}'>"
		"<tbody>{1}</tbody></table>".format(style, "".join(cells))
	)


@frappe.whitelist()
def get_spec_html(item_code, customer_visible_only=1, compact=0):
	rows = get_specifications(item_code, customer_visible_only=cint(customer_visible_only))
	return render_spec_block(rows, compact=cint(compact))
