"""Project Title and the Project link across Lead -> Quotation -> Rental Site -> Hire Order /
Hire Order Contract -> Rental Contract (services/project_link.py).

The rule under test throughout: a Project link is only filled when it is empty, never replaced.
Flows run through the portal's server methods as the Rental Manager of test_admin_portal; the desk
paths (ERPNext's own Lead -> Quotation mapper, a Rental Site saved in the desk) are checked directly.

    bench --site <site> run-tests --module thinknxg_rental.tests.test_project_link
"""
import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from thinknxg_rental.services import project_link
from thinknxg_rental.tests.test_admin_portal import STAFF, create, form, prepare, save


def unique(prefix):
	return f"{prefix} {frappe.generate_hash(length=6)}"


class TestProjectLink(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# the same company, stock, items and Rental Manager as the admin portal tests
		prepare(cls)

	def setUp(self):
		frappe.set_user(STAFF)

	def tearDown(self):
		frappe.set_user("Administrator")

	# ------------------------------------------------------------------ helpers
	def lead(self, title=None, project=None, deal_type="Material Hire"):
		boot = form("lead")
		boot["doc"].update(first_name=unique("PL"), company_name=unique("PL Co"), deal_type=deal_type, company=self.company,
			project_title=title, project=project)
		return save("lead", boot["doc"])

	def quotation(self, lead_name, submit=True, **values):
		key, q = create(form("lead", lead_name), "Create Quotation")
		q["doc"].update(values)
		q["doc"].update(items=[{"item_code": self.tube, "qty": 10, "rate": 4, "uom": "Nos", "nxg_rate_basis": "Daily"}],
			valid_till=add_days(nowdate(), 30), nxg_required_from=nowdate(), nxg_expected_return_date=add_days(nowdate(), 30))
		return save("quotation", q["doc"], submit=submit), q

	def site(self, quotation, **values):
		key, site = create(form("quotation", quotation), "Create Rental Site")
		site["doc"]["site_name"] = unique("PL Site")
		site["doc"].update(values)
		return save("rental-site", site["doc"])

	def desk_site(self, quotation):
		"""Quotation > Create > Rental Site in the desk: make the Customer, then save a site with the quotation set."""
		from thinknxg_rental.services.deal_flow import make_customer_from_quotation

		customer = make_customer_from_quotation(quotation)
		return frappe.get_doc({"doctype": "Rental Site", "site_name": unique("Desk"), "customer": customer, "company": self.company,
			"nxg_quotation": quotation}).insert()

	def project(self, name=None, customer=None):
		frappe.set_user("Administrator")
		doc = frappe.get_doc({"doctype": "Project", "project_name": name or unique("PL Project"), "company": self.company, "customer": customer}).insert()
		frappe.set_user(STAFF)
		return doc.name

	def count(self, title):
		return frappe.db.count("Project", {"project_name": title})

	# ------------------------------------------------------------------ Lead -> Quotation
	def test_lead_title_goes_to_the_quotation(self):
		title = unique("Marina Tower")
		lead = self.lead(title)
		_q, boot = self.quotation(lead, submit=False)
		self.assertEqual(boot["doc"]["project_title"], title)
		self.assertFalse(boot["doc"].get("project"))

	def test_lead_project_goes_to_the_quotation(self):
		project = self.project()
		lead = self.lead(unique("Title"), project)
		_q, boot = self.quotation(lead, submit=False)
		self.assertEqual(boot["doc"]["project"], project)

	def test_erpnext_lead_to_quotation_mapper_carries_both(self):
		# the desk's standard Lead > Create > Quotation (ERPNext's own make_quotation) copies by fieldname
		project = self.project()
		title = unique("Desk Title")
		lead = self.lead(title, project)
		frappe.set_user("Administrator")
		q = frappe.get_attr("erpnext.crm.doctype.lead.lead.make_quotation")(lead)
		self.assertEqual((q.project_title, q.project), (title, project))

	def test_mapping_into_a_quotation_keeps_its_project(self):
		own = self.project()
		lead = self.lead(unique("Title"), self.project())
		target = frappe.new_doc("Quotation")
		target.project = own
		target.project_title = "Kept"
		from thinknxg_rental.services.deal_flow import make_quotation_from_lead

		q = make_quotation_from_lead(lead, target_doc=target)
		self.assertEqual((q.project, q.project_title), (own, "Kept"))

	# ------------------------------------------------------------------ Rental Site
	def test_site_creates_the_project_and_links_it_everywhere_empty(self):
		title = unique("Harbour View")
		lead = self.lead(title)
		quotation, _boot = self.quotation(lead)
		site = self.site(quotation)
		project = frappe.db.get_value("Rental Site", site, "project")
		self.assertTrue(project)
		self.assertEqual(frappe.db.get_value("Project", project, ["project_name", "company"]), (title, self.company))
		self.assertEqual(frappe.db.get_value("Quotation", quotation, "project"), project)
		self.assertEqual(frappe.db.get_value("Lead", lead, "project"), project)
		self.assertEqual(self.count(title), 1)
		# downstream: Hire Order takes the site's Project; its Rental Contract keeps it; Cost Center still from the quotation
		cost_center = frappe.db.get_value("Cost Center", {"company": self.company, "is_group": 0})
		frappe.db.set_value("Quotation", quotation, "cost_center", cost_center)
		key, ho = create(form("rental-site", site), "Create Hire Order")
		self.assertEqual((ho["doc"]["project"], ho["doc"]["cost_center"]), (project, cost_center))
		ho["doc"]["order_date"] = nowdate()
		ho_name = save("hire-order", ho["doc"], submit=True)
		key, rc = create(form("hire-order", ho_name), "Create Rental Contract")
		self.assertEqual(rc["doc"]["project"], project)
		self.assertEqual(rc["doc"]["cost_center"], cost_center)
		rc_name = save("rental-contract", rc["doc"], submit=True)
		self.assertEqual(frappe.db.get_value("Rental Contract", rc_name, "project"), project)

	def test_hire_order_contract_gets_the_project(self):
		job = "PT-JOB-TOWER"
		if not frappe.db.exists("Job Type", job):
			self.skipTest("run test_admin_portal first: it makes the test Job Type")
		title = unique("Plant Job")
		lead = self.lead(title, deal_type="Hire Order Contract")
		key, q = create(form("lead", lead), "Create Quotation")
		q["doc"].update(items=[{"item_code": job, "qty": 1, "rate": 1000, "uom": "Nos", "nxg_included_days": 30}], valid_till=add_days(nowdate(), 30))
		quotation = save("quotation", q["doc"], submit=True)
		site = self.site(quotation)
		project = frappe.db.get_value("Rental Site", site, "project")
		key, hoc = create(form("rental-site", site), "Create Hire Order Contract")
		self.assertEqual(hoc["doc"]["project"], project)
		self.assertEqual(frappe.db.get_value("Project", project, "project_name"), title)

	def test_existing_quotation_link_is_kept(self):
		mine = self.project()
		lead = self.lead(unique("Ignored Title"))
		quotation, _ = self.quotation(lead, project=mine)
		site = self.site(quotation)
		self.assertEqual(frappe.db.get_value("Rental Site", site, "project"), mine)
		self.assertEqual(frappe.db.get_value("Quotation", quotation, "project"), mine)
		# the lead was empty, so it is filled with the same Project; no Project made from the title
		self.assertEqual(frappe.db.get_value("Lead", lead, "project"), mine)

	def test_existing_links_differ_and_each_is_kept(self):
		on_lead, on_site = self.project(), self.project()
		lead = self.lead(unique("Title"), on_lead)
		quotation, _ = self.quotation(lead)
		frappe.db.set_value("Quotation", quotation, "project", None)
		site = self.site(quotation, project=on_site)
		self.assertEqual(frappe.db.get_value("Rental Site", site, "project"), on_site)
		self.assertEqual(frappe.db.get_value("Lead", lead, "project"), on_lead)
		self.assertEqual(frappe.db.get_value("Quotation", quotation, "project"), on_site)

	def test_project_with_the_same_title_is_reused(self):
		title = unique("Reused Project")
		existing = self.project(title)
		quotation, _ = self.quotation(self.lead(title))
		site = self.site(quotation)
		self.assertEqual(frappe.db.get_value("Rental Site", site, "project"), existing)
		self.assertEqual(self.count(title), 1)
		# a second site from another quotation with the same title still makes no second Project
		site2 = self.site(self.quotation(self.lead(title))[0])
		self.assertEqual(frappe.db.get_value("Rental Site", site2, "project"), existing)
		self.assertEqual(self.count(title), 1)

	def test_title_of_another_customers_project_is_not_borrowed(self):
		other = frappe.db.get_value("Customer", {"disabled": 0}, "name")
		title = unique("Shared Name")
		theirs = self.project(title, customer=other)
		quotation, _ = self.quotation(self.lead(title))
		site = self.site(quotation)
		project = frappe.db.get_value("Rental Site", site, "project")
		if frappe.db.get_value("Rental Site", site, "customer") == other:
			self.assertEqual(project, theirs)
		else:
			self.assertNotEqual(project, theirs)
			self.assertTrue(frappe.db.get_value("Project", project, "project_name").startswith(title + " - "))

	def test_no_title_does_nothing(self):
		before = frappe.db.count("Project")
		lead = self.lead()
		quotation, _ = self.quotation(lead)
		site = self.site(quotation)
		self.assertFalse(frappe.db.get_value("Rental Site", site, "project"))
		self.assertFalse(frappe.db.get_value("Quotation", quotation, "project"))
		self.assertFalse(frappe.db.get_value("Lead", lead, "project"))
		self.assertEqual(frappe.db.count("Project"), before)

	def test_title_changed_after_linking_keeps_the_link(self):
		title = unique("First Name")
		lead = self.lead(title)
		quotation, _ = self.quotation(lead)
		site = self.site(quotation)
		project = frappe.db.get_value("Rental Site", site, "project")
		frappe.db.set_value("Quotation", quotation, "project_title", unique("Renamed"))
		boot = form("lead", lead)
		boot["doc"]["project_title"] = unique("Renamed")
		save("lead", boot["doc"])
		# saving the site again, or making another site from the same quotation, does not relink
		doc = frappe.get_doc("Rental Site", site)
		doc.location = "Gate 2"
		doc.save()
		site2 = self.desk_site(quotation).name
		for doctype, name in (("Rental Site", site), ("Rental Site", site2), ("Quotation", quotation), ("Lead", lead)):
			self.assertEqual(frappe.db.get_value(doctype, name, "project"), project, doctype)

	def test_desk_rental_site_from_a_quotation(self):
		# the desk's Create > Rental Site opens a new site with nxg_quotation set; saving it links the Project
		title = unique("Desk Site")
		lead = self.lead(title)
		quotation, _ = self.quotation(lead)
		doc = self.desk_site(quotation)
		self.assertEqual(frappe.db.get_value("Project", doc.project, "project_name"), title)

	def test_concurrent_creation_reuses_the_first_project(self):
		# a Project of that name made between the lookup and the insert (another user's save): the
		# unique project_name makes the insert fail, and the existing Project is used instead
		title = unique("Race")
		real_find = project_link.find_project
		calls = {"n": 0}

		def late_find(t, company, customer=None):
			calls["n"] += 1
			if calls["n"] == 1:
				frappe.get_doc({"doctype": "Project", "project_name": title, "company": self.company}).insert(ignore_permissions=True)
				return None
			return real_find(t, company, customer)

		project_link.find_project = late_find
		try:
			name = project_link.find_or_create_project(title, self.company)
		finally:
			project_link.find_project = real_find
		self.assertEqual(frappe.db.get_value("Project", name, "project_name"), title)
		self.assertEqual(self.count(title), 1)

	def test_fill_if_empty_never_replaces(self):
		first, second = self.project(), self.project()
		lead = self.lead(unique("T"), first)
		self.assertFalse(project_link.fill_if_empty("Lead", lead, second))
		self.assertEqual(frappe.db.get_value("Lead", lead, "project"), first)

	def test_user_without_project_create_permission_gets_no_project(self):
		frappe.set_user("Administrator")
		from thinknxg_rental.tests.test_admin_portal import ensure_user

		user = ensure_user("pl.noproject@example.com", ["Rental Manager", "Sales User", "Sales Manager", "Stock User"])
		frappe.set_user(user)
		if frappe.has_permission("Project", "create"):
			self.skipTest("Project create is allowed for these roles on this site")
		title = unique("Not Allowed")
		self.assertIsNone(project_link.find_or_create_project(title, self.company))
		self.assertEqual(self.count(title), 0)

	def test_custom_fields_once(self):
		from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

		from thinknxg_rental.services.setup import get_custom_fields

		frappe.set_user("Administrator")
		create_custom_fields(get_custom_fields(), ignore_validate=True)
		create_custom_fields(get_custom_fields(), ignore_validate=True)
		for doctype in ("Lead", "Quotation"):
			for field in ("project", "project_title"):
				self.assertEqual(frappe.db.count("Custom Field", {"dt": doctype, "fieldname": field}), 1, f"{doctype}.{field}")
				self.assertEqual([f.fieldname for f in frappe.get_meta(doctype).fields].count(field), 1)
