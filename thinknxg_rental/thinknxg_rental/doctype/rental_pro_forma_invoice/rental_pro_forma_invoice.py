"""Pro Forma Invoice: the preliminary commercial document sent before the tax invoice.

It confirms the material, quantities, rates and estimated rental period, the additional charges, the VAT that
the tax invoice is expected to carry (UAE or Oman, from the company's Rental Company Profile), and the
refundable security deposit, kept apart from rental revenue. It is never a tax invoice: approving it, sending
it or receiving money against it posts nothing to the accounts. Money received against it is a Rental Contract
Payment (advance or deposit, posted to liability accounts).

Status: Draft -> Submitted for Approval -> Approved (submit) -> Sent to Customer -> Customer Accepted ->
Advance Received -> Converted to Sales Invoice; Expired (valid-until passed before acceptance) and Cancelled.
Each change is logged in the Status History with who and when.

Conversion makes a Sales Invoice in the profile's tax invoice series. Its VAT is worked out again by the
profile's tax templates on the invoice date. Rental invoiced that way is credited on the contract's later
rental invoices (nxg_prepaid_credit), so the same days are never charged twice.
"""
import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import add_days, cint, date_diff, flt, formatdate, get_last_day, getdate, money_in_words, now_datetime, nowdate

from thinknxg_rental.services import vat
from thinknxg_rental.services.utils import BASIS_FACTOR, BASIS_UOM, as_system, billable_units, get_rental_rate, get_settings, require_setting

DOCTYPE = "Rental Pro Forma Invoice"
OPEN = ("Approved", "Sent to Customer", "Customer Accepted", "Advance Received")
CONVERTIBLE = OPEN
APPROVERS = ("Rental Manager", "Accounts Manager", "System Manager")
TRANSPORT = "Transportation"
EPS = 1e-9
# Lines taken from a Hire Order Contract: priced by the contract's job lines (jcr_billing.plan_periods), not by a rate basis
CONTRACT_CHARGE, EXCESS_CHARGE = "Contract Charge", "Excess Charge"
JOB_CHARGES = (CONTRACT_CHARGE, EXCESS_CHARGE)


