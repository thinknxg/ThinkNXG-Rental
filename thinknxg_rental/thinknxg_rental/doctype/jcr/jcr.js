frappe.ui.form.on("JCR Item", {
    custom_erection_date: recalculate_row,
    custom_dismantle_date: recalculate_row,
    contract_days: recalculate_row,
    excess_charge: recalculate_row,
    excess_period: recalculate_row,
});

function recalculate_row(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!(row.custom_erection_date && row.custom_dismantle_date)) return;
    const erection = frappe.datetime.str_to_obj(row.custom_erection_date);
    const dismantle = frappe.datetime.str_to_obj(row.custom_dismantle_date);
    const actual_days = frappe.datetime.get_day_diff(dismantle, erection);
    const excess_days = actual_days - flt(row.contract_days);
    frappe.model.set_value(cdt, cdn, "excess_days", Math.max(excess_days, 0));
    let amount = 0;
    if (excess_days > 0) {
        if (row.excess_period === "Weekly") amount = excess_days / 7 * flt(row.excess_charge);
        else if (row.excess_period === "Monthly") amount = excess_days / 30 * flt(row.excess_charge);
        else amount = excess_days * flt(row.excess_charge);
    }
    frappe.model.set_value(cdt, cdn, "excess_amount", amount);
}

frappe.ui.form.on("JCR", {
    refresh(frm) {
        if (frm.doc.docstatus !== 1) return;
        frm.add_custom_button(__("Sales Invoice"), () => frappe.call({
            method: "thinknxg_rental.thinknxg_rental.doctype.jcr.jcr.create_sales_invoice",
            args: { source_name: frm.doc.name }, freeze: true,
            callback(r) { if (r.message) frappe.set_route("Form", "Sales Invoice", r.message); },
        }), __("Create"));
        frm.add_custom_button(__("Multiple JCRs"), () => open_multi_jcr_dialog(frm), __("Create"));
    },
});

function open_multi_jcr_dialog(frm) {
    frappe.call({
        method: "thinknxg_rental.thinknxg_rental.doctype.jcr.jcr.get_invoiceable_jcrs",
        args: { jcr: frm.doc.name },
        callback(r) {
            const rows = r.message || [];
            if (!rows.length) return frappe.msgprint(__("No other submitted, uninvoiced JCRs found for {0}", [frm.doc.client_name]));
            const fields = [{ fieldtype: "HTML", fieldname: "info", options: __("This JCR is included. Tick the others to invoice together.") }];
            rows.forEach((row, i) => fields.push({ fieldtype: "Check", fieldname: "jcr_" + i, label: [row.name, row.hire_contract, row.location].filter(Boolean).join(" | ") }));
            const dialog = new frappe.ui.Dialog({ title: __("Invoice multiple JCRs"), fields,
                primary_action_label: __("Create Sales Invoice"), primary_action(values) {
                    const picked = [frm.doc.name];
                    rows.forEach((row, i) => { if (values["jcr_" + i]) picked.push(row.name); });
                    if (picked.length < 2) return frappe.msgprint(__("Tick at least one other JCR"));
                    frappe.call({
                        method: "thinknxg_rental.thinknxg_rental.doctype.jcr.jcr.create_sales_invoice_for_jcrs",
                        args: { jcrs: picked }, freeze: true,
                        callback(res) { if (res.message) { dialog.hide(); frappe.set_route("Form", "Sales Invoice", res.message); } },
                    });
                }
            });
            dialog.show();
        }
    });
}
