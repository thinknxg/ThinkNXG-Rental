import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate, now_datetime

from thinknxg_rental.services import subcontracting as sc

EPS = 1e-9
TERMINAL = ("Closed", "Cancelled")


class SubcontractWorkOrder(Document):
	# ----- validate (draft and approval stage) ----------------------------------------------------------------
	def validate(self):
		self.protect_status()
		self.load_contract()
		self.validate_supplier()
		self.validate_rows()
		self.validate_dates()
		self.calculate_totals()
		if self.docstatus == 0:
			self.check_availability(strict=False)

	def protect_status(self):
		"""Status moves only through the whitelisted workflow methods below, never through a form save or API write."""
		if self.is_new():
			self.status = "Draft"
		elif self.docstatus == 0 and not self.flags.workflow_move:
			self.status = frappe.db.get_value(self.doctype, self.name, "status") or "Draft"
		if self.flags.workflow_move:
			return
		if self.is_new() or self.docstatus == 0:
			for f in ("approved_by", "approved_on", "verified_by", "verified_on"):
				if not self.is_new() and self.get(f) != frappe.db.get_value(self.doctype, self.name, f):
					self.set(f, frappe.db.get_value(self.doctype, self.name, f))
				elif self.is_new():
					self.set(f, None)

	def load_contract(self):
		if not self.hire_order_contract:
			frappe.throw(_("Hire Order Contract is required"))
		hoc = frappe.db.get_value("Hire Order Contract", self.hire_order_contract,
			["docstatus", "status", "customer", "project", "rental_site", "company", "cost_center", "taxes_and_charges"], as_dict=True)
		if not hoc or hoc.docstatus != 1:
			frappe.throw(_("Hire Order Contract {0} must be submitted before work is subcontracted").format(self.hire_order_contract))
		if hoc.status in ("Cancelled", "Closed"):
			frappe.throw(_("Hire Order Contract {0} is {1}").format(self.hire_order_contract, hoc.status))
		for f in ("customer", "project", "rental_site", "company"):
			self.set(f, hoc.get(f))
		if not self.cost_center:
			self.cost_center = hoc.cost_center
		if not self.currency:
			self.currency = frappe.db.get_value("Company", self.company, "default_currency")
		if not self.contract_date:
			self.contract_date = nowdate()

	def validate_supplier(self):
		if not self.supplier:
			frappe.throw(_("Subcontractor is required"))
		meta = frappe.get_meta("Supplier")
		row = frappe.db.get_value("Supplier", self.supplier, ["supplier_name", "disabled"], as_dict=True)
		if not row or row.disabled:
			frappe.throw(_("Supplier {0} is not available").format(self.supplier))
		self.supplier_name = row.supplier_name
		if meta.has_field("is_subcontractor") and not frappe.db.get_value("Supplier", self.supplier, "is_subcontractor"):
			frappe.throw(_("{0} is not set up as a Subcontractor").format(self.supplier))
		if not self.retention_percentage and meta.has_field("default_retention_percentage"):
			self.retention_percentage = frappe.db.get_value("Supplier", self.supplier, "default_retention_percentage")

	def validate_rows(self):
		if not self.items:
			frappe.throw(_("Add at least one work item"))
		lines = sc.job_lines(self.hire_order_contract)
		kinds = set()
		for r in self.items:
			if flt(r.qty) <= 0:
				frappe.throw(_("Row {0}: Quantity must be greater than zero").format(r.idx))
			if flt(r.rate) < 0:
				frappe.throw(_("Row {0}: Rate cannot be negative").format(r.idx))
			if not r.work_category:
				frappe.throw(_("Row {0}: Work Category (Labour or Equipment) is required").format(r.idx))
			kinds.add(r.work_category)
			if r.is_additional:
				r.hoc_item = r.hoc_item if r.hoc_item in lines else None
				if not r.description:
					frappe.throw(_("Row {0}: describe the additional work").format(r.idx))
			else:
				if r.hoc_item not in lines:
					frappe.throw(_("Row {0}: Job line does not belong to Hire Order Contract {1}").format(r.idx, self.hire_order_contract))
				line = lines[r.hoc_item]
				r.job_type, r.contract_qty = line.job_type, flt(line.qty)
			r.amount = flt(r.qty) * flt(r.rate)
			if r.work_category != "Equipment":
				r.equipment_ownership = None
		dup = set()
		for r in self.items:
			if r.hoc_item and not r.is_additional:
				key = (r.hoc_item, r.work_category)
				if key in dup:
					frappe.throw(_("Row {0}: job line is repeated for {1}. Merge the quantities into one row").format(r.idx, r.work_category))
				dup.add(key)
		if self.subcontract_type == "Labour" and kinds - {"Labour"}:
			frappe.throw(_("A Labour work order cannot hold Equipment rows"))
		if self.subcontract_type == "Equipment" and kinds - {"Equipment"}:
			frappe.throw(_("An Equipment work order cannot hold Labour rows"))

	def validate_dates(self):
		if self.start_date and self.expected_completion_date and getdate(self.expected_completion_date) < getdate(self.start_date):
			frappe.throw(_("Expected Completion Date cannot be before Start Date"))

	def calculate_totals(self):
		labour = sum(flt(r.amount) for r in self.items if r.work_category == "Labour")
		equip = sum(flt(r.amount) for r in self.items if r.work_category == "Equipment")
		extra = sum(flt(r.amount) for r in self.items if r.is_additional)
		self.labour_cost, self.equipment_cost = labour, equip
		self.contract_amount = labour + equip - extra
		self.approved_additional_cost = extra
		self.final_contract_value = labour + equip
		self.total_estimated_cost = labour + equip
		self.advance_amount = flt(self.final_contract_value) * flt(self.advance_percentage) / 100 if self.advance_percentage else flt(self.advance_amount)

	# ----- allocation -----------------------------------------------------------------------------------------
	def check_availability(self, strict):
		"""strict=True (on approval): refuse. strict=False (draft): refuse too when the draft alone already exceeds the
		balance, because that work order could never be approved; quantity is only consumed on approval."""
		avail = {r.hoc_item: r for r in sc.line_availability(self.hire_order_contract, exclude=self.name)}
		per_line = {}
		for r in self.items:
			if r.is_additional or not r.hoc_item:
				continue
			per_line.setdefault(r.hoc_item, 0)
			per_line[r.hoc_item] += flt(r.qty)
		for hoc_item, qty in per_line.items():
			a = avail.get(hoc_item)
			if a is None or qty > flt(a.available_qty) + EPS:
				frappe.throw(_("{0}: {1} requested but only {2} of {3} is available for subcontracting").format(
					a.job_type_name or a.job_type if a else hoc_item, qty, flt(a.available_qty) if a else 0, flt(a.contract_qty) if a else 0),
					title=_("Over-allocation"))
		for r in self.items:
			if r.hoc_item and not r.is_additional and r.hoc_item in avail:
				r.previously_subcontracted_qty = avail[r.hoc_item].subcontracted_qty
		if self.allocation_type == "Full" and strict:
			for a in avail.values():
				if a.available_qty > EPS and per_line.get(a.hoc_item, 0) < a.available_qty - EPS:
					frappe.throw(_("Full allocation must cover the whole balance of every job line. {0} still has {1} unallocated").format(
						a.job_type_name or a.job_type, a.available_qty - per_line.get(a.hoc_item, 0)))

	def before_submit(self):
		if not self.flags.approving:
			frappe.throw(_("A Subcontract Work Order is approved with Approve, not submitted directly"), frappe.PermissionError)
		sc.lock_contract(self.hire_order_contract)
		self.load_contract()
		if frappe.get_meta("Supplier").has_field("subcontractor_approval_status"):
			status = frappe.db.get_value("Supplier", self.supplier, "subcontractor_approval_status")
			if status != "Approved":
				frappe.throw(_("Subcontractor {0} is {1}. Only Approved subcontractors can receive work").format(self.supplier, status or "not approved"))
		self.check_availability(strict=True)

	def on_submit(self):
		self.db_set({"status": "Approved", "approved_by": frappe.session.user, "approved_on": now_datetime()})
		self.add_comment("Info", _("Approved by {0}").format(frappe.session.user))

	# ----- cancel / amend -------------------------------------------------------------------------------------
	def before_cancel(self):
		sc.require_role(sc.MANAGER)
		blockers = []
		for dt, label in (("Subcontract Work Progress", "Work Progress"), ("Subcontract Completion Report", "Completion Report"),
				("Subcontract Material Allocation", "Material Allocation"), ("Subcontract Material Return", "Material Return"),
				("Subcontract Settlement", "Settlement")):
			if frappe.db.exists("DocType", dt):
				names = frappe.get_all(dt, filters={"subcontract_work_order": self.name, "docstatus": 1}, pluck="name")
				if names:
					blockers.append(_("{0}: {1}").format(label, ", ".join(names)))
		for dt in ("Purchase Order", "Purchase Invoice"):
			if frappe.get_meta(dt).has_field("subcontract_work_order"):
				names = frappe.get_all(dt, filters={"subcontract_work_order": self.name, "docstatus": 1}, pluck="name")
				if names:
					blockers.append(_("{0}: {1}").format(dt, ", ".join(names)))
		if blockers:
			frappe.throw(_("Cancel or reverse these first:") + "<br>" + "<br>".join(blockers), title=_("Cannot cancel"))
		self.flags.workflow_move = True
		sc.lock_contract(self.hire_order_contract)

	def on_cancel(self):
		# the quantity returns to the contract automatically: availability only counts docstatus = 1
		self.db_set("status", "Cancelled")
		self.add_comment("Info", _("Cancelled by {0}; quantity released back to {1}").format(frappe.session.user, self.hire_order_contract))

	def on_trash(self):
		if self.docstatus == 1:
			frappe.throw(_("Submitted work orders cannot be deleted"))


