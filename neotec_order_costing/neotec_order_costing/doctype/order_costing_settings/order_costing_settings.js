frappe.ui.form.on("Order Costing Settings", {
	refresh(frm) {
		show_version(frm);
		frm.add_custom_button(__("Test Batch ID"), () => test_batch_id(frm));
		frm.add_custom_button(__("Column Profiles"), () => {
			frappe.set_route("List", "Profitability Report Profile");
		});
		frm.add_custom_button(__("Open Profitability Report"), () => {
			frappe.set_route("query-report", "Order Wise Profitability");
		});
		frm.add_custom_button(__("Pick Peg Fields"), () => pick_peg_fields(frm), __("Cost Visibility"));
		frm.add_custom_button(__("Refresh an Order Chain"), () => refresh_chain(), __("Cost Visibility"));
		frm.add_custom_button(__("Repair Schema"), () => {
			frappe.call({
				method: "neotec_order_costing.install.repair_schema",
				freeze: true, freeze_message: __("Creating missing fields"),
				callback: (r) => {
					const res = r.message || {};
					const before = Object.entries(res.before || {})
						.map(([dt, f]) => `<li>${dt}: ${f.join(", ")}</li>`).join("");
					frappe.msgprint({
						title: res.fixed ? __("Schema Repaired") : __("Still Missing"),
						indicator: res.fixed ? "green" : "red",
						message: before
							? __("Created:") + `<ul>${before}</ul>`
							: __("Nothing was missing."),
					});
				},
			});
		}, __("Maintenance"));
		frm.add_custom_button(__("Check Configuration"), () => {
			frappe.call({ method: "neotec_order_costing.api.repair.run", freeze: true,
				freeze_message: __("Checking and repairing"),
				callback: (r) => {
					const res = r.message || {};
					frappe.show_alert({
						message: __("Repaired {0} peg(s)", [res.pegs || 0]),
						indicator: "green",
					});
				},
			});
		}, __("Maintenance"));

		if (frm.doc.allow_destructive_cleanup) {
			frm.add_custom_button(__("Delete Linked Documents"), () => open_cleanup(), __("Maintenance"));
			frm.add_custom_button(__("Reset Simulation Data"), () => reset_simulation(), __("Maintenance"));
			frm.page.set_indicator(__("Destructive cleanup enabled"), "red");
		}

		if (!frm.doc.enable_order_wise_cogs) {
			frm.dashboard.add_comment(
				__("Order-wise COGS is off. Stock valuation behaves exactly like the standard ERP."),
				"blue", true
			);
		} else if (frm.doc.enable_auto_batch && frm.doc.auto_batch_applies_to !== "Stock Inward Document") {
			frm.dashboard.add_comment(
				__("Create Batch On must be 'Stock Inward Document'. Other modes are not implemented and auto batch creation will not run reliably."),
				"red", true
			);
		} else if (frm.doc.costing_mode === "Pegged PO Rate") {
			frm.dashboard.add_comment(
				__("Pegged PO Rate reports COGS at the purchase order rate. Stock still posts at real valuation, so enable the variance journal to keep the ledger reconciled."),
				"orange", true
			);
		}
	},

	enable_auto_batch(frm) {
		if (frm.doc.enable_auto_batch && !(frm.doc.batch_naming_components || []).length) {
			frappe.msgprint(__("Add at least one component to define what a batch number looks like."));
		}
	},
});

frappe.ui.form.on("Batch Naming Component", {
	component(frm) { frm.save(); },
	static_value(frm) { frm.save(); },
	components_remove(frm) { frm.save(); },
});

