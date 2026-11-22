frappe.ui.form.on("Rental Contract Payment", {
	setup(frm) {
		frm.set_query("account", () => ({ filters: { company: frm.doc.company, is_group: 0, account_type: ["in", ["Bank", "Cash"]] } }));
		frm.set_query("rental_contract", () => ({ filters: { docstatus: 1, company: frm.doc.company || undefined } }));
		frm.set_query("sales_invoice", () => ({ filters: { customer: frm.doc.customer, company: frm.doc.company, docstatus: 1, is_return: 0, outstanding_amount: [">", 0] } }));
		frm.set_query("pro_forma_invoice", () => ({ filters: { docstatus: 1, customer: frm.doc.customer || undefined } }));
	},
	refresh(frm) {
		if (frm.doc.status === "Pending Approval") {
			frm.dashboard.set_headline_alert(__("Waiting for approval: an Accounts Manager or Rental Manager submits it to post the refund or deduction."), "orange");
		}
		if (frm.doc.journal_entry) {
			frm.add_custom_button(__("Journal Entry"), () => frappe.set_route("Form", "Journal Entry", frm.doc.journal_entry), __("View"));
		}
	},
	mode_of_payment(frm) {
		if (!frm.doc.mode_of_payment || !frm.doc.company) return;
		frappe.xcall("thinknxg_rental.thinknxg_rental.doctype.rental_contract_payment.rental_contract_payment.get_payment_account",
			{ mode_of_payment: frm.doc.mode_of_payment, company: frm.doc.company }).then((a) => a && frm.set_value("account", a));
	},
});
