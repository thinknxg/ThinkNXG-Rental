// Excess Material Conversion Entry: excess the company owns moved into rental stock, as the same or another
// item, through one Repack Stock Entry. Explicit and optional: never made by any other document.
const EMC = "thinknxg_rental.thinknxg_rental.doctype.excess_material_conversion_entry.excess_material_conversion_entry.";

frappe.ui.form.on("Excess Material Conversion Entry", {
	setup(frm) {
		frm.set_query("excess_register", "items", () => ({
			filters: {
				customer: frm.doc.customer,
				convertible_qty: [">", 0],
				status: ["!=", "Cancelled"],
				...(frm.doc.project ? { project: frm.doc.project } : {}),
				...(frm.doc.source_warehouse ? { excess_warehouse: frm.doc.source_warehouse } : {}),
			},
		}));
		// target: own rental warehouses only (rental stock)
		thinknxg_rental.rental_warehouses().then((list) => {
			const own = () => ({ filters: { name: ["in", list.filter((w) => w.category === "Own").map((w) => w.warehouse)], company: frm.doc.company } });
			frm.set_query("target_warehouse", own);
			frm.set_query("target_warehouse", "items", own);
		});
		frm.set_query("source_warehouse", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
		frm.set_query("difference_account", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
		frm.set_query("target_item_code", "items", () => ({
			filters: { is_stock_item: 1, disabled: 0, has_variants: 0, is_fixed_asset: 0 },
		}));
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Convertible Excess"), () => frm.trigger("get_items"));
			frm.set_intro(
				__("Only excess adjusted on a submitted Dismantling Entry belongs to the company and can be converted. The source item is consumed from the excess warehouse and the target item received into rental stock on one Repack Stock Entry; customer balances are not touched."),
				"blue"
			);
		}
		if (frm.doc.stock_entry) {
			frm.add_custom_button(__("Stock Ledger"), () =>
				frappe.set_route("query-report", "Stock Ledger", { voucher_no: frm.doc.stock_entry, company: frm.doc.company,
					from_date: frm.doc.posting_date, to_date: frm.doc.posting_date }), __("View"));
		}
	},
	target_warehouse(frm) {
		(frm.doc.items || []).forEach((d) => {
			if (!d.target_warehouse) frappe.model.set_value(d.doctype, d.name, "target_warehouse", frm.doc.target_warehouse);
		});
	},
	get_items(frm) {
		if (!frm.doc.customer) return frappe.msgprint(__("Select the Customer first"));
		frappe.call({
			method: EMC + "get_convertible_items",
			args: { customer: frm.doc.customer, project: frm.doc.project, source_warehouse: frm.doc.source_warehouse },
			callback(r) {
				const rows = r.message || [];
				if (!rows.length) return frappe.msgprint(__("This customer has no adjusted excess left to convert"));
				frm.clear_table("items");
				rows.forEach((row) => frm.add_child("items", Object.assign(row, { target_warehouse: frm.doc.target_warehouse })));
				if (!frm.doc.source_warehouse) frm.set_value("source_warehouse", rows[0].excess_warehouse);
				frm.refresh_field("items");
				frm.trigger("totals");
			},
		});
	},
	totals(frm) {
		const rows = frm.doc.items || [];
		frm.set_value("total_conversion_qty", rows.reduce((s, d) => s + flt(d.conversion_qty), 0));
		frm.set_value("total_target_qty", rows.reduce((s, d) => s + flt(d.target_qty), 0));
		frm.set_value("total_value", rows.reduce((s, d) => s + flt(d.amount), 0));
	},
});

frappe.ui.form.on("Excess Material Conversion Item", {
	items_add(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "target_warehouse", frm.doc.target_warehouse);
	},
	excess_register(frm, cdt, cdn) {
		const d = locals[cdt][cdn];
		if (!d.excess_register) return;
		frappe.db.get_value("Excess Material Register", d.excess_register, ["convertible_qty", "item_code"]).then((r) => {
			const m = r.message || {};
			frappe.model.set_value(cdt, cdn, { available_qty: flt(m.convertible_qty), conversion_qty: flt(m.convertible_qty), target_qty: flt(m.convertible_qty) });
			if (!d.target_item_code && frm.doc.conversion_type === "Convert to Existing Rental Item") {
				frappe.model.set_value(cdt, cdn, "target_item_code", m.item_code);
			}
		});
	},
	conversion_qty(frm, cdt, cdn) {
		const d = locals[cdt][cdn];
		if (!flt(d.target_qty)) frappe.model.set_value(cdt, cdn, "target_qty", d.conversion_qty);
		frm.trigger("totals");
	},
	target_qty(frm, cdt, cdn) {
		set_amount(frm, cdt, cdn);
	},
	valuation_rate(frm, cdt, cdn) {
		set_amount(frm, cdt, cdn);
	},
	target_item_code(frm, cdt, cdn) {
		fetch_rate(frm, cdt, cdn);
	},
	target_warehouse(frm, cdt, cdn) {
		fetch_rate(frm, cdt, cdn);
	},
	valuation_basis(frm, cdt, cdn) {
		fetch_rate(frm, cdt, cdn);
	},
	items_remove(frm) {
		frm.trigger("totals");
	},
});

function fetch_rate(frm, cdt, cdn) {
	const d = locals[cdt][cdn];
	if (d.valuation_basis === "Zero Value") {
		frappe.model.set_value(cdt, cdn, "valuation_rate", 0);
	} else if (d.valuation_basis === "Target Item Valuation Rate" && d.target_item_code) {
		frappe.call({
			method: EMC + "get_valuation_rate",
			args: { item_code: d.target_item_code, warehouse: d.target_warehouse, posting_date: frm.doc.posting_date },
			callback: (r) => frappe.model.set_value(cdt, cdn, "valuation_rate", flt(r.message)),
		});
	}
}

function set_amount(frm, cdt, cdn) {
	const d = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "amount", flt(d.target_qty) * flt(d.valuation_rate));
	frm.trigger("totals");
}
