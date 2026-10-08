frappe.ui.form.on("Hire Order Contract", {
	setup(frm) {
		frm.set_query("job_type", "items", () => ({ filters: { nxg_is_job_type_item: 1, is_stock_item: 0, disabled: 0 } }));
		frm.set_query("item_code", "materials", () => ({ filters: { is_stock_item: 1, disabled: 0 } }));
		frm.set_query("rental_site", () => ({ filters: { customer: frm.doc.customer, disabled: 0 } }));
		frm.set_query("taxes_and_charges", () => ({ filters: { company: frm.doc.company } }));
		frm.set_query("cost_center", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
	},
	make_jcr(frm) {
		// one JCR per job type (or per location / erection date); ask which when several are open
		const method = "thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract.";
		frappe.call({ method: method + "get_job_lines", args: { hire_order_contract: frm.doc.name } }).then((r) => {
			const lines = (r.message && r.message.lines) || [];
			if (!lines.length) return frappe.msgprint(__("Every job on this contract already has a Job Completion Report."));
			const open = (job_row) => frappe.model.open_mapped_doc({ method: method + "make_jcr", frm, args: { job_row } });
			if (lines.length === 1) return open(lines[0].idx);
			const label = (l) => `${l.idx}: ${l.job_type_name || l.job_type}${l.location ? " - " + l.location : ""} (${l.remaining} ${__("to report")})`;
			frappe.prompt(
				[{ fieldname: "line", fieldtype: "Select", label: __("Job Type"), reqd: 1, options: lines.map(label), default: label(lines[0]),
					description: __("Raise one Job Completion Report for each job type, with its own erection date.") }],
				(v) => open(parseInt(v.line, 10)),
				__("Which job was erected?"),
				__("Create JCR")
			);
		});
	},
	refresh(frm) {
		const base = "thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract.";
		if (frm.doc.docstatus === 0) {
			frm.set_intro(
				__("Physical Rental Items are filled from the job types when you first save. Edit them to match the actual job, or rebuild them after changing the jobs.")
			);
			if (!frm.is_new()) {
				frm.add_custom_button(__("Rebuild Materials from Job Types"), () =>
					frappe.confirm(__("Replace the Physical Rental Items table with a fresh explosion of the job types?"), () =>
						frm.call("refresh_materials").then(() => frm.reload_doc())
					)
				);
			}
			return;
		}
		if (frm.doc.docstatus !== 1) return;
		const create = (label, method) =>
			frm.add_custom_button(__(label), () => frappe.model.open_mapped_doc({ method: base + method, frm }), __("Create"));
		if (frm.doc.status === "Open") create("Rental Contract", "make_rental_contract");
		create("Material Reservation", "make_reservation");
		frm.add_custom_button(__("Job Completion Report (JCR)"), () => frm.trigger("make_jcr"), __("Create"));
		frm.page.set_inner_btn_group_as_primary(__("Create"));
	},
});

frappe.ui.form.on("Hire Order Contract Item", {
	qty: (frm, cdt, cdn) => set_contract_amount(cdt, cdn),
	contract_rate: (frm, cdt, cdn) => set_contract_amount(cdt, cdn),
});

function set_contract_amount(cdt, cdn) {
	const d = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "contract_amount", flt(d.qty) * flt(d.contract_rate));
}
