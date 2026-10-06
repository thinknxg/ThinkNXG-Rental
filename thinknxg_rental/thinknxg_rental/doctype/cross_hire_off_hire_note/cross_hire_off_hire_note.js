frappe.ui.form.on("Cross Hire Off-Hire Note", {
	setup(frm) {
		frm.set_query("cross_hire_order", () => ({ filters: { docstatus: 1, status: ["in", ["On Hire", "Partially Returned"]] } }));
		frm.set_query("return_from_warehouse", () => ({ filters: { is_group: 0, company: frm.doc.company } }));
	},
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.purchase_returns) {
			frm.add_custom_button(__("Purchase Returns"), () =>
				frappe.set_route("List", "Purchase Receipt", { nxg_cross_hire_off_hire_note: frm.doc.name })
			);
		}
	},
	cross_hire_order(frm) {
		if (!frm.doc.cross_hire_order || (frm.doc.items || []).some((d) => d.item_code)) return;
		frappe.model.open_mapped_doc({
			method: "thinknxg_rental.thinknxg_rental.doctype.cross_hire_off_hire_note.cross_hire_off_hire_note.make_cross_hire_off_hire_note",
			source_name: frm.doc.cross_hire_order,
		});
	},
});
