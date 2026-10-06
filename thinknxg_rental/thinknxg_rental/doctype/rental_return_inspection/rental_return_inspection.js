frappe.ui.form.on("Rental Return Inspection", {
	setup(frm) {
		frm.set_query("hire_off_hire_note", () => ({ filters: { docstatus: 1, inspection_status: "Pending" } }));
	},
	refresh(frm) {
		frm.get_field("items").grid.cannot_add_rows = true;
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Damage Settlement"), () =>
				frappe.model.open_mapped_doc({
					method: "thinknxg_rental.thinknxg_rental.doctype.hire_off_hire_note.hire_off_hire_note.make_damage_settlement",
					source_name: frm.doc.hire_off_hire_note,
				})
			);
		}
	},
	hire_off_hire_note(frm) {
		if (!frm.doc.hire_off_hire_note || (frm.doc.items || []).length) return;
		frappe.model.open_mapped_doc({
			method: "thinknxg_rental.thinknxg_rental.doctype.hire_off_hire_note.hire_off_hire_note.make_inspection",
			source_name: frm.doc.hire_off_hire_note,
		});
	},
});

frappe.ui.form.on("Rental Return Inspection Item", {
	repairable_qty: (frm, cdt, cdn) => set_good_qty(cdt, cdn),
	damaged_qty: (frm, cdt, cdn) => set_good_qty(cdt, cdn),
});

function set_good_qty(cdt, cdn) {
	const d = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "good_qty", Math.max(flt(d.returned_qty) - flt(d.repairable_qty) - flt(d.damaged_qty), 0));
}
