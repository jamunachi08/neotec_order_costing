frappe.query_reports["Item Wise Profitability"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
		  reqd: 1, default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date",
		  default: frappe.datetime.add_months(frappe.datetime.get_today(), -3) },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date",
		  default: frappe.datetime.get_today() },
		{
			fieldname: "group_by", label: __("Group By"), fieldtype: "Select",
			options: ["Item", "Brand", "Item Group", "Customer", "Project"],
			default: "Item",
		},
		{
			fieldname: "depth", label: __("Detail Level"), fieldtype: "Select",
			options: [
				{ label: __("Top level only"), value: "1" },
				{ label: __("Two levels"), value: "2" },
				{ label: __("Three levels"), value: "3" },
			],
			default: "2",
		},
		{
			fieldname: "cost_basis", label: __("Cost Basis"), fieldtype: "Select",
			options: ["Actual Purchase Cost", "Stock Ledger Valuation"],
			default: "Actual Purchase Cost",
		},

		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "brand", label: __("Brand"), fieldtype: "Link", options: "Brand" },
		{ fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group" },
		{ fieldname: "sales_person", label: __("Sales Person"), fieldtype: "Link", options: "Sales Person" },
		{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project" },
		{ fieldname: "cost_center", label: __("Cost Center"), fieldtype: "Link", options: "Cost Center" },
		{ fieldname: "territory", label: __("Territory"), fieldtype: "Link", options: "Territory" },
		{ fieldname: "campaign", label: __("Campaign"), fieldtype: "Link", options: "Campaign" },
		{ fieldname: "order_type", label: __("Order Type"), fieldtype: "Select",
		  options: ["", "Sales", "Maintenance", "Shopping Cart"] },
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "purchase_order", label: __("Purchase Order"), fieldtype: "Link", options: "Purchase Order" },
		{ fieldname: "batch_no", label: __("Batch"), fieldtype: "Link", options: "Batch" },

		{ fieldname: "include_open", label: __("Include Open Backlog"), fieldtype: "Check" },
		{ fieldname: "show_cost_source", label: __("Show Cost Source"), fieldtype: "Check", default: 1 },
		{ fieldname: "show_markup", label: __("Show Markup %"), fieldtype: "Check" },
		{ fieldname: "show_procurement", label: __("Show Procurement Columns"), fieldtype: "Check" },
		{
			fieldname: "extra_columns", label: __("Extra Columns"), fieldtype: "MultiSelectList",
			get_data(txt) {
				return neotec.order_costing.extra_column_options(txt);
			},
		},
	],

	tree: true,
	name_field: "entity",
	initial_depth: 0,

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.indent === 0) value = `<span style="font-weight:600">${value}</span>`;
		if (column.fieldname === "gross_margin_pct" || column.fieldname === "markup_pct") {
			const n = parseFloat(String(value).replace(/[^0-9.\-]/g, ""));
			if (!isNaN(n)) {
				const colour = n < 0 ? "#A32D2D" : n < 10 ? "#854F0B" : "#0F6E56";
				value = `<span style="color:${colour}">${value}</span>`;
			}
		}
		if (column.fieldname === "qty_open" && data && Number(data.qty_open) > 0) {
			value = `<span style="color:#854F0B">${value}</span>`;
		}
		return value;
	},

	onload(report) {
		neotec.order_costing.add_column_picker(report, "extra_columns");
		report.page.add_inner_button(__("Sales Person View"), () => {
			frappe.set_route("query-report", "Sales Person Profitability", {
				company: report.get_filter_value("company"),
				from_date: report.get_filter_value("from_date"),
				to_date: report.get_filter_value("to_date"),
			});
		});
	},
};
