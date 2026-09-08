frappe.query_reports["Order Wise Profitability"] = {
	filters: [
		{
			fieldname: "report_profile",
			label: __("Column Profile"),
			fieldtype: "Link",
			options: "Profitability Report Profile",
			reqd: 0,
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -3),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: [
				"None", "Sales Order", "Customer", "Sales Person", "Brand",
				"Item Group", "Item", "Supplier", "Purchase Order", "Batch",
			],
			default: "Sales Order",
		},
		{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "sales_person", label: __("Sales Person"), fieldtype: "Link", options: "Sales Person" },
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "purchase_order", label: __("Purchase Order"), fieldtype: "Link", options: "Purchase Order" },
		{ fieldname: "brand", label: __("Brand"), fieldtype: "Link", options: "Brand" },
		{ fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group" },
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{
			fieldname: "cost_basis",
			label: __("Cost Basis"),
			fieldtype: "Select",
			options: ["Actual Purchase Cost", "Stock Ledger Valuation"],
			default: "Actual Purchase Cost",
			description: __("Actual cost follows the purchase order for each sales order rather than blended valuation."),
		},
		{
			fieldname: "revenue_basis",
			label: __("Revenue Basis"),
			fieldtype: "Select",
			options: ["Invoiced Only", "Delivered and Invoiced"],
			default: "Delivered and Invoiced",
			description: __("Delivered lines carry real COGS before the invoice exists."),
		},
		{ fieldname: "only_pegged", label: __("Only Pegged Lines"), fieldtype: "Check" },
		{ fieldname: "hide_addons", label: __("Hide Add-on Items"), fieldtype: "Check" },
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname && column.fieldname.endsWith("gross_margin_pct")) {
			const n = parseFloat(String(value).replace(/[^0-9.\-]/g, ""));
			if (!isNaN(n)) {
				const colour = n < 0 ? "#A32D2D" : n < 10 ? "#854F0B" : "#0F6E56";
				value = `<span style="color:${colour}">${value}</span>`;
			}
		}
		return value;
	},

	onload(report) {
		neotec.order_costing.load_catalog();
		report.page.add_inner_button(__("Item Wise Profitability"), () => {
			frappe.set_route("query-report", "Item Wise Profitability", {
				company: report.get_filter_value("company"),
			});
		});
		report.page.add_inner_button(__("Configure Columns"), () => open_column_manager(report));
		report.page.add_inner_button(__("New Column Profile"), () => {
			frappe.new_doc("Profitability Report Profile");
		});
	},
};

function open_column_manager(report) {
	const profile = report.get_filter_value("report_profile");
	if (!profile) {
		frappe.msgprint(__("Pick a Column Profile first, or create one."));
		return;
	}

	frappe.call({
		method: "neotec_order_costing.api.field_catalog.get_catalog_tree",
		callback: (r) => render_dialog(report, profile, r.message || []),
	});
}

function render_dialog(report, profile, tree) {
	frappe.db.get_doc("Profitability Report Profile", profile).then((doc) => {
		const active = new Set((doc.fields || []).map((f) => `${f.source_document}||${f.fieldname}`));

		const html = tree
			.map((group) => {
				const boxes = group.fields
					.map((f) => {
						const checked = active.has(f.value) ? "checked" : "";
						return `<label style="display:block;margin:2px 0;font-weight:400">
							<input type="checkbox" class="noc-col" value="${f.value}" ${checked}>
							${frappe.utils.escape_html(f.label)}
							<span class="text-muted small">${frappe.utils.escape_html(f.fieldname)}</span>
						</label>`;
					})
					.join("");
				return `<div style="margin-bottom:12px">
					<div style="font-weight:500;margin-bottom:4px">${frappe.utils.escape_html(group.doctype_label)}</div>
					<div style="padding-left:10px">${boxes}</div>
				</div>`;
			})
			.join("");

		const d = new frappe.ui.Dialog({
			title: __("Columns for {0}", [profile]),
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "picker",
					options: `<div style="max-height:460px;overflow:auto">${html}</div>`,
				},
			],
			primary_action_label: __("Apply"),
			primary_action() {
				const chosen = Array.from(
					d.$wrapper[0].querySelectorAll("input.noc-col:checked")
				).map((el) => el.value);
				save_columns(profile, chosen, doc).then(() => {
					d.hide();
					report.refresh();
				});
			},
		});
		d.show();
	});
}

function save_columns(profile, chosen, doc) {
	const chosenSet = new Set(chosen);
	const existing = new Map((doc.fields || []).map((f) => [`${f.source_document}||${f.fieldname}`, f]));

	const rows = [];
	// keep the existing order for fields that survive, then append new picks
	(doc.fields || []).forEach((f) => {
		const key = `${f.source_document}||${f.fieldname}`;
		if (chosenSet.has(key)) rows.push(f);
	});
	chosen.forEach((key) => {
		if (existing.has(key)) return;
		const [source_document, fieldname] = key.split("||");
		rows.push({ source_document, fieldname, is_visible: 1 });
	});

	return frappe.call({
		method: "frappe.client.set_value",
		args: { doctype: "Profitability Report Profile", name: profile, fieldname: { fields: rows } },
		freeze: true,
		freeze_message: __("Updating columns"),
	});
}
