"""Command Center API (/rental/admin). Whitelisted methods the single-page application calls.

Rules every method follows:
  * check_staff() first: System Manager, Rental Manager or Rental User only.
  * Reads go through frappe.get_list / has_permission / the existing reports, so the user's own
    DocType and record permissions apply on the server, whatever the browser shows.
  * Writes go through portal/entry.py (save_entry, submit_entry, prepare_mapped, run_action), the
    DocType controllers' whitelisted methods, or standard Frappe methods. Nothing here writes data
    of its own, keeps a copy, or recalculates billing, stock or ownership.
"""
import csv
import io
import json
from urllib.parse import parse_qsl, urlparse

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from thinknxg_rental.command_center import registry as R

PAGE_SIZES = (20, 50, 100)
MAX_EXPORT = 5000


def _json(value):
	return frappe.parse_json(value) if isinstance(value, str) else (value or {})


# ----------------------------------------------------------------------------- boot
@frappe.whitelist()
def boot():
	R.check_staff()
	user = frappe.get_cached_doc("User", frappe.session.user)
	roles = [r for r in R.STAFF_ROLES if r in frappe.get_roles()]
	from thinknxg_rental.command_center.dashboard import company_currency

	return {
		"user": {"name": user.name, "full_name": user.full_name or user.name, "image": user.user_image, "roles": roles,
			"initials": "".join(w[0] for w in (user.full_name or user.name).split()[:2]).upper()},
		"nav": R.get_nav(),
		"routes": R.get_routes(),
		"quick_create": R.get_quick_create(),
		"badges": R.get_badges(),
		"currency": company_currency(),
		"company": frappe.db.get_single_value("Rental Settings", "company"),
		"today": nowdate(),
		"date_format": frappe.db.get_default("date_format") or "dd-mm-yyyy",
		"can_bill": frappe.has_permission("Rental Billing Schedule", "submit"),
		"version": frappe.get_attr("thinknxg_rental.__version__"),
	}


@frappe.whitelist()
def badges():
	R.check_staff()
	return R.get_badges()


# ----------------------------------------------------------------------------- dashboard
@frappe.whitelist()
def dashboard(period: str = "month", from_date: str | None = None, to_date: str | None = None):
	R.check_staff()
	from thinknxg_rental.command_center.dashboard import get_dashboard

	return get_dashboard(period, from_date, to_date)


# ----------------------------------------------------------------------------- lists
def _resolve(filters):
	"""'$today' in a view's fixed filters means today's date."""
	out = {}
	for k, v in (filters or {}).items():
		if isinstance(v, list):
			v = [nowdate() if x == "$today" else x for x in v]
		elif v == "$today":
			v = nowdate()
		out[k] = v
	return out


def _view(key):
	view = R.VIEWS.get(key)
	if not view or view["kind"] not in ("entry", "doctype"):
		raise frappe.DoesNotExistError(_("Unknown list"))
	if view["kind"] == "entry":
		cfg = R.entry_types()[view["entry"]]
		doctype = cfg["doctype"]
		label = cfg["plural"]
		singular = cfg["label"]
		columns = list(cfg["list_columns"]) + [c for c in view.get("columns", []) if c[0] not in {x[0] for x in cfg["list_columns"]}]
		search = cfg["search_fields"]
	else:
		doctype, label, columns, search = view["doctype"], view["label"], view["columns"], view.get("search") or []
		singular = doctype
	return frappe._dict(view=view, doctype=doctype, label=label, singular=singular, columns=columns, search=search)


@frappe.whitelist()
def list_view(view: str, search: str | None = None, tab: int | str | None = None, filters: str | dict | None = None,
		sort: str | None = None, page: int = 1, page_size: int = 20, columns: str | list | None = None):
	"""One page of a list, filtered and sorted on the server with the user's permissions."""
	R.check_staff()
	v = _view(view)
	frappe.has_permission(v.doctype, "read", throw=True)
	meta = frappe.get_meta(v.doctype)
	query = _list_query(v, meta, search, tab, filters)
	page_size = cint(page_size) if cint(page_size) in PAGE_SIZES else 20
	page = max(cint(page), 1)
	all_columns = [dict(fieldname=f, label=_(l), fieldtype=meta.get_field(f).fieldtype if meta.get_field(f) else "Data",
		options=(meta.get_field(f).options if meta.get_field(f) else "")) for f, l in v.columns if f == "name" or meta.has_field(f)]
	sort_field, sort_order = _sort(sort, meta, v)
	fields = ["name", "docstatus", "modified"] + [c["fieldname"] for c in all_columns]
	for extra in ("status", "currency", "customer", "supplier"):
		if meta.has_field(extra):
			fields.append(extra)
	rows = frappe.get_list(v.doctype, filters=query.filters, or_filters=query.or_filters, fields=list(dict.fromkeys(fields)),
		order_by=f"`tab{v.doctype}`.`{sort_field}` {sort_order}", limit_start=(page - 1) * page_size, limit=page_size)
	for r in rows:
		r["status"] = r.get("status") or ("Draft" if r.docstatus == 0 else "Submitted" if r.docstatus == 1 else "Cancelled")
	entry = v.view.get("entry")
	return {
		"view": view,
		"doctype": v.doctype,
		"label": _(v.label),
		"singular": _(v.singular),
		"description": _(meta.description) if meta.description else "",
		"entry": entry,
		"opens": "form" if entry else "desk",
		"columns": all_columns,
		"rows": frappe.parse_json(frappe.as_json(rows)),
		"total": _count(v.doctype, query),
		"page": page,
		"page_size": page_size,
		"sort": {"field": sort_field, "order": sort_order},
		"tabs": [_(t[0]) for t in v.view.get("tabs") or []],
		"tab": query.tab,
		"submittable": cint(meta.is_submittable),
		"statuses": _status_options(meta),
		"date_field": v.view.get("date_field") if (v.view.get("date_field") == "creation" or meta.has_field(v.view.get("date_field") or "")) else None,
		"party": v.view.get("party") if meta.has_field(v.view.get("party") or "") else None,
		"party_doctype": (meta.get_field(v.view["party"]).options if v.view.get("party") and meta.has_field(v.view["party"]) else None),
		"can_create": bool(entry) and frappe.has_permission(v.doctype, "create"),
		"can_export": frappe.has_permission(v.doctype, "export"),
		"desk_url": f"/app/{v.doctype.lower().replace(' ', '-')}",
	}


