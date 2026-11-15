// Rental Website Enquiry: staff move the enquiry into the usual Lead -> Quotation flow.
frappe.ui.form.on("Rental Website Enquiry", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.lead) frm.add_custom_button(__("Lead"), () => frappe.set_route("Form", "Lead", frm.doc.lead), __("Open"));
		if (frm.doc.customer) frm.add_custom_button(__("Customer"), () => frappe.set_route("Form", "Customer", frm.doc.customer), __("Open"));
		for (const f of ["hire_quotation", "purchase_quotation"]) {
			if (frm.doc[f]) frm.add_custom_button(frm.doc[f], () => frappe.set_route("Form", "Quotation", frm.doc[f]), __("Open"));
		}
		const missing = (frm.doc.items || []).some((d) => (d.line_type === "Purchase" ? !frm.doc.purchase_quotation : !frm.doc.hire_quotation));
		if (missing && frm.doc.status !== "Spam") {
			frm.add_custom_button(__("Create quotation"), () => frm.call("make_quotations").then(() => frm.reload_doc()), __("Create")).addClass("btn-primary");
		}
		if (frm.doc.status === "New") frm.add_custom_button(__("Mark as spam"), () => { frm.set_value("status", "Spam"); frm.save(); });
	},
});
