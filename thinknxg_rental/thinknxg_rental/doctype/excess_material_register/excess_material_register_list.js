frappe.listview_settings["Excess Material Register"] = {
	add_fields: ["status", "available_qty"],
	get_indicator(doc) {
		const colors = { Available: "orange", "Partly Returned": "yellow", "Partly Adjusted": "yellow", "Partly Settled": "yellow", Closed: "green", Cancelled: "red" };
		return [__(doc.status), colors[doc.status] || "gray", "status,=," + doc.status];
	},
};
