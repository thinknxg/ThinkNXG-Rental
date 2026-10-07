frappe.ui.form.on("Hire Delivery Order", {
	setup(frm) {
		frm.set_query("rental_contract", () => ({ filters: { docstatus: 1, status: ["not in", ["Completed", "Cancelled"]] } }));
		frm.set_query("source_document", () => ({ filters: { docstatus: 1, status: "Contracted" } }));
		frm.set_query("rental_material_reservation", () => ({
			filters: { docstatus: 1, rental_contract: frm.doc.rental_contract, status: ["in", ["Reserved", "Partially Reserved"]] },
		}));
		frm.set_query("source_warehouse", "items", () => ({ filters: { is_group: 0, company: frm.doc.company } }));
		frm.set_query("cross_hire_order", "items", () => ({ filters: { docstatus: 1, status: ["!=", "Completed"] } }));
		frm.set_query("batch_no", "items", (doc, cdt, cdn) => ({ filters: { item: locals[cdt][cdn].item_code } }));
	},
	source_type(frm) {
		if (frm.doc.docstatus === 0 && !frm.doc.rental_contract) frm.set_value("source_document", null);
	},
	source_document(frm) {
		// start a delivery from the Hire Order or Hire Order Contract: find its Rental Contract and lines
		if (!frm.doc.source_type || !frm.doc.source_document || frm.doc.rental_contract || frm.doc.docstatus !== 0) return;
		frappe.call({
			method: "thinknxg_rental.thinknxg_rental.doctype.hire_delivery_order.hire_delivery_order.get_delivery_for_source",
			args: { source_type: frm.doc.source_type, source_document: frm.doc.source_document },
			callback(r) {
				if (!r.message) return;
				frm.doc.rental_contract = r.message.rental_contract;
				frm.refresh_field("rental_contract");
				frm.clear_table("items");
				r.message.items.forEach((row) => frm.add_child("items", row));
				frm.refresh_field("items");
			},
		});
	},
	rental_material_reservation(frm) {
		if (frm.doc.rental_contract && frm.doc.docstatus === 0) frm.trigger("get_items");
	},
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.source_type === "Hire Order Contract" && frm.doc.source_document) {
			frm.add_custom_button(__("Continue to JCR"), () => {
				frappe.call({
					method: "thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract.make_jcr",
					args: { source_name: frm.doc.source_document }, freeze: true,
					callback(r) {
						if (!r.message) return;
						const doc = frappe.model.sync(r.message)[0];
						frappe.set_route("Form", doc.doctype, doc.name);
					}
				});
			}, __("Continue Workflow"));
		}
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Items from Contract"), () => frm.trigger("get_items"));
		}
	},
	rental_contract(frm) {
		if (frm.doc.rental_contract && !(frm.doc.items || []).some((d) => d.item_code)) frm.trigger("get_items");
	},
	get_items(frm) {
		if (!frm.doc.rental_contract) return frappe.msgprint(__("Select a Rental Contract first"));
		frappe.call({
			method: "thinknxg_rental.thinknxg_rental.doctype.hire_delivery_order.hire_delivery_order.get_dispatch_items",
			args: { rental_contract: frm.doc.rental_contract, reservation: frm.doc.rental_material_reservation || null },
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
