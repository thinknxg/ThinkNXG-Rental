"""Item + Rental Item Profile, and quotation rental rates and charges
(services/item_rental.py).

    bench --site <site> run-tests --module thinknxg_rental.tests.test_item_rental
"""
import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, nowdate

from thinknxg_rental.services import item_rental
from thinknxg_rental.tests.test_admin_portal import STAFF, _leaf, create, ensure_user, form, prepare, save

PROFILE = "Rental Item Profile"


def code(prefix="IR"):
	return f"{prefix}-{frappe.generate_hash(length=6).upper()}"


class TestItemRental(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		prepare(cls)
		cls.item_group = _leaf("Item Group")

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	# ------------------------------------------------------------------ helpers
	def item(self, stock=1, profile=None, **extra):
		"""An Item saved the way the desk form saves it: the Rental panel's values ride along as
		nxg_rental_profile (a JSON string, as the browser sends it)."""
		doc = frappe.get_doc(dict({"doctype": "Item", "item_code": code(), "item_group": self.item_group, "stock_uom": "Nos",
			"is_stock_item": stock}, **extra))
		if profile is not None:
			doc.nxg_rental_profile = json.dumps(profile)
		doc.insert()
		return doc

	def save_item(self, name, profile=None, **values):
		doc = frappe.get_doc("Item", name)
		doc.update(values)
		if profile is not None:
			doc.nxg_rental_profile = json.dumps(profile)
		doc.save()
		return doc

	# ------------------------------------------------------------------ Item creation
	def test_stock_item_without_profile(self):
		doc = self.item()
		self.assertFalse(frappe.db.exists(PROFILE, doc.name))

	def test_stock_item_with_profile_saved_together(self):
		doc = self.item(profile={"enabled": 1, "values": {"category": "Scaffolding", "monthly_rate": 30, "replacement_value": 900,
			"repair_charge": 120, "lost_charge": 800, "beyond_repair_charge": 650, "default_rate_basis": "Monthly"}})
		p = frappe.get_doc(PROFILE, doc.name)
		self.assertEqual(p.item, doc.name)
		self.assertEqual((p.repair_charge, p.lost_charge, p.beyond_repair_charge, p.monthly_rate), (120, 800, 650, 30))
		self.assertEqual((p.item_name, p.stock_uom, p.disabled), (doc.item_name, "Nos", 0))

	def test_profile_needs_maintain_stock(self):
		with self.assertRaises(frappe.ValidationError):
			self.item(stock=0, profile={"enabled": 1, "values": {"monthly_rate": 10}})
		# an existing active profile also keeps Maintain Stock from being switched off behind it
		doc = self.item(profile={"enabled": 1, "values": {"monthly_rate": 10}})
		with self.assertRaises(frappe.ValidationError):
			self.save_item(doc.name, is_stock_item=0)

	def test_failed_profile_rolls_back_the_item(self):
		frappe.db.savepoint("ir_item")
		name = code()
		doc = frappe.get_doc({"doctype": "Item", "item_code": name, "item_group": self.item_group, "stock_uom": "Nos", "is_stock_item": 1,
			"nxg_rental_profile": json.dumps({"enabled": 1, "values": {"repair_charge": -5}})})
		with self.assertRaises(frappe.ValidationError):
			doc.insert()
		frappe.db.rollback(save_point="ir_item")  # what the request does on any error
		self.assertFalse(frappe.db.exists("Item", name))
		self.assertFalse(frappe.db.exists(PROFILE, name))

	def test_existing_item_enable_then_update_then_switch_off(self):
		doc = self.item()
		self.save_item(doc.name, profile={"enabled": 1, "values": {"monthly_rate": 25, "lost_charge": 300}})
		self.assertEqual(frappe.db.get_value(PROFILE, doc.name, ["monthly_rate", "lost_charge", "disabled"]), (25, 300, 0))
		self.save_item(doc.name, profile={"enabled": 1, "values": {"lost_charge": 350, "beyond_repair_charge": 200}})
		self.assertEqual(frappe.db.get_value(PROFILE, doc.name, ["monthly_rate", "lost_charge", "beyond_repair_charge"]), (25, 350, 200))
		# switching off keeps the profile (and its history), disabled
		self.save_item(doc.name, profile={"enabled": 0, "values": {}})
		self.assertEqual(frappe.db.get_value(PROFILE, doc.name, "disabled"), 1)
		# a plain Item save without the panel touched leaves the profile alone
		self.save_item(doc.name, description="changed")
		self.assertEqual(frappe.db.get_value(PROFILE, doc.name, ["lost_charge", "disabled"]), (350, 1))

	def test_panel_cannot_set_the_link_or_other_items(self):
		doc = self.item(profile={"enabled": 1, "values": {"item": "SOMETHING-ELSE", "item_name": "Hacked", "monthly_rate": 5}})
		p = frappe.get_doc(PROFILE, doc.name)
		self.assertEqual((p.item, p.item_name), (doc.name, doc.item_name))

	def test_profile_needs_the_users_own_permission(self):
		user = ensure_user("ir.itemonly@example.com", ["Item Manager", "Stock User"])
		frappe.set_user(user)
		if frappe.has_permission(PROFILE, "create"):
			self.skipTest("Item Manager may create Rental Item Profiles on this site")
		self.assertFalse(item_rental.get_item_rental_profile()["can_create"])
		with self.assertRaises(frappe.PermissionError):
			self.item(profile={"enabled": 1, "values": {"monthly_rate": 5}})

	def test_profile_form_charges_and_validation(self):
		doc = self.item(profile={"enabled": 1, "values": {"monthly_rate": 10}})
		p = frappe.get_doc(PROFILE, doc.name)
		self.assertEqual((flt(p.lost_charge), flt(p.beyond_repair_charge)), (0, 0))  # empty on profiles made before
		p.update({"repair_charge": 50, "lost_charge": 400, "beyond_repair_charge": 300})
		p.save()
		self.assertEqual(frappe.db.get_value(PROFILE, doc.name, ["repair_charge", "lost_charge", "beyond_repair_charge"]), (50, 400, 300))
		for field in ("repair_charge", "lost_charge", "beyond_repair_charge"):
			p.reload()
			p.set(field, -1)
			with self.assertRaises(frappe.ValidationError, msg=field):
				p.save()

	def test_panel_lists_the_profile_fields(self):
		data = item_rental.get_item_rental_profile()
		names = [f["fieldname"] for f in data["fields"]]
		for field in ("repair_charge", "lost_charge", "beyond_repair_charge", "monthly_rate", "category"):
			self.assertIn(field, names)
		self.assertNotIn("item", names)
		self.assertFalse(data["exists"])

	# ------------------------------------------------------------------ Quotation rental charges
	def charged_item(self, repair, lost, beyond):
		return self.item(profile={"enabled": 1, "values": {"monthly_rate": 20, "repair_charge": repair, "lost_charge": lost,
			"beyond_repair_charge": beyond}}).name

	def quotation(self, items, submit=False):
		frappe.set_user(STAFF)
		boot = form("lead")
		boot["doc"].update(first_name="Charges", company_name=code("Charges Co"), deal_type="Material Hire", company=self.company)
		lead = save("lead", boot["doc"])
		key, q = create(form("lead", lead), "Create Quotation")
		q["doc"].update(items=items, valid_till=add_days(nowdate(), 30), nxg_required_from=nowdate(),
			nxg_expected_return_date=add_days(nowdate(), 30))
		return save("quotation", q["doc"], submit=submit)

	def row(self, item_code, **values):
		return dict({"item_code": item_code, "qty": 5, "rate": 20, "uom": "Nos", "nxg_rate_basis": "Monthly"}, **values)

	def charges(self, quotation):
		return [(r.item_code, flt(r.nxg_repair_charge), flt(r.nxg_lost_charge), flt(r.nxg_beyond_repair_charge))
			for r in frappe.get_doc("Quotation", quotation).items]

	def test_charges_api(self):
		item = self.charged_item(500, 4000, 2500)
		got = item_rental.get_item_rental_charges(item, self.company)
		self.assertEqual((got["nxg_repair_charge"], got["nxg_lost_charge"], got["nxg_beyond_repair_charge"], got["has_profile"]), (500, 4000, 2500, 1))
		plain = self.item().name
		self.assertEqual(item_rental.get_item_rental_charges(plain)["has_profile"], 0)
		self.assertEqual(item_rental.get_item_rental_charges(plain)["nxg_lost_charge"], 0)
		# a quotation in another currency gets them converted (company currency per unit of the quotation's)
		company_currency = frappe.get_cached_value("Company", self.company, "default_currency")
		other = "USD" if company_currency != "USD" else "EUR"
		self.assertEqual(item_rental.get_item_rental_charges(item, self.company, other, 2.5)["nxg_repair_charge"], 200)

	def test_rows_get_the_profile_charges_and_keep_their_own(self):
		a, b = self.charged_item(500, 4000, 2500), self.charged_item(80, 600, 300)
		plain = self.item().name
		quotation = self.quotation([self.row(a), self.row(b), self.row(plain)])
		self.assertEqual(self.charges(quotation), [(a, 500, 4000, 2500), (b, 80, 600, 300), (plain, 0, 0, 0)])
		# edit one row's charges on the quotation
		boot = form("quotation", quotation)
		boot["doc"]["items"][0].update(nxg_repair_charge=650, nxg_lost_charge=4200, nxg_beyond_repair_charge=0)
		save("quotation", boot["doc"])
		self.assertEqual(self.charges(quotation)[0], (a, 650, 4200, 0))
		self.assertEqual(self.charges(quotation)[1], (b, 80, 600, 300))  # other rows untouched
		# the profile keeps its own values
		self.assertEqual(frappe.db.get_value(PROFILE, a, ["repair_charge", "lost_charge", "beyond_repair_charge"]), (500, 4000, 2500))
		# reopening shows the quotation's values, and a later profile change does not reach saved rows
		frappe.set_user("Administrator")
		frappe.db.set_value(PROFILE, b, "repair_charge", 999)
		frappe.set_user(STAFF)
		boot = form("quotation", quotation)
		self.assertEqual([flt(r["nxg_repair_charge"]) for r in boot["doc"]["items"]], [650, 80, 0])
		save("quotation", boot["doc"])
		self.assertEqual(self.charges(quotation)[1], (b, 80, 600, 300))

	def test_desk_item_selection_fills_the_row(self):
		# ERPNext v16 picks an item on the server (Quotation.process_item_selection); the app's hook adds
		# the charges there, and picking another item replaces them with that item's defaults
		a, b = self.charged_item(500, 4000, 2500), self.charged_item(80, 600, 300)
		customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
		q = frappe.get_doc({"doctype": "Quotation", "quotation_to": "Customer", "party_name": customer, "company": self.company,
			"deal_type": "Material Hire", "items": [{"item_code": a, "qty": 1}]})
		q.set_missing_values()  # what the form has before any item is picked: currency, price list, rates
		q.run_method("process_item_selection", item_idx=1, reset_item_details=True, parentfield="items")
		row = q.items[0]
		self.assertEqual((row.nxg_repair_charge, row.nxg_lost_charge, row.nxg_beyond_repair_charge, row.nxg_charges_set), (500, 4000, 2500, 1))
		row.item_code = b
		q.run_method("process_item_selection", item_idx=1, reset_item_details=True, parentfield="items")
		self.assertEqual((row.nxg_repair_charge, row.nxg_lost_charge, row.nxg_beyond_repair_charge), (80, 600, 300))
		# recalculations of the same row (not a new item) leave edited charges alone
		row.nxg_repair_charge = 99
		q.run_method("process_item_selection", item_idx=1, reset_item_details=False, parentfield="items")
		self.assertEqual(row.nxg_repair_charge, 99)

	# ------------------------------------------------------------------ rates and rate basis
	def rated_item(self, daily, weekly, monthly, basis="Monthly"):
		return self.item(profile={"enabled": 1, "values": {"daily_rate": daily, "weekly_rate": weekly, "monthly_rate": monthly,
			"default_rate_basis": basis}}).name

	def rows(self, quotation):
		return [(r.nxg_rate_basis, flt(r.rate), flt(r.nxg_daily_rate), flt(r.nxg_weekly_rate), flt(r.nxg_monthly_rate))
			for r in frappe.get_doc("Quotation", quotation).items]

	def test_rates_api_uses_profile_rates_and_default_basis(self):
		item = self.rated_item(10, 60, 200, "Weekly")
		got = item_rental.get_item_rental_defaults(item, self.company)
		self.assertEqual((got["nxg_daily_rate"], got["nxg_weekly_rate"], got["nxg_monthly_rate"]), (10, 60, 200))
		self.assertEqual((got["nxg_rate_basis"], got["rate"]), ("Weekly", 60))
		# no profile: zero rates, the quotation's basis kept, no Rate proposed
		plain = item_rental.get_item_rental_defaults(self.item().name, self.company, rate_basis="Daily")
		self.assertEqual((plain["nxg_daily_rate"], plain["nxg_rate_basis"], plain.get("rate")), (0, "Daily", None))
		# other deals get the charges only
		self.assertNotIn("nxg_daily_rate", item_rental.get_item_rental_defaults(item, self.company, deal_type="Material Sale"))

	def test_rate_card_comes_before_the_profile(self):
		item = self.rated_item(10, 60, 200)
		customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
		frappe.get_doc({"doctype": "Rental Rate Card", "title": code("Card"), "customer": customer,
			"items": [{"item_code": item, "daily_rate": 8, "weekly_rate": 50, "monthly_rate": 170}]}).insert()
		got = item_rental.get_item_rental_defaults(item, self.company, customer=customer, quotation_to="Customer")
		self.assertEqual((got["nxg_daily_rate"], got["nxg_monthly_rate"], got["rate"]), (8, 170, 170))
		# a quotation to a Lead or Prospect has no customer card: the profile's rates
		got = item_rental.get_item_rental_defaults(item, self.company, customer=customer, quotation_to="Prospect")
		self.assertEqual(got["rate"], 200)

	def test_picked_item_fills_rates_basis_and_rate(self):
		item = self.rated_item(10, 60, 200, "Daily")
		customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
		frappe.db.delete("Rental Rate Card Item", {"item_code": item})
		q = frappe.get_doc({"doctype": "Quotation", "quotation_to": "Customer", "party_name": customer, "company": self.company,
			"deal_type": "Material Hire", "nxg_default_rate_basis": "Monthly", "items": [{"item_code": item, "qty": 2}]})
		q.set_missing_values()
		q.run_method("process_item_selection", item_idx=1, reset_item_details=True, parentfield="items")
		row = q.items[0]
		self.assertEqual((row.nxg_rate_basis, row.rate, row.nxg_daily_rate, row.nxg_weekly_rate, row.nxg_monthly_rate), ("Daily", 10, 10, 60, 200))
		self.assertEqual(flt(row.amount), 20)

	def test_rates_and_basis_stay_editable(self):
		item = self.rated_item(10, 60, 200, "Monthly")
		quotation = self.quotation([self.row(item, rate=0, nxg_rate_basis="Monthly")])
		self.assertEqual(self.rows(quotation), [("Monthly", 200, 10, 60, 200)])
		frappe.set_user(STAFF)
		# switch the basis: Rate takes that basis's rate
		boot = form("quotation", quotation)
		boot["doc"]["items"][0]["nxg_rate_basis"] = "Weekly"
		save("quotation", boot["doc"])
		self.assertEqual(self.rows(quotation), [("Weekly", 60, 10, 60, 200)])
		# edit the rate of the row's basis: Rate follows
		boot = form("quotation", quotation)
		boot["doc"]["items"][0]["nxg_weekly_rate"] = 55
		save("quotation", boot["doc"])
		self.assertEqual(self.rows(quotation), [("Weekly", 55, 10, 55, 200)])
		# type a Rate: it becomes this basis's rate; the other rates stay
		boot = form("quotation", quotation)
		boot["doc"]["items"][0]["rate"] = 52
		save("quotation", boot["doc"])
		self.assertEqual(self.rows(quotation), [("Weekly", 52, 10, 52, 200)])
		# editing another basis's rate leaves Rate alone
		boot = form("quotation", quotation)
		boot["doc"]["items"][0]["nxg_monthly_rate"] = 190
		save("quotation", boot["doc"])
		self.assertEqual(self.rows(quotation), [("Weekly", 52, 10, 52, 190)])
		# the hire amounts follow Rate, and the profile keeps its rates
		row = frappe.get_doc("Quotation", quotation).items[0]
		self.assertEqual(flt(row.nxg_rate_basis_amount), flt(row.qty) * 52)
		self.assertEqual(frappe.db.get_value(PROFILE, item, ["daily_rate", "weekly_rate", "monthly_rate", "default_rate_basis"]), (10, 60, 200, "Monthly"))

	def test_rate_given_with_the_row_is_kept(self):
		item = self.rated_item(10, 60, 200, "Monthly")
		quotation = self.quotation([self.row(item, rate=180, nxg_rate_basis="Monthly")])
		self.assertEqual(self.rows(quotation), [("Monthly", 180, 10, 60, 180)])

	def test_item_without_profile_keeps_a_typed_rate(self):
		plain = self.item().name
		quotation = self.quotation([self.row(plain, rate=33, nxg_rate_basis="Daily")])
		self.assertEqual(self.rows(quotation), [("Daily", 33, 33, 0, 0)])

	def test_negative_rate_is_refused(self):
		item = self.rated_item(10, 60, 200)
		with self.assertRaises(frappe.ValidationError):
			self.quotation([self.row(item, nxg_daily_rate=-1, nxg_charges_set=1)])

	def test_values_from_the_form_are_kept(self):
		# the form fetched the defaults and the user changed them before the first save
		a = self.charged_item(500, 4000, 2500)
		quotation = self.quotation([self.row(a, nxg_repair_charge=650, nxg_lost_charge=4000, nxg_beyond_repair_charge=2500, nxg_charges_set=1),
			self.row(a, nxg_repair_charge=0, nxg_lost_charge=0, nxg_beyond_repair_charge=0, nxg_charges_set=1)])
		self.assertEqual(self.charges(quotation), [(a, 650, 4000, 2500), (a, 0, 0, 0)])

	def test_negative_row_charge_is_refused(self):
		a = self.charged_item(500, 4000, 2500)
		with self.assertRaises(frappe.ValidationError):
			self.quotation([self.row(a, nxg_lost_charge=-1, nxg_charges_set=1)])

	def test_quotation_still_flows_to_hire_order(self):
		a = self.charged_item(500, 4000, 2500)
		quotation = self.quotation([self.row(a)], submit=True)
		self.assertEqual(frappe.db.get_value("Quotation", quotation, "docstatus"), 1)
		key, site = create(form("quotation", quotation), "Create Rental Site")
		site["doc"]["site_name"] = code("Charge Site")
		site_name = save("rental-site", site["doc"])
		key, ho = create(form("rental-site", site_name), "Create Hire Order")
		self.assertEqual([r["item_code"] for r in ho["doc"]["items"]], [a])

	def test_portal_columns_and_defaults(self):
		frappe.set_user(STAFF)
		boot = form("quotation")
		items = next(t for t in boot["tables"] if t["fieldname"] == "items")
		cols = {c["fieldname"]: c for c in items["columns"]}
		for field in item_rental.CHARGES:
			self.assertIn(field, cols)
			self.assertEqual(cols[field]["marks"], "nxg_charges_set")
		self.assertEqual(cols["item_code"]["defaults"]["method"], "thinknxg_rental.services.item_rental.get_item_rental_defaults")
		for field in item_rental.RATES.values():
			self.assertIn(field, cols)
		self.assertEqual(cols["nxg_rate_basis"]["copies"]["from"], item_rental.RATES)

	def test_custom_fields_once(self):
		from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

		from thinknxg_rental.services.setup import get_custom_fields

		create_custom_fields(get_custom_fields(), ignore_validate=True)
		create_custom_fields(get_custom_fields(), ignore_validate=True)
		self.assertFalse(frappe.db.exists("Custom Field", {"dt": "Item", "fieldname": "nxg_rental_classification"}))
		for doctype, fields in (("Item", ["nxg_rental_profile_html"]),
				("Quotation Item", list(item_rental.CHARGES) + ["nxg_charges_set"])):
			for field in fields:
				self.assertEqual(frappe.db.count("Custom Field", {"dt": doctype, "fieldname": field}), 1, f"{doctype}.{field}")
		meta = frappe.get_meta(PROFILE)
		for field in ("repair_charge", "lost_charge", "beyond_repair_charge"):
			self.assertEqual([f.fieldname for f in meta.fields].count(field), 1)
