const M = "thinknxg_rental.subcontracting.doctype.subcontractor_portal_access.subcontractor_portal_access.";
const ACT = (frm, method, label, args, group) => frm.add_custom_button(__(label), () => {
	const run = (extra) => frappe.call({ method: M + method, args: Object.assign({ name: frm.doc.name }, extra || {}), freeze: true, callback: () => frm.reload_doc() });
	if (args) frappe.prompt(args, run, __(label));
	else run();
}, group ? __(group) : null);
const REMARK = (name, label, reqd) => [{ fieldname: name, label: __(label), fieldtype: "Small Text", reqd: reqd ? 1 : 0 }];
frappe.ui.form.on("Subcontractor Portal Access", {
	setup(frm) { frm.set_query("supplier", () => ({ filters: { is_subcontractor: 1 } })); },
	refresh(frm) {
		if (!frm.is_new() && frm.doc.enabled) ACT(frm, "invite", frm.doc.invited_on ? "Send Invitation Again" : "Send Invitation");
	},
});
