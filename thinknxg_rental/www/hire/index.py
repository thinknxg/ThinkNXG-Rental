"""thinkNXG Rental public website: every page under /hire (and the site home page when chosen in
Rental Website Settings). Server-rendered so search engines read it; the basket, estimates and forms
are enhanced by public/rental_website/rw.js.

    /hire                                  home (sections from Rental Website Settings)
    /hire/equipment                        catalogue
    /hire/equipment/<category>             category (an ERPNext Item Group)
    /hire/equipment/<category>/<product>   product
    /hire/services | industries | about | contact | basket | account
"""
import json

import frappe
from frappe import _
from frappe.utils import cint, get_url, strip_html

from thinknxg_rental.website import catalogue as cat
from thinknxg_rental.website import icons
from thinknxg_rental.website.theme import theme

# Every text rw.js shows, so it is translated with the page (tests check this list against rw.js)
JS_MESSAGES = (
	"We could not reach the server. Check your connection and try again.",
	"Too many requests from this connection. Try again in a little while.",
	"Something went wrong. Try again, or contact us by phone or e-mail.",
	"day", "week", "month", "Menu", "Added to your enquiry", "View", "View enquiry", "{0} rental days",
	"charged as the {0}-day minimum", "Estimate", "At {0} per {1}, before tax and delivery. Your quotation confirms the price.",
	"We quote this item on request.", "Choose your dates to see the rental period.", "Enter a quantity",
	"Choose a start date from today and a return date after it", "Your enquiry is empty",
	"Add equipment from the catalogue, or send us a message with what you need.", "Browse equipment", "Send a message",
	"{0} days, from {1} to {2}", "Choose the dates to see the rental period and estimates.", "Price in the quotation",
	"{0} days", "Rate on request", "Min. hire {0} days", "Quantity", "Hire or buy", "Hire", "Buy", "Remove", "Estimated rental",
	"Before tax, delivery and any discount", "Add at least one item to your enquiry.",
	"Choose a start date from today and a return date after it.", "Thank you. Your enquiry is with the rental team.",
	"Keep this reference. We check availability for your dates and send you a quotation.",
	"A confirmation is on its way to your e-mail.", "See it in your account", "Back to the catalogue",
	"Fill in the highlighted fields.", "Thank you. Your message is with the rental team, reference {0}. We reply by e-mail or phone.",
	"Thank you. Your message is with the rental team.", "Some items are no longer offered and were taken out of your enquiry.",
	"Log out",
)


def js_messages():
	return {m: _(m) for m in JS_MESSAGES}

no_cache = 1
sitemap = 0  # listed with every product in /rental_sitemap.xml instead
STATIC = {"services", "industries", "about", "contact", "basket", "account"}


def get_context(context):
	s = cat.settings()
	staff_preview = False
	if not cint(s.enabled):
		if not ({"System Manager", "Website Manager", "Rental Manager"} & set(frappe.get_roles())):
			raise frappe.PageDoesNotExistError
		staff_preview = True
	path = (frappe.form_dict.get("app_path") or "").strip("/")
	parts = [p for p in path.split("/") if p]
	try:
		return _dispatch(context, s, parts, staff_preview)
	except frappe.PageDoesNotExistError:
		# a missing product or page inside the website gets the website's own "not found" page, still
		# answered with HTTP 404 (see website/renderer.py)
		frappe.local.flags.rw_not_found = True
		context.rw_status = 404
		return not_found(context, s)


