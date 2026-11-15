"""Public catalogue data for the rental website (/hire).

Only items whose Rental Item Profile has Show on Website (and is not disabled, nor its Item) appear.
Categories are the ERPNext Item Groups of those items, with their parent groups, so the catalogue
follows the item master. Rates come from the rental rate logic (customer rate card -> general rate card
-> Rental Item Profile, services/utils.get_rental_rate) and are shown only when the website settings
say so. Availability is free own stock (services/inventory: Bin minus open reservations, per active
own rental warehouse) shown as a band, never as a quantity.
"""
import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, getdate, strip_html

from thinknxg_rental.website.theme import slugify

BASE = "/hire"
CACHE_KEY = "thinknxg_rental:website:categories"
PAGE_LENGTH = 12
SORTS = {
	"featured": "p.featured desc, i.item_name asc",
	"name": "i.item_name asc",
	"name_desc": "i.item_name desc",
	"newest": "p.creation desc",
}


def settings():
	return frappe.get_cached_doc("Rental Website Settings")


def url(*parts):
	return "/".join([BASE] + [p for p in parts if p])


# ----------------------------------------------------------------------------- categories
def category_tree():
	"""[{name, slug, title, description, image, count, parent, depth, url}] of item groups with published
	items, with their ancestors below the root group, in tree order. Cached until an item, profile, item
	group or the website settings change."""
	cached = frappe.cache.get_value(CACHE_KEY)
	if cached is not None:
		return [frappe._dict(c) for c in cached]
	counts = dict(frappe.db.sql("""select i.item_group, count(*) from `tabRental Item Profile` p
		inner join `tabItem` i on i.name = p.item
		where p.show_on_website = 1 and p.disabled = 0 and i.disabled = 0 group by i.item_group"""))
	if not counts:
		frappe.cache.set_value(CACHE_KEY, [], expires_in_sec=600)
		return []
	groups = frappe.get_all("Item Group", fields=["name", "item_group_name", "parent_item_group", "lft", "rgt", "image", "is_group"], order_by="lft asc")
	by_name = {g.name: g for g in groups}
	root = min(groups, key=lambda g: g.lft).name if groups else None
	keep = set()
	for name in counts:
		g = by_name.get(name)
		while g and g.name != root:
			keep.add(g.name)
			g = by_name.get(g.parent_item_group)
	extra = {r.item_group: r for r in (settings().categories or [])}
	out, slugs = [], set()
	for g in groups:
		if g.name not in keep or (extra.get(g.name) and extra[g.name].hidden):
			continue
		slug = slugify(g.item_group_name or g.name) or slugify(g.name)
		base, n = slug, 2
		while slug in slugs:
			slug, n = f"{base}-{n}", n + 1
		slugs.add(slug)
		total = sum(c for name, c in counts.items() if by_name.get(name) and g.lft <= by_name[name].lft and by_name[name].rgt <= g.rgt)
		depth, p = 0, by_name.get(g.parent_item_group)
		while p and p.name != root:
			depth, p = depth + 1, by_name.get(p.parent_item_group)
		row = extra.get(g.name)
		out.append(dict(name=g.name, slug=slug, title=g.item_group_name or g.name, description=(row.description if row else "") or "",
			image=(row.image if row and row.image else g.image) or "", count=total, lft=g.lft, rgt=g.rgt,
			parent=g.parent_item_group if g.parent_item_group in keep else None, depth=depth, url=url("equipment", slug)))
	frappe.cache.set_value(CACHE_KEY, out, expires_in_sec=6 * 3600)
	return [frappe._dict(c) for c in out]


def clear_cache(doc=None, method=None):
	frappe.cache.delete_value(CACHE_KEY)


def category_by_slug(slug):
	return next((c for c in category_tree() if c.slug == slug), None)


def category_of(item_group):
	return next((c for c in category_tree() if c.name == item_group), None)


def top_categories():
	return [c for c in category_tree() if not c.parent]


# ----------------------------------------------------------------------------- availability and rates
def free_stock(items):
	"""{item: free own stock} - the same figure as warehouses.available_own_qty, for many items at once:
	per active own rental warehouse, max(Bin - open reservations, 0), summed."""
	from thinknxg_rental.services import inventory
	from thinknxg_rental.services import warehouses as rw

	items = list(items)
	whs = rw.own_warehouses()
	if not items or not whs:
		return {i: 0 for i in items}
	stock = inventory.bins(items, whs)
	held = inventory.reserved(items, set(whs))
	out = {i: 0.0 for i in items}
	for (item, wh), qty in stock.items():
		out[item] += max(flt(qty) - flt(held.get((item, wh))), 0)
	return out


