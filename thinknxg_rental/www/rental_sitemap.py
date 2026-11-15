"""/rental_sitemap.xml: every public page of the rental website - home, catalogue, categories, products
and the static pages. Linked from robots.txt by Rental Website Settings."""
from urllib.parse import quote

import frappe
from frappe.utils import cint, get_url, nowdate

no_cache = 1
base_template_path = "www/rental_sitemap.xml"


def get_context(context):
	from thinknxg_rental.website import catalogue as cat

	s = cat.settings()
	if not cint(s.enabled):
		return {"links": []}
	today = nowdate()
	loc = lambda path: get_url(quote(path))  # noqa: E731
	links = [{"loc": loc(p), "lastmod": today} for p in ("/hire", "/hire/equipment", "/hire/services", "/hire/industries", "/hire/about", "/hire/contact")]
	links += [{"loc": loc(c.url), "lastmod": today} for c in cat.category_tree()]
	rows = frappe.db.sql(f"""select {cat.CARD_FIELDS}, p.modified {cat._product_query()[0]} order by i.item_name""", as_dict=True)
	for r in rows:
		c = cat.category_of(r.item_group)
		slug = r.route or cat.slugify(r.item_name)
		links.append({"loc": loc(cat.url("equipment", c.slug if c else "all", slug)), "lastmod": f"{r.modified:%Y-%m-%d}"})
	return {"links": links}
