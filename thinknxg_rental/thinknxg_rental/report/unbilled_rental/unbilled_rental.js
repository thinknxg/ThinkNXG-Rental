frappe.query_reports["Unbilled Rental"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "upto_date", label: __("Accrue Up To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "show_zero", label: __("Show Contracts with Nothing Unbilled"), fieldtype: "Check" },
	],
};
