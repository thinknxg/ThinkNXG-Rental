import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, get_last_day, getdate, nowdate

BASIS_UOM = {"Daily": "Unit-Day", "Weekly": "Unit-Week", "Monthly": "Unit-Month"}
BASIS_FACTOR = {"Daily": 1, "Weekly": 7, "Monthly": 30}


def get_settings():
	return frappe.get_cached_doc("Rental Settings")


def require_setting(fieldname):
	settings = get_settings()
	value = settings.get(fieldname)
	if not value:
		label = settings.meta.get_label(fieldname)
		frappe.throw(_("Please set {0} in Rental Settings").format(frappe.bold(label)))
	return value


def billable_units(qty, from_date, to_date, rate_basis, month_basis=None):
	"""Units to bill for `qty` held from from_date to to_date inclusive.

	Daily -> unit-days, Weekly -> unit-weeks (days / 7), Monthly -> unit-months
	(days / 30, or days / days-in-that-month when month basis is Actual Calendar Days).
	"""
	from_date, to_date = getdate(from_date), getdate(to_date)
	days = date_diff(to_date, from_date) + 1
	if days <= 0 or not flt(qty):
		return 0.0
	rate_basis = rate_basis or "Monthly"
	if rate_basis == "Daily":
		return flt(qty) * days
	if rate_basis == "Weekly":
		return flt(qty) * days / 7.0
	if (month_basis or get_settings().month_basis) != "Actual Calendar Days":
		return flt(qty) * days / 30.0
	units, day = 0.0, from_date
	while day <= to_date:
		month_end = getdate(get_last_day(day))
		seg_end = min(month_end, to_date)
		units += flt(qty) * (date_diff(seg_end, day) + 1) / month_end.day
		day = add_days(seg_end, 1)
	return units


def estimate_amount(qty, days, rate_basis, rate):
	return flt(qty) * cint(days) / BASIS_FACTOR.get(rate_basis or "Monthly", 30) * flt(rate)


def get_profile(item_code):
	if not item_code or not frappe.db.exists("Rental Item Profile", item_code):
		return frappe._dict()
	return frappe.get_cached_doc("Rental Item Profile", item_code)


def get_rental_rate(item_code, rate_basis="Monthly", customer=None, posting_date=None):
	"""Customer rate card -> general rate card -> Rental Item Profile."""
	field = {"Daily": "daily_rate", "Weekly": "weekly_rate", "Monthly": "monthly_rate"}.get(rate_basis or "Monthly")
	posting_date = getdate(posting_date or nowdate())
	cards = frappe.db.sql(
		f"""
		select rci.{field} as rate, rc.customer
		from `tabRental Rate Card Item` rci
		inner join `tabRental Rate Card` rc on rc.name = rci.parent
		where rci.item_code = %(item)s and rc.disabled = 0
			and (rc.valid_from is null or rc.valid_from <= %(date)s)
			and (rc.valid_upto is null or rc.valid_upto >= %(date)s)
			and (rc.customer = %(customer)s or rc.customer is null or rc.customer = '')
			and rci.{field} > 0
		order by case when rc.customer = %(customer)s then 0 else 1 end, rc.valid_from desc
		limit 1
		""",
		{"item": item_code, "date": posting_date, "customer": customer or "__none__"},
		as_dict=True,
	)
	if cards:
		return flt(cards[0].rate)
	return flt(get_profile(item_code).get(field))


def get_bin_qty(item_code, warehouse):
	if not (item_code and warehouse):
		return 0.0
	return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"))


def get_open_reservations(item_code, warehouse):
	return frappe.db.sql(
		"""
		select r.name, r.hire_contract, r.hire_order,
			(ri.reserved_qty - ri.dispatched_qty - ri.released_qty) as balance
		from `tabRental Material Reservation Item` ri
		inner join `tabRental Material Reservation` r on r.name = ri.parent
		where r.docstatus = 1 and r.status not in ('Released', 'Dispatched')
			and r.source_warehouse = %s and ri.item_code = %s
			and (ri.reserved_qty - ri.dispatched_qty - ri.released_qty) > 0
		""",
		(warehouse, item_code),
		as_dict=True,
	)


def get_reserved_for_others(item_code, warehouse, hire_contract=None, hire_order=None, reservation=None):
	total = 0.0
	for row in get_open_reservations(item_code, warehouse):
		if reservation and row.name == reservation:
			continue
		if hire_contract and row.hire_contract == hire_contract:
			continue
		if hire_order and row.hire_order == hire_order:
			continue
		total += flt(row.balance)
	return total


def get_available_qty(item_code, warehouse, hire_contract=None, hire_order=None, reservation=None):
	"""Yard stock not promised to somebody else. Reservations never touch the stock ledger."""
	return get_bin_qty(item_code, warehouse) - get_reserved_for_others(
		item_code, warehouse, hire_contract, hire_order, reservation
	)


@frappe.whitelist()
def get_item_rental_details(item_code: str, customer: str | None = None, rate_basis: str | None = None,
		posting_date=None, warehouse: str | None = None):
	frappe.has_permission("Item", "read", throw=True)
	item = frappe.get_cached_value("Item", item_code, ["item_name", "stock_uom", "is_stock_item"], as_dict=True)
	if not item:
		frappe.throw(_("Item {0} not found").format(item_code))
	if not item.is_stock_item:
		frappe.throw(_("{0} is not a stock item. Rental material must have Maintain Stock enabled.").format(item_code))
	profile = get_profile(item_code)
	rate_basis = rate_basis or profile.get("default_rate_basis") or "Monthly"
	warehouse = warehouse or get_settings().rental_yard_warehouse
	return {
		"item_name": item.item_name,
		"uom": item.stock_uom,
		"rate_basis": rate_basis,
		"rate": get_rental_rate(item_code, rate_basis, customer, posting_date),
		"security_deposit_rate": flt(profile.get("security_deposit_rate")),
		"replacement_value": flt(profile.get("replacement_value")),
		"minimum_hire_days": cint(profile.get("minimum_hire_days")),
		"weight_per_unit": flt(profile.get("weight_per_unit")),
		"available_qty": get_available_qty(item_code, warehouse) if warehouse else 0,
	}


def check_duplicate_items(doc, key_fields=("item_code",), table="items"):
	seen = set()
	for row in doc.get(table):
		key = tuple(row.get(f) or "" for f in key_fields)
		if key in seen:
			frappe.throw(_("Row #{0}: {1} is entered more than once").format(row.idx, frappe.bold(row.item_code)))
		seen.add(key)
