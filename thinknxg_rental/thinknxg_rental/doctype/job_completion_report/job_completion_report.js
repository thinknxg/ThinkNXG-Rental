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
                row.nxg_duration = l.nxg_duration;
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
                    label: `${r.idx}. ${r.job_type_name || r.job_type}${r.location ? " - " + r.location : ""} (${r.job_qty}${nxg_returned(frm, r) ? ", " + __("{0} returned", [nxg_returned(frm, r)]) : ""})`,
                    value: r.name
                }));
                frappe.prompt([
                    { fieldname: "line_name", fieldtype: "Select", label: __("JCR Job Line"), options: opts, default: opts.length === 1 ? opts[0].value : undefined, reqd: 1 },
                    { fieldname: "dismantle_date", fieldtype: "Date", label: __("Dismantle Date"), reqd: 1, default: frappe.datetime.get_today() },
                    { fieldname: "return_qty", fieldtype: "Float", label: __("Qty Returned"), description: __("Leave blank when everything still outstanding is returned") },
                    { fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") }
                ], v => frm.call("record_dismantle", v).then(() => frm.reload_doc()), __("Record Dismantle"), __("Stop the Clock"));
            }).addClass("btn-primary");
        }
        if (frm.doc.status !== "Completed") {
            frm.add_custom_button(__("Generate Billing"), () => frappe.call({
                method: "thinknxg_rental.services.jcr_billing.generate_jcr_billing",
                args: { jcr: frm.doc.name, on_demand: 1 }, freeze: true
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

let nxg_syncing = false;

frappe.ui.form.on("Job Completion Report Line", {
    erection_date(frm, cdt, cdn) {
        const r=locals[cdt][cdn];
        if (r.erection_date && r.included_days) frappe.model.set_value(cdt,cdn,"contract_end_date",frappe.datetime.add_days(r.erection_date,Math.max(cint(r.included_days),1)-1));
    },
    job_qty(frm,cdt,cdn) {
        if (frm.doc.docstatus!==0) return;
        const row = locals[cdt][cdn];
        if (!nxg_syncing && flt(row.nxg_rotations_done)) frappe.model.set_value(cdt, cdn, "nxg_rotations_done", 0);
        frm.dirty();
    },
    nxg_rotations_done(frm,cdt,cdn) {
        if (frm.doc.docstatus!==0) return;
        const row = locals[cdt][cdn];
        if (!row.contract_item || !flt(row.nxg_rotations_done)) return;
        frappe.call({
            method: "frappe.client.get_value",
            args: { doctype: "Hire Order Contract Item", filters: { name: row.contract_item }, fieldname: "qty", parent: "Hire Order Contract" },
            callback: (r) => {
                const n = flt(r.message && r.message.qty);
                if (!n) return;
                nxg_syncing = true;
                frappe.model.set_value(cdt, cdn, "job_qty", n * flt(row.nxg_rotations_done)).then(() => { nxg_syncing = false; });
            }
        });
    }
});

// Description is a new grid column. Frappe keeps each user's own column choice and it overrides the
// doctype defaults, so users who saved their columns earlier would not see it. Add it once, next to
// the job name; after that the user can still remove or move it.
frappe.ui.form.on("Job Completion Report", {
    onload(frm) {
        try {
            const KEY = "NxgGridDefaults";
            const done = frappe.get_user_settings("Job Completion Report", KEY) || {};
            if (done.job_lines_description) return;
            const mark = { job_lines_description: 1 };
            const grid = frappe.get_user_settings("Job Completion Report", "GridView") || {};
            const saved = grid["Job Completion Report Line"] || [];
            if (!saved.length || saved.some((c) => c.fieldname === "description")) {
                frappe.model.user_settings.save("Job Completion Report", KEY, mark); // doctype defaults already include it
                return;
            }
            const columns = saved.slice();
            let at = columns.findIndex((c) => c.fieldname === "job_type_name") + 1;
            if (!at) at = columns.findIndex((c) => c.fieldname === "job_type") + 1;
            if (!at) at = columns.length;
            columns.splice(at, 0, { fieldname: "description", columns: 2 });
            frappe.model.user_settings.save("Job Completion Report", "GridView", { "Job Completion Report Line": columns })
                .then(() => frappe.model.user_settings.save("Job Completion Report", KEY, mark))
                .then(() => location.reload());
        } catch (e) {
            console.warn("JCR grid defaults not applied", e);
        }
    },
});

function nxg_returned(frm, row) {
    return (frm.doc.jcr_returns || []).filter((x) => x.jcr_line === row.name).reduce((a, x) => a + flt(x.return_qty), 0);
}


// ---- Balance Qty / Balance Rotation beside the entered values (draft JCRs) ----
function nxg_update_balance(frm, cdt, cdn) {
    const row = locals[cdt] && locals[cdt][cdn];
    if (!row || frm.doc.docstatus !== 0 || !row.contract_item || !frm.doc.hire_order_contract) return;
    frappe.call({
        method: "thinknxg_rental.thinknxg_rental.doctype.job_completion_report.job_completion_report.get_line_balance",
        args: {
            hire_order_contract: frm.doc.hire_order_contract,
            contract_item: row.contract_item,
            job_qty: flt(row.job_qty),
            exclude: frm.doc.name,
        },
        callback: (r) => {
            const m = r.message || {};
            if (flt(row.nxg_balance_qty) !== flt(m.balance_qty)) frappe.model.set_value(cdt, cdn, "nxg_balance_qty", flt(m.balance_qty));
            if (flt(row.nxg_balance_rotation) !== flt(m.balance_rotation)) frappe.model.set_value(cdt, cdn, "nxg_balance_rotation", flt(m.balance_rotation));
        },
    });
}

frappe.ui.form.on("Job Completion Report", {
    refresh(frm) {
        if (frm.doc.docstatus !== 0) return;
        (frm.doc.job_lines || []).forEach((r) => nxg_update_balance(frm, r.doctype, r.name));
    },
});

frappe.ui.form.on("Job Completion Report Line", {
    job_qty(frm, cdt, cdn) { nxg_update_balance(frm, cdt, cdn); },
    contract_item(frm, cdt, cdn) { nxg_update_balance(frm, cdt, cdn); },
});
