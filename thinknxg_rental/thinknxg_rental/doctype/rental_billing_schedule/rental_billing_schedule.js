frappe.ui.form.on("Rental Billing Schedule", {
	setup(frm) {
		frm.set_query("rental_contract", () => ({ filters: { docstatus: 1 } }));
	},
	refresh(frm) {
		frm.get_field("items").grid.cannot_add_rows = true;
		if (frm.doc.docstatus === 0) {
			frm.set_intro(__("Billing lines are calculated from the material-at-site ledger when you save."));
		}
		if (frm.doc.docstatus === 1 && !frm.doc.sales_invoice) {
			frm.add_custom_button(__("Create Sales Invoice"), () =>
				frappe.call({
					method: "thinknxg_rental.services.billing.make_sales_invoice",
					args: { schedule: frm.doc.name },
					freeze: true,
					callback: (r) => r.message && frappe.set_route("Form", "Sales Invoice", r.message),
				})
			).addClass("btn-primary");
		}
	},
});
