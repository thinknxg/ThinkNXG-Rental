frappe.query_reports["Customer-wise Excess Material"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project" },
		{ fieldname: "rental_contract", label: __("Contract"), fieldtype: "Link", options: "Rental Contract" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
	],
};