class RentalProFormaInvoice(Document):
	def autoname(self):
		profile = vat.get_profile(self.company)
		self.naming_series = profile.proforma_naming_series
		self.name = make_autoname(self.naming_series, doc=self)

	def validate(self):
		self.set_profile()
		self.set_party_details()
		if getdate(self.valid_until) < getdate(self.posting_date):
			frappe.throw(_("Valid Until cannot be before the Pro Forma Invoice date"))
		self.calculate()
		if self.docstatus == 0 and self.status not in ("Draft", "Submitted for Approval"):
			self.status = "Draft"

	# ------------------------------------------------------------------ context
	def set_profile(self):
		profile = vat.get_profile(self.company)
		self.company_profile = profile.name
		self.vat_country = profile.country
		self.currency = profile.currency
		self.company_vat_number = profile.vat_registration_number
		notes = []
		if not vat.is_reviewed(profile):
			notes.append(_("The VAT treatment rules of {0} have not been reviewed by finance yet.").format(profile.country))
		overridden = [d for d in list(self.items) + list(self.charges) + list(self.deposits) if d.treatment_overridden]
		if overridden:
			notes.append(_("{0} line(s) have a VAT treatment set by hand: approval needs an Accounts Manager.").format(len(overridden)))
		self.vat_review_note = " ".join(notes)
		self._profile = profile

	def set_party_details(self):
		from frappe.contacts.doctype.address.address import get_address_display, get_default_address

		self.customer_name = frappe.db.get_value("Customer", self.customer, "customer_name")
		if self.rental_contract:
			c = frappe.db.get_value("Rental Contract", self.rental_contract, ["customer", "company", "hire_order", "rental_site", "project"], as_dict=True)
			if (c.customer, c.company) != (self.customer, self.company):
				frappe.throw(_("Rental Contract {0} is for another customer or company").format(self.rental_contract))
			self.hire_order = self.hire_order or c.hire_order
			self.rental_site, self.project = self.rental_site or c.rental_site, self.project or c.project
		if self.hire_order:
			h = frappe.db.get_value("Hire Order", self.hire_order, ["customer", "company", "quotation", "customer_reference"], as_dict=True)
			if (h.customer, h.company) != (self.customer, self.company):
				frappe.throw(_("Hire Order {0} is for another customer or company").format(self.hire_order))
			self.quotation = self.quotation or h.quotation
			self.customer_reference = self.customer_reference or h.customer_reference
		self.customer_address = self.customer_address or get_default_address("Customer", self.customer)
		self.address_display = get_address_display(self.customer_address) if self.customer_address else ""
		country, vat_number = vat.customer_context(self.customer, self.customer_address)
		self.customer_country = self.customer_country or country
		self.customer_vat_number = self.customer_vat_number or vat_number
		if self.contact_person:
			c = frappe.db.get_value("Contact", self.contact_person, ["first_name", "last_name", "mobile_no", "email_id"], as_dict=True) or {}
			self.contact_display = " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x)
			self.contact_mobile = self.contact_mobile or c.get("mobile_no")
			self.contact_email = self.contact_email or c.get("email_id")
		site_country = None
		if self.rental_site:
			site = frappe.db.get_value("Rental Site", self.rental_site, ["address", "location", "project", "site_name"], as_dict=True)
			self.project = self.project or site.project
			if site.address:
				self.site_address_display = get_address_display(site.address)
				site_country = frappe.db.get_value("Address", site.address, "country")
			else:
				self.site_address_display = "\n".join(x for x in (site.site_name, site.location) if x)
		self.equipment_country = self.equipment_country or site_country
		if not self.override_supply_scope:
			self.supply_scope = vat.supply_scope(self.vat_country, self.equipment_country, self.customer_country)
		self.place_of_supply = self.place_of_supply or self.equipment_country or self.customer_country or self.vat_country

	# ------------------------------------------------------------------ amounts
	def calculate(self):
		profile = self._profile
		precision = vat.precision_of(self.currency)
		rounding = get_settings().pro_forma_rounding or "Pro Rata"
		registered = bool(self.customer_vat_number)
		self.total_rental = self.total_transport = self.total_other_services = 0
		starts, ends = [], []
		for d in self.items:
			self.calculate_item(d, rounding, precision)
			self.total_rental += d.amount
			starts.append(getdate(d.rental_from))
			ends.append(getdate(d.rental_to))
		for d in self.charges:
			if flt(d.qty) <= 0:
				d.qty = 1
			d.amount = flt(flt(d.qty) * flt(d.rate), precision)
			d.description = d.description or _(d.charge_type)
			if d.charge_type == TRANSPORT:
				self.total_transport += d.amount
			else:
				self.total_other_services += d.amount
		self.rental_start_date = min(starts) if starts else None
		self.rental_end_date = max(ends) if ends else None
		self.rental_days = date_diff(self.rental_end_date, self.rental_start_date) + 1 if starts else 0
		self.subtotal = flt(self.total_rental + self.total_transport + self.total_other_services, precision)
		if flt(self.discount_percentage):
			self.discount_amount = flt(self.subtotal * flt(self.discount_percentage) / 100.0, precision)
		self.total_discount = min(flt(self.discount_amount, precision), self.subtotal)
		if self.total_discount < 0:
			frappe.throw(_("Discount cannot be negative"))
		self.net_total = flt(self.subtotal - self.total_discount, precision)
		# VAT per line on its share of the net (the discount spread by amount), the treatment from the profile
		buckets = {vat.STANDARD: 0.0, vat.ZERO: 0.0, vat.EXEMPT: 0.0, vat.OUT: 0.0}
		# the total VAT is rounded once, on the net of each rate, as the tax invoice works it out
		by_rate = {}
		factor = self.net_total / self.subtotal if self.subtotal else 0
		for d, category in [(d, vat.RENTAL) for d in self.items] + [(d, d.charge_type) for d in self.charges]:
			self.apply_treatment(d, category, registered, profile)
			net = flt(d.amount) * factor
			d.vat_amount = flt(net * flt(d.vat_rate) / 100.0, precision)
			buckets[d.vat_treatment] += net
			by_rate[flt(d.vat_rate)] = by_rate.get(flt(d.vat_rate), 0) + net
		self.total_vat = sum(flt(net * rate / 100.0, precision) for rate, net in by_rate.items())
		self.taxable_amount = flt(buckets[vat.STANDARD], precision)
		self.zero_rated_amount = flt(buckets[vat.ZERO], precision)
		self.exempt_amount = flt(buckets[vat.EXEMPT], precision)
		self.out_of_scope_amount = flt(buckets[vat.OUT], precision)
		self.total_vat = flt(self.total_vat, precision)
		self.total_including_vat = flt(self.net_total + self.total_vat, precision)
		# the deposit: its own section, never in the rental and service totals above
		self.total_deposit = self.deposit_vat = 0
		for d in self.deposits:
			if flt(d.basis_qty) <= 0:
				d.basis_qty = 1
			d.amount = flt(flt(d.basis_qty) * flt(d.rate), precision)
			self.apply_treatment(d, vat.DEPOSIT, registered, profile)
			d.vat_amount = flt(d.amount * flt(d.vat_rate) / 100.0, precision)
			self.total_deposit += d.amount
			self.deposit_vat += d.vat_amount
		self.total_deposit = flt(self.total_deposit, precision)
		self.deposit_vat = flt(self.deposit_vat, precision)
		self.set_payable(precision)

	def set_payable(self, precision=None):
		precision = precision or vat.precision_of(self.currency)
		charges_due = max(flt(self.total_including_vat) - flt(self.advance_received), 0)
		deposit_due = max(flt(self.total_deposit) + flt(self.deposit_vat) - flt(self.deposit_received), 0)
		self.grand_total_payable = flt(charges_due + deposit_due, precision)
		self.in_words = money_in_words(self.grand_total_payable, self.currency)

	def calculate_item(self, d, rounding, precision):
		if not d.item_code:
			return
		item = frappe.get_cached_value("Item", d.item_code, ["item_name", "description", "stock_uom"], as_dict=True)
		d.item_name = d.item_name or item.item_name
		d.description = d.description or item.description or item.item_name
		d.uom = d.uom or item.stock_uom
		d.rate_basis = d.rate_basis or "Monthly"
		if flt(d.qty) <= 0:
			frappe.throw(_("Row #{0}: Quantity must be greater than zero").format(d.idx))
		if not d.rental_from or not d.rental_to or getdate(d.rental_to) < getdate(d.rental_from):
			frappe.throw(_("Row #{0}: set the rental period (Rental To on or after Rental From)").format(d.idx))
		if d.charge_type in JOB_CHARGES:
			# Contract Charge: qty = jobs, rate = contract rate for the whole contract period.
			# Excess Charge: qty = job-days (weeks, months) of the period, rate = the excess rate. Exact, nothing re-derived.
			if flt(d.rate) <= 0:
				frappe.throw(_("Row #{0}: {1} has no rate. Set it on the Hire Order Contract job line").format(d.idx, _(d.charge_type)))
			d.rental_days = date_diff(d.rental_to, d.rental_from) + 1
			d.billable_periods = 1
			d.amount = flt(flt(d.qty) * flt(d.rate), precision)
			d.period_label = _("{0} day(s)").format(d.rental_days)
			return
		if d.rate_basis == "Custom" and cint(d.period_days) <= 0:
			frappe.throw(_("Row #{0}: a Custom rate needs the number of days the rate covers").format(d.idx))
		if not flt(d.rate):
			d.rate = default_rate(d.item_code, d.rate_basis, self.customer, self.posting_date, d.period_days)
		d.rental_days = date_diff(d.rental_to, d.rental_from) + 1
		days = max(d.rental_days, cint(d.minimum_days))
		d.billable_periods = flt(periods(d.rate_basis, d.rental_from, days, d.period_days, rounding), 4)
		d.amount = flt(flt(d.qty) * flt(d.rate) * d.billable_periods, precision)
		unit = {"Daily": _("day(s)"), "Weekly": _("week(s)"), "Monthly": _("month(s)")}.get(d.rate_basis) or _("period(s) of {0} days").format(d.period_days)
		label = f"{_fmt(d.billable_periods)} {unit}"
		if days != d.rental_days:
			label += " " + _("(minimum {0} days)").format(days)
		d.period_label = label

	def apply_treatment(self, d, category, registered, profile):
		if d.treatment_overridden and d.vat_treatment:
			d.vat_rate = vat.rate_for(profile, d.vat_treatment, d.vat_rate)
			return
		d.vat_treatment, d.vat_rate, _remarks = vat.resolve(profile, category, self.supply_scope, registered)

	# ------------------------------------------------------------------ workflow
	def before_submit(self):
		roles = set(frappe.get_roles())
		if not roles & set(APPROVERS):
			frappe.throw(_("A Rental Manager or Accounts Manager approves a pro forma invoice"), frappe.PermissionError)
		if any(d.treatment_overridden for d in list(self.items) + list(self.charges) + list(self.deposits)) and not roles & {"Accounts Manager", "System Manager"}:
			frappe.throw(_("VAT treatment was set by hand on some lines: an Accounts Manager approves this pro forma invoice"),
				frappe.PermissionError, title=_("Finance Review Needed"))
		self.approved_by, self.approved_on = frappe.session.user, now_datetime()
		self.status = "Approved"

	def on_submit(self):
		self.log("Approved")
		# deposits and advances already taken on its contract or hire order are counted from now on
		from thinknxg_rental.services import deposits

		if deposits.claim_collections(self.name):
			refresh_payments(self.name)

	def before_cancel(self):
		if self.sales_invoice and frappe.db.get_value("Sales Invoice", self.sales_invoice, "docstatus") != 2:
			frappe.throw(_("Cancel Sales Invoice {0} first").format(self.sales_invoice))
		# money held only by this pro forma invoice (no contract or hire order to keep it) must be refunded first
		posted = frappe.get_all("Rental Contract Payment", filters={"pro_forma_invoice": self.name, "docstatus": 1,
			"rental_contract": ["in", ("", None)], "hire_order": ["in", ("", None)]}, pluck="name")
		if posted:
			frappe.throw(_("Deposits or advances are posted against this pro forma invoice ({0}). Cancel or refund them first.").format(", ".join(posted)))

	def on_cancel(self):
		# the rest stays with its contract or hire order, no longer shown on this pro forma invoice
		frappe.db.sql("""update `tabRental Contract Payment` set pro_forma_invoice = null, pro_forma_linked_automatically = 0
			where pro_forma_invoice = %s""", self.name)
		self.db_set("status", "Cancelled")
		self.log("Cancelled")

	def log(self, status, remarks=None):
		row = frappe.get_doc({"doctype": "Rental Pro Forma Status Log", "parent": self.name, "parenttype": DOCTYPE, "parentfield": "status_log",
			"idx": len(self.get("status_log") or []) + 1, "status": status, "changed_on": now_datetime(), "changed_by": frappe.session.user,
			"remarks": remarks})
		row.db_insert()
		self.append("status_log", row)
		self.add_comment("Info", _("Status: {0}").format(_(status)) + (f" - {remarks}" if remarks else ""))

	def set_status(self, status, remarks=None, **values):
		self.db_set(dict(values, status=status))
		self.log(status, remarks)

	def on_update(self):
		if self.docstatus == 0:
			last = (self.get("status_log") or [None])[-1]
			if not last or last.status != self.status:
				self.log(self.status)

	@frappe.whitelist()
	def submit_for_approval(self):
		self.check_permission("write")
		if self.docstatus != 0:
			frappe.throw(_("Only a draft can be submitted for approval"))
		self.status = "Submitted for Approval"
		self.save()
		return self.status

	@frappe.whitelist()
	def mark_sent(self, via: str = "PDF", remarks: str | None = None):
		self.check_permission("write")
		self._require(("Approved", "Sent to Customer", "Customer Accepted", "Advance Received"), _("sent"))
		values = {"sent_on": now_datetime(), "sent_via": via}
		status = "Sent to Customer" if self.status == "Approved" else self.status
		self.set_status(status, remarks or _("Sent by {0}").format(via), **values)
		return self.status

	@frappe.whitelist()
	def send_email(self, recipients: str, subject: str | None = None, message: str | None = None):
		self.check_permission("email")
		self._require(OPEN, _("sent"))
		frappe.sendmail(
			recipients=[r.strip() for r in recipients.replace(";", ",").split(",") if r.strip()],
			subject=subject or _("Pro Forma Invoice {0}").format(self.name),
			message=message or _("Please find attached Pro Forma Invoice {0} for your confirmation.").format(self.name),
			attachments=[frappe.attach_print(DOCTYPE, self.name, print_format=DOCTYPE, file_name=self.name)],
			reference_doctype=DOCTYPE, reference_name=self.name,
		)
		return self.mark_sent("Email", _("Emailed to {0}").format(recipients))

	@frappe.whitelist()
	def whatsapp_message(self):
		self.check_permission("read")
		self._require(OPEN, _("shared"))
		fmt = lambda v: frappe.format(v, {"fieldtype": "Currency", "options": self.currency})
		text = _("Pro Forma Invoice {0} from {1}: rental and charges {2} including VAT; refundable security deposit {3}; "
			"amount payable {4}. Valid until {5}. This is not a VAT tax invoice.").format(self.name, self.company,
			fmt(self.total_including_vat), fmt(flt(self.total_deposit) + flt(self.deposit_vat)), fmt(self.grand_total_payable),
			formatdate(self.valid_until))
		mobile = "".join(c for c in (self.contact_mobile or "") if c.isdigit())
		return {"mobile": mobile, "text": text}

	@frappe.whitelist()
	def mark_accepted(self, accepted_by: str | None = None, remarks: str | None = None):
		self.check_permission("write")
		self._require(("Approved", "Sent to Customer", "Advance Received"), _("accepted"))
		if self.accepted_on:
			frappe.throw(_("Accepted already, by {0}").format(self.accepted_by))
		values = dict(accepted_on=now_datetime(), accepted_by=accepted_by or self.contact_display or self.customer_name, acceptance_remarks=remarks)
		if self.status == "Advance Received":  # money came first: record the acceptance, keep the status
			self.db_set(values)
			self.log("Customer Accepted", remarks)
		else:
			self.set_status("Customer Accepted", remarks, **values)
		return self.status

	def _require(self, allowed, what):
		if self.docstatus != 1 or self.status not in allowed:
			frappe.throw(_("A pro forma invoice in status {0} cannot be {1}").format(_(self.status), what))


