frappe.query_reports["Subcontract Labour Cost"] = {
	filters: [
		{"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company"},
		{"fieldname": "supplier", "label": "Subcontractor", "fieldtype": "Link", "options": "Supplier"},
		{"fieldname": "hire_order_contract", "label": "Hire Order Contract", "fieldtype": "Link", "options": "Hire Order Contract"},
		{"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "\nApproved\nWork In Progress\nPartially Completed\nCompleted\nPending Final Verification\nVerified\nClosed"},
		{"fieldname": "from_date", "label": "From Date", "fieldtype": "Date"},
		{"fieldname": "to_date", "label": "To Date", "fieldtype": "Date"},
	],
};
