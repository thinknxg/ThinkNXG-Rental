"""Admin portal (/rental/admin): a staff-only operations board built on the same data as the desk reports.

Access is limited to System Manager, Rental Manager and Rental User. Pages are read-mostly; anything
that changes a document either links to the desk form or calls a whitelisted method that checks
the user's own DocType permissions.
"""
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, getdate, nowdate

from thinknxg_rental.portal.entry import entry_nav
from thinknxg_rental.portal.utils import get_requests, is_staff

# The menu bar holds the board and the documents people enter every day (see portal/entry.py);
# the optional documents (reservations, cross hire) and the read-mostly boards sit under "More".
MORE_NAV = (
	("requests", "/rental/admin/requests", "Customer requests"),
	("contracts", "/rental/admin/contracts", "Contract status"),
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
	more = entry_nav("more") + [frappe._dict(key=k, route=r, label=_(label)) for k, r, label in MORE_NAV]
	context.ra = frappe._dict(
		active=active,
		nav=[frappe._dict(key="board", route="/rental/admin", label=_("Board"))] + entry_nav(),
		more=more,
		more_active=any(m.key == active for m in more),
		today=getdate(nowdate()),
		can_bill=frappe.has_permission("Rental Billing Schedule", "submit"),
		user=frappe.session.user,
	)
	context.desk = desk
	context.title = title
	context.no_cache = 1
	context.show_sidebar = False
	context.no_breadcrumbs = True
	context.full_width = 1
	return context.ra


# ----------------------------------------------------------------------------- board
def get_stock_rows(filters=None):
	from thinknxg_rental.thinknxg_rental.report.rental_stock_position.rental_stock_position import execute

	rows = execute(filters or {})[1]
	groups = {}
	if rows:
		groups = dict(frappe.get_all("Item", filters={"name": ["in", [r["item_code"] for r in rows]]}, fields=["name", "item_group"], as_list=True))
	for r in rows:
		r["item_group"] = groups.get(r["item_code"])
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
		"Rental Contract",
		{"docstatus": 1, "status": ["in", ["On Hire", "Off Hired"]], "next_billing_date": ["<=", today],
			"contract_type": ["!=", "Job Type Contract"]},
	)
	overdue_hire = count(
		"Rental Contract", {"docstatus": 1, "status": "On Hire", "end_date": ["<", today]}
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
		(_("Job periods waiting for an invoice"), count("JCR Billing Schedule", {"status": "Pending"}),
			desk("JCR Billing Schedule", status="Pending"), "act"),
		(_("Jobs past their contract days and still standing"), count("Job Completion Report", {"docstatus": 1, "status": "In Excess"}),
			desk("Job Completion Report", status="In Excess"), "late"),
		(_("Billing schedules without an invoice"), count("Rental Billing Schedule", {"docstatus": 1, "status": "Unbilled"}),
			desk("Rental Billing Schedule", status="Unbilled"), "act"),
		(_("Hires past their end date with material still out"), overdue_hire, "/rental/admin/contracts?view=overdue", "late"),
		(_("Cross hire past its return date"), cross_overdue, "/rental/admin/suppliers", "late"),
		(_("Cross hire orders still to receive"), count("Cross Hire Order", {"docstatus": 1, "status": "To Receive"}),
			desk("Cross Hire Order", status="To Receive"), "act"),
	]
	fields = ["name", "rental_contract", "customer_name", "rental_site", "vehicle_no"]
	return frappe._dict(
		rentable=rentable,
		at_site_own=total("at_site_own"),
		at_site_cross=total("at_site_cross_hire"),
		recent=get_recent_operations(),
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


RECENT = (
	# doctype, entry menu, date field, what it is, quantity field
	("Hire Delivery Order", "delivery-order", "posting_date", "Delivered", "total_qty"),
	("Hire Off-Hire Note", "off-hire-note", "return_date", "Returned", "total_returned_qty"),
	("Rental Return Inspection", "return-inspection", "inspection_date", "Inspected", "total_returned_qty"),
	("Job Completion Report", "jcr", "modified", "Job report", None),
	("Rental Contract", "rental-contract", "contract_date", "Contract", "total_contract_qty"),
	("Cross Hire Off-Hire Note", "cross-hire-off-hire", "off_hire_date", "Back to supplier", "total_qty"),
)


def get_recent_operations(limit=10):
	"""The latest submitted rental documents, newest first, for the board."""
	from thinknxg_rental.portal.entry import entry_url

	out = []
	for doctype, key, date_field, label, qty_field in RECENT:
		if not frappe.has_permission(doctype, "read"):
			continue
		meta = frappe.get_meta(doctype)
		fields = ["name", "modified", date_field] + [f for f in ("customer_name", "supplier_name", "rental_site") if meta.has_field(f)]
		if qty_field and meta.has_field(qty_field):
			fields.append(qty_field)
		for d in frappe.get_list(doctype, filters={"docstatus": 1}, fields=list(dict.fromkeys(fields)), order_by="modified desc", limit_page_length=limit):
			out.append(frappe._dict(
				name=d.name, label=_(label), url=entry_url(key, d.name), modified=d.modified,
				date=getdate(d.get(date_field)) if d.get(date_field) else None,
				party=d.get("customer_name") or d.get("supplier_name"), site=d.get("rental_site"),
				qty=d.get(qty_field) if qty_field else None,
			))
	out.sort(key=lambda d: d.modified, reverse=True)
	return out[:limit]


# ----------------------------------------------------------------------------- lists
CONTRACT_VIEWS = {
	"live": {"status": ["in", ["Active", "On Hire", "Off Hired"]]},
	"overdue": {"status": "On Hire"},
	"completed": {"status": "Completed"},
	"all": {},
}


def get_admin_contracts(view="live", search=None, customer=None, site=None):
	today = nowdate()
	view = view if view in CONTRACT_VIEWS else "live"
	filters = {"docstatus": 1, **CONTRACT_VIEWS[view]}
	if view == "overdue":
		filters["end_date"] = ["<", today]
	if customer:
		filters["customer"] = customer
	if site:
		filters["rental_site"] = site
	or_filters = None
	if search:
		like = f"%{search.strip()[:60]}%"
		or_filters = {"name": ["like", like], "customer_name": ["like", like], "rental_site": ["like", like]}
	rows = frappe.get_all(
		"Rental Contract",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "customer", "customer_name", "rental_site", "status", "start_date", "end_date", "contract_type",
			"source_type", "source_document", "total_contract_qty", "total_dispatched_qty", "total_at_site_qty", "total_returned_qty",
			"last_billed_upto", "next_billing_date", "total_billed_amount"],
		order_by="end_date asc",
		limit=300,
	)
	# the order's value: the Hire Order estimate or the Hire Order Contract's contract charges
	values = {}
	for doctype, field in (("Hire Order", "estimated_amount"), ("Hire Order Contract", "total_contract_amount")):
		names = [r.source_document for r in rows if r.source_type == doctype and r.source_document]
		if names:
			values.update(dict(frappe.get_all(doctype, filters={"name": ["in", names]}, fields=["name", field], as_list=True)))
	for r in rows:
		r.order_value = flt(values.get(r.source_document))
		r.days_left = date_diff(r.end_date, today)
		r.late = r.status == "On Hire" and r.days_left < 0
		r.is_job = r.contract_type == "Job Type Contract"
		r.bill_due = bool(not r.is_job and r.next_billing_date and getdate(r.next_billing_date) <= getdate(today) and r.status != "Active")
	return view, rows


