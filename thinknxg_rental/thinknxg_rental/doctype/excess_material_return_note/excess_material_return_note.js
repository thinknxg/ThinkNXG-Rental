// Excess Material Return Note: excess material handed back to the customer, out of the excess warehouse.
frappe.ui.form.on("Excess Material Return Note", {
	setup(frm) {
		frm.set_query("excess_register", "items", () => ({
			filters: {
				customer: frm.doc.customer,
				status: ["not in", ["Closed", "Cancelled"]],
				...(frm.doc.source_warehouse ? { excess_warehouse: frm.doc.source_warehouse } : {}),
				...(frm.doc.hire_off_hire_note ? { hire_off_hire_note: frm.doc.hire_off_hire_note } : {}),
			},
		}));
		frm.set_query("hire_off_hire_note", () => ({ filters: { customer: frm.doc.customer, docstatus: 1 } }));
		frm.set_query("rental_contract", () => ({ filters: { customer: frm.doc.customer, docstatus: 1 } }));
		frm.set_query("source_warehouse", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
		frm.set_query("target_warehouse", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Excess Items"), () => frm.trigger("get_items"));
		}
	},
	get_items(frm) {
		if (!frm.doc.customer) return frappe.msgprint(__("Select the Customer first"));
		frappe.call({
			method: "thinknxg_rental.thinknxg_rental.doctype.excess_material_return_note.excess_material_return_note.get_excess_items",
			args: {
				customer: frm.doc.customer, project: frm.doc.project, rental_contract: frm.doc.rental_contract,
				hire_off_hire_note: frm.doc.hire_off_hire_note, source_warehouse: frm.doc.source_warehouse,
			},
			callback(r) {
				const rows = r.message || [];
				if (!rows.length) return frappe.msgprint(__("No excess material of this customer is available to return"));
				frm.clear_table("items");
				rows.forEach((row) => frm.add_child("items", row));
				if (!frm.doc.source_warehouse) frm.set_value("source_warehouse", rows[0].source_warehouse);
				frm.refresh_field("items");
			},
		});
	},
});

frappe.ui.form.on("Excess Material Return Item", {
	excess_register(frm, cdt, cdn) {
		const d = locals[cdt][cdn];
		if (!d.excess_register) return;
		frappe.db.get_value("Excess Material Register", d.excess_register, "available_qty").then((r) => {
			const avail = flt(r.message && r.message.available_qty);
			frappe.model.set_value(cdt, cdn, { available_qty: avail, return_qty: avail, balance_qty: 0 });
		});
	},
	return_qty(frm, cdt, cdn) {
		const d = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, "balance_qty", flt(d.available_qty) - flt(d.return_qty));
	},
});
