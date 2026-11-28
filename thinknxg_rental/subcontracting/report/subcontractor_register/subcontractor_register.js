frappe.query_reports["Subcontractor Register"] = {
	filters: [
		{"fieldname": "supplier", "label": "Subcontractor", "fieldtype": "Link", "options": "Supplier"},
		{"fieldname": "status", "label": "Approval", "fieldtype": "Select", "options": "\nPending\nApproved\nSuspended\nBlacklisted"},
	],
};
