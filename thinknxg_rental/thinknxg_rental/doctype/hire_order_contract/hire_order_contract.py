import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate, nowdate

from thinknxg_rental.events.item import get_job_type_items
from thinknxg_rental.services.utils import get_available_qty, get_contract_for_source, get_settings


class HireOrderContract(Document):
	"""Job type rental: a job (a non-stock Job Type Item) is hired for a fixed number of days at a
	contract charge, with an excess charge beyond them. Independent of Hire Order. The actual
	duration is controlled by the Job Completion Report (JCR)."""

	def validate(self):
		if self.rental_site and frappe.db.get_value("Rental Site", self.rental_site, "customer") != self.customer:
			frappe.throw(_("Rental Site {0} does not belong to customer {1}").format(self.rental_site, self.customer))
		self.validate_jobs()
		if not self.materials:
			self.explode_materials()
		self.validate_materials()

	def validate_jobs(self):
		seen = set()
		self.total_jobs = self.total_contract_amount = 0
		for d in self.items:
			item = frappe.get_cached_value("Item", d.job_type, ["nxg_is_job_type_item", "is_stock_item"], as_dict=True)
			if not cint(item.nxg_is_job_type_item) or cint(item.is_stock_item):
				frappe.throw(_("Row #{0}: {1} is not a Job Type Item (non-stock, Is Job Type Item ticked)").format(d.idx, frappe.bold(d.job_type)))
			key = (d.job_type, (d.location or "").strip().lower())
			if key in seen:
				frappe.throw(_("Row #{0}: {1} is entered twice for the same location. Raise the number of jobs instead.").format(d.idx, d.job_type))
			seen.add(key)
			if flt(d.qty) <= 0:
				frappe.throw(_("Row #{0}: No. of Jobs must be greater than zero").format(d.idx))
			if cint(d.included_days) < 1:
				frappe.throw(_("Row #{0}: Included Contract Days must be at least 1").format(d.idx))
			d.contract_amount = flt(d.qty) * flt(d.contract_rate)
			if self.docstatus == 0:
				d.jcr_qty = 0
			self.total_jobs += flt(d.qty)
			self.total_contract_amount += d.contract_amount

	def explode_materials(self):
		"""Job type -> its rental items -> physical stock items, multiplied by the number of jobs."""
		self.set("materials", [])
		for d in self.items:
			for c in get_job_type_items(d.job_type):
				self.append(
					"materials",
					{
						"job_type": d.job_type,
						"item_code": c.item_code,
						"item_name": c.item_name,
						"uom": c.uom,
						"qty_per_job": c.qty,
						"qty": flt(c.qty) * flt(d.qty),
					},
				)

	def validate_materials(self):
		if not self.materials:
			frappe.throw(_("No physical rental items. Add Job Type Rental Items to the job type item, or enter the materials."))
		yard = get_settings().rental_yard_warehouse
		totals = {}
		for m in self.materials:
			if not frappe.get_cached_value("Item", m.item_code, "is_stock_item"):
				frappe.throw(_("Materials row #{0}: {1} is not a stock item").format(m.idx, frappe.bold(m.item_code)))
			if flt(m.qty) <= 0:
				frappe.throw(_("Materials row #{0}: Total Qty must be greater than zero").format(m.idx))
			totals[m.item_code] = totals.get(m.item_code, 0) + flt(m.qty)
		if self.docstatus == 0:
			left = {k: max(get_available_qty(k, yard), 0) if yard else 0 for k in totals}
			for m in self.materials:
				m.available_qty = left[m.item_code]
				m.shortfall_qty = max(flt(m.qty) - left[m.item_code], 0)
				left[m.item_code] = max(left[m.item_code] - flt(m.qty), 0)

	def get_material_totals(self):
		"""{item_code: total qty} across every job on this contract."""
		totals = {}
		for m in self.materials:
			totals[m.item_code] = totals.get(m.item_code, 0) + flt(m.qty)
		return totals

	@frappe.whitelist()
	def refresh_materials(self):
		"""Re-explode the job types, discarding manual changes to the materials table."""
		self.check_permission("write")
		if self.docstatus != 0:
			frappe.throw(_("Materials can only be rebuilt on a draft"))
		self.validate_jobs()
		self.explode_materials()
		self.save()

	def on_submit(self):
		self.db_set("status", "Open")

	def on_cancel(self):
		self.db_set("status", "Cancelled")


def _source(source_name):
	doc = frappe.get_doc("Hire Order Contract", source_name)
	doc.check_permission("read")
	if doc.docstatus != 1:
		frappe.throw(_("Hire Order Contract {0} is not submitted").format(source_name))
	return doc


