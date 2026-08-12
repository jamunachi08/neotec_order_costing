import frappe
from frappe.model.document import Document

from neotec_order_costing.api.batching import build_batch_id


class OrderCostingSettings(Document):
	def validate(self):
		self._validate_variance_account()
		self._refresh_preview()

	def _validate_variance_account(self):
		if self.post_cost_variance and not self.cost_variance_account:
			frappe.throw("A Cost Variance Account is required when variance journals are enabled.")
		if self.costing_mode != "Pegged PO Rate" and self.post_cost_variance:
			self.post_cost_variance = 0

	def _refresh_preview(self):
		if not self.enable_auto_batch or not self.batch_naming_components:
			self.batch_preview = ""
			return
		sample = {
			"item_code": "HP-LAP-14",
			"item_group": "Laptops",
			"brand": "HP",
			"supplier": "SUP-0007",
			"customer": "CUST-0021",
			"sales_order": "SAL-ORD-2026-00142",
			"purchase_order": "PUR-ORD-2026-00088",
			"stock_document": "MAT-PRE-2026-00061",
			"sales_person": "Salesman A",
			"posting_date": "2026-08-01",
			"fiscal_year": "2026",
			"purchase_rate": 2000,
			"manufacturer_part_no": "6N4C2EA",
			"supplier_part_no": "HP-6N4C2EA-KSA",
			"customer_part_no": "IT-LAP-STD",
		}
		try:
			self.batch_preview = build_batch_id(sample, settings=self, dry_run=True)
		except Exception as exc:  # never block saving the settings over a preview
			self.batch_preview = "Preview unavailable: {0}".format(exc)


# ---------------------------------------------------------------------------
# Resolution helpers used by every other module in the app
# ---------------------------------------------------------------------------

def get_settings():
	return frappe.get_cached_doc("Order Costing Settings")


def is_enabled():
	return bool(get_settings().enable_order_wise_cogs)


def is_cost_visibility_enabled():
	"""Cost visibility stamps the pegged purchase rate onto sales documents for
	reporting and margin display. It never alters the stock ledger, so it is
	safe to run with Enable Order-wise COGS switched off."""
	settings = get_settings()
	return bool(settings.get("enable_cost_visibility") or settings.enable_order_wise_cogs)


def resolve_costing_mode(company=None, item_code=None, customer=None):
	"""Applicability rows win over the global mode. First matching enabled row
	is used, so implementors can order rows from specific to general."""
	settings = get_settings()
	if not settings.enable_order_wise_cogs:
		return "Default Valuation"

	if not settings.applicability:
		return settings.costing_mode

	item_group = brand = None
	if item_code:
		item_group, brand = frappe.get_cached_value("Item", item_code, ["item_group", "brand"])
	customer_group = frappe.get_cached_value("Customer", customer, "customer_group") if customer else None

	for row in settings.applicability:
		if not row.enabled:
			continue
		if row.company and company and row.company != company:
			continue
		if row.item_group and item_group and not _in_group_tree(item_group, row.item_group):
			continue
		if row.brand and brand and row.brand != brand:
			continue
		if row.customer_group and customer_group and customer_group != row.customer_group:
			continue
		return settings.costing_mode if row.costing_mode == "Follow Global" else row.costing_mode

	return "Default Valuation"


def _in_group_tree(item_group, ancestor):
	if item_group == ancestor:
		return True
	lft, rgt = frappe.get_cached_value("Item Group", ancestor, ["lft", "rgt"])
	node = frappe.get_cached_value("Item Group", item_group, ["lft", "rgt"])
	if not lft or not node:
		return False
	return lft <= node[0] and node[1] <= rgt


@frappe.whitelist()
def preview_batch_id(context=None):
	"""Called from the Settings form so implementors can test their composition
	against real document values before going live."""
	frappe.only_for(["System Manager", "Stock Manager"])
	context = frappe.parse_json(context) if isinstance(context, str) else (context or {})
	return build_batch_id(context, dry_run=True)
