frappe.ui.form.on("Purchase Receipt", {
	refresh(frm) {
		if (frm.doc.nxg_is_cross_hire_receipt) {
			frm.dashboard.add_comment(
				__("Cross hire receipt: stock quantity is updated at zero rate and zero valuation. The material remains supplier-owned."),
				"blue",
				true
			);
		}
	},
	nxg_is_cross_hire_receipt(frm) {
		if (!frm.doc.nxg_is_cross_hire_receipt) return;
		(frm.doc.items || []).forEach((d) => {
			frappe.model.set_value(d.doctype, d.name, { rate: 0, allow_zero_valuation_rate: 1 });
		});
	},
});
