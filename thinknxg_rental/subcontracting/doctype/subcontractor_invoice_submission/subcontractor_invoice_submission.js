const M = "thinknxg_rental.subcontracting.doctype.subcontractor_invoice_submission.subcontractor_invoice_submission.";
const ACT = (frm, method, label, args, group) => frm.add_custom_button(__(label), () => {
	const run = (extra) => frappe.call({ method: M + method, args: Object.assign({ name: frm.doc.name }, extra || {}), freeze: true, callback: () => frm.reload_doc() });
	if (args) frappe.prompt(args, run, __(label));
	else run();
}, group ? __(group) : null);
const REMARK = (name, label, reqd) => [{ fieldname: name, label: __(label), fieldtype: "Small Text", reqd: reqd ? 1 : 0 }];
frappe.ui.form.on("Subcontractor Invoice Submission", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 0) return;
		frm.page.clear_primary_action();
		if (frm.doc.status === "Draft") ACT(frm, "submit_for_verification", "Submit for Verification");
		if (["Draft", "Submitted"].includes(frm.doc.status)) ACT(frm, "verify", "Verify and Create Purchase Invoice", REMARK("review_remarks", "Remarks (shown to the subcontractor)"));
		if (frm.doc.status === "Submitted") ACT(frm, "reject", "Reject", REMARK("reason", "Reason", 1));
	},
});