def get_site_groups(search=None, ownership=None):
	from thinknxg_rental.thinknxg_rental.report.material_at_site.material_at_site import execute

	ownership = ownership if ownership in ("Own", "Cross Hire") else None
	rows = execute({"ownership": ownership} if ownership else {})[1]
	# delivered and returned per contract, item and ownership, from the same ledger as the at-site balance
	moved = {}
	contracts = list({r.rental_contract for r in rows})
	if contracts:
		for m in frappe.db.sql(
			"""select rental_contract, item_code, ownership, ifnull(cross_hire_order, '') as cross_hire_order, movement_type, sum(qty) as qty
			from `tabRental Ownership Ledger`
			where position_type = 'At Site' and rental_contract in %(contracts)s
			group by rental_contract, item_code, ownership, ifnull(cross_hire_order, ''), movement_type""",
			{"contracts": contracts}, as_dict=True,
		):
			moved[(m.rental_contract, m.item_code, m.ownership, m.cross_hire_order, m.movement_type)] = flt(m.qty)
	descriptions = {}
	items = list({r.item_code for r in rows})
	if items:
		descriptions = dict(frappe.get_all("Item", filters={"name": ["in", items]}, fields=["name", "description"], as_list=True))
	for r in rows:
		key = (r.rental_contract, r.item_code, r.ownership, r.cross_hire_order or "")
		r.delivered_qty = moved.get((*key, "Dispatch"), 0)
		r.returned_qty = -moved.get((*key, "Return"), 0)
		r.lost_qty = -moved.get((*key, "Loss"), 0)
		description = frappe.utils.strip_html(descriptions.get(r.item_code) or "").strip()
		r.description = description if description and description != r.item_name else ""
	if search:
		needle = search.strip().lower()
		rows = [
			r for r in rows
			if needle in " ".join(str(r.get(k) or "") for k in ("customer_name", "rental_site", "rental_contract", "item_name", "item_code")).lower()
		]
	groups = {}
	for r in rows:
		groups.setdefault((r.customer_name or r.customer, r.customer, r.rental_site, r.rental_contract), []).append(r)
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


