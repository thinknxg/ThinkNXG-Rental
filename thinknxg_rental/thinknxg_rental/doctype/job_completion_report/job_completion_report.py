import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, date_diff, flt, getdate, nowdate

from thinknxg_rental.services import jcr_billing
from thinknxg_rental.services.utils import get_contract_for_source


class JobCompletionReport(Document):
	"""JCR: records when a job was erected and when it was dismantled. The erection date starts
	the contract clock; days beyond the included contract days are excess and are billed from here."""

	def validate(self):
		hoc = frappe.get_doc("Hire Order Contract", self.hire_order_contract)
		if hoc.docstatus != 1:
			frappe.throw(_("Hire Order Contract {0} is not submitted").format(hoc.name))
		self.company = self.company or hoc.company
		self.rental_contract = get_contract_for_source("Hire Order Contract", hoc.name)
		line = self.get_job_line(hoc)
		self.included_days = cint(line.included_days)
		self.contract_rate = flt(line.contract_rate)
		self.excess_rate_basis = line.excess_rate_basis
		self.excess_rate = flt(line.excess_rate)
		self.contract_charge_billing = hoc.contract_charge_billing
		self.location = self.location or line.location
		if flt(self.job_qty) <= 0:
			frappe.throw(_("No. of Jobs must be greater than zero"))
		others = get_reported_qty(hoc.name, exclude=self.name).get(line.name, 0)
		if flt(others) + flt(self.job_qty) > flt(line.qty) + 1e-6:
			where = f" ({line.location})" if line.location else ""
			frappe.throw(
				_("{0}{1}: {2} on the contract line, {3} already on other JCRs, so at most {4} can go on this one.").format(
					frappe.bold(self.job_type), where, flt(line.qty), flt(others), flt(line.qty) - flt(others)
				)
			)
		self.set_duration()

	def get_job_line(self, hoc):
		"""The Hire Order Contract job line this JCR reports on. A contract can carry several job
		types, and the same job type at several locations; each line has its own terms."""
		lines = [d for d in hoc.items if d.job_type == self.job_type]
		if not lines:
			frappe.throw(_("{0} is not a job type on Hire Order Contract {1}").format(frappe.bold(self.job_type), hoc.name))
		line = next((d for d in lines if d.name == self.contract_item), None)
		if not line:
			reported = get_reported_qty(hoc.name, exclude=self.name)
			wanted = (self.location or "").strip().lower()
			line = (
				next((d for d in lines if wanted and (d.location or "").strip().lower() == wanted), None)
				or next((d for d in lines if flt(d.qty) - flt(reported.get(d.name)) > 1e-6), None)
				or lines[0]
			)
		self.contract_item = line.name
		return line

	def set_duration(self):
		self.contract_end_date = jcr_billing.get_contract_end(self.erection_date, self.included_days)
		if self.dismantle_date and getdate(self.dismantle_date) < getdate(self.erection_date):
			frappe.throw(_("Dismantle Date cannot be before the Erection Date"))
		upto = getdate(self.dismantle_date) if self.dismantle_date else max(getdate(nowdate()), getdate(self.erection_date))
		self.actual_days = date_diff(upto, self.erection_date) + 1
		self.excess_days = max(date_diff(upto, self.contract_end_date), 0)

	def before_update_after_submit(self):
		before = self.get_doc_before_save()
		if before and str(before.dismantle_date or "") != str(self.dismantle_date or ""):
			self.validate_dismantle_change(before)

	def validate_dismantle_change(self, before):
		if self.dismantle_date and getdate(self.dismantle_date) < getdate(self.erection_date):
			frappe.throw(_("Dismantle Date cannot be before the Erection Date"))
		billed_excess = [
			s for s in jcr_billing.get_schedules(self.name) if s.billing_type != "Contract" and (s.sales_invoice or s.status != "Pending")
		]
		if not billed_excess:
			return
		last = max(getdate(s.period_to) for s in billed_excess)
		if before.dismantle_date:
			frappe.throw(_("Excess is already billed up to {0}. Cancel those invoices and their JCR Billing Schedule rows before changing the dismantle date.").format(frappe.format(last, {"fieldtype": "Date"})))
		if self.dismantle_date and getdate(self.dismantle_date) <= last:
			frappe.throw(
				_("Excess is already billed up to {0}. Use a dismantle date after that, or cancel the later invoice and delete its JCR Billing Schedule row first.").format(
					frappe.format(last, {"fieldtype": "Date"})
				)
			)

	def on_submit(self):
		self.update_contract_jobs()
		jcr_billing.update_jcr_progress(self.name)
		jcr_billing.generate_jcr_billing(self.name)

	def on_update_after_submit(self):
		jcr_billing.update_jcr_progress(self.name)
		if self.dismantle_date:
			jcr_billing.generate_jcr_billing(self.name)

	def on_cancel(self):
		for s in jcr_billing.get_schedules(self.name):
			if s.sales_invoice:
				docstatus = frappe.db.get_value("Sales Invoice", s.sales_invoice, "docstatus")
				if docstatus == 1:
					frappe.throw(_("Cancel Sales Invoice {0} before cancelling this JCR").format(s.sales_invoice))
				if docstatus == 0:
					frappe.delete_doc("Sales Invoice", s.sales_invoice, ignore_permissions=True)
			frappe.delete_doc("JCR Billing Schedule", s.name, ignore_permissions=True, force=True)
		self.db_set("status", "Cancelled")
		self.update_contract_jobs()

	def update_contract_jobs(self):
		"""Show on each Hire Order Contract job line how many jobs have a JCR."""
		hoc = frappe.get_doc("Hire Order Contract", self.hire_order_contract)
		reported = get_reported_qty(hoc.name)
		for d in hoc.items:
			d.db_set("jcr_qty", flt(reported.get(d.name)), update_modified=False)

	@frappe.whitelist()
	def record_dismantle(self, dismantle_date: str, remarks: str | None = None):
		"""Stop the clock: sets the dismantle date and raises the final excess bill."""
		self.check_permission("write")
		if self.docstatus != 1:
			frappe.throw(_("Submit the JCR first"))
		self.dismantle_date = dismantle_date
		if remarks:
			self.remarks = remarks
		self.set_duration()
		self.flags.ignore_validate_update_after_submit = True
		self.save()


def get_reported_qty(hire_order_contract, exclude=None):
	"""{contract job line: jobs on submitted JCRs}."""
	return dict(
		frappe.db.sql(
			"""select contract_item, sum(job_qty) from `tabJob Completion Report`
			where docstatus = 1 and hire_order_contract = %s and name != %s and ifnull(contract_item, '') != ''
			group by contract_item""",
			(hire_order_contract, exclude or ""),
		)
	)
