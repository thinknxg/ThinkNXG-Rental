frappe.ui.form.on("Item", {
	setup(frm) {
		frm.set_query("item_code", "nxg_job_type_items", () => ({ filters: { is_stock_item: 1, disabled: 0 } }));
	},
	is_stock_item(frm) {
		if (frm.doc.is_stock_item && frm.doc.nxg_is_job_type_item) frm.set_value("nxg_is_job_type_item", 0);
	},
});
