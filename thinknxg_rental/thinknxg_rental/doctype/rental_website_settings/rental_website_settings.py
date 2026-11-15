import re

import frappe
from frappe import _
from frappe.model.document import Document

from thinknxg_rental.website.theme import TEMPLATES

HOME_ROUTE = "hire"


LINK_PREFIXES = ("/", "https://", "http://", "mailto:", "tel:")


def check_link(value, where):
	"""Website links must be site paths or ordinary web, mail or phone links (never javascript: and the like)."""
	value = (value or "").strip()
	if value and (not value.startswith(LINK_PREFIXES) or value.startswith("//")):
		frappe.throw(_("{0}: start the link with /, https://, mailto: or tel:").format(where), title=_("Invalid link"))


def check_public_image(value, where):
	if (value or "").startswith(("/private/", "private/")):
		frappe.throw(_("{0}: this file is private, so visitors cannot see it. Upload it again with Public ticked.").format(where),
			title=_("Private file"))


class RentalWebsiteSettings(Document):
	def validate(self):
		from thinknxg_rental.website.theme import safe_color

		for field in ("primary_color", "accent_color", "dark_color"):
			value = (self.get(field) or "").strip()
			if value and safe_color(value) != value:
				frappe.throw(_("{0} must be a colour such as #1f4e79").format(self.meta.get_label(field)))
		for row in self.links or []:
			check_link(row.link, _("Link row #{0}").format(row.idx))
		for row in self.sections or []:
			where = _("Home section #{0} ({1})").format(row.idx, _(row.section_type))
			check_link(row.cta_link, where)
			check_link(row.cta2_link, where)
			check_public_image(row.image, where)
		for row in self.cards or []:
			where = _("Card #{0} ({1})").format(row.idx, row.title or _(row.card_group))
			check_link(row.link, where)
			check_public_image(row.image, where)
		for row in self.categories or []:
			check_public_image(row.image, _("Category row #{0}").format(row.idx))
		check_link(self.map_link, self.meta.get_label("map_link"))
		for field in ("logo", "og_image", "about_image"):
			check_public_image(self.get(field), self.meta.get_label(field))
		if self.whatsapp and not re.fullmatch(r"\+?[0-9 ()-]{6,24}", self.whatsapp.strip()):
			frappe.throw(_("WhatsApp: enter the number with its country code, such as +968 9123 4567"))

	def on_update(self):
		from thinknxg_rental.website.catalogue import clear_cache

		clear_cache()
		self.sync_home_page()
		self.sync_robots()
		frappe.clear_cache(doctype="Rental Website Settings")

	def sync_home_page(self):
		ws = frappe.get_single("Website Settings")
		if self.enabled and self.use_as_home_page and ws.home_page != HOME_ROUTE:
			ws.home_page = HOME_ROUTE
		elif (not self.enabled or not self.use_as_home_page) and ws.home_page == HOME_ROUTE:
			ws.home_page = ""
		else:
			return
		ws.flags.ignore_permissions = True
		ws.save()

	def sync_robots(self):
		"""Point search engines at the catalogue sitemap and keep the customer and staff portals out."""
		if not self.enabled:
			return
		ws = frappe.get_single("Website Settings")
		lines = (ws.robots_txt or "").splitlines()
		wanted = ["Sitemap: " + frappe.utils.get_url("/rental_sitemap.xml")]
		if not any(line.strip().lower().startswith("user-agent") for line in lines):
			wanted = ["User-agent: *", "Disallow: /rental/", "Disallow: /app/", *wanted]
		missing = [w for w in wanted if w not in lines]
		if missing:
			ws.robots_txt = "\n".join([*lines, *missing]).strip()
			ws.flags.ignore_permissions = True
			ws.save()

	@frappe.whitelist()
	def load_template_sections(self):
		"""Replace the home page sections with the chosen template's set (content of matching sections kept)."""
		self.check_permission("write")
		order = TEMPLATES.get(self.template, {}).get("sections") or []
		existing = {}
		for row in self.sections:
			existing.setdefault(row.section_type, row.as_dict())
		defaults = {s["section_type"]: s for s in default_sections()}
		rows = []
		for section_type in order:
			base = existing.get(section_type) or defaults.get(section_type) or {"section_type": section_type}
			row = {k: base.get(k) for k in ("section_type", "enabled", "title", "subtitle", "item_group", "limit", "tone", "content", "image",
				"cta_label", "cta_link", "cta2_label", "cta2_link")}
			row["enabled"] = 1 if base.get("enabled", 1) else 0
			rows.append(row)
		self.set("sections", rows)
		self.save()
		return len(rows)


