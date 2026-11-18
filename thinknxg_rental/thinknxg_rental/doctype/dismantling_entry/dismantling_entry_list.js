frappe.listview_settings["Dismantling Entry"] = {
	get_indicator(doc) {
		return { Draft: [__("Draft"), "red", "docstatus,=,0"], Submitted: [__("Submitted"), "green", "docstatus,=,1"], Cancelled: [__("Cancelled"), "gray", "docstatus,=,2"] }[doc.status]
			|| [__(doc.status), "gray"];
	},
};
