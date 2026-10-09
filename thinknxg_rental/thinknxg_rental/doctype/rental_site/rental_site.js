// Rental Site made from a quotation: Create -> Hire Order carries on from here with the site filled in.
frappe.ui.form.on("Rental Site", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.disabled) return;
		frm.add_custom_button(__("Hire Order"), async () => {
			const quotation = frm.doc.nxg_quotation;
			if (!quotation) {
				frappe.new_doc("Hire Order", {
					customer: frm.doc.customer,
					customer_name: frm.doc.customer_name,
					company: frm.doc.company,
					rental_site: frm.doc.name,
				});
				return;
			}
			const r = await frappe.db.get_value("Quotation", quotation, ["deal_type", "docstatus"]);
			const v = r.message || {};
			if (v.docstatus !== 1) {
				frappe.msgprint(__("Submit quotation {0} first, then use this button.", [quotation]));
				return;
			}
			const fn = v.deal_type === "Hire Order Contract" ? "make_hire_order_contract_from_quotation" : "make_hire_order_from_quotation";
			frappe.model.open_mapped_doc({
				method: "thinknxg_rental.services.deal_flow." + fn,
				source_name: quotation,
				args: { rental_site: frm.doc.name },
			});
		}, __("Create"));
		frm.page.set_inner_btn_group_as_primary(__("Create"));
	},
});
