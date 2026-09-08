"""End-to-end simulation of the two-salesman laptop scenario.

Run on a test bench only:

	bench --site testneo.frappe.cloud execute \
		neotec_order_costing.simulation.run --kwargs "{'company': 'Your Co'}"

It proves the core claim: without pegging both orders cost 1,872.73 per HP
laptop; with pegging, A costs 2,000 and B costs 1,800.
"""

import frappe
from frappe.utils import flt, nowdate

BRANDS = {"HP": "HP", "Dell": "Dell", "Kingston": "Kingston"}

SPEC_ATTRS = [
	("processor", "Processor", "المعالج", "Data", 10, 1, 0),
	("ram", "RAM", "الذاكرة", "Float", 20, 1, 1),
	("storage", "Storage", "التخزين", "Data", 30, 1, 0),
	("display", "Display", "الشاشة", "Data", 40, 1, 0),
	("warranty", "Warranty", "الضمان", "Data", 50, 0, 0),
]


def _log(msg):
	print("[order-costing] {0}".format(msg))


def _ensure(doctype, name, values):
	if frappe.db.exists(doctype, name):
		return frappe.get_doc(doctype, name)
	doc = frappe.new_doc(doctype)
	doc.update(values)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc


def setup_specifications():
	for name, label_en, label_ar, datatype, order, key, agg in SPEC_ATTRS:
		_ensure("Specification Attribute", name, {
			"attribute_name": name, "label_en": label_en, "label_ar": label_ar,
			"datatype": datatype, "display_order": order, "is_key_spec": key,
			"is_numeric_aggregatable": agg, "show_to_customer": 1,
			"uom": "Nos" if datatype == "Float" else None,
		})

	if not frappe.db.exists("Specification Template", "Business Laptop"):
		tpl = frappe.new_doc("Specification Template")
		tpl.template_name = "Business Laptop"
		tpl.applies_to = "Item Group"
		tpl.item_group = "Laptops"
		tpl.enforce_mandatory = 0
		tpl.auto_apply_on_item_insert = 1
		for name, _en, _ar, _dt, order, _k, _a in SPEC_ATTRS:
			tpl.append("attributes", {"attribute": name, "is_mandatory": 1, "display_order": order})
		tpl.flags.ignore_permissions = True
		tpl.insert(ignore_permissions=True)


def _set_specs(item_code, values):
	item = frappe.get_doc("Item", item_code)
	item.custom_noc_specifications = []
	for attribute, value_en, value_ar in values:
		attr = frappe.get_cached_doc("Specification Attribute", attribute)
		item.append("custom_noc_specifications", {
			"attribute": attribute, "label_en": attr.label_en, "label_ar": attr.label_ar,
			"value_en": value_en, "value_ar": value_ar, "uom": attr.uom,
			"display_order": attr.display_order, "show_to_customer": 1,
		})
	item.save(ignore_permissions=True)


