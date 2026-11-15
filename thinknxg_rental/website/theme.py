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
	button, on_button = accent_button(base["accent"])
	base["css"] = ":root{--rw-primary:%s;--rw-accent:%s;--rw-dark:%s;--rw-primary-ink:%s;--rw-link:%s;--rw-accent-btn:%s;--rw-on-accent:%s;}" % (
		safe_color(base["primary"]), safe_color(base["accent"]), safe_color(base["dark"]), shade(readable_on_white(base["primary"]), -0.18),
		readable_on_white(base["primary"]), button, on_button)
	return base


WHITE, INK = "#ffffff", "#111111"
AA = 4.5  # WCAG AA for body-size text


def contrast(a, b):
	"""WCAG contrast ratio of two colours."""
	la, lb = sorted((_relative_luminance(a), _relative_luminance(b)), reverse=True)
	return (la + 0.05) / (lb + 0.05)


def _relative_luminance(hexcolor):
	def channel(c):
		c = c / 255
		return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

	r, g, b = (channel(c) for c in _rgb(hexcolor))
	return 0.2126 * r + 0.7152 * g + 0.0722 * b


def accent_button(accent):
	"""(button colour, text colour) for accent buttons, readable at AA. White text is kept when a slightly
	deeper accent reaches AA (the accent stays recognisable); otherwise dark text on the accent itself."""
	accent = safe_color(accent)
	for step in range(0, 9):
		c = shade(accent, -0.03 * step) if step else accent
		if contrast(c, WHITE) >= AA:
			return c, WHITE
	if contrast(accent, INK) >= AA:
		return accent, INK
	return shade(accent, -0.45), WHITE


def readable_on_white(color):
	"""The colour, deepened until text in it reads at AA on white (links, prices)."""
	c = safe_color(color)
	for _i in range(20):
		if contrast(c, WHITE) >= AA:
			return c
		c = shade(c, -0.08)
	return c


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
