"""Rental Ownership Ledger.

One signed row per movement. Two positions are tracked:

* At Site             - material on hire to a customer contract (Own or Cross Hire).
* Cross Hire Custody  - supplier-owned material we are holding (received - returned - lost).

`billing_date` is the first day the movement affects billing: a dispatch bills from its
dispatch date; a return stops billing the day after its last billable date.
"""
import frappe
from frappe.utils import add_days, flt, getdate

AT_SITE = "At Site"
CUSTODY = "Cross Hire Custody"


def add_entry(doc, **kwargs):
	entry = frappe.new_doc("Rental Ownership Ledger")
	entry.update({"voucher_type": doc.doctype, "voucher_no": doc.name, "company": doc.get("company")})
	entry.update(kwargs)
	entry.billing_date = entry.billing_date or entry.posting_date
	if entry.rental_contract and not entry.source_type:
		src = frappe.db.get_value("Rental Contract", entry.rental_contract, ["source_type", "source_document"])
		if src:
			entry.source_type, entry.source_document = src
	entry.flags.ignore_permissions = True
	entry.insert()
	return entry


def delete_entries(voucher_type, voucher_no):
	frappe.db.delete("Rental Ownership Ledger", {"voucher_type": voucher_type, "voucher_no": voucher_no})


def get_site_balance(rental_contract):
	"""{(item_code, ownership, cross_hire_order): qty} currently at site for a contract."""
	rows = frappe.db.sql(
		"""
		select item_code, ownership, ifnull(cross_hire_order, '') as cho, sum(qty) as qty
		from `tabRental Ownership Ledger`
		where position_type = %s and rental_contract = %s
		group by item_code, ownership, ifnull(cross_hire_order, '')
		""",
		(AT_SITE, rental_contract),
		as_dict=True,
	)
	return {(r.item_code, r.ownership, r.cho): flt(r.qty) for r in rows if flt(r.qty)}


def get_cross_hire_qty(cross_hire_order, item_code, position_type):
	return flt(
		frappe.db.sql(
			"""select sum(qty) from `tabRental Ownership Ledger`
			where position_type = %s and cross_hire_order = %s and item_code = %s""",
			(position_type, cross_hire_order, item_code),
		)[0][0]
	)


def get_cross_hire_undelivered(cross_hire_order, item_code):
	"""Supplier material in our custody that is not at any customer site."""
	return get_cross_hire_qty(cross_hire_order, item_code, CUSTODY) - get_cross_hire_qty(
		cross_hire_order, item_code, AT_SITE
	)


def get_segments(from_date, to_date, position_type, rental_contract=None, cross_hire_order=None):
	"""{item_code: [(seg_from, seg_to, qty), ...]} - constant-quantity stretches inside the period."""
	from_date, to_date = getdate(from_date), getdate(to_date)
	conditions, values = ["position_type = %(pt)s", "billing_date <= %(to)s"], {"pt": position_type, "to": to_date}
	if rental_contract:
		conditions.append("rental_contract = %(hc)s")
		values["hc"] = rental_contract
	if cross_hire_order:
		conditions.append("cross_hire_order = %(cho)s")
		values["cho"] = cross_hire_order
	rows = frappe.db.sql(
		f"""
		select item_code, billing_date, sum(qty) as qty
		from `tabRental Ownership Ledger`
		where {" and ".join(conditions)}
		group by item_code, billing_date
		order by item_code, billing_date
		""",
		values,
		as_dict=True,
	)
	by_item = {}
	for r in rows:
		by_item.setdefault(r.item_code, []).append((getdate(r.billing_date), flt(r.qty)))

	out = {}
	for item_code, events in by_item.items():
		qty = sum(q for d, q in events if d <= from_date)
		start, segments = from_date, []
		for d, q in events:
			if d <= from_date or not q:
				continue
			if qty > 0:
				segments.append((start, add_days(d, -1), qty))
			qty += q
			start = d
		if qty > 0:
			segments.append((start, to_date, qty))
		if segments:
			out[item_code] = segments
	return out


