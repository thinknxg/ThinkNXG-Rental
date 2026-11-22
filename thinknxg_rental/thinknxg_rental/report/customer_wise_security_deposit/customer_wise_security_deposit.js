frappe.query_reports["Customer-wise Security Deposit"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company" },
		{ fieldname: "country", label: __("Country"), fieldtype: "Select", options: ["", "Oman", "United Arab Emirates"] },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "rental_contract", label: __("Rental Contract"), fieldtype: "Link", options: "Rental Contract" },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "status", label: __("Deposit Status"), fieldtype: "Select", options: ["", "Not Collected", "Partially Collected", "Fully Collected", "Partially Refunded", "Settled"] },
	],
};