def _status_options(meta):
	df = meta.get_field("status")
	if df and df.fieldtype == "Select":
		return [o for o in (df.options or "").split("\n") if o]
	return []


def _sort(sort, meta, v):
	field, _sep, order = (sort or "").partition(" ")
	allowed = {"name", "modified", "creation"} | {c[0] for c in v.columns if meta.has_field(c[0])}
	if v.view.get("date_field"):
		allowed.add(v.view["date_field"])
	if field not in allowed:
		field = "modified"
	return field, "asc" if order.lower() == "asc" else "desc"


def _list_query(v, meta, search, tab, filters):
	filters_in = _json(filters)
	out = dict(_resolve(v.view.get("filters")))
	tabs = v.view.get("tabs") or []
	tab_index = None
	if tabs:
		tab_index = cint(tab) if tab not in (None, "") and 0 <= cint(tab) < len(tabs) else 0
		out.update(_resolve(tabs[tab_index][1]))
	# user filters: only plain values on known fields, so the browser cannot inject operators or fields
	for field, value in filters_in.items():
		if value in (None, "", []):
			continue
		if field == "docstatus" and str(value) in ("0", "1", "2"):
			out["docstatus"] = cint(value)
		elif field == "status" and meta.has_field("status"):
			out["status"] = str(value)
		elif field == "party" and v.view.get("party") and meta.has_field(v.view["party"]):
			out[v.view["party"]] = str(value)
		elif field in ("from_date", "to_date") and v.view.get("date_field"):
			pass
	date_field = v.view.get("date_field")
	if date_field and (filters_in.get("from_date") or filters_in.get("to_date")):
		start = getdate(filters_in.get("from_date") or "1900-01-01")
		end = getdate(filters_in.get("to_date") or "2999-12-31")
		out[date_field] = ["between", [start, end]]
	or_filters = None
	if search:
		like = f"%{search.strip()[:80]}%"
		or_filters = [["name", "like", like]] + [[f, "like", like] for f in v.search if meta.has_field(f)]
	return frappe._dict(filters=out, or_filters=or_filters, tab=tab_index)


def _count(doctype, query):
	from frappe.desk.reportview import execute
	from frappe.query_builder.functions import Count

	partial = execute(doctype, filters=query.filters, or_filters=query.or_filters, fields=[f"`tab{doctype}`.name"], order_by=None, run=0)
	return cint(frappe.qb.from_(partial).select(Count("*")).run()[0][0])


@frappe.whitelist()
def export_list(view: str, search: str | None = None, tab: int | str | None = None, filters: str | dict | None = None,
		sort: str | None = None):
	"""The list as CSV, up to 5,000 rows, for users with Export permission on the DocType."""
	R.check_staff()
	v = _view(view)
	frappe.has_permission(v.doctype, "export", throw=True)
	meta = frappe.get_meta(v.doctype)
	query = _list_query(v, meta, search, tab, filters)
	sort_field, sort_order = _sort(sort, meta, v)
	cols = [(f, l) for f, l in v.columns if meta.has_field(f)]
	rows = frappe.get_list(v.doctype, filters=query.filters, or_filters=query.or_filters,
		fields=["name"] + [f for f, _l in cols] + (["status"] if meta.has_field("status") else []),
		order_by=f"`tab{v.doctype}`.`{sort_field}` {sort_order}", limit=MAX_EXPORT)
	buf = io.StringIO()
	w = csv.writer(buf)
	w.writerow([_("ID")] + [_(l) for _f, l in cols] + ([_("Status")] if meta.has_field("status") else []))
	for r in rows:
		w.writerow([r.name] + [r.get(f) for f, _l in cols] + ([r.get("status")] if meta.has_field("status") else []))
	return {"filename": f"{v.label}.csv", "content": buf.getvalue()}


