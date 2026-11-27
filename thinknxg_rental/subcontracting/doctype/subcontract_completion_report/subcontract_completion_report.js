frappe.ui.form.on("Subcontract Completion Report", {
	setup(frm) { frm.set_query("subcontract_work_order", () => ({ filters: { docstatus: 1, status: "Completed" } })); },
});