def _dispatch(context, s, parts, staff_preview):
	t = theme(s)
	context.update(
		no_cache=1,
		rw=s,
		rw_theme=t,
		rw_staff_preview=staff_preview,
		rw_header_links=[l for l in s.links or [] if l.location == "Header"],
		rw_footer=_footer(s),
		rw_categories=cat.category_tree(),
		rw_top_categories=cat.top_categories(),
		rw_logged_in=frappe.session.user != "Guest",
		rw_user_name=frappe.db.get_value("User", frappe.session.user, "first_name") if frappe.session.user != "Guest" else None,
		rw_currency=cat.currency(),
		rw_path="/" + "/".join(["hire"] + parts),
		rw_csrf=frappe.sessions.get_csrf_token() if frappe.session.user != "Guest" else "",
		rw_cards=_cards(s),
		rw_json=json.dumps,
		rw_version=_version(),
		rw_money=cat.money,
		rw_icons=icons.sprite(c.icon for c in s.cards or [] if c.enabled),
		rw_icon_exists=icons.exists,
		rw_whatsapp="".join(ch for ch in (s.whatsapp or "") if ch.isdigit()),
		rw_signup=not cint(frappe.get_website_settings("disable_signup")),
	)
	context.rw_boot = {"show_prices": cint(s.show_prices), "show_availability": cint(s.show_availability), "currency": cat.currency(),
		"allow_purchase": cint(s.allow_purchase_enquiries), "logged_in": context.rw_logged_in, "messages": js_messages()}
	if not parts:
		return home(context, s)
	if parts[0] == "equipment":
		if len(parts) == 1:
			return catalogue(context, s, None)
		category = cat.category_by_slug(parts[1]) if parts[1] != "all" else None
		if len(parts) == 2:
			if not category:
				raise frappe.PageDoesNotExistError
			return catalogue(context, s, category)
		if len(parts) == 3:
			return product(context, s, parts[1], parts[2])
		raise frappe.PageDoesNotExistError
	if len(parts) == 1 and parts[0] in STATIC:
		return globals()["page_" + parts[0]](context, s)
	raise frappe.PageDoesNotExistError


def _version():
	from thinknxg_rental import __version__

	return __version__


def _cards(s):
	out = {}
	for c in s.cards or []:
		if c.enabled:
			out.setdefault(c.card_group, []).append(c)
	return out


def _footer(s):
	cols = {}
	for l in s.links or []:
		if l.location.startswith("Footer"):
			cols.setdefault(l.location.split(": ", 1)[-1], []).append(l)
	return cols


def seo(context, title, description=None, image=None, canonical=None, noindex=False, json_ld=None):
	s = context.rw
	context.title = title
	context.rw_title = title if title == (s.site_name or "") else f"{title} | {s.site_name or 'thinkNXG Rental'}"
	context.rw_description = (strip_html(description or "") or s.meta_description or s.tagline or "").strip()[:300]
	context.rw_og_image = get_url(image or s.og_image or s.logo or "/assets/thinknxg_rental/images/logo.svg")
	context.rw_canonical = get_url(canonical or context.rw_path)
	context.rw_noindex = noindex
	context.rw_json_ld = json_ld or []
	context.metatags = {}  # our own head tags; Frappe's are not used on these pages


def breadcrumb_ld(crumbs):
	return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
		{"@type": "ListItem", "position": i + 1, "name": name, "item": get_url(link)} for i, (name, link) in enumerate(crumbs)]}


# ----------------------------------------------------------------------------- pages
def home(context, s):
	context.rw_page = "templates/rental_website/pages/home.html"
	sections = []
	for sec in s.sections or []:
		if not sec.enabled:
			continue
		row = frappe._dict(sec.as_dict())
		if sec.section_type == "Featured Products":
			row.products, _t = cat.products(featured=1, page_length=cint(sec.limit) or 8)
			if not row.products:
				row.products, _t = cat.products(page_length=cint(sec.limit) or 8)
		elif sec.section_type == "Category Products":
			category = cat.category_of(sec.item_group) if sec.item_group else None
			if not category:
				continue
			row.category = category
			row.products, _t = cat.products(category=category, page_length=cint(sec.limit) or 4)
		elif sec.section_type in ("Services", "Industries", "Process", "Advantages", "Testimonials", "Statistics"):
			group = {"Services": "Service", "Industries": "Industry", "Process": "Process Step", "Advantages": "Advantage",
				"Testimonials": "Testimonial", "Statistics": "Statistic"}[sec.section_type]
			row.cards = context.rw_cards.get(group, [])
		elif sec.section_type == "Categories":
			row.categories = context.rw_top_categories or context.rw_categories
		if sec.section_type in ("Featured Products", "Category Products", "Services", "Industries", "Process", "Advantages",
				"Testimonials", "Statistics", "Categories") and not (row.products or row.cards or row.categories):
			continue  # nothing real to show: the section stays hidden
		sections.append(row)
	context.rw_sections = sections
	org = {"@context": "https://schema.org", "@type": "Organization", "name": s.organization_name or s.site_name or "thinkNXG Rental",
		"url": get_url("/hire"), "logo": get_url(s.logo or "/assets/thinknxg_rental/images/logo.svg")}
	if s.contact_phone:
		org["telephone"] = s.contact_phone
	if s.contact_email:
		org["email"] = s.contact_email
	hero = next((x for x in sections if x.section_type == "Hero"), None)
	seo(context, s.meta_title or s.site_name or "thinkNXG Rental", s.meta_description or (hero.subtitle if hero else None),
		image=hero.image if hero and hero.image else None, canonical="/hire", json_ld=[org])


