frappe.provide("neotec.order_costing");

neotec.order_costing.open_settings = function () {
	frappe.set_route("Form", "Order Costing Settings");
};

neotec.order_costing.cogs_source_colour = function (source) {
	return {
		"Pegged Batch Valuation": "green",
		"Pegged PO Rate": "blue",
		"Default Valuation": "orange",
		"Add-on Item": "purple",
	}[source] || "gray";
};
