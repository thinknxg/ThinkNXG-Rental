// Excess Material Abandonment: a Rental Manager approves (by submitting) that excess still held for the
// customer was abandoned by them. The excess then belongs to the company; no stock moves.
frappe.ui.form.on("Excess Material Abandonment", {
	setup(frm) {
		frm.set_query("excess_register", "items", () => ({
			filters: {
				customer: frm.doc.customer,
				available_qty: [">", 0],
				status: ["!=", "Cancelled"],
				...(frm.doc.project ? { project: frm.doc.project } : {}),
				...(frm.doc.rental_contract ? { rental_contract: frm.doc.rental_contract } : {}),
				...(frm.doc.hire_off_hire_note ? { hire_off_hire_note: frm.doc.hire_off_hire_note } : {}),
			},
		}));
		frm.set_query("rental_contract", () => ({ filters: { customer: frm.doc.customer, docstatus: 1 } }));
		frm.set_query("hire_off_hire_note", () => ({ filters: { customer: frm.doc.customer, docstatus: 1 } }));
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Excess Items"), () => frm.trigger("get_items"));
			frm.set_intro(
				frappe.user.has_role(["Rental Manager", "System Manager"])
					? __("Submitting approves the excess below as abandoned by the customer: it stops being theirs and can be converted into rental stock. No stock moves.")
					: __("Record the basis and evidence, save, and ask a Rental Manager to approve (submit) it."),
				"blue"
			);
		}
		if (frm.doc.rental_contract) {
			frm.add_custom_button(__("Adjustment History"), () => thinknxg_rental.excess_history({ rental_contract: frm.doc.rental_contract }), __("View"));
		}
	},
	get_items(frm) {
		if (!frm.doc.customer) return frappe.msgprint(__("Select the Customer first"));
		frappe.call({
			method: "thinknxg_rental.thinknxg_rental.doctype.excess_material_return_note.excess_material_return_note.get_excess_items",
			args: { customer: frm.doc.customer, project: frm.doc.project, rental_contract: frm.doc.rental_contract, hire_off_hire_note: frm.doc.hire_off_hire_note },
			callback(r) {
				const rows = r.message || [];
				if (!rows.length) return frappe.msgprint(__("Nothing of this customer's excess is still held for them"));
				frm.clear_table("items");
				rows.forEach((row) => frm.add_child("items", {
					excess_register: row.excess_register, item_code: row.item_code, item_name: row.item_name, uom: row.uom,
					hire_off_hire_note: row.hire_off_hire_note, available_qty: row.available_qty, abandon_qty: row.available_qty, balance_qty: 0,
				}));
				frm.refresh_field("items");
			},
		});
	},
});

frappe.ui.form.on("Excess Material Abandonment Item", {
	excess_register(frm, cdt, cdn) {
		const d = locals[cdt][cdn];
		if (!d.excess_register) return;
		frappe.db.get_value("Excess Material Register", d.excess_register, "available_qty").then((r) => {
			const avail = flt(r.message && r.message.available_qty);
			frappe.model.set_value(cdt, cdn, { available_qty: avail, abandon_qty: avail, balance_qty: 0 });
		});
	},
	abandon_qty(frm, cdt, cdn) {
		const d = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, "balance_qty", flt(d.available_qty) - flt(d.abandon_qty));
	},
});
