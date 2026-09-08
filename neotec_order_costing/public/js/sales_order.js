frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;

		frappe.db.get_single_value("Order Costing Settings", "enable_procurement_split").then((on) => {
			if (!on) return;
			frm.add_custom_button(__("Material Requests by Brand"), () => open_split(frm, "mr"), __("Create"));
			frm.add_custom_button(__("Purchase Orders by Brand"), () => open_split(frm, "po"), __("Create"));
		});

		frappe.db.get_single_value("Order Costing Settings", "enable_order_wise_cogs").then((on) => {
			if (!on) return;
			frm.add_custom_button(__("Cost Pegs"), () => {
				frappe.set_route("List", "Order Cost Peg", { sales_order: frm.doc.name });
			}, __("View"));
			frm.add_custom_button(__("Order Profitability"), () => {
				frappe.set_route("query-report", "Order Wise Profitability", {
					sales_order: frm.doc.name,
					group_by: "Item",
				});
			}, __("View"));
			render_peg_status(frm);
		});
	},
});

function render_peg_status(frm) {
	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Order Cost Peg",
			filters: { sales_order: frm.doc.name, docstatus: 1 },
			fields: ["status", "qty_pegged", "qty_open"],
			limit_page_length: 0,
		},
		callback: (r) => {
			const pegs = r.message || [];
			if (!pegs.length) return;
			const open = pegs.filter((p) => ["Open", "Ordered"].includes(p.status)).length;
			const msg = open
				? __("{0} of {1} cost pegs are still awaiting receipt", [open, pegs.length])
				: __("All {0} cost pegs are received", [pegs.length]);
			frm.dashboard.add_indicator(msg, open ? "orange" : "green");
		},
	});
}

function open_split(frm, target) {
	frappe.call({
		method: "neotec_order_costing.api.brand_split.preview_split",
		args: { sales_order: frm.doc.name },
		freeze: true,
		callback: (r) => {
			const data = r.message;
			if (!data || !data.groups.length) {
				frappe.msgprint(__("No stock items on this order to procure."));
				return;
			}
			show_split_dialog(frm, target, data);
		},
	});
}

function show_split_dialog(frm, target, data) {
	const rows = data.groups
		.map((g) => {
			const lines = g.items
				.map((i) => `<div class="text-muted small">${frappe.utils.escape_html(i.item_code)} &times; ${i.qty}</div>`)
				.join("");
			const supplier = g.supplier
				? frappe.utils.escape_html(g.supplier_name || g.supplier)
				: `<span class="text-danger">${__("No default supplier")}</span>`;
			return `<tr>
				<td><input type="checkbox" class="noc-group" value="${frappe.utils.escape_html(g.key)}" checked></td>
				<td><b>${frappe.utils.escape_html(g.key)}</b>${lines}</td>
				<td>${supplier}</td>
				<td class="text-right">${g.total_qty}</td>
			</tr>`;
		})
		.join("");

	const html = `<p class="text-muted">${__("Split basis")}: <b>${frappe.utils.escape_html(data.basis)}</b>.
		${__("One document will be created per group below.")}</p>
		<table class="table table-bordered">
			<thead><tr><th style="width:36px"></th><th>${__("Group")}</th><th>${__("Supplier")}</th>
			<th class="text-right">${__("Qty")}</th></tr></thead>
			<tbody>${rows}</tbody>
		</table>`;

	const d = new frappe.ui.Dialog({
		title: target === "mr" ? __("Create Material Requests by Group") : __("Create Purchase Orders by Group"),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "preview", options: html }],
		primary_action_label: __("Create {0} Documents", [data.groups.length]),
		primary_action() {
			const keys = Array.from(d.$wrapper[0].querySelectorAll("input.noc-group:checked")).map((e) => e.value);
			if (!keys.length) {
				frappe.msgprint(__("Select at least one group."));
				return;
			}
			const method =
				target === "mr"
					? "neotec_order_costing.api.brand_split.make_split_material_requests"
					: "neotec_order_costing.api.brand_split.make_split_purchase_orders";
			frappe.call({
				method,
				args: { sales_order: frm.doc.name, selected_keys: keys },
				freeze: true,
				freeze_message: __("Creating documents"),
				callback: (r) => {
					d.hide();
					const created = r.message || [];
					if (!created.length) return;
					const links = created
						.map((c) => frappe.utils.get_form_link(target === "mr" ? "Material Request" : "Purchase Order", c.name, true))
						.join("<br>");
					frappe.msgprint({
						title: __("Created"),
						indicator: "green",
						message: links,
					});
					frm.reload_doc();
				},
			});
		},
	});
	d.show();
}


frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		// An unsaved document has a temporary name that does not exist on the
		// server, so nothing here may call the backend with it.
		if (frm.is_new()) return;

		frappe.db.get_single_value("Order Costing Settings", "enable_cost_visibility").then((on) => {
			frappe.db.get_single_value("Order Costing Settings", "enable_order_wise_cogs").then((cogs) => {
				if (!on && !cogs) return;
				frm.add_custom_button(__("Refresh Purchase Cost"), () => {
					if (frm.is_dirty()) {
						frappe.msgprint(__("Save the document before fetching purchase rates."));
						return;
					}
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
