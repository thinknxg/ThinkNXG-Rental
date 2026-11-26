frappe.ui.form.on("Subcontract Material Allocation", {
	setup(frm) { frm.set_query("subcontract_work_order", () => ({ filters: { docstatus: 1, status: ["in", ["Approved", "Work In Progress", "Partially Completed", "Completed"]] } })); },
});
