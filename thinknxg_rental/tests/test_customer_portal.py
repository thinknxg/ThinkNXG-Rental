"""Customer Command Center (/rental): every API as a customer portal user, and data isolation.

Two customers, each with its own portal user. Customer A has a rental contract with material on site,
an invoice and requests; customer B must never see any of it.

    bench --site <site> run-tests --module thinknxg_rental.tests.test_customer_portal
"""
import base64

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from thinknxg_rental.portal import customer as cp
from thinknxg_rental.tests import test_reservation_warehouses as trw
from thinknxg_rental.tests.test_admin_portal import STAFF, prepare
from thinknxg_rental.thinknxg_rental.doctype.hire_delivery_order.hire_delivery_order import get_dispatch_items

USER_A = "cp.customer.a@example.com"
USER_B = "cp.customer.b@example.com"
PNG = base64.b64encode(base64.b64decode(
	"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")).decode()


def portal_user(email, customer):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0].replace(".", " ").title(),
			"user_type": "Website User", "send_welcome_email": 0}).insert(ignore_permissions=True)
	# a fresh customer every run: the test user belongs to this one only
	frappe.db.delete("Portal User", {"user": email, "parenttype": "Customer", "parent": ["!=", customer]})
	for name in frappe.get_all("Contact", filters={"user": email}, pluck="name"):
		frappe.delete_doc("Contact", name, ignore_permissions=True, force=True)
	c = frappe.get_doc("Customer", customer)
	if email not in [p.user for p in c.portal_users]:
		c.append("portal_users", {"user": email})
		c.save(ignore_permissions=True)
	contact = frappe.get_doc({"doctype": "Contact", "first_name": "Portal", "last_name": email.split("@")[0], "email_id": email, "user": email,
		"email_ids": [{"email_id": email, "is_primary": 1}], "links": [{"link_doctype": "Customer", "link_name": customer}]})
	contact.insert(ignore_permissions=True)