def availability_band(free, qty=None):
	"""What the website says about stock: never the figure itself."""
	threshold = cint(settings().limited_threshold) or 20
	if qty:
		if free >= flt(qty):
			return {"code": "available", "label": _("Available from stock")}
		if free > 0:
			return {"code": "partial", "label": _("Part available now, the rest on request")}
		return {"code": "request", "label": _("On request: we confirm availability")}
	if free >= threshold:
		return {"code": "available", "label": _("In stock")}
	if free > 0:
		return {"code": "limited", "label": _("Limited availability")}
	return {"code": "request", "label": _("Available on request")}


def rate_customer():
	"""The logged-in portal customer, whose own rate card applies; none for guests and staff."""
	if frappe.session.user == "Guest":
		return None
	from thinknxg_rental.portal.utils import get_portal_customers, is_staff

	if is_staff():
		return None
	customers, _preview = get_portal_customers()
	return customers[0] if len(customers) == 1 else None


def rates_for(item_code, customer=None):
	from thinknxg_rental.services.utils import get_rental_rate

	return {basis: flt(get_rental_rate(item_code, basis, customer)) for basis in ("Daily", "Weekly", "Monthly")}


def currency():
	from thinknxg_rental.services.utils import get_settings

	company = get_settings().company
	return frappe.get_cached_value("Company", company, "default_currency") if company else None


def estimate(item_code, qty, required_from, expected_return, customer=None):
	"""Rental days (at least the item's minimum hire), the rate on the item's default basis and the estimate,
	with the same formula as hire orders (services/utils.estimate_amount)."""
	from thinknxg_rental.services.utils import estimate_amount, get_rental_rate

	profile = frappe.db.get_value("Rental Item Profile", item_code, ["default_rate_basis", "minimum_hire_days"], as_dict=True) or frappe._dict()
	basis = profile.default_rate_basis or "Monthly"
	days = date_diff(getdate(expected_return), getdate(required_from)) + 1 if required_from and expected_return else 0
	chargeable = max(days, cint(profile.minimum_hire_days)) if days > 0 else 0
	rate = flt(get_rental_rate(item_code, basis, customer))
	return frappe._dict(days=days, chargeable_days=chargeable, minimum_hire_days=cint(profile.minimum_hire_days), rate_basis=basis,
		rate=rate, amount=estimate_amount(qty, chargeable, basis, rate) if chargeable and rate else 0)


# ----------------------------------------------------------------------------- products
def _product_query(category=None, search=None, system=None, purchasable=None, featured=None, items=None):
	cond, args = ["p.show_on_website = 1", "p.disabled = 0", "i.disabled = 0"], {}
	if category:
		cond.append("ig.lft >= %(lft)s and ig.rgt <= %(rgt)s")
		args.update(lft=category.lft, rgt=category.rgt)
	if search:
		cond.append("(i.item_name like %(q)s or i.name like %(q)s or ifnull(p.short_description, '') like %(q)s or ifnull(i.description, '') like %(q)s)")
		args["q"] = "%" + search.strip()[:80].replace("%", "").replace("_", "\\_") + "%"
	if system:
		cond.append("p.category = %(system)s")
		args["system"] = system
	if purchasable:
		cond.append("p.available_for_purchase = 1")
	if featured:
		cond.append("p.featured = 1")
	if items is not None:
		cond.append("p.item in %(items)s")
		args["items"] = tuple(items) or ("",)
	return f"""from `tabRental Item Profile` p inner join `tabItem` i on i.name = p.item
		left join `tabItem Group` ig on ig.name = i.item_group where {" and ".join(cond)}""", args


def products(category=None, search=None, system=None, purchasable=None, in_stock=None, featured=None, sort=None, page=1,
		page_length=PAGE_LENGTH, exclude=None):
	"""A page of catalogue cards and the total."""
	body, args = _product_query(category, search, system, purchasable, featured)
	if exclude:
		body += " and p.item != %(exclude)s"
		args["exclude"] = exclude
	order = SORTS.get(sort) or SORTS["featured"]
	page = max(cint(page), 1)
	length = min(max(cint(page_length), 1), 48)
	if in_stock:
		# free stock is worked out in Python (same rules as reservations); filter before paging
		codes = [r[0] for r in frappe.db.sql(f"select p.item {body} order by {order}", args)]
		free = free_stock(codes)
		codes = [c for c in codes if free.get(c, 0) > 0]
		total = len(codes)
		codes = codes[(page - 1) * length: page * length]
		rows = frappe.db.sql(f"select {CARD_FIELDS} {body} and p.item in %(page_items)s order by {order}", dict(args, page_items=tuple(codes) or ("",)), as_dict=True)
	else:
		total = frappe.db.sql(f"select count(*) {body}", args)[0][0]
		rows = frappe.db.sql(f"select {CARD_FIELDS} {body} order by {order} limit {length} offset {(page - 1) * length}", args, as_dict=True)
	return decorate(rows), cint(total)


