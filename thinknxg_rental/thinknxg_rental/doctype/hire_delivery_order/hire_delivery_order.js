frappe.ui.form.on("Hire Delivery Order", {
	setup(frm) {
		frm.set_query("hire_contract", () => ({ filters: { docstatus: 1, status: ["not in", ["Completed", "Cancelled"]] } }));
		frm.set_query("source_warehouse", "items", () => ({ filters: { is_group: 0, company: frm.doc.company } }));
		frm.set_query("cross_hire_order", "items", () => ({ filters: { docstatus: 1, status: ["!=", "Completed"] } }));
		frm.set_query("batch_no", "items", (doc, cdt, cdn) => ({ filters: { item: locals[cdt][cdn].item_code } }));
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Items from Contract"), () => frm.trigger("get_items"));
		}
	},
	hire_contract(frm) {
		if (frm.doc.hire_contract && !(frm.doc.items || []).some((d) => d.item_code)) frm.trigger("get_items");
	},
	get_items(frm) {
		if (!frm.doc.hire_contract) return frappe.msgprint(__("Select a Hire Contract first"));
		frappe.call({
			method: "thinknxg_rental.thinknxg_rental.doctype.hire_delivery_order.hire_delivery_order.get_dispatch_items",
			args: { hire_contract: frm.doc.hire_contract },
			callback(r) {
				const rows = r.message || [];
				frm.clear_table("items");
				rows.forEach((row) => frm.add_child("items", row));
				frm.refresh_field("items");
				if (!rows.length) {
					frappe.msgprint(__("Nothing can be dispatched right now: the contract is fully delivered, or no free yard stock / received cross-hire material is available."));
				}
			},
		});
	},
});
