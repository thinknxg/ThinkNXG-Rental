"""Admin portal (/rental/admin): a staff-only operations board built on the same data as the desk reports.

Access is limited to System Manager, Rental Manager and Rental User. Pages are read-mostly; anything
that changes a document either links to the desk form or calls a whitelisted method that checks
the user's own DocType permissions.
"""
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, getdate, nowdate

from thinknxg_rental.portal.utils import get_requests, is_staff

NAV = (
	("board", "/rental/admin", "Board"),
	("requests", "/rental/admin/requests", "Requests"),
	("contracts", "/rental/admin/contracts", "Contracts"),
	("sites", "/rental/admin/sites", "Material at site"),
	("yard", "/rental/admin/yard", "Yard"),
	("billing", "/rental/admin/billing", "Billing"),
	("suppliers", "/rental/admin/suppliers", "Cross hire"),
)


def desk(doctype, name=None, **filters):
	"""Desk URL for a form or a filtered list."""
	slug = doctype.lower().replace(" ", "-")
	if name:
		return f"/app/{slug}/{quote(str(name))}"
	query = "&".join(f"{k}={quote(str(v))}" for k, v in filters.items())
	return f"/app/{slug}" + (f"?{query}" if query else "")


def build_admin_context(context, active, title):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote(frappe.request.path)
		raise frappe.Redirect
	if not is_staff():
		raise frappe.PermissionError(_("The rental admin portal is for rental staff only."))
	context.ra = frappe._dict(
		active=active,
		nav=[frappe._dict(key=k, route=r, label=_(label)) for k, r, label in NAV],
		today=getdate(nowdate()),
		can_bill=frappe.has_permission("Rental Billing Schedule", "submit"),
		user=frappe.session.user,
	)
	context.desk = desk
	context.title = title
	context.no_cache = 1
	context.show_sidebar = False
	context.no_breadcrumbs = True
	return context.ra


# ----------------------------------------------------------------------------- board
def get_stock_rows(filters=None):
	from thinknxg_rental.thinknxg_rental.report.rental_stock_position.rental_stock_position import execute

	rows = execute(filters or {})[1]
	for r in rows:
		rentable = flt(r["own_total"]) + flt(r["at_site_cross_hire"]) + flt(r["cross_hire_not_at_site"])
		base = rentable or 1
		workshop = flt(r["inspection_qty"]) + flt(r["repair_qty"])
		r.update(
			rentable=rentable,
			workshop_qty=workshop,
			pct_own=round(flt(r["at_site_own"]) / base * 100, 2),
			pct_cross=round(flt(r["at_site_cross_hire"]) / base * 100, 2),
			pct_reserved=round(min(flt(r["reserved_qty"]), max(flt(r["yard_qty"]), 0)) / base * 100, 2),
			pct_workshop=round(workshop / base * 100, 2),
			short=flt(r["available_qty"]) < 0,
		)
	return rows


