frappe.query_reports["Consolidation Opportunity"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
		  reqd: 1, default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "brand", label: __("Brand"), fieldtype: "Link", options: "Brand" },
		{ fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group" },
		{ fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse" },
		{ fieldname: "from_date", label: __("Required From"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("Required To"), fieldtype: "Date" },
		{ fieldname: "include_unlinked_requests", label: __("Include Stock Requests"), fieldtype: "Check" },
	],
	onload(report) {
		report.page.add_inner_button(__("Start Consolidation"), () => {
			frappe.new_doc("Procurement Consolidation", {
				company: report.get_filter_value("company"),
				brand: report.get_filter_value("brand"),
				consolidation_date: frappe.datetime.get_today(),
			});
		});
	},
};
