const M = "thinknxg_rental.subcontracting.doctype.subcontract_daily_progress.subcontract_daily_progress.";
const ACT = (frm, method, label, args, group) => frm.add_custom_button(__(label), () => {
	const run = (extra) => frappe.call({ method: M + method, args: Object.assign({ name: frm.doc.name }, extra || {}), freeze: true, callback: () => frm.reload_doc() });
	if (args) frappe.prompt(args, run, __(label));
	else run();
}, group ? __(group) : null);
const REMARK = (name, label, reqd) => [{ fieldname: name, label: __(label), fieldtype: "Small Text", reqd: reqd ? 1 : 0 }];
frappe.ui.form.on("Subcontract Daily Progress", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 0) return;
		frm.page.clear_primary_action();
		if (["Draft", "Returned"].includes(frm.doc.status)) ACT(frm, "submit_for_review", "Submit for Review");
		if (["Draft", "Submitted"].includes(frm.doc.status)) ACT(frm, "approve", "Approve", REMARK("review_remarks", "Review remarks (shown to the subcontractor)"));
		if (frm.doc.status === "Submitted") ACT(frm, "return_for_correction", "Return for Correction", REMARK("review_remarks", "What needs correcting", 1));
	},
	subcontract_work_order(frm) { fill_items(frm); },
});
function fill_items(frm) {
	if (!frm.doc.subcontract_work_order || (frm.doc.items || []).length) return;
	frappe.db.get_doc("Subcontract Work Order", frm.doc.subcontract_work_order).then((w) => {
		w.items.forEach((r) => frm.add_child("items", { swo_item: r.name, job_type: r.job_type, description: r.description, ordered_qty: r.qty, reported_before: r.reported_qty }));
		frm.refresh_field("items");
	});
}
