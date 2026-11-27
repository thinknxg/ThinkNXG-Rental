"""Pro Forma Invoice of a Hire Order Contract: Contract Charge and Excess Charge lines per job line.

    bench --site <site> run-tests --module thinknxg_rental.tests.test_proforma_contract_charges

The amounts are worked by hand in each test (dates are fixed, so the days are exact):
    contract charge = jobs x contract rate;  excess charge = job-days beyond the contract days x excess rate.
"""
import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from thinknxg_rental.tests.test_admin_portal import prepare
from thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract import make_rental_contract
from thinknxg_rental.thinknxg_rental.doctype.rental_pro_forma_invoice import rental_pro_forma_invoice as pf

E0 = "2026-01-01"   # erection date used throughout


class TestProFormaContractCharges(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		prepare(cls)

	def setUp(self):
		frappe.set_user("Administrator")

	# ------------------------------------------------------------------ helpers
	def job(self, code):
		if not frappe.db.exists("Item", code):
			frappe.get_doc({"doctype": "Item", "item_code": code, "item_name": code.replace("-", " "), "item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": "Nos", "is_stock_item": 0}).insert()
		if not frappe.db.exists("Job Type", code):
			frappe.get_doc({"doctype": "Job Type", "item_code": code, "rental_items": []}).insert()
		return code

	def customer(self):
		name = f"PF Contract Customer {frappe.generate_hash(length=5)}"
		frappe.get_doc({"doctype": "Customer", "customer_name": name, "customer_group": self.customer_group, "territory": self.territory}).insert()
		site = frappe.get_doc({"doctype": "Rental Site", "site_name": f"PF Site {name[-5:]}", "customer": name, "company": self.company}).insert()
		return name, site.name

	def hoc(self, lines):
		"""lines: (job code, qty, included days, contract rate, excess basis, excess rate)"""
		customer, site = self.customer()
		doc = frappe.get_doc({"doctype": "Hire Order Contract", "company": self.company, "customer": customer, "rental_site": site, "order_date": E0, "required_from": E0,
			"contract_charge_billing": "On Erection", "items": [{"job_type": self.job(j), "location": f"Loc {j[-1]}", "qty": q, "included_days": d, "contract_rate": r,
				"excess_rate_basis": b, "excess_rate": e, "nxg_duration": 1} for j, q, d, r, b, e in lines]})
		doc.insert()
		doc.submit()
		return doc

	def jcr(self, hoc, idx, qty, erection=E0, dismantle=None):
		item = hoc.items[idx]
		doc = frappe.get_doc({"doctype": "Job Completion Report", "company": hoc.company, "hire_order_contract": hoc.name, "customer": hoc.customer,
			"rental_site": hoc.rental_site, "job_lines": [{"contract_item": item.name, "job_type": item.job_type, "job_qty": qty, "erection_date": erection,
				"dismantle_date": dismantle}]})
		doc.insert()
		doc.submit()
		return frappe.get_doc("Job Completion Report", doc.name)

	def make(self, hoc, upto):
		return pf.make_from_hire_order_contract(hoc.name, upto)

	def rows(self, doc, kind):
		return [r for r in doc.items if r.charge_type == kind]

	# ------------------------------------------------------------------ contract charge only
	def test_contract_charge_only_no_excess(self):
		hoc = self.hoc([("PF-JOB-A", 2, 30, 1000, "Daily", 50)])
		self.jcr(hoc, 0, 2)
		doc = self.make(hoc, "2026-01-30")  # the last contract day
		self.assertEqual([r.charge_type for r in doc.items], ["Contract Charge"])
		doc.insert()
		row = doc.items[0]
		self.assertEqual((flt(row.qty), flt(row.rate), str(row.rental_from), str(row.rental_to), row.rental_days), (2, 1000, "2026-01-01", "2026-01-30", 30))
		self.assertTrue(row.description.startswith("Contract Charge - PF JOB A - "), row.description)
		self.assertIn("2 Jobs - 30 Days", row.description)
		self.assertEqual((row.jcr, row.hire_order_item), (frappe.db.get_value("Job Completion Report", {"hire_order_contract": hoc.name}, "name"), hoc.items[0].name))
		self.assertEqual((flt(doc.items[0].amount), flt(doc.total_rental), flt(doc.net_total)), (2000, 2000, 2000))

	# ------------------------------------------------------------------ excess charge
	def test_excess_days_beyond_the_contract_days_only(self):
		hoc = self.hoc([("PF-JOB-A", 2, 30, 1000, "Daily", 50)])
		self.jcr(hoc, 0, 2)
		doc = self.make(hoc, "2026-02-14")  # contract Jan 1-30; excess Jan 31 to Feb 14 (15 days) on one row
		self.assertEqual(len(self.rows(doc, "Contract Charge")), 1)
		doc.insert()
		excess = self.rows(doc, "Excess Charge")
		self.assertEqual([(str(r.rental_from), str(r.rental_to), r.rental_days) for r in excess], [("2026-01-31", "2026-02-14", 15)])
		self.assertEqual([flt(r.qty) for r in excess], [30])          # job-days: 2 jobs x 15 days, not split by month
		self.assertTrue(all(flt(r.rate) == 50 and flt(r.job_qty) == 2 for r in excess))
		self.assertEqual([flt(r.amount) for r in doc.items], [2000, 1500])
		self.assertEqual(flt(doc.total_rental), 3500)
		self.assertIn("Excess Charge - PF JOB A - ", excess[0].description)
		self.assertIn("2 Jobs - 15 Days (31-01-2026 to 14-02-2026)", excess[0].description)

	def test_long_excess_stretch_is_one_row(self):
		# the SC-01 case: 30,000 jobs, 0.65 a day, 26 Apr to 30 Nov = 219 days -> 6,570,000 job-days, 4,270,500
		hoc = self.hoc([("PF-JOB-A", 30000, 30, 1, "Daily", 0.65)])
		self.jcr(hoc, 0, 30000, erection="2026-03-27")                # contract 27 Mar to 25 Apr
		doc = self.make(hoc, "2026-11-30")
		doc.insert()
		excess = self.rows(doc, "Excess Charge")
		self.assertEqual([(str(r.rental_from), str(r.rental_to), r.rental_days, flt(r.qty), flt(r.amount)) for r in excess],
			[("2026-04-26", "2026-11-30", 219, 6570000, 4270500)])
		self.assertEqual(excess[0].hire_order_item, hoc.items[0].name)
		self.assertIn("219 Days (26-04-2026 to 30-11-2026)", excess[0].description)

	def test_each_job_line_is_worked_on_its_own_duration_and_rate(self):
		hoc = self.hoc([("PF-JOB-A", 2, 30, 1000, "Daily", 50), ("PF-JOB-B", 1, 10, 200, "Daily", 20)])
		self.jcr(hoc, 0, 2)
		self.jcr(hoc, 1, 1)
		doc = self.make(hoc, "2026-01-31")
		by_job = {}
		for r in doc.items:
			by_job.setdefault(r.item_code, {})[r.charge_type] = by_job.get(r.item_code, {}).get(r.charge_type, 0) + flt(r.qty) * flt(r.rate)
		# A: contract 2 x 1000, excess Jan 31 only = 2 jobs x 1 day x 50;  B: contract 200, excess Jan 11-31 = 1 job x 21 days x 20
		self.assertEqual(by_job["PF-JOB-A"], {"Contract Charge": 2000, "Excess Charge": 100})
		self.assertEqual(by_job["PF-JOB-B"], {"Contract Charge": 200, "Excess Charge": 420})
		doc.insert()
		self.assertEqual(flt(doc.total_rental), 2000 + 100 + 200 + 420)

	def test_weekly_excess_basis(self):
		hoc = self.hoc([("PF-JOB-A", 1, 30, 1000, "Weekly", 70)])
		self.jcr(hoc, 0, 1)
		doc = self.make(hoc, "2026-02-07")  # excess Jan 31 + Feb 1-7 = 8 days = 8/7 weeks
		units = sum(flt(r.qty) for r in self.rows(doc, "Excess Charge"))
		self.assertAlmostEqual(units, 8 / 7.0, places=4)
		doc.insert()
		self.assertAlmostEqual(sum(flt(r.amount) for r in self.rows(doc, "Excess Charge")), 80.0, places=2)

	def test_several_jcrs_of_one_line_keep_their_own_references_and_dates(self):
		hoc = self.hoc([("PF-JOB-A", 4, 30, 1000, "Daily", 50)])
		first = self.jcr(hoc, 0, 1, "2026-01-01")
		second = self.jcr(hoc, 0, 3, "2026-01-11")
		doc = self.make(hoc, "2026-01-31")
		contract = self.rows(doc, "Contract Charge")
		self.assertEqual({r.jcr: (flt(r.qty), str(r.rental_from)) for r in contract}, {first.name: (1, "2026-01-01"), second.name: (3, "2026-01-11")})
		self.assertEqual(sum(flt(r.qty) * flt(r.rate) for r in contract), 4000)
		# only the first JCR has run past its 30 days (Jan 31): 1 job x 1 day
		self.assertEqual([(r.jcr, flt(r.qty)) for r in self.rows(doc, "Excess Charge")], [(first.name, 1)])

	# ------------------------------------------------------------------ repeated creation
	def test_repeat_creation_never_bills_a_period_twice(self):
		hoc = self.hoc([("PF-JOB-A", 2, 30, 1000, "Daily", 50)])
		self.jcr(hoc, 0, 2)
		first = self.make(hoc, "2026-01-31")
		first.insert()
		self.assertEqual(flt(first.total_rental), 2000 + 100)
		with self.assertRaisesRegex(frappe.ValidationError, "Nothing is left"):
			self.make(hoc, "2026-01-31")
		later = self.make(hoc, "2026-02-14")           # only the days after the first pro forma
		self.assertEqual([r.charge_type for r in later.items], ["Excess Charge"])
		self.assertEqual((str(later.items[0].rental_from), str(later.items[0].rental_to), flt(later.items[0].qty)), ("2026-02-01", "2026-02-14", 28))
		later.insert()
		first.reload()
		first.cancel() if first.docstatus == 1 else first.delete()   # a removed pro forma frees its periods
		again = self.make(hoc, "2026-01-31")
		self.assertEqual(len(again.items), 2)

	def test_jobs_not_yet_erected_carry_their_contract_charge_once(self):
		hoc = self.hoc([("PF-JOB-A", 3, 30, 1000, "Daily", 50)])
		self.jcr(hoc, 0, 1)
		doc = self.make(hoc, "2026-01-30")
		contract = self.rows(doc, "Contract Charge")
		self.assertEqual(sorted((flt(r.qty), bool(r.jcr)) for r in contract), [(1, True), (2, False)])
		self.assertEqual(sum(flt(r.qty) * flt(r.rate) for r in contract), 3000)
		doc.insert()
		self.jcr(hoc, 0, 2)                              # the two are erected later: their charge is not asked again
		with self.assertRaisesRegex(frappe.ValidationError, "Nothing is left"):
			self.make(hoc, "2026-01-30")

	def test_excess_follows_bill_upto_even_without_a_jcr(self):
		hoc = self.hoc([("PF-JOB-A", 2, 30, 1000, "Daily", 50)])        # no Job Completion Report at all
		doc = self.make(hoc, "2026-02-14")
		self.assertEqual([r.charge_type for r in doc.items], ["Contract Charge", "Excess Charge"])
		self.assertEqual([(str(r.rental_from), str(r.rental_to), flt(r.qty)) for r in self.rows(doc, "Excess Charge")],
			[("2026-01-31", "2026-02-14", 30)])
		doc.insert()
		self.assertEqual([flt(r.amount) for r in doc.items], [2000, 1500])
		more = self.make(hoc, "2026-02-28")                              # only the days after the first
		self.assertEqual([(str(r.rental_from), str(r.rental_to)) for r in more.items], [("2026-02-15", "2026-02-28")])
		with self.assertRaisesRegex(frappe.ValidationError, "Nothing is left"):
			self.make(hoc, "2026-02-14")

	def test_excess_billed_before_a_jcr_is_not_billed_again_for_those_jobs(self):
		hoc = self.hoc([("PF-JOB-A", 3, 30, 1000, "Daily", 50)])
		self.make(hoc, "2026-02-14").insert()                            # 3 jobs: contract 3000, excess 150 + 2100
		self.jcr(hoc, 0, 1)                                              # one of them is now reported
		with self.assertRaisesRegex(frappe.ValidationError, "Nothing is left"):
			self.make(hoc, "2026-02-14")

	def test_no_excess_rate_without_a_jcr_says_so(self):
		hoc = self.hoc([("PF-JOB-A", 1, 30, 1000, "Daily", 0)])
		doc = self.make(hoc, "2026-02-14")
		self.assertEqual(self.rows(doc, "Excess Charge"), [])
		self.assertIn("no excess rate", doc.remarks)

	# ------------------------------------------------------------------ validation
	def test_no_excess_rate_means_no_excess_line_and_says_so(self):
		hoc = self.hoc([("PF-JOB-A", 1, 30, 1000, "Daily", 0)])
		self.jcr(hoc, 0, 1)
		doc = self.make(hoc, "2026-01-30")
		self.assertEqual(self.rows(doc, "Excess Charge"), [])

	def test_job_line_without_contract_rate_is_reported_not_silently_priced(self):
		hoc = self.hoc([("PF-JOB-A", 1, 30, 0, "Daily", 5)])
		with self.assertRaisesRegex(frappe.ValidationError, "no contract rate"):
			self.make(hoc, "2026-01-30")

	def test_draft_contract_is_refused(self):
		hoc = self.hoc([("PF-JOB-A", 1, 30, 1000, "Daily", 5)])
		frappe.db.set_value("Hire Order Contract", hoc.name, "docstatus", 0)
		with self.assertRaisesRegex(frappe.ValidationError, "Submit the Hire Order Contract"):
			self.make(hoc, "2026-01-30")

	# ------------------------------------------------------------------ other paths
	def test_rental_contract_of_a_hire_order_contract_uses_the_same_lines(self):
		hoc = self.hoc([("PF-JOB-A", 2, 30, 1000, "Daily", 50)])
		self.jcr(hoc, 0, 2)
		rc = make_rental_contract(hoc.name)
		rc.insert()
		rc.submit()
		doc = pf.make_from_rental_contract(rc.name)
		self.assertEqual((doc.rental_contract, doc.hire_order_contract), (rc.name, hoc.name))
		self.assertEqual([r.charge_type for r in doc.items][:1], ["Contract Charge"])

	def test_contract_and_excess_lines_are_not_converted_to_a_second_tax_invoice(self):
		hoc = self.hoc([("PF-JOB-A", 2, 30, 1000, "Daily", 50)])
		self.jcr(hoc, 0, 2)
		doc = self.make(hoc, "2026-01-30")
		doc.insert()
		with self.assertRaisesRegex(frappe.ValidationError, "Job Completion Report"):
			pf.make_sales_invoice(doc.name)

	def test_hire_order_pro_forma_is_unchanged(self):
		"""Plain rental lines keep their rate-basis maths (the Hire Order path never sets a charge type)."""
		doc = frappe.new_doc("Rental Pro Forma Invoice")
		row = frappe._dict(item_code=None)
		self.assertEqual(frappe.get_meta("Rental Pro Forma Item").get_field("charge_type").default, "Rental")
		self.assertNotIn("Rental", pf.JOB_CHARGES)
		del doc, row