# ----------------------------------------------------------------------------- default content
def default_sections():
	return [
		dict(section_type="Hero", enabled=1, title=_("The Smarter Way to Rent Formwork & Scaffolding Equipment"),
			subtitle=_("Discover dependable construction equipment rental solutions powered by thinkNXG ERP. Explore products, check availability, and manage your rental requirements through one intelligent platform."),
			cta_label=_("Explore the catalogue"), cta_link="/hire/equipment", cta2_label=_("Request a quote"), cta2_link="/hire/basket", tone="Dark"),
		dict(section_type="Categories", enabled=1, title=_("Equipment categories"), subtitle=_("Browse formwork, scaffolding, props and accessories by system."), tone="Light"),
		dict(section_type="Featured Products", enabled=1, title=_("Popular rental products"), limit=8, tone="Tinted",
			cta_label=_("See the full catalogue"), cta_link="/hire/equipment"),
		dict(section_type="Category Products", enabled=0, title=_("Featured formwork systems"), limit=4, tone="Light"),
		dict(section_type="Category Products", enabled=0, title=_("Featured scaffolding systems"), limit=4, tone="Light"),
		dict(section_type="Advantages", enabled=1, title=_("Why choose thinkNXG Rental"), tone="Light"),
		dict(section_type="Process", enabled=1, title=_("How renting works"), subtitle=_("From enquiry to collection, every step is recorded and visible in your account."), tone="Tinted"),
		dict(section_type="Services", enabled=0, title=_("Rental services"), tone="Light", cta_label=_("All services"), cta_link="/hire/services"),
		dict(section_type="Industries", enabled=1, title=_("Industries we serve"), tone="Light", cta_label=_("All industries"), cta_link="/hire/industries"),
		dict(section_type="Testimonials", enabled=1, title=_("What our customers say"), tone="Tinted"),
		dict(section_type="Statistics", enabled=1, title=_("In numbers"), tone="Dark"),
		dict(section_type="Banner", enabled=0, title=_("Planning a large project?"), tone="Brand"),
		dict(section_type="Call to Action", enabled=1, title=_("Planning a project?"),
			subtitle=_("Tell us what you need and when. We come back with availability and a quotation."),
			cta_label=_("Send an enquiry"), cta_link="/hire/contact", cta2_label=_("Browse equipment"), cta2_link="/hire/equipment", tone="Brand"),
		dict(section_type="Contact", enabled=1, title=_("Talk to the rental team"), tone="Light"),
	]


