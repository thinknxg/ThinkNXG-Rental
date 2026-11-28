frappe.query_reports["Delayed Subcontract Work Orders"] = {
	filters: [
		{"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company"},
		{"fieldname": "supplier", "label": "Subcontractor", "fieldtype": "Link", "options": "Supplier"},
		{"fieldname": "project", "label": "Project", "fieldtype": "Link", "options": "Project"},
	],
};