# ----------------------------------------------------------------------------- document form
@frappe.whitelist()
def form(entry: str, name: str | None = None, make: str | None = None, source: str | None = None, args: str | None = None,
		prefill: str | dict | None = None):
	"""The shared document form: the admin portal's form boot (portal/entry.py get_form_boot), plus the
	document's timeline, attachments and the actions the user may take outside the portal engine."""
	R.check_staff()
	from thinknxg_rental.portal.entry import get_entry_type, get_form_boot

	cfg = get_entry_type(entry)
	form_dict = frappe._dict(_json(prefill))
	if make and source:
		form_dict.update(make=make, source=source, args=args)
	boot = get_form_boot(entry, name, form_dict)
	boot["route"] = R.entry_route(entry)
	boot["list_label"] = _(cfg["plural"])
	if boot.get("name"):
		doc = frappe.get_doc(boot["doctype"], boot["name"])
		boot["timeline"] = timeline(doc)
		boot["attachments"] = attachments(doc)
		boot["can_cancel"] = bool(doc.docstatus == 1 and frappe.has_permission(doc.doctype, "cancel", doc=doc))
		boot["can_amend"] = bool(doc.docstatus == 2 and frappe.has_permission(doc.doctype, "amend", doc=doc))
		boot["can_attach"] = bool(frappe.has_permission(doc.doctype, "write", doc=doc) or frappe.has_permission(doc.doctype, "read", doc=doc))
		boot["can_comment"] = bool(frappe.has_permission(doc.doctype, "read", doc=doc))
		boot["modified"] = str(doc.modified)
		boot["assigned"] = assignees(doc.doctype, doc.name)
		boot["owner"] = _who(doc.owner)
		boot["creation"] = str(doc.creation)
		boot["title"] = doc.get(cfg.get("title_field")) or doc.name
	return frappe.parse_json(frappe.as_json(boot))


def timeline(doc, limit=40):
	"""Comments and changes on the document, newest first (the desk form's activity)."""
	out = []
	for c in frappe.get_all("Comment", filters={"reference_doctype": doc.doctype, "reference_name": doc.name,
		"comment_type": ["in", ["Comment", "Info", "Edit", "Workflow", "Label", "Attachment", "Attachment Removed", "Submitted", "Cancelled"]]},
		fields=["name", "comment_type", "content", "comment_email", "owner", "creation"], order_by="creation desc", limit=limit):
		out.append({"kind": "comment" if c.comment_type == "Comment" else "info", "type": c.comment_type, "by": _who(c.owner),
			"content": frappe.utils.sanitize_html(c.content or ""), "at": str(c.creation), "name": c.name})
	for v in frappe.get_all("Version", filters={"ref_doctype": doc.doctype, "docname": doc.name},
		fields=["owner", "creation", "data"], order_by="creation desc", limit=limit):
		data = frappe.parse_json(v.data or "{}")
		changed = [f"{d[0]}" for d in (data.get("changed") or [])][:6]
		if data.get("created"):
			text = _("created this")
		elif changed:
			text = _("changed {0}").format(", ".join(changed))
		else:
			continue
		out.append({"kind": "change", "by": _who(v.owner), "content": text, "at": str(v.creation)})
	out.append({"kind": "change", "by": _who(doc.owner), "content": _("created this"), "at": str(doc.creation)})
	seen, final = set(), []
	for e in sorted(out, key=lambda e: e["at"], reverse=True):
		key = (e["content"], e["at"][:16])
		if key in seen:
			continue
		seen.add(key)
		final.append(e)
	return final[:limit]


def _who(user):
	return frappe.utils.get_fullname(user) if user else ""


def attachments(doc):
	return frappe.get_all("File", filters={"attached_to_doctype": doc.doctype, "attached_to_name": doc.name},
		fields=["name", "file_name", "file_url", "file_size", "is_private", "creation"], order_by="creation desc")


@frappe.whitelist(methods=["POST"])
def add_comment(doctype: str, name: str, content: str):
	"""A comment on a document's timeline, as the desk form's comment box does."""
	R.check_staff()
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	content = (content or "").strip()
	if not content:
		frappe.throw(_("Write a comment first"))
	comment = doc.add_comment("Comment", frappe.utils.sanitize_html(frappe.utils.escape_html(content).replace("\n", "<br>")))
	return {"name": comment.name}


@frappe.whitelist(methods=["POST"])
def cancel_document(doctype: str, name: str):
	"""Cancel a submitted document. Only users with Cancel permission on it (Rental Manager, System Manager);
	the DocType's own on_cancel rules still decide whether it can be cancelled."""
	R.check_staff()
	doc = frappe.get_doc(doctype, name)
	if not frappe.has_permission(doctype, "cancel", doc=doc):
		raise frappe.PermissionError(_("You are not allowed to cancel {0}").format(name))
	doc.cancel()
	return {"name": doc.name, "docstatus": doc.docstatus}


# ----------------------------------------------------------------------------- legacy addresses
@frappe.whitelist()
def resolve_url(url: str):
	"""Translate an address the portal engine returns (/rental/admin/entry?type=...) into a Command Center route."""
	R.check_staff()
	parsed = urlparse(url)
	query = dict(parse_qsl(parsed.query))
	if parsed.path.rstrip("/") == "/rental/admin/entry" and query.get("type"):
		return _entry_to_route(query)
	return {"route": parsed.path.replace("/rental/admin", "", 1).strip("/") + (f"?{parsed.query}" if parsed.query else "")}


