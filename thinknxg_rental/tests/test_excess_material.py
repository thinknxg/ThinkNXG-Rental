"""Excess material, Excess Material Return Notes, Dismantling Entries and reconciliation (the 17
scenarios of the brief, plus the guards around them).

    bench --site <site> run-tests --module thinknxg_rental.tests.test_excess_material

Each test uses fresh items and a fresh contract (a fresh customer), so balances never mix between tests.
"""
import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, nowdate

from thinknxg_rental.services import excess, ledger
from thinknxg_rental.tests.test_admin_portal import STAFF, create, ensure_item, ensure_user, form, prepare, save
from thinknxg_rental.thinknxg_rental.doctype.dismantling_entry.dismantling_entry import make_from_contract
from thinknxg_rental.thinknxg_rental.doctype.excess_material_abandonment.excess_material_abandonment import (
	make_from_registers as make_abandonment_from_registers,
)
from thinknxg_rental.thinknxg_rental.doctype.excess_material_conversion_entry.excess_material_conversion_entry import (
	DIFFERENT as CONV_DIFFERENT,
	EXISTING as CONV_EXISTING,
	make_from_register as make_conversion_from_register,
)
from thinknxg_rental.thinknxg_rental.doctype.excess_material_return_note.excess_material_return_note import (
	get_history,
	make_from_off_hire,
	make_from_registers,
)
from thinknxg_rental.thinknxg_rental.report.customer_wise_excess_material import customer_wise_excess_material
from thinknxg_rental.thinknxg_rental.report.excess_material_register import excess_material_register
from thinknxg_rental.thinknxg_rental.report.outstanding_customer_materials import outstanding_customer_materials
from thinknxg_rental.thinknxg_rental.report.project_wise_material_reconciliation import project_wise_material_reconciliation

RENTAL_USER = "excess.rental.user@example.com"


def tag():
	return frappe.generate_hash(length=5).upper()


def bin_qty(item, warehouse):
	return flt(frappe.db.get_value("Bin", {"item_code": item, "warehouse": warehouse}, "actual_qty"))


