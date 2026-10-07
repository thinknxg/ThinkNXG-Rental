frappe.query_reports["Cross Hire Position"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "rental_contract", label: __("Customer Contract"), fieldtype: "Link", options: "Rental Contract" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "include_closed", label: __("Include Fully Returned"), fieldtype: "Check" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "overdue_days" && data && data.overdue_days > 0) {
			value = `<span style="color: var(--red-500); font-weight: 600">${value}</span>`;
		}
		return value;
	},
};
