"""Public rental website (/hire): pages, catalogue, prices and availability from the rental logic,
enquiries into the Lead -> Quotation flow, the contact form, the sitemap, settings and the customer
portal additions (website enquiries, accepting a quotation).

    bench --site <site> run-tests --module thinknxg_rental.tests.test_public_website
"""
import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, nowdate, set_request
from frappe.website.serve import get_response

from thinknxg_rental.portal import customer as cp
from thinknxg_rental.tests.test_admin_portal import _leaf, prepare
from thinknxg_rental.tests.test_customer_portal import portal_user
from thinknxg_rental.website import api, catalogue as cat
from thinknxg_rental.website.theme import TEMPLATES, theme
from thinknxg_rental.thinknxg_rental.doctype.rental_website_settings.rental_website_settings import default_sections

USER = "rw.customer@example.com"
OTHER_USER = "rw.other@example.com"


def page(path, user="Guest"):
	"""(status, html, location) of a website page rendered as `user`."""
	frappe.set_user(user)
	frappe.local.form_dict = frappe._dict()
	set_request(method="GET", path=path)
	try:
		r = get_response()
		return r.status_code, frappe.safe_decode(r.get_data()), r.headers.get("Location")
	finally:
		if hasattr(frappe.local, "request"):
			del frappe.local.request
		frappe.local.form_dict = frappe._dict()
		frappe.set_user("Administrator")


