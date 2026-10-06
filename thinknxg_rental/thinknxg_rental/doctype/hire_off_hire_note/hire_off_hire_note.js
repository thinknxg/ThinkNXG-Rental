frappe.ui.form.on("Hire Off-Hire Note", {
	setup(frm) {
		frm.set_query("hire_contract", () => ({ filters: { docstatus: 1, status: ["in", ["On Hire", "Active"]] } }));
		frm.set_query("target_warehouse", "items", () => ({ filters: { is_group: 0, company: frm.doc.company } }));
	},
	refresh(frm) {
		const base = "thinknxg_rental.thinknxg_rental.doctype.hire_off_hire_note.hire_off_hire_note.";
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Items at Site"), () => frm.trigger("get_items"));
		}
		if (frm.doc.docstatus !== 1) return;
		if (frm.doc.inspection_status === "Pending") {
			frm.add_custom_button(__("Return Inspection"), () => frappe.model.open_mapped_doc({ method: base + "make_inspection", frm }), __("Create"));
		} else {
			frm.add_custom_button(__("Damage Settlement"), () => frappe.model.open_mapped_doc({ method: base + "make_damage_settlement", frm }), __("Create"));
		}
		frm.page.set_inner_btn_group_as_primary(__("Create"));
	},
	hire_contract(frm) {
		if (!frm.doc.hire_contract) return;
		frappe.db.get_value("Hire Order Contract", frm.doc.hire_contract, "grace_days").then((r) => {
			frm.set_value("grace_days", (r.message && r.message.grace_days) || 0);
		});
		if (!(frm.doc.items || []).some((d) => d.item_code)) frm.trigger("get_items");
	},
	get_items(frm) {
		if (!frm.doc.hire_contract) return frappe.msgprint(__("Select a Hire Contract first"));
		frappe.call({
			method: "thinknxg_rental.thinknxg_rental.doctype.hire_off_hire_note.hire_off_hire_note.get_items_at_site",
			args: { hire_contract: frm.doc.hire_contract },
			callback(r) {
				frm.clear_table("items");
				(r.message || []).forEach((row) => frm.add_child("items", row));
				frm.refresh_field("items");
			},
		});
	},
});
