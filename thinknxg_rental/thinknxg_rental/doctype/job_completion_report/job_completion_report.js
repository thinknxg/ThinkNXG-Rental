const JCR_HOC = "thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract.";

frappe.ui.form.on("Job Completion Report", {
	setup(frm) {
		frm.set_query("hire_order_contract", () => ({ filters: { docstatus: 1 } }));
		// only job types on the selected Hire Order Contract
		frm.set_query("job_type", () => ({
			filters: { name: ["in", frm.job_lines && frm.job_lines.length ? [...new Set(frm.job_lines.map((l) => l.job_type))] : [""]] },
		}));
	},
	onload(frm) {
		frm.trigger("load_job_lines");
	},
	hire_order_contract(frm) {
		if (frm.doc.docstatus === 0) frm.set_value({ job_type: null, location: null, contract_item: null });
		frm.trigger("load_job_lines");
	},
	load_job_lines(frm) {
		frm.job_lines = [];
		if (!frm.doc.hire_order_contract || frm.doc.docstatus !== 0) return;
		return frappe.call({ method: JCR_HOC + "get_job_lines", args: { hire_order_contract: frm.doc.hire_order_contract } }).then((r) => {
			const m = r.message || {};
			frm.job_lines = m.lines || [];
			frm.contract_charge_billing = m.contract_charge_billing;
			if (!frm.doc.company && m.company) frm.set_value("company", m.company);
			if (!frm.doc.job_type && frm.job_lines.length === 1) frm.set_value("job_type", frm.job_lines[0].job_type);
			frm.trigger("show_open_jobs");
		});
	},
	show_open_jobs(frm) {
		if (frm.doc.docstatus !== 0 || !frm.job_lines) return;
		if (!frm.job_lines.length) {
			frm.set_intro(__("Every job on this Hire Order Contract already has a Job Completion Report."), "orange");
		} else if (frm.job_lines.length > 1) {
			const list = frm.job_lines.map((l) => `${l.job_type_name || l.job_type}${l.location ? " - " + l.location : ""} (${l.remaining})`).join(", ");
			frm.set_intro(__("Jobs still to report on this contract: {0}. Raise one JCR for each, with its own erection date.", [list]), "blue");
		}
	},
	job_type(frm) {
		// show the chosen job's own terms straight away, not only after saving
		if (frm.doc.docstatus !== 0 || !frm.doc.job_type) return;
		const lines = (frm.job_lines || []).filter((l) => l.job_type === frm.doc.job_type);
		if (!lines.length) return;
		if (lines.some((l) => l.name === frm.doc.contract_item)) return; // already on a line of this job type
		const apply = (line) => frm.set_value({
			contract_item: line.name,
			location: line.location,
			job_qty: line.remaining,
			included_days: line.included_days,
			contract_rate: line.contract_rate,
			excess_rate_basis: line.excess_rate_basis,
			excess_rate: line.excess_rate,
			contract_charge_billing: frm.contract_charge_billing,
		}).then(() => frm.trigger("set_contract_end"));
		if (lines.length === 1) return apply(lines[0]);
		// the same job type at several locations: each is its own contract line
		const label = (l) => `${l.idx}: ${l.location || __("No location")} (${l.remaining} ${__("to report")})`;
		frappe.prompt(
			[{ fieldname: "line", fieldtype: "Select", label: __("Location"), reqd: 1, options: lines.map(label), default: label(lines[0]) }],
			(v) => apply(lines.find((l) => l.idx === parseInt(v.line, 10))),
			__("Which {0}?", [frm.doc.job_type]),
			__("Select")
		);
	},
	erection_date(frm) {
		frm.trigger("set_contract_end");
	},
	set_contract_end(frm) {
		if (frm.doc.docstatus !== 0 || !frm.doc.erection_date || !frm.doc.included_days) return;
		frm.set_value("contract_end_date", frappe.datetime.add_days(frm.doc.erection_date, Math.max(cint(frm.doc.included_days), 1) - 1));
	},
	refresh(frm) {
		frm.trigger("show_open_jobs");
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