# ------------------------------------------------------------------ calculation helpers
def periods(rate_basis, start, days, period_days=None, rounding="Pro Rata"):
	"""Billable periods for `days` days from `start`: days, weeks, months (Month Basis) or custom periods."""
	if days <= 0:
		return 0.0
	if rate_basis == "Custom":
		value = days / float(max(cint(period_days), 1))
	else:
		value = billable_units(1, start, add_days(start, days - 1), rate_basis)
	if rounding == "Round Up to Whole Period":
		value = math.ceil(value - 1e-6)
	return value


def default_rate(item_code, rate_basis, customer=None, posting_date=None, period_days=None):
	if rate_basis == "Custom":
		return flt(get_rental_rate(item_code, "Daily", customer, posting_date)) * max(cint(period_days), 1)
	return flt(get_rental_rate(item_code, rate_basis, customer, posting_date))


def _fmt(value):
	value = flt(value, 4)
	return str(int(value)) if value == int(value) else f"{value:.4f}".rstrip("0").rstrip(".")


# ------------------------------------------------------------------ payments, conversion, expiry
def refresh_payments(name):
	"""Advance and deposit received against the pro forma invoice (posted Rental Contract Payments)."""
	from thinknxg_rental.services import deposits

	doc = frappe.get_doc(DOCTYPE, name)
	rows = frappe.get_all("Rental Contract Payment", filters={"pro_forma_invoice": name, "docstatus": 1},
		fields=["name", "transaction_type", "amount", "vat_amount", "posting_date", "mode_of_payment", "reference_no", "currency",
			"rental_contract", "hire_order", "pro_forma_linked_automatically"], order_by="posting_date, creation")
	s = deposits.summarize([frappe._dict(r) for r in rows])
	# Payments Received: one row per receipt counted here
	frappe.db.delete("Rental Pro Forma Payment", {"parent": name, "parenttype": DOCTYPE, "parentfield": "payments"})
	for i, r in enumerate(rows, 1):
		frappe.get_doc({"doctype": "Rental Pro Forma Payment", "parent": name, "parenttype": DOCTYPE, "parentfield": "payments", "idx": i,
			"payment": r.name, "posting_date": r.posting_date, "transaction_type": r.transaction_type,
			"amount": -flt(r.amount) if r.transaction_type in (deposits.D_REFUND, deposits.A_REFUND) else flt(r.amount),
			"mode_of_payment": r.mode_of_payment, "reference_no": r.reference_no, "currency": r.currency,
			"collected_on": (_("Rental Contract {0}").format(r.rental_contract) if r.rental_contract else _("Hire Order {0}").format(r.hire_order))
				if r.pro_forma_linked_automatically else _("This Pro Forma Invoice")}).db_insert()
	doc.advance_received = flt(s.advance_received - s.advance_refunded)
	doc.advance_vat_included = flt(s.advance_vat_held)
	doc.deposit_received = flt(s.deposit_collected - s.deposit_refunded)
	doc.set_payable()
	values = {k: doc.get(k) for k in ("advance_received", "advance_vat_included", "deposit_received", "grand_total_payable", "in_words")}
	if doc.docstatus == 1 and doc.status in ("Approved", "Sent to Customer", "Customer Accepted") and doc.advance_received > 0:
		doc.set_status("Advance Received", None, **values)
	else:
		doc.db_set(values)


