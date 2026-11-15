"""Standard Stock Entries touching rental warehouses (made by hand, not by a rental document).

Material moves between locations with an ordinary Material Transfer - Kochi Yard to Calicut Yard, or
supplier material from one cross hire warehouse to another. These rules keep the rental position right:

* own stock and supplier-owned (cross hire) stock never cross over, in either direction
* stock held by an open reservation stays where it is reserved (move only what is free)
* customer site warehouses are moved only by Hire Delivery Orders and Off-Hire Notes
* supplier material moved between cross hire warehouses names its Cross Hire Order; the custody
  ledger records the move (no billing effect) so custody stays traceable per warehouse

Entries made by rental documents (nxg_hire_voucher_type set) are checked by those documents.
Stock Reconciliation and other ERPNext documents are not affected.
"""
import frappe
from frappe import _
from frappe.utils import flt

from thinknxg_rental.services import ledger
from thinknxg_rental.services import warehouses as rw

GUARDED = ("Material Transfer", "Material Issue", "Material Receipt")


def _kind(warehouse, cross, own, special):
	if not warehouse:
		return None
	if warehouse in cross:
		return "cross"
	if warehouse in own or warehouse in special:
		return "own"
	if rw.is_site_warehouse(warehouse):
		return "site"
	return None


def validate(doc, method=None):
	if doc.get("nxg_hire_voucher_type") or doc.purpose not in GUARDED:
		return
	from thinknxg_rental.thinknxg_rental.doctype.rental_material_reservation.rental_material_reservation import (
		get_cross_hire_warehouses,
	)

	cross = get_cross_hire_warehouses()
	own = set(rw.own_warehouses(active_only=False))
	special = rw.special_warehouses()
	out_of_own, cross_moves = {}, {}
	for row in doc.items:
		s, t = row.s_warehouse, row.t_warehouse
		ks, kt = _kind(s, cross, own, special), _kind(t, cross, own, special)
		prefix = _("Row #{0}: ").format(row.idx)
		if "site" in (ks, kt):
			frappe.throw(prefix + _("{0} is a customer site warehouse. Material goes to and comes back from sites only with a Hire Delivery Order or an Off-Hire Note.").format(
				frappe.bold(s if ks == "site" else t)))
		if ks == "cross" and kt != "cross" and t:
			frappe.throw(prefix + _("{0} holds supplier-owned (cross hire) material: it can only move to another cross hire warehouse, never into {1}").format(
				frappe.bold(s), frappe.bold(t)))
		if kt == "cross" and ks != "cross":
			frappe.throw(prefix + _("{0} is a cross hire warehouse: only supplier material received on a Cross Hire Receipt goes into it").format(frappe.bold(t)))
		if ks == "cross" and not t:
			frappe.throw(prefix + _("Supplier-owned material in {0} cannot be issued: return it with a Cross Hire Off-Hire Note, or record a loss on the customer Off-Hire Note").format(frappe.bold(s)))
		if kt == "own" and t in own and not rw.is_active(t) and doc.docstatus == 0:
			frappe.throw(prefix + _("{0} is inactive in Rental Settings and cannot receive stock").format(frappe.bold(t)))
		if ks == "own" and s in own:
			key = (row.item_code, s)
			out_of_own[key] = out_of_own.get(key, 0) + flt(row.transfer_qty or row.qty)
		if ks == "cross" and kt == "cross":
			key = (row.item_code, s)
			cross_moves[key] = cross_moves.get(key, 0) + flt(row.transfer_qty or row.qty)
	check_reserved(out_of_own, lock=doc.docstatus == 1)
	if cross_moves:
		check_cross_hire_moves(doc, cross_moves)


def check_reserved(out_of_own, lock=False):
	"""Stock leaving an own rental warehouse must not be held by an open reservation."""
	from thinknxg_rental.services.utils import get_bin_qty, get_reserved_for_others

	if lock:
		rw.lock_bins(out_of_own)
	for (item_code, warehouse), qty in out_of_own.items():
		reserved = get_reserved_for_others(item_code, warehouse, for_update=lock)
		if reserved <= 0:
			continue
		free = get_bin_qty(item_code, warehouse, for_update=lock) - reserved
		if qty > free + 1e-6:
			frappe.throw(
				_("{0}: moving {1} out of {2}, but {3} of it is reserved for open rental reservations and only {4} is free. "
					"Release or deliver the reservations first.").format(frappe.bold(item_code), qty, warehouse, reserved, max(free, 0)),
				title=_("Reserved Stock"),
			)


def check_cross_hire_moves(doc, moves):
	if not doc.get("nxg_cross_hire_order"):
		frappe.throw(_("Select the Cross Hire Order whose material is moved between cross hire warehouses"))
	cho = frappe.db.get_value("Cross Hire Order", doc.nxg_cross_hire_order, ["docstatus", "company"], as_dict=True)
	if not cho or cho.docstatus != 1:
		frappe.throw(_("Cross Hire Order {0} is not submitted").format(doc.nxg_cross_hire_order))
	for (item_code, warehouse), qty in moves.items():
		held = custody_in_warehouse(doc.nxg_cross_hire_order, item_code, warehouse)
		if qty > held + 1e-6:
			frappe.throw(
				_("{0}: only {1} of Cross Hire Order {2} is in {3} (moving {4})").format(
					frappe.bold(item_code), held, doc.nxg_cross_hire_order, warehouse, qty
				)
			)


def custody_in_warehouse(cross_hire_order, item_code, warehouse):
	"""Supplier material of one Cross Hire Order in one warehouse and not at a customer site."""
	from thinknxg_rental.services.inventory import in_custody_not_at_site

	return flt(in_custody_not_at_site([item_code], cross_hire_order).get((cross_hire_order, item_code, warehouse)))


def on_submit(doc, method=None):
	if doc.get("nxg_hire_voucher_type") or doc.purpose != "Material Transfer" or not doc.get("nxg_cross_hire_order"):
		return
	cross = set(rw.cross_hire_warehouses(active_only=False))
	cho = frappe.db.get_value("Cross Hire Order", doc.nxg_cross_hire_order,
		["supplier", "rental_contract", "customer", "project", "rental_site"], as_dict=True)
	for row in doc.items:
		if row.s_warehouse in cross and row.t_warehouse in cross:
			qty = flt(row.transfer_qty or row.qty)
			common = dict(posting_date=doc.posting_date, billing_date=doc.posting_date, position_type=ledger.CUSTODY,
				movement_type="Transfer", item_code=row.item_code, ownership="Cross Hire", supplier=cho.supplier,
				cross_hire_order=doc.nxg_cross_hire_order, rental_contract=cho.rental_contract, customer=cho.customer,
				project=cho.project, rental_site=cho.rental_site, source_warehouse=row.s_warehouse,
				target_warehouse=row.t_warehouse, stock_entry=doc.name, voucher_detail_no=row.name)
			# a pair on the same day: custody per warehouse moves, the supplier's billable quantity does not
			ledger.add_entry(doc, qty=-qty, warehouse=row.s_warehouse, **common)
			ledger.add_entry(doc, qty=qty, warehouse=row.t_warehouse, **common)


def on_cancel(doc, method=None):
	if doc.get("nxg_hire_voucher_type"):
		return
	ledger.delete_entries(doc.doctype, doc.name)
