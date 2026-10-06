"""Customer portal: who is logged in, which customers they may see, and the data behind each page.

Every query here is filtered by the customers resolved for the session user. Portal users never
get desk permissions on the rental DocTypes; the pages read with explicit customer filters instead.
Supplier and ownership details (own vs cross hire) are internal and are never sent to the portal.
"""
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

STAFF_ROLES = {"System Manager", "Rental Manager", "Rental User"}
NAV = (
	("overview", "/rental", "Overview"),
	("contracts", "/rental/contracts", "Contracts"),
	("material", "/rental/material", "Material at site"),
	("invoices", "/rental/invoices", "Invoices"),
	("requests", "/rental/requests", "Requests"),
)


def is_staff(user=None):
	return bool(STAFF_ROLES & set(frappe.get_roles(user or frappe.session.user)))


def get_portal_customers(customer=None):
	"""Returns (customers, preview). Staff may preview any one customer with ?customer=<name>."""
	user = frappe.session.user
	if user == "Guest":
		return [], False
	if is_staff(user):
		customer = customer or frappe.form_dict.get("customer")
		if customer and frappe.db.exists("Customer", customer):
			return [customer], True
		return [], True

	customers = set(frappe.get_all("Portal User", filters={"user": user, "parenttype": "Customer"}, pluck="parent"))
	contacts = set(frappe.get_all("Contact", filters={"user": user}, pluck="name"))
	contacts.update(frappe.get_all("Contact", filters={"email_id": user}, pluck="name"))
	if contacts:
		customers.update(
			frappe.get_all(
				"Dynamic Link",
				filters={"parenttype": "Contact", "parent": ["in", list(contacts)], "link_doctype": "Customer"},
				pluck="link_name",
			)
		)
	if customer:
		customers &= {customer}
	return sorted(c for c in customers if c), False


def build_context(context, active, title):
	"""Common page context. Redirects guests to the login page."""
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote(frappe.request.path)
		raise frappe.Redirect
	settings = frappe.get_cached_doc("Rental Settings")
	customers, preview = get_portal_customers()
	qs = f"customer={quote(customers[0])}" if preview and customers else ""
	rp = frappe._dict(
		customers=customers,
		preview=preview,
		qs=("?" + qs) if qs else "",
		qs_amp=("&" + qs) if qs else "",
		preview_customer=customers[0] if preview and customers else "",
		active=active,
		nav=[frappe._dict(key=k, route=r, label=_(label)) for k, r, label in NAV],
		allow_requests=cint(settings.portal_allow_requests),
		help_email=settings.portal_contact_email,
		help_phone=settings.portal_contact_phone,
		customer_names=[frappe.db.get_value("Customer", c, "customer_name") or c for c in customers],
	)
	context.rp = rp
	context.title = title
	context.no_cache = 1
	context.show_sidebar = False
	context.no_breadcrumbs = True
	return rp


# ----------------------------------------------------------------------------- data
def get_contracts(customers, live_only=False):
	filters = {"customer": ["in", customers], "docstatus": 1}
	if live_only:
		filters["status"] = ["in", ["Active", "On Hire"]]
	rows = frappe.get_all(
		"Hire Order Contract",
		filters=filters,
		fields=["name", "customer_name", "rental_site", "status", "start_date", "end_date", "billing_cycle",
			"total_contract_qty", "total_dispatched_qty", "total_at_site_qty", "total_returned_qty", "last_billed_upto"],
		order_by="start_date desc",
	)
	today = getdate(nowdate())
	for r in rows:
		r.days_left = date_diff(r.end_date, today) if r.end_date else None
		r.ending_soon = flt(r.total_at_site_qty) > 0 and r.days_left is not None and r.days_left <= 14
	return rows


def get_material(customers, hire_contract=None):
	"""Quantity at site per site / contract / item, own and cross-hired material combined."""
	values = {"customers": tuple(customers)}
	contract_cond = ""
	if hire_contract:
		contract_cond = "and l.hire_contract = %(hire_contract)s"
		values["hire_contract"] = hire_contract
	rows = frappe.db.sql(
		f"""
		select l.rental_site, l.hire_contract, l.item_code, i.item_name, i.stock_uom as uom,
			sum(l.qty) as qty,
			sum(case when l.movement_type = 'Dispatch' then l.qty else 0 end) as dispatched_qty,
			min(case when l.movement_type = 'Dispatch' then l.posting_date end) as first_dispatch
		from `tabRental Ownership Ledger` l
		left join `tabItem` i on i.name = l.item_code
		where l.position_type = 'At Site' and l.customer in %(customers)s {contract_cond}
		group by l.rental_site, l.hire_contract, l.item_code, i.item_name, i.stock_uom
		having sum(l.qty) > 0
		order by l.rental_site, l.hire_contract, i.item_name
		""",
		values,
		as_dict=True,
	)
	today = nowdate()
	for r in rows:
		r.days_at_site = date_diff(today, r.first_dispatch) + 1 if r.first_dispatch else 0
		r.percent_at_site = min(round(flt(r.qty) / flt(r.dispatched_qty) * 100), 100) if flt(r.dispatched_qty) else 0
	return rows


