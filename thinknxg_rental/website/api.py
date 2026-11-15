"""Public rental website API (guests allowed). Every figure is worked out on the server; nothing the
browser sends about prices or stock is used. Submissions are rate limited per IP, carry a honeypot field
and are validated field by field."""
import re

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, flt, getdate, nowdate, validate_email_address

from thinknxg_rental.website import catalogue as cat

MAX_LINES = 40
MAX_QTY = 100000
ENQUIRY_TYPES = ("Rental Hire", "Long-term Contract", "Project Rental", "Purchase", "General Enquiry", "Business Account")


def _enabled():
	if not cint(cat.settings().enabled):
		raise frappe.PermissionError(_("The rental website is not available."))


def _published(item_code):
	p = frappe.db.get_value("Rental Item Profile", item_code, ["show_on_website", "disabled", "available_for_purchase"], as_dict=True)
	if not p or not p.show_on_website or p.disabled or frappe.db.get_value("Item", item_code, "disabled"):
		frappe.throw(_("This item is not available on the website"), frappe.DoesNotExistError)
	return p


def _dates(required_from, expected_return, required=False):
	if not (required_from and expected_return):
		if required:
			frappe.throw(_("Choose the rental start and expected return dates"))
		return None, None
	start, end = getdate(required_from), getdate(expected_return)
	if start < getdate(nowdate()):
		frappe.throw(_("The rental start cannot be in the past"))
	if end < start:
		frappe.throw(_("The expected return date cannot be before the rental start"))
	if (end - start).days > 3660:
		frappe.throw(_("Choose a rental period of up to ten years"))
	return start, end


@frappe.whitelist(allow_guest=True)
def estimate(item_code: str, qty: float = 1, required_from: str | None = None, expected_return: str | None = None):
	"""Rental days, rate and estimate (when rates are shown) and the availability band for one product."""
	_enabled()
	_published(item_code)
	qty = flt(qty)
	if qty <= 0 or qty > MAX_QTY:
		frappe.throw(_("Enter a quantity between 1 and {0}").format(MAX_QTY))
	start, end = _dates(required_from, expected_return)
	s = cat.settings()
	out = {"qty": qty, "currency": cat.currency()}
	if start:
		e = cat.estimate(item_code, qty, start, end, cat.rate_customer())
		out.update(days=e.days, chargeable_days=e.chargeable_days, minimum_hire_days=e.minimum_hire_days)
		if cint(s.show_prices):
			out.update(rate_basis=e.rate_basis, rate=e.rate, amount=e.amount)
	if cint(s.show_availability):
		out["availability"] = cat.availability_band(cat.free_stock([item_code]).get(item_code, 0), qty)
	return out


@frappe.whitelist(allow_guest=True)
def basket(items: str | list, required_from: str | None = None, expected_return: str | None = None):
	"""The basket as the server sees it: each line's current name, image, link, availability and estimate."""
	_enabled()
	items = frappe.parse_json(items) if isinstance(items, str) else items or []
	codes = []
	for line in items[:MAX_LINES]:
		code = (line or {}).get("item_code")
		if code and code not in codes:
			codes.append(code)
	cards = {r.item_code: r for r in cat.decorate(frappe.db.sql(f"select {cat.CARD_FIELDS} {cat._product_query(items=codes)[0]}",
		{"items": tuple(codes) or ("",)}, as_dict=True))} if codes else {}
	start, end = _dates(required_from, expected_return)
	s = cat.settings()
	free = cat.free_stock(list(cards)) if cint(s.show_availability) else {}
	customer = cat.rate_customer()
	lines, total = [], 0
	for line in items[:MAX_LINES]:
		c = cards.get((line or {}).get("item_code"))
		if not c:
			continue
		qty = min(max(flt(line.get("qty")) or 1, 0), MAX_QTY)
		kind = "Purchase" if line.get("line_type") == "Purchase" and c.available_for_purchase and cint(s.allow_purchase_enquiries) else "Hire"
		row = {"item_code": c.item_code, "item_name": c.item_name, "image": c.image, "url": c.url, "uom": c.uom, "qty": qty, "line_type": kind,
			"category": c.category, "minimum_hire_days": cint(c.minimum_hire_days), "purchasable": bool(c.available_for_purchase and cint(s.allow_purchase_enquiries))}
		if cint(s.show_availability):
			row["availability"] = cat.availability_band(free.get(c.item_code, 0), qty)
		if start and kind == "Hire":
			e = cat.estimate(c.item_code, qty, start, end, customer)
			row.update(chargeable_days=e.chargeable_days)
			if cint(s.show_prices):
				row.update(rate=e.rate, rate_basis=e.rate_basis, amount=e.amount)
				total += flt(e.amount)
		lines.append(row)
	return {"lines": lines, "total": total if cint(s.show_prices) and start else None, "currency": cat.currency(),
		"days": (end - start).days + 1 if start else None, "show_prices": cint(s.show_prices)}