def _entry_to_route(query):
	route = R.entry_route(query.pop("type"))
	if query.get("name"):
		return {"route": f"{route}/{query.pop('name')}"}
	return {"route": f"{route}/new", "query": query}


# ----------------------------------------------------------------------------- search
SEARCH = [
	("Customer", ["customer_name"], "customers", None),
	("Supplier", ["supplier_name"], None, None),
	("Lead", ["lead_name", "company_name"], "sales/leads", "lead"),
	("Quotation", ["customer_name", "party_name"], "sales/quotations", "quotation"),
	("Rental Site", ["site_name", "customer_name"], "sites", "rental-site"),
	("Hire Order", ["customer_name", "rental_site"], "hire-orders", "hire-order"),
	("Hire Order Contract", ["customer_name", "rental_site"], "hire-contracts", "hire-order-contract"),
	("Rental Contract", ["customer_name", "rental_site", "source_document"], "contracts", "rental-contract"),
	("Job Completion Report", ["customer_name", "hire_order_contract"], "jcr", "jcr"),
	("Hire Delivery Order", ["customer_name", "rental_contract", "vehicle_no"], "deliveries", "delivery-order"),
	("Hire Off-Hire Note", ["customer_name", "rental_contract"], "off-hire", "off-hire-note"),
	("Rental Material Reservation", ["customer_name", "rental_contract"], "reservations", "material-reservation"),
	("Cross Hire Order", ["supplier_name", "rental_contract"], "cross-hire", "cross-hire-order"),
	("Sales Invoice", ["customer_name", "nxg_rental_contract"], "invoices", "sales-invoice"),
	("Item", ["item_name", "item_group"], "inventory", None),
]


@frappe.whitelist()
def search(q: str, limit: int = 6):
	"""Find documents by number, customer, site, item code or reference, across the rental documents
	the user may read. Each hit opens in the Command Center when it has a form there, else in the desk."""
	R.check_staff()
	q = (q or "").strip()[:80]
	if len(q) < 2:
		return []
	like = f"%{q}%"
	out = []
	for doctype, fields, route, entry in SEARCH:
		if not frappe.has_permission(doctype, "read"):
			continue
		meta = frappe.get_meta(doctype)
		fields = [f for f in fields if meta.has_field(f)]
		or_filters = [["name", "like", like]] + [[f, "like", like] for f in fields]
		rows = frappe.get_list(doctype, or_filters=or_filters, fields=["name", *fields] + (["status"] if meta.has_field("status") else []),
			order_by="modified desc", limit=cint(limit) or 6)
		for r in rows:
			title = r.get(fields[0]) if fields else ""
			if doctype == "Customer":
				target = {"route": f"customers/{r.name}"}
			elif doctype == "Item":
				target = {"route": f"inventory?item={r.name}"}
			elif route and entry:
				target = {"route": f"{route}/{r.name}"}
			else:
				target = {"url": f"/app/{doctype.lower().replace(' ', '-')}/{r.name}"}
			out.append(dict(doctype=_(doctype), name=r.name, title=title if title != r.name else "", status=r.get("status"), **target))
	return out


# ----------------------------------------------------------------------------- notifications and tasks
@frappe.whitelist()
def notifications(limit: int = 30):
	R.check_staff()
	rows = frappe.get_all("Notification Log", filters={"for_user": frappe.session.user},
		fields=["name", "subject", "document_type", "document_name", "read", "creation", "from_user", "type"],
		order_by="creation desc", limit=cint(limit) or 30)
	for r in rows:
		r.subject = frappe.utils.strip_html(r.subject or "")
		r.target = _target(r.document_type, r.document_name)
	unread = frappe.db.count("Notification Log", {"for_user": frappe.session.user, "read": 0})
	return {"rows": rows, "unread": unread}


@frappe.whitelist(methods=["POST"])
def mark_notifications_read():
	R.check_staff()
	from frappe.desk.doctype.notification_log.notification_log import mark_all_as_read

	mark_all_as_read()
	return {"ok": 1}


@frappe.whitelist()
def my_tasks(status: str = "Open"):
	"""ToDos assigned to the user (Frappe's Assign To), with the document each one is about."""
	R.check_staff()
	status = status if status in ("Open", "Closed") else "Open"
	rows = frappe.get_list("ToDo", filters={"allocated_to": frappe.session.user, "status": status},
		fields=["name", "description", "reference_type", "reference_name", "date", "priority", "status", "assigned_by", "creation"],
		order_by="date asc, creation desc", limit=100)
	for r in rows:
		r.description = frappe.utils.strip_html(r.description or "")
		r.target = _target(r.reference_type, r.reference_name)
		r.assigned_by = _who(r.assigned_by)
	return rows