@frappe.whitelist()
def make_sales_invoice(source_name: str):
	"""The VAT tax invoice for an approved pro forma invoice, in the company's tax invoice series."""
	pi = frappe.get_doc(DOCTYPE, source_name)
	pi.check_permission("read")
	frappe.has_permission("Sales Invoice", "create", throw=True)
	frappe.db.sql(f"select name from `tab{DOCTYPE}` where name = %s for update", source_name)
	pi.reload()
	if any(d.charge_type in JOB_CHARGES for d in pi.items):
		frappe.throw(_("Contract and excess charges of a Hire Order Contract are invoiced from its Job Completion Reports (Create Invoice), which keeps each billing period once. This pro forma invoice is the preliminary document for them."), title=_("Invoice from the Job Completion Report"))
	if pi.docstatus != 1 or pi.status not in CONVERTIBLE:
		frappe.throw(_("Only an approved pro forma invoice (not expired, cancelled or converted) becomes a tax invoice. Status: {0}").format(_(pi.status)))
	if pi.sales_invoice and frappe.db.get_value("Sales Invoice", pi.sales_invoice, "docstatus") != 2:
		frappe.throw(_("Sales Invoice {0} has already been made from this pro forma invoice").format(pi.sales_invoice), title=_("Already Converted"))
	profile = vat.get_profile(pi.company)
	settings = get_settings()
	charge_item = require_setting("rental_charge_item")
	contract = frappe.db.get_value("Rental Contract", pi.rental_contract, ["cost_center", "taxes_and_charges", "payment_terms_template"],
		as_dict=True) if pi.rental_contract else frappe._dict()

	si = frappe.new_doc("Sales Invoice")
	if profile.tax_invoice_naming_series:
		si.naming_series = profile.tax_invoice_naming_series
	si.update({
		"company": pi.company, "customer": pi.customer, "currency": pi.currency, "posting_date": nowdate(),
		"set_posting_time": 0, "project": pi.project, "cost_center": contract.cost_center,
		"customer_address": pi.customer_address, "contact_person": pi.contact_person,
		"payment_terms_template": pi.payment_terms_template or contract.payment_terms_template,
		"po_no": pi.customer_reference, "nxg_rental_contract": pi.rental_contract, "nxg_pro_forma_invoice": pi.name,
		"remarks": _("Tax invoice for Pro Forma Invoice {0}").format(pi.name), "terms": pi.terms,
	})
	if pi.customer_vat_number and si.meta.has_field("tax_id"):
		si.tax_id = pi.customer_vat_number
	for d in pi.items:
		uom = BASIS_UOM.get(d.rate_basis)
		si.append("items", {
			"item_code": charge_item, "item_name": d.item_name,
			"description": _("{0}: {1} {2} on hire {3} to {4} ({5})").format(d.item_name, _fmt(d.qty), d.uom or "",
				formatdate(d.rental_from), formatdate(d.rental_to), d.period_label),
			"qty": flt(flt(d.qty) * flt(d.billable_periods), 4),
			"uom": uom or "Charge", "conversion_factor": BASIS_FACTOR.get(d.rate_basis, 1) if uom else 1,
			"rate": flt(d.rate), "project": pi.project, "cost_center": contract.cost_center,
			"item_tax_template": vat.item_tax_template(profile, d.vat_treatment),
			"nxg_hire_item": d.item_code, "nxg_hire_from": d.rental_from, "nxg_hire_to": d.rental_to,
			"nxg_hire_days": d.rental_days, "nxg_hire_qty": d.qty,
		})
	for d in pi.charges:
		item = d.item_code or settings.service_charge_item or require_setting("service_charge_item")
		si.append("items", {
			"item_code": item, "item_name": _(d.charge_type), "description": d.description or _(d.charge_type),
			"qty": flt(d.qty) or 1, "uom": "Charge" if not d.item_code else None, "rate": flt(d.rate), "project": pi.project,
			"cost_center": contract.cost_center, "item_tax_template": vat.item_tax_template(profile, d.vat_treatment),
		})
	if flt(pi.total_discount):
		si.apply_discount_on = "Net Total"
		si.discount_amount = flt(pi.total_discount)
	taxes = profile.sales_taxes_template or contract.taxes_and_charges
	if taxes:
		from thinknxg_rental.services.billing import append_taxes

		append_taxes(si, "Sales Taxes and Charges Template", taxes)
	si.flags.ignore_permissions = True
	with as_system():
		si.insert()
	pi.db_set("sales_invoice", si.name)
	pi.log(pi.status, _("Tax invoice {0} drafted").format(si.name))
	return si.name


