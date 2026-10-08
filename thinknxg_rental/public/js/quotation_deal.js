frappe.ui.form.on("Quotation", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 1 || !frm.doc.deal_type) return;
		const method = "thinknxg_rental.services.deal_flow.";
		if (frm.doc.deal_type === "Material Hire") {
			frm.add_custom_button(__("Hire Order"), () => frappe.model.open_mapped_doc({
				method: method + "make_hire_order_from_quotation", frm
			}), __("Create"));
		} else if (frm.doc.deal_type === "Material Sale") {
			frm.add_custom_button(__("Sales Order"), () => frappe.model.open_mapped_doc({
				method: method + "make_sales_order_from_quotation", frm
			}), __("Create"));
		} else if (frm.doc.deal_type === "Hire Order Contract") {
			frm.add_custom_button(__("Hire Order Contract"), () => frappe.model.open_mapped_doc({
				method: method + "make_hire_order_contract_from_quotation", frm
			}), __("Create"));
		}
		frm.page.set_inner_btn_group_as_primary(__("Create"));
	},
});
