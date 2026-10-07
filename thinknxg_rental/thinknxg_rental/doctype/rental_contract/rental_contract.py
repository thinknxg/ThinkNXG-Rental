import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.utils import cint, flt, getdate, nowdate

from thinknxg_rental.services import billing, ledger
from thinknxg_rental.services.utils import check_duplicate_items, get_contract_source, get_rental_rate, get_settings

SOURCE_TYPES = {"Hire Order": "Item Rental", "Hire Order Contract": "Job Type Contract"}


class RentalContract(Document):
	def validate(self):
		self.set_source()
		self.validate_header()
		self.validate_items()

	def set_source(self):
		"""The contract is the common commercial layer; its source decides which business rules apply."""
		self.hire_order = self.hire_order_contract = None
		if not self.source_type:
			self.source_document = None
			self.contract_type = "Item Rental"
			return
		if self.source_type not in SOURCE_TYPES:
			frappe.throw(_("Rental Source Type must be Hire Order or Hire Order Contract"))
		if not self.source_document:
			frappe.throw(_("Select the {0} this contract is raised from").format(self.source_type))
		src = frappe.db.get_value(self.source_type, self.source_document, ["docstatus", "customer", "company"], as_dict=True)
		if not src or src.docstatus != 1:
			frappe.throw(_("{0} {1} is not submitted").format(self.source_type, self.source_document))
		if src.customer != self.customer:
			frappe.throw(_("{0} {1} belongs to customer {2}").format(self.source_type, self.source_document, src.customer))
		self.contract_type = SOURCE_TYPES[self.source_type]
		if self.source_type == "Hire Order":
			self.hire_order = self.source_document
		else:
			self.hire_order_contract = self.source_document
		if frappe.db.exists(
			"Rental Contract",
			{"source_type": self.source_type, "source_document": self.source_document, "docstatus": 1, "name": ["!=", self.name]},
		):
			frappe.throw(_("{0} {1} already has a submitted Rental Contract").format(self.source_type, self.source_document))

	def validate_header(self):
		if getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("Contract End Date cannot be before Contract Start Date"))
		site = frappe.db.get_value("Rental Site", self.rental_site, ["customer", "company", "disabled"], as_dict=True)
		if site.customer != self.customer:
			frappe.throw(_("Rental Site {0} does not belong to customer {1}").format(self.rental_site, self.customer))
		if site.company != self.company:
			frappe.throw(_("Rental Site {0} belongs to company {1}").format(self.rental_site, site.company))
		if self.billing_cycle == "Custom" and cint(self.billing_interval_days) < 1:
			frappe.throw(_("Billing Interval Days is required for a custom billing cycle"))

	def validate_items(self):
		check_duplicate_items(self)
		total = 0
		for d in self.items:
			if flt(d.qty) <= 0:
				frappe.throw(_("Row #{0}: Contracted Qty must be greater than zero").format(d.idx))
			if flt(d.qty) < flt(d.dispatched_qty):
				frappe.throw(
					_("Row #{0}: Contracted Qty cannot be less than the {1} already dispatched").format(d.idx, d.dispatched_qty)
				)
			if not frappe.get_cached_value("Item", d.item_code, "is_stock_item"):
				frappe.throw(_("Row #{0}: {1} is not a stock item").format(d.idx, d.item_code))
			d.rate_basis = d.rate_basis or "Monthly"
			if self.contract_type == "Job Type Contract":
				# priced per job on the Hire Order Contract and billed from the JCR, not per item
				d.rate = 0
			elif not flt(d.rate):
				d.rate = get_rental_rate(d.item_code, d.rate_basis, self.customer, self.contract_date)
			if self.docstatus == 0:
				d.pending_qty = max(flt(d.qty) - flt(d.dispatched_qty), 0)
			total += flt(d.qty)
		if self.docstatus == 0:
			self.total_contract_qty = total

	def before_update_after_submit(self):
		# items, quantities and rates may be revised on a live contract; new rates apply to unbilled periods
		if self.status in ("Completed", "Cancelled"):
			frappe.throw(_("A {0} contract cannot be changed").format(self.status))
		self.validate_items()
		present = {d.item_code for d in self.items}
		for item_code, _ownership, _cho in ledger.get_site_balance(self.name):
			if item_code not in present:
				frappe.throw(_("{0} is at site on this contract and cannot be removed").format(frappe.bold(item_code)))

	def on_update_after_submit(self):
		self.db_set("total_contract_qty", sum(flt(d.qty) for d in self.items), update_modified=False)
		ledger.update_contract_progress(self.name)

	def on_submit(self):
		self.db_set("status", "Active")
		if self.source_type:
			frappe.db.set_value(self.source_type, self.source_document, "status", "Contracted")
			# reservations (and JCRs) raised from the source document now belong to this contract
			for name in frappe.get_all(
				"Rental Material Reservation",
				filters={"source_type": self.source_type, "source_document": self.source_document, "docstatus": 1,
					"rental_contract": ["is", "not set"]},
				pluck="name",
			):
				frappe.db.set_value("Rental Material Reservation", name, "rental_contract", self.name)
		if self.hire_order_contract:
			for name in frappe.get_all(
				"Job Completion Report",
				filters={"hire_order_contract": self.hire_order_contract, "docstatus": ["<", 2], "rental_contract": ["is", "not set"]},
				pluck="name",
			):
				frappe.db.set_value("Job Completion Report", name, "rental_contract", self.name)
				frappe.db.set_value("JCR Billing Schedule", {"jcr": name}, "rental_contract", self.name)

	def on_cancel(self):
		self.db_set("status", "Cancelled")
		if self.source_type and self.source_document:
			frappe.db.set_value(self.source_type, self.source_document, "status", "Open")

	@frappe.whitelist()
	def extend_contract(self, new_end_date: str, remarks: str | None = None):
		self.check_permission("write")
		if self.docstatus != 1 or self.status in ("Completed", "Cancelled"):
			frappe.throw(_("Only a live contract can be extended"))
		if getdate(new_end_date) <= getdate(self.end_date):
			frappe.throw(_("New end date must be after the current end date {0}").format(self.end_date))
		self.append(
			"extensions",
			{
				"extension_date": nowdate(),
				"previous_end_date": self.end_date,
				"new_end_date": new_end_date,
				"extended_by": frappe.session.user,
				"remarks": remarks,
			},
		)
		self.end_date = new_end_date
		self.save()

	@frappe.whitelist()
	def close_contract(self):
		"""Final-bill and complete a contract once every item is back (or settled as lost)."""
		self.check_permission("write")
		ledger.update_contract_progress(self.name)
		self.reload()
		if flt(self.total_at_site_qty) > 0:
			frappe.throw(_("{0} units are still at site. Off-hire everything before closing.").format(self.total_at_site_qty))
		if self.hire_order_contract:
			standing = frappe.get_all(
				"Job Completion Report",
				filters={"hire_order_contract": self.hire_order_contract, "docstatus": 1, "dismantle_date": ["is", "not set"]},
				pluck="name",
			)
			if standing:
				frappe.throw(_("Record the dismantle date on {0} before closing this contract.").format(", ".join(standing)))
		billing.generate_billing(self.name)
		self.db_set("status", "Completed")
		for name in frappe.get_all(
			"Rental Material Reservation", {"rental_contract": self.name, "docstatus": 1, "status": ["in", ["Reserved", "Partially Reserved"]]}, pluck="name"
		):
			frappe.get_doc("Rental Material Reservation", name).release()

	@frappe.whitelist()
	def reopen_contract(self):
		self.check_permission("write")
		if self.status != "Completed":
			frappe.throw(_("Only a completed contract can be reopened"))
		self.db_set("status", "Active")
		ledger.update_contract_progress(self.name)