def default_cards():
	S, I, P, A = "Service", "Industry", "Process Step", "Advantage"
	return [
		dict(card_group=S, icon="layers", title=_("Formwork rental"), description=_("Wall, slab, column and beam formwork systems for concrete works of any size.")),
		dict(card_group=S, icon="construction", title=_("Scaffolding rental"), description=_("Access and support scaffolding with the fittings and accessories that go with it.")),
		dict(card_group=S, icon="boxes", title=_("Construction equipment rental"), description=_("Props, shoring and site equipment hired for the days, weeks or months you need.")),
		dict(card_group=S, icon="calendar-range", title=_("Long-term rental"), description=_("Monthly rates and contracts for projects that run over many months.")),
		dict(card_group=S, icon="clipboard-list", title=_("Project-based rental"), description=_("One contract for a project, with deliveries and returns phased to your programme.")),
		dict(card_group=S, icon="package-check", title=_("Equipment supply"), description=_("Selected items can also be bought. Ask for a purchase quotation.")),
		dict(card_group=S, icon="file-check-2", title=_("Rental contract management"), description=_("Contracts, extensions, returns and invoices you can follow in your online account.")),
		dict(card_group=S, icon="truck", title=_("Delivery and collection"), description=_("Delivery to site and collection when material goes off hire, each with its delivery or return note.")),
		dict(card_group=S, icon="hard-hat", title=_("Technical assistance"), description=_("Help choosing systems and quantities for your structure."), enabled=0),
		dict(card_group=I, icon="house", title=_("Residential construction"), description=_("Villas, apartment blocks and housing developments.")),
		dict(card_group=I, icon="building-2", title=_("Commercial construction"), description=_("Offices, retail, hotels and mixed-use buildings.")),
		dict(card_group=I, icon="route", title=_("Infrastructure"), description=_("Roads, utilities, drainage and public works.")),
		dict(card_group=I, icon="factory", title=_("Industrial projects"), description=_("Plants, warehouses and industrial facilities.")),
		dict(card_group=I, icon="waypoints", title=_("Bridges and flyovers"), description=_("Piers, decks and soffits that need heavy-duty support.")),
		dict(card_group=I, icon="building", title=_("High-rise construction"), description=_("Repetitive floor cycles with formwork and access systems.")),
		dict(card_group=I, icon="ruler", title=_("Civil engineering"), description=_("Retaining walls, tanks, culverts and structural works.")),
		dict(card_group=I, icon="landmark", title=_("Government and infrastructure projects"), description=_("Public buildings and state infrastructure programmes.")),
		dict(card_group=P, icon="search", title=_("Choose your equipment"), description=_("Browse the catalogue and add what you need to your enquiry.")),
		dict(card_group=P, icon="send", title=_("Send your enquiry"), description=_("Give the quantities, the rental dates and the project location.")),
		dict(card_group=P, icon="file-text", title=_("Receive your quotation"), description=_("We check availability and send a quotation for your period.")),
		dict(card_group=P, icon="truck", title=_("Delivery to site"), description=_("Material is dispatched to your site with a delivery note.")),
		dict(card_group=P, icon="layout-dashboard", title=_("Follow it online"), description=_("See material on site, invoices and requests in your account.")),
		dict(card_group=P, icon="undo-2", title=_("Return or extend"), description=_("Ask for a collection or more time straight from your account.")),
		dict(card_group=A, icon="warehouse", title=_("Stock across locations"), description=_("Availability is checked against stock in every rental yard, net of reservations.")),
		dict(card_group=A, icon="calendar-clock", title=_("Flexible hire periods"), description=_("Daily, weekly and monthly rates, with a clear minimum hire for each item.")),
		dict(card_group=A, icon="file-check-2", title=_("Clear quotations"), description=_("Every enquiry is answered with a quotation for your quantities and dates.")),
		dict(card_group=A, icon="monitor-smartphone", title=_("Your account online"), description=_("Orders, deliveries, returns, invoices and statements in one customer portal.")),
	]


def default_links():
	return [
		dict(location="Header", label=_("Equipment"), link="/hire/equipment"),
		dict(location="Header", label=_("Services"), link="/hire/services"),
		dict(location="Header", label=_("Industries"), link="/hire/industries"),
		dict(location="Header", label=_("About"), link="/hire/about"),
		dict(location="Header", label=_("Contact"), link="/hire/contact"),
		dict(location="Footer: Company", label=_("About us"), link="/hire/about"),
		dict(location="Footer: Company", label=_("Services"), link="/hire/services"),
		dict(location="Footer: Company", label=_("Industries"), link="/hire/industries"),
		dict(location="Footer: Company", label=_("Contact"), link="/hire/contact"),
		dict(location="Footer: Support", label=_("My account"), link="/hire/account"),
		dict(location="Footer: Support", label=_("Request a quote"), link="/hire/basket"),
		dict(location="Footer: Support", label=_("Long-term contracts"), link="/hire/contact?type=Long-term%20Contract"),
	]


def seed_defaults():
	"""First-time content for the website settings (only empty tables are filled; safe to run again)."""
	s = frappe.get_single("Rental Website Settings")
	changed = False
	if not s.template:
		s.template = "Industrial Corporate"
		changed = True
	for table, rows in (("sections", default_sections()), ("cards", default_cards()), ("links", default_links())):
		if not s.get(table):
			for row in rows:
				s.append(table, dict({"enabled": 1}, **row) if table != "links" else row)
			changed = True
	if not s.about_intro:
		s.about_intro = _("<p>thinkNXG Rental supplies formwork, scaffolding, props and construction accessories for hire, with selected items also available to buy.</p>"
			"<p>Every enquiry, quotation, delivery, return and invoice runs on thinkNXG ERP, so availability is checked against real stock and customers can follow their rentals online.</p>")
		changed = True
	rs = frappe.get_single("Rental Settings")
	for target, source in (("contact_email", "portal_contact_email"), ("contact_phone", "portal_contact_phone")):
		if not s.get(target) and rs.get(source):
			s.set(target, rs.get(source))
			changed = True
	if s.show_prices is None:
		s.show_prices = rs.portal_show_rates
	if changed:
		s.flags.ignore_permissions = True
		s.flags.ignore_mandatory = True
		s.save()
