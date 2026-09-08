frappe.provide("neotec.order_costing");

neotec.order_costing.open_settings = function () {
	frappe.set_route("Form", "Order Costing Settings");
};

neotec.order_costing.cogs_source_colour = function (source) {
	return {
		"Pegged Batch Valuation": "green",
		"Pegged PO Rate": "blue",
		"Default Valuation": "orange",
		"Add-on Item": "purple",
	}[source] || "gray";
};

// ---------------------------------------------------------------------------
// Extra column picker, shared by every profitability report
// ---------------------------------------------------------------------------

neotec.order_costing._catalog = null;

neotec.order_costing.load_catalog = function () {
	if (neotec.order_costing._catalog) {
		return Promise.resolve(neotec.order_costing._catalog);
	}
	return frappe
		.call({ method: "neotec_order_costing.api.report_columns.get_extra_catalog" })
		.then((r) => {
			neotec.order_costing._catalog = r.message || [];
			return neotec.order_costing._catalog;
		});
};

// MultiSelectList calls this synchronously, so serve from cache and warm it
// on first miss.
neotec.order_costing.extra_column_options = function (txt) {
	const catalog = neotec.order_costing._catalog;
	if (!catalog) {
		neotec.order_costing.load_catalog();
		return [];
	}
	const needle = (txt || "").toLowerCase();
	const out = [];
	catalog.forEach((group) => {
		group.fields.forEach((f) => {
			const label = `${group.doctype_label}: ${f.label}`;
			if (!needle || label.toLowerCase().includes(needle)) {
				out.push({ value: f.value, description: label });
			}
		});
	});
	return out.slice(0, 50);
};

neotec.order_costing.add_column_picker = function (report, fieldname) {
	neotec.order_costing.load_catalog();

	report.page.add_inner_button(__("Add Columns"), () => {
		neotec.order_costing.load_catalog().then((catalog) => {
			const current = new Set(report.get_filter_value(fieldname) || []);

			const html = catalog
				.map((group) => {
					const boxes = group.fields
						.map((f) => {
							const checked = current.has(f.value) ? "checked" : "";
							return `<label style="display:block;margin:2px 0;font-weight:400">
								<input type="checkbox" class="noc-extra" value="${f.value}" ${checked}>
								${frappe.utils.escape_html(f.label)}
							</label>`;
						})
						.join("");
					return `<div style="margin-bottom:12px">
						<div style="font-weight:500;margin-bottom:4px">
							${frappe.utils.escape_html(group.doctype_label)}
						</div>
						<div style="padding-left:10px">${boxes}</div>
					</div>`;
				})
				.join("");

			const d = new frappe.ui.Dialog({
				title: __("Add Columns From Related Documents"),
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
						d.$wrapper[0].querySelectorAll("input.noc-extra:checked")
					).map((el) => el.value);
					report.set_filter_value(fieldname, chosen);
					d.hide();
				},
			});
			d.show();
		});
	});

	report.page.add_inner_button(__("Clear Extra Columns"), () => {
		report.set_filter_value(fieldname, []);
	});
};
