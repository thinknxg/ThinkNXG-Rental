const M = "thinknxg_rental.subcontracting.doctype.subcontract_material_request.subcontract_material_request.";
const ACT = (frm, method, label, args, group) => frm.add_custom_button(__(label), () => {
	const run = (extra) => frappe.call({ method: M + method, args: Object.assign({ name: frm.doc.name }, extra || {}), freeze: true, callback: () => frm.reload_doc() });
	if (args) frappe.prompt(args, run, __(label));
	else run();
}, group ? __(group) : null);
const REMARK = (name, label, reqd) => [{ fieldname: name, label: __(label), fieldtype: "Small Text", reqd: reqd ? 1 : 0 }];
frappe.ui.form.on("Subcontract Material Request", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.docstatus === 0) {
			frm.page.clear_primary_action();
			if (frm.doc.status === "Draft") ACT(frm, "submit_request", "Submit Request");
			if (["Draft", "Submitted"].includes(frm.doc.status)) {
				ACT(frm, "approve", "Approve", REMARK("review_remarks", "Remarks (shown to the subcontractor)"));
				ACT(frm, "reject", "Reject", REMARK("review_remarks", "Reason (shown to the subcontractor)", 1));
			}
		}
		if (frm.doc.docstatus === 1 && ["Approved", "Partially Issued"].includes(frm.doc.status))
			frm.add_custom_button(__("Issue Material"), () => frappe.model.open_mapped_doc({ method: M + "make_material_allocation", frm }), __("Create"));
	},
});