def catalogue(context, s, category):
	f = frappe.form_dict
	sort = f.get("sort") if f.get("sort") in cat.SORTS else "featured"
	view = f.get("view") if f.get("view") in ("grid", "list") else ("list" if context.rw_theme["catalogue_view"] == "List" else "grid")
	page = max(cint(f.get("page")), 1)
	search = (f.get("q") or "").strip()[:80]
	system = f.get("system") or None
	rows, total = cat.products(category=category, search=search or None, system=system, purchasable=cint(f.get("purchase")) or None,
		in_stock=cint(f.get("in_stock")) or None, sort=sort, page=page, page_length=cat.PAGE_LENGTH)
	pages = max((total + cat.PAGE_LENGTH - 1) // cat.PAGE_LENGTH, 1)
	if page > pages and total:
		raise frappe.PageDoesNotExistError
	systems = [r[0] for r in frappe.db.sql("""select distinct p.category from `tabRental Item Profile` p
		where p.show_on_website = 1 and p.disabled = 0 and ifnull(p.category, '') != '' order by p.category""")]
	context.update(rw_page="templates/rental_website/pages/catalogue.html", rw_category=category, rw_products=rows, rw_total=total,
		rw_page_no=page, rw_pages=pages, rw_sort=sort, rw_view=view, rw_search=search, rw_system=system, rw_systems=systems,
		rw_filters={"in_stock": cint(f.get("in_stock")), "purchase": cint(f.get("purchase"))},
		rw_children=[c for c in context.rw_categories if category and c.parent == category.name])
	base = category.url if category else cat.url("equipment")
	query = {k: v for k, v in {"q": search, "system": system, "sort": sort if sort != "featured" else None, "view": f.get("view"),
		"in_stock": f.get("in_stock"), "purchase": f.get("purchase")}.items() if v}
	context.rw_base_url = base
	context.rw_query = query
	title = category.title if category else _("Equipment catalogue")
	if search:
		title = _("Search results for “{0}”").format(search)
	crumbs = [(_("Home"), "/hire"), (_("Equipment"), cat.url("equipment"))] + ([(category.title, category.url)] if category else [])
	context.rw_crumbs = crumbs
	desc = (category.description if category and category.description else
		_("Browse {0} for rent: specifications, rental rates and availability.").format(category.title if category else _("formwork, scaffolding and construction equipment")))
	canonical = base + (f"?page={page}" if page > 1 else "")
	seo(context, title, desc, image=category.image if category else None, canonical=canonical,
		noindex=bool(search or system or f.get("in_stock") or f.get("purchase") or f.get("sort") or f.get("view")),
		json_ld=[breadcrumb_ld(crumbs)])


def product(context, s, category_slug, slug):
	p = cat.product_by_slug(slug)
	if not p:
		raise frappe.PageDoesNotExistError
	if p.category_slug != category_slug:
		frappe.local.flags.redirect_location = p.url
		raise frappe.Redirect(301)  # one address per product
	crumbs = [(_("Home"), "/hire"), (_("Equipment"), cat.url("equipment"))]
	category = cat.category_by_slug(p.category_slug)
	if category:
		crumbs.append((category.title, category.url))
	crumbs.append((p.item_name, p.url))
	context.update(rw_page="templates/rental_website/pages/product.html", rw_product=p, rw_crumbs=crumbs)
	ld = {"@context": "https://schema.org", "@type": "Product", "name": p.item_name, "sku": p.item_code, "category": p.category,
		"description": strip_html(p.summary or p.description or "")[:500], "url": get_url(p.url),
		"image": [get_url(i["src"]) for i in p.images] or None, "brand": {"@type": "Brand", "name": s.organization_name or s.site_name or "thinkNXG Rental"}}
	if cint(s.show_prices) and p.rate:
		ld["offers"] = {"@type": "Offer", "priceCurrency": context.rw_currency, "price": p.rate, "url": get_url(p.url),
			"availability": "https://schema.org/InStock" if (p.availability or {}).get("code") in ("available", "limited") else "https://schema.org/PreOrder",
			"priceSpecification": {"@type": "UnitPriceSpecification", "price": p.rate, "priceCurrency": context.rw_currency,
				"unitText": {"Daily": "DAY", "Weekly": "WEEK", "Monthly": "MONTH"}.get(p.rate_basis, "MONTH")}}
	seo(context, p.item_name, p.summary or p.description or _("{0} for rent").format(p.item_name),
		image=p.images[0]["src"] if p.images else None, canonical=p.url, json_ld=[{k: v for k, v in ld.items() if v}, breadcrumb_ld(crumbs)])


def page_services(context, s):
	context.update(rw_page="templates/rental_website/pages/services.html", rw_crumbs=[(_("Home"), "/hire"), (_("Services"), "/hire/services")])
	seo(context, _("Rental services"), _("Formwork, scaffolding and construction equipment rental, long-term and project rental, supply and contract management."))


def page_industries(context, s):
	context.update(rw_page="templates/rental_website/pages/industries.html", rw_crumbs=[(_("Home"), "/hire"), (_("Industries"), "/hire/industries")])
	seo(context, _("Industries we serve"), _("Formwork and scaffolding rental for residential, commercial, infrastructure and industrial construction."))


def page_about(context, s):
	context.update(rw_page="templates/rental_website/pages/about.html", rw_crumbs=[(_("Home"), "/hire"), (_("About"), "/hire/about")])
	seo(context, _("About us"), s.about_intro, image=s.about_image)


def page_contact(context, s):
	context.update(rw_page="templates/rental_website/pages/contact.html", rw_crumbs=[(_("Home"), "/hire"), (_("Contact"), "/hire/contact")],
		rw_enquiry_type=frappe.form_dict.get("type") or "General Enquiry", rw_prefill=_prefill())
	seo(context, _("Contact us"), _("Ask about equipment, long-term contracts or project rental. Our rental team will reply."))


def page_basket(context, s):
	context.update(rw_page="templates/rental_website/pages/basket.html", rw_crumbs=[(_("Home"), "/hire"), (_("Your enquiry"), "/hire/basket")],
		rw_prefill=_prefill())
	seo(context, _("Your enquiry"), noindex=True)


def page_account(context, s):
	from thinknxg_rental.portal.utils import get_portal_customers, is_staff

	customers, staff = [], False
	if frappe.session.user != "Guest":
		staff = is_staff()
		if not staff:
			customers, _p = get_portal_customers()
	enquiries = []
	if frappe.session.user != "Guest":
		# the user's own enquiries, and those of the customer accounts they belong to
		or_filters = [["user", "=", frappe.session.user]] + ([["customer", "in", customers]] if customers else [])
		enquiries = frappe.get_all("Rental Website Enquiry", filters={"status": ["!=", "Spam"]}, or_filters=or_filters, fields=["name", "enquiry_type", "status", "enquiry_date"],
			order_by="creation desc", limit=10)
	context.update(rw_page="templates/rental_website/pages/account.html", rw_crumbs=[(_("Home"), "/hire"), (_("Account"), "/hire/account")],
		rw_customer_names=[frappe.db.get_value("Customer", c, "customer_name") for c in customers], rw_is_customer=bool(customers),
		rw_is_staff=staff, rw_enquiries=enquiries, rw_prefill=_prefill())
	seo(context, _("Your account"), noindex=True)


def not_found(context, s):
	context.update(rw_page="templates/rental_website/pages/not_found.html", rw_crumbs=[(_("Home"), "/hire"), (_("Page not found"), context.rw_path)])
	seo(context, _("Page not found"), noindex=True, canonical=context.rw_path)


def _prefill():
	if frappe.session.user == "Guest":
		return {}
	u = frappe.db.get_value("User", frappe.session.user, ["full_name", "email", "mobile_no", "phone"], as_dict=True) or {}
	return {"full_name": u.get("full_name") or "", "email": u.get("email") or "", "phone": u.get("mobile_no") or u.get("phone") or ""}
