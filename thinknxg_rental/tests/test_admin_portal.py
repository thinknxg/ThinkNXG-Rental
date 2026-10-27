"""End-to-end tests of the admin portal (/rental/admin) data entry and boards.

Every step goes through the same server methods the portal pages call (portal.entry.get_form_boot,
save_entry, prepare_mapped, run_action and the portal.admin boards), as a Rental Manager who is not
System Manager, so the real DocType validations and permissions apply.

Run on a test site with ERPNext and this app, after the setup wizard:
    bench --site <site> set-config allow_tests true
    bench --site <site> run-tests --module thinknxg_rental.tests.test_admin_portal
"""
import json
from urllib.parse import parse_qsl

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, nowdate

from thinknxg_rental.portal import admin
from thinknxg_rental.portal import entry as E

STAFF = "rental.portal.staff@example.com"
OUTSIDER = "rental.portal.outsider@example.com"


# ----------------------------------------------------------------------------- portal helpers
def form(key, name=None, **form_dict):
	"""What the form page receives, as plain JSON (the browser's copy of the document)."""
	return frappe.parse_json(frappe.as_json(E.get_form_boot(key, name, frappe._dict(form_dict))))


def action(boot, label):
	for a in boot["next"]:
		if a["label"] == label:
			return a
	raise AssertionError(f"{boot['name']}: no '{label}' button, only {[a['label'] for a in boot['next']]}")


def labels(boot):
	return [a["label"] for a in boot["next"]]


def create(boot, label, **values):
	"""Click a Create button (answering its ask panel with values): map in a POST, then open the unsaved
	document like the form page does."""
	a = action(boot, label)
	url = E.prepare_mapped(a["make"], a["source"], json.dumps(values) if values else None)["url"]
	target = dict(parse_qsl(url.split("?", 1)[1]))
	key = target.pop("type")
	if "name" in target:
		return key, form(key, target["name"])
	return key, form(key, **target)


def save(key, doc, submit=False):
	return E.save_entry(key, json.dumps(doc), 1 if submit else 0)["name"]


def run(boot, label, **values):
	a = action(boot, label)
	return E.run_action(a["run"], a["source"], json.dumps(values))


def fill(boot):
	"""The form's Get items button."""
	f = boot["fill"]
	return frappe.parse_json(frappe.as_json(frappe.get_attr(f["method"])(**{f.get("arg") or "rental_contract": boot["doc"][f["needs"]]})))


