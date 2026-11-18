frappe.query_reports["Excess Material Register"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project" },
		{ fieldname: "rental_contract", label: __("Contract"), fieldtype: "Link", options: "Rental Contract" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
		{ fieldname: "excess_category", label: __("Excess Category"), fieldtype: "Select", options: "\nExcess from Delivered Items\nAdditional Undelivered Items" },
		{ fieldname: "status", label: __("Status"), fieldtype: "Select", options: "\nAvailable\nPartly Returned\nPartly Adjusted\nPartly Settled\nClosed\nCancelled" },
		{ fieldname: "open_only", label: __("Only With Excess Available"), fieldtype: "Check" },
	],
};