def get_board():
	today = nowdate()
	stock = get_stock_rows()
	total = lambda key: sum(flt(r[key]) for r in stock)  # noqa: E731
	on_hire = total("at_site_own") + total("at_site_cross_hire")
	rentable = total("rentable")
	count = frappe.db.count

	billing_due = count(
		"Hire Order Contract",
		{"docstatus": 1, "status": ["in", ["On Hire", "Off Hired"]], "next_billing_date": ["<=", today]},
	)
	overdue_hire = count(
		"Hire Order Contract", {"docstatus": 1, "status": "On Hire", "end_date": ["<", today]}
	)
	cross_overdue = count(
		"Cross Hire Order",
		{"docstatus": 1, "status": ["in", ["On Hire", "Partially Returned"]], "expected_return_date": ["<", today]},
	)
	queues = [
		(_("Customer requests waiting"), count("Rental Portal Request", {"status": "Open"}), "/rental/admin/requests", "act"),
		(_("Delivery orders in draft"), count("Hire Delivery Order", {"docstatus": 0}), desk("Hire Delivery Order", docstatus=0), "act"),
		(_("Returns awaiting inspection"), count("Hire Off-Hire Note", {"docstatus": 1, "inspection_status": "Pending"}),
			desk("Hire Off-Hire Note", inspection_status="Pending", docstatus=1), "act"),
		(_("Damage settlements to invoice"), count("Rental Damage Settlement", {"docstatus": 1, "status": "To Invoice"}),
			desk("Rental Damage Settlement", status="To Invoice"), "act"),
		(_("Contracts due for billing"), billing_due, "/rental/admin/billing", "act"),
		(_("Billing schedules without an invoice"), count("Rental Billing Schedule", {"docstatus": 1, "status": "Unbilled"}),
			desk("Rental Billing Schedule", status="Unbilled"), "act"),
		(_("Hires past their end date with material still out"), overdue_hire, "/rental/admin/contracts?view=overdue", "late"),
		(_("Cross hire past its return date"), cross_overdue, "/rental/admin/suppliers", "late"),
		(_("Cross hire orders still to receive"), count("Cross Hire Order", {"docstatus": 1, "status": "To Receive"}),
			desk("Cross Hire Order", status="To Receive"), "act"),
	]
	fields = ["name", "hire_contract", "customer_name", "rental_site", "vehicle_no"]
	return frappe._dict(
		on_hire=on_hire,
		yard=total("yard_qty"),
		available=total("available_qty"),
		reserved=total("reserved_qty"),
		cross_hire=total("at_site_cross_hire") + total("cross_hire_not_at_site"),
		workshop=total("workshop_qty"),
		utilization=round(on_hire / rentable * 100) if rentable else 0,
		queues=[frappe._dict(label=l, count=c, route=r, tone=t) for l, c, r, t in queues if c],
		out_today=frappe.get_all(
			"Hire Delivery Order", filters={"docstatus": ["<", 2], "posting_date": today},
			fields=[*fields, "total_qty", "docstatus"], order_by="creation asc",
		),
		in_today=frappe.get_all(
			"Hire Off-Hire Note", filters={"docstatus": ["<", 2], "return_date": today},
			fields=[*fields, "total_returned_qty", "docstatus"], order_by="creation asc",
		),
		tight=sorted(
			[r for r in stock if r["rentable"] and (r["short"] or flt(r["available_qty"]) <= 0.1 * r["rentable"])],
			key=lambda r: flt(r["available_qty"]),
		)[:8],
	)


# ----------------------------------------------------------------------------- lists
def get_admin_contracts(view="live", search=None):
	today = nowdate()
	filters = {"docstatus": 1}
	if view == "overdue":
		filters.update({"status": "On Hire", "end_date": ["<", today]})
	elif view == "all":
		pass
	else:
		view = "live"
		filters["status"] = ["in", ["Active", "On Hire", "Off Hired"]]
	or_filters = None
	if search:
		like = f"%{search.strip()[:60]}%"
		or_filters = {"name": ["like", like], "customer_name": ["like", like], "rental_site": ["like", like]}
	rows = frappe.get_all(
		"Hire Order Contract",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "customer", "customer_name", "rental_site", "status", "start_date", "end_date",
			"total_contract_qty", "total_dispatched_qty", "total_at_site_qty", "last_billed_upto",
			"next_billing_date", "total_billed_amount"],
		order_by="end_date asc",
		limit=300,
	)
	for r in rows:
		r.days_left = date_diff(r.end_date, today)
		r.late = r.status == "On Hire" and r.days_left < 0
		r.bill_due = bool(r.next_billing_date and getdate(r.next_billing_date) <= getdate(today) and r.status != "Active")
	return view, rows


def get_site_groups(search=None):
	from thinknxg_rental.thinknxg_rental.report.material_at_site.material_at_site import execute

	rows = execute({})[1]
	if search:
		needle = search.strip().lower()
		rows = [
			r for r in rows
			if needle in " ".join(str(r.get(k) or "") for k in ("customer_name", "rental_site", "hire_contract", "item_name", "item_code")).lower()
		]
	groups = {}
	for r in rows:
		groups.setdefault((r.customer_name or r.customer, r.customer, r.rental_site, r.hire_contract), []).append(r)
	out = [
		frappe._dict(
			customer_name=key[0], customer=key[1], site=key[2], contract=key[3], rows=lines,
			total=sum(flt(l.qty) for l in lines),
			cross=sum(flt(l.qty) for l in lines if l.ownership == "Cross Hire"),
			value=sum(flt(l.replacement_value) for l in lines),
		)
		for key, lines in groups.items()
	]
	return out, frappe._dict(
		total=sum(g.total for g in out), cross=sum(g.cross for g in out), value=sum(g.value for g in out)
	)


