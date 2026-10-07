frappe.ui.form.on("JCR Billing Schedule", {
	refresh(frm) {
		frm.disable_save();
		if (frm.doc.status === "Pending" && !frm.doc.sales_invoice && flt(frm.doc.amount) > 0) {
			frm.add_custom_button(__("Create Sales Invoice"), () =>
				frappe.call({
					method: "thinknxg_rental.services.jcr_billing.make_sales_invoice",
					args: { schedule: frm.doc.name },
					freeze: true,
					callback: (r) => r.message && frappe.set_route("Form", "Sales Invoice", r.message),
				})
			).addClass("btn-primary");
		}
	},
});