class TestExcessMaterial(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		prepare(cls)
		frappe.set_user("Administrator")
		ensure_user(RENTAL_USER, ["Rental User", "Stock User"])
		cls.excess_wh = frappe.db.get_single_value("Rental Settings", "excess_warehouse")
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.clear_cache(doctype="Rental Settings")

	def tearDown(self):
		frappe.set_user("Administrator")

	# ------------------------------------------------------------------ fixtures
	def item(self, stock=100, uom=None):
		code = ensure_item(f"EX-{tag()}", "Excess Test Item", **({"stock_uom": uom} if uom else {}))
		frappe.get_doc({"doctype": "Rental Item Profile", "item": code, "daily_rate": 3, "monthly_rate": 60,
			"inspection_required": 0, "replacement_value": 100}).insert()
		if stock:
			se = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "company": self.company,
				"set_posting_time": 1, "posting_date": add_days(nowdate(), -60),
				"items": [{"item_code": code, "t_warehouse": self.yard, "qty": stock, "basic_rate": 50}]})
			se.insert()
			se.submit()
		return code

	def contract(self, rows):
		"""Lead -> quotation -> site -> hire order -> rental contract, through the portal (a fresh customer)."""
		frappe.set_user(STAFF)
		try:
			lead = form("lead")
			lead["doc"].update(first_name="Excess", company_name=f"Excess Co {tag()}", deal_type="Material Hire", company=self.company)
			lead_name = save("lead", lead["doc"])
			_key, q = create(form("lead", lead_name), "Create Quotation")
			q["doc"].update(items=[{"item_code": c, "qty": qty, "rate": 4, "uom": "Nos", "nxg_rate_basis": "Daily"} for c, qty in rows],
				valid_till=add_days(nowdate(), 30), nxg_required_from=nowdate(), nxg_expected_return_date=add_days(nowdate(), 30))
			quotation = save("quotation", q["doc"], submit=True)
			_key, site = create(form("quotation", quotation), "Create Rental Site")
			site["doc"]["site_name"] = f"Excess Site {frappe.generate_hash(length=8)}"
			site_name = save("rental-site", site["doc"])
			_key, ho = create(form("rental-site", site_name), "Create Hire Order")
			ho["doc"]["order_date"] = nowdate()
			ho_name = save("hire-order", ho["doc"], submit=True)
			_key, rc = create(form("hire-order", ho_name), "Create Rental Contract")
			return save("rental-contract", rc["doc"], submit=True)
		finally:
			frappe.set_user("Administrator")

	def deliver(self, contract, rows, days_ago=10):
		items = [{"item_code": code, "qty": qty, "ownership": "Own"} for code, qty in rows]
		doc = frappe.get_doc({"doctype": "Hire Delivery Order", "company": self.company, "rental_contract": contract,
			"posting_date": add_days(nowdate(), -days_ago), "items": items})
		doc.insert()
		doc.submit()
		return doc

	def off_hire(self, contract, rows, days_ago=5, submit=True):
		"""rows: (item, {returned_qty / received_qty / lost_qty / excess_qty})"""
		date = add_days(nowdate(), -days_ago)
		items = [dict({"item_code": code, "ownership": "Own"}, **values) for code, values in rows]
		doc = frappe.get_doc({"doctype": "Hire Off-Hire Note", "company": self.company, "rental_contract": contract,
			"off_hire_date": date, "return_date": date, "items": items})
		doc.insert()
		if submit:
			doc.submit()
		return doc

	def register(self, note, item):
		return frappe.get_doc(excess.REGISTER, {"hire_off_hire_note": note.name, "item_code": item})

	def return_note(self, registers, qty=None, submit=True):
		doc = make_from_registers([r.name for r in registers])
		if qty is not None:
			for d in doc.items:
				d.return_qty = qty
		doc.insert()
		if submit:
			doc.submit()
		return doc

	def dismantle(self, contract, rows, submit=True, **header):
		"""rows: (outstanding item, settled qty, register, excess used[, ratio_approved])"""
		doc = make_from_contract(contract)
		doc.update(header)
		for r in rows:
			doc.append("adjustments", {"outstanding_item": r[0], "adjustment_qty": r[1], "excess_register": r[2].name,
				"excess_qty_used": r[3], "ratio_approved": r[4] if len(r) > 4 else 0})
		doc.insert()
		if submit:
			doc.submit()
		return doc

	def contract_row(self, contract, item):
		return frappe.db.get_value("Rental Contract Item", {"parent": contract, "item_code": item},
			["dispatched_qty", "returned_qty", "lost_qty", "adjusted_qty", "at_site_qty"], as_dict=True)

	def site_warehouse(self, contract):
		return frappe.db.get_value("Rental Site", frappe.db.get_value("Rental Contract", contract, "rental_site"), "site_warehouse")

	def scenario(self, a_qty=10, b_qty=10):
		"""Contract with A and B, both delivered; A comes back short by 3, B comes back 5 over."""
		a, b = self.item(), self.item()
		rc = self.contract([(a, a_qty), (b, b_qty)])
		self.deliver(rc, [(a, a_qty), (b, b_qty)])
		note = self.off_hire(rc, [(a, {"returned_qty": a_qty - 3}), (b, {"received_qty": b_qty + 5})])
		return frappe._dict(a=a, b=b, rc=rc, note=note, reg=self.register(note, b))

	# ------------------------------------------------------------------ scenarios 1-4: classification and transfer
	def test_01_excess_from_delivered_items(self):
		"""Delivered 10, received 15: 10 returned, 5 excess into the excess warehouse, registered and traceable."""
		item = self.item()
		rc = self.contract([(item, 10)])
		do = self.deliver(rc, [(item, 10)])
		site = self.site_warehouse(rc)
		excess_before = bin_qty(item, self.excess_wh)
		note = self.off_hire(rc, [(item, {"received_qty": 15})])
		row = note.items[0]
		self.assertEqual((flt(row.returned_qty), flt(row.excess_qty)), (10, 5))
		self.assertEqual(row.excess_category, excess.DELIVERED)
		self.assertEqual(flt(note.total_excess_qty), 5)
		note.reload()
		self.assertTrue(note.excess_stock_entry)
		self.assertEqual(bin_qty(item, self.excess_wh) - excess_before, 5)
		self.assertEqual(bin_qty(item, site), 0)
		reg = self.register(note, item)
		self.assertEqual((flt(reg.delivered_qty), flt(reg.off_hire_returned_qty), flt(reg.excess_qty), flt(reg.available_qty)), (10, 10, 5, 5))
		self.assertEqual((reg.customer, reg.project, reg.rental_contract, reg.hire_delivery_order, reg.stock_entry),
			(note.customer, note.project, rc, do.name, note.excess_stock_entry))
		self.assertEqual(reg.excess_warehouse, self.excess_wh)
		self.assertEqual(frappe.db.get_value("Hire Off-Hire Item", row.name, "excess_register"), reg.name)
		# the contract balance is untouched by excess: nothing outstanding, nothing extra owed
		self.assertEqual(flt(self.contract_row(rc, item).at_site_qty), 0)
		# exactly one excess receipt for the note: never transferred twice
		self.assertEqual(frappe.db.count("Stock Entry", {"nxg_hire_voucher_no": note.name, "purpose": "Material Receipt", "docstatus": 1}), 1)
		self.assertEqual(frappe.db.count(excess.REGISTER, {"hire_off_hire_note": note.name}), 1)
		with self.assertRaises(frappe.ValidationError):
			excess.make_registers(frappe.get_doc("Hire Off-Hire Note", note.name), note.excess_stock_entry)

	def test_02_short_return_leaves_outstanding(self):
		item = self.item()
		rc = self.contract([(item, 10)])
		self.deliver(rc, [(item, 10)])
		note = self.off_hire(rc, [(item, {"received_qty": 7})])
		self.assertEqual((flt(note.items[0].returned_qty), flt(note.items[0].excess_qty)), (7, 0))
		self.assertFalse(frappe.db.exists(excess.REGISTER, {"hire_off_hire_note": note.name}))
		self.assertEqual(flt(self.contract_row(rc, item).at_site_qty), 3)
		self.assertEqual(excess.own_outstanding(rc), {item: 3})

	def test_03_additional_undelivered_item(self):
		"""An item never delivered on the contract comes back: accepted as Additional Undelivered Items."""
		a, extra = self.item(), self.item(stock=0)
		rc = self.contract([(a, 4)])
		self.deliver(rc, [(a, 4)])
		before = bin_qty(extra, self.excess_wh)
		note = self.off_hire(rc, [(a, {"returned_qty": 4}), (extra, {"received_qty": 6})])
		row = next(d for d in note.items if d.item_code == extra)
		self.assertEqual((flt(row.returned_qty), flt(row.excess_qty), row.excess_category), (0, 6, excess.UNDELIVERED))
		reg = self.register(note, extra)
		self.assertEqual((reg.excess_category, flt(reg.delivered_qty), flt(reg.excess_qty)), (excess.UNDELIVERED, 0, 6))
		self.assertEqual(bin_qty(extra, self.excess_wh) - before, 6)
		# entering the excess quantity directly still works as before
		note2 = self.off_hire(rc, [(extra, {"excess_qty": 2})])
		self.assertEqual(flt(self.register(note2, extra).excess_qty), 2)

	def test_04_existing_guards_kept(self):
		"""Returned Qty itself keeps its strict at-site check; an excess warehouse must stay apart."""
		item = self.item()
		rc = self.contract([(item, 5)])
		self.deliver(rc, [(item, 5)])
		with self.assertRaises(frappe.ValidationError):
			self.off_hire(rc, [(item, {"returned_qty": 8})])
		with self.assertRaises(frappe.ValidationError):
			self.off_hire(rc, [(item, {"received_qty": 8, "excess_warehouse": self.yard})])

	# ------------------------------------------------------------------ scenario 5-6: return to the customer
	def test_05_return_excess_to_customer(self):
		s = self.scenario()
		before = bin_qty(s.b, self.excess_wh)
		rn = self.return_note([s.reg], qty=2)
		self.assertEqual(rn.status, "Returned")
		self.assertEqual(bin_qty(s.b, self.excess_wh), before - 2)
		s.reg.reload()
		self.assertEqual((flt(s.reg.returned_to_customer_qty), flt(s.reg.available_qty), s.reg.status), (2, 3, "Partly Returned"))
		# over the available quantity: refused; the rest: allowed, and the register closes
		with self.assertRaises(frappe.ValidationError):
			self.return_note([s.reg], qty=4)
		self.return_note([s.reg], qty=3)
		s.reg.reload()
		self.assertEqual((flt(s.reg.available_qty), s.reg.status), (0, "Closed"))
		self.assertEqual(frappe.db.get_value("Hire Off-Hire Note", s.note.name, "excess_status"), "Settled")
		with self.assertRaises(frappe.ValidationError):
			make_from_off_hire(s.note.name)
		# cancelling a return puts the excess back
		rn.cancel()
		s.reg.reload()
		self.assertEqual((flt(s.reg.available_qty), s.reg.status), (2, "Partly Returned"))
		self.assertEqual(bin_qty(s.b, self.excess_wh), before - 3)

	def test_06_return_note_guards(self):
		s = self.scenario()
		other = self.scenario()
		doc = make_from_registers([s.reg.name])
		doc.append("items", {"excess_register": s.reg.name, "return_qty": 1})
		with self.assertRaises(frappe.ValidationError):  # same register twice
			doc.insert()
		doc = make_from_registers([s.reg.name])
		doc.append("items", {"excess_register": other.reg.name, "return_qty": 1})
		with self.assertRaises(frappe.ValidationError):  # another customer's excess
			doc.insert()

	# ------------------------------------------------------------------ scenario 7-11: adjustments
	def test_07_adjust_outstanding_against_excess(self):
		"""A is 3 short, B came back 5 over: settle the 3 A against 3 B."""
		s = self.scenario()
		site = self.site_warehouse(s.rc)
		a_site, b_excess = bin_qty(s.a, site), bin_qty(s.b, self.excess_wh)
		de = self.dismantle(s.rc, [(s.a, 3, s.reg, 3)])
		row = self.contract_row(s.rc, s.a)
		self.assertEqual((flt(row.adjusted_qty), flt(row.at_site_qty)), (3, 0))
		self.assertEqual(excess.own_outstanding(s.rc), {})
		s.reg.reload()
		self.assertEqual((flt(s.reg.adjusted_qty), flt(s.reg.available_qty), s.reg.status), (3, 2, "Partly Adjusted"))
		# stock: A leaves the site warehouse (it will not come back); B stays put as itself
		self.assertEqual(bin_qty(s.a, site), a_site - 3)
		self.assertEqual(bin_qty(s.b, self.excess_wh), b_excess)
		self.assertFalse(frappe.db.exists("Stock Entry Detail", {"parent": de.stock_entry, "item_code": s.b}))
		entries = frappe.get_all("Rental Ownership Ledger", filters={"voucher_no": de.name}, fields=["movement_type", "qty", "item_code", "billing_date"])
		self.assertEqual([(e.movement_type, flt(e.qty), e.item_code) for e in entries], [("Adjustment", -3, s.a)])
		self.assertEqual(str(entries[0].billing_date), add_days(nowdate(), 1))
		self.assertTrue(de.approved_by)
		self.assertEqual(frappe.db.get_value("Rental Contract", s.rc, "status"), "Off Hired")

	def test_08_partial_adjustments(self):
		s = self.scenario()
		self.dismantle(s.rc, [(s.a, 1, s.reg, 1)])
		self.assertEqual(flt(self.contract_row(s.rc, s.a).at_site_qty), 2)
		self.dismantle(s.rc, [(s.a, 2, s.reg, 2)])
		self.assertEqual(flt(self.contract_row(s.rc, s.a).at_site_qty), 0)
		s.reg.reload()
		self.assertEqual((flt(s.reg.adjusted_qty), flt(s.reg.available_qty)), (3, 2))

	def test_09_over_limits_refused(self):
		s = self.scenario()
		with self.assertRaises(frappe.ValidationError):  # more than outstanding (3)
			self.dismantle(s.rc, [(s.a, 4, s.reg, 4)])
		with self.assertRaises(frappe.ValidationError):  # more excess than available (5)
			self.dismantle(s.rc, [(s.a, 3, s.reg, 6, 1)])
		with self.assertRaises(frappe.ValidationError):  # no adjustment rows
			self.dismantle(s.rc, [])
		with self.assertRaises(frappe.ValidationError):  # a quantity left out
			self.dismantle(s.rc, [(s.a, 3, s.reg, 0)])

	def test_10_double_adjustment_refused(self):
		s = self.scenario()
		first = self.dismantle(s.rc, [(s.a, 3, s.reg, 3)], submit=False)
		second = self.dismantle(s.rc, [(s.a, 3, s.reg, 3)], submit=False)
		first.submit()
		with self.assertRaises(frappe.ValidationError):  # the 3 A are already settled
			second.submit()
		doc = make_from_contract(s.rc)
		doc.append("adjustments", {"outstanding_item": s.b, "adjustment_qty": 1, "excess_register": s.reg.name, "excess_qty_used": 1})
		with self.assertRaises(frappe.ValidationError):  # nothing of B is outstanding
			doc.insert()

	def test_11_returned_excess_cannot_be_adjusted(self):
		s = self.scenario()
		self.return_note([s.reg], qty=5)
		with self.assertRaises(frappe.ValidationError):
			self.dismantle(s.rc, [(s.a, 3, s.reg, 3)])
		# and adjusted excess cannot be returned
		s2 = self.scenario()
		self.dismantle(s2.rc, [(s2.a, 3, s2.reg, 3)])
		with self.assertRaises(frappe.ValidationError):
			self.return_note([s2.reg], qty=3)
		self.return_note([s2.reg], qty=2)

	# ------------------------------------------------------------------ scenario 12-13: cancellation
	def test_12_cancel_dismantling_restores(self):
		s = self.scenario()
		site = self.site_warehouse(s.rc)
		a_site = bin_qty(s.a, site)
		de = self.dismantle(s.rc, [(s.a, 3, s.reg, 3)])
		de.cancel()
		self.assertEqual(flt(self.contract_row(s.rc, s.a).at_site_qty), 3)
		self.assertEqual(bin_qty(s.a, site), a_site)
		self.assertFalse(frappe.db.exists("Rental Ownership Ledger", {"voucher_no": de.name}))
		s.reg.reload()
		self.assertEqual((flt(s.reg.adjusted_qty), flt(s.reg.available_qty), s.reg.status), (0, 5, "Available"))
		self.assertEqual(frappe.db.get_value("Rental Contract", s.rc, "status"), "On Hire")

	def test_13_cancel_off_hire_with_excess(self):
		s = self.scenario()
		self.dismantle(s.rc, [(s.a, 3, s.reg, 3)])
		with self.assertRaises(frappe.ValidationError):  # its excess is in use
			frappe.get_doc("Hire Off-Hire Note", s.note.name).cancel()
		s2 = self.scenario()
		before = bin_qty(s2.b, self.excess_wh)
		frappe.get_doc("Hire Off-Hire Note", s2.note.name).cancel()
		s2.reg.reload()
		self.assertEqual((s2.reg.status, flt(s2.reg.available_qty)), ("Cancelled", 0))
		self.assertEqual(bin_qty(s2.b, self.excess_wh), before - 5)
		with self.assertRaises(frappe.ValidationError):  # a cancelled register cannot be used
			self.return_note([s2.reg], qty=1)

	# ------------------------------------------------------------------ scenario 14: closure
	def test_14_closure_needs_reconciliation(self):
		s = self.scenario()
		contract = frappe.get_doc("Rental Contract", s.rc)
		with self.assertRaises(frappe.ValidationError):  # 3 A still outstanding
			contract.close_contract()
		self.dismantle(s.rc, [(s.a, 3, s.reg, 3)])
		result = excess.reconcile(s.rc)
		self.assertFalse(result["reconciled"])  # 2 B of excess still held
		self.assertEqual([(i["item_code"], i["delivered"], i["returned"], i["adjusted"], i["outstanding"]) for i in result["items"] if i["item_code"] == s.a],
			[(s.a, 10, 7, 3, 0)])
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Rental Contract", s.rc).close_contract()
		draft = self.return_note([s.reg], qty=2, submit=False)
		self.assertTrue(any(draft.name in i for i in excess.reconcile(s.rc)["issues"]))  # a draft is not settled
		draft.submit()
		result = excess.reconcile(s.rc)
		self.assertTrue(result["reconciled"], result["issues"])
		frappe.get_doc("Rental Contract", s.rc).close_contract()
		self.assertEqual(frappe.db.get_value("Rental Contract", s.rc, ["status", "reconciliation_status"]), ("Completed", "Reconciled"))

	def test_14b_exception_approval(self):
		s = self.scenario()
		self.dismantle(s.rc, [(s.a, 3, s.reg, 3)])
		frappe.set_user(RENTAL_USER)
		with self.assertRaises(frappe.PermissionError):
			excess.approve_exception(s.rc, "customer abandoned the extra material")
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			excess.approve_exception(s.rc, " ")
		frappe.get_doc("Rental Contract", s.rc).approve_reconciliation_exception("Customer abandoned 2 units of B")
		doc = frappe.get_doc("Rental Contract", s.rc)
		self.assertEqual((doc.reconciliation_exception, doc.reconciliation_exception_by, doc.reconciliation_status),
			(1, "Administrator", "Exception Approved"))
		self.assertTrue(frappe.db.exists("Comment", {"reference_name": s.rc, "content": ["like", "%Customer abandoned 2 units of B%"]}))
		doc.close_contract()
		self.assertEqual(frappe.db.get_value("Rental Contract", s.rc, "status"), "Completed")
		doc.reload()
		doc.reopen_contract()
		self.assertEqual(frappe.db.get_value("Rental Contract", s.rc, "reconciliation_exception"), 0)

	def test_14c_project_completion(self):
		s = self.scenario()
		project = frappe.get_doc({"doctype": "Project", "project_name": f"Excess Project {tag()}", "company": self.company}).insert()
		frappe.db.set_value("Rental Contract", s.rc, "project", project.name)
		frappe.db.set_value(excess.REGISTER, s.reg.name, "project", project.name)  # as if the project was set from the start
		project.status = "Completed"
		with self.assertRaises(frappe.ValidationError):
			project.save()
		self.dismantle(s.rc, [(s.a, 3, s.reg, 3)])
		self.return_note([s.reg], qty=2)
		project.reload()
		project.status = "Completed"
		project.save()

	# ------------------------------------------------------------------ scenario 15-16: customer, project, ratio
	def test_15_customer_and_project_scope(self):
		s = self.scenario()
		other = self.scenario()
		with self.assertRaises(frappe.ValidationError):  # another customer's excess
			self.dismantle(s.rc, [(s.a, 3, other.reg, 3)])
		# excess of project P1; the contract is now on P2
		p1 = frappe.get_doc({"doctype": "Project", "project_name": f"Excess P1 {tag()}", "company": self.company}).insert()
		p2 = frappe.get_doc({"doctype": "Project", "project_name": f"Excess P2 {tag()}", "company": self.company}).insert()
		frappe.db.set_value(excess.REGISTER, s.reg.name, "project", p1.name)
		frappe.db.set_value("Rental Contract", s.rc, "project", p2.name)
		doc = make_from_contract(s.rc)
		self.assertNotIn(s.reg.name, [d.excess_register for d in doc.excess_items])
		with self.assertRaises(frappe.ValidationError):
			self.dismantle(s.rc, [(s.a, 3, s.reg, 3)])
		# allowed from other projects: a Rental User may draft it, only a manager may approve it
		frappe.set_user(RENTAL_USER)
		draft = self.dismantle(s.rc, [(s.a, 3, s.reg, 3)], submit=False, allow_cross_project=1, cross_project_reason="Same client, adjoining site")
		self.assertFalse(draft.cross_project_approved_by)
		frappe.set_user("Administrator")
		draft.reload()
		draft.submit()
		self.assertEqual(draft.cross_project_approved_by, "Administrator")
		self.assertEqual(flt(self.contract_row(s.rc, s.a).at_site_qty), 0)

	def test_16_ratio_needs_approval(self):
		"""Items are never assumed interchangeable 1 : 1 - a different ratio needs a manager."""
		s = self.scenario()
		with self.assertRaises(frappe.ValidationError):
			self.dismantle(s.rc, [(s.a, 3, s.reg, 4)])  # 4 B for 3 A, not approved
		frappe.set_user(RENTAL_USER)
		with self.assertRaises(frappe.PermissionError):
			self.dismantle(s.rc, [(s.a, 3, s.reg, 4, 1)], submit=False)
		frappe.set_user("Administrator")
		de = self.dismantle(s.rc, [(s.a, 3, s.reg, 4, 1)])
		self.assertEqual((de.adjustments[0].ratio_approved_by, round(flt(de.adjustments[0].conversion_ratio), 4)), ("Administrator", 1.3333))
		s.reg.reload()
		self.assertEqual(flt(s.reg.available_qty), 1)

	def test_16b_rental_user_cannot_submit_dismantling(self):
		s = self.scenario()
		frappe.set_user(RENTAL_USER)
		draft = self.dismantle(s.rc, [(s.a, 3, s.reg, 3)], submit=False)
		with self.assertRaises(frappe.PermissionError):
			draft.submit()

	def test_16c_billing_stops_after_adjustment(self):
		s = self.scenario()
		self.dismantle(s.rc, [(s.a, 3, s.reg, 3)])
		segments = ledger.get_segments(add_days(nowdate(), -10), add_days(nowdate(), 5), ledger.AT_SITE, rental_contract=s.rc)
		last = segments[s.a][-1]
		self.assertEqual((str(last[1]), flt(last[2])), (nowdate(), 3))

	# ------------------------------------------------------------------ scenario 17: reports
	def test_17_reports_and_balances(self):
		s = self.scenario()
		self.dismantle(s.rc, [(s.a, 2, s.reg, 2)])
		self.return_note([s.reg], qty=1)
		customer = s.note.customer
		_c, rows = excess_material_register.execute({"customer": customer})
		self.assertEqual([(r.register, flt(r.excess_qty), flt(r.returned_to_customer_qty), flt(r.adjusted_qty), flt(r.available_qty)) for r in rows],
			[(s.reg.name, 5, 1, 2, 2)])
		_c, rows = customer_wise_excess_material.execute({"customer": customer})
		self.assertEqual([(r.item_code, r.excess_qty, r.available_qty) for r in rows], [(s.b, 5, 2)])
		_c, rows = project_wise_material_reconciliation.execute({"rental_contract": s.rc})
		by_item = {r.item_code: r for r in rows}
		self.assertEqual((by_item[s.a].delivered_qty, by_item[s.a].returned_qty, by_item[s.a].adjusted_qty, by_item[s.a].outstanding_qty), (10, 7, 2, 1))
		self.assertEqual((by_item[s.b].excess_qty, by_item[s.b].excess_available_qty, by_item[s.b].outstanding_qty), (5, 2, 0))
		_c, rows = outstanding_customer_materials.execute({"rental_contract": s.rc})
		self.assertEqual([(r.item_code, flt(r.outstanding_qty), flt(r.adjusted_qty), flt(r.excess_available_qty)) for r in rows], [(s.a, 1, 2, 2)])
		# warehouse stock agrees with the registers
		self.assertFalse(excess.excess_stock_issues(excess.reconcile(s.rc)["excess"]))


