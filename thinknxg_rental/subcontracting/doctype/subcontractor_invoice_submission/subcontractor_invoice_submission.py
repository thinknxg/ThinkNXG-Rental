import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from thinknxg_rental.services import subcontracting as sc

EPS = 1e-9
OPEN = ("Draft", "Submitted")


class SubcontractorInvoiceSubmission(Document):
	"""The subcontractor's own invoice, entered in the portal or by staff. Lines can only take accepted work that is not
	yet invoiced nor claimed on another open submission. Verifying (submit) creates the Subcontract Settlement, which
	creates the one Purchase Invoice with retention, advance and recoveries, so accounting stays in ERPNext."""

	def validate(self):
		self.protect_status()
		swo = frappe.db.get_value("Subcontract Work Order", self.subcontract_work_order,
			["docstatus", "status", "supplier", "company", "project"], as_dict=True)
		if not swo or swo.docstatus != 1:
			frappe.throw(_("Subcontract Work Order {0} must be approved").format(self.subcontract_work_order))
		allowed = ("Verified",) if self.bill_type == "Final Bill" else sc.BILLABLE
		if swo.status not in allowed:
			frappe.throw(_("A {0} needs the work order to be {1}; it is {2}").format(_(self.bill_type), _(" or ").join(allowed), swo.status))
		self.supplier, self.company, self.project = swo.supplier, swo.company, swo.project
		self.supplier_name = frappe.db.get_value("Supplier", self.supplier, "supplier_name")
		self.supplier_invoice_no = (self.supplier_invoice_no or "").strip()
		self.check_duplicate()
		lines = billable_lines(self.subcontract_work_order, exclude=self.name)
		total, seen = 0, set()
		for r in self.items:
			src = lines.get(r.swo_item)
			if not src:
				frappe.throw(_("Row {0}: work item does not belong to {1}").format(r.idx, self.subcontract_work_order))
			if r.swo_item in seen:
				frappe.throw(_("Row {0}: work item is repeated").format(r.idx))
			seen.add(r.swo_item)
			r.job_type, r.description, r.rate, r.billable_qty = src.job_type, src.description, flt(src.rate), flt(src.billable_qty)
			if flt(r.qty) <= 0:
				frappe.throw(_("Row {0}: quantity must be above zero").format(r.idx))
			if flt(r.qty) > r.billable_qty + EPS:
				frappe.throw(_("Row {0}: only {1} of {2} is accepted and not yet invoiced or claimed").format(r.idx, r.billable_qty, r.job_type),
					title=_("More than the accepted work"))
			r.amount = flt(r.qty) * r.rate
			total += r.amount
		self.total_claimed = total

	def check_duplicate(self):
		other = frappe.db.get_value("Subcontractor Invoice Submission", {"supplier": self.supplier, "company": self.company,
			"supplier_invoice_no": self.supplier_invoice_no, "name": ["!=", self.name or ""], "docstatus": ["<", 2],
			"status": ["not in", ["Rejected", "Cancelled"]]}, "name")
		if not other:
			other = frappe.db.get_value("Purchase Invoice", {"supplier": self.supplier, "company": self.company, "bill_no": self.supplier_invoice_no,
				"docstatus": ["<", 2]}, "name")
		if other:
			frappe.throw(_("Invoice number {0} of {1} is already recorded ({2})").format(self.supplier_invoice_no, self.supplier, other),
				title=_("Duplicate invoice"))

	def protect_status(self):
		if self.is_new():
			self.status = "Draft"
			self.submitted_by = self.submitted_by or frappe.session.user
		elif self.docstatus == 0 and not self.flags.workflow_move:
			self.status = frappe.db.get_value(self.doctype, self.name, "status") or "Draft"
		if self.docstatus == 0 and self.status == "Rejected" and not self.flags.workflow_move:
			frappe.throw(_("A rejected invoice cannot be changed. Submit a new one"))

	def before_submit(self):
		sc.require_role(*sc.ACCOUNTS, sc.MANAGER) if self.bill_type == "Running Bill" else sc.require_role("Accounts Manager")
		if self.status == "Rejected":
			frappe.throw(_("A rejected invoice cannot be verified"))
		sc.lock_work_order(self.subcontract_work_order)
		self.validate()

	def on_submit(self):
		st = frappe.new_doc("Subcontract Settlement")
		st.update({"subcontract_work_order": self.subcontract_work_order, "posting_date": self.supplier_invoice_date or frappe.utils.nowdate(),
			"settlement_type": "Final" if self.bill_type == "Final Bill" else "Partial", "invoice_submission": self.name,
			"supplier_invoice_no": self.supplier_invoice_no, "supplier_invoice_date": self.supplier_invoice_date,
			"remarks": _("From subcontractor invoice {0} ({1})").format(self.supplier_invoice_no, self.name)})
		for r in self.items:
			st.append("items", {"swo_item": r.swo_item, "qty": r.qty})
		st.insert()
		st.submit()
		self.db_set({"status": "Verified", "settlement": st.name, "purchase_invoice": st.purchase_invoice,
			"verified_by": frappe.session.user, "verified_on": now_datetime()})
		from thinknxg_rental.services.subcontract_portal import notify_supplier

		notify_supplier(self.supplier, _("Invoice {0} verified").format(self.supplier_invoice_no), self.review_remarks or "", self.doctype, self.name,
			commercial_only=True)

	def before_cancel(self):
		if self.settlement and frappe.db.get_value("Subcontract Settlement", self.settlement, "docstatus") == 1:
			frappe.throw(_("Cancel Settlement {0} first; it reverses the Purchase Invoice").format(self.settlement))

	def on_cancel(self):
		self.db_set("status", "Cancelled")


