// Dismantling Entry: outstanding delivered material settled against the customer's excess material.
// Both tables of balances come from the server (submitted transactions); the form only previews totals.
frappe.ui.form.on("Dismantling Entry", {
	setup(frm) {
		frm.set_query("rental_contract", () => ({ filters: { docstatus: 1, status: ["not in", ["Completed", "Cancelled"]] } }));
		frm.set_query("hire_delivery_order", () => ({ filters: { rental_contract: frm.doc.rental_contract, docstatus: 1 } }));
		frm.set_query("hire_off_hire_note", () => ({ filters: { rental_contract: frm.doc.rental_contract, docstatus: 1 } }));
		frm.set_query("outstanding_item", "adjustments", () => ({
			filters: { name: ["in", (frm.doc.outstanding_items || []).filter((d) => flt(d.outstanding_qty) > 0).map((d) => d.item_code)] },
		}));
		frm.set_query("excess_register", "adjustments", () => ({
			filters: { name: ["in", (frm.doc.excess_items || []).filter((d) => flt(d.available_qty) > 0).map((d) => d.excess_register)] },
		}));
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.rental_contract) {
			frm.add_custom_button(__("Refresh Balances"), () => frm.trigger("fetch_balances"));
		}
		if (frm.doc.rental_contract) {
			frm.add_custom_button(__("Adjustment History"), () => thinknxg_rental.excess_history({ rental_contract: frm.doc.rental_contract }), __("View"));
		}
		if (frm.doc.docstatus === 0) {
			frm.set_intro(__("Settles material the customer still owes against excess material they handed over. Enter both quantities on each row: items are never assumed to be interchangeable. Excess stays in the excess warehouse as its own item."), "blue");
		}
	},
	rental_contract(frm) {
		if (frm.doc.rental_contract) frm.trigger("fetch_balances");
	},
	allow_cross_project(frm) {
		if (frm.doc.rental_contract) frm.trigger("fetch_balances");
	},
	fetch_balances(frm) {
		return frm.call({ method: "fetch_balances", doc: frm.doc, freeze: true }).then(() => frm.refresh_fields());
	},
	totals(frm) {
		const rows = frm.doc.adjustments || [];
		const settled = {}, used = {};
		rows.forEach((d) => {
			settled[d.outstanding_item] = (settled[d.outstanding_item] || 0) + flt(d.adjustment_qty);
			used[d.excess_register] = (used[d.excess_register] || 0) + flt(d.excess_qty_used);
		});
		(frm.doc.outstanding_items || []).forEach((d) => {
			d.adjustment_qty = settled[d.item_code] || 0;
			d.remaining_qty = flt(d.outstanding_qty) - d.adjustment_qty;
		});
		(frm.doc.excess_items || []).forEach((d) => {
			d.adjustment_qty = used[d.excess_register] || 0;
			d.remaining_qty = flt(d.available_qty) - d.adjustment_qty;
		});
		frm.set_value("total_adjustment_qty", rows.reduce((s, d) => s + flt(d.adjustment_qty), 0));
		frm.set_value("total_excess_used_qty", rows.reduce((s, d) => s + flt(d.excess_qty_used), 0));
		frm.set_value("remaining_outstanding_qty", flt(frm.doc.total_outstanding_qty) - flt(frm.doc.total_adjustment_qty));
		frm.refresh_field("outstanding_items");
		frm.refresh_field("excess_items");
	},
});

frappe.ui.form.on("Dismantling Adjustment", {
	outstanding_item(frm, cdt, cdn) {
		const d = locals[cdt][cdn];
		const row = (frm.doc.outstanding_items || []).find((o) => o.item_code === d.outstanding_item);
		frappe.model.set_value(cdt, cdn, "outstanding_qty", row ? flt(row.outstanding_qty) : 0);
		frm.trigger("totals");
	},
	excess_register(frm, cdt, cdn) {
		const d = locals[cdt][cdn];
		const row = (frm.doc.excess_items || []).find((e) => e.excess_register === d.excess_register);
		frappe.model.set_value(cdt, cdn, "excess_available_qty", row ? flt(row.available_qty) : 0);
		frm.trigger("totals");
	},
	adjustment_qty(frm, cdt, cdn) {
		set_ratio(cdt, cdn);
		frm.trigger("totals");
	},
	excess_qty_used(frm, cdt, cdn) {
		set_ratio(cdt, cdn);
		frm.trigger("totals");
	},
	adjustments_remove(frm) {
		frm.trigger("totals");
	},
});

function set_ratio(cdt, cdn) {
	const d = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "conversion_ratio", flt(d.adjustment_qty) ? flt(d.excess_qty_used) / flt(d.adjustment_qty) : 0);
}
