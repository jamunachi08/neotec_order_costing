frappe.query_reports["Sales Person Profitability"] = {
	filters: [
		{
			fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
			reqd: 1, default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "from_date", label: __("From Date"), fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -3),
		},
		{
			fieldname: "to_date", label: __("To Date"), fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "cost_basis", label: __("Cost Basis"), fieldtype: "Select",
			options: ["Actual Purchase Cost", "Stock Ledger Valuation"],
			default: "Actual Purchase Cost",
			description: __("Actual cost follows the purchase order raised for each sales order. Ledger valuation blends every purchase of the item."),
		},
		{
			fieldname: "depth", label: __("Detail Level"), fieldtype: "Select",
			options: [
				{ label: __("Sales Person only"), value: "1" },
				{ label: __("Down to Sales Order"), value: "2" },
				{ label: __("Down to Item"), value: "3" },
			],
			default: "3",
		},
		{ fieldname: "sales_person", label: __("Sales Person"), fieldtype: "Link", options: "Sales Person" },
		{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "territory", label: __("Territory"), fieldtype: "Link", options: "Territory" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project" },
		{ fieldname: "cost_center", label: __("Cost Center"), fieldtype: "Link", options: "Cost Center" },
		{ fieldname: "campaign", label: __("Campaign"), fieldtype: "Link", options: "Campaign" },
		{ fieldname: "order_type", label: __("Order Type"), fieldtype: "Select",
		  options: ["", "Sales", "Maintenance", "Shopping Cart"] },
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "purchase_order", label: __("Purchase Order"), fieldtype: "Link", options: "Purchase Order" },
		{ fieldname: "batch_no", label: __("Batch"), fieldtype: "Link", options: "Batch" },
		{ fieldname: "brand", label: __("Brand"), fieldtype: "Link", options: "Brand" },
		{ fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group" },
		{
			fieldname: "include_delivered", label: __("Include Delivered, Not Invoiced"),
			fieldtype: "Check", default: 1,
		},
		{
			fieldname: "include_open", label: __("Include Open Backlog"), fieldtype: "Check",
			default: 0,
		},
		{ fieldname: "show_cost_source", label: __("Show Cost Source"), fieldtype: "Check", default: 1 },
		{ fieldname: "compare_ledger", label: __("Compare With Ledger COGS"), fieldtype: "Check" },
		{ fieldname: "show_buckets", label: __("Split Revenue by Stage"), fieldtype: "Check" },
		{ fieldname: "show_fulfilment", label: __("Show Fulfilment %"), fieldtype: "Check" },
		{ fieldname: "show_procurement", label: __("Show Procurement Columns"), fieldtype: "Check" },
		{ fieldname: "show_territory", label: __("Show Territory"), fieldtype: "Check" },
		{
			fieldname: "extra_columns", label: __("Extra Columns"), fieldtype: "MultiSelectList",
			get_data(txt) {
				return neotec.order_costing.extra_column_options(txt);
			},
		},
	],

	tree: true,
	name_field: "entity",
	parent_field: "parent_entity",
	initial_depth: 1,

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (data && data.indent === 0) {
			value = `<span style="font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "net_margin_pct" || column.fieldname === "gross_margin_pct") {
			const n = parseFloat(String(value).replace(/[^0-9.\-]/g, ""));
			if (!isNaN(n)) {
				const colour = n < 0 ? "#A32D2D" : n < 10 ? "#854F0B" : "#0F6E56";
				value = `<span style="color:${colour}">${value}</span>`;
			}
		}
		if (column.fieldname === "net_profit" && data && Number(data.net_profit) < 0) {
			value = `<span style="color:#A32D2D">${value}</span>`;
		}
		if (column.fieldname === "unit_cost" && data && data.is_actual_cost === 0) {
			value = `<span style="color:#854F0B" title="${__("Estimated, not a purchase order rate")}">${value} *</span>`;
		}
		if (column.fieldname === "cost_variance" && data) {
			const n = Number(data.cost_variance);
			if (n) {
				value = `<span style="color:${n > 0 ? "#A32D2D" : "#0F6E56"}">${value}</span>`;
			}
		}
		return value;
	},

	onload(report) {
		neotec.order_costing.add_column_picker(report, "extra_columns");
		report.page.add_inner_button(__("Item Wise Profitability"), () => {
			frappe.set_route("query-report", "Item Wise Profitability", {
				company: report.get_filter_value("company"),
				from_date: report.get_filter_value("from_date"),
				to_date: report.get_filter_value("to_date"),
			});
		});
		report.page.add_inner_button(__("Order Wise Profitability"), () => {
			frappe.set_route("query-report", "Order Wise Profitability", {
				company: report.get_filter_value("company"),
				from_date: report.get_filter_value("from_date"),
				to_date: report.get_filter_value("to_date"),
				group_by: "Sales Person",
			});
		});
		report.page.add_inner_button(__("Procurement Peg Register"), () => {
			frappe.set_route("query-report", "Procurement Peg Register", {
				company: report.get_filter_value("company"),
				sales_person: report.get_filter_value("sales_person") || "",
			});
		});
	},
};


frappe.query_reports["Sales Person Profitability"].onload = (function (base) {
	return function (report) {
		base.call(this, report);
		report.page.add_inner_button(__("Explain a Line Cost"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Where Did This Cost Come From?"),
				size: "large",
				fields: [
					{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link",
					  options: "Sales Order", reqd: 1 },
					{ fieldname: "item_code", label: __("Item"), fieldtype: "Link",
					  options: "Item", reqd: 1 },
					{ fieldname: "result", fieldtype: "HTML" },
				],
				primary_action_label: __("Explain"),
				primary_action(v) {
					frappe.call({
						method: "neotec_order_costing.api.order_cost.explain",
						args: v,
						callback: (r) => {
							const res = r.message || {};
							const rows = (res.candidates || []).map((c) => `<tr>
								<td>${frappe.utils.escape_html(c.source)}</td>
								<td class="text-right">${format_currency(c.rate)}</td></tr>`).join("");
							d.fields_dict.result.$wrapper.html(`
								<div style="margin-bottom:8px">
									<b>${__("Used")}:</b> ${format_currency(res.chosen_rate)}
									(${frappe.utils.escape_html(res.chosen_source || "")})
									${res.is_actual ? "" : `<span style="color:#854F0B"> — ${__("estimated")}</span>`}
								</div>
								<table class="table table-bordered"><thead><tr>
								<th>${__("Available Rate")}</th><th class="text-right">${__("Value")}</th>
								</tr></thead><tbody>${rows}</tbody></table>`);
						},
					});
				},
			});
			d.show();
		});
	};
})(frappe.query_reports["Sales Person Profitability"].onload);