@frappe.whitelist(methods=["POST"])
def close_task(name: str):
	R.check_staff()
	todo = frappe.get_doc("ToDo", name)
	if todo.allocated_to != frappe.session.user:
		raise frappe.PermissionError(_("This task is assigned to someone else"))
	todo.status = "Closed"
	todo.save()
	return {"ok": 1}


def _target(doctype, name):
	if not (doctype and name):
		return None
	for d, _f, route, entry in SEARCH:
		if d == doctype and route and entry:
			return {"route": f"{route}/{name}"}
	if doctype == "Rental Portal Request":
		return {"route": f"requests/{name}"}
	return {"url": f"/app/{doctype.lower().replace(' ', '-')}/{name}"}


# ----------------------------------------------------------------------------- boards
@frappe.whitelist()
def inventory(category: str | None = None, item: str | None = None, warehouse: str | None = None):
	"""The yard: every rentable item and where it is (the Rental Stock Position report), with the
	movement history of one item when it is selected."""
	R.check_staff()
	frappe.has_permission("Rental Item Profile", "read", throw=True)
	from thinknxg_rental.portal.admin import get_stock_rows

	rows = get_stock_rows({"category": category} if category else {})
	if item:
		rows = [r for r in rows if r["item_code"] == item] or rows
	categories = sorted({r.get("category") for r in get_stock_rows() if r.get("category")})
	out = {"rows": frappe.parse_json(frappe.as_json(rows)), "categories": categories, "movements": None, "warehouses": None}
	if item:
		out["movements"] = item_movements(item, warehouse)
		out["warehouses"] = item_warehouses(item)
		from thinknxg_rental.services.item_rental import is_unit_tracked, units

		# Stock + Asset: every unit (Serial No) and where it is
		out["units"] = units(item) if is_unit_tracked(item) and frappe.has_permission("Serial No", "read") else None
	return out


@frappe.whitelist()
def unit_history(item: str, serial_no: str):
	"""One unit of a Stock + Asset item: its movements and its return inspections."""
	R.check_staff()
	frappe.has_permission("Serial No", "read", doc=serial_no, throw=True)
	from thinknxg_rental.services.item_rental import unit_history as history

	h = history(item, serial_no)
	for m in h["moves"]:
		m.target = _target(m.source_doctype, m.source_name)
	for g in h["inspections"]:
		g["target"] = {"url": f"/app/rental-return-inspection/{g['inspection']}"}
	return frappe.parse_json(frappe.as_json(h))


def item_warehouses(item):
	if not frappe.has_permission("Warehouse", "read"):
		return []
	return frappe.get_all("Bin", filters={"item_code": item, "actual_qty": ["!=", 0]}, fields=["warehouse", "actual_qty", "reserved_qty"],
		order_by="actual_qty desc")


def item_movements(item, warehouse=None, limit=60):
	"""Stock movements of one item (the Stock Ledger), newest first, with the rental document behind each."""
	if not frappe.has_permission("Stock Ledger Entry", "read") and not frappe.has_permission("Rental Ownership Ledger", "read"):
		return []
	filters = {"item_code": item, "is_cancelled": 0}
	if warehouse:
		filters["warehouse"] = warehouse
	rows = frappe.get_all("Stock Ledger Entry", filters=filters,
		fields=["posting_date", "warehouse", "actual_qty", "qty_after_transaction", "voucher_type", "voucher_no"],
		order_by="posting_date desc, creation desc", limit=limit)
	vouchers = [r.voucher_no for r in rows if r.voucher_type == "Stock Entry"]
	origin = {}
	if vouchers:
		for se in frappe.get_all("Stock Entry", filters={"name": ["in", vouchers]}, fields=["name", "nxg_hire_voucher_type", "nxg_hire_voucher_no"]):
			origin[se.name] = (se.nxg_hire_voucher_type, se.nxg_hire_voucher_no)
	for r in rows:
		src = origin.get(r.voucher_no)
		r.source_doctype, r.source_name = src if src and src[1] else (r.voucher_type, r.voucher_no)
		r.target = _target(r.source_doctype, r.source_name)
	return rows


@frappe.whitelist()
def material_at_site(search: str | None = None, ownership: str | None = None):
	R.check_staff()
	frappe.has_permission("Rental Contract", "read", throw=True)
	from thinknxg_rental.portal.admin import get_site_groups

	groups, totals = get_site_groups(search, ownership)
	return frappe.parse_json(frappe.as_json({"groups": groups, "totals": totals}))


@frappe.whitelist()
def supplier_position():
	R.check_staff()
	frappe.has_permission("Cross Hire Order", "read", throw=True)
	from thinknxg_rental.portal.admin import get_cross_hire

	groups, totals = get_cross_hire()
	suppliers = {}
	for g in groups:
		s = suppliers.setdefault(g.supplier, frappe._dict(supplier=g.supplier, orders=0, on_hire=0, at_site=0, idle=0, overdue=0, billed=0))
		s.orders += 1
		s.on_hire += flt(g.on_hire)
		s.at_site += sum(flt(r.at_site_qty) for r in g.rows)
		s.idle += sum(flt(r.in_yard_qty) for r in g.rows if flt(r.on_hire_qty) > 0)
		s.overdue += 1 if g.overdue_days > 0 else 0
		s.billed += flt(g.billed)
	for g in groups:
		g.route = f"cross-hire/{g.order}"
	return frappe.parse_json(frappe.as_json({"groups": groups, "totals": totals, "suppliers": sorted(suppliers.values(), key=lambda s: -s.on_hire)}))


