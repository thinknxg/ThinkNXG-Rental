"""Cross hire procurement: Purchase Order, Cross Hire Receipt, Purchase Return and supplier invoice."""
import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, formatdate, getdate, nowdate

from thinknxg_rental.services import ledger
from thinknxg_rental.services.billing import append_taxes
from thinknxg_rental.services.utils import BASIS_FACTOR, BASIS_UOM, as_system, billable_units, get_settings, require_setting


def create_purchase_order(cho):
	"""Cross Hire Order -> Purchase Order.

	Each equipment item produces two lines:
	  * the stock item itself at zero rate (custody only, received via Purchase Receipt), and
	  * a non-stock hire charge line carrying the supplier's rate (billed via Purchase Invoice).
	"""
	settings = get_settings()
	charge_item = require_setting("cross_hire_charge_item")
	po = frappe.new_doc("Purchase Order")
	schedule_date = max(getdate(cho.hire_from), getdate(cho.order_date))
	po.update(
		{
			"supplier": cho.supplier,
			"company": cho.company,
			"transaction_date": cho.order_date,
			"schedule_date": schedule_date,
			"set_warehouse": cho.receipt_warehouse,
			"project": cho.project,
			"nxg_is_cross_hire": 1,
			"nxg_cross_hire_order": cho.name,
			"nxg_rental_contract": cho.rental_contract,
		}
	)
	for d in cho.items:
		po.append(
			"items",
			{
				"item_code": d.item_code,
				"qty": d.qty,
				"uom": d.uom,
				"stock_uom": d.uom,
				"conversion_factor": 1,
				"rate": 0,
				"price_list_rate": 0,
				"warehouse": cho.receipt_warehouse,
				"schedule_date": schedule_date,
				"project": cho.project,
				"nxg_cross_hire_rate": d.rate,
				"nxg_cross_hire_rate_basis": d.rate_basis,
			},
		)
	for d in cho.items:
		basis = d.rate_basis or "Monthly"
		units = flt(flt(d.qty) * cint(d.expected_hire_days) / BASIS_FACTOR[basis], 3)
		po.append(
			"items",
			{
				"item_code": charge_item,
				"item_name": _("Hire charges - {0}").format(d.item_name),
				"description": _("Hire charges for {0} x {1} from {2} to {3} ({4} days) at {5} per unit ({6})").format(
					flt(d.qty), d.item_name, formatdate(cho.hire_from), formatdate(cho.expected_return_date),
					cint(d.expected_hire_days), flt(d.rate), basis,
				),
				"qty": units,
				"uom": BASIS_UOM[basis],
				"conversion_factor": BASIS_FACTOR[basis],
				"rate": d.rate,
				"schedule_date": schedule_date,
				"project": cho.project,
				"nxg_is_cross_hire_charge": 1,
				"nxg_cross_hire_item": d.item_code,
				"nxg_cross_hire_rate": d.rate,
				"nxg_cross_hire_rate_basis": basis,
			},
		)
	append_taxes(po, "Purchase Taxes and Charges Template", cho.taxes_and_charges)
	po.flags.ignore_permissions = True
	with as_system():
		po.insert()
		if cint(settings.auto_submit_purchase_order):
			po.submit()
	return po.name


@frappe.whitelist()
def make_cross_hire_receipt(cross_hire_order: str):
	"""Open a Purchase Receipt for the pending equipment lines (zero rate, quantity only)."""
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

	from thinknxg_rental.events.purchase import apply_cross_hire_receipt_rules

	cho = frappe.get_doc("Cross Hire Order", cross_hire_order)
	cho.check_permission("read")
	if cho.docstatus != 1 or not cho.purchase_order:
		frappe.throw(_("Cross Hire Order must be submitted with a Purchase Order"))
	if frappe.db.get_value("Purchase Order", cho.purchase_order, "docstatus") != 1:
		frappe.throw(_("Submit Purchase Order {0} first").format(cho.purchase_order))
	pr = make_purchase_receipt(cho.purchase_order)
	pr.nxg_is_cross_hire_receipt = 1
	pr.nxg_cross_hire_order = cho.name
	pr.set_warehouse = cho.receipt_warehouse
	apply_cross_hire_receipt_rules(pr)
	for row in pr.items:
		row.warehouse = cho.receipt_warehouse
	if not pr.items:
		frappe.throw(_("Everything on this Cross Hire Order has already been received"))
	return pr


