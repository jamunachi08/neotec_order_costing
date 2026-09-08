frappe.ui.form.on("Material Request", {
	refresh(frm) {
		if (frm.is_new()) return;

		const group = (frm.doc.items || []).find((i) => i.custom_noc_split_group);
		if (group) {
			frm.dashboard.add_indicator(__("Procurement group: {0}", [group.custom_noc_split_group]), "blue");
		}

		if (frm.doc.docstatus !== 1 || frm.doc.material_request_type !== "Purchase") return;

		frappe.db.get_single_value("Order Costing Settings", "enable_procurement_split").then((on) => {
			if (!on) return;
			frm.add_custom_button(__("Split by Brand"), () => open_split(frm), __("Create"));
		});

		frappe.db.get_single_value("Order Costing Settings", "enable_consolidation").then((on) => {
			if (!on) return;
			frm.add_custom_button(__("Consolidate With Other Requests"), () => {
				frappe.new_doc("Procurement Consolidation", {
					company: frm.doc.company,
					consolidation_date: frappe.datetime.get_today(),
				});
			}, __("Create"));
		});
	},
});

function open_split(frm) {
	frappe.call({
		method: "neotec_order_costing.api.brand_split.preview_material_request_split",
		args: { material_request: frm.doc.name },
		freeze: true,
		callback: (r) => {
			const data = r.message;
			if (!data || !data.groups.length) {
				frappe.msgprint(__("Nothing left to procure on this request."));
				return;
			}
			show_dialog(frm, data);
		},
	});
}

function show_dialog(frm, data) {
	const rows = data.groups.map((g) => {
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
			<td>${frappe.utils.escape_html(g.target_doctype)}</td>
		</tr>`;
	}).join("");

	const note = data.policy_on
		? __("The document type per group is set by your procurement policy.")
		: __("Procurement policy is off, so every group becomes a purchase order.");

	const d = new frappe.ui.Dialog({
		title: __("Split Request by Brand"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML", fieldname: "preview",
				options: `<p class="text-muted">${__("Split basis")}:
					<b>${frappe.utils.escape_html(data.basis)}</b>. ${note}</p>
					<table class="table table-bordered"><thead><tr>
					<th style="width:36px"></th><th>${__("Group")}</th><th>${__("Supplier")}</th>
					<th class="text-right">${__("Qty")}</th><th>${__("Creates")}</th>
					</tr></thead><tbody>${rows}</tbody></table>`,
			},
			{
				fieldname: "override_doctype", label: __("Force Document Type"),
				fieldtype: "Select",
				options: ["", "Purchase Order", "Supplier Quotation", "Request for Quotation"],
				description: __("Leave blank to follow the policy above."),
			},
		],
		primary_action_label: __("Create Documents"),
		primary_action(v) {
			const keys = Array.from(d.$wrapper[0].querySelectorAll("input.noc-group:checked"))
				.map((e) => e.value);
			if (!keys.length) {
				frappe.msgprint(__("Select at least one group."));
				return;
			}
			frappe.call({
				method: "neotec_order_costing.api.brand_split.make_documents_from_material_request",
				args: {
					material_request: frm.doc.name,
					selected_keys: keys,
					override_doctype: v.override_doctype || null,
				},
				freeze: true,
				freeze_message: __("Creating documents"),
				callback: (r) => {
					d.hide();
					const created = r.message || [];
					if (!created.length) return;
					frappe.msgprint({
						title: __("Created"),
						indicator: "green",
						message: created
							.map((c) => frappe.utils.get_form_link(c.doctype, c.name, true))
							.join("<br>"),
					});
					frm.reload_doc();
				},
			});
		},
	});
	d.show();
}