class TestExcessConversion(TestExcessMaterial):
	"""Excess Material Conversion Entry: excess the company owns moved into rental stock (Repack)."""

	# the parent's tests are run by the parent class, not again here
	for _name in [n for n in dir(TestExcessMaterial) if n.startswith("test_")]:
		locals()[_name] = None
	del _name

	def convert(self, s, rows, submit=True, **header):
		"""rows: (register, conversion qty, target item, rate[, target qty, basis, warehouse])"""
		doc = frappe.get_doc({"doctype": "Excess Material Conversion Entry", "company": self.company, "customer": s.note.customer,
			"posting_date": nowdate(), "source_warehouse": self.excess_wh, "target_warehouse": self.yard,
			"conversion_type": header.pop("conversion_type", CONV_EXISTING), **header})
		for r in rows:
			doc.append("items", {"excess_register": r[0].name, "conversion_qty": r[1], "target_item_code": r[2], "valuation_rate": r[3],
				"target_qty": r[4] if len(r) > 4 else 0, "valuation_basis": r[5] if len(r) > 5 else "Manual Rate",
				"target_warehouse": r[6] if len(r) > 6 else None})
		doc.insert()
		if submit:
			doc.submit()
		return doc

	def adjusted(self):
		"""A, 3 short, settled against 3 of the 5 excess B: 3 B are the company's, 2 still the customer's."""
		s = self.scenario()
		s.de = self.dismantle(s.rc, [(s.a, 3, s.reg, 3)])
		return s

	def test_c1_only_company_owned_excess_converts(self):
		s = self.scenario()
		self.assertEqual(flt(excess.convertible([s.reg.name])[s.reg.name]), 0)
		with self.assertRaises(frappe.ValidationError):  # all 5 are still the customer's
			make_conversion_from_register(s.reg.name)
		with self.assertRaises(frappe.ValidationError):
			self.convert(s, [(s.reg, 1, s.b, 40)])
		# a Dismantling Entry never converts anything by itself
		self.dismantle(s.rc, [(s.a, 3, s.reg, 3)])
		self.assertFalse(frappe.db.exists("Excess Material Conversion Item", {"excess_register": s.reg.name}))
		s.reg.reload()
		self.assertEqual((flt(s.reg.convertible_qty), flt(s.reg.converted_qty)), (3, 0))

	def test_c2_convert_to_existing_rental_item(self):
		s = self.adjusted()
		ex_before, yard_before = bin_qty(s.b, self.excess_wh), bin_qty(s.b, self.yard)
		doc = self.convert(s, [(s.reg, 2, s.b, 40)])
		self.assertEqual((doc.status, flt(doc.total_value)), ("Converted", 80))
		se = frappe.get_doc("Stock Entry", doc.stock_entry)
		self.assertEqual((se.purpose, se.docstatus, se.nxg_hire_voucher_no), ("Repack", 1, doc.name))
		self.assertEqual(bin_qty(s.b, self.excess_wh), ex_before - 2)
		self.assertEqual(bin_qty(s.b, self.yard), yard_before + 2)
		incoming = frappe.get_all("Stock Ledger Entry", filters={"voucher_no": se.name, "is_cancelled": 0, "actual_qty": [">", 0]},
			fields=["item_code", "warehouse", "actual_qty", "incoming_rate"])
		self.assertEqual([(r.item_code, r.warehouse, flt(r.actual_qty), flt(r.incoming_rate)) for r in incoming], [(s.b, self.yard, 2, 40)])
		s.reg.reload()
		self.assertEqual((flt(s.reg.converted_qty), flt(s.reg.convertible_qty)), (2, 1))
		# customer side untouched: still 3 adjusted, 2 available to the customer, nothing outstanding
		self.assertEqual((flt(s.reg.adjusted_qty), flt(s.reg.available_qty)), (3, 2))
		self.assertEqual(flt(self.contract_row(s.rc, s.a).adjusted_qty), 3)
		self.assertEqual(flt(frappe.db.get_value("Rental Contract", s.rc, "total_adjusted_qty")), 3)
		# the customer's 2 can still be returned; the reconciliation is unaffected by the conversion
		self.return_note([s.reg], qty=2)
		self.assertTrue(excess.reconcile(s.rc)["reconciled"], excess.reconcile(s.rc)["issues"])

	def test_c3_convert_to_different_item(self):
		s = self.adjusted()
		other = ensure_item(f"EX-T-{tag()}", "Converted Target Item")  # no Rental Item Profile
		with self.assertRaises(frappe.ValidationError):  # not a rental item
			self.convert(s, [(s.reg, 2, other, 30)])
		doc = self.convert(s, [(s.reg, 2, other, 30, 1)], conversion_type=CONV_DIFFERENT)  # 2 B become 1 of the other item
		row = doc.items[0]
		self.assertEqual((row.source_item_code, row.target_item_code, flt(row.conversion_qty), flt(row.target_qty), flt(row.amount)),
			(s.b, other, 2, 1, 30))
		self.assertEqual(bin_qty(other, self.yard), 1)
		se = frappe.get_doc("Stock Entry", doc.stock_entry)
		self.assertEqual(sorted((d.item_code, d.s_warehouse or "", d.t_warehouse or "", flt(d.qty)) for d in se.items),
			sorted([(s.b, self.excess_wh, "", 2), (other, "", self.yard, 1)]))
		history = get_history(register=s.reg.name)["history"]
		self.assertIn(("Excess Material Conversion Entry", doc.name, other), [(h.doctype, h.name, h.get("target_item")) for h in history])

	def test_c4_limits_and_duplicates(self):
		s = self.adjusted()
		with self.assertRaises(frappe.ValidationError):  # 4 > 3 owned
			self.convert(s, [(s.reg, 4, s.b, 40)])
		with self.assertRaises(frappe.ValidationError):  # the same row twice
			self.convert(s, [(s.reg, 1, s.b, 40), (s.reg, 1, s.b, 40)])
		first = self.convert(s, [(s.reg, 3, s.b, 40)], submit=False)
		second = self.convert(s, [(s.reg, 2, s.b, 40)], submit=False)
		first.submit()
		with self.assertRaises(frappe.ValidationError):  # processed once only
			second.submit()
		with self.assertRaises(frappe.ValidationError):  # no rate given
			self.convert(s, [(s.reg, 1, s.b, 0)])

	def test_c5_valuation_basis(self):
		s = self.adjusted()
		doc = self.convert(s, [(s.reg, 1, s.b, 0, 0, "Target Item Valuation Rate")])
		self.assertEqual(flt(doc.items[0].valuation_rate), 50)  # the item's rate in the yard (received at 50)
		doc = self.convert(s, [(s.reg, 1, s.b, 99, 0, "Zero Value")])
		self.assertEqual((flt(doc.items[0].valuation_rate), flt(doc.total_value)), (0, 0))
		rate = frappe.db.get_value("Stock Ledger Entry", {"voucher_no": doc.stock_entry, "actual_qty": [">", 0], "is_cancelled": 0}, "incoming_rate")
		self.assertEqual(flt(rate), 0)
		fresh = ensure_item(f"EX-N-{tag()}", "Never Valued")
		with self.assertRaises(frappe.ValidationError):  # nothing to take a rate from
			self.convert(s, [(s.reg, 1, fresh, 0, 0, "Target Item Valuation Rate")], conversion_type=CONV_DIFFERENT)

	def test_c6_cancel_reverses_and_protects_adjustment(self):
		s = self.adjusted()
		ex_before, yard_before = bin_qty(s.b, self.excess_wh), bin_qty(s.b, self.yard)
		doc = self.convert(s, [(s.reg, 3, s.b, 40)])
		with self.assertRaises(frappe.ValidationError):  # the adjusted excess is now rental stock
			frappe.get_doc("Dismantling Entry", s.de.name).cancel()
		doc.cancel()
		self.assertEqual((bin_qty(s.b, self.excess_wh), bin_qty(s.b, self.yard)), (ex_before, yard_before))
		self.assertEqual(frappe.db.get_value("Stock Entry", doc.stock_entry, "docstatus"), 2)
		s.reg.reload()
		self.assertEqual((flt(s.reg.converted_qty), flt(s.reg.convertible_qty)), (0, 3))
		frappe.get_doc("Dismantling Entry", s.de.name).cancel()
		s.reg.reload()
		self.assertEqual((flt(s.reg.adjusted_qty), flt(s.reg.convertible_qty), flt(s.reg.available_qty)), (0, 0, 5))

	def test_c7_target_warehouse_and_permissions(self):
		s = self.adjusted()
		with self.assertRaises(frappe.ValidationError):  # not a rental warehouse
			self.convert(s, [(s.reg, 1, s.b, 40)], target_warehouse=self.excess_wh)
		with self.assertRaises(frappe.ValidationError):
			self.convert(s, [(s.reg, 1, s.b, 40, 0, "Manual Rate", self.site_warehouse(s.rc))])
		frappe.set_user(RENTAL_USER)
		with self.assertRaises(frappe.PermissionError):
			self.convert(s, [(s.reg, 1, s.b, 40)], submit=False)