def update_contract_progress(rental_contract):
	"""Recompute contract item counters, billing start and status from the ledger (idempotent)."""
	from thinknxg_rental.services.billing import get_period_end

	doc = frappe.get_doc("Rental Contract", rental_contract)
	rows = frappe.db.sql(
		"""
		select item_code, movement_type, sum(qty) as qty, min(billing_date) as first_date
		from `tabRental Ownership Ledger`
		where position_type = %s and rental_contract = %s
		group by item_code, movement_type
		""",
		(AT_SITE, rental_contract),
		as_dict=True,
	)
	moved, first_dispatch = {}, None
	for r in rows:
		moved[(r.item_code, r.movement_type)] = flt(r.qty)
		if r.movement_type == "Dispatch" and r.first_date:
			first_dispatch = min(first_dispatch, getdate(r.first_date)) if first_dispatch else getdate(r.first_date)

	totals = frappe._dict(dispatched=0, returned=0, at_site=0)
	for d in doc.items:
		dispatched = moved.get((d.item_code, "Dispatch"), 0)
		returned = -moved.get((d.item_code, "Return"), 0)
		lost = -moved.get((d.item_code, "Loss"), 0)
		values = {
			"dispatched_qty": dispatched,
			"returned_qty": returned,
			"lost_qty": lost,
			"at_site_qty": dispatched - returned - lost,
			"pending_qty": max(flt(d.qty) - dispatched, 0),
		}
		d.db_set(values, update_modified=False)
		totals.dispatched += dispatched
		totals.returned += returned
		totals.at_site += values["at_site_qty"]

	update = {
		"total_dispatched_qty": totals.dispatched,
		"total_returned_qty": totals.returned,
		"total_at_site_qty": totals.at_site,
		"billing_start_date": first_dispatch,
	}
	if doc.docstatus == 1 and doc.status != "Completed":
		update["status"] = "On Hire" if totals.at_site > 0 else ("Off Hired" if totals.dispatched > 0 else "Active")
	if doc.contract_type == "Job Type Contract":
		# job type contracts are billed from the Job Completion Report, never from material on hire
		update["next_billing_date"] = None
	elif not doc.last_billed_upto:
		update["next_billing_date"] = add_days(get_period_end(doc, first_dispatch), 1) if first_dispatch else None
	doc.db_set(update, update_modified=False)
	doc.notify_update()


def update_cross_hire_progress(cross_hire_order):
	doc = frappe.get_doc("Cross Hire Order", cross_hire_order)
	rows = frappe.db.sql(
		"""
		select item_code, movement_type, sum(qty) as qty
		from `tabRental Ownership Ledger`
		where position_type = %s and cross_hire_order = %s
		group by item_code, movement_type
		""",
		(CUSTODY, cross_hire_order),
		as_dict=True,
	)
	moved = {(r.item_code, r.movement_type): flt(r.qty) for r in rows}
	received_total = returned_total = on_hire_total = 0
	for d in doc.items:
		received = moved.get((d.item_code, "Receipt"), 0)
		returned = -moved.get((d.item_code, "Supplier Return"), 0)
		lost = -moved.get((d.item_code, "Loss"), 0)
		d.db_set(
			{"received_qty": received, "returned_qty": returned, "lost_qty": lost, "on_hire_qty": received - returned - lost},
			update_modified=False,
		)
		received_total += received
		returned_total += returned + lost
		on_hire_total += received - returned - lost

	if doc.docstatus == 1 and doc.status != "Completed":
		if not received_total:
			status = "To Receive"
		elif on_hire_total <= 0:
			status = "Returned"
		elif returned_total:
			status = "Partially Returned"
		else:
			status = "On Hire"
		doc.db_set("status", status, update_modified=False)
	doc.notify_update()
