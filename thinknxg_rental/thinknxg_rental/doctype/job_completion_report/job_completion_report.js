const JCR_HOC = "thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract.";

frappe.ui.form.on("Job Completion Report", {
    setup(frm) {
        frm.set_query("hire_order_contract", () => ({ filters: { docstatus: 1 } }));
        frm.set_query("rental_contract", () => ({ filters: { contract_type: "Job Type Contract", docstatus: 1 } }));
    },
    onload(frm) { frm.trigger("load_job_lines"); },
    hire_order_contract(frm) {
        if (frm.doc.docstatus === 0) frm.trigger("load_job_lines");
    },
    rental_contract(frm) {
        if (frm.doc.docstatus === 0 && frm.doc.rental_contract && !frm.doc.hire_order_contract) {
            frappe.db.get_value("Rental Contract", frm.doc.rental_contract, ["source_type","source_document","company","customer","rental_site"]).then(r => {
                const v=r.message||{};
                if (v.source_type === "Hire Order Contract" && v.source_document) frm.set_value("hire_order_contract",v.source_document);
                if (!frm.doc.company && v.company) frm.set_value("company",v.company);
            });
        }
    },
    load_job_lines(frm) {
        if (frm.doc.docstatus !== 0 || !frm.doc.hire_order_contract) return;
        return frappe.call({method:JCR_HOC+"get_job_lines",args:{hire_order_contract:frm.doc.hire_order_contract}}).then(r=>{
            const m=r.message||{};
            if (!frm.doc.job_lines || !frm.doc.job_lines.length) {
                frm.clear_table("job_lines");
                (m.lines||[]).forEach(l=>frm.add_child("job_lines",{
                    contract_item:l.name,job_type:l.job_type,job_type_name:l.job_type_name,location:l.location,
                    job_qty:l.remaining,erection_date:frappe.datetime.get_today(),included_days:l.included_days,
                    contract_end_date:frappe.datetime.add_days(frappe.datetime.get_today(),Math.max(cint(l.included_days),1)-1),
                    contract_rate:l.contract_rate,contract_charge_billing:m.contract_charge_billing,
                    excess_rate_basis:l.excess_rate_basis,excess_rate:l.excess_rate,status:"Draft"
                }));
                frm.refresh_field("job_lines");
            }
            if (!frm.doc.company && m.company) frm.set_value("company",m.company);
            if (!frm.doc.rental_contract && m.rental_contract) frm.set_value("rental_contract",m.rental_contract);
        });
    },
    refresh(frm) {
        if (frm.doc.docstatus !== 1) return;
        const active=(frm.doc.job_lines||[]).filter(r=>!r.dismantle_date && r.status!=="Completed");
        if (active.length) {
            frm.add_custom_button(__("Record Dismantle"),()=>{
                const opts=active.map(r=>({label:`${r.job_type_name||r.job_type}${r.location?" - "+r.location:""} (${r.job_qty})`,value:r.name}));
                frappe.prompt([
                    {fieldname:"line_name",fieldtype:"Select",label:__("JCR Job Line"),options:opts.map(x=>x.value).join("\n"),reqd:1},
                    {fieldname:"dismantle_date",fieldtype:"Date",label:__("Dismantle Date"),reqd:1,default:frappe.datetime.get_today()},
                    {fieldname:"remarks",fieldtype:"Small Text",label:__("Remarks")}
                ],v=>frm.call("record_dismantle",v).then(()=>frm.reload_doc()),__("Record Dismantle"),__("Stop the Clock"));
            }).addClass("btn-primary");
        }
        if (frm.doc.status !== "Completed") frm.add_custom_button(__("Generate Billing"),()=>frappe.call({method:"thinknxg_rental.services.jcr_billing.generate_jcr_billing",args:{jcr:frm.doc.name},freeze:true}).then(r=>{frappe.msgprint((r.message||[]).length?__("Billing periods processed: {0}",[r.message.join(", ")]):__("No billing period is due yet."));frm.reload_doc();}));
        frm.add_custom_button(__("Billing Schedule"),()=>frappe.set_route("List","JCR Billing Schedule",{jcr:frm.doc.name}));
    }
});

frappe.ui.form.on("Job Completion Report Line", {
    erection_date(frm, cdt, cdn) {
        const r=locals[cdt][cdn];
        if (r.erection_date && r.included_days) frappe.model.set_value(cdt,cdn,"contract_end_date",frappe.datetime.add_days(r.erection_date,Math.max(cint(r.included_days),1)-1));
    },
    job_qty(frm,cdt,cdn) { if (frm.doc.docstatus===0) frm.dirty(); }
});