def setup_masters(company, warehouse):
	for brand in BRANDS:
		_ensure("Brand", brand, {"brand": brand})

	_ensure("Item Group", "Laptops", {"item_group_name": "Laptops", "parent_item_group": "All Item Groups", "is_group": 0})
	_ensure("Item Group", "Upgrades", {"item_group_name": "Upgrades", "parent_item_group": "All Item Groups", "is_group": 0})

	items = [
		("SIM-HP-6N4C2EA", "HP EliteBook 640 G11", "HP", "Laptops"),
		("SIM-HP-8A4T1EA", "HP EliteBook 640 G11 (replacement)", "HP", "Laptops"),
		("SIM-DELL-LAT5450", "Dell Latitude 5450", "Dell", "Laptops"),
		("SIM-KST-16GB", "Kingston 16GB DDR5 Module", "Kingston", "Upgrades"),
	]
	for code, name, brand, group in items:
		_ensure("Item", code, {
			"item_code": code, "item_name": name, "item_group": group, "brand": brand,
			"stock_uom": "Nos", "is_stock_item": 1, "has_batch_no": 1,
			"create_new_batch": 0, "include_item_in_manufacturing": 0,
			"item_defaults": [{"company": company, "default_warehouse": warehouse}],
		})

	_ensure("Supplier", "SIM-HP-VENDOR", {"supplier_name": "SIM-HP-VENDOR", "supplier_group": "All Supplier Groups"})
	_ensure("Supplier", "SIM-DELL-VENDOR", {"supplier_name": "SIM-DELL-VENDOR", "supplier_group": "All Supplier Groups"})
	_ensure("Customer", "SIM-CORP-CUSTOMER", {"customer_name": "SIM-CORP-CUSTOMER", "customer_group": "All Customer Groups", "territory": "All Territories"})

	_ensure("Supplier", "SIM-KST-VENDOR", {"supplier_name": "SIM-KST-VENDOR",
										   "supplier_group": "All Supplier Groups"})

	for code, supplier in (("SIM-HP-6N4C2EA", "SIM-HP-VENDOR"), ("SIM-HP-8A4T1EA", "SIM-HP-VENDOR"),
						   ("SIM-KST-16GB", "SIM-KST-VENDOR"),
						   ("SIM-DELL-LAT5450", "SIM-DELL-VENDOR")):
		item = frappe.get_doc("Item", code)
		if not any(d.company == company and d.default_supplier for d in item.item_defaults):
			for d in item.item_defaults:
				if d.company == company:
					d.default_supplier = supplier
			item.save(ignore_permissions=True)

	# part numbers, specifications, equivalence and add-on behaviour
	for code, mfr_part in (("SIM-HP-6N4C2EA", "6N4C2EA"), ("SIM-HP-8A4T1EA", "8A4T1EA"),
						   ("SIM-DELL-LAT5450", "LAT5450-i7"), ("SIM-KST-16GB", "KVR56S46BS8-16")):
		_ensure("Manufacturer", code.split("-")[1], {"short_name": code.split("-")[1]})
		if not frappe.db.exists("Item Manufacturer", {"item_code": code}):
			frappe.get_doc({
				"doctype": "Item Manufacturer", "item_code": code,
				"manufacturer": code.split("-")[1], "manufacturer_part_no": mfr_part,
			}).insert(ignore_permissions=True)

	_set_specs("SIM-HP-6N4C2EA", [
		("processor", "Intel Core Ultra 7 155U", "إنتل كور ألترا 7"),
		("ram", "8", "8"),
		("storage", "512GB NVMe SSD", "512 جيجابايت"),
		("display", "14 inch WUXGA", "14 بوصة"),
		("warranty", "3 years onsite", "3 سنوات"),
	])
	_set_specs("SIM-HP-8A4T1EA", [
		("processor", "Intel Core Ultra 7 165U", "إنتل كور ألترا 7"),
		("ram", "8", "8"),
		("storage", "512GB NVMe SSD", "512 جيجابايت"),
		("display", "14 inch WUXGA", "14 بوصة"),
		("warranty", "3 years onsite", "3 سنوات"),
	])
	_set_specs("SIM-DELL-LAT5450", [
		("processor", "Intel Core Ultra 5 135U", "إنتل كور ألترا 5"),
		("ram", "16", "16"),
		("storage", "256GB NVMe SSD", "256 جيجابايت"),
		("display", "14 inch FHD", "14 بوصة"),
		("warranty", "3 years onsite", "3 سنوات"),
	])

	old = frappe.get_doc("Item", "SIM-HP-6N4C2EA")
	old.custom_noc_part_equivalence = []
	old.append("custom_noc_part_equivalence", {
		"equivalent_item": "SIM-HP-8A4T1EA", "relation": "Superseded By",
		"effective_from": "2026-08-03", "notes": "Simulation supersession",
	})
	old.save(ignore_permissions=True)

	ram = frappe.get_doc("Item", "SIM-KST-16GB")
	ram.custom_noc_modifies_attribute = "ram"
	ram.custom_noc_modification_mode = "Add"
	ram.custom_noc_modification_value = "16"
	ram.save(ignore_permissions=True)

	for sp in ("Salesman A", "Salesman B"):
		_ensure("Sales Person", sp, {"sales_person_name": sp, "is_group": 0,
									 "parent_sales_person": "Sales Team"})