class TestPublicWebsite(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		prepare(cls)
		frappe.set_user("Administrator")
		root = frappe.db.get_value("Item Group", {"parent_item_group": ["in", ["", None]]}, "name")
		for name, parent, is_group in (("RWT Formwork", root, 1), ("RWT Wall Panels", "RWT Formwork", 0), ("RWT Props", root, 0)):
			if not frappe.db.exists("Item Group", name):
				frappe.get_doc({"doctype": "Item Group", "item_group_name": name, "parent_item_group": parent, "is_group": is_group}).insert()
		cls.panel = cls.item("RWT-PANEL", "RWT Wall Panel 1200", "RWT Wall Panels", stock=500, monthly=90, featured=1, purchase=1, minimum=14)
		cls.prop = cls.item("RWT-PROP", "RWT Steel Prop", "RWT Props", stock=0, monthly=12)
		cls.hidden = cls.item("RWT-HIDDEN", "RWT Unpublished Item", "RWT Props", stock=10, monthly=5, publish=0)
		s = frappe.get_single("Rental Website Settings")
		cls.saved = {f: s.get(f) for f in ("enabled", "show_prices", "show_availability", "allow_purchase_enquiries", "use_as_home_page", "template")}
		s.update({"enabled": 1, "show_prices": 1, "show_availability": 1, "allow_purchase_enquiries": 1, "use_as_home_page": 0, "limited_threshold": 20})
		s.save()
		# a customer with a portal login, and another one
		cls.customer = frappe.get_doc({"doctype": "Customer", "customer_name": "RW Test Customer " + frappe.generate_hash(length=4),
			"customer_group": _leaf("Customer Group"), "territory": _leaf("Territory")}).insert().name
		portal_user(USER, cls.customer)
		cls.other = frappe.get_doc({"doctype": "Customer", "customer_name": "RW Other Customer " + frappe.generate_hash(length=4),
			"customer_group": _leaf("Customer Group"), "territory": _leaf("Territory")}).insert().name
		portal_user(OTHER_USER, cls.other)
		cat.clear_cache()
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		s = frappe.get_single("Rental Website Settings")
		s.update(cls.saved)
		s.save()
		frappe.db.commit()
		super().tearDownClass()

	@classmethod
	def item(cls, code, name, group, stock=0, monthly=0, featured=0, purchase=0, minimum=0, publish=1):
		if not frappe.db.exists("Item", code):
			frappe.get_doc({"doctype": "Item", "item_code": code, "item_name": name, "item_group": group, "stock_uom": "Nos", "is_stock_item": 1}).insert()
		if not frappe.db.exists("Rental Item Profile", code):
			frappe.get_doc({"doctype": "Rental Item Profile", "item": code}).insert()
		p = frappe.get_doc("Rental Item Profile", code)
		p.update({"category": "Formwork", "monthly_rate": monthly, "daily_rate": monthly / 20, "default_rate_basis": "Monthly", "minimum_hire_days": minimum,
			"show_on_website": publish, "featured": featured, "available_for_purchase": purchase, "dimensions": "1200 x 2400 mm", "weight_per_unit": 30})
		p.save()
		have = flt(frappe.db.get_value("Bin", {"item_code": code, "warehouse": cls.yard}, "actual_qty"))
		if stock > have:
			se = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "company": cls.company, "set_posting_time": 1,
				"posting_date": add_days(nowdate(), -10), "items": [{"item_code": code, "t_warehouse": cls.yard, "qty": stock - have, "basic_rate": 10}]})
			se.insert()
			se.submit()
		return code

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.clear_cache(doctype="Rental Website Settings")

	def tearDown(self):
		frappe.set_user("Administrator")

	def set(self, **values):
		s = frappe.get_single("Rental Website Settings")
		s.update(values)
		s.save()
		frappe.clear_cache(doctype="Rental Website Settings")

	def url_of(self, code):
		return next(p.url for p in cat.products(search="RWT", page_length=48)[0] if p.item_code == code)

	# ------------------------------------------------------------------ pages and routing
	def test_pages_render(self):
		for path in ("/hire", "/hire/equipment", "/hire/services", "/hire/industries", "/hire/about", "/hire/contact", "/hire/basket", "/hire/account"):
			status, html, _loc = page(path)
			self.assertEqual(status, 200, path)
			self.assertIn('rel="canonical"', html)
			self.assertIn("rw.css", html)
		status, html, _l = page("/hire")
		self.assertIn("The Smarter Way to Rent Formwork", html)
		self.assertIn('"@type": "Organization"', html)
		self.assertIn("RWT Wall Panel 1200", html)  # featured product on the home page

	def test_unknown_paths_are_not_found(self):
		for path in ("/hire/nothing", "/hire/equipment/no-such-category", "/hire/equipment/all/no-such-product", "/hire/equipment/a/b/c"):
			self.assertEqual(page(path)[0], 404, path)

	def test_disabled_website_is_hidden_from_visitors(self):
		self.set(enabled=0)
		try:
			self.assertEqual(page("/hire")[0], 404)
			status, html, _l = page("/hire", user="Administrator")
			self.assertEqual(status, 200)
			self.assertIn("rw-preview", html)
			with self.assertRaises(frappe.PermissionError):
				frappe.set_user("Guest")
				api.estimate(self.panel)
		finally:
			frappe.set_user("Administrator")
			self.set(enabled=1)

	# ------------------------------------------------------------------ catalogue
	def test_categories_come_from_item_groups(self):
		tree = {c.name: c for c in cat.category_tree()}
		self.assertIn("RWT Formwork", tree)
		self.assertIn("RWT Wall Panels", tree)
		self.assertEqual(tree["RWT Wall Panels"].parent, "RWT Formwork")
		self.assertGreaterEqual(tree["RWT Formwork"].count, 1)
		status, html, _l = page(tree["RWT Formwork"].url)
		self.assertEqual(status, 200)
		self.assertIn("RWT Wall Panel 1200", html)
		self.assertNotIn("RWT Steel Prop", html)

	def test_unpublished_items_never_appear(self):
		rows, _t = cat.products(search="RWT", page_length=48)
		codes = [r.item_code for r in rows]
		self.assertIn(self.panel, codes)
		self.assertNotIn(self.hidden, codes)
		self.assertIsNone(cat.product_by_slug(frappe.db.get_value("Rental Item Profile", self.hidden, "route")))
		with self.assertRaises(frappe.DoesNotExistError):
			api.estimate(self.hidden)

	def test_search_filters_sort_and_paging(self):
		rows, total = cat.products(search="RWT Wall", page_length=48)
		self.assertEqual([r.item_code for r in rows], [self.panel])
		rows, _t = cat.products(search="RWT", purchasable=1, page_length=48)
		self.assertEqual([r.item_code for r in rows], [self.panel])
		rows, _t = cat.products(search="RWT", in_stock=1, page_length=48)
		self.assertIn(self.panel, [r.item_code for r in rows])
		self.assertNotIn(self.prop, [r.item_code for r in rows])
		rows, _t = cat.products(search="RWT", sort="name_desc", page_length=48)
		self.assertEqual([r.item_code for r in rows], [self.panel, self.prop])
		rows, total = cat.products(search="RWT", page=2, page_length=1)
		self.assertEqual(total, 2)
		self.assertEqual(len(rows), 1)
		status, html, _l = page("/hire/equipment?q=RWT+Wall")
		self.assertEqual(status, 200)

	def test_product_page_and_canonical_redirect(self):
		url = self.url_of(self.panel)
		status, html, _l = page(url)
		self.assertEqual(status, 200)
		self.assertIn('"@type": "Product"', html)
		self.assertIn("RWT-PANEL", html)
		self.assertIn("data-rw-hire", html)
		slug = url.rsplit("/", 1)[-1]
		status, _h, location = page(f"/hire/equipment/rwt-props/{slug}")
		self.assertEqual(status, 301)
		self.assertTrue(location.endswith(url))

	# ------------------------------------------------------------------ prices and availability
	def test_rates_come_from_the_rental_rate_logic(self):
		from thinknxg_rental.services.utils import estimate_amount, get_rental_rate

		frappe.set_user("Guest")
		start, end = add_days(nowdate(), 2), add_days(nowdate(), 31)
		r = api.estimate(self.panel, 10, start, end)
		self.assertEqual(r["days"], 30)
		self.assertEqual(r["rate"], flt(get_rental_rate(self.panel, "Monthly", None)))
		self.assertAlmostEqual(r["amount"], estimate_amount(10, 30, "Monthly", r["rate"]))
		# the item's minimum hire applies to short periods
		r = api.estimate(self.panel, 10, start, add_days(start, 2))
		self.assertEqual(r["days"], 3)
		self.assertEqual(r["chargeable_days"], 14)

	def test_prices_hidden_when_switched_off(self):
		self.set(show_prices=0)
		try:
			frappe.set_user("Guest")
			r = api.estimate(self.panel, 5, add_days(nowdate(), 1), add_days(nowdate(), 10))
			self.assertNotIn("amount", r)
			self.assertNotIn("rate", r)
			self.assertFalse(any("rate" in p for p in cat.products(search="RWT")[0]))
			b = api.basket([{"item_code": self.panel, "qty": 2}], add_days(nowdate(), 1), add_days(nowdate(), 10))
			self.assertIsNone(b["total"])
			self.assertNotIn("amount", b["lines"][0])
		finally:
			frappe.set_user("Administrator")
			self.set(show_prices=1)

	def test_availability_is_a_band_from_free_stock(self):
		free = cat.free_stock([self.panel, self.prop])
		self.assertGreaterEqual(free[self.panel], 500)
		self.assertEqual(free[self.prop], 0)
		frappe.set_user("Guest")
		r = api.estimate(self.panel, 10)
		self.assertEqual(r["availability"]["code"], "available")
		self.assertNotIn("qty_available", r)
		r = api.estimate(self.panel, free[self.panel] + 1)
		self.assertEqual(r["availability"]["code"], "partial")
		self.assertEqual(api.estimate(self.prop, 1)["availability"]["code"], "request")
		self.assertEqual(cat.availability_band(5)["code"], "limited")

	def test_basket_ignores_prices_sent_by_the_browser(self):
		frappe.set_user("Guest")
		b = api.basket([{"item_code": self.panel, "qty": 4, "rate": 0.01, "amount": 0.01}, {"item_code": self.hidden, "qty": 1},
			{"item_code": self.prop, "qty": 1, "line_type": "Purchase"}], add_days(nowdate(), 1), add_days(nowdate(), 30))
		codes = [l["item_code"] for l in b["lines"]]
		self.assertEqual(codes, [self.panel, self.prop])
		self.assertEqual(b["lines"][1]["line_type"], "Hire")  # the prop is not for sale
		self.assertGreater(b["lines"][0]["amount"], 1)

	# ------------------------------------------------------------------ enquiries
	def enquiry(self, **extra):
		data = {"full_name": "Website Visitor", "email": f"visitor.{frappe.generate_hash(length=6)}@example.com", "phone": "+91 98470 00000",
			"company_name": "Visitor Builders", "project_location": "Kochi tower", "required_from": add_days(nowdate(), 3),
			"expected_return": add_days(nowdate(), 40), "items": [{"item_code": self.panel, "qty": 25, "estimated_amount": 1}]}
		data.update(extra)
		return api.submit_enquiry(data)

	def test_enquiry_creates_lead_and_draft_quotation(self):
		frappe.set_user("Guest")
		r = self.enquiry(items=[{"item_code": self.panel, "qty": 25}, {"item_code": self.panel, "qty": 5, "line_type": "Purchase"}])
		frappe.set_user("Administrator")
		e = frappe.get_doc("Rental Website Enquiry", r["name"])
		self.assertTrue(e.lead)
		self.assertEqual(frappe.db.get_value("Lead", e.lead, "email_id"), e.email)
		self.assertEqual(e.status, "In Review")
		hire = frappe.get_doc("Quotation", e.hire_quotation)
		self.assertEqual((hire.docstatus, hire.quotation_to, hire.party_name, hire.deal_type), (0, "Lead", e.lead, "Material Hire"))
		self.assertEqual(str(hire.nxg_required_from), str(e.required_from))
		self.assertEqual(hire.nxg_website_enquiry, e.name)
		self.assertEqual([(i.item_code, i.qty) for i in hire.items], [(self.panel, 25)])
		sale = frappe.get_doc("Quotation", e.purchase_quotation)
		self.assertEqual(sale.deal_type, "Material Sale")
		# the estimate is the server's, not the browser's
		self.assertGreater(e.estimated_total, 1)
		self.assertTrue(frappe.db.exists("Notification Log", {"document_type": "Rental Website Enquiry", "document_name": e.name}))
		# a second enquiry from the same e-mail reuses the lead
		frappe.set_user("Guest")
		r2 = self.enquiry(email=e.email)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Rental Website Enquiry", r2["name"], "lead"), e.lead)

	def test_enquiry_validation(self):
		frappe.set_user("Guest")
		cases = [
			dict(items=[]),
			dict(email="not-an-email"),
			dict(full_name=""),
			dict(phone="call me"),
			dict(required_from=add_days(nowdate(), -1)),
			dict(expected_return=add_days(nowdate(), 1)),
			dict(required_from=None),
			dict(items=[{"item_code": self.panel, "qty": 0}]),
			dict(items=[{"item_code": self.panel, "qty": 10**7}]),
			dict(items=[{"item_code": self.hidden, "qty": 1}]),
			dict(items=[{"item_code": self.prop, "qty": 1, "line_type": "Purchase"}]),
		]
		for case in cases:
			with self.assertRaises(frappe.ValidationError, msg=str(case)):
				self.enquiry(**case)

	def test_purchase_enquiries_can_be_switched_off(self):
		self.set(allow_purchase_enquiries=0)
		try:
			frappe.set_user("Guest")
			with self.assertRaises(frappe.ValidationError):
				self.enquiry(items=[{"item_code": self.panel, "qty": 1, "line_type": "Purchase"}])
		finally:
			frappe.set_user("Administrator")
			self.set(allow_purchase_enquiries=1)

	def test_honeypot_drops_bots_silently(self):
		frappe.set_user("Guest")
		before = frappe.db.count("Rental Website Enquiry")
		r = self.enquiry(website="http://spam.example")
		self.assertIsNone(r["name"])
		self.assertEqual(frappe.db.count("Rental Website Enquiry"), before)

	def test_logged_in_customer_enquiry_goes_to_the_customer(self):
		frappe.set_user(USER)
		r = self.enquiry(email=USER)
		self.assertTrue(r["customer"])
		frappe.set_user("Administrator")
		e = frappe.get_doc("Rental Website Enquiry", r["name"])
		self.assertEqual((e.customer, e.user, e.lead), (self.customer, USER, None))
		q = frappe.get_doc("Quotation", e.hire_quotation)
		self.assertEqual((q.quotation_to, q.party_name), ("Customer", self.customer))
		# the customer sees it in the portal; the other customer does not
		frappe.set_user(USER)
		self.assertIn(e.name, [x.name for x in cp.enquiries()["rows"]])
		frappe.set_user(OTHER_USER)
		self.assertNotIn(e.name, [x.name for x in cp.enquiries()["rows"]])
		status, html, _l = page("/hire/account", user=USER)
		self.assertIn(e.name, html)
		self.assertNotIn(e.name, page("/hire/account", user=OTHER_USER)[1])

	def test_contact_form(self):
		frappe.set_user("Guest")
		r = api.contact({"full_name": "Asker", "email": "asker@example.com", "message": "Do you hire climbing formwork?",
			"enquiry_type": "Long-term Contract", "subject": "Climbing formwork"})
		frappe.set_user("Administrator")
		e = frappe.get_doc("Rental Website Enquiry", r["name"])
		self.assertEqual(e.enquiry_type, "Long-term Contract")
		self.assertTrue(e.lead)
		self.assertFalse(e.hire_quotation)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.ValidationError):
			api.contact({"full_name": "Asker", "email": "asker@example.com", "message": ""})
		frappe.set_user("Administrator")

	def test_staff_can_make_quotations_later(self):
		e = frappe.get_doc({"doctype": "Rental Website Enquiry", "enquiry_type": "Rental Hire", "full_name": "Phone Caller", "email": "caller@example.com",
			"required_from": add_days(nowdate(), 5), "expected_return": add_days(nowdate(), 20), "items": [{"item_code": self.prop, "qty": 40}]}).insert()
		self.assertFalse(e.hire_quotation)
		made = e.make_quotations()
		e.reload()
		self.assertEqual(made, [e.hire_quotation])
		self.assertTrue(e.lead)

	# ------------------------------------------------------------------ quotation acceptance
	def test_customer_accepts_own_open_quotation_only(self):
		q = frappe.get_doc({"doctype": "Quotation", "quotation_to": "Customer", "party_name": self.customer, "company": self.company,
			"transaction_date": nowdate(), "valid_till": add_days(nowdate(), 10), "deal_type": "Material Hire",
			"nxg_required_from": nowdate(), "nxg_expected_return_date": add_days(nowdate(), 30),
			"items": [{"item_code": self.panel, "qty": 3, "rate": 90}]}).insert()
		q.submit()
		frappe.set_user(OTHER_USER)
		with self.assertRaises(frappe.PermissionError):
			cp.accept_quotation(q.name)
		frappe.set_user(USER)
		self.assertTrue(cp.quotation(q.name)["can_accept"])
		cp.accept_quotation(q.name)
		self.assertEqual(frappe.db.get_value("Quotation", q.name, "nxg_customer_accepted_by"), USER)
		self.assertFalse(cp.quotation(q.name)["can_accept"])
		with self.assertRaises(frappe.ValidationError):
			cp.accept_quotation(q.name)
		frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("Notification Log", {"document_type": "Quotation", "document_name": q.name}))

	def test_expired_quotation_cannot_be_accepted(self):
		q = frappe.get_doc({"doctype": "Quotation", "quotation_to": "Customer", "party_name": self.customer, "company": self.company,
			"transaction_date": add_days(nowdate(), -20), "valid_till": add_days(nowdate(), -1), "deal_type": "Material Sale",
			"items": [{"item_code": self.panel, "qty": 1, "rate": 90}]}).insert()
		q.submit()
		frappe.set_user(USER)
		self.assertFalse(cp.quotation(q.name)["can_accept"])
		with self.assertRaises(frappe.ValidationError):
			cp.accept_quotation(q.name)

	# ------------------------------------------------------------------ SEO, settings, templates
	def test_sitemap_lists_published_pages_only(self):
		status, xml, _l = page("/rental_sitemap.xml")
		self.assertEqual(status, 200)
		self.assertIn(self.url_of(self.panel), xml)
		self.assertIn("/hire/equipment</loc>", xml)
		self.assertNotIn("rwt-unpublished-item", xml)

	def test_home_page_and_robots_follow_settings(self):
		self.set(use_as_home_page=1)
		self.assertEqual(frappe.db.get_single_value("Website Settings", "home_page"), "hire")
		self.set(use_as_home_page=0)
		self.assertNotEqual(frappe.db.get_single_value("Website Settings", "home_page"), "hire")
		self.assertIn("/rental_sitemap.xml", frappe.db.get_single_value("Website Settings", "robots_txt") or "")

	def test_templates_change_layout_not_only_colours(self):
		s = frappe.get_single("Rental Website Settings")
		layouts = set()
		for name in TEMPLATES:
			s.template = name
			t = theme(s)
			layouts.add((t["attrs"]["data-header"], t["attrs"]["data-hero"], t["attrs"]["data-cards"], t["catalogue_view"]))
			self.assertIn("--rw-primary", t["css"])
		self.assertEqual(len(layouts), len(TEMPLATES))
		s.template = "Industrial Corporate"
		s.primary_color = "#123456"
		s.card_style = "Elevated"
		t = theme(s)
		self.assertIn("#123456", t["css"])
		self.assertEqual(t["attrs"]["data-cards"], "elevated")
		s.primary_color = "red;}body{display:none"
		with self.assertRaises(frappe.ValidationError):
			s.validate()

	def test_template_sections_load_in_order(self):
		s = frappe.get_single("Rental Website Settings")
		before = [r.as_dict() for r in s.sections]
		try:
			s.template = "Modern Minimal"
			s.load_template_sections()
			s.reload()
			self.assertEqual([r.section_type for r in s.sections], TEMPLATES["Modern Minimal"]["sections"])
		finally:
			s.reload()
			s.template = self.saved["template"] or "Industrial Corporate"
			s.set("sections", [{k: v for k, v in r.items() if k not in ("name", "idx", "parent")} for r in before])
			s.save()

	def test_sections_without_real_content_stay_hidden(self):
		# no testimonials or statistics are seeded, so those sections never render empty
		self.assertFalse(any(d["section_type"] in ("Testimonials", "Statistics") and d.get("content") for d in default_sections()))
		status, html, _l = page("/hire")
		self.assertNotIn("rw-quotes", html)
		self.assertNotIn("rw-stats", html)