@frappe.whitelist()
def billing_center(search: str | None = None):
	"""Accrued unbilled rental per contract (the Unbilled Rental report), billing due, open JCR periods
	and unpaid rental invoices. Billing itself runs services.billing.generate_billing, unchanged."""
	R.check_staff()
	frappe.has_permission("Rental Contract", "read", throw=True)
	from thinknxg_rental.portal.admin import get_billing

	b = get_billing(search)
	jcr = []
	if frappe.has_permission("JCR Billing Schedule", "read"):
		jcr = frappe.get_list("JCR Billing Schedule", filters={"status": "Pending"},
			fields=["name", "jcr", "customer", "billing_type", "period_from", "period_to", "amount", "sales_invoice"],
			order_by="period_to asc", limit=200)
		for r in jcr:
			r.route = f"jcr/{r.jcr}"
	billed_this_month = 0
	if frappe.has_permission("Sales Invoice", "read"):
		from frappe.utils import get_first_day

		billed_this_month = flt(frappe.db.sql(
			"""select sum(base_net_total) from `tabSales Invoice` where docstatus = 1 and posting_date >= %s
			and (ifnull(nxg_rental_billing_schedule, '') != '' or ifnull(nxg_jcr_billing_schedule, '') != '')""",
			get_first_day(nowdate()))[0][0])
	recoveries = 0
	if frappe.has_permission("Rental Damage Settlement", "read"):
		recoveries = flt(frappe.db.sql("select sum(grand_total) from `tabRental Damage Settlement` where docstatus = 1")[0][0])
	b.jcr_pending = jcr
	b.jcr_pending_total = sum(flt(r.amount) for r in jcr)
	b.billed_this_month = billed_this_month
	b.recoveries = recoveries
	b.can_bill = frappe.has_permission("Rental Billing Schedule", "submit")
	return frappe.parse_json(frappe.as_json(b))


@frappe.whitelist(methods=["POST"])
def bill_contract(rental_contract: str, only_complete: int = 1):
	"""Bill now: services.billing.generate_billing, exactly as the nightly job and the desk button do."""
	R.check_staff()
	if not frappe.has_permission("Rental Billing Schedule", "submit"):
		raise frappe.PermissionError(_("You are not allowed to bill rental contracts"))
	from thinknxg_rental.services.billing import generate_billing

	made = generate_billing(rental_contract, only_complete=cint(only_complete))
	return {"schedules": made}


@frappe.whitelist()
def outstanding():
	"""Unpaid rental invoices, by customer, aged."""
	R.check_staff()
	frappe.has_permission("Sales Invoice", "read", throw=True)
	from thinknxg_rental.command_center.dashboard import _rental_invoice_filter

	today = getdate(nowdate())
	invoices = frappe.get_list("Sales Invoice", filters={"docstatus": 1, "outstanding_amount": [">", 0], "is_return": 0},
		or_filters=[["nxg_rental_contract", "is", "set"], ["nxg_jcr", "is", "set"], ["nxg_rental_damage_settlement", "is", "set"]],
		fields=["name", "customer", "customer_name", "posting_date", "due_date", "grand_total", "outstanding_amount", "nxg_rental_contract", "nxg_jcr"],
		order_by="due_date asc", limit=1000)
	buckets = [("current", _("Not due")), ("d30", _("1-30 days")), ("d60", _("31-60 days")), ("d90", _("61-90 days")), ("d90p", _("Over 90 days"))]
	customers = {}
	for i in invoices:
		late = (today - getdate(i.due_date)).days if i.due_date else 0
		i.days_late = late
		key = "current" if late <= 0 else "d30" if late <= 30 else "d60" if late <= 60 else "d90" if late <= 90 else "d90p"
		i.bucket = key
		c = customers.setdefault(i.customer, frappe._dict(customer=i.customer, customer_name=i.customer_name, total=0, count=0,
			**{b: 0 for b, _l in buckets}))
		c.total += flt(i.outstanding_amount)
		c.count += 1
		c[key] += flt(i.outstanding_amount)
		i.route = f"invoices/{i.name}"
	totals = {b: sum(flt(c[b]) for c in customers.values()) for b, _l in buckets}
	totals["total"] = sum(totals.values())
	return frappe.parse_json(frappe.as_json({"buckets": [{"key": k, "label": l} for k, l in buckets], "customers": sorted(customers.values(), key=lambda c: -c.total),
		"invoices": invoices, "totals": totals, "can_pay": frappe.has_permission("Payment Entry", "create")}))


