frappe.ui.form.on("Rental Portal Request", {
	setup(frm) {
		frm.set_query("hire_contract", () => ({ filters: { docstatus: 1, customer: frm.doc.customer } }));
	},
	refresh(frm) {
		if (frm.is_new() || ["Completed", "Rejected", "Cancelled"].includes(frm.doc.status)) return;
		const base = "thinknxg_rental.thinknxg_rental.doctype.rental_portal_request.rental_portal_request.";
		if (frm.doc.request_type === "Hire Enquiry") {
			frm.add_custom_button(__("Create Hire Order"), () =>
				frappe.model.open_mapped_doc({ method: base + "make_hire_order", frm })
			).addClass("btn-primary");
		} else if (frm.doc.request_type === "Off-Hire Request") {
			frm.add_custom_button(__("Create Off-Hire Note"), () =>
				frappe.model.open_mapped_doc({ method: base + "make_off_hire_note", frm })
			).addClass("btn-primary");
		} else {
			frm.add_custom_button(__("Extend Contract"), () =>
				frappe.confirm(__("Extend {0} to {1}?", [frm.doc.hire_contract, frappe.datetime.str_to_user(frm.doc.new_end_date)]), () =>
					frm.call("apply_extension").then(() => frm.reload_doc())
				)
			).addClass("btn-primary");
		}
		frm.add_custom_button(__("Reject"), () =>
			frappe.prompt(
				[{ fieldname: "response", fieldtype: "Small Text", label: __("Reason shown to the customer"), reqd: 1 }],
				(v) => {
					frm.set_value({ status: "Rejected", response: v.response });
					frm.save();
				},
				__("Reject Request")
			)
		);
	},
});
