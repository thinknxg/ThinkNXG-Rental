frappe.ui.form.on("Rental Material Reservation", {
	setup(frm) {
		frm.set_query("item_code", "items", () => ({ filters: { is_stock_item: 1, disabled: 0 } }));
		frm.set_query("source_warehouse", () => ({ filters: { is_group: 0, company: frm.doc.company } }));
		frm.set_query("rental_contract", () => ({ filters: { docstatus: 1, status: ["not in", ["Completed", "Cancelled"]] } }));
		frm.set_query("source_document", () => ({ filters: { docstatus: 1 } }));
	},
	source_type(frm) {
		frm.set_value("source_document", null);
	},
	source_document(frm) {
		// Hire Order: its stock items. Hire Order Contract: job types exploded into physical rental items.
		if (!frm.doc.source_type || !frm.doc.source_document || frm.doc.docstatus !== 0) return;
		frappe.call({
			method: "thinknxg_rental.thinknxg_rental.doctype.rental_material_reservation.rental_material_reservation.get_source_items",
			args: { source_type: frm.doc.source_type, source_document: frm.doc.source_document },
			callback(r) {
				if (!r.message) return;
				const m = r.message;
				frm.set_value({ customer: m.customer, company: m.company, rental_site: m.rental_site, rental_contract: m.rental_contract, required_from: m.required_from });
				frm.clear_table("items");
				m.items.forEach((row) => frm.add_child("items", row));
				frm.refresh_field("items");
			},
		});
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0 && !frm.is_new()) {
			frm.set_intro(__("Reserved and shortfall quantities are recalculated from live yard stock every time you save and again on submit."));
		}
		if (frm.doc.docstatus !== 1) return;
		if (["Reserved", "Partially Reserved"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Release Reservation"), () =>
				frappe.confirm(__("Release the undispatched balance back to available stock?"), () =>
					frm.call("release").then(() => frm.reload_doc())
				)
			);
		}
		if (frm.doc.total_shortfall_qty > 0 && frm.doc.status !== "Released") {
			frm.add_custom_button(__("Cross Hire Order for Shortfall"), () =>
				frappe.model.open_mapped_doc({
					method: "thinknxg_rental.thinknxg_rental.doctype.rental_material_reservation.rental_material_reservation.make_cross_hire_order",
					frm,
				})
			).addClass("btn-primary");
		}
	},
});
