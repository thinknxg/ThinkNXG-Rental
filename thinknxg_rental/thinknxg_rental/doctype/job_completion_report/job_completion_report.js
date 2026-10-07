frappe.ui.form.on("Job Completion Report", {
	setup(frm) {
		frm.set_query("hire_order_contract", () => ({ filters: { docstatus: 1 } }));
		frm.set_query("job_type", () => ({ filters: { name: ["in", frm.job_types && frm.job_types.length ? frm.job_types : [""]] } }));
	},
	onload(frm) {
		frm.trigger("load_job_types");
	},
	hire_order_contract(frm) {
		frm.trigger("load_job_types");
	},
	load_job_types(frm) {
		frm.job_types = [];
		if (!frm.doc.hire_order_contract) return;
		frappe.db.get_doc("Hire Order Contract", frm.doc.hire_order_contract).then((hoc) => {
			frm.job_types = [...new Set((hoc.items || []).map((d) => d.job_type))];
			if (frm.doc.docstatus === 0 && !frm.doc.job_type && frm.job_types.length === 1) frm.set_value("job_type", frm.job_types[0]);
		});
	},
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		if (!frm.doc.dismantle_date) {
			frm.add_custom_button(__("Record Dismantle"), () => {
				frappe.prompt(
					[
						{ fieldname: "dismantle_date", fieldtype: "Date", label: __("Dismantle Date"), reqd: 1, default: frappe.datetime.get_today() },
						{ fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") },
					],
					(values) => frm.call("record_dismantle", values).then(() => frm.reload_doc()),
					__("Record Dismantle"),
					__("Stop the Clock")
				);
			}).addClass("btn-primary");
		}
		if (frm.doc.status !== "Completed") {
			frm.add_custom_button(__("Generate Billing"), () =>
				frappe.call({
					method: "thinknxg_rental.services.jcr_billing.generate_jcr_billing",
					args: { jcr: frm.doc.name },
					freeze: true,
					callback(r) {
						const made = r.message || [];
						frappe.msgprint(made.length ? __("Billing periods processed: {0}", [made.join(", ")]) : __("No billing period is due yet."));
						frm.reload_doc();
					},
				})
			);
		}
		frm.add_custom_button(__("Billing Schedule"), () => frappe.set_route("List", "JCR Billing Schedule", { jcr: frm.doc.name }));
	},
});
