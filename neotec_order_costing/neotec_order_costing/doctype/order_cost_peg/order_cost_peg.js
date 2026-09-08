frappe.ui.form.on("Order Cost Peg", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		if (frm.doc.sales_order) {
			frm.add_custom_button(__("Sales Order"), () => {
				frappe.set_route("Form", "Sales Order", frm.doc.sales_order);
			}, __("View"));
		}
		if (frm.doc.purchase_order) {
			frm.add_custom_button(__("Purchase Order"), () => {
				frappe.set_route("Form", "Purchase Order", frm.doc.purchase_order);
			}, __("View"));
		}
		if (frm.doc.batch_no) {
			frm.add_custom_button(__("Batch Traceability"), () => {
				frappe.set_route("query-report", "Batch Cost Traceability", { batch_no: frm.doc.batch_no });
			}, __("View"));
		}
		const margin = (frm.doc.selling_rate || 0) - (frm.doc.effective_cost_rate || 0);
		frm.dashboard.add_indicator(
			__("Unit margin: {0}", [format_currency(margin)]),
			margin >= 0 ? "green" : "red"
		);
	},
});