CARD_FIELDS = """p.item as item_code, i.item_name, i.item_group, i.image, i.stock_uom as uom, p.route, p.short_description,
	i.description, p.category as system, p.minimum_hire_days, p.weight_per_unit, p.dimensions, p.featured, p.available_for_purchase,
	p.default_rate_basis"""


def decorate(rows):
	s = settings()
	customer = rate_customer() if cint(s.show_prices) else None
	free = free_stock([r.item_code for r in rows]) if cint(s.show_availability) else {}
	for r in rows:
		cat = category_of(r.item_group)
		r.category = cat.title if cat else r.item_group
		r.category_slug = cat.slug if cat else "all"
		r.slug = r.route or slugify(r.item_name)
		r.url = url("equipment", r.category_slug, r.slug)
		r.summary = (r.short_description or strip_html(r.description or "")).strip()
		if r.summary == r.item_name:
			r.summary = ""
		r.summary = r.summary[:220]
		if cint(s.show_prices):
			from thinknxg_rental.services.utils import get_rental_rate

			r.rate_basis = r.default_rate_basis or "Monthly"
			r.rate = flt(get_rental_rate(r.item_code, r.rate_basis, customer))
		if cint(s.show_availability):
			r.availability = availability_band(free.get(r.item_code, 0))
	return rows


def product_by_slug(slug):
	name = frappe.db.get_value("Rental Item Profile", {"route": slug, "show_on_website": 1, "disabled": 0}, "name")
	if not name:
		# items without a slug yet are reachable by the slug made from their name
		for item_code, item_name in frappe.db.sql("""select p.item, i.item_name from `tabRental Item Profile` p inner join `tabItem` i on i.name = p.item
				where p.show_on_website = 1 and p.disabled = 0 and ifnull(p.route, '') = ''"""):
			if slugify(item_name) == slug:
				name = item_code
				break
	if not name or frappe.db.get_value("Item", name, "disabled"):
		return None
	return product(name)


def product(item_code):
	s = settings()
	p = frappe.get_doc("Rental Item Profile", item_code)
	item = frappe.get_cached_doc("Item", item_code)
	card = decorate(frappe.db.sql(f"select {CARD_FIELDS} {_product_query(items=[item_code])[0]}", {"items": (item_code,)}, as_dict=True))[0]
	images = []
	if item.image:
		images.append({"src": item.image, "alt": item.item_name})
	for g in p.gallery or []:
		if g.image and g.image not in [x["src"] for x in images]:
			images.append({"src": g.image, "alt": g.caption or item.item_name})
	specs = [(_("Item code"), item.name), (_("Unit"), item.stock_uom)]
	if p.category:
		specs.append((_("System"), _(p.category)))
	if p.dimensions:
		specs.append((_("Dimensions"), p.dimensions))
	if flt(p.weight_per_unit):
		specs.append((_("Weight"), f"{flt(p.weight_per_unit):g} kg"))
	if p.material:
		specs.append((_("Material"), p.material))
	if cint(p.minimum_hire_days):
		specs.append((_("Minimum hire"), _("{0} days").format(cint(p.minimum_hire_days))))
	specs += [(r.label, r.value) for r in p.specifications or []]
	datasheet = p.datasheet if p.datasheet and p.datasheet.startswith("/files/") else None
	related, _t = products(category=category_of(item.item_group), exclude=item_code, page_length=4)
	if not related and p.category:
		related, _t = products(system=p.category, exclude=item_code, page_length=4)
	out = frappe._dict(card)
	out.update(images=images, specs=specs, datasheet=datasheet, usage=p.usage or "", description=item.description or "",
		related=related, minimum_hire_days=cint(p.minimum_hire_days), purchasable=cint(p.available_for_purchase) and cint(s.allow_purchase_enquiries))
	if cint(s.show_prices):
		out.rates = rates_for(item_code, rate_customer())
		out.own_rates = bool(rate_customer())
	return out


def ensure_route(doc, method=None):
	"""Rental Item Profile validate: a unique website slug for published items."""
	if not doc.show_on_website:
		return
	slug = slugify(doc.route or frappe.db.get_value("Item", doc.item, "item_name") or doc.item)
	base, n = slug, 2
	while frappe.db.exists("Rental Item Profile", {"route": slug, "name": ["!=", doc.name]}):
		slug, n = f"{base}-{n}", n + 1
	doc.route = slug