def create_purchase_returns(note):
	"""Cross Hire Off-Hire Note -> Purchase Return(s) against the original receipts, oldest first."""
	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	remaining = {}
	extra = {}
	for d in note.items:
		remaining[d.item_code] = remaining.get(d.item_code, 0) + flt(d.qty)
		extra.setdefault(d.item_code, d)
	receipts = frappe.get_all(
		"Purchase Receipt",
		filters={"docstatus": 1, "is_return": 0, "nxg_cross_hire_order": note.cross_hire_order},
		pluck="name",
		order_by="posting_date asc, creation asc",
	)
	created = []
	for receipt in receipts:
		if not any(q > 1e-6 for q in remaining.values()):
			break
		ret = make_return_doc("Purchase Receipt", receipt)
		keep = []
		for row in ret.items:
			need = remaining.get(row.item_code, 0)
			# ERPNext only nets off earlier returns made from the receipt's own warehouse, so
			# take the balance from the receipt line itself (returned_qty covers every warehouse)
			src_row = frappe.db.get_value(
				"Purchase Receipt Item", row.purchase_receipt_item, ["qty", "stock_qty", "returned_qty"], as_dict=True
			) or frappe._dict()
			returnable = max((flt(src_row.stock_qty) or flt(src_row.qty)) - flt(src_row.returned_qty), 0)
			take = min(returnable, need)
			if take <= 1e-6:
				continue
			cf = flt(row.conversion_factor) or 1
			row.qty = -take
			row.received_qty = -take
			row.stock_qty = -take * cf
			row.received_stock_qty = -take * cf
			row.rejected_qty = 0
			row.rate = 0
			row.allow_zero_valuation_rate = 1
			row.warehouse = note.return_from_warehouse
			src = extra[row.item_code]
			if src.batch_no or src.serial_no:
				row.use_serial_batch_fields = 1
				row.batch_no = src.batch_no
				row.serial_no = src.serial_no
			remaining[row.item_code] = need - take
			keep.append(row)
		if not keep:
			continue
		ret.set("items", keep)
		for idx, row in enumerate(ret.items, 1):
			row.idx = idx
		ret.update(
			{
				"posting_date": note.off_hire_date,
				"set_posting_time": 1,
				"set_warehouse": note.return_from_warehouse,
				"nxg_is_cross_hire_receipt": 1,
				"nxg_cross_hire_order": note.cross_hire_order,
				"nxg_cross_hire_off_hire_note": note.name,
				"nxg_cross_hire_last_billable_date": note.last_billable_date or note.off_hire_date,
				"remarks": _("Cross hire off-hire {0}").format(note.name),
			}
		)
		ret.flags.ignore_permissions = True
		with as_system():
			ret.insert()
			ret.submit()
		created.append(ret.name)
	short = {k: v for k, v in remaining.items() if v > 1e-6}
	if short:
		frappe.throw(
			_("Could not find enough returnable quantity on the cross hire receipts for: {0}").format(
				", ".join(f"{k} ({v})" for k, v in short.items())
			)
		)
	return created


