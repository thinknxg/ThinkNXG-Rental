"""thinkNXG Rental customer Command Center: the API behind /rental (public/customer_portal).

Security model
--------------
* Every method starts from the session user. The customers it may see are resolved here
  (portal.utils.get_portal_customers: Portal Users of the Customer, or Contacts linked to it).
  A `customer` argument from the browser only narrows that set; it never widens it.
* Customer users hold no desk permissions on these DocTypes, so reads are explicit queries that
  always carry the resolved customer filter. Single documents are fetched only after checking
  that their customer (party) is one of the session's customers and that they are submitted.
* Internal details are never sent: warehouses, own / cross hire ownership, suppliers, costs,
  employee notes and comments.
* Rental staff may preview one customer with ?customer=<name> (read-only).
"""
import base64
import mimetypes
import re

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, date_diff, flt, get_first_day, getdate, nowdate, strip_html

from thinknxg_rental.portal.utils import get_portal_customers, is_staff
from thinknxg_rental.services import ledger
from thinknxg_rental.thinknxg_rental.doctype.rental_portal_request.rental_portal_request import (
	CONTRACT_TYPES,
	REQUEST_TYPES,
)

LIVE = ("Active", "On Hire")
MAX_PAGE = 100
# how each request type is shown to customers, the group it is listed under, and what its form asks for
REQUEST_FORMS = {
	"Additional Material Request": dict(label="Additional Material", group="additional", icon="package-plus",
		help="More material delivered to one of your sites.", contract=1, items="catalogue", date="Required delivery date",
		date_reqd=1),
	"Extension Request": dict(label="Rental Extension", group="extensions", icon="calendar-plus",
		help="Keep material longer than the agreed return date.", contract=1, items="site", items_optional=1, new_end_date=1),
	"Off-Hire Request": dict(label="Material Return", group="returns", icon="undo-2",
		help="Return material from site; we arrange the collection.", contract=1, items="site", date="Requested pickup date",
		location="Pickup location"),
	"Pickup Request": dict(label="Material Pickup", group="returns", icon="truck",
		help="Material is gathered and ready: book a collection.", contract=1, items="site", date="Pickup date", date_reqd=1,
		location="Pickup location"),
	"Delivery Reschedule": dict(label="Delivery Rescheduling", group="deliveries", icon="calendar-clock",
		help="Move a planned delivery to another date.", contract=1, date="New delivery date", date_reqd=1, remarks_reqd=1),
	"Replacement Request": dict(label="Material Replacement", group="service", icon="repeat",
		help="Swap material on site for replacement units.", contract=1, items="site", remarks_reqd=1),
	"Damage Report": dict(label="Damaged Material", group="service", icon="triangle-alert",
		help="Report material that was damaged on site.", contract=1, items="site", remarks_reqd=1, attachments=1),
	"Missing Material Report": dict(label="Missing Material", group="service", icon="search-x",
		help="Report material that cannot be found on site.", contract=1, items="site", remarks_reqd=1, attachments=1),
	"Hire Enquiry": dict(label="New Hire Enquiry", group="additional", icon="clipboard-list",
		help="Material for a new site or project.", items="catalogue", date="Needed from", date_reqd=1,
		return_date=1, location="Site location"),
	"Complaint": dict(label="Complaint", group="support", icon="message-square-warning",
		help="Tell us what went wrong.", contract_optional=1, subject=1, remarks_reqd=1, attachments=1),
	"Support Request": dict(label="General Support", group="support", icon="life-buoy",
		help="Any other question for the rental team.", contract_optional=1, subject=1, remarks_reqd=1, attachments=1),
}
ATTACH_EXT = {"pdf", "jpg", "jpeg", "png", "webp", "heic", "gif", "doc", "docx", "xls", "xlsx", "csv", "txt"}
ATTACH_MAX = 10 * 1024 * 1024
PDF_DOCTYPES = ("Rental Contract", "Hire Order", "Hire Order Contract", "Hire Delivery Order", "Hire Off-Hire Note",
	"Sales Invoice", "Quotation", "Sales Order", "Payment Entry")


# ============================================================================= context
class Ctx(frappe._dict):
	pass


def ctx(customer=None):
	"""The customers this request may read: the session user's, narrowed to `customer` if given."""
	if frappe.session.user == "Guest":
		raise frappe.PermissionError(_("Please log in to open the rental portal."))
	customers, preview = get_portal_customers(customer or None)
	if not customers:
		if preview:
			raise frappe.PermissionError(_("Choose a customer to preview the portal."))
		raise frappe.PermissionError(_("Your login is not linked to a customer account. Please contact the rental team."))
	return Ctx(customers=customers, preview=preview, args={"customers": tuple(customers)})


def _settings():
	return frappe.get_cached_doc("Rental Settings")


def _currency():
	company = _settings().company
	return frappe.get_cached_value("Company", company, "default_currency") if company else None


def _paging(page, page_length):
	length = min(max(cint(page_length) or 20, 1), MAX_PAGE)
	page = max(cint(page) or 1, 1)
	return page, length, (page - 1) * length


def _like(search):
	return "%" + re.sub(r"[%_\\]", "", (search or "").strip())[:60] + "%"


