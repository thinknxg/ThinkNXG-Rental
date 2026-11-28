// Supplier form, subcontractor part: approval status changes only through Approve / Suspend (role-checked on the server).
frappe.ui.form.on("Supplier", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.is_subcontractor) return;
		frm.set_df_property("subcontractor_approval_status", "read_only", 1);
		const M = "thinknxg_rental.services.subcontracting.approve_subcontractor";
		const set = (status, label) => frm.add_custom_button(__(label), () => frappe.prompt({ fieldname: "remarks", label: __("Remarks"), fieldtype: "Small Text" },
			(v) => frappe.call({ method: M, args: { supplier: frm.doc.name, status, remarks: v.remarks }, freeze: true, callback: () => frm.reload_doc() }), __(label)), __("Subcontractor"));
		if (frm.doc.subcontractor_approval_status !== "Approved") set("Approved", "Approve");
		if (frm.doc.subcontractor_approval_status === "Approved") set("Suspended", "Suspend");
		if (frm.doc.subcontractor_approval_status !== "Blacklisted") set("Blacklisted", "Blacklist");
		frm.add_custom_button(__("Subcontractor 360"), () => window.open("/rental/admin/subcontracting/subcontractors/" + encodeURIComponent(frm.doc.name)), __("Subcontractor"));
		frm.add_custom_button(__("Portal Access"), () => frappe.new_doc("Subcontractor Portal Access", { supplier: frm.doc.name }), __("Subcontractor"));
	},
});
