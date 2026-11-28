import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, now_datetime

from thinknxg_rental.services import subcontracting as sc

EPS = 1e-9


class SubcontractMaterialRequest(Document):
	"""Company material a subcontractor asks for. Approval (submit) only authorises the issue; the stock moves with a
	Subcontract Material Allocation made from the request, which also keeps the issued quantity here up to date."""

	def validate(self):
		self.protect_status()
		swo = sc.work_order_for_document(self, sc.WORKING)
		self.supplier, self.company, self.project = swo.supplier, swo.company, swo.project
		self.supplier_name = frappe.db.get_value("Supplier", self.supplier, "supplier_name")
		if getdate(self.required_by) < getdate(self.request_date):
			frappe.throw(_("Required By cannot be before the Request Date"))
		seen = set()
		for r in self.items:
			if flt(r.qty) <= 0:
				frappe.throw(_("Row {0}: Quantity must be greater than zero").format(r.idx))
			if r.item_code in seen:
				frappe.throw(_("Row {0}: {1} is repeated. Merge the quantities").format(r.idx, r.item_code))
			seen.add(r.item_code)
			if not frappe.db.get_value("Item", r.item_code, "is_stock_item"):
				frappe.throw(_("Row {0}: {1} is not a stock item the company can issue").format(r.idx, r.item_code))

	def protect_status(self):
		if self.is_new():
			self.status = "Draft"
			self.requested_by = self.requested_by or frappe.session.user
		elif self.docstatus == 0 and not self.flags.workflow_move:
			self.status = frappe.db.get_value(self.doctype, self.name, "status") or "Draft"
		if self.docstatus == 0 and self.status == "Rejected" and not self.flags.workflow_move:
			frappe.throw(_("A rejected request cannot be changed. Raise a new one"))

	def before_submit(self):
		sc.require_role(sc.STORE_MANAGER, sc.MANAGER)
		if self.status == "Rejected":
			frappe.throw(_("A rejected request cannot be approved"))

	def on_submit(self):
		self.db_set({"status": "Approved", "approved_by": frappe.session.user, "approved_on": now_datetime()})
		if self.source == "Portal":
			from thinknxg_rental.services.subcontract_portal import notify_supplier

			notify_supplier(self.supplier, _("Material request {0} approved").format(self.name), self.review_remarks or "", self.doctype, self.name)

	def before_cancel(self):
		sc.require_role(sc.STORE_MANAGER, sc.MANAGER)
		if frappe.db.exists("Subcontract Material Allocation", {"material_request": self.name, "docstatus": 1}):
			frappe.throw(_("Material has been issued against this request. Cancel the Material Allocation first"))

	def on_cancel(self):
		self.db_set("status", "Cancelled")


def check_issue(allocation):
	"""An allocation made from a request issues only approved items, up to what is still to issue."""
	req = frappe.get_doc("Subcontract Material Request", allocation.material_request)
	if req.docstatus != 1:
		frappe.throw(_("Material Request {0} is not approved").format(req.name))
	if req.subcontract_work_order != allocation.subcontract_work_order:
		frappe.throw(_("Material Request {0} is for another work order").format(req.name))
	pending = {r.item_code: flt(r.qty) - issued_qty(req.name, r.item_code, exclude=allocation.name) for r in req.items}
	for r in allocation.items:
		if r.item_code not in pending:
			frappe.throw(_("Row {0}: {1} was not requested on {2}").format(r.idx, r.item_code, req.name))
		if flt(r.qty) > pending[r.item_code] + EPS:
			frappe.throw(_("Row {0}: only {1} of {2} is still to issue on {3}").format(r.idx, pending[r.item_code], r.item_code, req.name))


def issued_qty(request, item_code, exclude=None):
	return flt(frappe.db.sql("""select sum(i.qty) from `tabSubcontract Material Item` i join `tabSubcontract Material Allocation` a on a.name = i.parent
		where a.material_request = %s and a.docstatus = 1 and i.item_code = %s and a.name != %s""", (request, item_code, exclude or ""))[0][0])


def update_issued(request):
	req = frappe.get_doc("Subcontract Material Request", request)
	full = True
	anything = False
	for r in req.items:
		q = issued_qty(request, r.item_code)
		frappe.db.set_value("Subcontract Material Request Item", r.name, "issued_qty", q, update_modified=False)
		full = full and q >= flt(r.qty) - EPS
		anything = anything or q > EPS
	if req.docstatus == 1:
		req.db_set("status", "Issued" if full else ("Partially Issued" if anything else "Approved"))


def _get(name):
	doc = frappe.get_doc("Subcontract Material Request", name)
	doc.check_permission("read")
	return doc


@frappe.whitelist()
def submit_request(name):
	doc = _get(name)
	doc.check_permission("write")
	if doc.docstatus != 0 or doc.status != "Draft":
		frappe.throw(_("Only a draft request can be submitted"))
	doc.flags.workflow_move = True
	doc.status = "Submitted"
	doc.save()
	return doc.status


@frappe.whitelist()
def approve(name, review_remarks=None):
	doc = _get(name)
	if doc.docstatus != 0 or doc.status not in ("Draft", "Submitted"):
		frappe.throw(_("Only a draft or submitted request can be approved"))
	if review_remarks is not None:
		doc.review_remarks = review_remarks
	doc.flags.workflow_move = True
	doc.submit()
	return "Approved"


@frappe.whitelist()
def reject(name, review_remarks):
	sc.require_role(sc.STORE_MANAGER, sc.MANAGER)
	doc = _get(name)
	if doc.docstatus != 0 or doc.status not in ("Draft", "Submitted"):
		frappe.throw(_("Only a draft or submitted request can be rejected"))
	if not (review_remarks or "").strip():
		frappe.throw(_("Give the reason for rejecting the request"))
	doc.db_set({"status": "Rejected", "review_remarks": review_remarks})
	from thinknxg_rental.services.subcontract_portal import notify_supplier

	notify_supplier(doc.supplier, _("Material request {0} rejected").format(doc.name), review_remarks, doc.doctype, doc.name)
	return "Rejected"


@frappe.whitelist()
def make_material_allocation(source_name, source_warehouse=None):
	"""Draft Material Allocation for what is still to issue on an approved request."""
	sc.require_role(sc.STORE_MANAGER, sc.MANAGER)
	req = _get(source_name)
	if req.docstatus != 1 or req.status not in ("Approved", "Partially Issued"):
		frappe.throw(_("Only an approved request with material still to issue can be issued"))
	doc = frappe.new_doc("Subcontract Material Allocation")
	doc.update({"subcontract_work_order": req.subcontract_work_order, "material_request": req.name, "company": req.company,
		"supplier": req.supplier, "posting_date": frappe.utils.nowdate(),
		"source_warehouse": source_warehouse or frappe.db.get_single_value("Rental Settings", "rental_yard_warehouse")})
	for r in req.items:
		left = flt(r.qty) - issued_qty(req.name, r.item_code)
		if left > EPS:
			doc.append("items", {"item_code": r.item_code, "item_name": r.item_name, "uom": r.uom, "qty": left})
	return doc
