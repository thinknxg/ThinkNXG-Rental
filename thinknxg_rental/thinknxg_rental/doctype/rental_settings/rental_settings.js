frappe.ui.form.on("Rental Settings", {
	setup(frm) {
		["rental_yard_warehouse", "cross_hire_yard_warehouse", "inspection_warehouse", "repair_warehouse", "scrap_warehouse"].forEach((f) =>
			frm.set_query(f, () => ({ filters: { is_group: 0, company: frm.doc.company } }))
		);
		// own rental and cross hire warehouses: leaf warehouses of the company, any location
		["own_rental_warehouses", "cross_hire_warehouses"].forEach((table) =>
			frm.set_query("warehouse", table, () => ({ filters: { is_group: 0, company: frm.doc.company } }))
		);
		frm.set_query("customer_sites_warehouse", () => ({ filters: { is_group: 1, company: frm.doc.company } }));
		["rental_charge_item", "cross_hire_charge_item", "damage_recovery_item", "loss_recovery_item"].forEach((f) =>
			frm.set_query(f, () => ({ filters: { is_stock_item: 0, disabled: 0 } }))
		);
	},
	refresh(frm) {
		frm.set_intro(
			__("Own Rental Warehouses and Cross Hire Warehouses can be at any location. Each table has one default; inactive warehouses keep their stock and history but are not offered on new transactions."),
			"blue"
		);
		frm.add_custom_button(__("Create Default Warehouses and Items"), () => {
			if (!frm.doc.company) return frappe.msgprint(__("Select the Default Company first"));
			frappe.call({
				method: "thinknxg_rental.services.setup.setup_company",
				args: { company: frm.doc.company },
				freeze: true,
				callback: () => frm.reload_doc(),
			});
		});
	},
});

// one default per table: ticking a row's default clears the others
frappe.ui.form.on("Rental Warehouse", {
	is_default(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.is_default) return;
		(frm.doc[row.parentfield] || []).forEach((d) => {
			if (d.name !== row.name && d.is_default) frappe.model.set_value(d.doctype, d.name, "is_default", 0);
		});
		if (!row.is_active) frappe.model.set_value(cdt, cdn, "is_active", 1);
	},
});