def _paged(rows, total, page, length):
	return {"rows": rows, "total": cint(total), "page": page, "page_length": length, "pages": max((cint(total) + length - 1) // length, 1)}


def _owner_field(doctype):
	return {"Quotation": "party_name", "Payment Entry": "party"}.get(doctype, "customer")


def _quotation_parties(c):
	leads = frappe.get_all("Customer", filters={"name": ["in", c.customers], "lead_name": ["is", "set"]}, pluck="lead_name")
	return tuple(c.customers) + tuple(leads)


def own_document(doctype, name, c, submitted=True):
	"""The document, if it belongs to one of the session's customers (and is submitted)."""
	if not name or not isinstance(name, str) or not frappe.db.exists(doctype, name):
		raise frappe.DoesNotExistError(_("{0} {1} was not found").format(_(doctype), name))
	doc = frappe.get_doc(doctype, name)
	if doctype == "Quotation":
		ok = doc.party_name in _quotation_parties(c)
	elif doctype == "Payment Entry":
		ok = doc.party_type == "Customer" and doc.party in c.customers
	else:
		ok = doc.get("customer") in c.customers
	if not ok or (submitted and doc.docstatus != 1):
		raise frappe.PermissionError(_("{0} {1} was not found").format(_(doctype), name))
	return doc


# ============================================================================= boot
@frappe.whitelist()
def boot(customer: str | None = None):
	"""Who is logged in, the customers they can switch between, and what the portal offers them."""
	user = frappe.session.user
	if user == "Guest":
		raise frappe.PermissionError(_("Please log in to open the rental portal."))
	staff = is_staff()
	if staff:
		customers = [customer] if customer and frappe.db.exists("Customer", customer) else []
	else:
		customers, _preview = get_portal_customers()
	s = _settings()
	u = frappe.get_cached_value("User", user, ["full_name", "first_name", "user_image", "email"], as_dict=True) or frappe._dict()
	names = dict(frappe.get_all("Customer", filters={"name": ["in", customers or [""]]}, fields=["name", "customer_name"], as_list=True))
	out = {
		"user": {"name": user, "full_name": u.full_name or user, "first_name": u.first_name or u.full_name or user,
			"email": u.email, "image": u.user_image},
		"staff": staff,
		"customers": [{"name": n, "customer_name": names.get(n) or n} for n in customers],
		"settings": {"allow_requests": cint(s.portal_allow_requests), "show_rates": cint(s.portal_show_rates),
			"contact_email": s.portal_contact_email, "contact_phone": s.portal_contact_phone,
			"company": s.company, "currency": _currency()},
		"request_forms": {k: dict(v, label=_(v["label"]), help=_(v["help"])) for k, v in REQUEST_FORMS.items()},
		"features": {"sales_orders": 0, "quotations": 0},
		"unread": frappe.db.count("Notification Log", {"for_user": user, "read": 0}),
		"app_name": "thinkNXG Rental",
	}
	if customers:
		c = Ctx(customers=customers, args={"customers": tuple(customers)})
		out["features"]["sales_orders"] = cint(frappe.db.count("Sales Order", {"customer": ["in", customers], "docstatus": 1}))
		out["features"]["quotations"] = cint(frappe.db.count("Quotation", {"party_name": ["in", list(_quotation_parties(c))], "docstatus": 1}))
	return out


@frappe.whitelist()
def preview_customers(search: str | None = None):
	"""Staff only: customers to preview the portal as."""
	if not is_staff():
		raise frappe.PermissionError
	filters = {"disabled": 0}
	or_filters = {"name": ["like", _like(search)], "customer_name": ["like", _like(search)]} if search else None
	return frappe.get_all("Customer", filters=filters, or_filters=or_filters, fields=["name", "customer_name"], order_by="modified desc", limit=30)


# ============================================================================= dashboard
@frappe.whitelist()
def dashboard(customer: str | None = None):
	c = ctx(customer)
	a = c.args
	today = getdate(nowdate())
	a.update(today=today, soon=add_days(today, 14), ahead=add_days(today, 30))
	k = frappe._dict()
	k.active_contracts = cint(frappe.db.sql("""select count(*) from `tabRental Contract`
		where docstatus = 1 and status in ('Active', 'On Hire') and customer in %(customers)s""", a)[0][0])
	awaiting = cint(frappe.db.sql("""select (select count(*) from `tabHire Order` where docstatus = 1 and status = 'Open' and customer in %(customers)s)
		+ (select count(*) from `tabHire Order Contract` where docstatus = 1 and status = 'Open' and customer in %(customers)s)""", a)[0][0])
	k.active_orders = k.active_contracts + awaiting
	k.on_rent = flt(frappe.db.sql("""select sum(qty) from `tabRental Ownership Ledger`
		where position_type = 'At Site' and customer in %(customers)s""", a)[0][0])
	k.on_rent_30d = flt(frappe.db.sql("""select sum(qty) from `tabRental Ownership Ledger`
		where position_type = 'At Site' and customer in %(customers)s and posting_date <= %(d)s""", dict(a, d=add_days(today, -30)))[0][0])
	pending = frappe.db.sql("""select count(distinct c.name), sum(greatest(ci.qty - ci.dispatched_qty, 0))
		from `tabRental Contract` c inner join `tabRental Contract Item` ci on ci.parent = c.name
		where c.docstatus = 1 and c.status in ('Active', 'On Hire') and c.customer in %(customers)s and ci.qty > ci.dispatched_qty""", a)[0]
	k.pending_delivery_orders, k.pending_delivery_qty = cint(pending[0]), flt(pending[1])
	returns = frappe.db.sql("""select count(distinct r.name), sum(i.qty) from `tabRental Portal Request` r
		left join `tabRental Portal Request Item` i on i.parent = r.name
		where r.customer in %(customers)s and r.status in ('Open', 'In Progress') and r.request_type in ('Off-Hire Request', 'Pickup Request')""", a)[0]
	k.pending_returns, k.pending_return_qty = cint(returns[0]), flt(returns[1])
	inv = frappe.db.sql("""select count(*), sum(outstanding_amount), sum(case when due_date < %(today)s then outstanding_amount else 0 end),
			sum(case when due_date < %(today)s then 1 else 0 end)
		from `tabSales Invoice` where docstatus = 1 and customer in %(customers)s and outstanding_amount > 0""", a)[0]
	k.unpaid_invoices, k.outstanding, k.overdue_amount, k.overdue_invoices = cint(inv[0]), flt(inv[1]), flt(inv[2]), cint(inv[3])
	k.pending_requests = cint(frappe.db.count("Rental Portal Request", {"customer": ["in", c.customers], "status": ["in", ["Open", "In Progress"]]}))

	# operations overview
	ops = frappe._dict()
	ops.active_rentals = cint(frappe.db.sql("""select count(*) from (select rental_contract, item_code from `tabRental Ownership Ledger`
		where position_type = 'At Site' and customer in %(customers)s group by rental_contract, item_code having sum(qty) > 0) t""", a)[0][0])
	ops.overdue = frappe.db.sql("""select count(*), sum(total_at_site_qty) from `tabRental Contract` where docstatus = 1 and status in ('Active', 'On Hire')
		and customer in %(customers)s and total_at_site_qty > 0 and end_date < %(today)s""", a)[0]
	ops.ending_soon = cint(frappe.db.sql("""select count(*) from `tabRental Contract` where docstatus = 1 and status in ('Active', 'On Hire')
		and customer in %(customers)s and total_at_site_qty > 0 and end_date between %(today)s and %(soon)s""", a)[0][0])
	ops.upcoming_deliveries = cint(frappe.db.sql("""select count(*) from `tabHire Delivery Order` where docstatus = 0 and customer in %(customers)s
		and posting_date >= %(today)s""", a)[0][0]) + cint(frappe.db.count("Rental Portal Request", {"customer": ["in", c.customers],
		"status": ["in", ["Open", "In Progress"]], "request_type": ["in", ["Hire Enquiry", "Additional Material Request"]]}))
	ops.scheduled_pickups = k.pending_returns
	ops.pending_extensions = cint(frappe.db.count("Rental Portal Request", {"customer": ["in", c.customers],
		"status": ["in", ["Open", "In Progress"]], "request_type": "Extension Request"}))
	ops.overdue = {"contracts": cint(ops.overdue[0]), "qty": flt(ops.overdue[1])}

	return {
		"customer_names": [frappe.db.get_value("Customer", x, "customer_name") or x for x in c.customers],
		"currency": _currency(),
		"kpi": k,
		"ops": ops,
		"movement": _movement_chart(c, today),
		"by_site": _site_chart(c),
		"recent_orders": orders(customer=customer, page=1, page_length=6)["rows"],
		"upcoming": upcoming(c, today),
		"notifications": notifications(page=1, page_length=5)["rows"],
	}


def _movement_chart(c, today):
	"""Units dispatched and returned per month, last 6 months (from the rental ledger)."""
	start = getdate(get_first_day(add_months(today, -5)))
	rows = frappe.db.sql("""select date_format(posting_date, '%%Y-%%m') as ym,
			sum(case when movement_type = 'Dispatch' then qty else 0 end) as out_qty,
			sum(case when movement_type in ('Return', 'Loss') then -qty else 0 end) as in_qty
		from `tabRental Ownership Ledger`
		where position_type = 'At Site' and customer in %(customers)s and posting_date >= %(start)s
		group by ym""", dict(c.args, start=start), as_dict=True)
	by = {r.ym: r for r in rows}
	out, d = [], start
	for _i in range(6):
		key = d.strftime("%Y-%m")
		r = by.get(key) or frappe._dict(out_qty=0, in_qty=0)
		out.append({"label": d.strftime("%b"), "month": key, "dispatched": flt(r.out_qty), "returned": flt(r.in_qty)})
		d = getdate(add_months(d, 1))
	return out


def _site_chart(c):
	rows = frappe.db.sql("""select rental_site as site, sum(qty) as qty from `tabRental Ownership Ledger`
		where position_type = 'At Site' and customer in %(customers)s group by rental_site having sum(qty) > 0 order by qty desc limit 8""",
		c.args, as_dict=True)
	return [{"site": r.site, "qty": flt(r.qty)} for r in rows]


def upcoming(c, today):
	"""Deliveries, pickups, rental ends, inspections and payments, overdue first, then the next 30 days."""
	a = dict(c.args, today=today, ahead=add_days(today, 30))
	out = []
	for d in frappe.db.sql("""select name, posting_date, rental_site, total_qty, rental_contract from `tabHire Delivery Order`
			where docstatus = 0 and customer in %(customers)s and posting_date between %(today)s and %(ahead)s""", a, as_dict=True):
		out.append(dict(kind="delivery", date=d.posting_date, title=_("Delivery to {0}").format(d.rental_site),
			detail=_("{0} units planned").format(f"{flt(d.total_qty):g}"), route=f"deliveries/{d.name}"))
	for r in frappe.db.sql("""select name, request_type, required_date, rental_site, rental_contract, status from `tabRental Portal Request`
			where customer in %(customers)s and status in ('Open', 'In Progress') and required_date is not null
			and request_type in ('Off-Hire Request', 'Pickup Request', 'Hire Enquiry', 'Additional Material Request', 'Delivery Reschedule')
			and required_date <= %(ahead)s""", a, as_dict=True):
		pickup = r.request_type in ("Off-Hire Request", "Pickup Request")
		out.append(dict(kind="pickup" if pickup else "delivery", date=r.required_date,
			title=(_("Pickup from {0}") if pickup else _("Requested delivery to {0}")).format(r.rental_site or _("new site")),
			detail=_("{0} {1} - {2}").format(_(REQUEST_FORMS.get(r.request_type, {}).get("label", r.request_type)), r.name, _(r.status)),
			route=f"requests/{r.name}"))
	for k in frappe.db.sql("""select name, end_date, rental_site, total_at_site_qty from `tabRental Contract`
			where docstatus = 1 and status in ('Active', 'On Hire') and customer in %(customers)s and total_at_site_qty > 0
			and end_date <= %(ahead)s""", a, as_dict=True):
		late = getdate(k.end_date) < today
		out.append(dict(kind="overdue" if late else "expiry", date=k.end_date,
			title=(_("Rental overdue at {0}") if late else _("Rental ends at {0}")).format(k.rental_site),
			detail=_("{0} units still on site").format(f"{flt(k.total_at_site_qty):g}"), route=f"orders/{k.name}"))
	for n in frappe.db.sql("""select name, return_date, rental_site from `tabHire Off-Hire Note`
			where docstatus = 1 and customer in %(customers)s and inspection_status = 'Pending'""", a, as_dict=True):
		out.append(dict(kind="inspection", date=n.return_date, title=_("Inspection of returned material"),
			detail=_("{0} from {1}").format(n.name, n.rental_site), route=f"returns/{n.name}"))
	for i in frappe.db.sql("""select name, due_date, outstanding_amount, currency from `tabSales Invoice`
			where docstatus = 1 and customer in %(customers)s and outstanding_amount > 0 and due_date <= %(ahead)s""", a, as_dict=True):
		late = getdate(i.due_date) < today
		out.append(dict(kind="payment-overdue" if late else "payment", date=i.due_date,
			title=(_("Payment overdue: {0}") if late else _("Payment due: {0}")).format(i.name),
			amount=flt(i.outstanding_amount), currency=i.currency, route=f"invoices/{i.name}"))
	out.sort(key=lambda x: getdate(x["date"]))
	return out[:12]


# ============================================================================= rental orders
ORDER_STATUSES = ("Awaiting Contract", "Active", "On Hire", "Off Hired", "Completed")


def _orders_sql(c, search=None, status=None, from_date=None, to_date=None, site=None):
	inner = """
		select 'Rental Contract' as doctype, c.name, ifnull(c.source_document, c.name) as order_no, c.contract_date as order_date,
			c.rental_site, c.project, c.start_date, c.end_date, c.status, c.creation, c.contract_type,
			c.total_contract_qty as qty, c.total_at_site_qty as at_site_qty, c.source_type, c.source_document
		from `tabRental Contract` c where c.docstatus = 1 and c.customer in %(customers)s
		union all
		select 'Hire Order', h.name, h.name, h.order_date, h.rental_site, h.project, h.required_from, h.expected_return_date,
			'Awaiting Contract', h.creation, 'Item Rental', h.total_qty, 0, 'Hire Order', h.name
		from `tabHire Order` h where h.docstatus = 1 and h.status = 'Open' and h.customer in %(customers)s
		union all
		select 'Hire Order Contract', j.name, j.name, j.order_date, j.rental_site, j.project, j.required_from, null,
			'Awaiting Contract', j.creation, 'Job Type Contract', j.total_jobs, 0, 'Hire Order Contract', j.name
		from `tabHire Order Contract` j where j.docstatus = 1 and j.status = 'Open' and j.customer in %(customers)s"""
	cond, a = [], dict(c.args)
	if search:
		cond.append("(t.name like %(q)s or t.order_no like %(q)s or t.rental_site like %(q)s or ifnull(t.project, '') like %(q)s)")
		a["q"] = _like(search)
	if status == "live":
		cond.append("t.status in ('Awaiting Contract', 'Active', 'On Hire')")
	elif status == "closed":
		cond.append("t.status in ('Off Hired', 'Completed')")
	elif status in ORDER_STATUSES:
		cond.append("t.status = %(status)s")
		a["status"] = status
	if from_date:
		cond.append("t.order_date >= %(from_date)s")
		a["from_date"] = getdate(from_date)
	if to_date:
		cond.append("t.order_date <= %(to_date)s")
		a["to_date"] = getdate(to_date)
	if site:
		cond.append("t.rental_site = %(site)s")
		a["site"] = site
	where = (" where " + " and ".join(cond)) if cond else ""
	return f"from ({inner}) t{where}", a


@frappe.whitelist()
def orders(customer: str | None = None, page: int = 1, page_length: int = 20, search: str | None = None, status: str | None = None,
		from_date: str | None = None, to_date: str | None = None, site: str | None = None, sort: str | None = None):
	"""Rental orders: every rental contract (with the hire order it came from), and hire orders still awaiting
	their contract."""
	c = ctx(customer)
	page, length, start = _paging(page, page_length)
	body, a = _orders_sql(c, search, status, from_date, to_date, site)
	total = frappe.db.sql(f"select count(*) {body}", a)[0][0]
	order_by = {"date_asc": "t.order_date asc, t.creation asc", "end": "t.end_date is null, t.end_date asc"}.get(sort, "t.order_date desc, t.creation desc")
	rows = frappe.db.sql(f"select t.* {body} order by {order_by} limit {length} offset {start}", a, as_dict=True)
	_order_values(rows)
	today = getdate(nowdate())
	for r in rows:
		r.route = f"orders/{r.name}"
		r.overdue = r.status in LIVE and flt(r.at_site_qty) > 0 and r.end_date and getdate(r.end_date) < today
		r.ending_soon = r.status in LIVE and flt(r.at_site_qty) > 0 and r.end_date and 0 <= date_diff(r.end_date, today) <= 14
	return _paged(rows, total, page, length)


def _order_values(rows):
	"""Order value: the hire order's estimate, the job contract's total, else the contract lines at their rates."""
	ho = [r.source_document for r in rows if r.source_type == "Hire Order" and r.source_document]
	hoc = [r.source_document for r in rows if r.source_type == "Hire Order Contract" and r.source_document]
	ho_val = dict(frappe.get_all("Hire Order", filters={"name": ["in", ho or [""]]}, fields=["name", "estimated_amount"], as_list=True))
	hoc_val = dict(frappe.get_all("Hire Order Contract", filters={"name": ["in", hoc or [""]]}, fields=["name", "total_contract_amount"], as_list=True))
	direct = [r.name for r in rows if r.doctype == "Rental Contract" and not r.source_document]
	rc_val = {}
	if direct:
		rc_val = dict(frappe.db.sql("""select parent, sum(qty * rate) from `tabRental Contract Item` where parent in %s group by parent""", [tuple(direct)]))
	for r in rows:
		if r.source_type == "Hire Order":
			r.value = flt(ho_val.get(r.source_document))
		elif r.source_type == "Hire Order Contract":
			r.value = flt(hoc_val.get(r.source_document))
		else:
			r.value = flt(rc_val.get(r.name))


def _resolve_order(name, c):
	"""(order doc, contract doc or None) for a rental contract or a hire order / hire order contract number."""
	from thinknxg_rental.services.utils import get_contract_for_source

	for doctype in ("Rental Contract", "Hire Order", "Hire Order Contract"):
		if name and frappe.db.exists(doctype, name):
			doc = own_document(doctype, name, c)
			if doctype == "Rental Contract":
				source = frappe.get_doc(doc.source_type, doc.source_document) if doc.source_type and doc.source_document else None
				return source, doc
			contract = get_contract_for_source(doctype, name)
			return doc, (frappe.get_doc("Rental Contract", contract) if contract else None)
	raise frappe.DoesNotExistError(_("Rental order {0} was not found").format(name))


@frappe.whitelist()
def order(name: str, customer: str | None = None):
	c = ctx(customer)
	source, contract = _resolve_order(name, c)
	head = contract or source
	site = frappe.db.get_value("Rental Site", head.rental_site, ["site_name", "location", "site_contact", "contact_phone", "address"], as_dict=True) or frappe._dict()
	address = frappe.db.get_value("Address", site.address, ["address_line1", "address_line2", "city", "state", "country"], as_dict=True) if site.address else None
	lines = []
	if contract:
		for d in contract.items:
			lines.append(dict(item_code=d.item_code, item_name=d.item_name, uom=d.uom, ordered=flt(d.qty), delivered=flt(d.dispatched_qty),
				returned=flt(d.returned_qty), lost=flt(d.lost_qty), at_site=flt(d.at_site_qty), to_deliver=flt(d.pending_qty),
				rate=flt(d.rate), rate_basis=d.rate_basis, amount=flt(d.qty) * flt(d.rate)))
	elif source.doctype == "Hire Order":
		for d in source.items:
			lines.append(dict(item_code=d.item_code, item_name=d.item_name, uom=d.uom, ordered=flt(d.qty), delivered=0, returned=0, lost=0,
				at_site=0, to_deliver=flt(d.qty), rate=flt(d.rate), rate_basis=d.rate_basis, amount=flt(d.estimated_amount)))
	else:
		for d in source.materials:
			lines.append(dict(item_code=d.item_code, item_name=d.item_name, uom=d.get("uom"), ordered=flt(d.qty), delivered=0, returned=0,
				lost=0, at_site=0, to_deliver=flt(d.qty), rate=None, rate_basis=None, amount=None))
	descriptions = dict(frappe.get_all("Item", filters={"name": ["in", [l["item_code"] for l in lines] or [""]]},
		fields=["name", "description"], as_list=True))
	for l in lines:
		desc = strip_html(descriptions.get(l["item_code"]) or "").strip()
		l["description"] = desc if desc and desc != l["item_name"] else ""
	jobs = []
	hoc = source if source and source.doctype == "Hire Order Contract" else None
	if hoc:
		for j in hoc.items:
			jobs.append(dict(job_type=j.job_type_name or j.job_type, location=j.location, qty=flt(j.qty), included_days=j.included_days,
				rate=flt(j.contract_rate), amount=flt(j.contract_amount), reported=flt(j.jcr_qty), balance=flt(j.balance_qty)))
	rows = [_order_values_row(head, source)]
	out = {
		"name": name,
		"order_no": source.name if source else contract.name,
		"order_doctype": source.doctype if source else "Rental Contract",
		"contract": contract.name if contract else None,
		"order_date": source.order_date if source else contract.contract_date,
		"customer_name": head.customer_name,
		"site": head.rental_site,
		"site_name": site.site_name,
		"site_location": site.location,
		"site_contact": site.site_contact,
		"site_phone": site.contact_phone,
		"address": ", ".join(x for x in (address or {}).values() if x) if address else None,
		"project": head.project,
		"customer_reference": source.get("customer_reference") if source else None,
		"start_date": contract.start_date if contract else source.get("required_from"),
		"end_date": contract.end_date if contract else source.get("expected_return_date"),
		"status": contract.status if contract else _("Awaiting Contract"),
		"contract_type": contract.contract_type if contract else ("Job Type Contract" if hoc else "Item Rental"),
		"billing_cycle": contract.billing_cycle if contract else source.get("billing_cycle"),
		"last_billed_upto": contract.last_billed_upto if contract else None,
		"value": rows[0],
		"currency": _currency(),
		"lines": lines,
		"jobs": jobs,
		"extensions": [dict(date=e.extension_date, previous=e.previous_end_date, new=e.new_end_date) for e in (contract.extensions if contract else [])],
		"timeline": _timeline(source, contract, c),
		"deliveries": deliveries(customer=customer, contract=contract.name, page_length=50)["rows"] if contract else [],
		"returns": returns(customer=customer, contract=contract.name, page_length=50)["rows"] if contract else [],
		"invoices": invoices(customer=customer, contract=contract.name, page_length=50)["rows"] if contract else [],
		"requests": requests(customer=customer, contract=contract.name, page_length=20)["rows"] if contract else [],
		"documents": [d for d in ([dict(doctype=source.doctype, name=source.name, label=_(source.doctype))] if source else [])
			+ ([dict(doctype="Rental Contract", name=contract.name, label=_("Rental Contract"))] if contract else [])],
		"can_request": bool(contract and contract.status in LIVE),
	}
	return out


def _order_values_row(head, source):
	if source and source.doctype == "Hire Order":
		return flt(source.estimated_amount)
	if source and source.doctype == "Hire Order Contract":
		return flt(source.total_contract_amount)
	return sum(flt(d.qty) * flt(d.rate) for d in head.items) if head.doctype == "Rental Contract" else None


def _timeline(source, contract, c):
	"""Only what the records show happened."""
	from thinknxg_rental.thinknxg_rental.doctype.rental_material_reservation.rental_material_reservation import get_contract_reservations

	ev = []
	if source:
		ev.append(dict(date=source.order_date, title=_("Order placed"), detail=source.name, icon="file-plus"))
	if contract:
		ev.append(dict(date=contract.contract_date, title=_("Order confirmed"), detail=_("Rental contract {0}").format(contract.name), icon="badge-check"))
		for r in frappe.get_all("Rental Material Reservation", filters={"name": ["in", get_contract_reservations(contract.name) or [""]]},
				fields=["name", "reservation_date", "total_reserved_qty"]):
			ev.append(dict(date=r.reservation_date, title=_("Material prepared"), detail=_("{0} units reserved for you").format(f"{flt(r.total_reserved_qty):g}"), icon="package-check"))
		for d in frappe.get_all("Hire Delivery Order", filters={"rental_contract": contract.name, "docstatus": 1},
				fields=["name", "posting_date", "total_qty", "vehicle_no"], order_by="posting_date asc"):
			ev.append(dict(date=d.posting_date, title=_("Material dispatched and delivered"), detail=_("{0}: {1} units").format(d.name, f"{flt(d.total_qty):g}"),
				icon="truck", route=f"deliveries/{d.name}"))
		if contract.billing_start_date:
			ev.append(dict(date=contract.billing_start_date, title=_("Rental started"), icon="play"))
		for e in contract.extensions:
			ev.append(dict(date=e.extension_date, title=_("Rental extended"), detail=_("New return date {0}").format(frappe.format(e.new_end_date, "Date")), icon="calendar-plus"))
		for r in frappe.get_all("Rental Portal Request", filters={"rental_contract": contract.name, "request_type": ["in", ["Off-Hire Request", "Pickup Request"]],
				"status": ["!=", "Cancelled"]}, fields=["name", "request_date"]):
			ev.append(dict(date=r.request_date, title=_("Return requested"), detail=r.name, icon="undo-2", route=f"requests/{r.name}"))
		last = None
		for n in frappe.get_all("Hire Off-Hire Note", filters={"rental_contract": contract.name, "docstatus": 1},
				fields=["name", "return_date", "total_returned_qty", "total_lost_qty"], order_by="return_date asc"):
			last = n.return_date
			ev.append(dict(date=n.return_date, title=_("Material returned"), detail=_("{0}: {1} units").format(n.name, f"{flt(n.total_returned_qty):g}"),
				icon="package-open", route=f"returns/{n.name}"))
		if contract.status == "Completed":
			ev.append(dict(date=last or getdate(contract.modified), title=_("Rental closed"), icon="flag"))
	order = {"Order placed": 0, "Order confirmed": 1}
	ev.sort(key=lambda e: (getdate(e["date"]) if e.get("date") else getdate("1900-01-01"), order.get(e["title"], 5)))
	return ev


# ============================================================================= active rentals
@frappe.whitelist()
def active_rentals(customer: str | None = None, page: int = 1, page_length: int = 25, search: str | None = None,
		site: str | None = None, state: str | None = None):
	"""Material on hire now, per rental contract and item."""
	c = ctx(customer)
	page, length, start = _paging(page, page_length)
	a = dict(c.args, today=getdate(nowdate()), soon=add_days(getdate(nowdate()), 14))
	cond = []
	if search:
		cond.append("(l.item_code like %(q)s or i.item_name like %(q)s or l.rental_contract like %(q)s or l.rental_site like %(q)s or ifnull(c.source_document, '') like %(q)s)")
		a["q"] = _like(search)
	if site:
		cond.append("l.rental_site = %(site)s")
		a["site"] = site
	having = "sum(l.qty) > 0"
	if state == "overdue":
		cond.append("c.end_date < %(today)s")
	elif state == "expiring":
		cond.append("c.end_date between %(today)s and %(soon)s")
	elif state == "partial":
		having += " and sum(case when l.movement_type in ('Return', 'Loss') then 1 else 0 end) > 0"
	where = (" and " + " and ".join(cond)) if cond else ""
	body = f"""from `tabRental Ownership Ledger` l
		inner join `tabRental Contract` c on c.name = l.rental_contract
		left join `tabItem` i on i.name = l.item_code
		where l.position_type = 'At Site' and l.customer in %(customers)s{where}
		group by l.rental_contract, l.item_code having {having}"""
	total = frappe.db.sql(f"select count(*) from (select l.rental_contract {body}) t", a)[0][0]
	rows = frappe.db.sql(f"""select l.rental_contract, l.item_code, max(i.item_name) as item_name, max(i.stock_uom) as uom,
			max(l.rental_site) as rental_site, max(c.source_document) as order_no, max(c.start_date) as start_date, max(c.end_date) as end_date,
			max(c.status) as contract_status, sum(l.qty) as qty,
			sum(case when l.movement_type = 'Dispatch' then l.qty else 0 end) as delivered,
			sum(case when l.movement_type in ('Return', 'Loss') then -l.qty else 0 end) as returned,
			min(case when l.movement_type = 'Dispatch' then l.posting_date end) as first_dispatch
		{body} order by max(c.end_date) asc, l.rental_contract, max(i.item_name) limit {length} offset {start}""", a, as_dict=True)
	rates = {}
	if rows:
		for r in frappe.db.sql("""select parent, item_code, rate, rate_basis from `tabRental Contract Item`
				where parent in %s""", [tuple({r.rental_contract for r in rows})], as_dict=True):
			rates[(r.parent, r.item_code)] = r
	today = getdate(nowdate())
	for r in rows:
		rate = rates.get((r.rental_contract, r.item_code)) or frappe._dict()
		r.rate, r.rate_basis = flt(rate.rate), rate.rate_basis
		r.period_value = flt(r.qty) * flt(rate.rate)
		r.days_on_hire = date_diff(today, r.first_dispatch) + 1 if r.first_dispatch else 0
		r.days_left = date_diff(r.end_date, today) if r.end_date else None
		r.state = "overdue" if r.days_left is not None and r.days_left < 0 else "expiring" if r.days_left is not None and r.days_left <= 14 else "active"
		r.partial = flt(r.returned) > 0
		r.route = f"orders/{r.rental_contract}"
	summary = frappe.db.sql("""select count(*) as line_count, sum(t.qty) as qty, sum(case when t.end_date < %(today)s then 1 else 0 end) as overdue,
			sum(case when t.end_date between %(today)s and %(soon)s then 1 else 0 end) as expiring
		from (select l.rental_contract, max(c.end_date) as end_date, sum(l.qty) as qty from `tabRental Ownership Ledger` l
			inner join `tabRental Contract` c on c.name = l.rental_contract
			where l.position_type = 'At Site' and l.customer in %(customers)s group by l.rental_contract, l.item_code having sum(l.qty) > 0) t""",
		a, as_dict=True)[0]
	out = _paged(rows, total, page, length)
	out.update(summary={k: flt(v) for k, v in summary.items()}, currency=_currency(), sites=_sites(c))
	return out


def _sites(c):
	return frappe.get_all("Rental Site", filters={"customer": ["in", c.customers]}, fields=["name", "site_name"], order_by="site_name asc")


# ============================================================================= deliveries and returns
@frappe.whitelist()
def deliveries(customer: str | None = None, page: int = 1, page_length: int = 20, search: str | None = None, contract: str | None = None,
		site: str | None = None, from_date: str | None = None, to_date: str | None = None, status: str | None = None):
	c = ctx(customer)
	page, length, start = _paging(page, page_length)
	a, cond = dict(c.args, today=getdate(nowdate())), ["d.customer in %(customers)s",
		"(d.docstatus = 1 or (d.docstatus = 0 and d.posting_date >= %(today)s))"]
	if status == "scheduled":
		cond.append("d.docstatus = 0")
	elif status == "delivered":
		cond.append("d.docstatus = 1")
	for field, value in (("rental_contract", contract), ("rental_site", site)):
		if value:
			cond.append(f"d.{field} = %({field})s")
			a[field] = value
	if from_date:
		cond.append("d.posting_date >= %(from_date)s")
		a["from_date"] = getdate(from_date)
	if to_date:
		cond.append("d.posting_date <= %(to_date)s")
		a["to_date"] = getdate(to_date)
	if search:
		cond.append("(d.name like %(q)s or d.rental_contract like %(q)s or d.rental_site like %(q)s or ifnull(d.source_document, '') like %(q)s or ifnull(d.vehicle_no, '') like %(q)s)")
		a["q"] = _like(search)
	where = " and ".join(cond)
	total = frappe.db.sql(f"select count(*) from `tabHire Delivery Order` d where {where}", a)[0][0]
	rows = frappe.db.sql(f"""select d.name, d.posting_date, d.rental_contract, d.source_document as order_no, d.rental_site, d.project,
			d.total_qty, d.vehicle_no, d.driver_name, d.dispatch_reference, d.docstatus
		from `tabHire Delivery Order` d where {where} order by d.posting_date desc, d.creation desc limit {length} offset {start}""", a, as_dict=True)
	for r in rows:
		r.status = _("Delivered") if r.docstatus == 1 else _("Scheduled")
		r.route = f"deliveries/{r.name}"
	return _paged(rows, total, page, length)


@frappe.whitelist()
def delivery(name: str, customer: str | None = None):
	c = ctx(customer)
	doc = own_document("Hire Delivery Order", name, c, submitted=False)
	if doc.docstatus == 2 or (doc.docstatus == 0 and getdate(doc.posting_date) < getdate(nowdate())):
		raise frappe.PermissionError(_("Hire Delivery Order {0} was not found").format(name))
	contract = frappe.get_doc("Rental Contract", doc.rental_contract)
	pending = {d.item_code: flt(d.pending_qty) for d in contract.items}
	items = {}
	for d in doc.items:  # one line per item: warehouses and ownership are internal
		row = items.setdefault(d.item_code, dict(item_code=d.item_code, item_name=d.item_name, uom=d.uom, qty=0,
			ordered=flt(d.contract_qty), pending=pending.get(d.item_code, 0)))
		row["qty"] += flt(d.qty)
	return {
		"name": doc.name, "status": _("Delivered") if doc.docstatus == 1 else _("Scheduled"), "posting_date": doc.posting_date,
		"rental_contract": doc.rental_contract, "order_no": doc.source_document or doc.rental_contract, "rental_site": doc.rental_site,
		"project": doc.project, "vehicle_no": doc.vehicle_no, "driver_name": doc.driver_name, "driver_phone": doc.driver_phone,
		"transporter": doc.transporter, "dispatch_reference": doc.dispatch_reference, "total_qty": flt(doc.total_qty),
		"items": list(items.values()), "can_print": doc.docstatus == 1,
	}


@frappe.whitelist()
def returns(customer: str | None = None, page: int = 1, page_length: int = 20, search: str | None = None, contract: str | None = None,
		site: str | None = None, from_date: str | None = None, to_date: str | None = None, status: str | None = None):
	"""Returns made (off-hire notes) and returns asked for and not yet collected (return / pickup requests)."""
	c = ctx(customer)
	page, length, start = _paging(page, page_length)
	a = dict(c.args)
	cond_n, cond_r = ["n.docstatus = 1", "n.customer in %(customers)s"], ["r.customer in %(customers)s",
		"r.status in ('Open', 'In Progress')", "r.request_type in ('Off-Hire Request', 'Pickup Request')"]
	for field, value in (("rental_contract", contract), ("rental_site", site)):
		if value:
			cond_n.append(f"n.{field} = %({field})s")
			cond_r.append(f"r.{field} = %({field})s")
			a[field] = value
	if from_date:
		cond_n.append("n.return_date >= %(from_date)s")
		cond_r.append("ifnull(r.required_date, r.request_date) >= %(from_date)s")
		a["from_date"] = getdate(from_date)
	if to_date:
		cond_n.append("n.return_date <= %(to_date)s")
		cond_r.append("ifnull(r.required_date, r.request_date) <= %(to_date)s")
		a["to_date"] = getdate(to_date)
	if search:
		cond_n.append("(n.name like %(q)s or n.rental_contract like %(q)s or n.rental_site like %(q)s)")
		cond_r.append("(r.name like %(q)s or r.rental_contract like %(q)s or r.rental_site like %(q)s)")
		a["q"] = _like(search)
	parts = []
	if status in (None, "", "returned"):
		parts.append(f"""select 'Hire Off-Hire Note' as doctype, n.name, n.return_date as date, n.rental_contract, n.rental_site,
			n.total_returned_qty as qty, n.total_lost_qty as lost_qty, n.status as raw_status, n.off_hire_type, n.creation
			from `tabHire Off-Hire Note` n where {" and ".join(cond_n)}""")
	if status in (None, "", "requested"):
		parts.append(f"""select 'Rental Portal Request' as doctype, r.name, ifnull(r.required_date, r.request_date) as date, r.rental_contract, r.rental_site,
			(select sum(i.qty) from `tabRental Portal Request Item` i where i.parent = r.name) as qty, 0 as lost_qty, r.status as raw_status,
			r.request_type as off_hire_type, r.creation
			from `tabRental Portal Request` r where {" and ".join(cond_r)}""")
	if not parts:
		return _paged([], 0, page, length)
	union = " union all ".join(parts)
	total = frappe.db.sql(f"select count(*) from ({union}) t", a)[0][0]
	rows = frappe.db.sql(f"select * from ({union}) t order by t.date desc, t.creation desc limit {length} offset {start}", a, as_dict=True)
	for r in rows:
		if r.doctype == "Hire Off-Hire Note":
			r.status = {"Inspection Pending": _("Returned, inspection pending"), "Completed": _("Returned")}.get(r.raw_status, _(r.raw_status))
			r.kind = _("{0} return").format(_(r.off_hire_type)) if r.off_hire_type else _("Return")
			r.route = f"returns/{r.name}"
		else:
			r.status = _("Pickup requested") if r.raw_status == "Open" else _("Pickup being arranged")
			r.kind = _(REQUEST_FORMS[r.off_hire_type]["label"])
			r.route = f"requests/{r.name}"
		r.pending = r.doctype != "Hire Off-Hire Note"
	return _paged(rows, total, page, length)


@frappe.whitelist()
def return_note(name: str, customer: str | None = None):
	c = ctx(customer)
	doc = own_document("Hire Off-Hire Note", name, c)
	items = {}
	for d in doc.items:
		row = items.setdefault(d.item_code, dict(item_code=d.item_code, item_name=d.item_name, uom=d.uom, returned=0, lost=0,
			at_site_before=flt(d.at_site_qty), still_at_site=flt(d.pending_qty)))
		row["returned"] += flt(d.returned_qty)
		row["lost"] += flt(d.lost_qty)
	inspection = frappe.db.get_value("Rental Return Inspection", {"hire_off_hire_note": doc.name, "docstatus": 1},
		["name", "inspection_date", "total_good_qty", "total_repairable_qty", "total_damaged_qty"], as_dict=True)
	return {
		"name": doc.name, "status": doc.status, "off_hire_type": doc.off_hire_type, "off_hire_date": doc.off_hire_date,
		"return_date": doc.return_date, "last_billable_date": doc.last_billable_date, "rental_contract": doc.rental_contract,
		"rental_site": doc.rental_site, "vehicle_no": doc.vehicle_no, "driver_name": doc.driver_name,
		"total_returned_qty": flt(doc.total_returned_qty), "total_lost_qty": flt(doc.total_lost_qty),
		"inspection_status": doc.inspection_status, "inspection": inspection, "items": list(items.values()),
		"request": doc.portal_request,
	}


# ============================================================================= commercial
@frappe.whitelist()
def quotations(customer: str | None = None, page: int = 1, page_length: int = 20, search: str | None = None, status: str | None = None):
	c = ctx(customer)
	page, length, start = _paging(page, page_length)
	filters = {"docstatus": 1, "party_name": ["in", list(_quotation_parties(c))]}
	if status:
		filters["status"] = status
	or_filters = {"name": ["like", _like(search)], "title": ["like", _like(search)]} if search else None
	total = len(frappe.get_all("Quotation", filters=filters, or_filters=or_filters, pluck="name"))
	rows = frappe.get_all("Quotation", filters=filters, or_filters=or_filters, order_by="transaction_date desc, creation desc",
		fields=["name", "transaction_date", "valid_till", "grand_total", "currency", "status", "title", "order_type"], start=start, limit=length)
	sites = dict(frappe.get_all("Rental Site", filters={"nxg_quotation": ["in", [r.name for r in rows] or [""]]}, fields=["nxg_quotation", "name"], as_list=True))
	for r in rows:
		r.rental_site = sites.get(r.name)
		r.route = f"quotations/{r.name}"
	return _paged(rows, total, page, length)


def _doc_lines(doc, extra=()):
	return [dict(item_code=d.item_code, item_name=d.item_name, description=strip_html(d.description or "") if d.description != d.item_name else "",
		qty=flt(d.qty), uom=d.uom, rate=flt(d.rate), amount=flt(d.amount), **{f: d.get(f) for f in extra}) for d in doc.items]


def _taxes(doc):
	return [dict(description=t.description, rate=flt(t.rate), amount=flt(t.tax_amount)) for t in (doc.get("taxes") or []) if flt(t.tax_amount)]


@frappe.whitelist()
def quotation(name: str, customer: str | None = None):
	c = ctx(customer)
	doc = own_document("Quotation", name, c)
	return dict(name=doc.name, title=doc.title, transaction_date=doc.transaction_date, valid_till=doc.valid_till, status=doc.status,
		currency=doc.currency, net_total=flt(doc.net_total), total_taxes=flt(doc.total_taxes_and_charges), grand_total=flt(doc.grand_total),
		items=_doc_lines(doc, ("nxg_rate_basis",)), taxes=_taxes(doc), terms=doc.terms,
		rental_site=frappe.db.get_value("Rental Site", {"nxg_quotation": doc.name}, "name"))


@frappe.whitelist()
def sales_orders(customer: str | None = None, page: int = 1, page_length: int = 20, search: str | None = None, status: str | None = None):
	c = ctx(customer)
	page, length, start = _paging(page, page_length)
	filters = {"docstatus": 1, "customer": ["in", c.customers]}
	if status:
		filters["status"] = status
	or_filters = {"name": ["like", _like(search)], "po_no": ["like", _like(search)], "project": ["like", _like(search)]} if search else None
	total = len(frappe.get_all("Sales Order", filters=filters, or_filters=or_filters, pluck="name"))
	rows = frappe.get_all("Sales Order", filters=filters, or_filters=or_filters, order_by="transaction_date desc, creation desc", start=start, limit=length,
		fields=["name", "transaction_date", "delivery_date", "project", "grand_total", "currency", "status", "po_no", "per_delivered", "per_billed"])
	for r in rows:
		r.route = f"sales-orders/{r.name}"
	return _paged(rows, total, page, length)


@frappe.whitelist()
def sales_order(name: str, customer: str | None = None):
	c = ctx(customer)
	doc = own_document("Sales Order", name, c)
	return dict(name=doc.name, transaction_date=doc.transaction_date, delivery_date=doc.delivery_date, status=doc.status, po_no=doc.po_no,
		project=doc.project, currency=doc.currency, net_total=flt(doc.net_total), total_taxes=flt(doc.total_taxes_and_charges),
		grand_total=flt(doc.grand_total), per_delivered=flt(doc.per_delivered), per_billed=flt(doc.per_billed),
		items=_doc_lines(doc, ("delivered_qty",)), taxes=_taxes(doc), terms=doc.terms)


def _invoice_kind(r):
	if r.is_return:
		return _("Credit note")
	if r.get("nxg_rental_damage_settlement"):
		return _("Damage and loss")
	if r.get("nxg_jcr_billing_schedule"):
		return _("Job charges")
	if r.get("nxg_rental_billing_schedule") or r.get("nxg_rental_contract"):
		return _("Rental")
	return _("Invoice")


@frappe.whitelist()
def invoices(customer: str | None = None, page: int = 1, page_length: int = 20, search: str | None = None, status: str | None = None,
		contract: str | None = None, from_date: str | None = None, to_date: str | None = None):
	c = ctx(customer)
	page, length, start = _paging(page, page_length)
	today = getdate(nowdate())
	filters = [["docstatus", "=", 1], ["customer", "in", c.customers]]
	if status == "unpaid":
		filters.append(["outstanding_amount", ">", 0])
	elif status == "overdue":
		filters += [["outstanding_amount", ">", 0], ["due_date", "<", today]]
	elif status == "paid":
		filters += [["outstanding_amount", "<=", 0], ["is_return", "=", 0]]
	elif status == "credit":
		filters.append(["is_return", "=", 1])
	if contract:
		filters.append(["nxg_rental_contract", "=", contract])
	if from_date:
		filters.append(["posting_date", ">=", getdate(from_date)])
	if to_date:
		filters.append(["posting_date", "<=", getdate(to_date)])
	or_filters = {"name": ["like", _like(search)], "nxg_rental_contract": ["like", _like(search)], "po_no": ["like", _like(search)]} if search else None
	total = len(frappe.get_all("Sales Invoice", filters=filters, or_filters=or_filters, pluck="name"))
	rows = frappe.get_all("Sales Invoice", filters=filters, or_filters=or_filters, order_by="posting_date desc, creation desc", start=start, limit=length,
		fields=["name", "posting_date", "due_date", "grand_total", "outstanding_amount", "currency", "status", "is_return", "nxg_rental_contract",
			"nxg_rental_billing_schedule", "nxg_rental_damage_settlement", "nxg_jcr_billing_schedule"])
	periods = {}
	scheds = [r.nxg_rental_billing_schedule for r in rows if r.nxg_rental_billing_schedule]
	if scheds:
		periods = {s.name: s for s in frappe.get_all("Rental Billing Schedule", filters={"name": ["in", scheds]}, fields=["name", "from_date", "to_date"])}
	for r in rows:
		r.kind = _invoice_kind(r)
		p = periods.get(r.nxg_rental_billing_schedule)
		r.period_from, r.period_to = (p.from_date, p.to_date) if p else (None, None)
		r.rental_contract = r.nxg_rental_contract
		r.overdue = flt(r.outstanding_amount) > 0 and r.due_date and getdate(r.due_date) < today
		r.payment_status = _("Credit note") if r.is_return else _("Overdue") if r.overdue else _("Unpaid") if flt(r.outstanding_amount) > 0 else _("Paid")
		for f in ("nxg_rental_contract", "nxg_rental_billing_schedule", "nxg_rental_damage_settlement", "nxg_jcr_billing_schedule"):
			r.pop(f, None)
		r.route = f"invoices/{r.name}"
	out = _paged(rows, total, page, length)
	totals = frappe.db.sql("""select sum(outstanding_amount), sum(case when due_date < %(today)s then outstanding_amount else 0 end)
		from `tabSales Invoice` where docstatus = 1 and customer in %(customers)s and outstanding_amount > 0""", dict(c.args, today=today))[0]
	out.update(outstanding=flt(totals[0]), overdue=flt(totals[1]), currency=_currency())
	return out


@frappe.whitelist()
def invoice(name: str, customer: str | None = None):
	c = ctx(customer)
	doc = own_document("Sales Invoice", name, c)
	pays = frappe.db.sql("""select p.name, p.posting_date, r.allocated_amount, p.mode_of_payment, p.reference_no
		from `tabPayment Entry Reference` r inner join `tabPayment Entry` p on p.name = r.parent
		where p.docstatus = 1 and r.reference_doctype = 'Sales Invoice' and r.reference_name = %s order by p.posting_date""", doc.name, as_dict=True)
	today = getdate(nowdate())
	overdue = flt(doc.outstanding_amount) > 0 and doc.due_date and getdate(doc.due_date) < today
	period = frappe.db.get_value("Rental Billing Schedule", doc.get("nxg_rental_billing_schedule"), ["from_date", "to_date"], as_dict=True) if doc.get("nxg_rental_billing_schedule") else None
	return dict(name=doc.name, posting_date=doc.posting_date, due_date=doc.due_date, status=doc.status, currency=doc.currency,
		kind=_invoice_kind(doc), is_return=doc.is_return, return_against=doc.return_against, po_no=doc.po_no,
		rental_contract=doc.get("nxg_rental_contract"), period=period, net_total=flt(doc.net_total),
		total_taxes=flt(doc.total_taxes_and_charges), grand_total=flt(doc.grand_total), rounded_total=flt(doc.rounded_total),
		outstanding_amount=flt(doc.outstanding_amount), overdue=overdue,
		payment_status=_("Credit note") if doc.is_return else _("Overdue") if overdue else _("Unpaid") if flt(doc.outstanding_amount) > 0 else _("Paid"),
		items=_doc_lines(doc), taxes=_taxes(doc), payments=pays, terms=doc.terms)


@frappe.whitelist()
def payments(customer: str | None = None, page: int = 1, page_length: int = 20, search: str | None = None,
		from_date: str | None = None, to_date: str | None = None):
	c = ctx(customer)
	page, length, start = _paging(page, page_length)
	filters = [["docstatus", "=", 1], ["party_type", "=", "Customer"], ["party", "in", c.customers]]
	if from_date:
		filters.append(["posting_date", ">=", getdate(from_date)])
	if to_date:
		filters.append(["posting_date", "<=", getdate(to_date)])
	or_filters = {"name": ["like", _like(search)], "reference_no": ["like", _like(search)]} if search else None
	total = len(frappe.get_all("Payment Entry", filters=filters, or_filters=or_filters, pluck="name"))
	rows = frappe.get_all("Payment Entry", filters=filters, or_filters=or_filters, order_by="posting_date desc, creation desc", start=start, limit=length,
		fields=["name", "posting_date", "payment_type", "paid_amount", "paid_from_account_currency as currency", "mode_of_payment",
			"reference_no", "reference_date", "unallocated_amount", "status"])
	refs = {}
	if rows:
		for r in frappe.get_all("Payment Entry Reference", filters={"parent": ["in", [x.name for x in rows]], "parenttype": "Payment Entry"},
				fields=["parent", "reference_doctype", "reference_name", "allocated_amount"]):
			refs.setdefault(r.parent, []).append(r)
	for r in rows:
		r.allocations = [dict(doctype=x.reference_doctype, name=x.reference_name, amount=flt(x.allocated_amount),
			route=f"invoices/{x.reference_name}" if x.reference_doctype == "Sales Invoice" else None) for x in refs.get(r.name, [])]
		r.is_refund = r.payment_type == "Pay"
		r.status = _("Refund") if r.is_refund else _("Received")
	return _paged(rows, total, page, length)


@frappe.whitelist()
def statement(customer: str | None = None, from_date: str | None = None, to_date: str | None = None, company: str | None = None):
	"""Account statement from the general ledger: opening balance, every debit and credit, running balance."""
	c = ctx(customer)
	today = getdate(nowdate())
	to_date = getdate(to_date) if to_date else today
	from_date = getdate(from_date) if from_date else getdate(add_months(get_first_day(today), -11))
	if from_date > to_date:
		frappe.throw(_("From date must be on or before the To date"))
	companies = [x[0] for x in frappe.db.sql("""select distinct company from `tabGL Entry` where party_type = 'Customer'
		and party in %(customers)s and is_cancelled = 0""", c.args)]
	company = company if company in companies else (_settings().company if _settings().company in companies else (companies[0] if companies else _settings().company))
	a = dict(c.args, f=from_date, t=to_date, company=company)
	opening = flt(frappe.db.sql("""select sum(debit - credit) from `tabGL Entry` where party_type = 'Customer' and party in %(customers)s
		and is_cancelled = 0 and company = %(company)s and posting_date < %(f)s""", a)[0][0])
	rows = frappe.db.sql("""select posting_date, voucher_type, voucher_no, against_voucher_type, against_voucher, sum(debit) as debit, sum(credit) as credit,
			min(creation) as creation
		from `tabGL Entry` where party_type = 'Customer' and party in %(customers)s and is_cancelled = 0 and company = %(company)s
			and posting_date between %(f)s and %(t)s
		group by posting_date, voucher_type, voucher_no, against_voucher_type, against_voucher
		order by posting_date, creation limit 2000""", a, as_dict=True)
	balance, out = opening, []
	routes = {"Sales Invoice": "invoices", "Payment Entry": "payments"}
	labels = {"Sales Invoice": _("Invoice"), "Payment Entry": _("Payment"), "Journal Entry": _("Adjustment")}
	for r in rows:
		balance += flt(r.debit) - flt(r.credit)
		ref = r.against_voucher if r.against_voucher and r.against_voucher != r.voucher_no else None
		out.append(dict(date=r.posting_date, type=labels.get(r.voucher_type, _(r.voucher_type)), voucher_type=r.voucher_type, voucher_no=r.voucher_no,
			reference=ref, debit=flt(r.debit), credit=flt(r.credit), balance=balance,
			route=(f"{routes[r.voucher_type]}/{r.voucher_no}" if r.voucher_type == "Sales Invoice" else None)))
	return dict(company=company, companies=companies, currency=frappe.get_cached_value("Company", company, "default_currency") if company else None,
		from_date=from_date, to_date=to_date, opening=opening, closing=balance, rows=out,
		total_debit=sum(r["debit"] for r in out), total_credit=sum(r["credit"] for r in out), truncated=len(rows) >= 2000)


# ============================================================================= requests
GROUPS = {
	"extensions": ("Extension Request",),
	"additional": ("Additional Material Request", "Hire Enquiry"),
	"returns": ("Off-Hire Request", "Pickup Request"),
	"deliveries": ("Delivery Reschedule",),
	"service": ("Replacement Request", "Damage Report", "Missing Material Report"),
	"support": ("Complaint", "Support Request"),
	"complaints": ("Complaint", "Damage Report", "Missing Material Report"),
}


@frappe.whitelist()
def requests(customer: str | None = None, page: int = 1, page_length: int = 20, search: str | None = None, status: str | None = None,
		group: str | None = None, contract: str | None = None, request_type: str | None = None):
	c = ctx(customer)
	page, length, start = _paging(page, page_length)
	filters = {"customer": ["in", c.customers]}
	if group in GROUPS:
		filters["request_type"] = ["in", list(GROUPS[group])]
	if request_type in REQUEST_TYPES:
		filters["request_type"] = request_type
	if status == "open":
		filters["status"] = ["in", ["Open", "In Progress"]]
	elif status == "closed":
		filters["status"] = ["in", ["Completed", "Rejected", "Cancelled"]]
	elif status in ("Open", "In Progress", "Completed", "Rejected", "Cancelled"):
		filters["status"] = status
	if contract:
		filters["rental_contract"] = contract
	or_filters = {"name": ["like", _like(search)], "subject": ["like", _like(search)], "rental_contract": ["like", _like(search)],
		"rental_site": ["like", _like(search)]} if search else None
	total = len(frappe.get_all("Rental Portal Request", filters=filters, or_filters=or_filters, pluck="name"))
	rows = frappe.get_all("Rental Portal Request", filters=filters, or_filters=or_filters, order_by="creation desc", start=start, limit=length,
		fields=["name", "request_type", "status", "request_date", "required_date", "new_end_date", "rental_contract", "rental_site", "subject",
			"site_location", "response", "modified"])
	qty = {}
	if rows:
		qty = dict(frappe.db.sql("""select parent, sum(qty) from `tabRental Portal Request Item` where parent in %s group by parent""",
			[tuple(r.name for r in rows)]))
	for r in rows:
		r.label = _(REQUEST_FORMS.get(r.request_type, {}).get("label", r.request_type))
		r.qty = flt(qty.get(r.name))
		r.route = f"requests/{r.name}"
	counts = dict(frappe.db.sql("""select status, count(*) from `tabRental Portal Request` where customer in %(customers)s group by status""", c.args))
	out = _paged(rows, total, page, length)
	out["counts"] = counts
	return out


@frappe.whitelist()
def request(name: str, customer: str | None = None):
	c = ctx(customer)
	doc = own_document("Rental Portal Request", name, c, submitted=False)
	messages = frappe.get_all("Communication", filters={"reference_doctype": doc.doctype, "reference_name": doc.name,
		"communication_type": "Communication"}, order_by="communication_date asc",
		fields=["name", "sender", "sender_full_name", "sent_or_received", "communication_date", "content", "subject"])
	for m in messages:
		m.content = strip_html(m.content or "").strip()[:4000]
		m.mine = m.sent_or_received == "Received"
	files = frappe.get_all("File", filters={"attached_to_doctype": doc.doctype, "attached_to_name": doc.name},
		fields=["name", "file_name", "file_size", "creation"], order_by="creation asc")
	ref = None
	if doc.reference_doctype and doc.reference_name:
		route = {"Hire Order": f"orders/{doc.reference_name}", "Hire Off-Hire Note": f"returns/{doc.reference_name}",
			"Rental Contract": f"orders/{doc.reference_name}"}.get(doc.reference_doctype)
		ref = dict(doctype=_(doc.reference_doctype), name=doc.reference_name, route=route)
	return dict(name=doc.name, request_type=doc.request_type, label=_(REQUEST_FORMS.get(doc.request_type, {}).get("label", doc.request_type)),
		status=doc.status, request_date=doc.request_date, raised_by=frappe.db.get_value("User", doc.raised_by, "full_name") if doc.raised_by else None,
		rental_contract=doc.rental_contract, rental_site=doc.rental_site, site_location=doc.site_location, subject=doc.subject,
		required_date=doc.required_date, expected_return_date=doc.expected_return_date, new_end_date=doc.new_end_date,
		remarks=doc.remarks, response=doc.response, reference=ref,
		items=[dict(item_code=d.item_code, item_name=d.item_name, uom=d.uom, qty=flt(d.qty)) for d in doc.items],
		messages=messages, files=files, can_cancel=doc.status == "Open", can_message=doc.status in ("Open", "In Progress"),
		can_attach=doc.status in ("Open", "In Progress") and len(files) < 10, created=doc.creation)


@frappe.whitelist()
def request_options(customer: str | None = None, contract: str | None = None):
	"""What a new request form offers: the customer's live contracts (with what is on site) and the catalogue."""
	c = ctx(customer)
	contracts = frappe.get_all("Rental Contract", filters={"customer": ["in", c.customers], "docstatus": 1, "status": ["in", list(LIVE)]},
		fields=["name", "rental_site", "end_date", "source_document", "total_at_site_qty", "customer"], order_by="contract_date desc")
	out = {"contracts": contracts, "sites": _sites(c), "catalogue": [], "site_items": []}
	if contract:
		match = next((x for x in contracts if x.name == contract), None)
		if not match:
			raise frappe.PermissionError(_("Contract {0} is not open for requests").format(contract))
		out["site_items"] = _site_items(contract)
		out["contract_items"] = frappe.get_all("Rental Contract Item", filters={"parent": contract, "parenttype": "Rental Contract"},
			fields=["item_code", "item_name", "uom", "qty"], order_by="idx")
	show_rates = cint(_settings().portal_show_rates)
	fields = ["item as item_code", "item_name", "category", "stock_uom as uom"] + (["daily_rate", "weekly_rate", "monthly_rate"] if show_rates else [])
	out["catalogue"] = frappe.get_all("Rental Item Profile", filters={"disabled": 0}, fields=fields, order_by="category asc, item_name asc")
	return out


def _site_items(contract):
	totals = {}
	for (item_code, _ownership, _cho), qty in ledger.get_site_balance(contract).items():
		totals[item_code] = totals.get(item_code, 0) + flt(qty)
	out = []
	for item_code, qty in sorted(totals.items()):
		if qty > 0:
			item = frappe.get_cached_value("Item", item_code, ["item_name", "stock_uom"], as_dict=True)
			out.append({"item_code": item_code, "item_name": item.item_name, "uom": item.stock_uom, "at_site_qty": qty})
	return out


@frappe.whitelist(methods=["POST"])
def submit_request(data: str | dict, customer: str | None = None):
	"""Raise a request. Everything is checked again here: the contract is the customer's and live, the items
	and quantities fit what was ordered or is on site, the dates make sense."""
	c = ctx(customer)
	if c.preview:
		frappe.throw(_("Staff previews are read-only."))
	if not cint(_settings().portal_allow_requests):
		frappe.throw(_("Online requests are currently switched off. Please contact us directly."))
	d = frappe._dict(frappe.parse_json(data) if isinstance(data, str) else data or {})
	request_type = d.get("request_type")
	form = REQUEST_FORMS.get(request_type)
	if request_type not in REQUEST_TYPES or not form:
		frappe.throw(_("Unknown request type"))
	today = getdate(nowdate())
	items = [i for i in (d.get("items") or []) if isinstance(i, dict) and i.get("item_code") and flt(i.get("qty")) > 0]
	text = lambda v, n: (v or "").strip()[:n]  # noqa: E731
	doc = frappe.new_doc("Rental Portal Request")
	doc.update({"request_type": request_type, "customer": c.customers[0], "raised_by": frappe.session.user, "request_date": nowdate(),
		"remarks": text(d.get("remarks"), 2000), "subject": text(d.get("subject"), 140), "site_location": text(d.get("site_location"), 140),
		"company": _settings().company})
	contract = None
	if d.get("rental_contract"):
		contract = frappe.db.get_value("Rental Contract", d.rental_contract, ["name", "customer", "company", "docstatus", "status", "end_date",
			"rental_site"], as_dict=True)
		if not contract or contract.docstatus != 1 or contract.customer not in c.customers:
			raise frappe.PermissionError(_("Contract not found"))
		if contract.status not in LIVE:
			frappe.throw(_("Contract {0} is closed").format(contract.name))
		doc.update({"rental_contract": contract.name, "customer": contract.customer, "company": contract.company, "rental_site": contract.rental_site})
	elif request_type in CONTRACT_TYPES:
		frappe.throw(_("Choose the rental order this request is about"))
	elif len(c.customers) > 1 and d.get("for_customer") in c.customers:
		doc.customer = d.for_customer
	if form.get("subject") and not doc.subject:
		frappe.throw(_("Add a short subject"))
	if form.get("remarks_reqd") and not doc.remarks:
		frappe.throw(_("Please describe the request"))
	if form.get("date"):
		value = d.get("required_date")
		if form.get("date_reqd") and not value:
			frappe.throw(_("{0} is required").format(_(form["date"])))
		if value:
			if getdate(value) < today:
				frappe.throw(_("{0} cannot be in the past").format(_(form["date"])))
			doc.required_date = getdate(value)
	if form.get("return_date") and d.get("expected_return_date"):
		if doc.required_date and getdate(d.expected_return_date) < doc.required_date:
			frappe.throw(_("The expected return date cannot be before the start date"))
		doc.expected_return_date = getdate(d.expected_return_date)
	if form.get("new_end_date"):
		value = d.get("new_end_date")
		if not value or getdate(value) <= getdate(contract.end_date):
			frappe.throw(_("The new return date must be after the current return date {0}").format(frappe.format(contract.end_date, "Date")))
		doc.new_end_date = getdate(value)
	if form.get("items"):
		if not items and not form.get("items_optional"):
			frappe.throw(_("Add at least one item and quantity"))
		if form["items"] == "catalogue":
			rentable = set(frappe.get_all("Rental Item Profile", filters={"disabled": 0}, pluck="item"))
			for i in items:
				if i["item_code"] not in rentable:
					frappe.throw(_("{0} is not available for hire").format(i["item_code"]))
		else:
			at_site = {i["item_code"]: i["at_site_qty"] for i in _site_items(contract.name)}
			for i in items:
				if flt(i["qty"]) > flt(at_site.get(i["item_code"])) + 1e-6:
					frappe.throw(_("{0}: {1} asked for but {2} is on site").format(i["item_code"], flt(i["qty"]), flt(at_site.get(i["item_code"]))))
	else:
		items = []
	seen = set()
	for i in items:
		if i["item_code"] in seen:
			frappe.throw(_("{0} is listed twice").format(i["item_code"]))
		seen.add(i["item_code"])
		doc.append("items", {"item_code": i["item_code"], "qty": flt(i["qty"])})
	doc.flags.ignore_permissions = True
	doc.insert()
	return {"name": doc.name, "route": f"requests/{doc.name}"}


@frappe.whitelist(methods=["POST"])
def cancel_request(name: str, customer: str | None = None):
	c = ctx(customer)
	if c.preview:
		frappe.throw(_("Staff previews are read-only."))
	doc = own_document("Rental Portal Request", name, c, submitted=False)
	if doc.status != "Open":
		frappe.throw(_("This request is already being handled. Please send the team a message instead."))
	doc.db_set("status", "Cancelled")
	return {"name": doc.name}


@frappe.whitelist(methods=["POST"])
def add_request_message(name: str, message: str, customer: str | None = None):
	"""A message from the customer on their request: a Communication the rental team sees on the request."""
	c = ctx(customer)
	if c.preview:
		frappe.throw(_("Staff previews are read-only."))
	doc = own_document("Rental Portal Request", name, c, submitted=False)
	if doc.status not in ("Open", "In Progress"):
		frappe.throw(_("This request is closed. Raise a new request instead."))
	message = (message or "").strip()
	if not message:
		frappe.throw(_("Write a message first"))
	comm = frappe.get_doc({"doctype": "Communication", "communication_type": "Communication", "communication_medium": "Other",
		"sent_or_received": "Received", "reference_doctype": doc.doctype, "reference_name": doc.name, "subject": _("Re: {0}").format(doc.name),
		"content": frappe.utils.escape_html(message[:4000]).replace("\n", "<br>"), "sender": frappe.session.user,
		"sender_full_name": frappe.db.get_value("User", frappe.session.user, "full_name"), "communication_date": frappe.utils.now_datetime()})
	comm.flags.ignore_permissions = True
	comm.insert()
	return {"name": comm.name}


@frappe.whitelist(methods=["POST"])
def upload_attachment(name: str, filename: str, content: str, customer: str | None = None):
	"""Attach a photo or document (base64) to one of the customer's open requests. Stored as a private file."""
	c = ctx(customer)
	if c.preview:
		frappe.throw(_("Staff previews are read-only."))
	doc = own_document("Rental Portal Request", name, c, submitted=False)
	if doc.status not in ("Open", "In Progress"):
		frappe.throw(_("This request is closed"))
	if frappe.db.count("File", {"attached_to_doctype": doc.doctype, "attached_to_name": doc.name}) >= 10:
		frappe.throw(_("A request can have up to 10 attachments"))
	filename = re.sub(r"[^\w.\- ]", "_", (filename or "file").strip())[:120] or "file"
	ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
	if ext not in ATTACH_EXT:
		frappe.throw(_("This file type is not accepted. Use a PDF, an image, or an Office document."))
	try:
		raw = base64.b64decode((content or "").split(",", 1)[-1], validate=True)
	except Exception:
		frappe.throw(_("The file could not be read"))
	if not raw or len(raw) > ATTACH_MAX:
		frappe.throw(_("Files must be smaller than 10 MB"))
	f = frappe.get_doc({"doctype": "File", "file_name": filename, "attached_to_doctype": doc.doctype, "attached_to_name": doc.name,
		"is_private": 1, "content": raw})
	f.flags.ignore_permissions = True
	f.save()
	return {"name": f.name, "file_name": f.file_name, "file_size": f.file_size}


@frappe.whitelist()
def download_attachment(request: str, file: str, customer: str | None = None):
	c = ctx(customer)
	doc = own_document("Rental Portal Request", request, c, submitted=False)
	f = frappe.db.get_value("File", {"name": file, "attached_to_doctype": doc.doctype, "attached_to_name": doc.name}, "name")
	if not f:
		raise frappe.PermissionError(_("File not found"))
	fdoc = frappe.get_doc("File", f)
	frappe.local.response.filename = fdoc.file_name
	frappe.local.response.filecontent = fdoc.get_content()
	frappe.local.response.type = "download"
	frappe.local.response.content_type = mimetypes.guess_type(fdoc.file_name)[0] or "application/octet-stream"


@frappe.whitelist()
def download_pdf(doctype: str, name: str, customer: str | None = None):
	"""A PDF of one of the customer's own submitted documents, in the document's default print format."""
	c = ctx(customer)
	if doctype not in PDF_DOCTYPES:
		raise frappe.PermissionError(_("This document cannot be downloaded"))
	doc = own_document(doctype, name, c)
	frappe.flags.ignore_print_permissions = True
	try:
		pdf = frappe.get_print(doctype, doc.name, doc=doc, as_pdf=True)
	finally:
		frappe.flags.ignore_print_permissions = False
	frappe.local.response.filename = f"{doc.name}.pdf"
	frappe.local.response.filecontent = pdf
	frappe.local.response.type = "pdf"


# ============================================================================= documents and history
@frappe.whitelist()
def documents(customer: str | None = None, tab: str = "rental", page: int = 1, page_length: int = 25, search: str | None = None):
	"""The customer's document library, newest first, each with a PDF download."""
	c = ctx(customer)
	page, length, start = _paging(page, page_length)
	a = dict(c.args, parties=_quotation_parties(c))
	q = ""
	if search:
		a["q"] = _like(search)
		q = " and (t.name like %(q)s or ifnull(t.reference, '') like %(q)s)"
	parts = {
		"rental": [
			"""select 'Rental Contract' as doctype, name, contract_date as date, rental_site as reference, null as amount, status, creation
				from `tabRental Contract` where docstatus = 1 and customer in %(customers)s""",
			"""select 'Hire Order' as doctype, name, order_date as date, rental_site as reference, estimated_amount as amount, status as status, creation
				from `tabHire Order` where docstatus = 1 and customer in %(customers)s""",
			"""select 'Hire Order Contract' as doctype, name, order_date as date, rental_site as reference, total_contract_amount as amount, status as status, creation
				from `tabHire Order Contract` where docstatus = 1 and customer in %(customers)s""",
			"""select 'Quotation' as doctype, name, transaction_date as date, title as reference, grand_total as amount, status as status, creation
				from `tabQuotation` where docstatus = 1 and party_name in %(parties)s""",
			"""select 'Sales Order' as doctype, name, transaction_date as date, po_no as reference, grand_total as amount, status as status, creation
				from `tabSales Order` where docstatus = 1 and customer in %(customers)s""",
		],
		"delivery": [
			"""select 'Hire Delivery Order' as doctype, name, posting_date as date, rental_site as reference, null as amount, 'Delivered' as status, creation
				from `tabHire Delivery Order` where docstatus = 1 and customer in %(customers)s""",
			"""select 'Hire Off-Hire Note' as doctype, name, return_date as date, rental_site as reference, null as amount, status as status, creation
				from `tabHire Off-Hire Note` where docstatus = 1 and customer in %(customers)s""",
		],
		"invoices": [
			"""select 'Sales Invoice' as doctype, name, posting_date as date, nxg_rental_contract as reference, grand_total as amount, status as status, creation
				from `tabSales Invoice` where docstatus = 1 and customer in %(customers)s""",
			"""select 'Payment Entry' as doctype, name, posting_date as date, reference_no as reference, paid_amount as amount, status as status, creation
				from `tabPayment Entry` where docstatus = 1 and party_type = 'Customer' and party in %(customers)s""",
		],
	}.get(tab)
	if not parts:
		frappe.throw(_("Unknown document group"))
	union = " union all ".join(parts)
	total = frappe.db.sql(f"select count(*) from ({union}) t where 1=1{q}", a)[0][0]
	rows = frappe.db.sql(f"select * from ({union}) t where 1=1{q} order by t.date desc, t.creation desc limit {length} offset {start}", a, as_dict=True)
	routes = {"Rental Contract": "orders", "Hire Order": "orders", "Hire Order Contract": "orders", "Quotation": "quotations",
		"Sales Order": "sales-orders", "Hire Delivery Order": "deliveries", "Hire Off-Hire Note": "returns", "Sales Invoice": "invoices"}
	for r in rows:
		r.label = _(r.doctype)
		r.route = f"{routes[r.doctype]}/{r.name}" if r.doctype in routes else None
	out = _paged(rows, total, page, length)
	out["currency"] = _currency()
	return out


@frappe.whitelist()
def history(customer: str | None = None, page: int = 1, page_length: int = 25, search: str | None = None,
		from_date: str | None = None, to_date: str | None = None):
	"""Every delivery and return, newest first."""
	c = ctx(customer)
	page, length, start = _paging(page, page_length)
	a, cond = dict(c.args), ""
	if search:
		a["q"] = _like(search)
		cond += " and (t.name like %(q)s or t.rental_contract like %(q)s or t.rental_site like %(q)s)"
	if from_date:
		a["f"] = getdate(from_date)
		cond += " and t.date >= %(f)s"
	if to_date:
		a["t"] = getdate(to_date)
		cond += " and t.date <= %(t)s"
	union = """select 'delivery' as kind, name, posting_date as date, rental_contract, rental_site, total_qty as qty, 0 as lost_qty, creation
			from `tabHire Delivery Order` where docstatus = 1 and customer in %(customers)s
		union all
		select 'return', name, return_date, rental_contract, rental_site, total_returned_qty, total_lost_qty, creation
			from `tabHire Off-Hire Note` where docstatus = 1 and customer in %(customers)s"""
	total = frappe.db.sql(f"select count(*) from ({union}) t where 1=1{cond}", a)[0][0]
	rows = frappe.db.sql(f"select * from ({union}) t where 1=1{cond} order by t.date desc, t.creation desc limit {length} offset {start}", a, as_dict=True)
	for r in rows:
		r.route = f"{'deliveries' if r.kind == 'delivery' else 'returns'}/{r.name}"
	closed = frappe.db.sql("""select count(*), sum(total_contract_qty) from `tabRental Contract` where docstatus = 1 and customer in %(customers)s
		and status in ('Off Hired', 'Completed')""", c.args)[0]
	out = _paged(rows, total, page, length)
	out["closed_contracts"] = cint(closed[0])
	return out


# ============================================================================= notifications and communication
ROUTES = {"Rental Contract": "orders", "Hire Order": "orders", "Hire Order Contract": "orders", "Hire Delivery Order": "deliveries",
	"Hire Off-Hire Note": "returns", "Sales Invoice": "invoices", "Quotation": "quotations", "Sales Order": "sales-orders",
	"Rental Portal Request": "requests", "Payment Entry": "payments", "Rental Return Inspection": None}


@frappe.whitelist()
def notifications(page: int = 1, page_length: int = 20, unread: int = 0):
	"""The session user's own notifications."""
	if frappe.session.user == "Guest":
		raise frappe.PermissionError
	page, length, start = _paging(page, page_length)
	filters = {"for_user": frappe.session.user}
	if cint(unread):
		filters["read"] = 0
	total = frappe.db.count("Notification Log", filters)
	rows = frappe.get_all("Notification Log", filters=filters, order_by="creation desc", start=start, limit=length,
		fields=["name", "subject", "document_type", "document_name", "read", "creation", "type"])
	for r in rows:
		r.subject = strip_html(r.subject or "")
		base = ROUTES.get(r.document_type)
		if r.document_type == "Payment Entry":
			r.route = "payments"
		elif r.document_type == "Rental Return Inspection":
			note = frappe.db.get_value("Rental Return Inspection", r.document_name, "hire_off_hire_note")
			r.route = f"returns/{note}" if note else None
		else:
			r.route = f"{base}/{r.document_name}" if base and r.document_name else None
	out = _paged(rows, total, page, length)
	out["unread"] = frappe.db.count("Notification Log", {"for_user": frappe.session.user, "read": 0})
	return out


@frappe.whitelist(methods=["POST"])
def mark_notifications_read(names: str | list | None = None):
	if frappe.session.user == "Guest":
		raise frappe.PermissionError
	names = frappe.parse_json(names) if isinstance(names, str) else names
	filters = {"for_user": frappe.session.user, "read": 0}
	if names:
		filters["name"] = ["in", list(names)[:200]]
	for n in frappe.get_all("Notification Log", filters=filters, pluck="name"):
		frappe.db.set_value("Notification Log", n, "read", 1, update_modified=False)
	return {"unread": frappe.db.count("Notification Log", {"for_user": frappe.session.user, "read": 0})}


@frappe.whitelist()
def communications(customer: str | None = None, page: int = 1, page_length: int = 20, search: str | None = None):
	"""E-mails and messages exchanged with the rental team: about the customer, or on one of their requests."""
	c = ctx(customer)
	page, length, start = _paging(page, page_length)
	a, cond = dict(c.args), ""
	if search:
		a["q"] = _like(search)
		cond = " and (m.subject like %(q)s or m.reference_name like %(q)s)"
	body = f"""from `tabCommunication` m
		where m.communication_type = 'Communication' and m.sent_or_received in ('Sent', 'Received') and (
			(m.reference_doctype = 'Rental Portal Request' and m.reference_name in (select name from `tabRental Portal Request` where customer in %(customers)s))
			or exists (select 1 from `tabCommunication Link` k where k.parent = m.name and k.link_doctype = 'Customer' and k.link_name in %(customers)s)
			or (m.reference_doctype = 'Customer' and m.reference_name in %(customers)s)){cond}"""
	total = frappe.db.sql(f"select count(*) {body}", a)[0][0]
	rows = frappe.db.sql(f"""select m.name, m.subject, m.sender_full_name, m.sender, m.sent_or_received, m.communication_date,
			m.reference_doctype, m.reference_name, m.content {body} order by m.communication_date desc limit {length} offset {start}""", a, as_dict=True)
	for r in rows:
		r.content = strip_html(r.content or "").strip()[:1500]
		r.direction = "from_you" if r.sent_or_received == "Received" else "from_team"
		base = ROUTES.get(r.reference_doctype)
		r.route = f"{base}/{r.reference_name}" if base and r.reference_name else None
		r.reference_label = _(r.reference_doctype) if r.reference_doctype else None
	return _paged(rows, total, page, length)


# ============================================================================= search
@frappe.whitelist()
def search(q: str, customer: str | None = None):
	"""The customer's own records matching the text, grouped by kind (5 each)."""
	c = ctx(customer)
	q = (q or "").strip()
	if len(q) < 2:
		return []
	like = _like(q)
	groups = []

	def add(label, icon, rows, route, title, sub):
		if rows:
			groups.append({"label": label, "icon": icon, "rows": [{"title": title(r), "sub": sub(r), "route": route(r)} for r in rows]})

	a = dict(c.args, q=like, parties=_quotation_parties(c))
	add(_("Rental orders"), "file-check-2", frappe.db.sql("""select name, rental_site, status, source_document from `tabRental Contract`
		where docstatus = 1 and customer in %(customers)s and (name like %(q)s or rental_site like %(q)s or ifnull(project, '') like %(q)s
		or ifnull(source_document, '') like %(q)s) order by contract_date desc limit 5""", a, as_dict=True),
		lambda r: f"orders/{r.name}", lambda r: r.source_document or r.name, lambda r: f"{r.name} · {r.rental_site} · {_(r.status)}")
	add(_("Hire orders awaiting contract"), "clipboard-list", frappe.db.sql("""select name, rental_site from `tabHire Order`
		where docstatus = 1 and status = 'Open' and customer in %(customers)s and (name like %(q)s or rental_site like %(q)s) limit 5""", a, as_dict=True),
		lambda r: f"orders/{r.name}", lambda r: r.name, lambda r: r.rental_site)
	add(_("Deliveries"), "truck", frappe.db.sql("""select name, posting_date, rental_site from `tabHire Delivery Order`
		where docstatus = 1 and customer in %(customers)s and (name like %(q)s or rental_contract like %(q)s or ifnull(vehicle_no, '') like %(q)s)
		order by posting_date desc limit 5""", a, as_dict=True),
		lambda r: f"deliveries/{r.name}", lambda r: r.name, lambda r: f"{frappe.format(r.posting_date, 'Date')} · {r.rental_site}")
	add(_("Returns"), "undo-2", frappe.db.sql("""select name, return_date, rental_site from `tabHire Off-Hire Note`
		where docstatus = 1 and customer in %(customers)s and (name like %(q)s or rental_contract like %(q)s) order by return_date desc limit 5""", a, as_dict=True),
		lambda r: f"returns/{r.name}", lambda r: r.name, lambda r: f"{frappe.format(r.return_date, 'Date')} · {r.rental_site}")
	add(_("Invoices"), "receipt", frappe.db.sql("""select name, posting_date, grand_total, currency from `tabSales Invoice`
		where docstatus = 1 and customer in %(customers)s and (name like %(q)s or ifnull(nxg_rental_contract, '') like %(q)s or ifnull(po_no, '') like %(q)s)
		order by posting_date desc limit 5""", a, as_dict=True),
		lambda r: f"invoices/{r.name}", lambda r: r.name, lambda r: f"{frappe.format(r.posting_date, 'Date')} · {frappe.utils.fmt_money(r.grand_total, currency=r.currency)}")
	add(_("Quotations"), "file-text", frappe.db.sql("""select name, transaction_date, title from `tabQuotation`
		where docstatus = 1 and party_name in %(parties)s and (name like %(q)s or ifnull(title, '') like %(q)s) order by transaction_date desc limit 5""", a, as_dict=True),
		lambda r: f"quotations/{r.name}", lambda r: r.name, lambda r: f"{frappe.format(r.transaction_date, 'Date')} · {r.title or ''}")
	add(_("Sales orders"), "shopping-cart", frappe.db.sql("""select name, transaction_date, status from `tabSales Order`
		where docstatus = 1 and customer in %(customers)s and (name like %(q)s or ifnull(po_no, '') like %(q)s) order by transaction_date desc limit 5""", a, as_dict=True),
		lambda r: f"sales-orders/{r.name}", lambda r: r.name, lambda r: f"{frappe.format(r.transaction_date, 'Date')} · {_(r.status)}")
	add(_("Requests"), "messages-square", frappe.db.sql("""select name, request_type, status, subject from `tabRental Portal Request`
		where customer in %(customers)s and (name like %(q)s or ifnull(subject, '') like %(q)s or ifnull(rental_contract, '') like %(q)s)
		order by creation desc limit 5""", a, as_dict=True),
		lambda r: f"requests/{r.name}", lambda r: r.subject or r.name,
		lambda r: f"{r.name} · {_(REQUEST_FORMS.get(r.request_type, {}).get('label', r.request_type))} · {_(r.status)}")
	add(_("Payments"), "wallet", frappe.db.sql("""select name, posting_date, paid_amount, paid_from_account_currency as currency from `tabPayment Entry`
		where docstatus = 1 and party_type = 'Customer' and party in %(customers)s and (name like %(q)s or ifnull(reference_no, '') like %(q)s)
		order by posting_date desc limit 5""", a, as_dict=True),
		lambda r: "payments", lambda r: r.name, lambda r: f"{frappe.format(r.posting_date, 'Date')} · {frappe.utils.fmt_money(r.paid_amount, currency=r.currency)}")
	return groups


# ============================================================================= account
def _my_contact(c):
	user = frappe.session.user
	names = frappe.get_all("Contact", filters={"user": user}, pluck="name") or frappe.get_all("Contact", filters={"email_id": user}, pluck="name")
	for n in names:
		linked = frappe.get_all("Dynamic Link", filters={"parenttype": "Contact", "parent": n, "link_doctype": "Customer",
			"link_name": ["in", c.customers]}, pluck="link_name")
		if linked:
			return frappe.get_doc("Contact", n)
	return None


@frappe.whitelist()
def profile(customer: str | None = None):
	c = ctx(customer)
	out = []
	for name in c.customers:
		cust = frappe.get_doc("Customer", name)
		address_names = frappe.get_all("Dynamic Link", filters={"parenttype": "Address", "link_doctype": "Customer", "link_name": name}, pluck="parent")
		addresses = frappe.get_all("Address", filters={"name": ["in", address_names or [""]], "disabled": 0},
			fields=["name", "address_title", "address_type", "address_line1", "address_line2", "city", "state", "country", "pincode",
				"is_primary_address", "is_shipping_address", "phone", "email_id"], order_by="is_primary_address desc")
		contact_names = frappe.get_all("Dynamic Link", filters={"parenttype": "Contact", "link_doctype": "Customer", "link_name": name}, pluck="parent")
		contacts = frappe.get_all("Contact", filters={"name": ["in", contact_names or [""]], "status": ["!=", "Passive"]},
			fields=["name", "full_name", "first_name", "last_name", "email_id", "phone", "mobile_no", "designation", "is_primary_contact", "user"],
			order_by="is_primary_contact desc, full_name asc")
		for k in contacts:
			k.portal_user = bool(k.user)
			k.pop("user")
		out.append(dict(name=cust.name, customer_name=cust.customer_name, customer_group=cust.customer_group, customer_type=cust.customer_type,
			tax_id=cust.tax_id, email=cust.email_id, mobile=cust.mobile_no, website=cust.website,
			primary_contact=frappe.db.get_value("Contact", cust.customer_primary_contact, "full_name") if cust.customer_primary_contact else None,
			addresses=addresses, contacts=contacts,
			sites=frappe.get_all("Rental Site", filters={"customer": name, "disabled": 0},
				fields=["name", "site_name", "location", "site_contact", "contact_phone", "project"], order_by="site_name asc")))
	me = _my_contact(c)
	return dict(customers=out, me=dict(name=me.name, first_name=me.first_name, last_name=me.last_name, email=me.email_id, phone=me.phone,
		mobile_no=me.mobile_no, designation=me.designation) if me else None, can_edit_contact=bool(me) and not c.preview)


@frappe.whitelist(methods=["POST"])
def update_my_contact(first_name: str | None = None, last_name: str | None = None, phone: str | None = None,
		mobile_no: str | None = None, designation: str | None = None, customer: str | None = None):
	"""The logged-in person may correct their own contact details; nothing else on the account changes here."""
	c = ctx(customer)
	if c.preview:
		frappe.throw(_("Staff previews are read-only."))
	me = _my_contact(c)
	if not me:
		frappe.throw(_("Your login has no contact record. Ask the rental team to add one."))
	clean = lambda v, n: re.sub(r"[<>]", "", (v or "").strip())[:n]  # noqa: E731
	if first_name is not None:
		if not clean(first_name, 60):
			frappe.throw(_("First name is required"))
		me.first_name = clean(first_name, 60)
	if last_name is not None:
		me.last_name = clean(last_name, 60)
	if designation is not None:
		me.designation = clean(designation, 80)
	for field, value in (("phone", phone), ("mobile_no", mobile_no)):
		if value is not None:
			value = clean(value, 30)
			if value and not re.fullmatch(r"[0-9+()\-. ]{5,30}", value):
				frappe.throw(_("Enter a valid phone number"))
			me.set(field, value)
			rows = [p for p in me.phone_nos if (p.is_primary_phone if field == "phone" else p.is_primary_mobile_no)]
			if rows:
				rows[0].phone = value
			elif value:
				me.append("phone_nos", {"phone": value, "is_primary_phone": int(field == "phone"), "is_primary_mobile_no": int(field == "mobile_no")})
	me.flags.ignore_permissions = True
	me.save()
	return {"ok": 1}


@frappe.whitelist()
def get_settings():
	if frappe.session.user == "Guest":
		raise frappe.PermissionError
	from frappe.desk.doctype.notification_settings.notification_settings import create_notification_settings

	user = frappe.session.user
	if not frappe.db.exists("Notification Settings", user):
		create_notification_settings(user)
	ns = frappe.db.get_value("Notification Settings", user, ["enabled", "enable_email_notifications"], as_dict=True) or frappe._dict()
	return {"email_notifications": cint(ns.enabled) and cint(ns.enable_email_notifications), "email": user,
		"language": frappe.db.get_value("User", user, "language")}


@frappe.whitelist(methods=["POST"])
def save_settings(email_notifications: int = 1):
	if frappe.session.user == "Guest":
		raise frappe.PermissionError
	get_settings()
	frappe.db.set_value("Notification Settings", frappe.session.user, {"enabled": 1, "enable_email_notifications": cint(email_notifications)})
	return get_settings()
