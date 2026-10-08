const JCR_HOC = "thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract.";

frappe.ui.form.on("Job Completion Report", {
    setup(frm) {
        frm.set_query("hire_order_contract", () => ({ filters: { docstatus: 1 } }));
        frm.set_query("rental_contract", () => ({ filters: { contract_type: "Job Type Contract", docstatus: 1 } }));
    },

    onload(frm) {
        if (frm.doc.docstatus === 0) frm.trigger("load_job_lines");
    },

    hire_order_contract(frm) {
        if (frm.doc.docstatus === 0) frm.trigger("load_job_lines");
    },

    async rental_contract(frm) {
        if (frm.doc.docstatus !== 0 || !frm.doc.rental_contract) return;

        const r = await frappe.db.get_value(
            "Rental Contract",
            frm.doc.rental_contract,
            ["source_type", "source_document", "company", "customer", "rental_site"]
        );
        const v = r.message || {};

        if (v.source_type !== "Hire Order Contract" || !v.source_document) {
            frappe.msgprint(__("The selected Rental Contract is not linked to a Hire Order Contract."));
            return;
        }

        if (v.company && !frm.doc.company) await frm.set_value("company", v.company);
        if (v.customer && !frm.doc.customer) await frm.set_value("customer", v.customer);
        if (v.rental_site && !frm.doc.rental_site) await frm.set_value("rental_site", v.rental_site);

        // Do not depend on the asynchronous field event firing. Resolve the source
        // and populate the child table explicitly as soon as Rental Contract is selected.
        if (frm.doc.hire_order_contract !== v.source_document) {
            await frm.set_value("hire_order_contract", v.source_document);
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
        if (!lines.length && !(frm.doc.job_lines || []).some(r => r.job_type)) {
            frappe.msgprint(__("All job lines of {0} are already reported on a Job Completion Report.", [frm.doc.hire_order_contract]));
        }

        // A newly created JCR must always receive the complete set of open HOC
        // job lines in one child table. Existing rows are never overwritten.
        if (!(frm.doc.job_lines || []).some(r => r.job_type)) {
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
                // Keep the dates independent for every JCR row. They are intentionally
                // left blank so the user can enter the actual erection date per job.
                row.erection_date = null;
                row.contract_end_date = null;
                row.dismantle_date = null;
            });
            frm.refresh_field("job_lines");
        }

        if (!frm.doc.company && m.company) await frm.set_value("company", m.company);
        if (!frm.doc.rental_contract && m.rental_contract) await frm.set_value("rental_contract", m.rental_contract);
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
    }
});

frappe.ui.form.on("Job Completion Report Line", {
    erection_date(frm, cdt, cdn) {
        const r=locals[cdt][cdn];
        if (r.erection_date && r.included_days) frappe.model.set_value(cdt,cdn,"contract_end_date",frappe.datetime.add_days(r.erection_date,Math.max(cint(r.included_days),1)-1));
    },
    job_qty(frm,cdt,cdn) { if (frm.doc.docstatus===0) frm.dirty(); }
});
