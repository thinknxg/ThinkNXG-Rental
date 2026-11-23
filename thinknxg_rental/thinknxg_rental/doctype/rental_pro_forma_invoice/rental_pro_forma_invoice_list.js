// The pro forma invoice's own status (not just Draft / Submitted) in the list and the form header.
frappe.listview_settings["Rental Pro Forma Invoice"] = {
	add_fields: ["status", "docstatus"],
	has_indicator_for_draft: 1,
	get_indicator(doc) {
		const colour = {
			Draft: "red", "Submitted for Approval": "orange", Approved: "blue", "Sent to Customer": "purple",
			"Customer Accepted": "cyan", "Advance Received": "green", "Converted to Sales Invoice": "gray", Expired: "gray", Cancelled: "red",
		}[doc.status] || "gray";
		return [__(doc.status || "Draft"), colour, "status,=," + (doc.status || "Draft")];
	},
};