def get_invoices(customers, hire_contract=None, limit=None):
	filters = {"customer": ["in", customers], "docstatus": 1, "nxg_hire_contract": ["is", "set"]}
	if hire_contract:
		filters["nxg_hire_contract"] = hire_contract
	rows = frappe.get_all(
		"Sales Invoice",
		filters=filters,
		fields=["name", "posting_date", "due_date", "grand_total", "outstanding_amount", "currency", "status", "is_return",
			"nxg_hire_contract", "nxg_rental_billing_schedule", "nxg_rental_damage_settlement"],
		order_by="posting_date desc, creation desc",
		limit=limit,
	)
	for r in rows:
		r.hire_contract = r.nxg_hire_contract
		r.schedule = r.nxg_rental_billing_schedule
		r.settlement = r.nxg_rental_damage_settlement
	periods = {}
	schedules = [r.schedule for r in rows if r.schedule]
	if schedules:
		for s in frappe.get_all(
			"Rental Billing Schedule", filters={"name": ["in", schedules]}, fields=["name", "from_date", "to_date"]
		):
			periods[s.name] = s
	today = getdate(nowdate())
	for r in rows:
		r.kind = _("Credit note") if r.is_return else (_("Damage and loss") if r.settlement else _("Rental"))
		period = periods.get(r.schedule)
		r.period_from, r.period_to = (period.from_date, period.to_date) if period else (None, None)
		r.unpaid = flt(r.outstanding_amount) > 0
		r.overdue = r.unpaid and r.due_date and getdate(r.due_date) < today
	return rows


def get_requests(customers, hire_contract=None, limit=None):
	filters = {"customer": ["in", customers]}
	if hire_contract:
		filters["hire_contract"] = hire_contract
	rows = frappe.get_all(
		"Rental Portal Request",
		filters=filters,
		fields=["name", "request_type", "status", "request_date", "hire_contract", "rental_site", "site_location",
			"required_date", "expected_return_date", "new_end_date", "remarks", "response"],
		order_by="creation desc",
		limit=limit,
	)
	if rows:
		items = frappe.get_all(
			"Rental Portal Request Item",
			filters={"parent": ["in", [r.name for r in rows]], "parenttype": "Rental Portal Request"},
			fields=["parent", "item_name", "item_code", "qty", "uom"],
			order_by="idx",
		)
		by_parent = {}
		for i in items:
			by_parent.setdefault(i.parent, []).append(i)
		for r in rows:
			r.lines = by_parent.get(r.name, [])
	return rows


def get_movements(customers, hire_contract=None, limit=8):
	"""Deliveries and returns, newest first."""
	base = {"customer": ["in", customers], "docstatus": 1}
	if hire_contract:
		base["hire_contract"] = hire_contract
	out = []
	for d in frappe.get_all(
		"Hire Delivery Order", filters=base, limit=limit, order_by="posting_date desc, creation desc",
		fields=["name", "posting_date", "hire_contract", "rental_site", "total_qty", "vehicle_no", "dispatch_reference"],
	):
		d.update(kind="out", label=_("Delivered"), date=d.posting_date, qty=d.total_qty, lost_qty=0)
		out.append(d)
	for d in frappe.get_all(
		"Hire Off-Hire Note", filters=base, limit=limit, order_by="return_date desc, creation desc",
		fields=["name", "return_date", "off_hire_date", "last_billable_date", "hire_contract", "rental_site",
			"total_returned_qty", "total_lost_qty", "vehicle_no", "off_hire_type"],
	):
		d.update(kind="in", label=_("Returned"), date=d.return_date, qty=d.total_returned_qty, lost_qty=d.total_lost_qty)
		out.append(d)
	out.sort(key=lambda d: (getdate(d.date), d.name), reverse=True)
	return out[:limit] if limit else out


def get_overview(customers):
	contracts = get_contracts(customers)
	live = [c for c in contracts if c.status in ("Active", "On Hire")]
	on_hire = [c for c in contracts if flt(c.total_at_site_qty) > 0]
	invoices = get_invoices(customers)
	unpaid = [i for i in invoices if i.unpaid and not i.is_return]
	return frappe._dict(
		units_at_site=sum(flt(c.total_at_site_qty) for c in contracts),
		site_count=len({c.rental_site for c in on_hire}),
		live_contracts=live,
		on_hire=on_hire,
		ending_soon=[c for c in contracts if c.ending_soon],
		unpaid=unpaid,
		unpaid_total=sum(flt(i.outstanding_amount) for i in unpaid),
		overdue_count=len([i for i in unpaid if i.overdue]),
		currency=unpaid[0].currency if unpaid else None,
		open_requests=frappe.db.count(
			"Rental Portal Request", {"customer": ["in", customers], "status": ["in", ["Open", "In Progress"]]}
		),
		movements=get_movements(customers, limit=6),
	)


def get_contract_detail(name, customers):
	if not name or not frappe.db.exists("Hire Order Contract", name):
		raise frappe.DoesNotExistError
	doc = frappe.get_doc("Hire Order Contract", name)
	if doc.docstatus != 1 or doc.customer not in customers:
		raise frappe.PermissionError
	site = frappe.db.get_value("Rental Site", doc.rental_site, ["location", "site_contact", "contact_phone"], as_dict=True)
	items = []
	for d in doc.items:
		dispatched = flt(d.dispatched_qty)
		base = max(flt(d.qty), dispatched) or 1
		items.append(
			frappe._dict(
				item_code=d.item_code, item_name=d.item_name, uom=d.uom, qty=flt(d.qty), rate=flt(d.rate),
				rate_basis=d.rate_basis, dispatched_qty=dispatched, returned_qty=flt(d.returned_qty),
				lost_qty=flt(d.lost_qty), at_site_qty=flt(d.at_site_qty), pending_qty=flt(d.pending_qty),
				pct_site=round(flt(d.at_site_qty) / base * 100, 2),
				pct_back=round((flt(d.returned_qty) + flt(d.lost_qty)) / base * 100, 2),
			)
		)
	return frappe._dict(
		doc=doc,
		site=site or frappe._dict(),
		lines=items,
		movements=get_movements(customers, hire_contract=name, limit=None),
		invoices=get_invoices(customers, hire_contract=name),
		requests=get_requests(customers, hire_contract=name, limit=10),
		days_left=date_diff(doc.end_date, nowdate()),
	)
