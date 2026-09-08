frappe.ui.form.on("Profitability Report Profile", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Add Columns"), () => open_picker(frm));
		frm.add_custom_button(__("Remove Hidden Columns"), () => {
			frm.doc.fields = (frm.doc.fields || []).filter((f) => f.is_visible);
			frm.refresh_field("fields");
			frm.dirty();
		});
		frm.add_custom_button(__("Run Report"), () => {
			frappe.set_route("query-report", "Order Wise Profitability", { report_profile: frm.doc.name });
		});
	},
});

function open_picker(frm) {
	frappe.call({
		method: "neotec_order_costing.api.field_catalog.get_catalog_tree",
		callback: (r) => {
			const tree = r.message || [];
			const active = new Set((frm.doc.fields || []).map((f) => `${f.source_document}||${f.fieldname}`));

			const html = tree.map((g) => {
				const boxes = g.fields.map((f) => {
					const dis = active.has(f.value) ? "disabled checked" : "";
					return `<label style="display:block;margin:2px 0;font-weight:400">
						<input type="checkbox" class="noc-pick" value="${f.value}" ${dis}>
						${frappe.utils.escape_html(f.label)}
					</label>`;
				}).join("");
				return `<div style="margin-bottom:12px">
					<div style="font-weight:500">${frappe.utils.escape_html(g.doctype_label)}</div>
					<div style="padding-left:10px">${boxes}</div></div>`;
			}).join("");

			const d = new frappe.ui.Dialog({
				title: __("Add Columns From Any Document"),
				size: "large",
				fields: [{ fieldtype: "HTML", fieldname: "picker",
						   options: `<div style="max-height:460px;overflow:auto">${html}</div>` }],
				primary_action_label: __("Add"),
				primary_action() {
					const picks = Array.from(d.$wrapper[0].querySelectorAll("input.noc-pick:checked:not(:disabled)"))
						.map((e) => {
							const [source_document, fieldname] = e.value.split("||");
							return { source_document, fieldname };
						});
					if (!picks.length) { d.hide(); return; }
					frappe.call({
						method: "neotec_order_costing.neotec_order_costing.doctype.profitability_report_profile.profitability_report_profile.add_fields",
						args: { profile: frm.doc.name, selections: picks },
						freeze: true,
						callback: () => { d.hide(); frm.reload_doc(); },
					});
				},
			});
			d.show();
		},
	});
}
