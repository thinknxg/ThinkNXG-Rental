frappe.ui.form.on("Hire Order Contract", {
    setup(frm) {
        frm.set_query("job_type", () => ({ filters: { is_job_type_item: 1, is_stock_item: 1, disabled: 0 } }));
        frm.set_query("item_code", "items", () => ({ filters: { is_rental_item: 1, is_stock_item: 1, disabled: 0 } }));
        frm.set_query("rental_site", () => ({ filters: { customer: frm.doc.customer, disabled: 0 } }));
        frm.set_query("hire_order", () => ({ filters: { docstatus: 1, status: "Open" } }));
        frm.set_query("taxes_and_charges", () => ({ filters: { company: frm.doc.company } }));
        frm.set_query("cost_center", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
    },
    refresh(frm) {
        if (frm.doc.docstatus === 1) {
            const base = "thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract.";
            const live = !["Completed", "Cancelled"].includes(frm.doc.status);
            const create = (label, method) => frm.add_custom_button(__(label), () => frappe.model.open_mapped_doc({ method: base + method, frm }), __("Create"));
            if (live) {
                create("Material Reservation", "make_reservation");
                create("Delivery Order", "make_delivery_order");
                if (frm.doc.total_at_site_qty > 0) create("Off-Hire Note", "make_off_hire_note");
                create("Cross Hire Order", "make_cross_hire_order");
                frm.add_custom_button(__("JCR"), () => frappe.call({
                    method: base + "make_jcr", args: { source_name: frm.doc.name }, freeze: true,
                    callback(r) { if (r.message) frappe.model.with_doctype("JCR", () => { const d = frappe.model.sync(r.message)[0]; frappe.set_route("Form", "JCR", d.name); }); }
                }), __("Create"));
                frm.page.set_inner_btn_group_as_primary(__("Create"));
            }
            if (frm.doc.billing_start_date) {
                frm.add_custom_button(__("Generate Billing"), () => frappe.prompt([
                    { fieldname: "upto_date", fieldtype: "Date", label: __("Bill Up To"), reqd: 1, default: frappe.datetime.add_days(frappe.datetime.get_today(), -1) }
                ], values => frappe.call({
                    method: "thinknxg_rental.services.billing.generate_billing", args: { hire_contract: frm.doc.name, upto_date: values.upto_date }, freeze: true,
                    callback(r) { const made = r.message || []; frappe.msgprint(made.length ? __("Created billing schedules: {0}", [made.join(", ")]) : __("Nothing to bill up to that date.")); frm.reload_doc(); }
                }), __("Generate Rental Billing")), __("Actions"));
            }
            frm.add_custom_button(__("Close Contract"), () => frappe.confirm(__("Raise the final rental bill and mark this contract Completed?"), () => frm.call("close_contract").then(() => frm.reload_doc())), __("Actions"));
        }
        if (frm.doc.status === "Completed") frm.add_custom_button(__("Reopen Contract"), () => frm.call("reopen_contract").then(() => frm.reload_doc()));
        frm.add_custom_button(__("Material at Site"), () => frappe.set_route("query-report", "Material at Site", { hire_contract: frm.doc.name }), __("View"));
    },
    hire_order(frm) {
        if (!frm.doc.hire_order || frm.doc.items?.some(d => d.item_code)) return;
        frappe.model.open_mapped_doc({ method: "thinknxg_rental.thinknxg_rental.doctype.hire_order.hire_order.make_contract", source_name: frm.doc.hire_order });
    },
    job_type(frm) {
        if (!frm.doc.job_type) return;
        frappe.call({
            method: "thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract.load_job_type_items",
            args: { source_name: frm.doc.job_type }, freeze: true,
            callback(r) {
                if (!r.message) return;
                frm.clear_table("items");
                (r.message || []).forEach(row => frm.add_child("items", row));
                frm.refresh_field("items");
                calculate_contract_rows(frm);
            }
        });
    },
});

frappe.ui.form.on("Hire Contract Item", {
    item_code(frm, cdt, cdn) { fetch_rental_details(frm, cdt, cdn); calculate_row(frm, cdt, cdn); },
    qty(frm, cdt, cdn) { calculate_row(frm, cdt, cdn); },
    contract_rate(frm, cdt, cdn) { calculate_row(frm, cdt, cdn); },
    rate(frm, cdt, cdn) { calculate_row(frm, cdt, cdn); },
    rotation_qty(frm, cdt, cdn) { calculate_row(frm, cdt, cdn); },
    contract_days(frm, cdt, cdn) { calculate_row(frm, cdt, cdn); },
    length(frm, cdt, cdn) { calculate_row(frm, cdt, cdn); },
    width(frm, cdt, cdn) { calculate_row(frm, cdt, cdn); },
    height(frm, cdt, cdn) { calculate_row(frm, cdt, cdn); },
});

function fetch_rental_details(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.item_code) return;
    frappe.call({
        method: "thinknxg_rental.services.utils.get_item_rental_details",
        args: { item_code: row.item_code, customer: frm.doc.customer, rate_basis: row.rate_basis || frm.doc.billing_cycle, posting_date: frm.doc.contract_date },
        callback(r) {
            if (!r.message) return;
            const m = r.message;
            frappe.model.set_value(cdt, cdn, { item_name: m.item_name, uom: m.uom, rate_basis: m.rate_basis, rate: m.rate, contract_rate: m.rate, replacement_value: m.replacement_value });
        },
    });
}

function calculate_row(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    const l = flt(row.length), w = flt(row.width), h = flt(row.height);
    if (l && w && h) {
        frappe.model.set_value(cdt, cdn, "area", l * w * h);
        frappe.model.set_value(cdt, cdn, "qty", l * w * h);
    }
    const qty = flt(row.qty);
    const duration = flt(row.rotation_qty) || flt(row.contract_days) || 1;
    const rate = flt(row.contract_rate) || flt(row.rate);
    frappe.model.set_value(cdt, cdn, "contract_amount", qty * rate * duration);
    calculate_contract_rows(frm);
}

function calculate_contract_rows(frm) {
    let qty = 0, amount = 0;
    (frm.doc.items || []).forEach(row => { qty += flt(row.qty); amount += flt(row.contract_amount); });
    frm.set_value("total_contract_qty", qty);
    frm.set_value("total_contract_amount", amount);
}
