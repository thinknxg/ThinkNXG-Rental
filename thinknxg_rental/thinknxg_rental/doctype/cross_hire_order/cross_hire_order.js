frappe.ui.form.on("Cross Hire Order", {
	setup(frm) {
		frm.set_query("item_code", "items", () => ({ filters: { is_stock_item: 1, disabled: 0 } }));
		frm.set_query("rental_contract", () => ({ filters: { docstatus: 1, status: ["not in", ["Completed", "Cancelled"]] } }));
		frm.set_query("taxes_and_charges", () => ({ filters: { company: frm.doc.company } }));
	},
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || frm.doc.status === "Completed") return;
		const on_hire = (frm.doc.items || []).reduce((t, d) => t + flt(d.on_hire_qty), 0);
		const to_receive = (frm.doc.items || []).some((d) => flt(d.received_qty) < flt(d.qty));

		if (to_receive) {
			frm.add_custom_button(__("Cross Hire Receipt"), () =>
				frappe.call({
					method: "thinknxg_rental.services.cross_hire.make_cross_hire_receipt",
					args: { cross_hire_order: frm.doc.name },
					freeze: true,
					callback(r) {
						if (!r.message) return;
						const doc = frappe.model.sync(r.message)[0];
						frappe.set_route("Form", doc.doctype, doc.name);
					},
				}), __("Create"));
		}
		if (on_hire > 0) {
			frm.add_custom_button(__("Cross Hire Off-Hire Note"), () =>
				frappe.model.open_mapped_doc({
					method: "thinknxg_rental.thinknxg_rental.doctype.cross_hire_off_hire_note.cross_hire_off_hire_note.make_cross_hire_off_hire_note",
					frm,
				}), __("Create"));
		}
		if (frm.doc.status !== "To Receive") {
			frm.add_custom_button(__("Supplier Hire Invoice"), () => {
				frappe.prompt(
					[{ fieldname: "upto_date", fieldtype: "Date", label: __("Bill Up To"), reqd: 1, default: frappe.datetime.get_today() }],
					(values) =>
						frappe.call({
							method: "thinknxg_rental.services.cross_hire.make_supplier_invoice",
							args: { cross_hire_order: frm.doc.name, upto_date: values.upto_date },
							freeze: true,
							callback: (r) => r.message && frappe.set_route("Form", "Purchase Invoice", r.message),
						}),
					__("Supplier Hire Invoice")
				);
			}, __("Create"));
		}
		frm.page.set_inner_btn_group_as_primary(__("Create"));
		if (frm.doc.status === "Returned") {
			frm.add_custom_button(__("Complete Order"), () =>
				frappe.confirm(__("Mark this cross hire order Completed and close its Purchase Order?"), () =>
					frm.call("complete").then(() => frm.reload_doc())
				)
			);
		}
	},
});

frappe.ui.form.on("Cross Hire Order Item", {
	item_code(frm, cdt, cdn) {
		const d = locals[cdt][cdn];
		if (d.item_code && !d.rate_basis) frappe.model.set_value(cdt, cdn, "rate_basis", frm.doc.rate_basis);
	},
});
