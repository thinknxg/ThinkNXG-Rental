frappe.query_reports["Rental Stock Position"] = {
	filters: [
		{ fieldname: "category", label: __("Category"), fieldtype: "Select", options: "\nFormwork\nScaffolding\nShoring / Props\nAccessories\nOther" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "location", label: __("Location"), fieldtype: "Data" },
		{ fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse" },
		{ fieldname: "group_by_warehouse", label: __("Group by Warehouse"), fieldtype: "Check" },
	],
};