class TestCustomerPortal(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		prepare(cls)
		frappe.db.set_single_value("Rental Settings", "portal_allow_requests", 1)
		frappe.clear_cache(doctype="Rental Settings")
		frappe.set_user(STAFF)
		cls.rc, cls.site = trw.TestReservationWarehouses.contract(cls, [(cls.tube, 20), (cls.coupler, 30)])
		frappe.set_user("Administrator")
		cls.customer = frappe.db.get_value("Rental Contract", cls.rc, "customer")
		portal_user(USER_A, cls.customer)
		# delivery of everything ordered
		rows = get_dispatch_items(cls.rc)
		cls.delivery = frappe.get_doc({"doctype": "Hire Delivery Order", "company": cls.company, "rental_contract": cls.rc,
			"posting_date": add_days(nowdate(), -5), "items": rows}).insert()
		cls.delivery.submit()
		# a second customer with nothing in common
		cls.other = frappe.get_doc({"doctype": "Customer", "customer_name": "CP Other Customer " + frappe.generate_hash(length=4),
			"customer_group": cls.customer_group, "territory": cls.territory}).insert().name
		portal_user(USER_B, cls.other)
		# an invoice for customer A
		inv = frappe.get_doc({"doctype": "Sales Invoice", "customer": cls.customer, "company": cls.company, "posting_date": nowdate(),
			"due_date": add_days(nowdate(), 10), "items": [{"item_code": cls.tube, "qty": 1, "rate": 75}]})
		inv.insert()
		inv.submit()
		cls.invoice = inv.name
		frappe.db.commit()

	def setUp(self):
		frappe.set_user(USER_A)

	def tearDown(self):
		frappe.set_user("Administrator")

	# ------------------------------------------------------------------ who sees what
	def test_boot_and_context(self):
		b = cp.boot()
		self.assertEqual([c["name"] for c in b["customers"]], [self.customer])
		self.assertFalse(b["staff"])
		self.assertIn("Off-Hire Request", b["request_forms"])
		frappe.set_user("Guest")
		self.assertRaises(frappe.PermissionError, cp.dashboard)

	def test_customer_argument_cannot_widen_access(self):
		frappe.set_user(USER_B)
		self.assertRaises(frappe.PermissionError, cp.dashboard, customer=self.customer)
		self.assertRaises(frappe.PermissionError, cp.orders, customer=self.customer)

	def test_dashboard_figures_are_the_customers(self):
		d = cp.dashboard()
		self.assertEqual(d["kpi"].on_rent, 50)
		self.assertGreaterEqual(d["kpi"].active_contracts, 1)
		self.assertGreaterEqual(d["kpi"].outstanding, 75)
		self.assertTrue(any(s["qty"] == 50 for s in d["by_site"]))
		self.assertEqual(sum(m["dispatched"] for m in d["movement"]), 50)
		frappe.set_user(USER_B)
		b = cp.dashboard()
		self.assertEqual((b["kpi"].on_rent, b["kpi"].active_contracts, b["kpi"].outstanding), (0, 0, 0))
		self.assertFalse(b["recent_orders"])

	def test_orders_and_order_detail(self):
		rows = cp.orders()["rows"]
		row = next(r for r in rows if r.name == self.rc)
		self.assertEqual(row.at_site_qty, 50)
		self.assertTrue(cp.orders(search=row.order_no)["total"] >= 1)
		self.assertEqual(cp.orders(status="closed", search=self.rc)["total"], 0)
		o = cp.order(self.rc)
		self.assertEqual({l["item_code"]: l["delivered"] for l in o["lines"]}, {self.tube: 20, self.coupler: 30})
		titles = [e["title"] for e in o["timeline"]]
		self.assertIn("Order placed", titles)
		self.assertIn("Material dispatched and delivered", titles)
		self.assertEqual(o["deliveries"][0]["name"], self.delivery.name)
		self.assertEqual(cp.order(row.order_no)["contract"], self.rc)  # by hire order number too
		frappe.set_user(USER_B)
		self.assertRaises(frappe.PermissionError, cp.order, self.rc)
		self.assertEqual(cp.orders()["total"], 0)

	def test_active_rentals_and_movements(self):
		a = cp.active_rentals()
		self.assertEqual(sorted((r.item_code, r.qty) for r in a["rows"] if r.rental_contract == self.rc), sorted([(self.tube, 20), (self.coupler, 30)]))
		self.assertTrue(all(r.days_on_hire >= 6 for r in a["rows"] if r.rental_contract == self.rc))
		d = cp.delivery(self.delivery.name)
		self.assertEqual(sum(i["qty"] for i in d["items"]), 50)
		self.assertNotIn("source_warehouse", d["items"][0])  # internal details stay internal
		self.assertTrue(cp.deliveries()["total"] >= 1)
		frappe.set_user(USER_B)
		self.assertRaises(frappe.PermissionError, cp.delivery, self.delivery.name)
		self.assertEqual(cp.active_rentals()["total"], 0)
		self.assertEqual(cp.deliveries()["total"], 0)

	def test_invoices_statement_and_documents(self):
		inv = cp.invoices()
		self.assertIn(self.invoice, [r.name for r in inv["rows"]])
		self.assertEqual(cp.invoice(self.invoice)["payment_status"], "Unpaid")
		st = cp.statement()
		self.assertIn(self.invoice, [r["voucher_no"] for r in st["rows"]])
		self.assertAlmostEqual(st["closing"], st["opening"] + st["total_debit"] - st["total_credit"])
		docs = cp.documents(tab="invoices")
		self.assertIn(self.invoice, [r.name for r in docs["rows"]])
		self.assertIn(self.delivery.name, [r.name for r in cp.documents(tab="delivery")["rows"]])
		frappe.set_user(USER_B)
		self.assertRaises(frappe.PermissionError, cp.invoice, self.invoice)
		self.assertFalse(cp.statement()["rows"])
		self.assertEqual(cp.invoices()["total"], 0)
		self.assertEqual(cp.documents(tab="invoices")["total"], 0)

	def test_pdf_download_only_for_own_documents(self):
		frappe.set_user(USER_B)
		self.assertRaises(frappe.PermissionError, cp.download_pdf, "Sales Invoice", self.invoice)
		frappe.set_user(USER_A)
		self.assertRaises(frappe.PermissionError, cp.download_pdf, "User", USER_A)  # not a customer document
		try:
			cp.download_pdf("Sales Invoice", self.invoice)
		except frappe.PermissionError:
			raise
		except Exception as e:  # noqa: BLE001 - the PDF engine may be missing on a test machine
			self.skipTest(f"PDF engine not available: {e}")
		self.assertEqual(frappe.local.response.type, "pdf")
		self.assertTrue(frappe.local.response.filecontent.startswith(b"%PDF"))

	def test_search_is_scoped(self):
		groups = cp.search(self.rc)
		self.assertTrue(any(self.rc in r["route"] for g in groups for r in g["rows"]))
		frappe.set_user(USER_B)
		self.assertEqual(cp.search(self.rc), [])

	# ------------------------------------------------------------------ requests
	def test_return_request_flow(self):
		self.assertRaises(frappe.ValidationError, cp.submit_request, {"request_type": "Off-Hire Request", "rental_contract": self.rc,
			"items": [{"item_code": self.tube, "qty": 25}]})  # more than on site
		self.assertRaises(frappe.ValidationError, cp.submit_request, {"request_type": "Pickup Request", "rental_contract": self.rc,
			"items": [{"item_code": self.tube, "qty": 5}]})  # pickup date required
		r = cp.submit_request({"request_type": "Off-Hire Request", "rental_contract": self.rc, "required_date": add_days(nowdate(), 3),
			"site_location": "Gate 2", "items": [{"item_code": self.tube, "qty": 5}]})
		doc = frappe.get_doc("Rental Portal Request", r["name"])
		self.assertEqual((doc.customer, doc.status, doc.raised_by, doc.site_location), (self.customer, "Open", USER_A, "Gate 2"))
		returns = cp.returns(status="requested")
		self.assertIn(r["name"], [x.name for x in returns["rows"]])
		cp.add_request_message(r["name"], "Ready at gate 2 from 8 am")
		up = cp.upload_attachment(r["name"], "photo.png", PNG)
		self.assertRaises(frappe.ValidationError, cp.upload_attachment, r["name"], "virus.exe", PNG)
		detail = cp.request(r["name"])
		self.assertEqual(detail["messages"][-1]["content"], "Ready at gate 2 from 8 am")
		self.assertEqual([f.name for f in detail["files"]], [up["name"]])
		cp.download_attachment(r["name"], up["name"])
		self.assertEqual(frappe.local.response.type, "download")
		# the notification log of the user knows about it
		self.assertTrue(frappe.db.exists("Notification Log", {"for_user": USER_A, "document_name": r["name"]}))
		# another customer cannot touch it
		frappe.set_user(USER_B)
		for fn, args in ((cp.request, (r["name"],)), (cp.cancel_request, (r["name"],)), (cp.add_request_message, (r["name"], "hi")),
				(cp.upload_attachment, (r["name"], "a.png", PNG)), (cp.download_attachment, (r["name"], up["name"]))):
			self.assertRaises(frappe.PermissionError, fn, *args)
		self.assertFalse(frappe.db.exists("Notification Log", {"for_user": USER_B, "document_name": r["name"]}))
		frappe.set_user(USER_A)
		cp.cancel_request(r["name"])
		self.assertEqual(frappe.db.get_value("Rental Portal Request", r["name"], "status"), "Cancelled")

	def test_request_types_validate_their_fields(self):
		end = frappe.db.get_value("Rental Contract", self.rc, "end_date")
		self.assertRaises(frappe.ValidationError, cp.submit_request, {"request_type": "Extension Request", "rental_contract": self.rc, "new_end_date": end})
		ext = cp.submit_request({"request_type": "Extension Request", "rental_contract": self.rc, "new_end_date": add_days(end, 10), "remarks": "Pour delayed"})
		self.assertEqual(str(frappe.db.get_value("Rental Portal Request", ext["name"], "new_end_date")), str(add_days(end, 10)))
		self.assertRaises(frappe.ValidationError, cp.submit_request, {"request_type": "Support Request", "remarks": "Help"})  # no subject
		sup = cp.submit_request({"request_type": "Support Request", "subject": "Statement copy", "remarks": "Please send the March statement"})
		self.assertFalse(frappe.db.get_value("Rental Portal Request", sup["name"], "rental_contract"))
		self.assertRaises(frappe.ValidationError, cp.submit_request, {"request_type": "Damage Report", "rental_contract": self.rc,
			"items": [{"item_code": self.coupler, "qty": 2}]})  # description required
		dmg = cp.submit_request({"request_type": "Damage Report", "rental_contract": self.rc, "items": [{"item_code": self.coupler, "qty": 2}],
			"remarks": "Two couplers bent"})
		self.assertEqual(cp.requests(group="complaints")["rows"][0].name, dmg["name"])
		self.assertRaises(frappe.ValidationError, cp.submit_request, {"request_type": "Additional Material Request", "rental_contract": self.rc,
			"required_date": add_days(nowdate(), -1), "items": [{"item_code": self.tube, "qty": 5}]})  # past date
		add = cp.submit_request({"request_type": "Additional Material Request", "rental_contract": self.rc, "required_date": add_days(nowdate(), 2),
			"items": [{"item_code": self.tube, "qty": 5}]})
		self.assertEqual(frappe.db.get_value("Rental Portal Request", add["name"], "rental_site"), self.site)
		self.assertRaises(frappe.ValidationError, cp.submit_request, {"request_type": "Not A Type"})
		# a contract of another customer
		frappe.set_user(USER_B)
		self.assertRaises(frappe.PermissionError, cp.submit_request, {"request_type": "Extension Request", "rental_contract": self.rc,
			"new_end_date": add_days(end, 10)})

	def test_staff_completes_service_request_and_customer_is_told(self):
		r = cp.submit_request({"request_type": "Replacement Request", "rental_contract": self.rc, "items": [{"item_code": self.coupler, "qty": 1}],
			"remarks": "Thread worn"})
		frappe.set_user(STAFF)
		doc = frappe.get_doc("Rental Portal Request", r["name"])
		doc.complete("Replacement goes out tomorrow")
		frappe.set_user(USER_A)
		self.assertEqual(cp.request(r["name"])["response"], "Replacement goes out tomorrow")
		notes = cp.notifications()
		row = next(n for n in notes["rows"] if n.document_name == r["name"] and "completed" in n.subject)
		self.assertEqual(row.route, f"requests/{r['name']}")
		before = notes["unread"]
		after = cp.mark_notifications_read([row.name])["unread"]
		self.assertEqual(after, before - 1)

	def test_staff_preview_is_read_only(self):
		frappe.set_user(STAFF)
		self.assertEqual(cp.dashboard(customer=self.customer)["kpi"].on_rent, 50)
		self.assertRaises(frappe.ValidationError, cp.submit_request, {"request_type": "Support Request", "subject": "x", "remarks": "y"}, customer=self.customer)
		self.assertRaises(frappe.PermissionError, cp.dashboard)  # no customer chosen

	def test_requests_can_be_switched_off(self):
		frappe.db.set_single_value("Rental Settings", "portal_allow_requests", 0)
		frappe.clear_cache(doctype="Rental Settings")
		try:
			self.assertRaises(frappe.ValidationError, cp.submit_request, {"request_type": "Support Request", "subject": "x", "remarks": "y"})
		finally:
			frappe.db.set_single_value("Rental Settings", "portal_allow_requests", 1)
			frappe.clear_cache(doctype="Rental Settings")

	# ------------------------------------------------------------------ account
	def test_profile_contacts_and_settings(self):
		p = cp.profile()
		self.assertEqual([c["name"] for c in p["customers"]], [self.customer])
		self.assertEqual(p["me"]["email"], USER_A)
		cp.update_my_contact(phone="+968 2400 0000", designation="Site manager")
		self.assertEqual(frappe.db.get_value("Contact", p["me"]["name"], ["phone", "designation"]), ("+968 2400 0000", "Site manager"))
		self.assertRaises(frappe.ValidationError, cp.update_my_contact, phone="<script>")
		s = cp.save_settings(email_notifications=0)
		self.assertEqual(s["email_notifications"], 0)
		self.assertEqual(cp.save_settings(email_notifications=1)["email_notifications"], 1)
		frappe.set_user(USER_B)
		self.assertNotIn(self.customer, [c["name"] for c in cp.profile()["customers"]])

	def test_notifications_follow_documents(self):
		names = frappe.get_all("Notification Log", filters={"for_user": USER_A, "document_type": "Hire Delivery Order",
			"document_name": self.delivery.name}, pluck="name")
		self.assertTrue(names)  # the delivery told the customer
		self.assertTrue(frappe.db.exists("Notification Log", {"for_user": USER_A, "document_type": "Sales Invoice", "document_name": self.invoice}))
		frappe.set_user(USER_B)
		self.assertNotIn(names[0], [n.name for n in cp.notifications(page_length=100)["rows"]])
		cp.mark_notifications_read(names)  # someone else's names: nothing happens to them
		self.assertEqual(frappe.db.get_value("Notification Log", names[0], "read"), 0)

	def test_rental_expiry_reminder_once(self):
		from thinknxg_rental.services.customer_notify import rental_expiry_reminders

		frappe.set_user("Administrator")
		frappe.db.set_value("Rental Contract", self.rc, "end_date", add_days(nowdate(), 3))
		rental_expiry_reminders()
		rental_expiry_reminders()
		count = frappe.db.count("Notification Log", {"for_user": USER_A, "document_name": self.rc, "subject": ["like", "%ends on%"]})
		self.assertEqual(count, 1)

	# ------------------------------------------------------------------ pages
	def test_pages_route_to_the_application(self):
		from frappe.utils import get_html_for_route

		for path in ("/rental", "/rental/orders", f"/rental/orders/{self.rc}", "/rental/contracts", "/rental/requests/new"):
			html = get_html_for_route(path)
			self.assertIn("window.cp_boot", html, path)
			self.assertIn(self.customer, html)
		frappe.set_user(STAFF)
		admin = get_html_for_route("/rental/admin")
		self.assertNotIn("window.cp_boot", admin)