@frappe.whitelist()
def make_rental_contract(source_name: str, target_doc=None):
	"""The Rental Contract is the common rental account; its items are the exploded physical materials."""
	source = _source(source_name)
	if get_contract_for_source("Hire Order Contract", source.name):
		frappe.throw(_("Hire Order Contract {0} already has a submitted Rental Contract").format(source.name))
	if not source.rental_site:
		frappe.throw(_("Set the Rental Site on the Hire Order Contract first"))
	settings = get_settings()
	start = getdate(source.required_from)
	longest = max(cint(d.included_days) for d in source.items)
	target = frappe.new_doc("Rental Contract")
	target.update(
		{
			"company": source.company,
			"customer": source.customer,
			"rental_site": source.rental_site,
			"source_type": "Hire Order Contract",
			"source_document": source.name,
			"contract_type": "Job Type Contract",
			"contract_date": source.order_date,
			"start_date": start,
			"end_date": add_days(start, longest - 1),
			"grace_days": cint(settings.default_grace_days),
			"billing_cycle": "Monthly",
			"taxes_and_charges": source.taxes_and_charges,
			"payment_terms_template": source.payment_terms_template,
			"cost_center": source.cost_center,
			"terms": source.terms,
		}
	)
	for item_code, qty in source.get_material_totals().items():
		target.append("items", {"item_code": item_code, "qty": qty, "rate_basis": "Monthly", "rate": 0})
	return target


@frappe.whitelist()
def make_reservation(source_name: str, target_doc=None):
	"""Reserve the physical stock items, never the non-stock job type."""
	from thinknxg_rental.thinknxg_rental.doctype.rental_material_reservation.rental_material_reservation import get_source_items

	source = _source(source_name)
	data = get_source_items("Hire Order Contract", source.name)
	target = frappe.new_doc("Rental Material Reservation")
	target.update(
		{
			"company": source.company,
			"customer": source.customer,
			"rental_site": source.rental_site,
			"rental_contract": data["rental_contract"],
			"source_type": "Hire Order Contract",
			"source_document": source.name,
			"reservation_date": nowdate(),
			"required_from": source.required_from,
			"source_warehouse": get_settings().rental_yard_warehouse,
		}
	)
	for row in data["items"]:
		target.append("items", row)
	if not target.items:
		frappe.throw(_("Everything on this contract has already been dispatched"))
	return target


def get_open_job_lines(doc):
	"""Job lines of a Hire Order Contract that still have jobs without a JCR."""
	from thinknxg_rental.thinknxg_rental.doctype.job_completion_report.job_completion_report import get_reported_qty

	# counted from the submitted JCRs themselves, never from a stored counter (a duplicated or
	# amended contract would otherwise inherit the old one)
	reported = get_reported_qty(doc.name)
	return [
		frappe._dict(
			idx=d.idx, name=d.name, job_type=d.job_type, job_type_name=d.job_type_name, location=d.location, qty=flt(d.qty),
			remaining=flt(d.qty) - flt(reported.get(d.name)), included_days=cint(d.included_days),
			contract_rate=flt(d.contract_rate), excess_rate_basis=d.excess_rate_basis, excess_rate=flt(d.excess_rate),
		)
		for d in doc.items
		if flt(d.qty) - flt(reported.get(d.name)) > 1e-6
	]


@frappe.whitelist()
def get_job_lines(hire_order_contract: str):
	"""For the JCR form: every job line with jobs still to report, and the contract's billing choice."""
	doc = _source(hire_order_contract)
	return {
		"lines": get_open_job_lines(doc),
		"contract_charge_billing": doc.contract_charge_billing,
		"company": doc.company,
		"rental_contract": get_contract_for_source("Hire Order Contract", doc.name),
	}


@frappe.whitelist()
def make_jcr(source_name: str, target_doc=None, args=None):
    """Create one JCR containing every still-unreported job line on the Hire Order Contract.
    Each child row can later carry its own erection/dismantle date."""
    source = _source(source_name)
    lines = get_open_job_lines(source)
    if not lines:
        frappe.throw(_("Every job on this contract already has a Job Completion Report"))
    target = frappe.new_doc("Job Completion Report")
    target.update({"company":source.company,"hire_order_contract":source.name,"rental_contract":get_contract_for_source("Hire Order Contract",source.name),"customer":source.customer,"rental_site":source.rental_site})
    for line in lines:
        target.append("job_lines",{
            "contract_item":line.name,"job_type":line.job_type,"job_type_name":line.job_type_name,"location":line.location,
            "job_qty":line.remaining,"erection_date":nowdate(),"included_days":line.included_days,
            "contract_end_date":add_days(nowdate(),max(line.included_days,1)-1),"contract_rate":line.contract_rate,
            "contract_charge_billing":source.contract_charge_billing,"excess_rate_basis":line.excess_rate_basis,
            "excess_rate":line.excess_rate,"status":"Draft"
        })
    return target

