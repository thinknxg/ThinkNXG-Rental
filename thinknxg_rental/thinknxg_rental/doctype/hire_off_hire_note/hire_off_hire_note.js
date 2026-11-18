frappe.ui.form.on("Hire Off-Hire Note", {
	setup(frm) {
		frm.set_query("rental_contract", () => ({ filters: { docstatus: 1, status: ["in", ["On Hire", "Active"]] } }));
		// own material: an own rental warehouse or the inspection warehouse; cross hire: a cross hire warehouse
		Promise.all([thinknxg_rental.rental_warehouses(), frappe.db.get_single_value("Rental Settings", "inspection_warehouse")]).then(([list, inspection]) => {
			const of = (kind) => list.filter((w) => w.category === kind).map((w) => w.warehouse);
			frm.set_query("target_warehouse", "items", (doc, cdt, cdn) => {
				const cross = locals[cdt][cdn].ownership === "Cross Hire";
				return { filters: { name: ["in", cross ? of("Cross Hire") : of("Own").concat(inspection ? [inspection] : [])], company: frm.doc.company } };
			});
			frm.set_query("return_to_warehouse", "items", () => ({ filters: { name: ["in", of("Own")], company: frm.doc.company } }));
			frm.set_query("delivered_from", "items", () => ({ filters: { name: ["in", list.map((w) => w.warehouse)] } }));
		});
	},
	refresh(frm) {
		const base = "thinknxg_rental.thinknxg_rental.doctype.hire_off_hire_note.hire_off_hire_note.";
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Items at Site"), () => frm.trigger("get_items"));
		}
		if (frm.doc.docstatus !== 1) return;
		if (frm.doc.inspection_status === "Pending") {
			frm.add_custom_button(__("Return Inspection"), () => frappe.model.open_mapped_doc({ method: base + "make_inspection", frm }), __("Create"));
		} else {
			frm.add_custom_button(__("Damage Settlement"), () => frappe.model.open_mapped_doc({ method: base + "make_damage_settlement", frm }), __("Create"));
		}
		// excess material: return it to the customer, or settle outstanding material against it
		const rental = "thinknxg_rental.thinknxg_rental.doctype.";
		if (flt(frm.doc.total_excess_qty) > 0 && !["Settled", "Cancelled"].includes(frm.doc.excess_status)) {
			frm.add_custom_button(__("Excess Material Return"), () => frappe.model.open_mapped_doc({
				method: rental + "excess_material_return_note.excess_material_return_note.make_from_off_hire", frm }), __("Create"));
		}
		frm.add_custom_button(__("Dismantling Entry"), () => frappe.model.open_mapped_doc({
			method: rental + "dismantling_entry.dismantling_entry.make_from_off_hire", frm }), __("Create"));
		if (flt(frm.doc.total_excess_qty) > 0 && !["Settled", "Cancelled"].includes(frm.doc.excess_status)) {
			frm.add_custom_button(__("Excess Material Abandonment"), () => frappe.model.open_mapped_doc({
				method: rental + "excess_material_abandonment.excess_material_abandonment.make_from_off_hire", frm }), __("Create"));
		}
		if (flt(frm.doc.total_excess_qty) > 0) {
			frm.add_custom_button(__("Excess Material Register"), () =>
				frappe.set_route("List", "Excess Material Register", { hire_off_hire_note: frm.doc.name }), __("View"));
			frm.add_custom_button(__("Adjustment History"), () => thinknxg_rental.excess_history({ hire_off_hire_note: frm.doc.name }), __("View"));
		}
		frm.page.set_inner_btn_group_as_primary(__("Create"));
	},
	rental_contract(frm) {
		if (!frm.doc.rental_contract) return;
		frappe.db.get_value("Rental Contract", frm.doc.rental_contract, "grace_days").then((r) => {
			frm.set_value("grace_days", (r.message && r.message.grace_days) || 0);
		});
		if (!(frm.doc.items || []).some((d) => d.item_code)) frm.trigger("get_items");
	},
	get_items(frm) {
		if (!frm.doc.rental_contract) return frappe.msgprint(__("Select a Rental Contract first"));
		frappe.call({
			method: "thinknxg_rental.thinknxg_rental.doctype.hire_off_hire_note.hire_off_hire_note.get_items_at_site",
			args: { rental_contract: frm.doc.rental_contract },
			callback(r) {
				frm.clear_table("items");
				(r.message || []).forEach((row) => frm.add_child("items", row));
				frm.refresh_field("items");
			},
		});
	},
});

// Received: everything that physically came back. The server splits it into Returned (up to what is at
// site) and Excess (the rest) when the note is saved; shown here as a preview for a single row.
frappe.ui.form.on("Hire Off-Hire Item", {
	received_qty(frm, cdt, cdn) {
		const d = locals[cdt][cdn];
		if (!flt(d.received_qty)) return;
		if (d.ownership === "Cross Hire") {
			frappe.model.set_value(cdt, cdn, { returned_qty: flt(d.received_qty), excess_qty: 0 });
			return;
		}
		const returned = Math.max(Math.min(flt(d.received_qty), flt(d.at_site_qty) - flt(d.lost_qty)), 0);
		frappe.model.set_value(cdt, cdn, { returned_qty: returned, excess_qty: flt(d.received_qty) - returned });
	},
});
