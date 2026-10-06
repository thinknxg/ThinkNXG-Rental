frappe.ui.form.on("Hire Order Contract", {
	setup(frm) {
		frm.set_query("item_code", "items", () => ({ filters: { is_stock_item: 1, disabled: 0 } }));
		frm.set_query("rental_site", () => ({ filters: { customer: frm.doc.customer, disabled: 0 } }));
		frm.set_query("hire_order", () => ({ filters: { docstatus: 1, status: "Open" } }));
		frm.set_query("taxes_and_charges", () => ({ filters: { company: frm.doc.company } }));
		frm.set_query("cost_center", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
	},
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		const base = "thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract.";
		const live = !["Completed", "Cancelled"].includes(frm.doc.status);
		const create = (label, method) =>
			frm.add_custom_button(__(label), () => frappe.model.open_mapped_doc({ method: base + method, frm }), __("Create"));

		if (live) {
			create("Material Reservation", "make_reservation");
			create("Delivery Order", "make_delivery_order");
			if (frm.doc.total_at_site_qty > 0) create("Off-Hire Note", "make_off_hire_note");
			create("Cross Hire Order", "make_cross_hire_order");
			frm.page.set_inner_btn_group_as_primary(__("Create"));

			frm.add_custom_button(__("Extend Contract"), () => {
				frappe.prompt(
					[
						{ fieldname: "new_end_date", fieldtype: "Date", label: __("New End Date"), reqd: 1 },
						{ fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") },
					],
					(values) => frm.call("extend", values).then(() => frm.reload_doc()),
					__("Extend Contract")
				);
			}, __("Actions"));

			if (frm.doc.billing_start_date) {
				frm.add_custom_button(__("Generate Billing"), () => {
					frappe.prompt(
						[{
							fieldname: "upto_date", fieldtype: "Date", label: __("Bill Up To"), reqd: 1,
							default: frappe.datetime.add_days(frappe.datetime.get_today(), -1),
							description: __("Complete billing periods are created up to this date; the last one is cut off here."),
						}],
						(values) =>
							frappe.call({
								method: "thinknxg_rental.services.billing.generate_billing",
								args: { hire_contract: frm.doc.name, upto_date: values.upto_date },
								freeze: true,
								callback(r) {
									const made = r.message || [];
									frappe.msgprint(made.length ? __("Created billing schedules: {0}", [made.join(", ")]) : __("Nothing to bill up to that date."));
									frm.reload_doc();
								},
							}),
						__("Generate Rental Billing")
					);
				}, __("Actions"));
			}
			frm.add_custom_button(__("Close Contract"), () => {
				frappe.confirm(__("Raise the final rental bill and mark this contract Completed?"), () =>
					frm.call("close_contract").then(() => frm.reload_doc())
				);
			}, __("Actions"));
		}
		if (frm.doc.status === "Completed") {
			frm.add_custom_button(__("Reopen Contract"), () => frm.call("reopen_contract").then(() => frm.reload_doc()));
		}
		frm.add_custom_button(__("Material at Site"), () =>
			frappe.set_route("query-report", "Material at Site", { hire_contract: frm.doc.name })
		, __("View"));
	},
	hire_order(frm) {
		if (!frm.doc.hire_order || frm.doc.items?.some((d) => d.item_code)) return;
		frappe.model.open_mapped_doc({
			method: "thinknxg_rental.thinknxg_rental.doctype.hire_order.hire_order.make_contract",
			source_name: frm.doc.hire_order,
		});
	},
});

frappe.ui.form.on("Hire Contract Item", {
	item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item_code) return;
		frappe.call({
			method: "thinknxg_rental.services.utils.get_item_rental_details",
			args: { item_code: row.item_code, customer: frm.doc.customer, rate_basis: row.rate_basis, posting_date: frm.doc.contract_date },
			callback(r) {
				if (!r.message) return;
				const m = r.message;
				frappe.model.set_value(cdt, cdn, { item_name: m.item_name, uom: m.uom, rate_basis: m.rate_basis, rate: m.rate, replacement_value: m.replacement_value });
			},
		});
	},
});
