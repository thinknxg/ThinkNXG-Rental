frappe.ui.form.on("Job Completion Report", {
	setup(frm) {
		frm.set_query("hire_order_contract", () => ({ filters: { docstatus: 1 } }));
	},
	hire_order_contract(frm) {
		if (frm.doc.docstatus === 0) frm.set_value({ job_type: null, location: null, contract_item: null, items: [] });
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.items?.length) {
			frm.set_intro(
				__("This JCR contains all open job lines from the Hire Order Contract. Set the erection date separately for each row; dismantle dates can also be different."),
				"blue"
			);
		}
		if (frm.doc.docstatus !== 1) return;

		if (frm.doc.items?.length) {
			const open = (frm.doc.items || []).filter((r) => !r.dismantle_date);
			if (open.length) {
				frm.add_custom_button(__("Record Item Dismantle"), () => {
					const options = open.map((r) => `${r.name}: ${r.job_type_name || r.job_type}${r.location ? " - " + r.location : ""}`).join("\n");
					frappe.prompt(
						[
							{ fieldname: "row", fieldtype: "Select", label: __("Job Item"), reqd: 1, options },
							{ fieldname: "dismantle_date", fieldtype: "Date", label: __("Dismantle Date"), reqd: 1, default: frappe.datetime.get_today() },
							{ fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") },
						],
						(values) => {
							const row = open.find((r) => r.name === values.row.split(":")[0]);
							if (!row) return;
							frm.call("record_item_dismantle", { contract_item: row.contract_item, dismantle_date: values.dismantle_date, remarks: values.remarks })
								.then(() => frm.reload_doc());
						},
						__("Record Dismantle"),
						__("Save")
					);
				});
			}
		}

		frm.add_custom_button(__("Generate Billing"), () =>
			frappe.call({
				method: "thinknxg_rental.services.jcr_billing.generate_jcr_billing",
				args: { jcr: frm.doc.name }, freeze: true,
				callback(r) {
					const made = r.message || [];
					frappe.msgprint(made.length ? __("Billing periods processed: {0}", [made.join(", ")]) : __("No billing period is due yet."));
					frm.reload_doc();
				},
			})
		);
		frm.add_custom_button(__("Billing Schedule"), () => frappe.set_route("List", "JCR Billing Schedule", { jcr: frm.doc.name }));
		frm.add_custom_button(__("Hire Order Contract"), () => frappe.set_route("Form", "Hire Order Contract", frm.doc.hire_order_contract), __("View"));
		frm.add_custom_button(__("Rental Contract"), () => frappe.set_route("Form", "Rental Contract", frm.doc.rental_contract), __("View"));
	},
});
