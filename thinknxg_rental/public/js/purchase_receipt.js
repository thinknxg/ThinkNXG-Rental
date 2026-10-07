frappe.ui.form.on("Purchase Receipt", {
	refresh(frm) {
		if (!frm.doc.nxg_is_cross_hire_receipt) return;
		frm.dashboard.add_comment(
			__("Cross hire receipt: stock quantity is updated at zero rate and zero valuation. The material remains supplier-owned."),
			"blue",
			true
		);
		if (frm.doc.docstatus === 1 && frm.doc.nxg_cross_hire_order) {
			frappe.db.get_value("Cross Hire Order", frm.doc.nxg_cross_hire_order, ["rental_contract", "receive_at", "status"]).then((r) => {
				const d = r.message || {};
				if (!d.rental_contract) return;
				if (d.receive_at === "Direct to Site") {
					frm.add_custom_button(__("Continue to JCR"), () => {
						frappe.db.get_value("Rental Contract", d.rental_contract, "source_document").then((x) => {
							const hoc = x.message && x.message.source_document;
							if (hoc) frappe.set_route("Form", "Hire Order Contract", hoc);
							else frappe.set_route("Form", "Rental Contract", d.rental_contract);
						});
					}, __("Continue Workflow"));
				} else {
					frm.add_custom_button(__("Continue to Delivery"), () => {
						frappe.call({
							method: "thinknxg_rental.thinknxg_rental.doctype.rental_contract.rental_contract.make_delivery_order",
							args: { source_name: d.rental_contract },
							freeze: true,
							callback(res) {
								if (!res.message) return;
								const doc = frappe.model.sync(res.message)[0];
								frappe.set_route("Form", doc.doctype, doc.name);
							}
						});
					}, __("Continue Workflow"));
				}
			});
		}
	},
	nxg_is_cross_hire_receipt(frm) {
		if (!frm.doc.nxg_is_cross_hire_receipt) return;
		(frm.doc.items || []).forEach((d) => frappe.model.set_value(d.doctype, d.name, { rate: 0, allow_zero_valuation_rate: 1 }));
	},
});
