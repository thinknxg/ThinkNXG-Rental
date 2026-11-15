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
