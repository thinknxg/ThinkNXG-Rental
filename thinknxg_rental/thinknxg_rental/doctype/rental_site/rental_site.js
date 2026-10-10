// Rental Site made from a quotation: Create -> Hire Order carries on from here with the site filled in.
frappe.ui.form.on("Rental Site", {
        refresh(frm) {
                if (frm.is_new() || frm.doc.disabled) return;
                frm.add_custom_button(__("Hire Order"), async () => {
                        let quotation = frm.doc.nxg_quotation;
                        if (!quotation) {
                                // Site not made from a quotation: use the customer's only submitted hire quotation
                                const q = await frappe.db.get_list("Quotation", {
                                        filters: {
                                                quotation_to: "Customer", party_name: frm.doc.customer, docstatus: 1,
                                                deal_type: ["in", ["Material Hire", "Hire Order Contract"]],
                                                status: ["not in", ["Lost", "Expired", "Cancelled"]],
                                        },
                                        fields: ["name"], limit: 50, order_by: "creation desc",
                                });
                                if (q.length === 1) {
                                        quotation = q[0].name;
                                } else if (q.length > 1) {
                                        frappe.msgprint(__("This Rental Site is not linked to a quotation and the customer has several. Create the site from the quotation (Quotation > Create > Rental Site)."));
                                        return;
                                }
                        }
                        if (!quotation) {
                                frappe.new_doc("Hire Order", {
                                        customer: frm.doc.customer,
                                        customer_name: frm.doc.customer_name,
                                        company: frm.doc.company,
                                        rental_site: frm.doc.name,
                                });
                                return;
                        }
                        if (!frm.doc.nxg_quotation) await frappe.db.set_value("Rental Site", frm.doc.name, "nxg_quotation", quotation);
                        const r = await frappe.db.get_value("Quotation", quotation, ["deal_type", "docstatus"]);
                        const v = r.message || {};
                        if (v.docstatus !== 1) {
                                frappe.msgprint(__("Submit quotation {0} first, then use this button.", [quotation]));
                                return;
                        }
                        const fn = v.deal_type === "Hire Order Contract" ? "make_hire_order_contract_from_quotation" : "make_hire_order_from_quotation";
                        frappe.model.open_mapped_doc({
                                method: "thinknxg_rental.services.deal_flow." + fn,
                                source_name: quotation,
                                args: { rental_site: frm.doc.name },
                        });
                }, __("Create"));
                frm.page.set_inner_btn_group_as_primary(__("Create"));
        },
});

// Site opened from Quotation > Create > Rental Site: keep that quotation on the site.
// quotation_deal.js leaves it in frappe.flags because a read-only prefill is often dropped.
function nxg_take_site_quotation(max_age_ms) {
        const f = frappe.flags.nxg_site_quotation;
        if (!f) return null;
        frappe.flags.nxg_site_quotation = null;
        return Date.now() - f.at <= max_age_ms ? f.quotation : null;
}

frappe.ui.form.on("Rental Site", {
        onload(frm) {
                if (!frm.is_new()) return;
                const q = nxg_take_site_quotation(60000);
                if (q && !frm.doc.nxg_quotation) frm.set_value("nxg_quotation", q);
        },
        refresh(frm) {
                // fallback: the site was saved through a quick-entry dialog, so the new-form step never ran
                if (frm.is_new() || frm.doc.nxg_quotation || !frappe.flags.nxg_site_quotation) return;
                const q = nxg_take_site_quotation(120000);
                if (q) frappe.db.set_value("Rental Site", frm.doc.name, "nxg_quotation", q).then(() => frm.reload_doc());
        },
});