def sales_invoice_submitted(si):
	if si.get("nxg_pro_forma_invoice") and not si.is_return:
		pi = frappe.get_doc(DOCTYPE, si.nxg_pro_forma_invoice)
		pi.set_status("Converted to Sales Invoice", _("Tax invoice {0}").format(si.name), sales_invoice=si.name)


def sales_invoice_removed(si):
	"""Tax invoice cancelled or deleted: the pro forma invoice can be converted again."""
	name = si.get("nxg_pro_forma_invoice")
	if not name or frappe.db.get_value(DOCTYPE, name, "sales_invoice") != si.name:
		return
	pi = frappe.get_doc(DOCTYPE, name)
	previous = next((r.status for r in reversed(pi.status_log) if r.status in OPEN), "Approved")
	if pi.status == "Converted to Sales Invoice":
		pi.set_status(previous, _("Tax invoice {0} cancelled").format(si.name), sales_invoice=None)
	else:
		pi.db_set("sales_invoice", None)


def prepaid_rental(rental_contract):
	"""Rental already charged on tax invoices made from pro forma invoices of the contract (or its hire order),
	less what later rental invoices have credited."""
	ho = frappe.db.get_value("Rental Contract", rental_contract, "hire_order")
	pis = frappe.get_all(DOCTYPE, filters={"docstatus": 1, "rental_contract": rental_contract}, pluck="name")
	if ho:
		pis += frappe.get_all(DOCTYPE, filters={"docstatus": 1, "hire_order": ho, "rental_contract": ["in", ("", None)]}, pluck="name")
	if not pis:
		return 0.0
	charged = frappe.db.sql("""select ifnull(sum(it.net_amount), 0) from `tabSales Invoice Item` it
		inner join `tabSales Invoice` si on si.name = it.parent
		where si.docstatus = 1 and si.is_return = 0 and si.nxg_pro_forma_invoice in %s and ifnull(it.nxg_hire_item, '') != ''""",
		(tuple(pis),))[0][0]
	credited = frappe.db.sql("""select ifnull(sum(nxg_prepaid_credit), 0) from `tabSales Invoice`
		where docstatus < 2 and nxg_rental_contract = %s and ifnull(nxg_pro_forma_invoice, '') = ''""", rental_contract)[0][0]
	return max(flt(charged) - flt(credited), 0)


