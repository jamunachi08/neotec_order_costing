frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		frm.add_custom_button(__("Invoice Profitability"), () => {
			frappe.set_route("query-report", "Order Wise Profitability", {
				group_by: "Item",
				customer: frm.doc.customer,
				from_date: frm.doc.posting_date,
				to_date: frm.doc.posting_date,
			});
		}, __("Order Costing"));
	},
});

frappe.ui.form.on("Sales Invoice Item", {
	item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.so_detail) return;
		frappe.db.get_single_value("Order Costing Settings", "enable_addon_handling").then((on) => {
			if (!on) return;
			frappe.show_alert({
				message: __("{0} is not on the Sales Order. It will be treated as an add-on line.", [row.item_code]),
				indicator: "blue",
			});
		});
	},
});


frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		frappe.db.get_single_value("Order Costing Settings", "enable_cost_visibility").then((on) => {
			frappe.db.get_single_value("Order Costing Settings", "enable_order_wise_cogs").then((cogs) => {
				if (!on && !cogs) return;
				frm.add_custom_button(__("Refresh Purchase Cost"), () => {
					frappe.call({
						method: "neotec_order_costing.api.cost_stamp.refresh_document",
						args: { doctype: frm.doc.doctype, name: frm.doc.name },
						freeze: true,
						freeze_message: __("Fetching purchase rates"),
						callback: (r) => {
							const res = r.message || {};
							frappe.show_alert({
								message: __("{0} of {1} line(s) updated", [res.updated || 0, res.total || 0]),
								indicator: res.updated ? "green" : "orange",
							});
							frm.reload_doc();
						},
					});
				}, __("Order Costing"));
				show_cost_summary(frm);
			});
		});
	},
});

function show_cost_summary(frm) {
	const rows = (frm.doc.items || []).filter((i) => i.custom_noc_pegged_cost_rate);
	if (!rows.length) {
		frm.dashboard.add_indicator(__("No purchase cost fetched yet"), "orange");
		return;
	}
	let cost = 0, revenue = 0;
	(frm.doc.items || []).forEach((i) => {
		cost += (i.custom_noc_pegged_cost_rate || 0) * (i.qty || 0);
		revenue += (i.amount || 0);
	});
	const margin = revenue - cost;
	frm.dashboard.add_indicator(
		__("Cost {0} · Margin {1}", [format_currency(cost), format_currency(margin)]),
		margin >= 0 ? "green" : "red"
	);
}
