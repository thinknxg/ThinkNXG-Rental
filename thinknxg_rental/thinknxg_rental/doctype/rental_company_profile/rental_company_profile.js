frappe.ui.form.on("Rental Company Profile", {
	setup(frm) {
		["security_deposit_account", "customer_advance_account"].forEach((f) =>
			frm.set_query(f, () => ({ filters: { company: frm.doc.company, is_group: 0, root_type: "Liability", account_type: "Receivable" } })));
		frm.set_query("output_vat_account", () => ({ filters: { company: frm.doc.company, is_group: 0, root_type: "Liability" } }));
		frm.set_query("sales_taxes_template", () => ({ filters: { company: frm.doc.company, disabled: 0 } }));
		["zero_rated_item_tax_template", "exempt_item_tax_template", "out_of_scope_item_tax_template"].forEach((f) =>
			frm.set_query(f, () => ({ filters: { company: frm.doc.company, disabled: 0 } }))
		);
	},
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.reviewed_on) {
			frm.dashboard.set_headline_alert(__("VAT rules reviewed by {0} on {1}", [frm.doc.reviewed_by, frappe.datetime.str_to_user(frm.doc.reviewed_on)]), "green");
		} else {
			frm.dashboard.set_headline_alert(__("VAT rules not reviewed by finance yet: pro forma invoices show a review note until they are."), "orange");
		}
		if (frappe.user.has_role(["Accounts Manager", "System Manager"])) {
			frm.add_custom_button(__("Mark Rules Reviewed"), () =>
				frappe.prompt([{ fieldname: "note", fieldtype: "Small Text", label: __("Review Note") }], (v) =>
					frm.call("mark_reviewed", { note: v.note }).then(() => frm.reload_doc()), __("Finance Review"))
			);
		}
		if (frappe.user.has_role(["Accounts Manager", "System Manager"]) && (!frm.doc.security_deposit_account || !frm.doc.customer_advance_account)) {
			frm.add_custom_button(__("Set Up Accounts"), () => frm.call("setup_accounts").then(() => frm.reload_doc()));
		}
		if (!(frm.doc.rules || []).length) {
			frm.add_custom_button(__("Add Starting Rules"), () => frm.call("add_default_rules").then(() => frm.reload_doc()));
		}
	},
});
