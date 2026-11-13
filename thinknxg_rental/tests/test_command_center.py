"""The Command Center (/rental/admin): its API, its permissions and its agreement with the reports.

Every API call is made as a real user with real roles, so the checks are the ones a browser meets.
Run on a test site with ERPNext and this app, after the setup wizard:
    bench --site <site> run-tests --module thinknxg_rental.tests.test_command_center
"""
import re

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from thinknxg_rental.command_center import api
from thinknxg_rental.command_center import registry as R
from thinknxg_rental.portal.admin import get_stock_rows
from thinknxg_rental.tests.test_admin_portal import ensure_user

RENTAL_USER = "cc.test.user@example.com"
RENTAL_MANAGER = "cc.test.manager@example.com"
SYSTEM_MANAGER = "cc.test.sysman@example.com"
CUSTOMER = "cc.test.customer@example.com"


def as_user(user):
	frappe.set_user(user)
	frappe.local.cache = {}
	frappe.clear_cache(user=user)


class TestCommandCenter(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_user(RENTAL_USER, ["Rental User"])
		ensure_user(RENTAL_MANAGER, ["Rental Manager"])
		ensure_user(SYSTEM_MANAGER, ["System Manager", "Rental Manager"])
		if not frappe.db.exists("User", CUSTOMER):
			frappe.get_doc({"doctype": "User", "email": CUSTOMER, "first_name": "Portal", "user_type": "Website User",
				"send_welcome_email": 0}).insert(ignore_permissions=True)
		frappe.get_doc("User", CUSTOMER).add_roles("Customer")

	def tearDown(self):
		frappe.set_user("Administrator")

	# ------------------------------------------------------------------ who may use it
	def test_outsiders_are_refused_everywhere(self):
		calls = [
			lambda: api.boot(), lambda: api.dashboard("month"), lambda: api.list_view("contracts"),
			lambda: api.search("RC"), lambda: api.inventory(), lambda: api.billing_center(), lambda: api.outstanding(),
			lambda: api.requests(), lambda: api.users_roles(), lambda: api.form("rental-contract"),
			lambda: api.bill_contract("RC-NONE"), lambda: api.export_list("contracts"), lambda: api.supplier_position(),
		]
		for user in ("Guest", CUSTOMER):
			as_user(user)
			for call in calls:
				with self.assertRaises(frappe.PermissionError, msg=user):
					call()

	def test_staff_page_redirects_guests_and_refuses_customers(self):
		from thinknxg_rental.www.rental.admin import index

		frappe.local.request = None
		as_user("Guest")
		with self.assertRaises(frappe.Redirect):
			index.get_context(frappe._dict())
		as_user(CUSTOMER)
		with self.assertRaises(frappe.PermissionError):
			index.get_context(frappe._dict())
		as_user(RENTAL_USER)
		context = frappe._dict()
		index.get_context(context)
		self.assertTrue(context.csrf_token)
		self.assertEqual(context.cc_boot["user"]["name"], RENTAL_USER)

	def test_users_and_roles_are_for_system_managers_only(self):
		for user in (RENTAL_USER, RENTAL_MANAGER):
			as_user(user)
			with self.assertRaises(frappe.PermissionError):
				api.users_roles()
			self.assertNotIn("users", [i["key"] for g in api.boot()["nav"] for i in g["items"]])
		as_user(SYSTEM_MANAGER)
		users = {u.name: u for u in api.users_roles()}
		self.assertIn("Rental User", users[RENTAL_USER].roles)
		self.assertIn("users", [i["key"] for g in api.boot()["nav"] for i in g["items"]])

	def test_sidebar_only_lists_what_the_user_may_open(self):
		as_user(RENTAL_USER)
		for group in api.boot()["nav"]:
			for item in group["items"]:
				doctype = R.view_doctype(item["key"])
				if item["kind"] == "list" and doctype:
					self.assertTrue(frappe.has_permission(doctype, "read"), item["key"])

	def test_a_list_the_user_cannot_read_is_refused_on_the_server(self):
		as_user(RENTAL_USER)
		hidden = [k for k, v in R.VIEWS.items() if v["kind"] in ("entry", "doctype") and not frappe.has_permission(R.view_doctype(k), "read")]
		for key in hidden:
			with self.assertRaises(frappe.PermissionError, msg=key):
				api.list_view(key)

	# ------------------------------------------------------------------ lists
	def test_list_counts_pages_and_ignores_unknown_filters(self):
		as_user(RENTAL_MANAGER)
		everything = api.list_view("contracts", tab=4, page_size=20)
		total = frappe.db.count("Rental Contract")
		self.assertEqual(everything["total"], total)
		self.assertLessEqual(len(everything["rows"]), 20)
		# a field or operator the view does not offer is dropped, not passed to the query
		odd = api.list_view("contracts", tab=4, filters={"owner": "nobody", "name": ["like", "%"], "docstatus": "9"})
		self.assertEqual(odd["total"], total)
		# the live tab is the same set the desk filter gives
		live = api.list_view("contracts", tab=0)
		self.assertEqual(live["total"], frappe.db.count("Rental Contract", {"docstatus": 1, "status": ["in", R.LIVE]}))
		# sorting by a column it does not show falls back to Last modified
		self.assertEqual(api.list_view("contracts", sort="owner asc")["sort"]["field"], "modified")

	def test_export_needs_export_permission(self):
		as_user(RENTAL_MANAGER)
		out = api.export_list("contracts", tab=4)
		self.assertTrue(out["content"].splitlines()[0].startswith("ID"))
		self.assertEqual(len(out["content"].strip().splitlines()) - 1, frappe.db.count("Rental Contract"))

	# ------------------------------------------------------------------ the dashboard agrees with the reports
	def test_dashboard_stock_figures_match_rental_stock_position(self):
		as_user(RENTAL_MANAGER)
		frappe.cache.delete_keys("thinknxg_rental:cc_dashboard:")
		d = api.dashboard("month")
		kpi = {k["key"]: k["value"] for k in d["kpis"]}
		rows = get_stock_rows()
		total = lambda key: sum(flt(r[key]) for r in rows)  # noqa: E731
		self.assertAlmostEqual(kpi["rentable"], total("rentable"))
		self.assertAlmostEqual(kpi["available"], total("available_qty"))
		self.assertAlmostEqual(kpi["reserved"], total("reserved_qty"))
		self.assertAlmostEqual(kpi["on_hire"], total("at_site_own") + total("at_site_cross_hire"))
		self.assertAlmostEqual(kpi["contracts"], frappe.db.count("Rental Contract", {"docstatus": 1, "status": ["in", ["Active", "On Hire"]]}))
		# the work queue, KPIs and charts are worked out for this user only
		self.assertTrue(all(q["route"] for q in d["queue"]))

	def test_dashboard_cache_is_per_user(self):
		as_user(RENTAL_MANAGER)
		frappe.cache.delete_keys("thinknxg_rental:cc_dashboard:")
		api.dashboard("month")
		keys = [k.decode() if isinstance(k, bytes) else k for k in frappe.cache.get_keys("thinknxg_rental:cc_dashboard:")]
		self.assertTrue(keys and all(RENTAL_MANAGER in k for k in keys))

	def test_unbilled_kpi_is_the_billing_engine_figure(self):
		as_user(RENTAL_MANAGER)
		frappe.cache.delete_keys("thinknxg_rental:cc_dashboard:")
		kpi = {k["key"]: k for k in api.dashboard("month")["kpis"]}
		b = api.billing_center()
		self.assertAlmostEqual(flt(kpi["unbilled"]["value"]), flt(b["accrued_total"]) + flt(b["jcr_pending_total"]))

	# ------------------------------------------------------------------ documents and actions
	def test_form_search_and_timeline(self):
		name = frappe.db.get_value("Rental Contract", {"docstatus": 1})
		if not name:
			self.skipTest("no submitted rental contract on this site")
		as_user(RENTAL_USER)
		boot = api.form("rental-contract", name)
		self.assertEqual(boot["name"], name)
		self.assertEqual(boot["route"], "contracts")
		self.assertIn("timeline", boot)
		hits = api.search(name)
		self.assertIn({"route": f"contracts/{name}"}.items() <= hits[0].items(), [True])
		api.add_comment("Rental Contract", name, "Checked <b>today</b>")
		comment = api.form("rental-contract", name)["timeline"][0]
		self.assertEqual(comment["kind"], "comment")
		self.assertIn("&lt;b&gt;", comment["content"])  # what staff type is shown as text, never as markup

	def test_cancel_needs_cancel_permission(self):
		name = frappe.db.get_value("Rental Contract", {"docstatus": 1})
		if not name:
			self.skipTest("no submitted rental contract on this site")
		as_user(RENTAL_USER)
		if frappe.has_permission("Rental Contract", "cancel"):
			self.skipTest("Rental User may cancel on this site")
		with self.assertRaises(frappe.PermissionError):
			api.cancel_document("Rental Contract", name)
		self.assertEqual(frappe.db.get_value("Rental Contract", name, "docstatus"), 1)

	def test_assign_puts_the_document_in_my_tasks(self):
		name = frappe.db.get_value("Rental Contract", {"docstatus": 1})
		if not name:
			self.skipTest("no submitted rental contract on this site")
		as_user(RENTAL_MANAGER)
		api.assign("Rental Contract", name, RENTAL_USER)
		with self.assertRaises(frappe.ValidationError):
			api.assign("Rental Contract", name, CUSTOMER)  # only rental staff can be assigned
		as_user(RENTAL_USER)
		tasks = api.my_tasks()
		task = next(t for t in tasks if t.reference_name == name)
		self.assertEqual(task.target, {"route": f"contracts/{name}"})
		api.close_task(task.name)
		as_user(RENTAL_MANAGER)
		with self.assertRaises(frappe.PermissionError):
			api.close_task(task.name)  # someone else's task

	# ------------------------------------------------------------------ the map of the app
	def test_every_route_and_icon_exists(self):
		as_user("Administrator")
		sprite = open(frappe.get_app_path("frappe", "public", "icons", "lucide.svg")).read()
		icons = set(re.findall(r'id="icon-([^"]+)"', sprite))
		for _g, _l, items in R.NAV:
			for key, _label, icon, kind in items:
				self.assertIn(icon, icons, key)
				if kind == "list":
					self.assertIn(key, R.VIEWS, key)
				if kind == "report":
					self.assertTrue(frappe.db.exists("Report", R.REPORTS[key]), key)
		types = R.entry_types()
		for key, view in R.VIEWS.items():
			if view["kind"] == "entry":
				self.assertIn(view["entry"], types, key)
			if view["kind"] in ("entry", "doctype"):
				meta = frappe.get_meta(R.view_doctype(key))
				for field, _label in view.get("columns", []):
					self.assertTrue(field == "name" or meta.has_field(field), f"{key}: {field}")
		for entry, route in R.QUICK_CREATE:
			self.assertEqual(R.entry_route(entry), route)
		for name, filters in R.REPORT_FILTERS.items():
			self.assertIn(name, R.REPORTS.values())