# ----- whitelisted workflow ---------------------------------------------------------------------------------
def _get(name):
	return frappe.get_doc("Subcontract Work Order", name)


def _move(doc, status, **extra):
	doc.flags.workflow_move = True
	doc.db_set("status", status, update_modified=True)
	for k, v in extra.items():
		doc.db_set(k, v)
	doc.add_comment("Info", _("Status: {0}").format(status))
	doc.status = status
	return status


@frappe.whitelist()
def submit_for_approval(name):
	sc.require_role(sc.MANAGER, sc.EXECUTIVE)
	doc = _get(name)
	if doc.docstatus != 0 or doc.status != "Draft":
		frappe.throw(_("Only a Draft work order can be sent for approval"))
	doc.check_permission("write")
	doc.flags.workflow_move = True
	doc.validate()
	doc.check_availability(strict=True)
	return _move(doc, "Pending Approval")


@frappe.whitelist()
def approve(name):
	sc.require_role(sc.MANAGER)
	doc = _get(name)
	if doc.docstatus != 0 or doc.status != "Pending Approval":
		frappe.throw(_("Only a work order that is Pending Approval can be approved"))
	doc.flags.approving = True
	doc.flags.workflow_move = True
	doc.submit()
	return doc.status


@frappe.whitelist()
def reject(name, reason=None):
	sc.require_role(sc.MANAGER)
	doc = _get(name)
	if doc.docstatus != 0 or doc.status != "Pending Approval":
		frappe.throw(_("Only a work order that is Pending Approval can be returned to Draft"))
	if reason:
		doc.add_comment("Comment", _("Returned to Draft: {0}").format(reason))
	return _move(doc, "Draft")


