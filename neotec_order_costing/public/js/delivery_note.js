frappe.ui.form.on("Delivery Note", {
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Reapply Cost Pegs"), () => {
				frm.save().then(() => frappe.show_alert({ message: __("Pegged batches refreshed"), indicator: "green" }));
			}, __("Order Costing"));
		}
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Order Profitability"), () => {
				const so = (frm.doc.items || []).map((i) => i.against_sales_order).find(Boolean);
				frappe.set_route("query-report", "Order Wise Profitability", {
					company: frm.doc.company,
					group_by: "Item",
					sales_order: so || "",
					from_date: frm.doc.posting_date,
					to_date: frm.doc.posting_date,
					revenue_basis: "Delivered and Invoiced",
				});
			}, __("Order Costing"));

			frm.add_custom_button(__("Check Batch Valuation"), () => check_batches(frm), __("Order Costing"));
		}
		show_cogs_summary(frm);
	},
});

function show_cogs_summary(frm) {
	const flagged = (frm.doc.items || []).filter((i) => i.custom_noc_cogs_source);
	if (!flagged.length) return;
	const fallbacks = flagged.filter((i) => i.custom_noc_cogs_source === "Default Valuation").length;
	const addons = flagged.filter((i) => i.custom_noc_is_addon).length;
	if (fallbacks) {
		frm.dashboard.add_indicator(__("{0} line(s) fell back to default valuation", [fallbacks]), "orange");
	}
	if (addons) {
		frm.dashboard.add_indicator(__("{0} add-on line(s)", [addons]), "blue");
	}
}


function check_batches(frm) {
	const batches = (frm.doc.items || []).map((i) => i.batch_no).filter(Boolean);
	if (!batches.length) {
		frappe.msgprint(__("No batches on this delivery note."));
		return;
	}
	frappe.call({
		method: "neotec_order_costing.api.repair.diagnose_batches",
		args: { batches: batches },
		freeze: true,
		callback: (r) => {
			const rows = (r.message || []).map((b) => `<tr>
				<td>${frappe.utils.escape_html(b.batch)}</td>
				<td>${frappe.utils.escape_html(b.item)}</td>
				<td class="text-right">${b.qty_in}</td>
				<td class="text-right">${b.qty_out}</td>
				<td class="text-right">${b.incoming_rate}</td>
				<td>${b.batchwise ? "&#10003;" : `<span class="text-danger">${__("off")}</span>`}</td>
				<td class="text-muted small">${frappe.utils.escape_html(b.note || "")}</td>
			</tr>`).join("");
			frappe.msgprint({
				title: __("Batch Valuation Check"),
				message: `<table class="table table-bordered"><thead><tr>
					<th>${__("Batch")}</th><th>${__("Item")}</th>
					<th class="text-right">${__("In")}</th><th class="text-right">${__("Out")}</th>
					<th class="text-right">${__("Rate")}</th><th>${__("Batchwise")}</th>
					<th>${__("Note")}</th></tr></thead><tbody>${rows}</tbody></table>`,
			});
		},
	});
}


frappe.ui.form.on("Delivery Note", {
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
