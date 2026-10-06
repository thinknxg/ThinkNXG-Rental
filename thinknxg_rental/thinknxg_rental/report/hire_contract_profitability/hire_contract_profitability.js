frappe.query_reports["Hire Contract Profitability"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "from_date", label: __("Invoices From"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("Invoices To"), fieldtype: "Date" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "status", label: __("Contract Status"), fieldtype: "Select", options: "\nActive\nOn Hire\nOff Hired\nCompleted" },
		{ fieldname: "show_zero", label: __("Show Contracts without Invoices"), fieldtype: "Check" },
	],
};