@frappe.whitelist()
def start_work(name):
	sc.require_role(sc.MANAGER, sc.SITE_ENGINEER)
	doc = _get(name)
	if doc.docstatus != 1 or doc.status != "Approved":
		frappe.throw(_("Work starts only on an Approved work order"))
	return _move(doc, "Work In Progress")


@frappe.whitelist()
def submit_for_final_verification(name):
	sc.require_role(sc.MANAGER, sc.SITE_ENGINEER)
	frappe.throw(_("Certify completion with a Subcontract Completion Report; it sends the work order for final verification"))


@frappe.whitelist()
def verify_completion(name):
	sc.require_role(sc.MANAGER)
	doc = _get(name)
	if doc.docstatus != 1 or doc.status != "Pending Final Verification":
		frappe.throw(_("Final verification applies to a work order that is Pending Final Verification"))
	if not frappe.db.exists("Subcontract Completion Report", {"subcontract_work_order": name, "docstatus": 1}):
		frappe.throw(_("No certified Completion Report"))
	left = [r for r, b in sc.issued_balance(name).items() if b.outstanding > 1e-9]
	if left:
		frappe.throw(_("Material is still with the subcontractor: {0}. Reconcile it with a Material Return first").format(", ".join(left)))
	return _move(doc, "Verified", verified_by=frappe.session.user, verified_on=now_datetime())


