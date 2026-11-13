"""Command Center dashboard: KPIs, work queue, charts and today's operations.

Every figure is read from real records: the Rental Stock Position report and the Rental Ownership
Ledger for stock, the Stock Ledger for own stock on past dates, submitted Sales and Purchase Invoices
for money, and the rental documents themselves for the queue. Nothing is estimated or stored.

Stock definitions match the Rental Stock Position report exactly, so the dashboard and the report
always agree:
  own rentable  = Rental Yard + at customer sites (own) + under inspection + in repair
  rentable      = own rentable + cross-hired material in our custody
  on hire       = at customer sites, own and cross-hired (Rental Ownership Ledger, At Site)
  utilization   = on hire / rentable
"""
from bisect import bisect_right

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, date_diff, flt, get_first_day, get_last_day, getdate, nowdate

from thinknxg_rental.command_center.registry import entry_route

CACHE_SECONDS = 60
PERIODS = ("today", "week", "month", "quarter", "year", "custom")


# ----------------------------------------------------------------------------- period
def resolve_period(period="month", from_date=None, to_date=None):
	today = getdate(nowdate())
	period = period if period in PERIODS else "month"
	if period == "today":
		start = end = today
	elif period == "week":
		start = add_days(today, -today.weekday())
		end = add_days(start, 6)
	elif period == "month":
		start, end = getdate(get_first_day(today)), getdate(get_last_day(today))
	elif period == "quarter":
		q_start_month = 3 * ((today.month - 1) // 3) + 1
		start = today.replace(month=q_start_month, day=1)
		end = getdate(get_last_day(add_months(start, 2)))
	elif period == "year":
		start, end = today.replace(month=1, day=1), today.replace(month=12, day=31)
	else:
		if not (from_date and to_date):
			frappe.throw(_("Choose both dates for a custom period"))
		start, end = getdate(from_date), getdate(to_date)
		if end < start:
			frappe.throw(_("The period cannot end before it starts"))
		if date_diff(end, start) > 3 * 366:
			frappe.throw(_("Choose a period of three years or less"))
	days = date_diff(end, start) + 1
	prev_end = add_days(start, -1)
	prev_start = add_days(prev_end, -(days - 1))
	return frappe._dict(period=period, from_date=start, to_date=end, prev_from=getdate(prev_start), prev_to=getdate(prev_end), days=days)


def buckets(start, end):
	"""Chart buckets for a range: days up to six weeks, weeks up to about seven months, else months."""
	days = date_diff(end, start) + 1
	out = []
	if days <= 42:
		d = start
		while d <= end:
			out.append((d, d, d.strftime("%d %b")))
			d = add_days(d, 1)
		return "day", out
	if days <= 210:
		d = add_days(start, -start.weekday())
		while d <= end:
			b_end = add_days(d, 6)
			out.append((max(d, start), min(getdate(b_end), end), d.strftime("%d %b")))
			d = add_days(d, 7)
		return "week", out
	d = getdate(get_first_day(start))
	while d <= end:
		b_end = getdate(get_last_day(d))
		out.append((max(d, start), min(b_end, end), d.strftime("%b %Y")))
		d = add_days(b_end, 1)
	return "month", out


# ----------------------------------------------------------------------------- stock position over time
def _own_warehouses():
	s = frappe.get_cached_doc("Rental Settings")
	whs = {s.rental_yard_warehouse, s.inspection_warehouse, s.repair_warehouse}
	whs.update(frappe.get_all("Rental Site", filters={"site_warehouse": ["is", "set"]}, pluck="site_warehouse"))
	return [w for w in whs if w]


def position_history():
	"""Cumulative series to answer 'what was the position on date d' with bisect, from three grouped queries."""
	items = frappe.get_all("Rental Item Profile", filters={"disabled": 0}, pluck="item")
	whs = _own_warehouses()
	own = []
	if items and whs:
		own = frappe.db.sql(
			"""select posting_date, sum(actual_qty) from `tabStock Ledger Entry`
			where is_cancelled = 0 and warehouse in %(whs)s and item_code in %(items)s
			group by posting_date order by posting_date""",
			{"whs": tuple(whs), "items": tuple(items)},
		)
	led = frappe.db.sql(
		"""select posting_date, position_type, ownership, sum(qty) from `tabRental Ownership Ledger`
		group by posting_date, position_type, ownership order by posting_date"""
	)

	def series(rows):
		dates, values, total = [], [], 0.0
		for d, q in rows:
			total += flt(q)
			if dates and dates[-1] == d:
				values[-1] = total
			else:
				dates.append(d)
				values.append(total)
		return dates, values

	split = {"own": [], "site_own": [], "site_cross": [], "custody": []}
	split["own"] = [(d, q) for d, q in own]
	for d, ptype, ownership, q in led:
		if ptype == "At Site":
			split["site_own" if ownership == "Own" else "site_cross"].append((d, q))
		elif ptype == "Cross Hire Custody":
			split["custody"].append((d, q))
	hist = {k: series(v) for k, v in split.items()}

	def at(key, d):
		dates, values = hist[key]
		i = bisect_right(dates, getdate(d))
		return values[i - 1] if i else 0.0

	def position(d):
		own_q, own_site, cross_site, custody = at("own", d), at("site_own", d), at("site_cross", d), at("custody", d)
		rentable = own_q + custody
		on_hire = own_site + cross_site
		return frappe._dict(rentable=rentable, own=own_q, custody=custody, site_own=own_site, site_cross=cross_site,
			on_hire=on_hire, utilization=(on_hire / rentable * 100) if rentable else 0)

	return position


# ----------------------------------------------------------------------------- KPIs
def _stock():
	from thinknxg_rental.portal.admin import get_stock_rows

	return get_stock_rows()


def kpis(p, stock, position, currency):
	today = getdate(nowdate())
	total = lambda key: sum(flt(r[key]) for r in stock)  # noqa: E731
	own_site, cross_site = total("at_site_own"), total("at_site_cross_hire")
	on_hire = own_site + cross_site
	rentable = total("rentable")
	custody = total("at_site_cross_hire") + total("cross_hire_not_at_site")
	util = round(on_hire / rentable * 100, 1) if rentable else 0
	start = position(add_days(p.from_date, -1)) if p.from_date <= today else None

	def delta(now, then, unit=""):
		if start is None:
			return None
		change = round(flt(now) - flt(then), 1)
		return {"value": change, "unit": unit, "label": _("since {0}").format(frappe.format_value(p.from_date, {"fieldtype": "Date"}))}

	out = [
		dict(key="rentable", label=_("Total rental units"), value=rentable, unit=_("units"), route="inventory",
			delta=delta(rentable, start.rentable if start else 0),
			hint=_("Own stock in the yard, at sites, inspection and repair, plus cross-hired stock in custody")),
		dict(key="on_hire", label=_("On hire"), value=on_hire, unit=_("units"), route="material-at-site",
			delta=delta(on_hire, start.on_hire if start else 0), sub=_("{0} own, {1} cross-hired").format(_n(own_site), _n(cross_site))),
		dict(key="available", label=_("Available"), value=total("available_qty"), unit=_("units"), route="inventory",
			hint=_("Rental Yard stock less open reservations")),
		dict(key="reserved", label=_("Reserved"), value=total("reserved_qty"), unit=_("units"), route="reservations"),
		dict(key="inspection", label=_("Under inspection"), value=total("inspection_qty"), unit=_("units"), route="off-hire"),
		dict(key="repair", label=_("Under repair"), value=total("repair_qty"), unit=_("units"), route="inventory"),
		dict(key="utilization", label=_("Utilization"), value=util, unit="%", route="utilization",
			delta=delta(util, round(start.utilization, 1) if start else 0, "pts")),
	]
	if frappe.has_permission("Rental Contract", "read"):
		live = frappe.db.count("Rental Contract", {"docstatus": 1, "status": ["in", ["Active", "On Hire"]]})
		started = frappe.db.count("Rental Contract", {"docstatus": 1, "start_date": ["between", [p.from_date, p.to_date]]})
		late = frappe.db.count("Rental Contract", {"docstatus": 1, "status": "On Hire", "end_date": ["<", today]})
		out += [
			dict(key="contracts", label=_("Active rental contracts"), value=live, route="contracts",
				sub=_("{0} started in this period").format(started)),
			dict(key="late", label=_("Contracts past end date"), value=late, route="contracts?tab=1", tone="bad" if late else None),
		]
	if frappe.has_permission("Rental Contract", "read"):
		unbilled = unbilled_amount()
		out.append(dict(key="unbilled", label=_("Unbilled rental"), value=unbilled.total, currency=currency, route="billing",
			sub=_("Accrued to yesterday, {0} contracts").format(unbilled.contracts)))
	if frappe.has_permission("Sales Invoice", "read"):
		o = outstanding_totals()
		out.append(dict(key="outstanding", label=_("Outstanding rental invoices"), value=o.amount, currency=currency, route="outstanding",
			sub=_("{0} invoices, {1} overdue").format(o.count, o.overdue_count), tone="bad" if o.overdue_count else None))
	out.append(dict(key="cross_hire", label=_("Active cross-hire units"), value=custody, unit=_("units"), route="supplier-position",
		delta=delta(custody, start.custody if start else 0), sub=_("{0} at customer sites").format(_n(cross_site))))
	return out


def _n(v):
	v = flt(v)
	return f"{v:,.0f}" if v == int(v) else f"{v:,.2f}"


def unbilled_amount():
	from thinknxg_rental.thinknxg_rental.report.unbilled_rental.unbilled_rental import execute

	rows = execute({"upto_date": add_days(nowdate(), -1)})[1]
	jcr = flt(frappe.db.sql("select sum(amount) from `tabJCR Billing Schedule` where status = 'Pending'")[0][0])
	return frappe._dict(total=sum(flt(r["unbilled_amount"]) for r in rows) + jcr, contracts=len(rows))


def _rental_invoice_filter(alias=""):
	a = f"{alias}." if alias else ""
	return f"(ifnull({a}nxg_rental_contract, '') != '' or ifnull({a}nxg_jcr, '') != '')"


def outstanding_totals():
	row = frappe.db.sql(
		f"""select count(*), sum(outstanding_amount),
			sum(case when due_date < %(today)s then 1 else 0 end), sum(case when due_date < %(today)s then outstanding_amount else 0 end)
		from `tabSales Invoice` where docstatus = 1 and outstanding_amount > 0 and is_return = 0 and {_rental_invoice_filter()}""",
		{"today": nowdate()},
	)[0]
	return frappe._dict(count=cint(row[0]), amount=flt(row[1]), overdue_count=cint(row[2]), overdue_amount=flt(row[3]))


# ----------------------------------------------------------------------------- work queue
def work_queue(stock, limit=40):
	"""One row per thing someone has to do, most urgent first: what, for whom, which document, how old."""
	today = getdate(nowdate())
	rows = []

	def add(kind, title, party, doctype, name, route, priority, date=None, due=None, action=None):
		age = date_diff(today, date) if date else None
		rows.append(dict(kind=kind, title=title, party=party, doctype=doctype, name=name, route=route, priority=priority,
			age=age, due=str(due) if due else None, action=action or _("Open")))

	def readable(doctype):
		return frappe.has_permission(doctype, "read")

	if readable("Rental Portal Request"):
		for r in frappe.get_list("Rental Portal Request", filters={"status": ["in", ["Open", "In Progress"]]},
			fields=["name", "request_type", "customer_name", "request_date", "status"], order_by="creation asc", limit=limit):
			waiting = date_diff(today, r.request_date)
			add("request", _("{0} ({1})").format(_(r.request_type), _(r.status)), r.customer_name, "Rental Portal Request", r.name,
				f"requests/{r.name}", "high" if r.status == "Open" and waiting >= 2 else "normal", r.request_date,
				action=_("Start") if r.status == "Open" else _("Handle"))
	if readable("Hire Delivery Order"):
		for r in frappe.get_list("Hire Delivery Order", filters={"docstatus": 0}, fields=["name", "customer_name", "posting_date", "rental_site"],
			order_by="posting_date asc", limit=limit):
			add("delivery", _("Delivery order in draft"), r.customer_name, "Hire Delivery Order", r.name, f"deliveries/{r.name}",
				"high" if getdate(r.posting_date) <= today else "normal", r.posting_date, due=r.posting_date, action=_("Submit"))
	if readable("Hire Off-Hire Note"):
		for r in frappe.get_list("Hire Off-Hire Note", filters={"docstatus": 1, "inspection_status": "Pending"},
			fields=["name", "customer_name", "return_date"], order_by="return_date asc", limit=limit):
			add("inspection", _("Returned material awaiting inspection"), r.customer_name, "Hire Off-Hire Note", r.name, f"off-hire/{r.name}",
				"high" if date_diff(today, r.return_date) >= 2 else "normal", r.return_date, action=_("Inspect"))
	if readable("Rental Damage Settlement"):
		for r in frappe.get_list("Rental Damage Settlement", filters={"docstatus": 1, "status": "To Invoice"},
			fields=["name", "customer_name", "posting_date", "grand_total"], order_by="posting_date asc", limit=limit):
			add("settlement", _("Damage settlement to invoice"), r.customer_name, "Rental Damage Settlement", r.name, f"settlements/{r.name}",
				"normal", r.posting_date, action=_("Invoice"))
	if readable("Rental Contract"):
		for r in frappe.get_list("Rental Contract", filters={"docstatus": 1, "status": ["in", ["On Hire", "Off Hired"]],
			"next_billing_date": ["<=", today], "contract_type": ["!=", "Job Type Contract"]},
			fields=["name", "customer_name", "next_billing_date"], order_by="next_billing_date asc", limit=limit):
			add("billing", _("Rental billing due"), r.customer_name, "Rental Contract", r.name, "billing", "normal",
				r.next_billing_date, due=r.next_billing_date, action=_("Bill"))
		for r in frappe.get_list("Rental Contract", filters={"docstatus": 1, "status": "On Hire", "end_date": ["<", today]},
			fields=["name", "customer_name", "end_date", "total_at_site_qty"], order_by="end_date asc", limit=limit):
			add("late", _("Past end date, {0} units still at site").format(_n(r.total_at_site_qty)), r.customer_name, "Rental Contract",
				r.name, f"contracts/{r.name}", "high", r.end_date, due=r.end_date, action=_("Extend or collect"))
	if readable("JCR Billing Schedule"):
		for r in frappe.get_list("JCR Billing Schedule", filters={"status": "Pending", "period_to": ["<", today]},
			fields=["name", "jcr", "customer", "period_to", "billing_type"], order_by="period_to asc", limit=limit):
			add("jcr", _("{0} period waiting for an invoice").format(_(r.billing_type)), r.customer, "Job Completion Report", r.jcr,
				f"jcr/{r.jcr}", "normal", r.period_to, action=_("Invoice"))
	if readable("Cross Hire Order"):
		for r in frappe.get_list("Cross Hire Order", filters={"docstatus": 1, "status": ["in", ["On Hire", "Partially Returned"]],
			"expected_return_date": ["<", today]}, fields=["name", "supplier_name", "expected_return_date"],
			order_by="expected_return_date asc", limit=limit):
			add("cross", _("Cross-hired material overdue for return"), r.supplier_name, "Cross Hire Order", r.name, f"cross-hire/{r.name}",
				"high", r.expected_return_date, due=r.expected_return_date, action=_("Return"))
	for r in stock:
		if r["rentable"] and (r["short"] or flt(r["available_qty"]) <= 0.1 * flt(r["rentable"])):
			add("short", _("Running short: {0} free of {1}").format(_n(r["available_qty"]), _n(r["rentable"])), r["item_name"], "Item",
				r["item_code"], f"inventory?item={r['item_code']}", "high" if r["short"] else "normal", action=_("Review"))
	rank = {"high": 0, "normal": 1}
	rows.sort(key=lambda r: (rank[r["priority"]], -(r["age"] or 0)))
	return rows[:limit]


# ----------------------------------------------------------------------------- charts
def charts(p, stock, position):
	today = getdate(nowdate())
	unit, bks = buckets(p.from_date, p.to_date)
	labels = [b[2] for b in bks]
	out = {"unit": unit, "labels": labels}

	# utilization and own vs cross-hired at site, at the end of each bucket (future buckets left empty)
	util, own, cross = [], [], []
	for b_start, b_end, _label in bks:
		if b_start > today:
			util.append(None), own.append(None), cross.append(None)
			continue
		pos = position(min(b_end, today))
		util.append(round(pos.utilization, 1))
		own.append(pos.site_own)
		cross.append(pos.site_cross)
	out["utilization"] = util
	out["at_site"] = {"own": own, "cross": cross}

	def bucket_of(d):
		d = getdate(d)
		for i, (s, e, _l) in enumerate(bks):
			if s <= d <= e:
				return i
		return None

	def by_bucket(rows):
		values = [0.0] * len(bks)
		for d, amount in rows:
			i = bucket_of(d)
			if i is not None:
				values[i] += flt(amount)
		return [round(v, 3) for v in values]

	rng = {"from": p.from_date, "to": p.to_date}
	if frappe.has_permission("Sales Invoice", "read"):
		out["revenue"] = by_bucket(frappe.db.sql(
			f"""select posting_date, base_net_total from `tabSales Invoice`
			where docstatus = 1 and posting_date between %(from)s and %(to)s and {_rental_invoice_filter()}""", rng))
		out["customers"] = [dict(label=r[0] or r[1], key=r[1], value=flt(r[2])) for r in frappe.db.sql(
			f"""select max(customer_name), customer, sum(base_net_total) as total from `tabSales Invoice`
			where docstatus = 1 and posting_date between %(from)s and %(to)s and {_rental_invoice_filter()}
			group by customer order by total desc limit 8""", rng)]
	if frappe.has_permission("Rental Billing Schedule", "read"):
		billed = frappe.db.sql("""select to_date, total_amount from `tabRental Billing Schedule`
			where docstatus = 1 and to_date between %(from)s and %(to)s""", rng)
		billed += frappe.db.sql("""select period_to, amount from `tabJCR Billing Schedule`
			where status in ('Pending', 'Invoiced') and period_to between %(from)s and %(to)s""", rng)
		out["billing"] = by_bucket(billed)
	if frappe.has_permission("Purchase Invoice", "read"):
		out["cross_hire_cost"] = by_bucket(frappe.db.sql(
			"""select posting_date, base_net_total from `tabPurchase Invoice`
			where docstatus = 1 and ifnull(nxg_cross_hire_order, '') != '' and posting_date between %(from)s and %(to)s""", rng))

	# availability by category, as the yard tube: own at sites, cross-hired at sites, reserved, workshop, free
	cats = {}
	for r in stock:
		c = cats.setdefault(r.get("category") or _("Other"), dict(own=0, cross=0, reserved=0, workshop=0, free=0))
		c["own"] += flt(r["at_site_own"])
		c["cross"] += flt(r["at_site_cross_hire"])
		c["reserved"] += min(flt(r["reserved_qty"]), max(flt(r["yard_qty"]), 0))
		c["workshop"] += flt(r["workshop_qty"])
		c["free"] += max(flt(r["available_qty"]), 0)
	out["categories"] = [dict(label=k, **v) for k, v in sorted(cats.items(), key=lambda kv: -sum(kv[1].values()))]
	top = sorted(stock, key=lambda r: -(flt(r["at_site_own"]) + flt(r["at_site_cross_hire"])))[:8]
	out["top_items"] = [dict(label=r["item_name"], key=r["item_code"], own=flt(r["at_site_own"]), cross=flt(r["at_site_cross_hire"]),
		utilization=round(flt(r["utilization"]), 1)) for r in top if flt(r["at_site_own"]) + flt(r["at_site_cross_hire"]) > 0]
	out["profitability"] = profitability(p)
	return out


def profitability(p, limit=8):
	if not (frappe.db.exists("Report", "Hire Contract Profitability") and frappe.has_permission("Sales Invoice", "read")):
		return None
	from thinknxg_rental.thinknxg_rental.report.hire_contract_profitability.hire_contract_profitability import execute

	rows = execute({"from_date": p.from_date, "to_date": p.to_date})[1]
	rows = sorted(rows, key=lambda r: -abs(flt(r.get("gross_contribution"))))[:limit]
	return [dict(label=r.get("rental_contract") or r.get("name"), customer=r.get("customer_name"),
		revenue=flt(r.get("rental_revenue")) + flt(r.get("damage_recovery")), cost=flt(r.get("cross_hire_cost")),
		value=flt(r.get("gross_contribution")), margin=flt(r.get("margin"))) for r in rows]


# ----------------------------------------------------------------------------- today
def today_and_recent():
	today = nowdate()
	out = {"deliveries": [], "returns": [], "recent": {}}
	if frappe.has_permission("Hire Delivery Order", "read"):
		out["deliveries"] = [dict(r, route=f"deliveries/{r.name}") for r in frappe.get_list("Hire Delivery Order",
			filters={"docstatus": ["<", 2], "posting_date": today},
			fields=["name", "customer_name", "rental_site", "vehicle_no", "total_qty", "docstatus"], order_by="creation asc", limit=50)]
	returns = []
	if frappe.has_permission("Hire Off-Hire Note", "read"):
		returns += [dict(r, kind=_("Off-hire note"), route=f"off-hire/{r.name}", qty=r.total_returned_qty) for r in frappe.get_list(
			"Hire Off-Hire Note", filters={"docstatus": ["<", 2], "return_date": today},
			fields=["name", "customer_name", "rental_site", "vehicle_no", "total_returned_qty", "docstatus"], order_by="creation asc", limit=50)]
	if frappe.has_permission("Rental Portal Request", "read"):
		returns += [dict(r, kind=_("Collection requested"), route=f"requests/{r.name}", docstatus=0) for r in frappe.get_list(
			"Rental Portal Request", filters={"request_type": "Off-Hire Request", "status": ["in", ["Open", "In Progress"]], "required_date": today},
			fields=["name", "customer_name", "rental_site"], limit=50)]
	if frappe.has_permission("Rental Contract", "read"):
		returns += [dict(r, kind=_("Contract ends today"), route=f"contracts/{r.name}", qty=r.total_at_site_qty, docstatus=1) for r in frappe.get_list(
			"Rental Contract", filters={"docstatus": 1, "status": "On Hire", "end_date": today},
			fields=["name", "customer_name", "rental_site", "total_at_site_qty"], limit=50)]
	out["returns"] = returns
	for key, doctype, route, fields in (
		("hire_orders", "Hire Order", "hire-orders", ["customer_name", "order_date", "estimated_amount"]),
		("contracts", "Rental Contract", "contracts", ["customer_name", "start_date", "total_at_site_qty"]),
		("deliveries", "Hire Delivery Order", "deliveries", ["customer_name", "posting_date", "total_qty"]),
		("off_hire", "Hire Off-Hire Note", "off-hire", ["customer_name", "return_date", "total_returned_qty"]),
	):
		if not frappe.has_permission(doctype, "read"):
			continue
		rows = frappe.get_list(doctype, filters={"docstatus": ["<", 2]}, fields=["name", "docstatus", "status", "modified", *fields],
			order_by="modified desc", limit=6)
		out["recent"][key] = [dict(r, route=f"{route}/{r.name}") for r in rows]
	return out


def company_currency():
	company = frappe.db.get_single_value("Rental Settings", "company") or frappe.defaults.get_user_default("Company")
	return frappe.get_cached_value("Company", company, "default_currency") if company else None


# ----------------------------------------------------------------------------- entry point
def get_dashboard(period="month", from_date=None, to_date=None):
	p = resolve_period(period, from_date, to_date)
	key = f"thinknxg_rental:cc_dashboard:{frappe.session.user}:{p.from_date}:{p.to_date}"
	cached = frappe.cache.get_value(key)
	if cached:
		return cached
	currency = company_currency()
	stock = _stock()
	position = position_history()
	data = frappe._dict(
		period=dict(p, from_date=str(p.from_date), to_date=str(p.to_date), prev_from=str(p.prev_from), prev_to=str(p.prev_to)),
		currency=currency,
		kpis=kpis(p, stock, position, currency),
		queue=work_queue(stock),
		charts=charts(p, stock, position),
		today=today_and_recent(),
		generated=frappe.utils.now(),
	)
	data = frappe.parse_json(frappe.as_json(data))
	frappe.cache.set_value(key, data, expires_in_sec=CACHE_SECONDS)
	return data