def _clean(value, length):
	value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value or "")).strip()
	return value[:length]


def _contact(d):
	full_name, email = _clean(d.get("full_name"), 140), _clean(d.get("email"), 140).lower()
	if not full_name:
		frappe.throw(_("Enter your name"))
	if not email or not validate_email_address(email):
		frappe.throw(_("Enter a valid e-mail address"))
	phone = _clean(d.get("phone"), 40)
	if phone and not re.fullmatch(r"[0-9+()\-. ]{5,40}", phone):
		frappe.throw(_("Enter a valid phone number"))
	return {"full_name": full_name, "email": email, "phone": phone, "company_name": _clean(d.get("company_name"), 140)}


def _spam(d):
	# a field people never see: bots fill it in
	if d.get("website") or d.get("hp"):
		return True
	return False


def _logged_in_customer():
	if frappe.session.user == "Guest":
		return None, None
	from thinknxg_rental.portal.utils import get_portal_customers, is_staff

	if is_staff():
		return None, frappe.session.user
	customers, _preview = get_portal_customers()
	return (customers[0] if len(customers) == 1 else None), frappe.session.user


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=3600)
def submit_enquiry(data: str | dict):
	"""The basket (or a single product) sent as an enquiry. Returns the enquiry reference."""
	_enabled()
	d = frappe._dict(frappe.parse_json(data) if isinstance(data, str) else data or {})
	if _spam(d):
		return {"name": None, "ok": 1}
	s = cat.settings()
	enquiry_type = d.get("enquiry_type") if d.get("enquiry_type") in ENQUIRY_TYPES else "Rental Hire"
	lines = []
	seen = set()
	for line in (d.get("items") or [])[:MAX_LINES]:
		code = (line or {}).get("item_code")
		qty = flt((line or {}).get("qty"))
		if not code:
			continue
		if qty <= 0 or qty > MAX_QTY:
			frappe.throw(_("Enter a quantity between 1 and {0} for {1}").format(MAX_QTY, code))
		p = _published(code)
		kind = "Purchase" if line.get("line_type") == "Purchase" else "Hire"
		if kind == "Purchase" and not (p.available_for_purchase and cint(s.allow_purchase_enquiries)):
			frappe.throw(_("{0} is available for hire only").format(code))
		if (code, kind) in seen:
			continue
		seen.add((code, kind))
		lines.append({"item_code": code, "qty": qty, "line_type": kind})
	if not lines and enquiry_type in ("Rental Hire", "Purchase"):
		frappe.throw(_("Add at least one item to your enquiry"))
	hire = any(line["line_type"] == "Hire" for line in lines)
	start, end = _dates(d.get("required_from"), d.get("expected_return"), required=hire)
	if lines and not hire:
		enquiry_type = "Purchase"
	customer, user = _logged_in_customer()
	doc = frappe.get_doc(dict(_contact(d), doctype="Rental Website Enquiry", enquiry_type=enquiry_type, status="New",
		subject=_clean(d.get("subject"), 140), project_location=_clean(d.get("project_location"), 140), required_from=start,
		expected_return=end, delivery_requirements=_clean(d.get("delivery_requirements"), 1000), message=_clean(d.get("message"), 4000),
		customer=customer, user=user, source_page=_clean(d.get("source_page"), 140), items=lines))
	doc.flags.ignore_permissions = True
	doc.flags.from_website = True
	doc.insert()
	return {"name": doc.name, "ok": 1, "customer": bool(customer),
		"confirmation": bool(frappe.db.exists("Email Account", {"default_outgoing": 1, "enable_outgoing": 1}))}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=3600)
def contact(data: str | dict):
	"""The contact / enquiry form: general questions, long-term contracts, project rentals, account requests."""
	_enabled()
	d = frappe._dict(frappe.parse_json(data) if isinstance(data, str) else data or {})
	if _spam(d):
		return {"name": None, "ok": 1}
	message = _clean(d.get("message"), 4000)
	if not message:
		frappe.throw(_("Write your message"))
	enquiry_type = d.get("enquiry_type") if d.get("enquiry_type") in ENQUIRY_TYPES else "General Enquiry"
	customer, user = _logged_in_customer()
	doc = frappe.get_doc(dict(_contact(d), doctype="Rental Website Enquiry", enquiry_type=enquiry_type, status="New",
		subject=_clean(d.get("subject"), 140) or _(enquiry_type), project_location=_clean(d.get("project_location"), 140),
		message=message, customer=customer, user=user, source_page=_clean(d.get("source_page"), 140)))
	doc.flags.ignore_permissions = True
	doc.flags.from_website = True
	doc.insert()
	return {"name": doc.name, "ok": 1}