def expire():
	"""Scheduler (daily): pro forma invoices not accepted by their valid-until date expire."""
	for name in frappe.get_all(DOCTYPE, filters={"docstatus": 1, "status": ["in", ("Approved", "Sent to Customer")],
			"valid_until": ["<", nowdate()]}, pluck="name"):
		frappe.get_doc(DOCTYPE, name).set_status("Expired", _("Valid until date passed"))
	for name in frappe.get_all(DOCTYPE, filters={"docstatus": 0, "valid_until": ["<", nowdate()],
			"status": ["in", ("Draft", "Submitted for Approval")]}, pluck="name"):
		frappe.db.set_value(DOCTYPE, name, "status", "Expired")


# ------------------------------------------------------------------ made from other documents
def _new(company, customer, **values):
	settings = get_settings()
	doc = frappe.new_doc(DOCTYPE)
	doc.update(dict(company=company, customer=customer, posting_date=nowdate(),
		valid_until=add_days(nowdate(), cint(settings.pro_forma_validity_days) or 15), **values))
	terms = settings.pro_forma_terms
	if terms:
		doc.terms_template = terms
		doc.terms = frappe.db.get_value("Terms and Conditions", terms, "terms")
	return doc


@frappe.whitelist()
def make_from_hire_order(source_name: str):
	ho = frappe.get_doc("Hire Order", source_name)
	ho.check_permission("read")
	start = getdate(ho.required_from or nowdate())
	end = getdate(ho.expected_return_date) if ho.expected_return_date else add_days(start, max(cint(ho.expected_hire_days), 1) - 1)
	doc = _new(ho.company, ho.customer, hire_order=ho.name, quotation=ho.quotation, customer_reference=ho.customer_reference,
		rental_site=ho.rental_site, project=ho.project, payment_terms_template=ho.payment_terms_template,
		rental_contract=frappe.db.get_value("Rental Contract", {"hire_order": ho.name, "docstatus": 1}, "name"))
	for d in ho.items:
		days = cint(d.expected_hire_days) or (date_diff(end, start) + 1)
		doc.append("items", {"item_code": d.item_code, "item_name": d.item_name, "uom": d.uom, "qty": d.qty,
			"rate_basis": d.rate_basis or ho.rate_basis or "Monthly", "rate": d.rate, "rental_from": start,
			"rental_to": add_days(start, days - 1), "hire_order_item": d.name})
		if flt(d.security_deposit):
			doc.append("deposits", {"description": _("Security deposit: {0}").format(d.item_name), "item_code": d.item_code,
				"basis_qty": d.qty, "rate": d.security_deposit_rate, "deposit_type": "Refundable"})
	return doc


@frappe.whitelist()
def make_from_rental_contract(source_name: str):
	rc = frappe.get_doc("Rental Contract", source_name)
	rc.check_permission("read")
	if rc.get("hire_order_contract"):
		# a Job Type Contract bills its job lines, not material on hire
		return make_from_hire_order_contract(rc.hire_order_contract, rental_contract=rc.name)
	start = getdate(rc.start_date or nowdate())
	end = getdate(rc.end_date) if rc.end_date else add_days(start, 29)
	doc = _new(rc.company, rc.customer, rental_contract=rc.name, hire_order=rc.hire_order, rental_site=rc.rental_site,
		project=rc.project, payment_terms_template=rc.payment_terms_template)
	for d in rc.items:
		doc.append("items", {"item_code": d.item_code, "item_name": d.item_name, "uom": d.uom, "qty": d.qty,
			"rate_basis": d.rate_basis or "Monthly", "rate": d.rate, "rental_from": start, "rental_to": end,
			"minimum_days": rc.minimum_hire_days})
	if flt(rc.security_deposit):
		doc.append("deposits", {"description": _("Security deposit for the material on hire"), "basis_qty": 1,
			"rate": rc.security_deposit, "deposit_type": "Refundable"})
	return doc


@frappe.whitelist()
def make_from_hire_order_contract(source_name: str, bill_upto: str | None = None, rental_contract: str | None = None):
	"""Pro forma invoice of a Hire Order Contract: a Contract Charge line and, where days run past the contract, Excess Charge
	lines for every job line, as the Job Completion Report billing would invoice them up to `bill_upto` (month end by default)."""
	hoc = frappe.get_doc("Hire Order Contract", source_name)
	hoc.check_permission("read")
	if hoc.docstatus != 1:
		frappe.throw(_("Submit the Hire Order Contract first"))
	upto = getdate(bill_upto) if bill_upto else getdate(get_last_day(nowdate()))
	rental_contract = rental_contract or frappe.db.get_value("Rental Contract", {"hire_order_contract": hoc.name, "docstatus": 1}, "name")
	doc = _new(hoc.company, hoc.customer, hire_order_contract=hoc.name, rental_contract=rental_contract, quotation=hoc.quotation,
		customer_reference=hoc.customer_reference, rental_site=hoc.rental_site, project=hoc.project,
		payment_terms_template=hoc.payment_terms_template)
	rows, notes = contract_lines(hoc, upto)
	if not rows:
		frappe.throw(_("Nothing is left to put on a pro forma invoice up to {0}: every contract and excess period is already on a pro forma or tax invoice.").format(formatdate(upto))
			+ ("<br>" + "<br>".join(notes) if notes else ""))
	for r in rows:
		doc.append("items", r)
	if notes:
		doc.remarks = "\n".join(notes)
	return doc


