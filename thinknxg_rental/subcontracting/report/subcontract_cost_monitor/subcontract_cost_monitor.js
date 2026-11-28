frappe.query_reports["Subcontract Cost Monitor"] = {
	filters: [
		{"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company"},
		{"fieldname": "supplier", "label": "Subcontractor", "fieldtype": "Link", "options": "Supplier"},
		{"fieldname": "project", "label": "Project", "fieldtype": "Link", "options": "Project"},
		{"fieldname": "from_date", "label": "From Date", "fieldtype": "Date"},
		{"fieldname": "to_date", "label": "To Date", "fieldtype": "Date"},
	],
};