def billable_lines(swo, exclude=None):
	"""Per work item: accepted − invoiced − quantity on other open (draft or submitted) invoice submissions."""
	rows = frappe.get_all("Subcontract Work Item", filters={"parent": swo},
		fields=["name", "job_type", "description", "rate", "qty", "accepted_qty", "invoiced_qty", "work_category"], order_by="idx")
	pending = {r.swo_item: flt(r.qty) for r in frappe.db.sql("""select i.swo_item, sum(i.qty) as qty from `tabSubcontractor Invoice Item` i
		join `tabSubcontractor Invoice Submission` s on s.name = i.parent where s.subcontract_work_order = %s and s.docstatus = 0
		and s.status in ('Draft', 'Submitted') and s.name != %s group by i.swo_item""", (swo, exclude or ""), as_dict=True)}
	out = {}
	for r in rows:
		r.billable_qty = max(flt(r.accepted_qty) - flt(r.invoiced_qty) - pending.get(r.name, 0), 0)
		out[r.name] = r
	return out


def _get(name):
	doc = frappe.get_doc("Subcontractor Invoice Submission", name)
	doc.check_permission("read")
	return doc


@frappe.whitelist()
def submit_for_verification(name):
	doc = _get(name)
	doc.check_permission("write")
	if doc.docstatus != 0 or doc.status != "Draft":
		frappe.throw(_("Only a draft invoice can be submitted"))
	doc.flags.workflow_move = True
	doc.status = "Submitted"
	doc.save()
	return doc.status


@frappe.whitelist()
def verify(name, review_remarks=None):
	doc = _get(name)
	if doc.docstatus != 0 or doc.status not in ("Draft", "Submitted"):
		frappe.throw(_("Only a draft or submitted invoice can be verified"))
	if review_remarks is not None:
		doc.review_remarks = review_remarks
	doc.flags.workflow_move = True
	doc.submit()
	return "Verified"


@frappe.whitelist()
def reject(name, reason):
	sc.require_role(*sc.ACCOUNTS, sc.MANAGER)
	doc = _get(name)
	if doc.docstatus != 0 or doc.status != "Submitted":
		frappe.throw(_("Only a submitted invoice can be rejected"))
	if not (reason or "").strip():
		frappe.throw(_("Give the reason for rejecting the invoice"))
	doc.db_set({"status": "Rejected", "rejection_reason": reason, "review_remarks": doc.review_remarks or reason})
	from thinknxg_rental.services.subcontract_portal import notify_supplier

	notify_supplier(doc.supplier, _("Invoice {0} rejected").format(doc.supplier_invoice_no), reason, doc.doctype, doc.name, commercial_only=True)
	return "Rejected"