def _live_contract(source):
	if source.docstatus != 1 or source.status in ("Completed", "Cancelled"):
		frappe.throw(_("Contract {0} is not live").format(source.name))


@frappe.whitelist()
def make_reservation(source_name: str, target_doc=None):
	def post_process(source, target):
		_live_contract(source)
		target.reservation_date = nowdate()
		target.required_from = source.start_date
		target.required_to = source.end_date
		target.source_warehouse = get_settings().rental_yard_warehouse
		target.source_type, target.source_document = source.source_type, source.source_document

	return get_mapped_doc(
		"Rental Contract",
		source_name,
		{
			"Rental Contract": {"doctype": "Rental Material Reservation", "field_map": {"name": "rental_contract"}},
			"Rental Contract Item": {
				"doctype": "Rental Material Reservation Item",
				"field_map": {"pending_qty": "required_qty"},
				"condition": lambda d: flt(d.pending_qty) > 0,
			},
		},
		target_doc,
		post_process,
	)


@frappe.whitelist()
def make_delivery_order(source_name: str, target_doc=None):
	from thinknxg_rental.thinknxg_rental.doctype.hire_delivery_order.hire_delivery_order import get_dispatch_items

	source = frappe.get_doc("Rental Contract", source_name)
	_live_contract(source)
	target = frappe.new_doc("Hire Delivery Order")
	target.update(
		{
			"company": source.company,
			"rental_contract": source.name,
			"source_type": source.source_type,
			"source_document": source.source_document,
			"posting_date": nowdate(),
		}
	)
	for row in get_dispatch_items(source.name):
		target.append("items", row)
	target.run_method("set_missing_values")
	return target


@frappe.whitelist()
def make_off_hire_note(source_name: str, target_doc=None):
	from thinknxg_rental.thinknxg_rental.doctype.hire_off_hire_note.hire_off_hire_note import get_items_at_site

	source = frappe.get_doc("Rental Contract", source_name)
	_live_contract(source)
	target = frappe.new_doc("Hire Off-Hire Note")
	target.update(
		{
			"company": source.company,
			"rental_contract": source.name,
			"off_hire_date": nowdate(),
			"return_date": nowdate(),
			"grace_days": cint(source.grace_days),
		}
	)
	for row in get_items_at_site(source.name):
		target.append("items", row)
	return target


@frappe.whitelist()
def make_cross_hire_order(source_name: str, target_doc=None):
	source = frappe.get_doc("Rental Contract", source_name)
	_live_contract(source)
	settings = get_settings()
	target = frappe.new_doc("Cross Hire Order")
	target.update(
		{
			"company": source.company,
			"rental_contract": source.name,
			"order_date": nowdate(),
			"hire_from": max(getdate(source.start_date), getdate(nowdate())),
			"expected_return_date": max(getdate(source.end_date), getdate(nowdate())),
		}
	)
	yard = settings.rental_yard_warehouse
	from thinknxg_rental.services.utils import get_available_qty

	for d in source.items:
		pending = flt(d.pending_qty)
		if pending <= 0:
			continue
		available = max(get_available_qty(d.item_code, yard, source.name, get_contract_source(source.name)), 0) if yard else 0
		shortfall = pending - available
		if shortfall > 0:
			target.append("items", {"item_code": d.item_code, "item_name": d.item_name, "uom": d.uom, "qty": shortfall, "rate_basis": d.rate_basis})
	return target
