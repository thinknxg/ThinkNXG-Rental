frappe.query_reports["Rental Stock Position"] = {
	filters: [
		{ fieldname: "category", label: __("Category"), fieldtype: "Select", options: "\nFormwork\nScaffolding\nShoring / Props\nAccessories\nOther" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
	],
};
