frappe.ui.form.on("Quotation", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 1) return;
		const method = "thinknxg_rental.services.deal_flow.";
		if (frm.doc.quotation_to === "Lead" && frm.doc.party_name) {
			frm.add_custom_button(__("Convert Party to Customer"), () =>
				frappe.call({
					method: method + "convert_quotation_party_to_customer",
					args: { source_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Converting party to Customer..."),
				}).then((r) => {
					if (r.message) {
						frappe.show_alert({ message: __("Customer {0} created/linked", [r.message]), indicator: "green" });
						frm.reload_doc();
					}
				})
			);
		}
		if (!frm.doc.deal_type) return;
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