def _free_stretches(start, end, done):
	"""[start, end] without the periods in `done`: the stretches nobody has billed yet."""
	out, cursor = [], getdate(start)
	for f, t in sorted(done):
		if t < cursor:
			continue
		if f > end:
			break
		if f > cursor:
			out.append((cursor, add_days(f, -1)))
		cursor = max(cursor, add_days(t, 1))
	if cursor <= end:
		out.append((cursor, end))
	return out


def _merge_stretches(pieces):
	"""Join back-to-back stretches with the same number of jobs, so a free stretch is one row whatever months it spans."""
	out = []
	for a, b, q in sorted(pieces):
		if out and abs(out[-1][2] - q) <= EPS and add_days(out[-1][1], 1) == a:
			out[-1] = (out[-1][0], b, q)
		else:
			out.append((a, b, q))
	return out


def _covered(hoc_name):
	"""{(line key, charge type): [(from, to)]} of periods already on a live pro forma or invoiced through the JCR billing."""
	out = {}
	# rows without a JCR line (jobs not yet reported) are keyed by their contract line
	for r in frappe.db.sql("""select if(ifnull(i.jcr_line, '') = '', i.hire_order_item, i.jcr_line) as k, i.charge_type, i.rental_from, i.rental_to
		from `tabRental Pro Forma Item` i join `tabRental Pro Forma Invoice` p on p.name = i.parent where p.hire_order_contract = %s
		and p.docstatus < 2 and p.status not in ('Expired', 'Cancelled') and i.charge_type in %s""", (hoc_name, JOB_CHARGES), as_dict=True):
		out.setdefault((r.k, r.charge_type), []).append((getdate(r.rental_from), getdate(r.rental_to)))
	for r in frappe.db.sql("""select jcr_line, billing_type, period_from, period_to from `tabJCR Billing Schedule`
		where hire_order_contract = %s and (ifnull(sales_invoice, '') != '' or status in ('Invoiced', 'No Charge'))""", hoc_name, as_dict=True):
		kind = CONTRACT_CHARGE if r.billing_type == "Contract" else EXCESS_CHARGE
		out.setdefault((r.jcr_line, kind), []).append((getdate(r.period_from), getdate(r.period_to)))
	return out


def _prebilled_excess(hoc_name):
	"""Excess already put on a pro forma for jobs that had no JCR then: {HOC job line: [[from, to, jobs]]}."""
	out = {}
	for r in frappe.db.sql("""select i.hire_order_item, i.rental_from, i.rental_to, i.job_qty from `tabRental Pro Forma Item` i
		join `tabRental Pro Forma Invoice` p on p.name = i.parent where p.hire_order_contract = %s and p.docstatus < 2
		and p.status not in ('Expired', 'Cancelled') and i.charge_type = %s and ifnull(i.jcr_line, '') = ''""", (hoc_name, EXCESS_CHARGE), as_dict=True):
		out.setdefault(r.hire_order_item, []).append([getdate(r.rental_from), getdate(r.rental_to), flt(r.job_qty)])
	return out


def _net_prebilled(start, end, qty, entries):
	"""[(from, to, jobs)] of [start, end] for `qty` jobs after the jobs whose excess was already billed on a pro forma before their JCR existed."""
	if not entries:
		return [(start, end, qty)]
	cuts = sorted({start, add_days(end, 1)} | {c for f, t, _q in entries for c in (f, add_days(t, 1)) if start < c <= end})
	out = []
	for a, b in zip(cuts, cuts[1:]):
		b = add_days(b, -1)
		have = [e for e in entries if e[0] <= a and b <= e[1] and e[2] > EPS]
		take = min(qty, sum(e[2] for e in have))
		left = take
		for e in have:  # split each entry around the stretch so its jobs are used only once
			use = min(e[2], left)
			left -= use
			if use <= EPS:
				continue
			if e[0] < a:
				entries.append([e[0], add_days(a, -1), e[2]])
			if b < e[1]:
				entries.append([add_days(b, 1), e[1], e[2]])
			e[0], e[1], e[2] = a, b, e[2] - use
		if qty - take > EPS:
			out.append((a, b, qty - take))
	return out


def _prebilled(hoc_name):
	"""Jobs whose contract charge went on a pro forma before any Job Completion Report existed: {HOC job line: jobs}."""
	return {r.hire_order_item: flt(r.qty) for r in frappe.db.sql("""select i.hire_order_item, sum(i.job_qty) as qty from `tabRental Pro Forma Item` i
		join `tabRental Pro Forma Invoice` p on p.name = i.parent where p.hire_order_contract = %s and p.docstatus < 2
		and p.status not in ('Expired', 'Cancelled') and i.charge_type = %s and ifnull(i.jcr_line, '') = '' group by i.hire_order_item""",
		(hoc_name, CONTRACT_CHARGE), as_dict=True)}


