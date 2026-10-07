frappe.ui.form.on("Lead", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 0 || !frm.doc.deal_type) return;
		frm.add_custom_button(__("Quotation"), () => {
			frappe.model.open_mapped_doc({
				method: "thinknxg_rental.services.deal_flow.make_quotation_from_lead",
				frm,
			});
		}, __("Create"));
		frm.page.set_inner_btn_group_as_primary(__("Create"));
	},
});
