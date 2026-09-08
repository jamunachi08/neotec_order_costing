frappe.ui.form.on("Purchase Order", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.docstatus === 0) {
			frappe.db.get_single_value("Order Costing Settings", "enable_consolidation").then((on) => {
				if (!on) return;
				frm.add_custom_button(__("Demand by Brand"), () => get_items_by_brand(frm), __("Get Items From"));
			});
		}
		if (frm.doc.docstatus !== 1) return;
		frm.add_custom_button(__("Cost Pegs"), () => {
			frappe.set_route("List", "Order Cost Peg", { purchase_order: frm.doc.name });
		}, __("View"));

		frm.add_custom_button(__("Allocation Across Orders"), () => show_allocation(frm), __("View"));

		frappe.db.get_single_value("Order Costing Settings", "procurement_flow").then((flow) => {
			if (flow === "Purchase Invoice with Update Stock") {
				frm.dashboard.add_comment(
					__("Order Costing is set to post stock directly from the Purchase Invoice. A Purchase Receipt is not required."),
					"blue", true
				);
			}
		});
	},
});


function get_items_by_brand(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Get Open Demand by Brand"),
		size: "extra-large",
		fields: [
			{ fieldname: "brand", label: __("Brand"), fieldtype: "Link", options: "Brand" },
			{ fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group" },
			{ fieldtype: "Column Break" },
			{ fieldname: "from_date", label: __("Required From"), fieldtype: "Date" },
			{ fieldname: "to_date", label: __("Required To"), fieldtype: "Date" },
			{ fieldtype: "Column Break" },
			{ fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse" },
			{
				fieldname: "include_unlinked_requests", label: __("Include Stock Requests"),
				fieldtype: "Check",
				description: __("Requests with no sales order behind them."),
			},
			{ fieldtype: "Section Break" },
			{ fieldname: "results", fieldtype: "HTML" },
		],
		primary_action_label: __("Search"),
		primary_action(v) {
			frappe.call({
				method: "neotec_order_costing.api.consolidation.get_demand",
				args: Object.assign({ company: frm.doc.company }, v),
				freeze: true,
				callback: (r) => render_results(d, frm, r.message || []),
			});
		},
	});
	d.show();
}

function render_results(d, frm, rows) {
	if (!rows.length) {
		d.fields_dict.results.$wrapper.html(`<p>${__("No open demand matches those filters.")}</p>`);
		return;
	}
	const totals = {};
	rows.forEach((r) => { totals[r.item_code] = (totals[r.item_code] || 0) + r.qty_pending; });

	const body = rows.map((r, i) => `<tr>
		<td><input type="checkbox" class="noc-dem" data-idx="${i}" checked></td>
		<td>${frappe.utils.escape_html(r.item_code)}</td>
		<td>${frappe.utils.escape_html(r.brand || "-")}</td>
		<td>${frappe.utils.escape_html(r.sales_order || "-")}</td>
		<td>${frappe.utils.escape_html(r.customer || "-")}</td>
		<td class="text-right">${r.qty_pending}</td>
		<td>${frappe.utils.escape_html(r.required_by || "-")}</td>
	</tr>`).join("");

	const summary = Object.entries(totals)
		.map(([item, qty]) => `<b>${frappe.utils.escape_html(item)}</b>: ${qty}`)
		.join(" &middot; ");

	d.fields_dict.results.$wrapper.html(
		`<div style="margin-bottom:6px">${__("Consolidated")}: ${summary}</div>
		<div style="max-height:340px;overflow:auto">
		<table class="table table-bordered"><thead><tr>
		<th style="width:36px"></th><th>${__("Item")}</th><th>${__("Brand")}</th>
		<th>${__("Sales Order")}</th><th>${__("Customer")}</th>
		<th class="text-right">${__("Pending")}</th><th>${__("Required By")}</th>
		</tr></thead><tbody>${body}</tbody></table></div>`
	);

	d.set_primary_action(__("Add to Purchase Order"), () => {
		const picked = Array.from(d.$wrapper[0].querySelectorAll("input.noc-dem:checked"))
			.map((e) => rows[parseInt(e.dataset.idx, 10)]);
		if (!picked.length) {
			frappe.msgprint(__("Select at least one line."));
			return;
		}
		const merged = {};
		picked.forEach((r) => {
			const key = `${r.item_code}::${r.uom}::${r.warehouse}`;
			if (!merged[key]) merged[key] = Object.assign({}, r, { qty: 0 });
			merged[key].qty += r.qty_pending;
		});
		Object.values(merged).forEach((r) => {
			const row = frm.add_child("items", {
				item_code: r.item_code,
				qty: r.qty,
				uom: r.uom,
				warehouse: r.warehouse,
				schedule_date: r.required_by,
				material_request: r.material_request,
				material_request_item: r.material_request_item,
			});
			frappe.model.set_value(row.doctype, row.name, "item_code", r.item_code);
		});
		frm.refresh_field("items");
		d.hide();
		frappe.show_alert({
			message: __("{0} consolidated line(s) added", [Object.keys(merged).length]),
			indicator: "green",
		});
	});
}

function show_allocation(frm) {
	const lines = (frm.doc.items || []).map((i) => i.name);
	if (!lines.length) return;
	Promise.all(
		lines.map((n) =>
			frappe.call({
				method: "neotec_order_costing.api.allocation.get_allocation",
				args: { purchase_order_item: n },
			})
		)
	).then((results) => {
		const body = [];
		results.forEach((res, i) => {
			(res.message || []).forEach((a) => {
				body.push(`<tr>
					<td>${frappe.utils.escape_html(frm.doc.items[i].item_code)}</td>
					<td>${frappe.utils.escape_html(a.sales_order || "-")}</td>
					<td class="text-right">${a.allocated}</td>
					<td class="text-right">${a.received}</td>
				</tr>`);
			});
		});
		if (!body.length) {
			frappe.msgprint(__("No cost pegs are linked to this purchase order."));
			return;
		}
		frappe.msgprint({
			title: __("Allocation Across Sales Orders"),
			message: `<table class="table table-bordered"><thead><tr>
				<th>${__("Item")}</th><th>${__("Sales Order")}</th>
				<th class="text-right">${__("Allocated")}</th>
				<th class="text-right">${__("Received")}</th>
				</tr></thead><tbody>${body.join("")}</tbody></table>`,
		});
	});
}