def contract_lines(hoc, upto):
	"""Pro forma item rows for a Hire Order Contract. Contract Charge: jobs x contract rate for the contract days. Excess Charge: only the
	days beyond the contract days of that job line, at that line's excess rate and basis, each job line on its own."""
	from thinknxg_rental.services import jcr_billing
	from thinknxg_rental.thinknxg_rental.doctype.job_completion_report import job_completion_report as jcrmod

	month_basis = get_settings().month_basis
	covered, prebilled, prebilled_excess = _covered(hoc.name), _prebilled(hoc.name), _prebilled_excess(hoc.name)
	rows, notes = [], []

	def dmy(v):
		return getdate(v).strftime("%d-%m-%Y")

	def contract_row(line, ref, qty, start, end, jcr=None, jcr_line=None, hoc_item=None):
		days = date_diff(end, start) + 1
		name = line.get("job_type_name") or line.job_type
		return {"item_code": line.job_type, "item_name": name, "charge_type": CONTRACT_CHARGE, "qty": qty, "job_qty": qty, "rate": flt(line.contract_rate),
			"rate_basis": "Daily", "rental_from": start, "rental_to": end, "jcr": jcr, "jcr_line": jcr_line, "hire_order_item": hoc_item,
			"description": _("Contract Charge - {0} - {1} - {2} Jobs - {3} Days ({4} to {5})").format(name, ref, _fmt(qty), days, dmy(start), dmy(end))}

	def excess_row(line, ref, jobs, start, end, jcr=None, jcr_line=None, hoc_item=None):
		basis = line.excess_rate_basis or "Daily"
		unit = {"Daily": _("day"), "Weekly": _("week"), "Monthly": _("month")}.get(basis, basis)
		name = line.get("job_type_name") or line.job_type
		return {"item_code": line.job_type, "item_name": name, "charge_type": EXCESS_CHARGE, "qty": flt(billable_units(jobs, start, end, basis, month_basis), 6),
			"job_qty": flt(jobs, 6), "rate": flt(line.excess_rate), "rate_basis": basis, "rental_from": start, "rental_to": end, "jcr": jcr, "jcr_line": jcr_line,
			"hire_order_item": hoc_item,
			"description": _("Excess Charge - {0} - {1} - {2} Jobs - {3} Days ({4} to {5}) @ {6} per job per {7}").format(
				name, ref, _fmt(jobs), date_diff(end, start) + 1, dmy(start), dmy(end), _fmt(line.excess_rate), unit)}

	for jcr_name in frappe.get_all("Job Completion Report", filters={"hire_order_contract": hoc.name, "docstatus": 1, "status": ["!=", "Cancelled"]}, pluck="name", order_by="creation"):
		jcr = frappe.get_doc("Job Completion Report", jcr_name)
		for line in jcr.job_lines:
			ref = f"{jcr.name} @ {line.location}" if line.location else jcr.name
			pieces, no_excess_rate = [], False
			for p in jcr_billing.plan_periods(line, today=upto, on_demand=True, partial=True):
				kind = CONTRACT_CHARGE if p.billing_type == "Contract" else EXCESS_CHARGE
				start, end = getdate(p.period_from), getdate(p.period_to)
				done = covered.get((line.name, kind), [])
				if kind == CONTRACT_CHARGE:
					if done:
						continue
					qty = flt(p.qty)
					if flt(line.contract_rate) <= 0:
						notes.append(_("{0}: no contract rate, so no contract charge").format(ref))
						continue
					early = min(prebilled.get(line.contract_item, 0), qty)  # jobs already on a pro forma made before this JCR
					prebilled[line.contract_item] = prebilled.get(line.contract_item, 0) - early
					if qty - early <= EPS:
						continue
					rows.append(contract_row(line, ref, flt(qty - early, 6), start, end, jcr.name, line.name, line.contract_item))
					continue
				# Excess: only the days not already billed or on a live pro forma; gathered here, written below as one row per free stretch
				if flt(line.excess_rate) <= 0:
					no_excess_rate = True
					continue
				pieces += [(a, b, q) for a, b in _free_stretches(start, end, done)
					for a, b, q in _net_prebilled(a, b, flt(p.qty), prebilled_excess.get(line.contract_item))]
			if no_excess_rate:
				notes.append(_("{0}: no excess rate, so its excess days are not charged").format(ref))
			for start, end, jobs in _merge_stretches(pieces):
				rows.append(excess_row(line, ref, jobs, start, end, jcr.name, line.name, line.contract_item))
	# jobs not yet on a Job Completion Report: the contract charge they will carry, from the required date
	reported, returned = jcrmod.get_reported_qty_by_line(hoc.name), jcrmod.get_returned_qty_by_line(hoc.name)
	for item in hoc.items:
		remaining = jcrmod.remaining_jobs(item, reported, returned)
		if remaining <= EPS:
			continue
		ref = f"{hoc.name} {jcrmod.line_label(item)}"
		if flt(item.contract_rate) <= 0:
			notes.append(_("{0}: no contract rate, so no contract charge").format(jcrmod.line_label(item)))
			continue
		start = getdate(hoc.required_from or hoc.order_date or nowdate())
		end = jcr_billing.get_contract_end(start, item.included_days)
		left = remaining - prebilled.get(item.name, 0)  # jobs whose contract charge is not on a pro forma yet
		if left > EPS:
			rows.append(contract_row(item, ref, flt(left, 6), start, end, hoc_item=item.name))
		# days past the contract days up to Bill Up To are excess, JCR or not: every unreported job, one row for the whole free stretch
		if end >= upto:
			continue
		if flt(item.excess_rate) <= 0:
			notes.append(_("{0}: no excess rate, so its excess days are not charged").format(ref))
			continue
		for a, b in _free_stretches(add_days(end, 1), upto, covered.get((item.name, EXCESS_CHARGE), [])):
			rows.append(excess_row(item, ref, remaining, a, b, hoc_item=item.name))
	return rows, notes


@frappe.whitelist()
def get_item_rate(item_code: str, rate_basis: str = "Monthly", customer: str | None = None, posting_date: str | None = None,
		period_days: int | None = None):
	return default_rate(item_code, rate_basis, customer, posting_date, period_days)


def link_contract(contract):
	"""Pro forma invoices of the hire order belong to the contract made from it (and count what it collected)."""
	if contract.hire_order:
		frappe.db.sql(f"""update `tab{DOCTYPE}` set rental_contract = %s
			where hire_order = %s and ifnull(rental_contract, '') = ''""", (contract.name, contract.hire_order))
		from thinknxg_rental.services import deposits

		for name in frappe.get_all(DOCTYPE, filters={"rental_contract": contract.name, "docstatus": 1}, pluck="name"):
			if deposits.claim_collections(name):
				refresh_payments(name)