@frappe.whitelist()
def close(name):
	sc.require_role(sc.MANAGER)
	doc = _get(name)
	if doc.docstatus != 1 or doc.status != "Verified":
		frappe.throw(_("Only a Verified work order can be closed"))
	return _move(doc, "Closed")


@frappe.whitelist()
def make_purchase_order(name):
	"""The commercial order for the work, a standard Purchase Order. Invoicing still runs through Subcontract Settlement."""
	sc.require_role(sc.MANAGER, "Purchase Manager")
	doc = _get(name)
	if doc.docstatus != 1:
		frappe.throw(_("Approve the work order first"))
	if doc.purchase_order and frappe.db.get_value("Purchase Order", doc.purchase_order, "docstatus") != 2:
		frappe.throw(_("Purchase Order {0} already exists").format(doc.purchase_order))
	po = frappe.new_doc("Purchase Order")
	po.update({"company": doc.company, "supplier": doc.supplier, "transaction_date": nowdate(), "schedule_date": doc.expected_completion_date or nowdate(),
		"currency": doc.currency, "project": doc.project, "cost_center": doc.cost_center, "subcontract_work_order": doc.name})
	if doc.taxes_and_charges:
		po.taxes_and_charges = doc.taxes_and_charges
	for r in doc.items:
		po.append("items", {"item_code": r.job_type, "qty": r.qty, "rate": r.rate, "schedule_date": doc.expected_completion_date or nowdate(),
			"project": doc.project, "cost_center": doc.cost_center})
	po.flags.ignore_permissions = True
	po.insert()
	doc.db_set("purchase_order", po.name)
	return po.name


@frappe.whitelist()
def make_advance_payment(name, amount, mode_of_payment=None):
	"""Draft advance Payment Entry for Accounts to review and submit; limited to the advance agreed on the work order."""
	sc.require_role(*sc.ACCOUNTS, sc.MANAGER)
	from erpnext.accounts.party import get_party_account

	doc = _get(name)
	if doc.docstatus != 1:
		frappe.throw(_("Approve the work order first"))
	if not doc.advance_amount:
		frappe.throw(_("No advance is agreed on this work order"))
	pe = frappe.new_doc("Payment Entry")
	pe.update({"payment_type": "Pay", "party_type": "Supplier", "party": doc.supplier, "company": doc.company, "posting_date": nowdate(),
		"mode_of_payment": mode_of_payment, "paid_amount": flt(amount), "received_amount": flt(amount), "subcontract_work_order": doc.name,
		"project": doc.project, "cost_center": doc.cost_center,
		"paid_to": get_party_account("Supplier", doc.supplier, doc.company)})
	paid_from = None
	if mode_of_payment:
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account
		paid_from = (get_bank_cash_account(mode_of_payment, doc.company) or {}).get("account")
	paid_from = paid_from or frappe.db.get_value("Company", doc.company, "default_bank_account") or frappe.db.get_value("Company", doc.company, "default_cash_account")
	if not paid_from:
		frappe.throw(_("Choose a Mode of Payment, or set a default bank or cash account on Company {0}").format(doc.company))
	pe.paid_from = paid_from
	pe.paid_from_account_currency = pe.paid_to_account_currency = frappe.db.get_value("Account", paid_from, "account_currency")
	pe.source_exchange_rate = pe.target_exchange_rate = 1
	pe.flags.ignore_permissions = True
	pe.insert()
	return pe.name