@frappe.whitelist()
def requests(view: str = "open", search: str | None = None, request_type: str | None = None):
	R.check_staff()
	frappe.has_permission("Rental Portal Request", "read", throw=True)
	from thinknxg_rental.portal.admin import get_admin_requests

	view, rows = get_admin_requests(view, search, request_type)
	assigned = {}
	if rows:
		for t in frappe.get_all("ToDo", filters={"reference_type": "Rental Portal Request", "reference_name": ["in", [r.name for r in rows]],
			"status": "Open"}, fields=["reference_name", "allocated_to"]):
			assigned.setdefault(t.reference_name, []).append(_who(t.allocated_to))
	for r in rows:
		r.assigned = assigned.get(r.name, [])
		r.route = f"requests/{r.name}"
	counts = {s: frappe.db.count("Rental Portal Request", {"status": s}) for s in ("Open", "In Progress")}
	return frappe.parse_json(frappe.as_json({"view": view, "rows": rows, "counts": counts,
		"types": ["Hire Enquiry", "Off-Hire Request", "Extension Request"]}))


@frappe.whitelist(methods=["POST"])
def assign(doctype: str, name: str, user: str | None = None):
	"""Assign a document (a customer request, a delivery...) to a member of the rental staff with
	Frappe's Assign To, yourself by default. The assignee sees it under My Tasks."""
	R.check_staff()
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("write" if doc.docstatus == 0 else "read")
	user = user or frappe.session.user
	if not R.is_staff(user):
		frappe.throw(_("{0} is not rental staff").format(user))
	from frappe.desk.form.assign_to import add

	if frappe.db.exists("ToDo", {"reference_type": doctype, "reference_name": name, "allocated_to": user, "status": "Open"}):
		return {"ok": 1}
	add({"assign_to": [user], "doctype": doctype, "name": name, "description": _("{0} {1}").format(_(doctype), name)})
	return {"ok": 1, "assigned": assignees(doctype, name)}


def assignees(doctype, name):
	return [{"user": t.allocated_to, "name": _who(t.allocated_to)} for t in frappe.get_all("ToDo",
		filters={"reference_type": doctype, "reference_name": name, "status": "Open"}, fields=["allocated_to"])]


@frappe.whitelist()
def staff_users():
	R.check_staff()
	users = frappe.get_all("Has Role", filters={"role": ["in", list(R.STAFF_ROLES)], "parenttype": "User"}, pluck="parent", distinct=True)
	return [{"value": u, "label": _who(u)} for u in users if u not in ("Administrator", "Guest") and frappe.db.get_value("User", u, "enabled")]


@frappe.whitelist()
def customer_overview(customer: str):
	"""One customer: sites, contracts, material at site and unpaid invoices."""
	R.check_staff()
	doc = frappe.get_doc("Customer", customer)
	doc.check_permission("read")
	out = {"name": doc.name, "customer_name": doc.customer_name, "customer_group": doc.customer_group, "territory": doc.territory,
		"mobile_no": doc.get("mobile_no"), "email_id": doc.get("email_id"), "desk_url": f"/app/customer/{doc.name}"}
	if frappe.has_permission("Rental Site", "read"):
		out["sites"] = frappe.get_list("Rental Site", filters={"customer": customer}, fields=["name", "site_contact", "contact_phone", "disabled"])
	if frappe.has_permission("Rental Contract", "read"):
		out["contracts"] = frappe.get_list("Rental Contract", filters={"customer": customer, "docstatus": ["<", 2]},
			fields=["name", "rental_site", "status", "start_date", "end_date", "total_at_site_qty", "total_billed_amount"], order_by="start_date desc")
		out["at_site"] = flt(sum(flt(c.total_at_site_qty) for c in out["contracts"] if c.status in ("Active", "On Hire")))
	if frappe.has_permission("Sales Invoice", "read"):
		out["invoices"] = frappe.get_list("Sales Invoice", filters={"customer": customer, "docstatus": 1, "outstanding_amount": [">", 0]},
			fields=["name", "posting_date", "due_date", "grand_total", "outstanding_amount"], order_by="due_date asc")
		out["outstanding"] = sum(flt(i.outstanding_amount) for i in out["invoices"])
	return frappe.parse_json(frappe.as_json(out))


@frappe.whitelist()
def customers(search: str | None = None, page: int = 1, page_size: int = 20):
	R.check_staff()
	frappe.has_permission("Customer", "read", throw=True)
	page_size = cint(page_size) if cint(page_size) in PAGE_SIZES else 20
	page = max(cint(page), 1)
	or_filters = None
	if search:
		like = f"%{search.strip()[:80]}%"
		or_filters = [["name", "like", like], ["customer_name", "like", like], ["mobile_no", "like", like], ["email_id", "like", like]]
	filters = {"disabled": 0}
	rows = frappe.get_list("Customer", filters=filters, or_filters=or_filters,
		fields=["name", "customer_name", "customer_group", "territory", "mobile_no", "email_id"], order_by="customer_name asc",
		limit_start=(page - 1) * page_size, limit=page_size)
	names = [r.name for r in rows]
	if names and frappe.has_permission("Rental Contract", "read"):
		live = dict(frappe.db.sql("""select customer, count(*) from `tabRental Contract` where docstatus = 1
			and status in ('Active', 'On Hire') and customer in %(c)s group by customer""", {"c": tuple(names)}))
		site_qty = dict(frappe.db.sql("""select customer, sum(total_at_site_qty) from `tabRental Contract` where docstatus = 1
			and customer in %(c)s group by customer""", {"c": tuple(names)}))
	else:
		live, site_qty = {}, {}
	if names and frappe.has_permission("Sales Invoice", "read"):
		owed = dict(frappe.db.sql("""select customer, sum(outstanding_amount) from `tabSales Invoice` where docstatus = 1
			and outstanding_amount > 0 and customer in %(c)s group by customer""", {"c": tuple(names)}))
	else:
		owed = {}
	for r in rows:
		r.live_contracts = cint(live.get(r.name))
		r.at_site = flt(site_qty.get(r.name))
		r.outstanding = flt(owed.get(r.name))
	from frappe.desk.reportview import execute
	from frappe.query_builder.functions import Count

	partial = execute("Customer", filters=filters, or_filters=or_filters, fields=["`tabCustomer`.name"], order_by=None, run=0)
	total = cint(frappe.qb.from_(partial).select(Count("*")).run()[0][0])
	return frappe.parse_json(frappe.as_json({"rows": rows, "total": total, "page": page, "page_size": page_size,
		"can_create": frappe.has_permission("Customer", "create")}))


