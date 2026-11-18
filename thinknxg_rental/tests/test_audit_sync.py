"""Repository audit (v2.6.1): desk features carried to the Command Center and the customer portal, server-side
quotation costs, menus and thinkNXG branding on the framework's screens.

    bench --site <site> run-tests --module thinknxg_rental.tests.test_audit_sync
"""
import json

import frappe
from frappe.utils import flt, nowdate

from thinknxg_rental.command_center import registry
from thinknxg_rental.portal import customer as cp
from thinknxg_rental.portal import entry as E
from thinknxg_rental.services import branding, desk_menu
from thinknxg_rental.tests.test_admin_portal import STAFF, create, ensure_item, form, save
from thinknxg_rental.tests import test_excess_material as tem


class TestAuditSync(tem.TestExcessMaterial):
	# the parent's tests run in their own class
	for _name in [n for n in dir(tem.TestExcessMaterial) if n.startswith("test_")]:
		locals()[_name] = None
	del _name

	# ------------------------------------------------------------------ Command Center: excess material
	def test_portal_off_hire_received_splits_into_excess(self):
		"""The Command Center's off-hire form takes Received, and the server splits it as on the desk."""
		item = self.item()
		rc = self.contract([(item, 10)])
		self.deliver(rc, [(item, 10)])
		frappe.set_user(STAFF)
		boot = form("off-hire-note", rental_contract=rc)
		columns = [c["fieldname"] for c in boot["tables"][0]["columns"]]
		self.assertTrue({"received_qty", "excess_qty"} <= set(columns))
		doc = boot["doc"]
		doc.update(off_hire_date=nowdate(), return_date=nowdate())
		doc["items"] = [{"item_code": item, "ownership": "Own", "received_qty": 15}]
		name = save("off-hire-note", doc, submit=True)
		frappe.set_user("Administrator")
		row = frappe.get_doc("Hire Off-Hire Note", name).items[0]
		self.assertEqual((flt(row.returned_qty), flt(row.excess_qty)), (10, 5))
		reg = self.register(frappe._dict(name=name), item)
		self.assertEqual(flt(reg.available_qty), 5)
		# the note's form offers the excess documents and lists its register
		frappe.set_user(STAFF)
		boot = form("off-hire-note", name)
		labels = [a["label"] for a in boot["next"]]
		self.assertTrue({"Create Excess Material Return", "Create Dismantling Entry", "Create Excess Material Abandonment"} <= set(labels))
		related = {r["label"]: r for r in boot.get("related") or []}
		self.assertIn(reg.name, [x["name"] for x in related["Excess material"]["rows"]])

	def test_portal_excess_documents_save_through_their_controllers(self):
		s = self.scenario()
		frappe.set_user(STAFF)
		boot = form("off-hire-note", s.note.name)
		# hand 2 back to the customer
		key, rn = create(boot, "Create Excess Material Return")
		self.assertEqual(key, "excess-return-note")
		rn["doc"]["items"][0]["return_qty"] = 2
		rn_name = save(key, rn["doc"], submit=True)
		# settle the 3 outstanding A against 3 B
		key, de = create(boot, "Create Dismantling Entry")
		self.assertEqual(key, "dismantling-entry")
		self.assertIn(s.a, [r["item_code"] for r in de["doc"]["outstanding_items"]])
		de["doc"]["adjustments"] = [{"outstanding_item": s.a, "adjustment_qty": 3, "excess_register": s.reg.name, "excess_qty_used": 3}]
		de_name = save(key, de["doc"], submit=True)
		frappe.set_user("Administrator")
		s.reg.reload()
		self.assertEqual((flt(s.reg.returned_to_customer_qty), flt(s.reg.adjusted_qty), flt(s.reg.available_qty)), (2, 3, 0))
		self.assertEqual(frappe.db.get_value("Excess Material Return Note", rn_name, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Dismantling Entry", de_name, "approved_by"), STAFF)
		# and convert the adjusted excess into rental stock
		frappe.set_user(STAFF)
		cv = form("excess-conversion")
		cv["doc"].update(customer=s.note.customer, company=self.company, posting_date=nowdate(), source_warehouse=self.excess_wh,
			target_warehouse=self.yard, conversion_type="Convert to Existing Rental Item")
		cv["doc"]["items"] = [{"excess_register": s.reg.name, "conversion_qty": 3, "target_item_code": s.b, "valuation_basis": "Manual Rate",
			"valuation_rate": 40}]
		save("excess-conversion", cv["doc"], submit=True)
		frappe.set_user("Administrator")
		s.reg.reload()
		self.assertEqual((flt(s.reg.converted_qty), flt(s.reg.convertible_qty)), (3, 0))

	def test_portal_abandonment_needs_a_manager(self):
		s = self.scenario()
		frappe.set_user(STAFF)  # a Rental Manager
		key, ab = create(form("off-hire-note", s.note.name), "Create Excess Material Abandonment")
		ab["doc"].update(abandonment_basis="Customer confirmed in writing", reason="Not collecting the extra props")
		save(key, ab["doc"], submit=True)
		frappe.set_user("Administrator")
		s.reg.reload()
		self.assertEqual((flt(s.reg.abandoned_qty), flt(s.reg.available_qty)), (5, 0))

	def test_contract_offers_dismantling_entry(self):
		s = self.scenario()
		frappe.set_user(STAFF)
		boot = form("rental-contract", s.rc)
		self.assertIn("Dismantling Entry", [a["label"] for a in boot["next"]])

	# ------------------------------------------------------------------ Lead / Quotation parity with the desk
	def test_lead_and_quotation_fields_match_the_desk(self):
		specs = {f["fieldname"]: f for f in E.get_form_specs(E.ENTRY_TYPES["lead"])[0]}
		for field in ("nxg_rental_site_profile", "nxg_project_contact_name", "nxg_project_contact_email", "lead_owner",
				"nxg_tender_assignee", "nxg_tender_final_submission_date", "nxg_tender_finalization_date"):
			self.assertIn(field, specs)
		self.assertTrue(specs["project"].get("ro"))  # the desk hides it; made by the Rental Site
		header, tables, _t = E.get_form_specs(E.ENTRY_TYPES["quotation"])
		self.assertIn("nxg_rental_site_profile", [f["fieldname"] for f in header])
		items = [c["fieldname"] for c in tables[0]["columns"]]
		self.assertTrue({"nxg_weight", "nxg_purchase_cost", "nxg_total_cost"} <= set(items))
		site_action = next(a for a in E.ENTRY_TYPES["quotation"]["next"] if a["label"] == "Create Rental Site")
		self.assertEqual(site_action["when"]["docstatus"], [1])  # only after submit, as on the desk

	def test_rental_site_takes_the_site_profile_name(self):
		item = self.item()
		rc = self.contract([(item, 1)])
		quotation = frappe.db.get_value("Hire Order", frappe.db.get_value("Rental Contract", rc, "source_document"), "quotation")
		profile = f"North Tower {tem.tag()}"
		frappe.db.set_value("Quotation", quotation, "nxg_rental_site_profile", profile)
		site = E.make_site_from_quotation(quotation)
		self.assertEqual(site.site_name, profile)

	def test_quotation_costs_on_the_server(self):
		"""Weight, Purchase Cost and Total Cost no longer depend on the desk form."""
		item = ensure_item(f"AS-{tem.tag()}", "Audit Sale Item", weight_per_unit=2.5, valuation_rate=12)
		customer = frappe.get_all("Customer", pluck="name", limit=1)[0]
		q = frappe.get_doc({"doctype": "Quotation", "quotation_to": "Customer", "party_name": customer, "company": self.company,
			"deal_type": "Material Sale", "transaction_date": nowdate(), "items": [{"item_code": item, "qty": 4, "rate": 20}]})
		q.insert()
		row = q.items[0]
		self.assertEqual((flt(row.nxg_weight), flt(row.nxg_purchase_cost), flt(row.nxg_total_cost)), (2.5, 12, 48))
		row.nxg_purchase_cost = 10  # a cost typed by the user is kept
		row.qty = 5
		q.save()
		self.assertEqual((flt(q.items[0].nxg_purchase_cost), flt(q.items[0].nxg_total_cost)), (10, 50))

	# ------------------------------------------------------------------ customer portal
	def test_customer_sees_extra_material_on_the_return(self):
		s = self.scenario()
		self.dismantle(s.rc, [(s.a, 3, s.reg, 3)])
		self.return_note([s.reg], qty=1)
		r = cp.return_note(s.note.name, customer=s.note.customer)
		self.assertEqual([(x["item_code"], x["received"], x["returned"], x["settled"], x["held"]) for x in r["excess"]], [(s.b, 5, 1, 3, 1)])
		self.assertEqual(next(i for i in r["items"] if i["item_code"] == s.b)["excess"], 5)

	# ------------------------------------------------------------------ navigation
	def test_menus_list_the_new_documents(self):
		menu = desk_menu.get_menu()
		docs = {i.get("doctype") for g in menu["groups"] for i in g["items"]}
		for dt in ("Rental Website Enquiry", "Rental Website Settings", "Excess Material Register", "Dismantling Entry",
				"Excess Material Abandonment", "Excess Material Conversion Entry", "Excess Material Return Note"):
			self.assertIn(dt, docs)
		frappe.set_user(STAFF)
		nav = {i["key"] for g in registry.get_nav() for i in g["items"]}
		for key in ("website-enquiries", "excess/register", "excess/returns", "excess/dismantling", "excess/abandonment",
				"excess/conversion", "reports/project-reconciliation", "reports/outstanding-materials"):
			self.assertIn(key, nav)
		self.assertEqual(registry.entry_route("dismantling-entry"), "excess/dismantling")

	# ------------------------------------------------------------------ branding
	def test_branding_replaces_only_framework_defaults(self):
		frappe.db.set_single_value("System Settings", "app_name", "Frappe")
		branding.apply()
		self.assertEqual(frappe.db.get_single_value("System Settings", "app_name"), "thinkNXG")
		self.assertEqual(frappe.db.get_default("app_name"), "thinkNXG")  # what the desk reads
		frappe.db.set_single_value("System Settings", "app_name", "Acme Formwork")  # an administrator's own choice stays
		branding.apply()
		self.assertEqual(frappe.db.get_single_value("System Settings", "app_name"), "Acme Formwork")
		nav = frappe.get_single("Navbar Settings")
		visible = [r.route for r in nav.help_dropdown if not r.hidden]
		self.assertFalse([r for r in visible if "frappe.io" in (r or "")])
		self.assertIn("https://thinknxg.com/thinkdesk", [r.route for r in nav.help_dropdown])
		self.assertTrue(nav.app_logo or frappe.db.get_single_value("Website Settings", "app_logo"))

	def test_web_pages_use_thinknxg_favicon_and_footer(self):
		from frappe.website.doctype.website_settings.website_settings import get_website_settings

		ctx = get_website_settings()
		self.assertEqual(ctx["favicon"], "/assets/thinknxg_rental/images/logo.svg")
		self.assertIn("thinkNXG", ctx["footer_powered"])
		self.assertNotIn("ERPNext", json.dumps({k: ctx.get(k) for k in ("favicon", "splash_image", "footer_powered")}))

	def test_no_old_brand_in_user_facing_strings(self):
		"""Visible names (descriptions, labels, translated strings) of this app say thinkNXG / thinkNXG ERP."""
		from thinknxg_rental import hooks

		self.assertNotIn("ERPNext", hooks.app_description)
		for doctype in frappe.get_all("DocType", filters={"module": "thinkNXG Rental"}, pluck="name"):
			meta = frappe.get_meta(doctype)
			texts = [meta.description or ""] + [f"{f.label or ''} {f.description or ''}" for f in meta.fields]
			for t in texts:
				self.assertNotRegex(t, r"\b(Frappe|ERPNext)\b", f"{doctype}: {t}")
