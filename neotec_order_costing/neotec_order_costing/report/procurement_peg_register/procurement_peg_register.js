frappe.query_reports["Procurement Peg Register"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
		  default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order" },
		{ fieldname: "purchase_order", label: __("Purchase Order"), fieldtype: "Link", options: "Purchase Order" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "sales_person", label: __("Sales Person"), fieldtype: "Link", options: "Sales Person" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "brand", label: __("Brand"), fieldtype: "Link", options: "Brand" },
		{ fieldname: "status", label: __("Status"), fieldtype: "Select",
		  options: ["", "Open", "Ordered", "Received", "Partially Delivered", "Closed"] },
		{ fieldname: "only_open", label: __("Only Open Pegs"), fieldtype: "Check" },
	],
};
