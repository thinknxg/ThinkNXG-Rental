"""Excess Material Conversion Entry: excess the company owns, moved into rental stock as the same or
another item. Optional and explicit: nothing else ever makes one.

Only excess the company owns can be converted: adjusted on a submitted Dismantling Entry (the customer
was given credit for it) or approved as abandoned on an Excess Material Abandonment, and not yet converted. Excess still available to the customer is theirs.

The stock movement is ONE ERPNext Repack Stock Entry: the source excess item is consumed from the excess
warehouse (at its zero value) and the target item is received in an own rental warehouse at the rate
chosen on the row (Set Basic Rate Manually, or zero valuation). A Repack is ERPNext's own transaction for
one item going out and another coming in; a Material Transfer cannot change an item code. The value
added is posted against the Difference Account. Cancelling cancels the Repack, which reverses the stock
ledger and GL entries.

Neither the customer's balance (Rental Ownership Ledger) nor any Dismantling Entry is touched.
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime, nowdate

from thinknxg_rental.services import excess, stock
from thinknxg_rental.services import warehouses as rw

EXISTING = "Convert to Existing Rental Item"
DIFFERENT = "Convert to Different Item"
EPS = excess.EPS


class ExcessMaterialConversionEntry(Document):
	def validate(self):
		self.status = {0: "Draft", 1: "Converted", 2: "Cancelled"}[self.docstatus]
		if not self.items:
			frappe.throw(_("Add at least one excess register to convert"))
		self.validate_warehouses()
		names = [d.excess_register for d in self.items]
		if self.docstatus == 1:
			excess.lock_registers(names)
		regs = {r.name: r for r in frappe.get_all(excess.REGISTER, filters={"name": ["in", names]}, fields=["*"])}
		left = excess.convertible(names, exclude=(self.doctype, self.name))
		self.validate_rows(regs, left)

	def validate_warehouses(self):
		if not self.source_warehouse:
			self.source_warehouse = frappe.db.get_single_value("Rental Settings", "excess_warehouse")
		if not self.target_warehouse:
			self.target_warehouse = rw.default_own_warehouse()
		if frappe.db.get_value("Warehouse", self.source_warehouse, "company") != self.company:
			frappe.throw(_("{0} belongs to another company").format(self.source_warehouse))
		for d in self.items:
			d.target_warehouse = d.target_warehouse or self.target_warehouse
		for wh in {self.target_warehouse, *[d.target_warehouse for d in self.items]}:
			label = _("Target Warehouse {0}").format(wh)
			if wh == self.source_warehouse:
				frappe.throw(_("{0} is the excess warehouse itself").format(label))
			rw.validate_own(wh, row_label=label + ": ", company=self.company)
		if self.difference_account:
			acc = frappe.db.get_value("Account", self.difference_account, ["company", "is_group"], as_dict=True)
			if not acc or acc.company != self.company or acc.is_group:
				frappe.throw(_("Difference Account {0} must be a ledger account of {1}").format(self.difference_account, self.company))

	def validate_rows(self, regs, left):
		taken, keys = {}, set()
		self.total_conversion_qty = self.total_target_qty = self.total_value = 0
		for d in self.items:
			prefix = _("Row #{0}: ").format(d.idx)
			reg = regs.get(d.excess_register)
			if not reg:
				frappe.throw(prefix + _("Excess register {0} not found").format(d.excess_register))
			if reg.status == "Cancelled":
				frappe.throw(prefix + _("{0} was cancelled with its off-hire note").format(reg.name))
			if reg.customer != self.customer or reg.company != self.company:
				frappe.throw(prefix + _("{0} is excess of {1}, not of {2}").format(reg.name, reg.customer, self.customer), title=_("Different Customer"))
			if self.project and reg.project != self.project:
				frappe.throw(prefix + _("{0} is excess of project {1}, not {2}").format(reg.name, reg.project or _("(none)"), self.project))
			if reg.excess_warehouse != self.source_warehouse:
				frappe.throw(prefix + _("{0} is held in {1}, not in {2}. Convert from one warehouse per entry.").format(
					reg.name, reg.excess_warehouse, self.source_warehouse))
			d.update({"source_item_code": reg.item_code, "source_item_name": reg.item_name, "source_uom": reg.uom,
				"hire_off_hire_note": reg.hire_off_hire_note})
			d.source_batch_no = d.source_batch_no or reg.batch_no
			d.available_qty = flt(left.get(reg.name))
			if flt(d.conversion_qty) <= 0:
				frappe.throw(prefix + _("Conversion Qty must be more than zero"))
			if not flt(d.target_qty):
				d.target_qty = d.conversion_qty
			if flt(d.target_qty) <= 0:
				frappe.throw(prefix + _("Target Qty must be more than zero"))
			taken[reg.name] = taken.get(reg.name, 0) + flt(d.conversion_qty)
			key = (reg.name, d.target_item_code, d.target_warehouse)
			if key in keys:
				frappe.throw(prefix + _("{0} into {1} at {2} is entered twice. Use one row.").format(reg.name, d.target_item_code, d.target_warehouse),
					title=_("Duplicate Row"))
			keys.add(key)
			self.validate_target_item(d, prefix)
			self.set_rate(d, prefix)
			self.total_conversion_qty += flt(d.conversion_qty)
			self.total_target_qty += flt(d.target_qty)
			self.total_value += flt(d.amount)
		for name, qty in taken.items():
			if qty > flt(left.get(name)) + EPS:
				frappe.throw(_("{0} ({1}): converting {2} but only {3} can be converted. Only excess adjusted on a submitted Dismantling Entry or approved as abandoned, and not yet converted, belongs to the company.").format(
					name, regs[name].item_code, qty, flt(left.get(name))), title=_("More Than Available"))

	def validate_target_item(self, d, prefix):
		item = frappe.get_cached_value("Item", d.target_item_code, ["item_name", "stock_uom", "is_stock_item", "disabled",
			"has_variants", "is_fixed_asset"], as_dict=True)
		if not item or item.disabled or not item.is_stock_item or item.has_variants or item.is_fixed_asset:
			frappe.throw(prefix + _("{0} must be an enabled stock item (not a template or fixed asset)").format(frappe.bold(d.target_item_code)))
		d.target_item_name, d.target_uom = item.item_name, item.stock_uom
		is_rental = frappe.db.exists("Rental Item Profile", d.target_item_code)
		if self.conversion_type == EXISTING and not is_rental:
			frappe.throw(prefix + _("{0} is not a rental item (it has no Rental Item Profile). Pick a rental item, or use Convert to Different Item.").format(
				frappe.bold(d.target_item_code)), title=_("Not a Rental Item"))

	def set_rate(self, d, prefix):
		if d.valuation_basis == "Zero Value":
			d.valuation_rate = 0
		elif d.valuation_basis == "Target Item Valuation Rate":
			d.valuation_rate = target_valuation_rate(d.target_item_code, d.target_warehouse, self.posting_date)
			if not d.valuation_rate:
				frappe.throw(prefix + _("{0} has no valuation rate yet. Enter a Manual Rate, or choose Zero Value.").format(
					frappe.bold(d.target_item_code)), title=_("No Valuation Rate"))
		elif flt(d.valuation_rate) <= 0:
			frappe.throw(prefix + _("Enter the Valuation Rate, or choose Zero Value"), title=_("Valuation Rate Required"))
		d.amount = flt(d.target_qty) * flt(d.valuation_rate)

	def on_submit(self):
		account = self.difference_account or frappe.get_cached_value("Company", self.company, "stock_adjustment_account")
		rows = []
		for d in self.items:  # consumed: the excess item, at the zero value it was received at
			rows.append({"item_code": d.source_item_code, "qty": d.conversion_qty, "s_warehouse": self.source_warehouse,
				"zero_value": True, "batch_no": d.source_batch_no, "serial_no": d.source_serial_no})
		for d in self.items:  # received: the target item, at the rate chosen
			zero = d.valuation_basis == "Zero Value"
			extra = {"is_finished_item": 1, "expense_account": account}
			if not zero:
				extra.update({"set_basic_rate_manually": 1, "basic_rate": flt(d.valuation_rate)})
			rows.append({"item_code": d.target_item_code, "qty": d.target_qty, "t_warehouse": d.target_warehouse,
				"zero_value": zero, "batch_no": d.target_batch_no, "serial_no": d.target_serial_no, "extra": extra})
		entry = stock.make_stock_entry(self, "Repack", rows, self.posting_date,
			remarks=f"Excess converted to rental stock - {self.name} ({self.customer})")
		self.db_set({"stock_entry": entry, "status": "Converted", "converted_by": frappe.session.user, "converted_on": now_datetime()})
		excess.recompute([d.excess_register for d in self.items])

	def on_cancel(self):
		stock.cancel_stock_entries(self)
		self.db_set("status", "Cancelled")
		excess.recompute([d.excess_register for d in self.items])


def target_valuation_rate(item_code, warehouse, posting_date):
	"""The target item's valuation rate in the warehouse as at the posting date, else its latest rate in
	any warehouse, else the rate on the Item."""
	from erpnext.stock.utils import get_stock_balance

	rate = flt(get_stock_balance(item_code, warehouse, posting_date, with_valuation_rate=True)[1]) if warehouse else 0
	if not rate:
		rows = frappe.get_all("Bin", filters={"item_code": item_code, "valuation_rate": [">", 0]}, pluck="valuation_rate",
			order_by="modified desc", limit=1)
		rate = flt(rows[0]) if rows else 0
	return rate or flt(frappe.get_cached_value("Item", item_code, "valuation_rate"))


@frappe.whitelist()
def get_valuation_rate(item_code: str, warehouse: str | None = None, posting_date: str | None = None):
	frappe.has_permission("Excess Material Conversion Entry", "read", throw=True)
	return target_valuation_rate(item_code, warehouse, posting_date or nowdate())


def _convertible_rows(filters):
	names = frappe.get_all(excess.REGISTER, filters=dict(filters, status=["!=", "Cancelled"]), pluck="name", order_by="posting_date, creation")
	left = excess.convertible(names)
	return [n for n in names if left.get(n, 0) > EPS], left


@frappe.whitelist()
def get_convertible_items(customer: str, project: str | None = None, source_warehouse: str | None = None):
	"""Excess of a customer that the company owns (adjusted, not converted), for Get Convertible Excess."""
	frappe.has_permission("Excess Material Conversion Entry", "create", throw=True)
	filters = {"customer": customer}
	if project:
		filters["project"] = project
	if source_warehouse:
		filters["excess_warehouse"] = source_warehouse
	names, left = _convertible_rows(filters)
	out = []
	for r in frappe.get_all(excess.REGISTER, filters={"name": ["in", names]}, fields=["*"], order_by="posting_date, creation"):
		has_profile = frappe.db.exists("Rental Item Profile", r.item_code)
		out.append({"excess_register": r.name, "source_item_code": r.item_code, "source_item_name": r.item_name, "source_uom": r.uom,
			"hire_off_hire_note": r.hire_off_hire_note, "available_qty": left[r.name], "conversion_qty": left[r.name],
			"target_item_code": r.item_code if has_profile else None, "target_qty": left[r.name], "valuation_basis": "Manual Rate",
			"source_batch_no": r.batch_no, "excess_warehouse": r.excess_warehouse})
	return out


@frappe.whitelist()
def make_from_register(source_name: str, target_doc=None):
	"""A draft conversion for one register, for what the company owns of it."""
	frappe.has_permission(excess.REGISTER, "read", source_name, throw=True)
	frappe.has_permission("Excess Material Conversion Entry", "create", throw=True)
	reg = frappe.get_doc(excess.REGISTER, source_name)
	qty = flt(excess.convertible([reg.name]).get(reg.name))
	if qty <= EPS:
		frappe.throw(_("Nothing of {0} can be converted. Only excess adjusted on a submitted Dismantling Entry or approved as abandoned, and not yet converted, belongs to the company.").format(reg.name))
	doc = frappe.new_doc("Excess Material Conversion Entry")
	doc.update({"company": reg.company, "customer": reg.customer, "customer_name": reg.customer_name, "project": reg.project,
		"posting_date": nowdate(), "source_warehouse": reg.excess_warehouse, "target_warehouse": rw.default_own_warehouse()})
	has_profile = frappe.db.exists("Rental Item Profile", reg.item_code)
	doc.conversion_type = EXISTING if has_profile else DIFFERENT
	doc.append("items", {"excess_register": reg.name, "source_item_code": reg.item_code, "source_item_name": reg.item_name,
		"source_uom": reg.uom, "hire_off_hire_note": reg.hire_off_hire_note, "available_qty": qty, "conversion_qty": qty,
		"target_item_code": reg.item_code if has_profile else None, "target_qty": qty, "valuation_basis": "Manual Rate",
		"target_warehouse": doc.target_warehouse, "source_batch_no": reg.batch_no})
	return doc

