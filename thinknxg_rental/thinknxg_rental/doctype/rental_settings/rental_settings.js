frappe.ui.form.on("Rental Settings", {
	setup(frm) {
		["rental_yard_warehouse", "cross_hire_yard_warehouse", "inspection_warehouse", "repair_warehouse", "scrap_warehouse"].forEach((f) =>
			frm.set_query(f, () => ({ filters: { is_group: 0, company: frm.doc.company } }))
		);
		frm.set_query("customer_sites_warehouse", () => ({ filters: { is_group: 1, company: frm.doc.company } }));
		["rental_charge_item", "cross_hire_charge_item", "damage_recovery_item", "loss_recovery_item"].forEach((f) =>
			frm.set_query(f, () => ({ filters: { is_stock_item: 0, disabled: 0 } }))
		);
	},
	refresh(frm) {
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
