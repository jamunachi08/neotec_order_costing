frappe.ui.form.on("Procurement Consolidation", {
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Fetch Demand"), () => {
				frm.call({
					doc: frm.doc, method: "fetch",
					freeze: true, freeze_message: __("Collecting open demand"),
					callback: (r) => {
						frm.refresh();
						frappe.show_alert({
							message: __("{0} demand line(s) found", [r.message || 0]),
							indicator: (r.message ? "green" : "orange"),
						});
					},
				});
			}).addClass("btn-primary");

			frm.add_custom_button(__("Select All"), () => toggle_all(frm, 1), __("Lines"));
			frm.add_custom_button(__("Clear All"), () => toggle_all(frm, 0), __("Lines"));
			frm.add_custom_button(__("Check Policy"), () => check_policy(frm), __("Lines"));
		}

		if (frm.doc.docstatus === 1 && frm.doc.created_documents) {
			frm.dashboard.add_comment(
				frappe.utils.escape_html(frm.doc.created_documents).replace(/\n/g, "<br>"),
				"green", true
			);
		}

		if (frm.doc.total_expected_saving) {
			frm.dashboard.add_indicator(
				__("Expected saving: {0}", [format_currency(frm.doc.total_expected_saving)]),
				frm.doc.total_expected_saving > 0 ? "green" : "orange"
			);
		}
		if (frm.doc.total_orders > 1) {
			frm.dashboard.add_indicator(
				__("Consolidating {0} sales orders", [frm.doc.total_orders]), "blue"
			);
		}
	},

	group_by(frm) { if (frm.doc.items.length) frm.save(); },
});

frappe.ui.form.on("Procurement Consolidation Item", {
	qty_to_order(frm) { frm.save(); },
	select_row(frm) { frm.save(); },
});

frappe.ui.form.on("Procurement Consolidation Summary", {
	target_rate(frm) {
		frm.call({ doc: frm.doc, method: "recalculate_savings",
			callback: () => frm.refresh_field("summary") });
	},
	supplier(frm) { frm.dirty(); },
});

function toggle_all(frm, value) {
	(frm.doc.items || []).forEach((row) => { row.select_row = value; });
	frm.refresh_field("items");
	frm.save();
}

function check_policy(frm) {
	const rows = frm.doc.summary || [];
	if (!rows.length) {
		frappe.msgprint(__("Fetch demand first."));
		return;
	}
	const calls = rows.map((r) =>
		frappe.call({
			method: "neotec_order_costing.api.consolidation.preview_path",
			args: {
				company: frm.doc.company, brand: r.brand, supplier: r.supplier,
				amount: (r.total_qty || 0) * (r.target_rate || 0),
			},
		})
	);
	Promise.all(calls).then((results) => {
		const body = results.map((res, i) => {
			const r = rows[i];
			return `<tr><td>${frappe.utils.escape_html(r.brand || "-")}</td>
				<td>${frappe.utils.escape_html(r.item_code)}</td>
				<td>${r.total_qty}</td>
				<td>${frappe.utils.escape_html(res.message.doctype)}</td></tr>`;
		}).join("");
		frappe.msgprint({
			title: __("Procurement Path by Group"),
			message: `<table class="table table-bordered"><thead><tr>
				<th>${__("Brand")}</th><th>${__("Item")}</th>
				<th>${__("Qty")}</th><th>${__("Will create")}</th>
				</tr></thead><tbody>${body}</tbody></table>`,
		});
	});
}
