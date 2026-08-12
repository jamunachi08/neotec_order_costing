frappe.ui.form.on("Item", {
	refresh(frm) {
		if (frm.is_new()) return;

		frappe.db.get_single_value("Order Costing Settings", "enable_specifications").then((on) => {
			if (!on) return;

			frm.add_custom_button(__("Apply Specification Template"), () => apply_template(frm), __("Part Number"));
			frm.add_custom_button(__("Compare With Another Part"), () => compare_parts(frm), __("Part Number"));
			frm.add_custom_button(__("Spec Sheet"), () => {
				window.open(
					frappe.urllib.get_full_url(
						"/api/method/frappe.utils.print_format.download_pdf?doctype=Item" +
						"&name=" + encodeURIComponent(frm.doc.name) +
						"&format=" + encodeURIComponent("Part Number Spec Sheet")
					)
				);
			}, __("Part Number"));

			show_part_numbers(frm);
		});
	},
});

function show_part_numbers(frm) {
	frappe.call({
		method: "neotec_order_costing.api.specs.get_item_specifications",
		args: { item_code: frm.doc.name, customer_visible_only: 0 },
		callback: (r) => {
			const specs = r.message || [];
			if (!specs.length) {
				frm.dashboard.add_indicator(__("No specifications recorded"), "orange");
			} else {
				const blank = specs.filter((s) => !s.value_en).length;
				frm.dashboard.add_indicator(
					blank
						? __("{0} specification(s), {1} not filled", [specs.length, blank])
						: __("{0} specification(s) complete", [specs.length]),
					blank ? "orange" : "green"
				);
			}
		},
	});
}

function apply_template(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Apply Specification Template"),
		fields: [
			{ fieldname: "template", label: __("Template"), fieldtype: "Link",
			  options: "Specification Template", reqd: 1 },
		],
		primary_action_label: __("Apply"),
		primary_action(v) {
			frm.set_value("custom_noc_spec_template", v.template);
			frm.save().then(() => d.hide());
		},
	});
	d.show();
}

function compare_parts(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Compare Part Numbers"),
		size: "large",
		fields: [
			{ fieldname: "other", label: __("Compare With"), fieldtype: "Link", options: "Item", reqd: 1 },
			{ fieldname: "result", fieldtype: "HTML" },
		],
		primary_action_label: __("Compare"),
		primary_action(v) {
			frappe.call({
				method: "neotec_order_costing.api.equivalence.compare_parts",
				args: { item_a: frm.doc.name, item_b: v.other },
				callback: (r) => d.fields_dict.result.$wrapper.html(r.message || ""),
			});
		},
	});
	d.show();
}
