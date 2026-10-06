frappe.ui.form.on("Purchase Order", {
	refresh(frm) {
		if (!frm.doc.nxg_is_cross_hire) return;
		frm.dashboard.add_comment(
			__("Cross hire order {0}: equipment lines are quantity-only (zero rate). Hire cost sits on the charge lines and is billed by Purchase Invoice.", [
				frm.doc.nxg_cross_hire_order,
			]),
			"blue",
			true
		);
		if (frm.doc.docstatus === 1 && frm.doc.nxg_cross_hire_order) {
			frm.add_custom_button(__("Cross Hire Order"), () =>
				frappe.set_route("Form", "Cross Hire Order", frm.doc.nxg_cross_hire_order)
			);
		}
	},
});
