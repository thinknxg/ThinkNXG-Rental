const M = "thinknxg_rental.subcontracting.doctype.subcontract_work_order.subcontract_work_order.";
frappe.ui.form.on("Subcontract Work Order", {
	setup(frm) {
		frm.set_query("supplier", () => ({ filters: { is_subcontractor: 1, subcontractor_approval_status: "Approved", disabled: 0 } }));
		frm.set_query("hire_order_contract", () => ({ filters: { docstatus: 1 } }));
		frm.set_query("agreement", () => ({ filters: { docstatus: 1, status: "Active", supplier: frm.doc.supplier } }));
	},
	refresh(frm) {
		const act = (label, method, group, args = {}) => frm.add_custom_button(__(label), () =>
			frappe.call({ method: M + method, args: { name: frm.doc.name, ...args }, freeze: true, callback: () => frm.reload_doc() }), group ? __(group) : null);
		if (frm.doc.docstatus === 0 && !frm.is_new()) {
			if (frm.doc.status === "Draft") act("Send for Approval", "submit_for_approval");
			if (frm.doc.status === "Pending Approval") { act("Approve", "approve"); act("Return to Draft", "reject"); }
			frm.page.clear_primary_action();
		}
		if (frm.doc.docstatus === 1) {
			if (["Approved", "Rejected by Subcontractor"].includes(frm.doc.status)) act("Send to Subcontractor", "send_to_subcontractor");
			if (["Approved", "Sent to Subcontractor", "Accepted by Subcontractor"].includes(frm.doc.status)) act("Start Work", "start_work");
			if (!["On Hold", "Pending Final Verification", "Verified", "Closed", "Cancelled"].includes(frm.doc.status))
				frm.add_custom_button(__("Put on Hold"), () => frappe.prompt({ fieldname: "reason", label: __("Reason"), fieldtype: "Small Text", reqd: 1 },
					(v) => frappe.call({ method: M + "put_on_hold", args: { name: frm.doc.name, reason: v.reason }, freeze: true, callback: () => frm.reload_doc() }), __("Put on Hold")));
			if (frm.doc.status === "On Hold") act("Resume", "resume");
			frm.add_custom_button(__("Command Center"), () => window.open("/rental/admin/subcontracting/work-orders/" + encodeURIComponent(frm.doc.name)));
			if (frm.doc.status === "Pending Final Verification") act("Verify Completion", "verify_completion");
			if (frm.doc.status === "Verified") act("Close", "close");
			const make = (doctype, label) => frm.add_custom_button(__(label), () =>
				frappe.new_doc(doctype, { subcontract_work_order: frm.doc.name }), __("Create"));
			make("Subcontract Material Allocation", "Material Allocation");
			make("Subcontract Work Progress", "Work Progress");
			make("Subcontract Material Return", "Material Return");
			make("Subcontract Completion Report", "Completion Report");
			make("Subcontract Settlement", "Settlement");
			make("Subcontract Daily Progress", "Daily Progress");
			make("Subcontract Material Request", "Material Request");
			make("Subcontract Variation", "Variation");
			make("Subcontractor Invoice Submission", "Supplier Invoice");
			if (!frm.doc.purchase_order) act("Purchase Order", "make_purchase_order", "Create");
			if (frm.doc.advance_amount) frm.add_custom_button(__("Advance Payment"), () => frappe.prompt(
				[{ fieldname: "amount", label: __("Amount"), fieldtype: "Currency", reqd: 1, default: frm.doc.advance_amount }, { fieldname: "mode_of_payment", label: __("Mode of Payment"), fieldtype: "Link", options: "Mode of Payment" }],
				(v) => frappe.call({ method: M + "make_advance_payment", args: { name: frm.doc.name, ...v }, callback: (r) => frappe.set_route("Form", "Payment Entry", r.message) }),
				__("Advance Payment")), __("Create"));
		}
	},
});
frappe.ui.form.on("Subcontract Work Item", {
	qty: (frm, cdt, cdn) => { const r = locals[cdt][cdn]; frappe.model.set_value(cdt, cdn, "amount", flt(r.qty) * flt(r.rate)); },
	rate: (frm, cdt, cdn) => { const r = locals[cdt][cdn]; frappe.model.set_value(cdt, cdn, "amount", flt(r.qty) * flt(r.rate)); },
});