def get_billing():
	from thinknxg_rental.thinknxg_rental.report.unbilled_rental.unbilled_rental import execute

	today = getdate(nowdate())
	accrued = execute({"upto_date": add_days(today, -1)})[1]
	invoices = frappe.get_all(
		"Sales Invoice",
		filters={"docstatus": 1, "outstanding_amount": [">", 0], "nxg_hire_contract": ["is", "set"], "is_return": 0},
		fields=["name", "customer_name", "nxg_hire_contract", "posting_date", "due_date", "grand_total",
			"outstanding_amount", "currency"],
		order_by="due_date asc",
		limit=200,
	)
	for i in invoices:
		i.days_late = date_diff(today, i.due_date) if i.due_date else 0
	return frappe._dict(
		accrued=accrued,
		accrued_total=sum(flt(r["unbilled_amount"]) for r in accrued),
		due=[r for r in accrued if r["overdue"]],
		invoices=invoices,
		receivable=sum(flt(i.outstanding_amount) for i in invoices),
		late_total=sum(flt(i.outstanding_amount) for i in invoices if i.days_late > 0),
		drafts=frappe.db.count("Sales Invoice", {"docstatus": 0, "nxg_hire_contract": ["is", "set"]}),
	)


def get_cross_hire():
	from thinknxg_rental.thinknxg_rental.report.cross_hire_position.cross_hire_position import execute

	rows = execute({})[1]
	groups = {}
	for r in rows:
		groups.setdefault((r.supplier_name or r.supplier, r.cross_hire_order), []).append(r)
	out = []
	for (supplier, order), lines in groups.items():
		head = lines[0]
		out.append(
			frappe._dict(
				supplier=supplier, order=order, purchase_order=head.purchase_order, status=head.status,
				contract=head.hire_contract, site=head.rental_site, due=head.expected_return_date,
				overdue_days=max(l.overdue_days for l in lines), rows=lines,
				on_hire=sum(flt(l.on_hire_qty) for l in lines),
			)
		)
	out.sort(key=lambda g: -g.overdue_days)
	return out, frappe._dict(
		on_hire=sum(g.on_hire for g in out),
		at_site=sum(flt(r.at_site_qty) for r in rows),
		idle=sum(flt(r.in_yard_qty) for r in rows if flt(r.on_hire_qty) > 0),
		overdue=len([g for g in out if g.overdue_days > 0]),
	)


def get_admin_requests(view="open"):
	statuses = {"open": ["Open", "In Progress"], "closed": ["Completed", "Rejected", "Cancelled"]}.get(view)
	if not statuses:
		view, statuses = "open", ["Open", "In Progress"]
	names = frappe.get_all(
		"Rental Portal Request", filters={"status": ["in", statuses]}, fields=["name", "customer", "customer_name", "raised_by"],
		order_by="creation desc" if view == "closed" else "creation asc", limit=200,
	)
	if not names:
		return view, []
	extra = {n.name: n for n in names}
	rows = get_requests(list({n.customer for n in names}), limit=None)
	rows = [r for r in rows if r.name in extra]
	order = {n.name: i for i, n in enumerate(names)}
	rows.sort(key=lambda r: order[r.name])
	today = nowdate()
	for r in rows:
		r.customer_name = extra[r.name].customer_name
		r.customer = extra[r.name].customer
		r.raised_by = extra[r.name].raised_by
		r.age_days = date_diff(today, r.request_date)
	return view, rows


# ----------------------------------------------------------------------------- actions
@frappe.whitelist(methods=["POST"])
def start_request(name: str):
	"""Mark a customer request as being handled, so the customer sees progress."""
	if not is_staff():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	doc = frappe.get_doc("Rental Portal Request", name)
	doc.check_permission("write")
	if doc.status != "Open":
		frappe.throw(_("Request {0} is already {1}").format(name, doc.status))
	doc.db_set("status", "In Progress")
	return {"name": name}
