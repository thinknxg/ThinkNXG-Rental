frappe.ui.form.on("Subcontract Material Return", {
	subcontract_work_order(frm) {
		if (!frm.doc.subcontract_work_order || !frm.is_new()) return;
		frappe.call({ method: "thinknxg_rental.subcontracting.api.prefill", args: { doctype: frm.doctype, subcontract_work_order: frm.doc.subcontract_work_order },
			callback: (r) => { frm.clear_table("items"); (r.message || []).forEach((row) => frm.add_child("items", row)); frm.refresh_field("items"); } });
	},
});
