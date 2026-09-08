frappe.ui.form.on("Supplier Quotation", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.docstatus !== 1) return;
		frm.add_custom_button(__("Cost Pegs"), () => {
			frappe.set_route("List", "Order Cost Peg", {
				procurement_document: frm.doc.name,
			});
		}, __("View"));
	},
});
