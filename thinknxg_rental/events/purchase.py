"""Hooks that make standard ERPNext buying documents behave as cross-hire documents.

Purchase Order   = Cross Hire Order     (equipment lines at zero rate + hire charge lines)
Purchase Receipt = Cross Hire Receipt   (quantity only, zero rate, zero valuation)
Purchase Return  = Cross Hire Off-Hire  (quantity only, zero rate)
Purchase Invoice = Supplier hire bill   (charge lines only, never touches stock)
"""
import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate

from thinknxg_rental.services import ledger


def _zero_line(row, receipt=False):
	changed = bool(flt(row.rate) or flt(row.price_list_rate))
	row.rate = 0
	row.price_list_rate = 0
	row.discount_percentage = 0
	row.discount_amount = 0
	if receipt:
		row.allow_zero_valuation_rate = 1
	return changed


# ----------------------------------------------------------------------------- Purchase Order
def po_before_validate(doc, method=None):
	if not doc.get("nxg_is_cross_hire"):
		return
	for row in doc.items:
		if not row.get("nxg_is_cross_hire_charge"):
			_zero_line(row)


def po_validate(doc, method=None):
	if not doc.get("nxg_is_cross_hire"):
		return
	changed = False
	for row in doc.items:
		if not row.get("nxg_is_cross_hire_charge") and flt(row.rate):
			changed = _zero_line(row) or changed
	if changed:
		doc.calculate_taxes_and_totals()


# ----------------------------------------------------------------------------- Purchase Receipt
def _inherit_cross_hire_flags(doc):
	if doc.get("nxg_is_cross_hire_receipt") and doc.get("nxg_cross_hire_order"):
		return
	if doc.is_return and doc.return_against:
		src = frappe.db.get_value(
			"Purchase Receipt", doc.return_against, ["nxg_is_cross_hire_receipt", "nxg_cross_hire_order"], as_dict=True
		)
		if src and src.nxg_is_cross_hire_receipt:
			doc.nxg_is_cross_hire_receipt = 1
			doc.nxg_cross_hire_order = src.nxg_cross_hire_order
			return
	for po in {d.purchase_order for d in doc.items if d.get("purchase_order")}:
		src = frappe.db.get_value("Purchase Order", po, ["nxg_is_cross_hire", "nxg_cross_hire_order"], as_dict=True)
		if src and src.nxg_is_cross_hire:
			doc.nxg_is_cross_hire_receipt = 1
			doc.nxg_cross_hire_order = src.nxg_cross_hire_order
			return


def apply_cross_hire_receipt_rules(doc):
	"""Strip hire-charge lines and force quantity-only (zero rate / zero valuation) equipment lines."""
	keep = []
	for row in doc.items:
		if row.get("purchase_order_item") and frappe.db.get_value(
			"Purchase Order Item", row.purchase_order_item, "nxg_is_cross_hire_charge"
		):
			continue
		keep.append(row)
	if len(keep) != len(doc.items):
		doc.set("items", keep)
		for idx, row in enumerate(doc.items, 1):
			row.idx = idx
	for row in doc.items:
		_zero_line(row, receipt=True)
		row.rejected_qty = 0


def pr_before_validate(doc, method=None):
	_inherit_cross_hire_flags(doc)
	if doc.get("nxg_is_cross_hire_receipt"):
		apply_cross_hire_receipt_rules(doc)


