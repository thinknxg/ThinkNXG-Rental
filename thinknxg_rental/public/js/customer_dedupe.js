frappe.ui.form.on("Customer", {
refresh(frm) {
if (!frm.is_dirty()) {
frm._orig = { name: frm.doc.customer_name, tax: frm.doc.tax_id };
}
},
customer_name(frm) { frm._dup_ok = false; },
tax_id(frm) { frm._dup_ok = false; },
after_save(frm) { frm._dup_ok = false; },
before_save(frm) {
if (frm._dup_ok) return;
const o = frm._orig || {};
if (!frm.is_new() && o.name === frm.doc.customer_name && o.tax === frm.doc.tax_id) return;

frappe.validated = false;
frappe.call({
method: "thinknxg_rental.services.customer_dedupe.check_duplicate_customer",
args: { customer_name: frm.doc.customer_name, tax_id: frm.doc.tax_id, name: frm.is_new() ? "" : frm.doc.name },
callback(r) {
const msgs = r.message || [];
const go = () => { frm._dup_ok = true; frm.save(); };
if (!msgs.length) return go();
frappe.confirm(
msgs.join("<br><br>") + "<br><br><b>" + __("Do you still want to create a duplicate Customer?") + "</b>",
go,
() => { frm._dup_ok = false; }
);
},
});
},
});