def configure_settings():
	s = frappe.get_single("Order Costing Settings")
	s.enable_order_wise_cogs = 1
	s.costing_mode = "Pegged Batch Valuation"
	s.shortfall_behaviour = "Fallback to Default Valuation with Warning"
	s.procurement_flow = "Auto Detect"
	s.enable_auto_batch = 1
	s.auto_batch_applies_to = "Stock Inward Document"
	s.batch_separator = "-"
	s.enable_procurement_split = 1
	s.split_basis = "Brand"
	s.enable_addon_handling = 1
	s.addon_item_groups = "Upgrades"
	s.addon_costing = "Own Peg If Available"
	s.enable_specifications = 1
	s.spec_language = "Bilingual"
	s.enable_as_built_configuration = 1
	s.allow_superseded_substitution = "Prompt"
	s.log_substitutions = 1
	s.supplier_resolution = "Item Supplier then Item Default"
	s.batch_naming_components = []
	for row in (
		{"component": "Static Text", "static_value": "BT", "idx": 1},
		{"component": "Brand", "idx": 2},
		{"component": "Manufacturer Part No", "idx": 3},
		{"component": "Sales Order (last 4)", "idx": 4},
		{"component": "Serial Counter", "counter_length": 3, "idx": 5},
	):
		s.append("batch_naming_components", row)
	s.flags.ignore_permissions = True
	s.save(ignore_permissions=True)
	_log("settings configured, batch preview = {0}".format(s.batch_preview))


def _sales_order(company, warehouse, customer, sales_person, lines, date):
	so = frappe.new_doc("Sales Order")
	so.company = company
	so.customer = customer
	so.transaction_date = date
	so.delivery_date = date
	so.append("sales_team", {"sales_person": sales_person, "allocated_percentage": 100})
	for code, qty, rate in lines:
		so.append("items", {"item_code": code, "qty": qty, "rate": rate,
							"delivery_date": date, "warehouse": warehouse})
	so.flags.ignore_permissions = True
	so.insert(ignore_permissions=True)
	so.submit()
	return so


def _purchase_orders(sales_order, rates):
	from neotec_order_costing.api.brand_split import make_split_purchase_orders

	created = make_split_purchase_orders(sales_order)
	out = []
	for entry in created:
		po = frappe.get_doc("Purchase Order", entry["name"])
		for item in po.items:
			if item.item_code in rates:
				item.rate = rates[item.item_code]
		po.save(ignore_permissions=True)
		po.submit()
		out.append(po)
	return out


def _receive(po, use_purchase_invoice=False):
	if use_purchase_invoice:
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice

		doc = make_purchase_invoice(po.name)
		doc.update_stock = 1
		doc.bill_no = "SIM-{0}".format(po.name)
		doc.bill_date = nowdate()
	else:
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

		doc = make_purchase_receipt(po.name)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc


def _deliver(sales_order, addon=None):
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

	dn = make_delivery_note(sales_order)
	if addon:
		dn.append("items", addon)
	dn.flags.ignore_permissions = True
	dn.insert(ignore_permissions=True)
	dn.submit()
	return dn


def _cogs(dn):
	rows = frappe.get_all(
		"Stock Ledger Entry",
		filters={"voucher_type": "Delivery Note", "voucher_no": dn.name, "is_cancelled": 0},
		fields=["item_code", "actual_qty", "stock_value_difference", "batch_no"],
	)
	out = {}
	for r in rows:
		bucket = out.setdefault(r.item_code, {"qty": 0.0, "value": 0.0, "batches": set()})
		bucket["qty"] += abs(flt(r.actual_qty))
		bucket["value"] += abs(flt(r.stock_value_difference))
		if r.batch_no:
			bucket["batches"].add(r.batch_no)
	for code, b in out.items():
		b["rate"] = b["value"] / b["qty"] if b["qty"] else 0
	return out


