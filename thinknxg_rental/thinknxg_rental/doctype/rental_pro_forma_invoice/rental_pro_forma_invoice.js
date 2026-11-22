// Pro Forma Invoice: approval, sending, acceptance, money received against it and conversion to the tax invoice.
const NXG_PF = "thinknxg_rental.thinknxg_rental.doctype.rental_pro_forma_invoice.rental_pro_forma_invoice.";

frappe.ui.form.on("Rental Pro Forma Invoice", {
	setup(frm) {
		frm.set_query("hire_order", () => ({ filters: { customer: frm.doc.customer, company: frm.doc.company, docstatus: ["!=", 2] } }));
		frm.set_query("rental_contract", () => ({ filters: { customer: frm.doc.customer, company: frm.doc.company, docstatus: 1 } }));
		frm.set_query("customer_address", () => ({ query: "frappe.contacts.doctype.address.address.address_query", filters: { link_doctype: "Customer", link_name: frm.doc.customer } }));
		frm.set_query("contact_person", () => ({ query: "frappe.contacts.doctype.contact.contact.contact_query", filters: { link_doctype: "Customer", link_name: frm.doc.customer } }));
		frm.set_query("rental_site", () => ({ filters: { customer: frm.doc.customer } }));
	},
	refresh(frm) {
		if (frm.doc.vat_review_note) frm.dashboard.set_headline_alert(frm.doc.vat_review_note, "orange");
		const s = frm.doc.status;
		if (frm.doc.docstatus === 0 && !frm.is_new() && s === "Draft") {
			frm.add_custom_button(__("Submit for Approval"), () => frm.call("submit_for_approval").then(() => frm.reload_doc()));
		}
		if (frm.doc.docstatus !== 1) return;
		const open = ["Approved", "Sent to Customer", "Customer Accepted", "Advance Received"].includes(s);
		if (open) {
			frm.add_custom_button(__("Email to Customer"), () => {
				frappe.prompt([
					{ fieldname: "recipients", fieldtype: "Data", label: __("To"), reqd: 1, default: frm.doc.contact_email },
					{ fieldname: "subject", fieldtype: "Data", label: __("Subject"), default: __("Pro Forma Invoice {0}", [frm.doc.name]) },
					{ fieldname: "message", fieldtype: "Small Text", label: __("Message") },
				], (v) => frm.call("send_email", v).then(() => frm.reload_doc()), __("Email Pro Forma Invoice"), __("Send"));
			}, __("Share"));
			frm.add_custom_button(__("WhatsApp"), () => frm.call("whatsapp_message").then((r) => {
				const m = r.message;
				window.open(`https://wa.me/${m.mobile}?text=${encodeURIComponent(m.text)}`, "_blank", "noopener");
				frm.call("mark_sent", { via: "WhatsApp" }).then(() => frm.reload_doc());
			}), __("Share"));
			frm.add_custom_button(__("Mark as Sent (PDF)"), () => frm.call("mark_sent", { via: "PDF" }).then(() => frm.reload_doc()), __("Share"));
		}
		if (["Approved", "Sent to Customer"].includes(s)) {
			frm.add_custom_button(__("Customer Accepted"), () => frappe.prompt([
				{ fieldname: "accepted_by", fieldtype: "Data", label: __("Accepted By"), default: frm.doc.contact_display },
				{ fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") },
			], (v) => frm.call("mark_accepted", v).then(() => frm.reload_doc()), __("Customer Acceptance")), __("Status"));
		}
		if (open) {
			const b = () => frappe.xcall("thinknxg_rental.thinknxg_rental.doctype.rental_contract_payment.rental_contract_payment.get_balances", { pro_forma_invoice: frm.doc.name });
			frm.add_custom_button(__("Collect Advance"), () => b().then((bal) => thinknxg_rental.payments.dialog(frm, "Advance Collection", bal)), __("Payment"));
			if (flt(frm.doc.total_deposit) > 0) {
				frm.add_custom_button(__("Collect Security Deposit"), () => b().then((bal) => thinknxg_rental.payments.dialog(frm, "Deposit Collection", bal)), __("Payment"));
			}
			if (!frm.doc.sales_invoice) {
				frm.add_custom_button(__("Tax Invoice"), () => frappe.confirm(
					__("Make the VAT tax invoice for this pro forma invoice? Its VAT is worked out again on the invoice date."),
					() => frappe.xcall(NXG_PF + "make_sales_invoice", { source_name: frm.doc.name }).then((name) => frappe.set_route("Form", "Sales Invoice", name))
				), __("Create"));
			}
		}
		if (frm.doc.sales_invoice) {
			frm.add_custom_button(__("Tax Invoice {0}", [frm.doc.sales_invoice]), () => frappe.set_route("Form", "Sales Invoice", frm.doc.sales_invoice), __("View"));
		}
	},
	customer: (frm) => frm.set_value({ customer_address: null, contact_person: null, customer_country: null, customer_vat_number: null }),
	discount_percentage: (frm) => frm.doc.discount_percentage && frm.set_value("discount_amount", 0),
});

frappe.ui.form.on("Rental Pro Forma Item", {
	item_code: (frm, cdt, cdn) => nxg_pf_rate(frm, cdt, cdn),
	rate_basis: (frm, cdt, cdn) => nxg_pf_rate(frm, cdt, cdn),
	period_days: (frm, cdt, cdn) => nxg_pf_rate(frm, cdt, cdn),
	items_add(frm, cdt, cdn) {
		const prev = (frm.doc.items || []).filter((d) => d.name !== cdn).slice(-1)[0];
		if (prev) frappe.model.set_value(cdt, cdn, { rental_from: prev.rental_from, rental_to: prev.rental_to, rate_basis: prev.rate_basis });
	},
});

function nxg_pf_rate(frm, cdt, cdn) {
	const d = locals[cdt][cdn];
	if (!d.item_code) return;
	frappe.xcall(NXG_PF + "get_item_rate", { item_code: d.item_code, rate_basis: d.rate_basis || "Monthly", customer: frm.doc.customer,
		posting_date: frm.doc.posting_date, period_days: d.period_days }).then((rate) => frappe.model.set_value(cdt, cdn, "rate", rate));
}
