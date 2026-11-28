const M = "thinknxg_rental.subcontracting.doctype.subcontract_variation.subcontract_variation.";
const ACT = (frm, method, label, args, group) => frm.add_custom_button(__(label), () => {
	const run = (extra) => frappe.call({ method: M + method, args: Object.assign({ name: frm.doc.name }, extra || {}), freeze: true, callback: () => frm.reload_doc() });
	if (args) frappe.prompt(args, run, __(label));
	else run();
}, group ? __(group) : null);
const REMARK = (name, label, reqd) => [{ fieldname: name, label: __(label), fieldtype: "Small Text", reqd: reqd ? 1 : 0 }];
frappe.ui.form.on("Subcontract Variation", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 0) return;
		frm.page.clear_primary_action();
		if (frm.doc.status === "Draft") ACT(frm, "submit_variation", "Submit");
		if (frm.doc.status === "Submitted") ACT(frm, "start_review", "Start Review");
		if (["Draft", "Submitted", "Under Review"].includes(frm.doc.status)) {
			ACT(frm, "approve", "Approve", [{ fieldname: "approved_amount", label: __("Approved amount (claims)"), fieldtype: "Currency", default: frm.doc.approved_amount || frm.doc.claimed_amount },
				{ fieldname: "external_remarks", label: __("Remarks to the subcontractor"), fieldtype: "Small Text" }]);
		}
		if (["Submitted", "Under Review"].includes(frm.doc.status)) ACT(frm, "reject", "Reject", REMARK("reason", "Reason", 1));
	},
});
