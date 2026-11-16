frappe.ui.form.on("Lead", {
	setup(frm) {
		// Existing customer: search by customer name only
		frm.set_query("customer", () => ({ query: "thinknxg_rental.services.lead_fields.customer_name_search" }));
	},
	refresh(frm) {
		if (frm.is_new() && frm.doc.lead_owner && !frm.doc.nxg_tender_assignee) frm.set_value("nxg_tender_assignee", frm.doc.lead_owner);
		if (frm.is_new() || frm.doc.docstatus !== 0 || !frm.doc.deal_type) return;
		frm.add_custom_button(__("Quotation"), () => {
			frappe.model.open_mapped_doc({
				method: "thinknxg_rental.services.deal_flow.make_quotation_from_lead",
				frm,
			});
		}, __("Create"));
		frm.page.set_inner_btn_group_as_primary(__("Create"));
	},
	customer(frm) {
		if (!frm.doc.customer) return;
		// Existing customer: fill the organization, address and primary contact details
		frappe.call({
			method: "thinknxg_rental.services.lead_fields.get_customer_details",
			args: { customer: frm.doc.customer },
		}).then((r) => {
			const d = r.message || {};
			Object.keys(d).forEach((k) => { if (d[k]) frm.set_value(k, d[k]); });
		});
	},
	lead_owner(frm) {
		if (frm.doc.lead_owner && !frm.doc.nxg_tender_assignee) frm.set_value("nxg_tender_assignee", frm.doc.lead_owner);
	},
	nxg_required_from(frm) { nxg_lead_hire_days(frm); },
	nxg_expected_return_date(frm) { nxg_lead_hire_days(frm); },
	validate(frm) {
		if (frm.doc.nxg_required_from && frm.doc.nxg_expected_return_date && frm.doc.nxg_expected_return_date < frm.doc.nxg_required_from) {
			frappe.throw(__("Expected Return Date cannot be before Required From."));
		}
	},
});

function nxg_lead_hire_days(frm) {
	const a = frm.doc.nxg_required_from, b = frm.doc.nxg_expected_return_date;
	frm.set_value("nxg_hire_period_days", a && b ? Math.max(frappe.datetime.get_diff(b, a) + 1, 0) : 0);
}
