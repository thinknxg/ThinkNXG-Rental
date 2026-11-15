frappe.query_reports["Rental Inventory"] = {
	filters: [
		{ fieldname: "location", label: __("Location"), fieldtype: "Data" },
		{ fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "ownership", label: __("Ownership"), fieldtype: "Select", options: "\nOwn\nCross Hire" },
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{
			fieldname: "stock_status",
			label: __("Stock Status"),
			fieldtype: "Select",
			options: "\nAvailable\nReserved\nAt Site\nIn Custody\nUnder Inspection\nIn Repair\nScrap",
		},
	],
};