@frappe.whitelist()
def users_roles():
	"""Rental staff and their rental roles. System Manager only."""
	R.check_staff()
	if "System Manager" not in frappe.get_roles():
		raise frappe.PermissionError(_("Only a System Manager can see users and roles"))
	rows = {}
	for r in frappe.get_all("Has Role", filters={"role": ["in", list(R.STAFF_ROLES) + ["Customer"]], "parenttype": "User"},
		fields=["parent", "role"]):
		if r.parent in ("Administrator", "Guest"):
			continue
		rows.setdefault(r.parent, set()).add(r.role)
	users = frappe.get_all("User", filters={"name": ["in", list(rows)]}, fields=["name", "full_name", "enabled", "last_active", "user_type"]) if rows else []
	for u in users:
		u.roles = sorted(rows[u.name])
		u.desk_url = f"/app/user/{u.name}"
	return sorted(users, key=lambda u: (not u.enabled, u.full_name or u.name))


@frappe.whitelist()
def settings_summary():
	R.check_staff()
	frappe.has_permission("Rental Settings", "read", throw=True)
	doc = frappe.get_single("Rental Settings")
	meta = frappe.get_meta("Rental Settings")
	sections, current = [], None
	for df in meta.fields:
		if df.fieldtype in ("Section Break", "Tab Break"):
			current = {"label": _(df.label) if df.label else "", "fields": []}
			sections.append(current)
			continue
		if df.fieldtype in ("Column Break", "HTML", "Button") or df.hidden:
			continue
		if current is None:
			current = {"label": _("General"), "fields": []}
			sections.append(current)
		current["fields"].append({"label": _(df.label), "fieldtype": df.fieldtype, "value": doc.get(df.fieldname)})
	return {"sections": [s for s in sections if s["fields"]], "can_edit": frappe.has_permission("Rental Settings", "write"),
		"desk_url": "/app/rental-settings"}


@frappe.whitelist()
def report_meta(view: str):
	"""Which report a Reports item runs, and its filters with their defaults. The report itself runs
	through frappe.desk.query_report.run, which applies the report's own role check."""
	R.check_staff()
	name = R.REPORTS.get(view)
	if not name:
		raise frappe.DoesNotExistError(_("Unknown report"))
	report = frappe.get_doc("Report", name)
	if not report.is_permitted():
		raise frappe.PermissionError(_("You are not allowed to run {0}").format(name))
	company = frappe.db.get_single_value("Rental Settings", "company") or frappe.defaults.get_user_default("Company")
	today = getdate(nowdate())
	values = {"$company": company, "$today": str(today), "$year_start": str(today.replace(month=1, day=1))}
	filters = []
	for f in R.REPORT_FILTERS.get(name, []):
		f = dict(f, label=_(f["label"]))
		f["default"] = values.get(f["default"], f["default"])
		filters.append(f)
	return {"name": name, "label": _(name), "description": _(report.get("description") or ""), "filters": filters,
		"desk_url": f"/app/query-report/{name}"}


@frappe.whitelist()
def utilization(period: str = "year", from_date: str | None = None, to_date: str | None = None):
	"""Utilization over a period (from the same ledgers as the dashboard) and per item now."""
	R.check_staff()
	frappe.has_permission("Rental Item Profile", "read", throw=True)
	from thinknxg_rental.command_center.dashboard import _stock, buckets, position_history, resolve_period

	p = resolve_period(period, from_date, to_date)
	position = position_history()
	unit, bks = buckets(p.from_date, p.to_date)
	today = getdate(nowdate())
	points = []
	for s, e, label in bks:
		if s > today:
			points.append({"label": label, "utilization": None})
			continue
		pos = position(min(e, today))
		points.append({"label": label, "utilization": round(pos.utilization, 1), "on_hire": pos.on_hire, "rentable": pos.rentable})
	items = sorted(_stock(), key=lambda r: -flt(r["utilization"]))
	return frappe.parse_json(frappe.as_json({"unit": unit, "points": points, "items": items,
		"period": {"from_date": str(p.from_date), "to_date": str(p.to_date), "period": p.period}}))