function test_batch_id(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Test Batch ID Composition"),
		fields: [
			{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item", reqd: 1 },
			{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order" },
			{ fieldname: "purchase_order", label: __("Purchase Order"), fieldtype: "Link", options: "Purchase Order" },
			{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
			{ fieldname: "posting_date", label: __("Posting Date"), fieldtype: "Date",
			  default: frappe.datetime.get_today() },
			{ fieldname: "result", label: __("Resulting Batch ID"), fieldtype: "Data", read_only: 1 },
		],
		primary_action_label: __("Generate"),
		primary_action(values) {
			frappe.call({
				method: "neotec_order_costing.neotec_order_costing.doctype.order_costing_settings.order_costing_settings.preview_batch_id",
				args: { context: values },
				callback: (r) => d.set_value("result", r.message || __("Nothing generated")),
			});
		},
	});
	d.show();
}


function open_cleanup() {
	const d = new frappe.ui.Dialog({
		title: __("Delete Linked Document Cycle"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				options:
					"<div style='padding:8px;border-left:3px solid #A32D2D;background:#FBF0F0;margin-bottom:10px'>" +
					__("Pick any document in the cycle. Everything linked to it, upstream and downstream, is cancelled and deleted: quotations, orders, requests, receipts, invoices, deliveries, cost pegs, batches and their ledger entries. This cannot be undone.") +
					"</div>",
			},
			{
				fieldname: "anchor_doctype", label: __("Anchor Document Type"),
				fieldtype: "Select", reqd: 1, default: "Sales Order",
				options: [
					"Quotation", "Sales Order", "Material Request", "Purchase Order",
					"Purchase Receipt", "Purchase Invoice", "Delivery Note",
					"Sales Invoice", "Order Cost Peg", "Batch",
				],
				onchange() {
					const d2 = cur_dialog;
					d2.set_value("anchor", "");
					d2.set_df_property("anchor", "options", d2.get_value("anchor_doctype"));
					d2.fields_dict.preview.$wrapper.empty();
					d2.set_df_property("confirmation", "read_only", 1);
					d2.set_primary_action(__("Preview"), () => do_preview(d2));
				},
			},
			{
				fieldname: "anchor", label: __("Document"), fieldtype: "Dynamic Link",
				options: "anchor_doctype",
				description: __("Leave blank to use the company and date range instead."),
			},
			{ fieldtype: "Column Break" },
			{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
			  default: frappe.defaults.get_user_default("Company") },
			{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
			{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
			{ fieldtype: "Section Break" },
			{
				fieldname: "exclude_doctypes", label: __("Protect These Document Types"),
				fieldtype: "MultiSelectList",
				description: __("Traversal stops at anything listed here and it is never deleted."),
				get_data() {
					return [
						"Payment Entry", "Journal Entry", "Sales Invoice", "Purchase Invoice",
						"Delivery Note", "Purchase Receipt", "Landed Cost Voucher",
						"Purchase Order", "Material Request", "Sales Order", "Quotation",
						"Batch", "Order Cost Peg",
					];
				},
			},
			{ fieldtype: "Section Break" },
			{ fieldname: "preview", fieldtype: "HTML" },
			{ fieldtype: "Section Break" },
			{
				fieldname: "confirmation", label: __("Type DELETE to confirm"),
				fieldtype: "Data", read_only: 1,
				description: __("Enabled once a preview has been run."),
			},
		],
		primary_action_label: __("Preview"),
		primary_action() { do_preview(d); },
	});
	d.show();
}

function cleanup_args(d) {
	const v = d.get_values(true);
	return {
		anchors: v.anchor ? [v.anchor] : null,
		anchor_doctype: v.anchor_doctype,
		company: v.company,
		from_date: v.from_date,
		to_date: v.to_date,
		exclude_doctypes: v.exclude_doctypes || [],
	};
}

function do_preview(d) {
	frappe.call({
		method: "neotec_order_costing.api.cleanup.preview",
		args: cleanup_args(d),
		freeze: true,
		freeze_message: __("Tracing linked documents"),
		callback: (r) => {
			const res = r.message || {};
			d.fields_dict.preview.$wrapper.html(res.html || "");
			if (!res.total) {
				d.set_df_property("confirmation", "read_only", 1);
				return;
			}
			d.set_df_property("confirmation", "read_only", 0);
			d.set_primary_action(__("Delete {0} Documents", [res.total]), () => {
				run_cleanup(d, res.total);
			});
		},
	});
}

function run_cleanup(d, total) {
	const confirmation = d.get_value("confirmation");
	if (confirmation !== "DELETE") {
		frappe.msgprint(__("Type DELETE in the confirmation box."));
		return;
	}
	frappe.confirm(
		__("Permanently delete {0} document(s)? This cannot be undone.", [total]),
		() => {
			frappe.call({
				method: "neotec_order_costing.api.cleanup.execute_cleanup",
				args: Object.assign(cleanup_args(d), { confirmation: confirmation }),
				freeze: true,
				freeze_message: __("Deleting"),
				callback: (r) => {
					const res = r.message || {};
					d.hide();
					let msg = __("Deleted {0} document(s).", [res.deleted_count || 0]);
					if (res.failed_count) {
						msg += "<br><b>" + __("{0} failed:", [res.failed_count]) + "</b><br>" +
							(res.failed || []).slice(0, 15).map(frappe.utils.escape_html).join("<br>");
					}
					frappe.msgprint({
						title: __("Cleanup Complete"),
						message: msg,
						indicator: res.failed_count ? "orange" : "green",
					});
				},
			});
		}
	);
}

function reset_simulation() {
	frappe.prompt(
		[{ fieldname: "confirmation", label: __("Type DELETE to confirm"), fieldtype: "Data", reqd: 1 }],
		(v) => {
			frappe.call({
				method: "neotec_order_costing.api.cleanup.reset_simulation",
				args: { confirmation: v.confirmation },
				freeze: true,
				freeze_message: __("Removing simulation data"),
				callback: (r) => {
					const res = r.message || {};
					frappe.msgprint(
						__("Removed {0} record(s), {1} failure(s).",
						   [res.deleted_count || 0, res.failed_count || 0])
					);
				},
			});
		},
		__("Reset Simulation Data"),
		__("Delete")
	);
}


function show_version(frm) {
	frappe.call({
		method: "neotec_order_costing.api.repair.get_app_info",
		callback: (r) => {
			const info = r.message || {};
			if (info.schema_current) {
				frm.dashboard.add_indicator(
					__("Order Costing v{0}", [info.code_version]), "green"
				);
				return;
			}
			frm.dashboard.add_indicator(
				__("v{0} installed, database not migrated", [info.code_version]), "red"
			);
			const gaps = Object.entries(info.missing_fields || {})
				.map(([v, f]) => `<li>${v}: ${f.join(", ")}</li>`)
				.join("");
			frm.dashboard.add_comment(
				__("Features from these versions are missing from the database. Run bench migrate.") +
					`<ul>${gaps}</ul>`,
				"red", true
			);
		},
	});
}


function pick_peg_fields(frm) {
	frappe.call({
		method: "neotec_order_costing.api.cost_stamp.get_peg_field_options",
		callback: (r) => {
			const options = r.message || [];
			const d = new frappe.ui.Dialog({
				title: __("Copy a Field From Order Cost Peg"),
				fields: [
					{
						fieldname: "peg_fieldname", label: __("Field on Order Cost Peg"),
						fieldtype: "Select", reqd: 1,
						options: options.map((o) => ({ label: `${o.label} (${o.fieldname})`, value: o.fieldname })),
					},
					{
						fieldname: "target_doctype", label: __("Copy To"), fieldtype: "Select", reqd: 1,
						options: ["Quotation Item", "Sales Order Item", "Delivery Note Item", "Sales Invoice Item"],
						default: "Sales Order Item",
					},
					{
						fieldname: "target_fieldname", label: __("Target Field Name"),
						fieldtype: "Data", reqd: 1, default: "custom_noc_",
						description: __("Created automatically on the next migrate."),
					},
				],
				primary_action_label: __("Add"),
				primary_action(v) {
					const src = options.find((o) => o.fieldname === v.peg_fieldname) || {};
					const row = frm.add_child("cost_visibility_fields", {
						peg_fieldname: v.peg_fieldname,
						target_doctype: v.target_doctype,
						target_fieldname: v.target_fieldname,
						target_fieldtype: src.fieldtype || "Currency",
						enabled: 1,
					});
					frm.refresh_field("cost_visibility_fields");
					frm.save().then(() => {
						d.hide();
						frappe.msgprint(__("Added. Run bench migrate to create the target field."));
					});
				},
			});
			d.show();
		},
	});
}

function refresh_chain() {
	frappe.prompt(
		[{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link",
		   options: "Sales Order", reqd: 1 }],
		(v) => {
			frappe.call({
				method: "neotec_order_costing.api.cost_stamp.refresh_sales_order_chain",
				args: { sales_order: v.sales_order },
				freeze: true,
				freeze_message: __("Pushing purchase cost through the chain"),
				callback: (r) => {
					const res = r.message || {};
					const lines = Object.entries(res).map(([dt, val]) => {
						const arr = Array.isArray(val) ? val : [val];
						const n = arr.reduce((a, x) => a + (x.updated || 0), 0);
						return `${dt}: ${n}`;
					}).join("<br>");
					frappe.msgprint({ title: __("Refreshed"), message: lines, indicator: "green" });
				},
			});
		},
		__("Refresh Purchase Cost Across Chain"),
		__("Refresh")
	);
}
