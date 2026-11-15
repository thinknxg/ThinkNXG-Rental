"""Multi-location rental warehouses: seed Own Rental Warehouses and Cross Hire Warehouses.

* the existing Rental Yard and Cross Hire Yard become the defaults of their tables
* warehouses already used as own sources (reservations, deliveries, own returns) and as cross hire
  receipt warehouses (Cross Hire Orders received at a yard) are added, so documents made before
  the upgrade stay valid

Safe to run again: rows already in a table are left as they are (default and active flags included),
and nothing is renamed, deleted or reposted.
"""
import frappe

from thinknxg_rental.services import warehouses as rw


def _used(sql):
	return [r[0] for r in frappe.db.sql(sql) if r[0]]


def execute():
	frappe.reload_doc("thinknxg_rental", "doctype", "rental_warehouse")
	frappe.reload_doc("thinknxg_rental", "doctype", "rental_settings")
	s = frappe.get_single("Rental Settings")
	if not (s.rental_yard_warehouse or s.cross_hire_yard_warehouse or s.own_rental_warehouses or s.cross_hire_warehouses):
		return  # not set up yet: setup_company fills the tables

	own = [s.rental_yard_warehouse]
	own += _used("""select distinct source_warehouse from `tabRental Material Reservation Item`
		where docstatus < 2 and ifnull(ownership, 'Own') = 'Own'""")
	own += _used("""select distinct source_warehouse from `tabRental Material Reservation` where docstatus < 2""")
	own += _used("""select distinct source_warehouse from `tabHire Delivery Item`
		where docstatus = 1 and ifnull(ownership, 'Own') = 'Own'""")
	cross = [s.cross_hire_yard_warehouse]
	cross += _used("""select distinct receipt_warehouse from `tabCross Hire Order`
		where docstatus = 1 and ifnull(receive_at, '') != 'Direct to Site'""")

	special = rw.special_warehouses() | {s.customer_sites_warehouse}
	taken = {r.warehouse for r in s.own_rental_warehouses} | {r.warehouse for r in s.cross_hire_warehouses}

	def usable(wh):
		if not wh or wh in special or wh in taken:
			return False
		row = frappe.db.get_value("Warehouse", wh, ["is_group", "company"], as_dict=True)
		if not row or row.is_group or (s.company and row.company != s.company):
			return False
		return not rw.is_site_warehouse(wh)

	changed = False
	# the cross hire yard is placed first so a yard used both ways stays a cross hire warehouse
	for table, candidates, legacy in (
		("cross_hire_warehouses", cross, s.cross_hire_yard_warehouse),
		("own_rental_warehouses", own, s.rental_yard_warehouse),
	):
		has_default = any(r.is_default for r in s.get(table))
		for wh in dict.fromkeys(candidates):
			if not usable(wh):
				continue
			s.append(table, {"warehouse": wh, "is_active": 1, "is_default": 1 if (wh == legacy and not has_default) else 0,
				"location": rw.default_location(wh)})
			taken.add(wh)
			changed = True
	if changed:
		s.flags.ignore_permissions = True
		s.flags.ignore_mandatory = True
		s.save()
	frappe.clear_cache(doctype="Rental Settings")
