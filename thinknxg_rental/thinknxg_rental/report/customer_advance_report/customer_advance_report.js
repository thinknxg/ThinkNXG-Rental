frappe.query_reports["Customer Advance Report"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "country", label: __("Country"), fieldtype: "Select", options: ["", "Oman", "United Arab Emirates"] },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "rental_contract", label: __("Rental Contract"), fieldtype: "Link", options: "Rental Contract" },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "status", label: __("Advance Status"), fieldtype: "Select", options: ["", "Not Received", "Partially Received", "Fully Received", "Partially Utilized", "Fully Utilized", "Partially Refunded"] },
	],
};
