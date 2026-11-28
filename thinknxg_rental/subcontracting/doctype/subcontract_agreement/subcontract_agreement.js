const M = "thinknxg_rental.subcontracting.doctype.subcontract_agreement.subcontract_agreement.";
const ACT = (frm, method, label, args, group) => frm.add_custom_button(__(label), () => {
	const run = (extra) => frappe.call({ method: M + method, args: Object.assign({ name: frm.doc.name }, extra || {}), freeze: true, callback: () => frm.reload_doc() });
	if (args) frappe.prompt(args, run, __(label));
	else run();
}, group ? __(group) : null);
const REMARK = (name, label, reqd) => [{ fieldname: name, label: __(label), fieldtype: "Small Text", reqd: reqd ? 1 : 0 }];
frappe.ui.form.on("Subcontract Agreement", {
	setup(frm) { frm.set_query("supplier", () => ({ filters: { is_subcontractor: 1, disabled: 0 } })); },
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.docstatus === 0) {
			frm.page.clear_primary_action();
			if (frm.doc.status === "Draft") ACT(frm, "submit_for_approval", "Send for Approval");
			if (frm.doc.status === "Pending Approval") { ACT(frm, "approve", "Approve"); ACT(frm, "reject", "Return to Draft", REMARK("reason", "Reason")); }
		}
		if (frm.doc.docstatus === 1 && ["Active", "Expired"].includes(frm.doc.status)) {
			ACT(frm, "terminate", "Terminate", REMARK("reason", "Reason", 1));
			frm.add_custom_button(__("Work Order"), () => frappe.new_doc("Subcontract Work Order", { supplier: frm.doc.supplier, agreement: frm.doc.name, project: frm.doc.project,
				customer: frm.doc.customer, company: frm.doc.company, hire_order_contract: frm.doc.hire_order_contract }), __("Create"));
		}
	},
});
