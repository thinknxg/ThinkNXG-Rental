frappe.query_reports["Damage and Loss Register"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -3) },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "hire_contract", label: __("Contract"), fieldtype: "Link", options: "Hire Order Contract" },
		{ fieldname: "classification", label: __("Classification"), fieldtype: "Select", options: "\nRepairable\nBeyond Repair\nLost" },
	],
};
