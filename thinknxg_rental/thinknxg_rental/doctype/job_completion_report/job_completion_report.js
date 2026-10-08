const JCR_HOC = "thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract.";

frappe.ui.form.on("Job Completion Report", {
    setup(frm) {
        frm.set_query("hire_order_contract", () => ({ filters: { docstatus: 1 } }));
        frm.set_query("rental_contract", () => ({ filters: { contract_type: "Job Type Contract", docstatus: 1 } }));
    },

    onload(frm) {
        if (frm.doc.docstatus === 0) frm.trigger("load_job_lines");
    },

    async hire_order_contract(frm) {
        if (frm.doc.docstatus !== 0 || frm._jcr_syncing) return;
        // A different Hire Order Contract was picked: start from its own lines.
        frm.clear_table("job_lines");
        frm.refresh_field("job_lines");
        await frm.trigger("load_job_lines");
    },

    async rental_contract(frm) {
        if (frm.doc.docstatus !== 0 || frm._jcr_syncing || !frm.doc.rental_contract) return;

        const r = await frappe.db.get_value(
            "Rental Contract",
            frm.doc.rental_contract,
            ["source_type", "source_document"]
        );
        const v = r.message || {};
        if (v.source_type !== "Hire Order Contract" || !v.source_document) {
            frappe.msgprint(__("The selected Rental Contract is not linked to a Hire Order Contract."));
            return;
        }

        if (frm.doc.hire_order_contract !== v.source_document) {
            frm._jcr_syncing = true;
            try {
                frm.clear_table("job_lines");
                await frm.set_value("hire_order_contract", v.source_document);
            } finally {
                frm._jcr_syncing = false;
            }
        }
        await frm.trigger("load_job_lines");
    },

    async load_job_lines(frm) {
        if (frm.doc.docstatus !== 0 || !frm.doc.hire_order_contract) return;

        const r = await frappe.call({
            method: JCR_HOC + "get_job_lines",
            args: { hire_order_contract: frm.doc.hire_order_contract }
        });
        const m = r.message || {};
        const lines = m.lines || [];
        const has_rows = (frm.doc.job_lines || []).some(row => row.job_type);

        if (!has_rows) {
            frm.clear_table("job_lines");
            lines.forEach((l) => {
                const row = frm.add_child("job_lines");
                row.contract_item = l.name;
                row.job_type = l.job_type;
                row.job_type_name = l.job_type_name;
                row.location = l.location;
                row.job_qty = l.remaining;
                row.included_days = l.included_days;
                row.contract_rate = l.contract_rate;
                row.contract_charge_billing = m.contract_charge_billing;
                row.excess_rate_basis = l.excess_rate_basis;
                row.excess_rate = l.excess_rate;
                row.status = "Draft";
                // Dates stay blank so the user enters the real dates per job.
                row.erection_date = null;
                row.contract_end_date = null;
                row.dismantle_date = null;
            });
            frm.refresh_field("job_lines");
        }

        // Keep Rental Contract, company, customer and site in line with the Hire Order Contract.
        frm._jcr_syncing = true;
        try {
            if (m.rental_contract) {
                let current_source = null;
                if (frm.doc.rental_contract) {
                    const c = await frappe.db.get_value("Rental Contract", frm.doc.rental_contract, "source_document");
                    current_source = (c.message || {}).source_document;
                }
                if (current_source !== frm.doc.hire_order_contract) {
                    await frm.set_value("rental_contract", m.rental_contract);
                }
            }
            if (frm.doc.rental_contract) {
                const c = await frappe.db.get_value("Rental Contract", frm.doc.rental_contract, ["company", "customer", "rental_site"]);
                const v = c.message || {};
                for (const f of ["company", "customer", "rental_site"]) {
                    if (v[f] && frm.doc[f] !== v[f]) await frm.set_value(f, v[f]);
                }
            } else if (m.company && !frm.doc.company) {
                await frm.set_value("company", m.company);
            }
        } finally {
            frm._jcr_syncing = false;
        }
    },

    refresh(frm) {
        if (frm.doc.docstatus !== 1) return;
        const active = (frm.doc.job_lines || []).filter(r => !r.dismantle_date && r.status !== "Completed");
        if (active.length) {
            frm.add_custom_button(__("Record Dismantle"), () => {
                const opts = active.map(r => ({
                    label: `${r.job_type_name || r.job_type}${r.location ? " - " + r.location : ""} (${r.job_qty})`,
                    value: r.name
                }));
                frappe.prompt([
                    { fieldname: "line_name", fieldtype: "Select", label: __("JCR Job Line"), options: opts.map(x => x.value).join("\n"), reqd: 1 },
                    { fieldname: "dismantle_date", fieldtype: "Date", label: __("Dismantle Date"), reqd: 1, default: frappe.datetime.get_today() },
                    { fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") }
                ], v => frm.call("record_dismantle", v).then(() => frm.reload_doc()), __("Record Dismantle"), __("Stop the Clock"));
            }).addClass("btn-primary");
        }
        if (frm.doc.status !== "Completed") {
            frm.add_custom_button(__("Generate Billing"), () => frappe.call({
                method: "thinknxg_rental.services.jcr_billing.generate_jcr_billing",
                args: { jcr: frm.doc.name }, freeze: true
            }).then(r => {
                frappe.msgprint((r.message || []).length ? __("Billing periods processed: {0}", [r.message.join(", ")]) : __("No billing period is due yet."));
                frm.reload_doc();
            }));
        }
        frm.add_custom_button(__("Billing Schedule"), () => frappe.set_route("List", "JCR Billing Schedule", { jcr: frm.doc.name }));
        if (frm.doc.status !== "Completed") {
            const make_invoice = (jcrs) => frappe.call({
                method: "thinknxg_rental.services.jcr_billing.make_combined_invoice",
                args: { jcrs: JSON.stringify(jcrs) }, freeze: true, freeze_message: __("Creating Sales Invoice...")
            }).then(r => {
                if (r.message) frappe.set_route("Form", "Sales Invoice", r.message);
            });
            frm.add_custom_button(__("Sales Invoice"), () => make_invoice([frm.doc.name]), __("Create"));
            frm.add_custom_button(__("Multiple JCRs"), () => {
                frappe.call({
                    method: "thinknxg_rental.services.jcr_billing.get_combinable_jcrs",
                    args: { jcr: frm.doc.name }
                }).then(r => {
                    const others = r.message || [];
                    if (!others.length) {
                        frappe.msgprint(__("There is no other open JCR for {0}.", [frm.doc.customer]));
                        return;
                    }
                    const d = new frappe.ui.Dialog({
                        title: __("Invoice Multiple JCRs"),
                        fields: [
                            { fieldtype: "HTML", fieldname: "info", options: `<p class="text-muted">${__("{0} is always included. Tick the JCRs to put on the same invoice.", [frm.doc.name])}</p>` },
                            {
                                fieldtype: "MultiCheck", fieldname: "jcrs", label: __("JCRs of {0}", [frm.doc.customer_name || frm.doc.customer]),
                                columns: 1,
                                options: others.map(o => ({
                                    label: `${o.name} (${o.rental_contract || o.hire_order_contract || ""}${o.pending_periods ? ", " + __("{0} pending", [o.pending_periods]) : ""})`,
                                    value: o.name, checked: 0
                                }))
                            }
                        ],
                        primary_action_label: __("Create Invoice"),
                        primary_action(values) {
                            d.hide();
                            make_invoice([frm.doc.name].concat(values.jcrs || []));
                        }
                    });
                    d.show();
                });
            }, __("Create"));
        }
    }
});

frappe.ui.form.on("Job Completion Report Line", {
    erection_date(frm, cdt, cdn) {
        const r=locals[cdt][cdn];
        if (r.erection_date && r.included_days) frappe.model.set_value(cdt,cdn,"contract_end_date",frappe.datetime.add_days(r.erection_date,Math.max(cint(r.included_days),1)-1));
    },
    job_qty(frm,cdt,cdn) { if (frm.doc.docstatus===0) frm.dirty(); }
});
