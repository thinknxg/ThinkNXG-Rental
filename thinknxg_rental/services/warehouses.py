"""Rental warehouses: own rental warehouses and cross hire warehouses, across locations.

Rental Settings holds two tables of Rental Warehouse rows (warehouse, location, is default, is active):

* Own Rental Warehouses - company-owned rental stock (Kochi Yard, Calicut Yard, ...)
* Cross Hire Warehouses - supplier-owned material received on cross hire

Business logic asks this module, never the legacy single-yard fields, which only follow each
table's default for older code and reports. With empty tables (an install that has not migrated
yet) the legacy fields are the only warehouse of each kind, so a single-yard setup works unchanged.
"""
import frappe
from frappe import _

OWN = "Own"
CROSS_HIRE = "Cross Hire"

TABLES = {OWN: ("own_rental_warehouses", "rental_yard_warehouse"), CROSS_HIRE: ("cross_hire_warehouses", "cross_hire_yard_warehouse")}
# warehouses with a fixed purpose that can never be a rental or cross hire warehouse
SPECIAL_FIELDS = ("inspection_warehouse", "repair_warehouse", "scrap_warehouse", "lost_warehouse", "excess_warehouse")


def settings():
	return frappe.get_cached_doc("Rental Settings")


def _rows(category):
	"""[(warehouse, location, is_default, is_active)] of a category, default first."""
	s = settings()
	table, legacy = TABLES[category]
	rows = [(r.warehouse, r.location, int(r.is_default or 0), int(r.is_active or 0)) for r in (s.get(table) or []) if r.warehouse]
	if not rows and s.get(legacy):
		rows = [(s.get(legacy), None, 1, 1)]
	return sorted(rows, key=lambda r: (-r[2], -r[3]))


def get_warehouses(category, active_only=True):
	return [r[0] for r in _rows(category) if r[3] or not active_only]


def own_warehouses(active_only=True):
	return get_warehouses(OWN, active_only)


def cross_hire_warehouses(active_only=True):
	return get_warehouses(CROSS_HIRE, active_only)


def default_warehouse(category):
	rows = _rows(category)
	for wh, _loc, is_default, active in rows:
		if is_default and active:
			return wh
	for wh, _loc, _d, active in rows:
		if active:
			return wh
	return None


def default_own_warehouse():
	return default_warehouse(OWN)


def default_cross_hire_warehouse():
	return default_warehouse(CROSS_HIRE)


def require_default(category):
	wh = default_warehouse(category)
	if not wh:
		label = _("Own Rental Warehouses") if category == OWN else _("Cross Hire Warehouses")
		frappe.throw(_("Please add a default warehouse to {0} in Rental Settings").format(frappe.bold(label)))
	return wh


def category_of(warehouse, active_only=False):
	"""Own / Cross Hire for a configured warehouse, else None."""
	if not warehouse:
		return None
	for category in (OWN, CROSS_HIRE):
		if warehouse in get_warehouses(category, active_only):
			return category
	return None


def is_own(warehouse, active_only=False):
	return category_of(warehouse, active_only) == OWN


def is_cross_hire(warehouse, active_only=False):
	return category_of(warehouse, active_only) == CROSS_HIRE


def is_active(warehouse):
	return category_of(warehouse, active_only=True) is not None


def location_of(warehouse):
	"""The row's Location / Branch, else the parent warehouse's name (Kochi - TC -> Kochi)."""
	if not warehouse:
		return None
	for category in (OWN, CROSS_HIRE):
		for wh, loc, _d, _a in _rows(category):
			if wh == warehouse and loc:
				return loc
	return default_location(warehouse)


def default_location(warehouse):
	parent = frappe.db.get_value("Warehouse", warehouse, "parent_warehouse")
	if not parent:
		return None
	name = frappe.db.get_value("Warehouse", parent, "warehouse_name") or parent
	# a root group ("All Warehouses") names no place
	if not frappe.db.get_value("Warehouse", parent, "parent_warehouse"):
		return None
	return name


