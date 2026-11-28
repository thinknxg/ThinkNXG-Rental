import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from thinknxg_rental.services import subcontracting as sc
from thinknxg_rental.services.utils import as_system

EPS = 1e-9


class SubcontractSettlement(Document):
	"""Certified work becomes ONE standard Purchase Invoice. Retention, penalties, recoveries and other deductions are
	deduction rows on that invoice; advances are allocated with ERPNext's own advance mechanism; payment is a normal
	Payment Entry against the invoice. No separate ledger exists."""

	def validate(self):
		swo = frappe.db.get_value("Subcontract Work Order", self.subcontract_work_order,
			["docstatus", "status", "company", "supplier", "currency", "contract_amount", "approved_additional_cost", "retention_percentage", "hire_order_contract"], as_dict=True)
		if not swo or swo.docstatus != 1:
			frappe.throw(_("Subcontract Work Order {0} must be approved").format(self.subcontract_work_order))
		allowed = ("Verified",) if self.settlement_type == "Final" else sc.BILLABLE
		if swo.status not in allowed:
			frappe.throw(_("A {0} settlement needs the work order to be {1}; it is {2}").format(self.settlement_type, _(" or ").join(allowed), swo.status))
		self.company, self.supplier, self.hire_order_contract, self.currency = swo.company, swo.supplier, swo.hire_order_contract, swo.currency
		self.original_amount, self.additional_work = swo.contract_amount, swo.approved_additional_cost
		if self.retention_percentage is None or (self.is_new() and not flt(self.retention_percentage)):
			self.retention_percentage = swo.retention_percentage
		rows = {r.name: r for r in frappe.get_all("Subcontract Work Item", filters={"parent": self.subcontract_work_order},
			fields=["name", "job_type", "work_category", "accepted_qty", "invoiced_qty", "rate"])}
		total, any_qty = 0, False
		for r in self.items:
			src = rows.get(r.swo_item)
			if not src:
				frappe.throw(_("Row {0}: work item does not belong to {1}").format(r.idx, self.subcontract_work_order))
			r.job_type, r.work_category, r.accepted_qty, r.invoiced_qty, r.rate = src.job_type, src.work_category, flt(src.accepted_qty), flt(src.invoiced_qty), flt(src.rate)
			if flt(r.qty) < 0 or flt(r.qty) > r.accepted_qty - r.invoiced_qty + EPS:
				frappe.throw(_("Row {0}: invoice quantity {1} is more than the accepted, not yet invoiced quantity {2}").format(r.idx, r.qty, r.accepted_qty - r.invoiced_qty))
			r.amount = flt(r.qty) * r.rate
			total += r.amount
			any_qty = any_qty or flt(r.qty) > 0
		if not any_qty:
			frappe.throw(_("Nothing to invoice: no accepted work is waiting"))
		self.certified_value = total
		self.retention_amount = total * flt(self.retention_percentage) / 100
		if self.is_new() and not flt(self.damage_recovery):
			self.damage_recovery = min(sc.unsettled_recovery(self.subcontract_work_order), total - self.retention_amount)
		if flt(self.damage_recovery) > sc.unsettled_recovery(self.subcontract_work_order, self.name) + EPS:
			frappe.throw(_("Damage / loss recovery cannot exceed what the returns charged and earlier settlements have not already taken"))
		paid, rec = sc.advance_paid(self.subcontract_work_order, self.name)
		net = total - self.retention_amount - flt(self.penalties) - flt(self.damage_recovery) - flt(self.other_deductions)
		if net < -EPS:
			frappe.throw(_("Deductions are more than the certified value"))
		self.advance_recovery = max(min(paid - rec, net), 0) if self.docstatus == 0 else self.advance_recovery
		self.final_payable = net - flt(self.advance_recovery)
		self.previous_payments = flt(frappe.db.sql(
			"""select sum(r.allocated_amount) from `tabPayment Entry Reference` r join `tabPayment Entry` pe on pe.name = r.parent
			where pe.docstatus = 1 and pe.subcontract_work_order = %s and r.reference_doctype = 'Purchase Invoice'""", self.subcontract_work_order)[0][0])
		self.outstanding = self.final_payable

	def before_submit(self):
		sc.require_role(*sc.ACCOUNTS, sc.MANAGER) if self.settlement_type == "Partial" else sc.require_role("Accounts Manager")
		sc.lock_work_order(self.subcontract_work_order)
		self.validate()

	def on_submit(self):
		for r in self.items:
			frappe.db.sql("update `tabSubcontract Work Item` set invoiced_qty = ifnull(invoiced_qty, 0) + %s where name = %s", (flt(r.qty), r.swo_item))
		self.create_invoice()

	def create_invoice(self):
		swo = frappe.get_doc("Subcontract Work Order", self.subcontract_work_order)
		accounts = sc.settlement_accounts(self.company)
		pi = frappe.new_doc("Purchase Invoice")
		pi.update({"company": self.company, "supplier": self.supplier, "posting_date": self.posting_date,
			"bill_no": self.get("supplier_invoice_no") or None, "bill_date": self.get("supplier_invoice_date") or self.posting_date,
			"currency": self.currency, "subcontract_work_order": self.subcontract_work_order, "project": swo.project, "cost_center": swo.cost_center,
			"update_stock": 0, "remarks": _("Subcontract Settlement {0} for {1}").format(self.name, self.subcontract_work_order)})
		for r in self.items:
			if flt(r.qty) > 0:
				pi.append("items", {"item_code": r.job_type, "qty": r.qty, "rate": r.rate, "project": swo.project, "cost_center": swo.cost_center,
					"description": _("{0} ({1}) – {2}").format(r.job_type, r.work_category, self.subcontract_work_order)})
		if swo.taxes_and_charges:
			pi.taxes_and_charges = swo.taxes_and_charges
			pi.set_taxes()
		for amount, account, label in ((self.retention_amount, accounts["retention_account"], _("Retention held")),
				(self.penalties, accounts["recovery_account"], _("Penalties")),
				(self.damage_recovery, accounts["recovery_account"], _("Material damage / loss recovery")),
				(self.other_deductions, accounts["recovery_account"], _("Other deductions"))):
			if flt(amount) > 0:
				pi.append("taxes", {"category": "Total", "add_deduct_tax": "Deduct", "charge_type": "Actual", "account_head": account,
					"description": label, "tax_amount": flt(amount), "cost_center": swo.cost_center})
		pi.flags.from_settlement = True
		pi.flags.ignore_permissions = True
		with as_system():
			pi.insert()
			# advances: only payments made against THIS work order
			pi.calculate_taxes_and_totals()
			pi.set_advances()
			pi.advances = [a for a in pi.advances if frappe.db.get_value("Payment Entry", a.reference_name, "subcontract_work_order") == self.subcontract_work_order]
			pi.calculate_taxes_and_totals()
			pi.save()
			self.db_set("advance_recovery", flt(pi.total_advance))
			self.db_set("final_payable", flt(pi.grand_total) - flt(pi.total_advance) - 0)
			pi.submit()
		self.db_set({"purchase_invoice": pi.name, "outstanding": flt(pi.outstanding_amount)})

	def before_cancel(self):
		sc.require_role("Accounts Manager")
		sc.lock_work_order(self.subcontract_work_order)
		status = frappe.db.get_value("Subcontract Work Order", self.subcontract_work_order, "status")
		if status == "Closed":
			frappe.throw(_("The work order is closed"))
		if self.purchase_invoice and frappe.db.get_value("Purchase Invoice", self.purchase_invoice, "docstatus") == 1:
			pi = frappe.get_doc("Purchase Invoice", self.purchase_invoice)
			pi.flags.ignore_permissions = pi.flags.ignore_links = True
			with as_system():
				pi.cancel()

	def on_cancel(self):
		if self.get("invoice_submission"):
			# the verified submission no longer stands: its invoice number can be submitted again
			frappe.db.set_value("Subcontractor Invoice Submission", self.invoice_submission, "status", "Cancelled", update_modified=False)
		for r in self.items:
			frappe.db.sql("update `tabSubcontract Work Item` set invoiced_qty = greatest(ifnull(invoiced_qty, 0) - %s, 0) where name = %s", (flt(r.qty), r.swo_item))