class TestExcessAbandonment(TestExcessConversion):
	"""Excess Material Abandonment: a Rental Manager approves that the customer abandoned their excess."""

	for _name in [n for n in dir(TestExcessConversion) if n.startswith("test_")]:
		locals()[_name] = None
	del _name

	def abandon(self, regs, qty=None, submit=True, **header):
		doc = make_abandonment_from_registers([r.name for r in regs])
		doc.update({"abandonment_basis": "Customer confirmed in writing", "customer_reference": "Email 18-11-2026",
			"reason": "Customer will not collect the extra material", **header})
		if qty is not None:
			for d in doc.items:
				d.abandon_qty = qty
		doc.insert()
		if submit:
			doc.submit()
		return doc

	def test_a1_manager_approves_no_stock_moves(self):
		s = self.scenario()
		before = bin_qty(s.b, self.excess_wh)
		frappe.set_user(RENTAL_USER)
		draft = self.abandon([s.reg], qty=2, submit=False)  # a Rental User records it ...
		with self.assertRaises(frappe.PermissionError):  # ... but cannot approve it
			draft.submit()
		frappe.set_user("Administrator")
		draft.reload()
		draft.submit()
		self.assertEqual((draft.status, draft.approved_by), ("Approved", "Administrator"))
		s.reg.reload()
		self.assertEqual((flt(s.reg.abandoned_qty), flt(s.reg.available_qty), flt(s.reg.convertible_qty), s.reg.status),
			(2, 3, 2, "Partly Abandoned"))
		self.assertEqual(bin_qty(s.b, self.excess_wh), before)  # nothing moved
		self.assertFalse(frappe.db.exists("Stock Entry", {"nxg_hire_voucher_no": draft.name}))
		self.assertEqual(flt(self.contract_row(s.rc, s.a).at_site_qty), 3)  # the customer's own balance is untouched
		self.assertTrue(frappe.db.exists("Comment", {"reference_name": s.rc, "content": ["like", f"%{draft.name}%abandoned%"]}))
		history = get_history(register=s.reg.name)["history"]
		self.assertIn(("Excess Material Abandonment", draft.name), [(h.doctype, h.name) for h in history])

	def test_a2_abandoned_is_no_longer_the_customers(self):
		s = self.scenario()
		self.abandon([s.reg], qty=4)
		with self.assertRaises(frappe.ValidationError):  # only 1 left to return
			self.return_note([s.reg], qty=2)
		with self.assertRaises(frappe.ValidationError):  # nor to set against outstanding material
			self.dismantle(s.rc, [(s.a, 2, s.reg, 2)])
		with self.assertRaises(frappe.ValidationError):  # nor to abandon again
			self.abandon([s.reg], qty=2)
		self.return_note([s.reg], qty=1)
		s.reg.reload()
		self.assertEqual((flt(s.reg.available_qty), s.reg.status), (0, "Closed"))
		with self.assertRaises(frappe.ValidationError):  # nothing left to abandon
			make_abandonment_from_registers([s.reg.name])
		first, other = self.scenario(), self.scenario()
		doc = make_abandonment_from_registers([first.reg.name])
		doc.update({"abandonment_basis": "Other", "reason": "test"})
		doc.append("items", {"excess_register": other.reg.name, "abandon_qty": 1})
		with self.assertRaises(frappe.ValidationError):  # another customer's register
			doc.insert()

	def test_a3_abandoned_excess_can_be_converted(self):
		s = self.scenario()
		ab = self.abandon([s.reg], qty=5)
		conv = self.convert(s, [(s.reg, 5, s.b, 40)])
		s.reg.reload()
		self.assertEqual((flt(s.reg.converted_qty), flt(s.reg.convertible_qty)), (5, 0))
		with self.assertRaises(frappe.ValidationError):  # converted: cancel the conversion first
			frappe.get_doc("Excess Material Abandonment", ab.name).cancel()
		conv.cancel()
		frappe.get_doc("Excess Material Abandonment", ab.name).cancel()
		s.reg.reload()
		self.assertEqual((flt(s.reg.abandoned_qty), flt(s.reg.available_qty), s.reg.status), (0, 5, "Available"))

	def test_a4_reconciliation_closes_without_exception(self):
		s = self.scenario()
		self.dismantle(s.rc, [(s.a, 3, s.reg, 3)])
		self.assertFalse(excess.reconcile(s.rc)["reconciled"])  # 2 B still held for the customer
		draft = self.abandon([s.reg], submit=False)
		self.assertTrue(any(draft.name in i for i in excess.reconcile(s.rc)["issues"]))
		draft.submit()
		result = excess.reconcile(s.rc)
		self.assertTrue(result["reconciled"], result["issues"])
		self.assertIsNone(result["exception"])
		frappe.get_doc("Rental Contract", s.rc).close_contract()
		self.assertEqual(frappe.db.get_value("Rental Contract", s.rc, ["status", "reconciliation_status"]), ("Completed", "Reconciled"))
		_c, rows = excess_material_register.execute({"rental_contract": s.rc})
		self.assertEqual([(flt(r.adjusted_qty), flt(r.abandoned_qty), flt(r.available_qty), flt(r.convertible_qty)) for r in rows], [(3, 2, 0, 5)])
