frappe.ui.form.on("Subcontract Work Progress", {
	subcontract_work_order(frm) {
		if (!frm.doc.subcontract_work_order || !frm.is_new()) return;
		frappe.call({ method: "thinknxg_rental.subcontracting.api.prefill", args: { doctype: frm.doctype, subcontract_work_order: frm.doc.subcontract_work_order },
			callback: (r) => { frm.clear_table("items"); (r.message || []).forEach((row) => frm.add_child("items", row)); frm.refresh_field("items"); } });
	},
});

frappe.ui.form.on("Subcontract Work Progress", {
	refresh(frm) {
		if (!frm.is_new() && frm.doc.docstatus === 0 && frm.doc.inspection_status === "Inspection Requested")
			frm.add_custom_button(__("Schedule Inspection"), () => frappe.prompt([{ fieldname: "proposed_inspection_date", label: __("Inspection date"), fieldtype: "Date",
				default: frm.doc.proposed_inspection_date }, { fieldname: "inspector", label: __("Inspector"), fieldtype: "Link", options: "User", default: frappe.session.user }],
			(v) => frappe.call({ method: "thinknxg_rental.subcontracting.doctype.subcontract_work_progress.subcontract_work_progress.start_inspection",
				args: Object.assign({ name: frm.doc.name }, v), callback: () => frm.reload_doc() }), __("Schedule Inspection")));
	},
});
