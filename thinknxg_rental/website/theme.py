"""Website templates: each is a set of design tokens and layout choices. Rental Website Settings picks
one and may override any of its values. Adding a template means adding an entry here (and, for a new
layout value, its CSS in public/rental_website/rw.css); pages and sections do not change."""
import frappe

TEMPLATES = {
	"Industrial Corporate": dict(
		primary="#1f4e79", accent="#0b8f8a", dark="#0e1a2b", typography="Condensed Headings", header_style="Solid Dark",
		hero_layout="Split", card_style="Bordered", catalogue_view="Grid", corner_style="Soft",
		sections=["Hero", "Categories", "Featured Products", "Category Products", "Advantages", "Process", "Industries", "Testimonials",
			"Statistics", "Call to Action", "Contact"],
	),
	"Modern Minimal": dict(
		primary="#1f5fd6", accent="#0b8f8a", dark="#111c2d", typography="Barlow Throughout", header_style="Light",
		hero_layout="Centred", card_style="Flat", catalogue_view="Grid", corner_style="Rounded",
		sections=["Hero", "Categories", "Featured Products", "Process", "Advantages", "Testimonials", "Call to Action"],
	),
	"Premium Construction": dict(
		primary="#1f4e79", accent="#e8a317", dark="#15181d", typography="Condensed Headings", header_style="Transparent over Hero",
		hero_layout="Full Image", card_style="Elevated", catalogue_view="Grid", corner_style="Square",
		sections=["Hero", "Statistics", "Categories", "Category Products", "Services", "Industries", "Process", "Testimonials",
			"Banner", "Call to Action", "Contact"],
	),
	"Enterprise Rental": dict(
		primary="#1f5fd6", accent="#0b8f8a", dark="#0e1a2b", typography="Barlow Throughout", header_style="Light",
		hero_layout="Split", card_style="Specification", catalogue_view="List", corner_style="Soft",
		sections=["Hero", "Advantages", "Categories", "Featured Products", "Services", "Process", "Statistics", "Call to Action", "Contact"],
	),
	"Equipment Catalogue Focus": dict(
		primary="#1f4e79", accent="#1f5fd6", dark="#0e1a2b", typography="Condensed Headings", header_style="Solid Dark",
		hero_layout="Compact Search", card_style="Specification", catalogue_view="List", corner_style="Soft",
		sections=["Hero", "Categories", "Featured Products", "Category Products", "Process", "Call to Action"],
	),
}
DEFAULT = "Industrial Corporate"
OVERRIDES = ("typography", "header_style", "hero_layout", "card_style", "catalogue_view", "corner_style")
COLORS = {"primary": "primary_color", "accent": "accent_color", "dark": "dark_color"}


def slugify(value):
	return frappe.website.utils.cleanup_page_name(value or "").replace("_", "-")


def theme(settings=None):
	"""The template's values with the administrator's overrides applied."""
	s = settings or frappe.get_cached_doc("Rental Website Settings")
	base = dict(TEMPLATES.get(s.template) or TEMPLATES[DEFAULT])
	for key, field in COLORS.items():
		if s.get(field):
			base[key] = s.get(field)
	for key in OVERRIDES:
		if s.get(key):
			base[key] = s.get(key)
	base["template"] = s.template if s.template in TEMPLATES else DEFAULT
	base["attrs"] = {
		"data-template": slugify(base["template"]),
		"data-header": slugify(base["header_style"]),
		"data-hero": slugify(base["hero_layout"]),
		"data-cards": slugify(base["card_style"]),
		"data-corners": slugify(base["corner_style"]),
		"data-type": slugify(base["typography"]),
	}
	base["css"] = ":root{--rw-primary:%s;--rw-accent:%s;--rw-dark:%s;--rw-primary-ink:%s;--rw-on-accent:%s;}" % (
		safe_color(base["primary"]), safe_color(base["accent"]), safe_color(base["dark"]), shade(base["primary"], -0.18),
		"#111" if luminance(base["accent"]) > 0.55 else "#fff")
	return base


def safe_color(value):
	value = (value or "").strip()
	return value if value.startswith("#") and len(value) in (4, 7) and all(c in "0123456789abcdefABCDEF" for c in value[1:]) else "#1f4e79"


def _rgb(hexcolor):
	h = safe_color(hexcolor).lstrip("#")
	if len(h) == 3:
		h = "".join(c * 2 for c in h)
	return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def shade(hexcolor, amount):
	r, g, b = _rgb(hexcolor)
	f = (lambda c: max(0, min(255, round(c * (1 + amount))))) if amount < 0 else (lambda c: round(c + (255 - c) * amount))
	return "#%02x%02x%02x" % (f(r), f(g), f(b))


def luminance(hexcolor):
	r, g, b = (c / 255 for c in _rgb(hexcolor))
	return 0.2126 * r + 0.7152 * g + 0.0722 * b
