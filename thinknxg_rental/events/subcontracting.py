"""Hooks of the Subcontracting module on standard documents. Kept small: the rules live in services/subcontracting.py."""
import frappe
from frappe import _
from frappe.utils import flt


def purchase_invoice_validate(doc, method=None):
	"""A subcontract invoice is raised only by a Subcontract Settlement, so certified quantity cannot be invoiced twice."""
	if doc.get("subcontract_work_order") and not doc.flags.from_settlement and not doc.get("amended_from") and doc.is_new():
		frappe.throw(_("Invoice subcontract work through a Subcontract Settlement, not a manual Purchase Invoice"))


def payment_entry_validate(doc, method=None):
	"""Tag a payment with the work order it settles, and keep advances within the agreed advance."""
	if doc.payment_type != "Pay" or doc.party_type != "Supplier":
		return
	swo = doc.get("subcontract_work_order")
	for ref in doc.get("references") or []:
		if swo:
			break
		if ref.reference_doctype in ("Purchase Invoice", "Purchase Order") and ref.reference_name:
			swo = frappe.db.get_value(ref.reference_doctype, ref.reference_name, "subcontract_work_order")
	if not swo:
		return
	doc.subcontract_work_order = swo
	row = frappe.db.get_value("Subcontract Work Order", swo, ["supplier", "docstatus", "advance_amount"], as_dict=True)
	if not row or row.docstatus != 1:
		frappe.throw(_("Subcontract Work Order {0} is not approved").format(swo))
	if row.supplier != doc.party:
		frappe.throw(_("Payment party {0} is not the subcontractor of {1}").format(doc.party, swo))
	if not [r for r in doc.references if r.reference_doctype == "Purchase Invoice"]:
		given = flt(frappe.db.sql("""select sum(paid_amount) from `tabPayment Entry` where docstatus < 2 and payment_type = 'Pay' and subcontract_work_order = %s and name != %s
			and not exists (select 1 from `tabPayment Entry Reference` r where r.parent = `tabPayment Entry`.name and r.reference_doctype = 'Purchase Invoice')""",
			(swo, doc.name or ""))[0][0])
		if given + flt(doc.paid_amount) > flt(row.advance_amount) + 1e-9:
			frappe.throw(_("Advances to {0} would reach {1}; the agreed advance is {2}").format(swo, given + flt(doc.paid_amount), row.advance_amount))


def contract_on_cancel(doc, method=None):
	live = frappe.get_all("Subcontract Work Order", filters={"hire_order_contract": doc.name, "docstatus": 1}, pluck="name")
	if live:
		frappe.throw(_("Cancel the Subcontract Work Orders first: {0}").format(", ".join(live)))