# ----------------------------------------------------------------------------- fixtures
def ensure_user(email, roles):
	if not frappe.db.exists("User", email):
		user = frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0})
		user.insert(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	user.add_roles(*roles)
	return email


def ensure_item(code, name, stock=1, **extra):
	if not frappe.db.exists("Item", code):
		frappe.get_doc({"doctype": "Item", "item_code": code, "item_name": name, "item_group": _leaf("Item Group"),
			"stock_uom": "Nos", "is_stock_item": stock, **extra}).insert(ignore_permissions=True)
	return code


def _leaf(doctype):
	return frappe.db.get_value(doctype, {"is_group": 0}, "name")


def settings():
	return frappe.get_cached_doc("Rental Settings")


class TestAdminPortal(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = frappe.db.get_single_value("Rental Settings", "company") or frappe.db.get_value("Company", {}, "name")
		s = frappe.get_single("Rental Settings")
		if not s.rental_yard_warehouse:
			from thinknxg_rental.services.setup import setup_company

			setup_company(cls.company)
		frappe.clear_cache(doctype="Rental Settings")
		cls.yard = settings().rental_yard_warehouse
		ensure_user(STAFF, ["Rental Manager", "Sales User", "Sales Manager", "Stock User", "Purchase User", "Accounts User", "Projects User"])
		ensure_user(OUTSIDER, ["Sales User"])
		cls.tube = ensure_item("PTA-TUBE", "Portal Test Tube 6m")
		cls.coupler = ensure_item("PTA-COUPLER", "Portal Test Coupler")
		for code in (cls.tube, cls.coupler):
			if not frappe.db.exists("Rental Item Profile", {"item": code}):
				frappe.get_doc({"doctype": "Rental Item Profile", "item": code, "category": "Scaffolding", "daily_rate": 4,
					"replacement_value": 500}).insert(ignore_permissions=True)
		if flt(frappe.db.get_value("Bin", {"item_code": cls.tube, "warehouse": cls.yard}, "actual_qty")) < 1000:
			# received well before the backdated deliveries in the tests
			se = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "company": cls.company,
				"set_posting_time": 1, "posting_date": add_days(nowdate(), -90), "items": [
				{"item_code": cls.tube, "t_warehouse": cls.yard, "qty": 1000, "basic_rate": 400},
				{"item_code": cls.coupler, "t_warehouse": cls.yard, "qty": 1000, "basic_rate": 20}]})
			se.insert(ignore_permissions=True)
			se.submit()
		cls.customer_group = _leaf("Customer Group")
		cls.territory = _leaf("Territory")
		frappe.db.commit()

	def setUp(self):
		frappe.set_user(STAFF)

	def tearDown(self):
		frappe.set_user("Administrator")

	# ------------------------------------------------------------------ helpers for a flow
	def lead_to_site(self, deal_type, name):
		lead = form("lead")
		lead["doc"].update(first_name=name, company_name=f"{name} Builders", deal_type=deal_type, company=self.company)
		lead_name = save("lead", lead["doc"])
		lead = form("lead", lead_name)
		key, q = create(lead, "Create Quotation")
		self.assertEqual(key, "quotation")
		return lead_name, q

	def quote(self, q, rows, submit=True):
		q["doc"]["items"] = rows
		q["doc"]["valid_till"] = add_days(nowdate(), 30)
		name = save("quotation", q["doc"], submit=submit)
		return form("quotation", name)

	# ------------------------------------------------------------------ A: material hire
	def test_a_material_hire(self):
		lead_name, q = self.lead_to_site("Material Hire", "Hira")
		q["doc"].update(nxg_required_from=nowdate(), nxg_expected_return_date=add_days(nowdate(), 60))
		q = self.quote(q, [{"item_code": self.tube, "qty": 100, "rate": 4, "uom": "Nos", "nxg_rate_basis": "Daily"},
			{"item_code": self.coupler, "qty": 200, "rate": 1, "uom": "Nos", "nxg_rate_basis": "Daily"}])
		self.assertEqual(q["docstatus"], 1)
		# the lead no longer offers a second quotation, and lists this one
		lead = form("lead", lead_name)
		self.assertNotIn("Create Quotation", labels(lead))
		self.assertIn(q["name"], [r["name"] for r in lead["related"][0]["rows"]])

		key, site = create(q, "Create Rental Site")
		site["doc"]["site_name"] = f"Hira Tower {frappe.generate_hash(length=4)}"
		site_name = save("rental-site", site["doc"])
		self.assertNotIn("Create Rental Site", labels(form("quotation", q["name"])))

		key, ho = create(form("rental-site", site_name), "Create Hire Order")
		self.assertEqual(key, "hire-order")
		self.assertEqual(ho["doc"]["rental_site"], site_name)
		ho["doc"]["order_date"] = nowdate()
		ho_name = save("hire-order", ho["doc"], submit=True)
		ho = form("hire-order", ho_name)
		self.assertNotIn("Create Hire Order", labels(form("quotation", q["name"])))

		key, rc = create(ho, "Create Rental Contract")
		# started 40 days ago, so a whole billing period is complete
		rc["doc"].update(contract_date=add_days(nowdate(), -40), start_date=add_days(nowdate(), -40), billing_cycle="Weekly")
		rc_name = save("rental-contract", rc["doc"], submit=True)
		rc = form("rental-contract", rc_name)
		self.assertEqual(rc["status"], "Active")
		self.assertIn(rc_name, [r["name"] for r in form("hire-order", ho_name)["related"][0]["rows"]])

		# deposit on the submitted contract
		run(rc, "Record Deposit", deposit_received=5000, deposit_reference="CHQ-1")
		self.assertEqual(flt(frappe.db.get_value("Rental Contract", rc_name, "deposit_received")), 5000)

		# reservation (optional) then delivery of part of the order
		key, res = create(rc, "Material Reservation")
		res_name = save("material-reservation", res["doc"], submit=True)
		self.assertGreater(flt(frappe.db.get_value("Rental Material Reservation", res_name, "total_reserved_qty")), 0)

		do = form("delivery-order", rental_contract=rc_name)
		do["doc"]["items"] = fill(do)
		for r in do["doc"]["items"]:
			r["qty"] = 60 if r["item_code"] == self.tube else 200
		do["doc"].update(vehicle_no="KA01AB1234", posting_date=add_days(nowdate(), -40))
		do_name = save("delivery-order", do["doc"], submit=True)
		rc = form("rental-contract", rc_name)
		self.assertEqual(rc["status"], "On Hire")
		self.assertEqual(flt(rc["doc"]["total_at_site_qty"]), 260)
		self.assertIn(do_name, [r["name"] for s in rc["related"] if s["label"] == "Delivery Orders" for r in s["rows"]])

		# material at site comes from the ledger: delivered 60, returned 0, at site 60
		groups, totals = admin.get_site_groups(rc_name)
		tube_row = next(r for g in groups for r in g.rows if r.item_code == self.tube and g.contract == rc_name)
		self.assertEqual((flt(tube_row.delivered_qty), flt(tube_row.returned_qty), flt(tube_row.qty)), (60, 0, 60))
		view, rows = admin.get_admin_contracts("live", rc_name)
		self.assertEqual(flt(rows[0].total_at_site_qty), 260)

		# partial return with damage
		oh = form("off-hire-note", rental_contract=rc_name)
		oh["doc"]["items"] = fill(oh)
		oh["doc"]["items"] = [dict(r, returned_qty=20) for r in oh["doc"]["items"] if r["item_code"] == self.tube]
		oh_name = save("off-hire-note", oh["doc"], submit=True)
		groups, totals = admin.get_site_groups(rc_name)
		tube_row = next(r for g in groups for r in g.rows if r.item_code == self.tube and g.contract == rc_name)
		self.assertEqual((flt(tube_row.delivered_qty), flt(tube_row.returned_qty), flt(tube_row.qty)), (60, 20, 40))

		# over-returning is refused by the DocType
		oh2 = form("off-hire-note", rental_contract=rc_name)
		oh2["doc"]["items"] = [dict(r, returned_qty=999) for r in fill(oh2) if r["item_code"] == self.tube]
		self.assertRaises(frappe.ValidationError, save, "off-hire-note", oh2["doc"], True)

		oh = form("off-hire-note", oh_name)
		if "Create Return Inspection" in labels(oh):
			key, ri = create(oh, "Create Return Inspection")
			for r in ri["doc"]["items"]:
				r.update(good_qty=15, repairable_qty=3, damaged_qty=2, damage_notes="bent")
			ri_name = save("return-inspection", ri["doc"], submit=True)
			ri = form("return-inspection", ri_name)
			key, ds = create(ri, "Create Damage Settlement")
		else:
			key, ds = create(oh, "Create Damage Settlement")
		if not ds["doc"].get("items"):
			ds["doc"]["items"] = [{"item_code": self.tube, "classification": "Beyond Repair", "qty": 2, "rate": 500, "liability_percent": 100}]
		ds_name = save("damage-settlement", ds["doc"], submit=True)
		ds = form("damage-settlement", ds_name)
		self.assertIn(ds_name, [r["name"] for s in form("off-hire-note", oh_name)["related"] if s["label"] == "Damage settlements" for r in s["rows"]])
		url = E.prepare_mapped(action(ds, "Create Sales Invoice")["make"], ds_name)["url"]
		self.assertIn("sales-invoice", url)
		self.assertTrue(frappe.db.get_value("Rental Damage Settlement", ds_name, "sales_invoice"))
		self.assertNotIn("Create Sales Invoice", labels(form("damage-settlement", ds_name)))

		# billing: Bill Now uses the billing engine; a second run bills nothing new
		from thinknxg_rental.services.billing import generate_billing

		first = generate_billing(rc_name, only_complete=1)
		again = generate_billing(rc_name, only_complete=1)
		self.assertTrue(first)
		self.assertFalse(again)
		billing = admin.get_billing(rc_name)
		self.assertTrue(all(r["rental_contract"] == rc_name for r in billing.accrued))

		# extension
		rc = form("rental-contract", rc_name)
		new_end = add_days(rc["doc"]["end_date"], 15)
		run(rc, "Extend Contract", new_end_date=new_end, remarks="customer asked")
		self.assertEqual(str(frappe.db.get_value("Rental Contract", rc_name, "end_date")), new_end)
		self.assertEqual(len(form("rental-contract", rc_name)["doc"]["extensions"]), 1)

		# board figures agree with the stock position report rows they are built from
		b = admin.get_board()
		rows = admin.get_stock_rows()
		self.assertEqual(flt(b.at_site_own), sum(flt(r["at_site_own"]) for r in rows))
		self.assertTrue(any(r.name == do_name for r in b.recent))

	# ------------------------------------------------------------------ B: contract hire with several JCRs
	def test_b_contract_hire_jcrs(self):
		job = "PT-JOB-TOWER"
		if not frappe.db.exists("Item", job):
			frappe.set_user("Administrator")
			frappe.get_doc({"doctype": "Item", "item_code": job, "item_name": "Portal Test Tower Job", "item_group": _leaf("Item Group"),
				"stock_uom": "Nos", "is_stock_item": 0}).insert()
		if not frappe.db.exists("Job Type", job):
			frappe.set_user("Administrator")
			frappe.get_doc({"doctype": "Job Type", "item_code": job, "job_type_name": "Portal Test Tower Job", "rental_items": [
				{"item_code": self.tube, "qty": 10}, {"item_code": self.coupler, "qty": 20}]}).insert()
		frappe.set_user(STAFF)
		lead_name, q = self.lead_to_site("Hire Order Contract", "Jaya")
		q = self.quote(q, [{"item_code": job, "qty": 2, "rate": 10000, "uom": "Nos", "nxg_included_days": 30,
			"nxg_excess_basis": "Daily", "nxg_excess_rate": 100}])
		key, site = create(q, "Create Rental Site")
		site["doc"]["site_name"] = f"Jaya Plant {frappe.generate_hash(length=4)}"
		site_name = save("rental-site", site["doc"])
		key, hoc = create(form("rental-site", site_name), "Create Hire Order Contract")
		self.assertEqual(key, "hire-order-contract")
		# two locations of the same job type
		line = dict(hoc["doc"]["items"][0])
		line.pop("name", None)
		hoc["doc"]["items"] = [dict(line, location="North", qty=1), dict(line, location="South", qty=1)]
		hoc["doc"]["order_date"] = nowdate()
		hoc_name = save("hire-order-contract", hoc["doc"])
		hoc = form("hire-order-contract", hoc_name)
		self.assertTrue(hoc["doc"]["materials"], "physical rental items are built on first save")
		save("hire-order-contract", hoc["doc"], submit=True)
		hoc = form("hire-order-contract", hoc_name)
		key, rc = create(hoc, "Create Rental Contract")
		rc_name = save("rental-contract", rc["doc"], submit=True)
		do = form("delivery-order", rental_contract=rc_name)
		do["doc"]["items"] = fill(do)
		save("delivery-order", do["doc"], submit=True)

		# JCR 1: North, erected 40 days ago. Two lines are open, so the button asks which one.
		hoc = form("hire-order-contract", hoc_name)
		line_of = {r["location"]: r["name"] for r in hoc["doc"]["items"]}
		ask = action(hoc, "Create Job Completion Report")["ask"]
		self.assertEqual([c["value"] for c in ask[0]["choices"]], ["", line_of["North"], line_of["South"]])
		key, j1 = create(hoc, "Create Job Completion Report", contract_item=line_of["North"])
		self.assertEqual(key, "jcr")
		self.assertEqual(j1["doc"]["hire_order_contract"], hoc_name)
		self.assertEqual([r["contract_item"] for r in j1["doc"]["job_lines"]], [line_of["North"]], "only the chosen job line")
		j1["doc"]["job_lines"][0].update(erection_date=add_days(nowdate(), -40), job_qty=1)
		j1_name = save("jcr", j1["doc"], submit=True)
		# JCR 2: South, staged in two parts of 0.5. Only South is open now, so no question.
		hoc = form("hire-order-contract", hoc_name)
		self.assertFalse(action(hoc, "Create Job Completion Report")["ask"])
		key, j2 = create(hoc, "Create Job Completion Report")
		self.assertEqual([r["location"] for r in j2["doc"]["job_lines"]], ["South"], "the second JCR offers the line not yet reported")
		j2["doc"]["job_lines"][0].update(erection_date=add_days(nowdate(), -10), job_qty=0.5)
		j2_name = save("jcr", j2["doc"], submit=True)
		hoc = form("hire-order-contract", hoc_name)
		key, j3 = create(hoc, "Create Job Completion Report")
		j3["doc"]["job_lines"][0].update(erection_date=add_days(nowdate(), -5), job_qty=0.5)
		j3_name = save("jcr", j3["doc"], submit=True)
		self.assertNotIn("Create Job Completion Report", labels(form("hire-order-contract", hoc_name)), "every job is reported")

		# contract end = erection + contract days - 1
		j1_doc = frappe.get_doc("Job Completion Report", j1_name)
		self.assertEqual(str(j1_doc.job_lines[0].contract_end_date), add_days(add_days(nowdate(), -40), j1_doc.job_lines[0].included_days - 1))

		# the Hire Order Contract lists every JCR line, each linking to its JCR
		hoc = form("hire-order-contract", hoc_name)
		jcr_rows = next(s for s in hoc["related"] if s["label"] == "Job Completion Reports")["rows"]
		self.assertEqual(sorted({r["jcr"] for r in jcr_rows}), sorted([j1_name, j2_name, j3_name]))
		self.assertTrue(all(r["url"].endswith(r["jcr"]) for r in jcr_rows))

		# billing per JCR: run twice, no period twice
		from thinknxg_rental.services import jcr_billing

		frappe.set_user("Administrator")
		jcr_billing.run_daily_jcr_billing()
		jcr_billing.run_daily_jcr_billing()
		frappe.set_user(STAFF)
		periods = frappe.get_all("JCR Billing Schedule", filters={"jcr": ["in", [j1_name, j2_name, j3_name]]},
			fields=["jcr", "jcr_line", "billing_type", "period_from", "period_to"])
		keys = [(p.jcr, p.jcr_line, p.billing_type, str(p.period_from)) for p in periods]
		self.assertEqual(len(keys), len(set(keys)), "no JCR billing period twice")
		self.assertTrue([p for p in periods if p.jcr == j1_name])

		# one invoice for two JCRs marks only those two
		combinable = [r.name for r in jcr_billing.get_combinable_jcrs(j1_name)]
		if j2_name in combinable:
			inv = jcr_billing.make_combined_invoice(json.dumps([j1_name, j2_name]))
			self.assertTrue(inv)
			self.assertFalse(frappe.get_all("JCR Billing Schedule", filters={"jcr": j3_name, "sales_invoice": inv}))

		# partial then final dismantle on a JCR that was not invoiced together
		j3 = form("jcr", j3_name)
		line_name = j3["doc"]["job_lines"][0]["name"]
		run(j3, "Record Dismantle", line_name=line_name, dismantle_date=add_days(nowdate(), -2), return_qty=0.25)
		self.assertIn("Record Dismantle", labels(form("jcr", j3_name)))
		run(form("jcr", j3_name), "Record Dismantle", line_name=line_name, dismantle_date=add_days(nowdate(), -1))
		self.assertNotIn("Record Dismantle", labels(form("jcr", j3_name)))
		self.assertTrue(frappe.db.get_value("Job Completion Report Line", line_name, "dismantle_date"))

	# ------------------------------------------------------------------ C: material sale
	def test_c_material_sale(self):
		lead_name, q = self.lead_to_site("Material Sale", "Kiran")
		q = self.quote(q, [{"item_code": self.coupler, "qty": 10, "rate": 50, "uom": "Nos"}])
		self.assertNotIn("Create Rental Site", labels(q))
		key, so = create(q, "Create Sales Order")
		self.assertEqual(key, "sales-order")
		so["doc"]["delivery_date"] = add_days(nowdate(), 3)
		for r in so["doc"]["items"]:
			r["delivery_date"] = so["doc"]["delivery_date"]
			r["warehouse"] = self.yard
		so_name = save("sales-order", so["doc"], submit=True)
		self.assertNotIn("Create Sales Order", labels(form("quotation", q["name"])))
		key, dn = create(form("sales-order", so_name), "Create Delivery Note")
		self.assertEqual(key, "delivery-note")
		dn_name = save("delivery-note", dn["doc"], submit=True)
		key, si = create(form("delivery-note", dn_name), "Create Sales Invoice")
		si_name = save("sales-invoice", si["doc"], submit=True)
		self.assertTrue(si_name)
		so = form("sales-order", so_name)
		self.assertTrue(any(r["name"] == dn_name for s in so["related"] for r in s["rows"]))
		# no rental documents for a sale
		party = frappe.db.get_value("Sales Order", so_name, "customer")
		self.assertFalse(frappe.db.exists("Rental Contract", {"customer": party}))
		self.assertFalse(frappe.db.exists("Rental Ownership Ledger", {"customer": party}))

	# ------------------------------------------------------------------ D: cross hire
	def test_d_cross_hire(self):
		frappe.set_user("Administrator")
		supplier = "Portal Test Supplier"
		if not frappe.db.exists("Supplier", supplier):
			frappe.get_doc({"doctype": "Supplier", "supplier_name": supplier, "supplier_group": _leaf("Supplier Group")}).insert()
		customer = self._customer("Portal Cross Customer")
		site = self._site(customer, "Cross Yard Site")
		frappe.set_user(STAFF)
		ho = form("hire-order", customer=customer, rental_site=site, company=self.company)
		ho["doc"].update(order_date=nowdate(), required_from=nowdate(), expected_return_date=add_days(nowdate(), 30),
			items=[{"item_code": self.tube, "qty": 5, "rate": 4, "rate_basis": "Daily"}])
		ho_name = save("hire-order", ho["doc"], submit=True)
		key, rc = create(form("hire-order", ho_name), "Create Rental Contract")
		rc_name = save("rental-contract", rc["doc"], submit=True)

		cho = form("cross-hire-order", rental_contract=rc_name)
		cho["doc"].update(supplier=supplier, company=self.company, hire_from=nowdate(), expected_return_date=add_days(nowdate(), 20),
			rate_basis="Daily", receive_at="Cross Hire Yard", items=[{"item_code": self.coupler, "qty": 30, "rate": 2, "rate_basis": "Daily"}])
		cho_name = save("cross-hire-order", cho["doc"], submit=True)
		po = frappe.db.get_value("Cross Hire Order", cho_name, "purchase_order")
		self.assertTrue(po)
		if frappe.db.get_value("Purchase Order", po, "docstatus") == 0:
			frappe.get_doc("Purchase Order", po).submit()
		cho = form("cross-hire-order", cho_name)
		self.assertIn("Print Purchase Order", [p["label"] for p in cho["prints"]])
		key, pr = create(cho, "Cross Hire Receipt")
		self.assertEqual(key, "cross-hire-receipt")
		save("cross-hire-receipt", pr["doc"], submit=True)
		cho = form("cross-hire-order", cho_name)
		self.assertNotIn("Cross Hire Receipt", labels(cho))
		self.assertEqual(flt(sum(flt(r["received_qty"]) for r in cho["doc"]["items"])), 30)

		# supplier hire invoice from the portal opens the draft Purchase Invoice in the desk
		res = run(cho, "Supplier Hire Invoice", upto_date=nowdate())
		self.assertIn("/app/purchase-invoice/", res["url"])
		groups, totals = admin.get_cross_hire()
		g = next(g for g in groups if g.order == cho_name)
		self.assertTrue(g.invoices)

		# nothing went to a site, so all 30 can go back to the supplier
		key, back = create(form("cross-hire-order", cho_name), "Cross Hire Off-Hire Note")
		self.assertEqual(key, "cross-hire-off-hire")
		for r in back["doc"]["items"]:
			r["qty"] = r.get("on_hire_qty") or r.get("qty")
		save("cross-hire-off-hire", back["doc"], submit=True)
		cho = form("cross-hire-order", cho_name)
		self.assertEqual(cho["status"], "Returned")
		run(cho, "Complete Order")
		self.assertEqual(frappe.db.get_value("Cross Hire Order", cho_name, "status"), "Completed")

	# ------------------------------------------------------------------ requests
	def test_e_customer_requests(self):
		frappe.set_user("Administrator")
		customer = self._customer("Portal Request Customer")
		req = frappe.get_doc({"doctype": "Rental Portal Request", "request_type": "Hire Enquiry", "customer": customer,
			"request_date": nowdate(), "status": "Open", "company": self.company, "required_date": nowdate(),
			"expected_return_date": add_days(nowdate(), 20), "items": [{"item_code": self.tube, "qty": 3}]}).insert()
		rejected = frappe.get_doc({"doctype": "Rental Portal Request", "request_type": "Hire Enquiry", "customer": customer,
			"request_date": nowdate(), "status": "Open", "company": self.company, "items": [{"item_code": self.tube, "qty": 1}]}).insert()
		frappe.set_user(STAFF)
		view, rows = admin.get_admin_requests("open", "Portal Request Customer")
		self.assertIn(req.name, [r.name for r in rows])
		r = form("request", req.name)
		run(r, "Start")
		self.assertEqual(frappe.db.get_value("Rental Portal Request", req.name, "status"), "In Progress")
		r = form("request", req.name)
		key, ho = create(r, "Create Hire Order")
		self.assertEqual(ho["doc"]["portal_request"], req.name)
		ho["doc"].update(rental_site=self._site(customer, "Request Site"), order_date=nowdate())
		ho_name = save("hire-order", ho["doc"])
		# a second conversion is refused, and the button is gone
		self.assertNotIn("Create Hire Order", labels(form("request", req.name)))
		self.assertRaises(frappe.ValidationError, E.prepare_mapped, action(r, "Create Hire Order")["make"], req.name)
		ho2 = frappe.get_doc(dict(frappe.get_doc("Hire Order", ho_name).as_dict(), name=None, docstatus=0))
		self.assertRaises(frappe.ValidationError, ho2.insert)
		save("hire-order", form("hire-order", ho_name)["doc"], submit=True)
		self.assertEqual(frappe.db.get_value("Rental Portal Request", req.name, "status"), "Completed")

		# reject needs a reason, which the customer then sees
		r = form("request", rejected.name)
		self.assertRaises(frappe.ValidationError, run, r, "Reject")
		run(r, "Reject", reason="No stock for those dates")
		self.assertEqual(frappe.db.get_value("Rental Portal Request", rejected.name, ["status", "response"]),
			("Rejected", "No stock for those dates"))

	# ------------------------------------------------------------------ permissions
	def test_f_permissions(self):
		frappe.set_user(OUTSIDER)
		self.assertRaises(frappe.PermissionError, form, "rental-contract")
		self.assertRaises(frappe.PermissionError, E.save_entry, "jcr", json.dumps({"hire_order_contract": "x"}))
		rc = frappe.db.get_value("Rental Contract", {"docstatus": 1}, "name")
		if rc:
			idx = next(i for i, a in enumerate(E.ENTRY_TYPES["rental-contract"]["next"]) if a.get("call") == "extend_contract")
			self.assertRaises(frappe.PermissionError, E.run_action, f"rental-contract:{idx}", rc, json.dumps({"new_end_date": "2099-01-01"}))
		frappe.set_user(STAFF)
		# only configured actions run: an index that is a mapper, not an action, is refused
		self.assertRaises(frappe.ValidationError, E.run_action, "rental-contract:0", rc or "x", "{}")

	# ------------------------------------------------------------------ G: one JCR per job line and erection stage
	def test_g_jcr_per_job_line(self):
		"""HOC with Job A @ Site A (2 jobs) and Job B @ Site B (1 job): JCR 1 for Job A, JCR 2 for Job B and
		JCR 3 for a second erection stage of Job A, each picked from the contract page."""
		frappe.set_user("Administrator")
		jobs = {}
		for code, name in (("PT-JOB-A", "Portal Test Job A"), ("PT-JOB-B", "Portal Test Job B")):
			if not frappe.db.exists("Item", code):
				frappe.get_doc({"doctype": "Item", "item_code": code, "item_name": name, "item_group": _leaf("Item Group"),
					"stock_uom": "Nos", "is_stock_item": 0}).insert()
			if not frappe.db.exists("Job Type", code):
				frappe.get_doc({"doctype": "Job Type", "item_code": code, "rental_items": [{"item_code": self.tube, "qty": 10}]}).insert()
			jobs[code] = name
		customer = self._customer("Portal JCR Customer")
		site = self._site(customer, "JCR Stage Site")
		line = {"included_days": 30, "contract_rate": 1000, "excess_rate_basis": "Daily", "excess_rate": 50, "nxg_duration": 1}
		hoc = frappe.get_doc({"doctype": "Hire Order Contract", "company": self.company, "customer": customer, "rental_site": site,
			"order_date": add_days(nowdate(), -30), "required_from": add_days(nowdate(), -30), "contract_charge_billing": "On Erection",
			"items": [dict(line, job_type="PT-JOB-A", location="Site A", qty=2), dict(line, job_type="PT-JOB-B", location="Site B", qty=1)]})
		hoc.insert()
		hoc.submit()
		line_a, line_b = hoc.items[0].name, hoc.items[1].name
		frappe.set_user(STAFF)
		label = "Create Job Completion Report"

		# two open lines: the job line must be chosen, and only a line of this contract is accepted
		boot = form("hire-order-contract", hoc.name)
		ask = action(boot, label)["ask"]
		self.assertEqual(ask[0]["fieldname"], "contract_item")
		self.assertTrue(ask[0]["reqd"])
		self.assertRaises(frappe.ValidationError, create, boot, label)
		self.assertRaises(frappe.ValidationError, create, boot, label, contract_item="not-a-line")

		def new_jcr(contract_item=None, **row):
			values = {"contract_item": contract_item} if contract_item else {}
			key, j = create(form("hire-order-contract", hoc.name), label, **values)
			self.assertEqual(key, "jcr")
			self.assertEqual(j["doc"]["hire_order_contract"], hoc.name)
			self.assertEqual(j["doc"]["customer_name"], frappe.db.get_value("Customer", customer, "customer_name"))
			self.assertEqual(len(j["doc"]["job_lines"]), 1)
			j["doc"]["job_lines"][0].update(row)
			return j

		# the erection date is still required, and the message names the job line
		j = new_jcr(line_a, job_qty=1)
		with self.assertRaisesRegex(frappe.ValidationError, "Portal Test Job A @ Site A.*Erection Date"):
			save("jcr", j["doc"], submit=True)
		self.assertFalse(frappe.db.exists("Job Completion Report", {"hire_order_contract": hoc.name}), "a failed save leaves nothing behind")

		j1 = save("jcr", new_jcr(line_a, job_qty=1, erection_date="2026-10-01")["doc"], submit=True)
		j2 = save("jcr", new_jcr(line_b, job_qty=1, erection_date="2026-10-05")["doc"], submit=True)
		# Job A has one job left: the next JCR takes it without asking; a spare draft for the same job is
		# saved too, but cannot be submitted once the real one is
		self.assertFalse(action(form("hire-order-contract", hoc.name), label)["ask"])
		spare = save("jcr", new_jcr(job_qty=1, erection_date="2026-10-09")["doc"])
		self.assertEqual(form("jcr", spare)["status"], "Draft")
		j3 = save("jcr", new_jcr(job_qty=1, erection_date="2026-10-10")["doc"], submit=True)
		with self.assertRaisesRegex(frappe.ValidationError, "only 0 jobs remain"):
			E.submit_entry("jcr", spare)
		self.assertNotIn(label, labels(form("hire-order-contract", hoc.name)))

		expect = {j1: (line_a, "2026-10-01"), j2: (line_b, "2026-10-05"), j3: (line_a, "2026-10-10")}
		for name, (contract_item, erected) in expect.items():
			d = frappe.get_doc("Job Completion Report", name)
			self.assertEqual((d.docstatus, d.hire_order_contract, d.customer, d.company), (1, hoc.name, customer, self.company))
			self.assertEqual([(r.contract_item, str(r.erection_date), flt(r.job_qty)) for r in d.job_lines], [(contract_item, erected, 1)])
		self.assertEqual([(flt(d.jcr_qty), flt(d.balance_qty)) for d in frappe.get_doc("Hire Order Contract", hoc.name).items], [(2, 0), (1, 0)])

		# the contract lists every JCR with its job line; drafts show as Draft
		rows = next(r for r in form("hire-order-contract", hoc.name)["related"] if r["label"] == "Job Completion Reports")["rows"]
		listed = {(r["jcr"], r["line"], r["location"], r["status"]) for r in rows}
		self.assertTrue({(j1, "#1", "Site A"), (j2, "#2", "Site B"), (j3, "#1", "Site A")} <= {x[:3] for x in listed})
		self.assertIn((spare, "#1", "Site A", "Draft"), listed)

		# creating JCRs makes billing periods once and no invoice
		sched = frappe.get_all("JCR Billing Schedule", filters={"jcr": ["in", [j1, j2, j3]]}, fields=["jcr", "jcr_line", "billing_type", "period_from", "sales_invoice"])
		self.assertEqual(len(sched), len({(s.jcr, s.jcr_line, s.billing_type, str(s.period_from)) for s in sched}))
		self.assertFalse([s for s in sched if s.sales_invoice])

		# someone without JCR rights gets no JCR
		frappe.set_user(OUTSIDER)
		self.assertRaises(frappe.PermissionError, E.prepare_mapped, "hire-order-contract:3", hoc.name, json.dumps({"contract_item": line_a}))

	# ------------------------------------------------------------------ fixtures
	def _customer(self, name):
		if not frappe.db.exists("Customer", name):
			frappe.get_doc({"doctype": "Customer", "customer_name": name, "customer_group": self.customer_group,
				"territory": self.territory}).insert(ignore_permissions=True)
		return name

	def _site(self, customer, name):
		existing = frappe.db.get_value("Rental Site", {"site_name": name, "customer": customer}, "name")
		if existing:
			return existing
		return frappe.get_doc({"doctype": "Rental Site", "site_name": name, "customer": customer, "company": self.company}).insert(
			ignore_permissions=True).name
