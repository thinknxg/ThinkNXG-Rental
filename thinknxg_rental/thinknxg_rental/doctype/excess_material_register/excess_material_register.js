frappe.ui.form.on("Excess Material Register", {
	refresh(frm) {
		frm.disable_save();
		if (frm.doc.status === "Cancelled") return;
		if (frm.doc.available_qty > 0) {
			frm.add_custom_button(__("Excess Material Return Note"), () => {
				frappe.call({
					method: "thinknxg_rental.thinknxg_rental.doctype.excess_material_return_note.excess_material_return_note.make_from_registers",
					args: { registers: [frm.doc.name] },
					callback: (r) => {
						const doc = frappe.model.sync(r.message)[0];
						frappe.set_route("Form", doc.doctype, doc.name);
					},
				});
			}, __("Create"));
			frm.add_custom_button(__("Excess Material Abandonment"), () => frappe.model.open_mapped_doc({
				method: "thinknxg_rental.thinknxg_rental.doctype.excess_material_abandonment.excess_material_abandonment.make_from_register", frm }), __("Create"));
			frm.add_custom_button(__("Dismantling Entry"), () => {
				frappe.new_doc("Dismantling Entry", { rental_contract: frm.doc.rental_contract });
			}, __("Create"));
		}
		if (frm.doc.convertible_qty > 0) {
			frm.add_custom_button(__("Excess Material Conversion Entry"), () => frappe.model.open_mapped_doc({
				method: "thinknxg_rental.thinknxg_rental.doctype.excess_material_conversion_entry.excess_material_conversion_entry.make_from_register",
				frm }), __("Create"));
		}
		frm.add_custom_button(__("Adjustment History"), () => thinknxg_rental.excess_history({ register: frm.doc.name }), __("View"));
	},
});
