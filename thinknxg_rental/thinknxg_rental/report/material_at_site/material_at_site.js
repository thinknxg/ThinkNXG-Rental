frappe.query_reports["Material at Site"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "as_on_date", label: __("As On Date"), fieldtype: "Date" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "rental_site", label: __("Site"), fieldtype: "Link", options: "Rental Site" },
		{ fieldname: "rental_contract", label: __("Contract"), fieldtype: "Link", options: "Rental Contract" },
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "ownership", label: __("Ownership"), fieldtype: "Select", options: "\nOwn\nCross Hire" },
		{ fieldname: "supplier", label: __("Cross Hire Supplier"), fieldtype: "Link", options: "Supplier" },
	],
};