def pr_validate(doc, method=None):
	if not doc.get("nxg_is_cross_hire_receipt"):
		return
	if not doc.get("nxg_cross_hire_order"):
		frappe.throw(_("Cross Hire Order is mandatory for a Cross Hire Receipt"))
	cho = frappe.get_doc("Cross Hire Order", doc.nxg_cross_hire_order)
	if cho.docstatus != 1:
		frappe.throw(_("Cross Hire Order {0} is not submitted").format(cho.name))
	if cho.supplier != doc.supplier:
		frappe.throw(_("Supplier does not match Cross Hire Order {0}").format(cho.name))
	if cho.status == "Completed" and not doc.is_return:
		frappe.throw(_("Cross Hire Order {0} is completed").format(cho.name))

	ordered = {d.item_code for d in cho.items}
	recalc = False
	for row in doc.items:
		if row.item_code not in ordered:
			frappe.throw(_("Row #{0}: {1} is not on Cross Hire Order {2}").format(row.idx, row.item_code, cho.name))
		if flt(row.rate) or not row.allow_zero_valuation_rate:
			recalc = _zero_line(row, receipt=True) or recalc
	if recalc:
		doc.calculate_taxes_and_totals()

	if doc.is_return:
		# supplier material still standing at a customer site cannot be handed back
		returning = {}
		for row in doc.items:
			returning[row.item_code] = returning.get(row.item_code, 0) + abs(flt(row.stock_qty) or flt(row.qty))
		for item_code, qty in returning.items():
			free = ledger.get_cross_hire_undelivered(cho.name, item_code)
			if qty > free + 1e-6:
				frappe.throw(
					_("{0}: only {1} is off customer sites and available to return to the supplier (returning {2}). "
						"Off-hire it from the customer first.").format(frappe.bold(item_code), free, qty)
				)


def pr_on_submit(doc, method=None):
	if not doc.get("nxg_is_cross_hire_receipt"):
		return
	cho = frappe.db.get_value(
		"Cross Hire Order", doc.nxg_cross_hire_order, ["rental_contract", "customer", "project", "rental_site"], as_dict=True
	)
	if doc.is_return:
		last_billable = getdate(doc.get("nxg_cross_hire_last_billable_date") or doc.posting_date)
		billing_date, movement = add_days(last_billable, 1), "Supplier Return"
	else:
		billing_date, movement = doc.posting_date, "Receipt"
	for row in doc.items:
		qty = flt(row.stock_qty) or flt(row.qty)
		if not qty:
			continue
		ledger.add_entry(
			doc,
			posting_date=doc.posting_date,
			billing_date=billing_date,
			position_type=ledger.CUSTODY,
			movement_type=movement,
			item_code=row.item_code,
			qty=qty,
			ownership="Cross Hire",
			supplier=doc.supplier,
			cross_hire_order=doc.nxg_cross_hire_order,
			rental_contract=cho.rental_contract,
			customer=cho.customer,
			project=cho.project,
			rental_site=cho.rental_site,
			warehouse=row.warehouse,
			voucher_detail_no=row.name,
		)
	ledger.update_cross_hire_progress(doc.nxg_cross_hire_order)


def pr_on_cancel(doc, method=None):
	if not doc.get("nxg_is_cross_hire_receipt"):
		return
	if not doc.is_return:
		# cancelling a receipt must not leave more at customer sites than we hold
		for item_code in {d.item_code for d in doc.items}:
			qty = sum(flt(d.stock_qty) or flt(d.qty) for d in doc.items if d.item_code == item_code)
			if ledger.get_cross_hire_undelivered(doc.nxg_cross_hire_order, item_code) - qty < -1e-6:
				frappe.throw(
					_("Cannot cancel: {0} from this receipt has been dispatched to a customer site or returned.").format(
						frappe.bold(item_code)
					)
				)
	ledger.delete_entries(doc.doctype, doc.name)
	ledger.update_cross_hire_progress(doc.nxg_cross_hire_order)


# ----------------------------------------------------------------------------- Purchase Invoice
def pi_update_cross_hire(doc, method=None):
	cho = doc.get("nxg_cross_hire_order")
	if not cho:
		return
	row = frappe.db.sql(
		"""select sum(base_net_total), max(nxg_cross_hire_billing_to) from `tabPurchase Invoice`
		where docstatus = 1 and nxg_cross_hire_order = %s""",
		cho,
	)[0]
	frappe.db.set_value(
		"Cross Hire Order", cho, {"billed_amount": flt(row[0]), "last_billed_upto": row[1]}, update_modified=False
	)