def run(company=None, warehouse=None, use_purchase_invoice_for_b=True):
	company = company or frappe.defaults.get_defaults().get("company")
	warehouse = warehouse or frappe.db.get_value(
		"Warehouse", {"company": company, "is_group": 0}, "name"
	)
	if not company or not warehouse:
		frappe.throw("Pass company and warehouse explicitly.")

	setup_specifications()
	setup_masters(company, warehouse)
	configure_settings()

	# ---- Salesman A: 200 HP + 100 Dell, ordered 01/08/2026
	so_a = _sales_order(company, warehouse, "SIM-CORP-CUSTOMER", "Salesman A",
						[("SIM-HP-6N4C2EA", 200, 2600), ("SIM-DELL-LAT5450", 100, 2400)], "2026-08-01")
	_log("SO-A {0} created, expect 2 purchase orders (HP and Dell)".format(so_a.name))
	pos_a = _purchase_orders(so_a.name, {"SIM-HP-6N4C2EA": 2000, "SIM-DELL-LAT5450": 1850})
	_log("A purchase orders: {0}".format([p.name for p in pos_a]))
	for po in pos_a:
		doc = _receive(po, use_purchase_invoice=False)
		_log("A inward via {0} {1}".format(doc.doctype, doc.name))

	# ---- Salesman B: 350 HP, ordered 05/08/2026, direct purchase invoice flow
	so_b = _sales_order(company, warehouse, "SIM-CORP-CUSTOMER", "Salesman B",
						[("SIM-HP-6N4C2EA", 350, 2500)], "2026-08-05")
	pos_b = _purchase_orders(so_b.name, {"SIM-HP-6N4C2EA": 1800})
	_log("B purchase orders: {0}".format([p.name for p in pos_b]))
	for po in pos_b:
		doc = _receive(po, use_purchase_invoice=use_purchase_invoice_for_b)
		_log("B inward via {0} {1}".format(doc.doctype, doc.name))

	# ---- Deliver B FIRST, to prove FIFO would have got it wrong
	dn_b = _deliver(so_b.name)
	dn_a = _deliver(so_a.name, addon={
		"item_code": "SIM-KST-16GB", "qty": 200, "rate": 400, "warehouse": warehouse,
	})

	cogs_b = _cogs(dn_b)
	cogs_a = _cogs(dn_a)

	blended = (200 * 2000 + 350 * 1800) / 550.0
	_log("=" * 62)
	_log("Moving average would have costed every HP unit at {0:.2f}".format(blended))
	_log("Salesman A HP actual COGS rate: {0:.2f} (batches {1})".format(
		cogs_a.get("SIM-HP-6N4C2EA", {}).get("rate", 0),
		sorted(cogs_a.get("SIM-HP-6N4C2EA", {}).get("batches", []))))
	_log("Salesman B HP actual COGS rate: {0:.2f} (batches {1})".format(
		cogs_b.get("SIM-HP-6N4C2EA", {}).get("rate", 0),
		sorted(cogs_b.get("SIM-HP-6N4C2EA", {}).get("batches", []))))
	_log("=" * 62)

	assert abs(cogs_a.get("SIM-HP-6N4C2EA", {}).get("rate", 0) - 2000) < 1, "A did not cost at 2000"
	assert abs(cogs_b.get("SIM-HP-6N4C2EA", {}).get("rate", 0) - 1800) < 1, "B did not cost at 1800"
	_log("PASS: order-wise COGS is correct for both salesmen")

	return {
		"sales_order_a": so_a.name, "sales_order_b": so_b.name,
		"delivery_a": dn_a.name, "delivery_b": dn_b.name,
		"blended_rate_avoided": blended,
		"cogs_a": cogs_a.get("SIM-HP-6N4C2EA", {}).get("rate"),
		"cogs_b": cogs_b.get("SIM-HP-6N4C2EA", {}).get("rate"),
		"as_built": _verify_as_built(dn_a),
	}


def _verify_as_built(dn):
	"""The order promised 8GB. Two hundred laptops shipped with two hundred
	16GB modules, so the delivered spec must read 24GB."""
	name = frappe.db.get_value(
		"As Built Configuration",
		{"delivery_document": dn.name, "base_item": "SIM-HP-6N4C2EA"},
		"name",
	)
	if not name:
		_log("WARN: no as-built configuration generated")
		return None
	config = frappe.get_doc("As Built Configuration", name)
	ram = next((r for r in config.specifications if r.attribute == "ram"), None)
	if not ram:
		_log("WARN: RAM attribute missing from as-built configuration")
		return None
	_log("As-built RAM: ordered {0}, delivered {1} (modified={2})".format(
		ram.base_value, ram.value_en, ram.is_modified))
	assert flt(ram.value_en) == 24, "as-built RAM should be 24, got {0}".format(ram.value_en)
	_log("PASS: as-built configuration reflects the RAM upgrade")
	return {"config": name, "ram_ordered": ram.base_value, "ram_delivered": ram.value_en}