def locations():
	"""{warehouse: location} for every configured warehouse, active or not."""
	out = {}
	for category in (OWN, CROSS_HIRE):
		for wh, _loc, _d, _a in _rows(category):
			out[wh] = location_of(wh)
	return out


def special_warehouses():
	s = settings()
	return {s.get(f) for f in SPECIAL_FIELDS if s.get(f)}


def is_site_warehouse(warehouse):
	if not warehouse:
		return False
	return bool(
		frappe.db.exists("Rental Site", {"site_warehouse": warehouse})
		or frappe.db.exists("Rental Site", {"cross_hire_site_warehouse": warehouse})
	)


# ----------------------------------------------------------------------------- validation helpers
def validate_own(warehouse, row_label="", allow_inactive=False, company=None):
	"""An own rental warehouse, active unless allow_inactive (an allocation made before it was retired)."""
	if not is_own(warehouse, active_only=not allow_inactive):
		if is_cross_hire(warehouse):
			frappe.throw(_("{0}{1} is a cross hire warehouse: own stock cannot be taken from or put into it").format(row_label, frappe.bold(warehouse)))
		if is_own(warehouse):
			frappe.throw(_("{0}{1} is inactive in Rental Settings and cannot be used on new transactions").format(row_label, frappe.bold(warehouse)))
		frappe.throw(_("{0}{1} is not an own rental warehouse in Rental Settings").format(row_label, frappe.bold(warehouse)))
	validate_company(warehouse, company, row_label)


def validate_cross_hire(warehouse, row_label="", allowed=(), allow_inactive=False, company=None):
	"""A cross hire warehouse, or one of `allowed` (a direct-to-site receipt warehouse of the order)."""
	if warehouse in set(allowed or ()):
		return
	if not is_cross_hire(warehouse, active_only=not allow_inactive):
		if is_own(warehouse):
			frappe.throw(_("{0}{1} is an own rental warehouse: supplier-owned material cannot enter it").format(row_label, frappe.bold(warehouse)))
		if is_cross_hire(warehouse):
			frappe.throw(_("{0}{1} is inactive in Rental Settings and cannot be used on new transactions").format(row_label, frappe.bold(warehouse)))
		frappe.throw(_("{0}{1} is not a cross hire warehouse in Rental Settings").format(row_label, frappe.bold(warehouse)))
	validate_company(warehouse, company, row_label)


def validate_company(warehouse, company, row_label=""):
	if not company or not warehouse:
		return
	wh_company = frappe.db.get_value("Warehouse", warehouse, "company")
	if wh_company and wh_company != company:
		frappe.throw(_("{0}Warehouse {1} belongs to {2}, not {3}").format(row_label, frappe.bold(warehouse), wh_company, company))


def lock_bins(pairs):
	"""Lock the Bin rows of (item_code, warehouse) pairs until the transaction ends, in a fixed order
	so two concurrent submissions queue up instead of both reading the same free stock."""
	pairs = sorted({(i, w) for i, w in pairs if i and w})
	for item_code, warehouse in pairs:
		frappe.db.sql(
			"select name from `tabBin` where item_code = %s and warehouse = %s for update", (item_code, warehouse)
		)
	return pairs


@frappe.whitelist()
def get_rental_warehouses(category: str | None = None, active_only: int = 1):
	"""Warehouses with their location for pickers and filters."""
	out = []
	for cat in ([category] if category else [OWN, CROSS_HIRE]):
		default = default_warehouse(cat)
		for wh, _loc, _d, active in _rows(cat):
			if active or not int(active_only):
				out.append({"warehouse": wh, "location": location_of(wh), "category": cat, "is_default": int(wh == default), "is_active": active})
	return out


def available_own_qty(item_code, rental_contract=None, source=None):
	"""Own stock of an item free to reserve or dispatch, over every active own rental warehouse
	(each warehouse counted on its own, so a reservation elsewhere never makes a warehouse negative)."""
	from thinknxg_rental.services.utils import get_available_qty

	return sum(max(get_available_qty(item_code, w, rental_contract, source), 0) for w in own_warehouses())
