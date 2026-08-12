"""Connections shown in the document's Connections tab, so procurement and
costing documents are creatable and traceable from where the user already is.
"""

from frappe import _


def _merge(data, group_label, items, link_fieldname):
	data.setdefault("transactions", [])
	data["transactions"].append({"label": _(group_label), "items": items})
	data.setdefault("non_standard_fieldnames", {})
	for item in items:
		data["non_standard_fieldnames"][item] = link_fieldname
	return data


def sales_order_dashboard(data=None):
	data = data or {}
	data.setdefault("fieldname", "sales_order")
	data.setdefault("transactions", [])
	data["transactions"].append({
		"label": _("Order Costing"),
		"items": ["Order Cost Peg"],
	})
	data.setdefault("non_standard_fieldnames", {})
	data["non_standard_fieldnames"]["Order Cost Peg"] = "sales_order"
	return data


def purchase_order_dashboard(data=None):
	data = data or {}
	data.setdefault("fieldname", "purchase_order")
	data.setdefault("transactions", [])
	data["transactions"].append({
		"label": _("Order Costing"),
		"items": ["Order Cost Peg"],
	})
	data.setdefault("non_standard_fieldnames", {})
	data["non_standard_fieldnames"]["Order Cost Peg"] = "purchase_order"
	return data


def batch_dashboard(data=None):
	data = data or {}
	data.setdefault("fieldname", "batch_no")
	data.setdefault("transactions", [])
	data["transactions"].append({
		"label": _("Order Costing"),
		"items": ["Order Cost Peg"],
	})
	data.setdefault("non_standard_fieldnames", {})
	data["non_standard_fieldnames"]["Order Cost Peg"] = "batch_no"
	return data


def item_dashboard(data=None):
	data = data or {}
	data.setdefault("fieldname", "base_item")
	data.setdefault("transactions", [])
	data["transactions"].append({
		"label": _("Part Number"),
		"items": ["As Built Configuration", "Part Substitution Log"],
	})
	data.setdefault("non_standard_fieldnames", {})
	data["non_standard_fieldnames"]["As Built Configuration"] = "base_item"
	data["non_standard_fieldnames"]["Part Substitution Log"] = "original_item"
	return data