def get_billing(search=None):
	from thinknxg_rental.thinknxg_rental.report.unbilled_rental.unbilled_rental import execute

	today = getdate(nowdate())
	upto = add_days(today, -1)
	accrued = execute({"upto_date": upto})[1]
	needle = (search or "").strip().lower()[:60]
	if needle:
		accrued = [r for r in accrued if needle in " ".join(str(r.get(k) or "") for k in ("rental_contract", "customer", "customer_name", "rental_site")).lower()]
	billed = {}
	if accrued:
		billed = dict(frappe.get_all("Rental Contract", filters={"name": ["in", [r["rental_contract"] for r in accrued]]},
			fields=["name", "total_billed_amount"], as_list=True))
	for r in accrued:
		r["billed_amount"] = flt(billed.get(r["rental_contract"]))
		r["period_to"] = upto
	invoice_filters = {"docstatus": 1, "outstanding_amount": [">", 0], "nxg_rental_contract": ["is", "set"], "is_return": 0}
	invoice_or = None
	if needle:
		like = f"%{needle}%"
		invoice_or = {"name": ["like", like], "customer": ["like", like], "customer_name": ["like", like], "nxg_rental_contract": ["like", like]}
	invoices = frappe.get_all(
		"Sales Invoice",
		filters=invoice_filters,
		or_filters=invoice_or,
		fields=["name", "customer_name", "nxg_rental_contract", "posting_date", "due_date", "grand_total",
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
		drafts=frappe.db.count("Sales Invoice", {"docstatus": 0, "nxg_rental_contract": ["is", "set"]}),
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
				contract=head.rental_contract, site=head.rental_site, due=head.expected_return_date,
				overdue_days=max(l.overdue_days for l in lines), rows=lines,
				on_hire=sum(flt(l.on_hire_qty) for l in lines),
			)
		)
	invoices = {}
	orders = [g.order for g in out]
	if orders:
		for pi in frappe.get_all("Purchase Invoice", filters={"nxg_cross_hire_order": ["in", orders], "docstatus": ["<", 2]},
			fields=["name", "nxg_cross_hire_order", "docstatus", "status", "grand_total", "outstanding_amount"], order_by="posting_date asc"):
			invoices.setdefault(pi.nxg_cross_hire_order, []).append(pi)
	for g in out:
		g.invoices = invoices.get(g.order, [])
		g.billed = sum(flt(i.grand_total) for i in g.invoices if i.docstatus == 1)
	out.sort(key=lambda g: -g.overdue_days)
	return out, frappe._dict(
		on_hire=sum(g.on_hire for g in out),
		at_site=sum(flt(r.at_site_qty) for r in rows),
		idle=sum(flt(r.in_yard_qty) for r in rows if flt(r.on_hire_qty) > 0),
		overdue=len([g for g in out if g.overdue_days > 0]),
	)


REQUEST_TYPES = ("Hire Enquiry", "Off-Hire Request", "Extension Request")


def get_admin_requests(view="open", search=None, request_type=None):
	statuses = {"open": ["Open", "In Progress"], "closed": ["Completed", "Rejected", "Cancelled"]}.get(view)
	if not statuses:
		view, statuses = "open", ["Open", "In Progress"]
	filters = {"status": ["in", statuses]}
	if request_type in REQUEST_TYPES:
		filters["request_type"] = request_type
	or_filters = None
	if search:
		like = f"%{search.strip()[:60]}%"
		or_filters = {"name": ["like", like], "customer": ["like", like], "customer_name": ["like", like],
			"rental_contract": ["like", like], "rental_site": ["like", like]}
	names = frappe.get_all(
		"Rental Portal Request", filters=filters, or_filters=or_filters, fields=["name", "customer", "customer_name", "raised_by"],
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
	frappe.get_doc("Rental Portal Request", name).start()
	return {"name": name}
