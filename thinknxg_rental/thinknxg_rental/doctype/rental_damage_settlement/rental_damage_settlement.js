frappe.ui.form.on("Rental Damage Settlement", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && !frm.doc.sales_invoice) {
			frm.add_custom_button(__("Create Sales Invoice"), () =>
				frappe.call({
					method: "thinknxg_rental.thinknxg_rental.doctype.rental_damage_settlement.rental_damage_settlement.make_sales_invoice",
					args: { settlement: frm.doc.name },
					freeze: true,
					callback: (r) => r.message && frappe.set_route("Form", "Sales Invoice", r.message),
				})
			).addClass("btn-primary");
		}
	},
});

frappe.ui.form.on("Rental Damage Settlement Item", {
	qty: (frm, cdt, cdn) => set_amount(frm, cdt, cdn),
	rate: (frm, cdt, cdn) => set_amount(frm, cdt, cdn),
	liability_percent: (frm, cdt, cdn) => set_amount(frm, cdt, cdn),
	salvage_value: (frm, cdt, cdn) => set_amount(frm, cdt, cdn),
});

function set_amount(frm, cdt, cdn) {
	const d = locals[cdt][cdn];
	const amount = Math.max((flt(d.qty) * flt(d.rate) * flt(d.liability_percent)) / 100 - flt(d.salvage_value), 0);
	frappe.model.set_value(cdt, cdn, "amount", amount);
}