@frappe.whitelist()
def make_supplier_invoice(cross_hire_order: str, upto_date: str | None = None):
	"""Draft Purchase Invoice for supplier hire charges, computed from what was actually in custody each day."""
	cho = frappe.get_doc("Cross Hire Order", cross_hire_order)
	cho.check_permission("write")
	if cho.docstatus != 1:
		frappe.throw(_("Cross Hire Order is not submitted"))
	draft = frappe.db.get_value("Purchase Invoice", {"nxg_cross_hire_order": cho.name, "docstatus": 0}, "name")
	if draft:
		frappe.throw(_("Draft Purchase Invoice {0} already exists for this order. Submit or delete it first.").format(draft))
	charge_item = require_setting("cross_hire_charge_item")

	first = frappe.db.sql(
		"select min(billing_date), max(billing_date) from `tabRental Ownership Ledger` where position_type = %s and cross_hire_order = %s",
		(ledger.CUSTODY, cho.name),
	)[0]
	if not first[0]:
		frappe.throw(_("Nothing has been received against this Cross Hire Order yet"))
	from_date = add_days(cho.last_billed_upto, 1) if cho.last_billed_upto else getdate(first[0])
	to_date = getdate(upto_date) if upto_date else getdate(nowdate())
	if not sum(flt(d.on_hire_qty) for d in cho.items):
		to_date = min(to_date, add_days(getdate(first[1]), -1))
	if getdate(from_date) > to_date:
		frappe.throw(_("Supplier hire is already billed up to {0}").format(formatdate(cho.last_billed_upto)))

	po_lines = {}
	if cho.purchase_order:
		for row in frappe.get_all(
			"Purchase Order Item",
			filters={"parent": cho.purchase_order, "nxg_is_cross_hire_charge": 1},
			fields=["name", "nxg_cross_hire_item", "qty", "rate", "billed_amt"],
		):
			row.remaining = max(flt(row.qty) - (flt(row.billed_amt) / flt(row.rate) if flt(row.rate) else 0), 0)
			po_lines[row.nxg_cross_hire_item] = row

	month_basis = get_settings().month_basis
	rates = {d.item_code: d for d in cho.items}
	pi = frappe.new_doc("Purchase Invoice")
	pi.update(
		{
			"supplier": cho.supplier,
			"company": cho.company,
			"posting_date": nowdate(),
			"project": cho.project,
			"nxg_cross_hire_order": cho.name,
			"nxg_cross_hire_billing_from": from_date,
			"nxg_cross_hire_billing_to": to_date,
			"remarks": _("Cross hire charges {0} to {1} - {2}").format(formatdate(from_date), formatdate(to_date), cho.name),
		}
	)
	segments = ledger.get_segments(from_date, to_date, ledger.CUSTODY, cross_hire_order=cho.name)
	for item_code in sorted(segments):
		d = rates.get(item_code)
		if not d:
			continue
		basis = d.rate_basis or "Monthly"
		for seg_from, seg_to, qty in segments[item_code]:
			units = flt(billable_units(qty, seg_from, seg_to, basis, month_basis), 3)
			if units <= 0:
				continue
			base = {
				"item_code": charge_item,
				"item_name": _("Hire charges - {0}").format(d.item_name),
				"description": _("{0}: {1} units on hire {2} to {3} ({4} days)").format(
					d.item_name, flt(qty), formatdate(seg_from), formatdate(seg_to), date_diff(seg_to, seg_from) + 1
				),
				"uom": BASIS_UOM[basis],
				"conversion_factor": BASIS_FACTOR[basis],
				"rate": d.rate,
				"project": cho.project,
				"nxg_cross_hire_item": item_code,
			}
			# bill against the Purchase Order charge line up to its ordered quantity; any
			# overrun (hire extended beyond the estimate) goes on an unlinked line
			po_line = po_lines.get(item_code)
			linked = min(units, flt(po_line.remaining, 3)) if po_line else 0
			if linked > 0:
				pi.append("items", dict(base, qty=linked, purchase_order=cho.purchase_order, po_detail=po_line.name))
				po_line.remaining -= linked
			if units - linked > 0.0005:
				pi.append("items", dict(base, qty=flt(units - linked, 3)))
	if not pi.items:
		frappe.throw(_("No supplier hire charges fall between {0} and {1}").format(formatdate(from_date), formatdate(to_date)))
	append_taxes(pi, "Purchase Taxes and Charges Template", cho.taxes_and_charges)
	pi.insert()
	return pi.name
