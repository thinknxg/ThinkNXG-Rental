"""Contract closure needs every return inspected and every lost and damaged item settled
(services/closure.py), and lost units settled on a Damage Settlement stop being billed at the off-hire.

    bench --site <site> run-tests --module thinknxg_rental.tests.test_contract_closure
"""
import frappe
from frappe.utils import add_days, flt, getdate, nowdate

from thinknxg_rental.services import closure, ledger
from thinknxg_rental.tests import test_excess_material as tem
from thinknxg_rental.thinknxg_rental.doctype.hire_off_hire_note.hire_off_hire_note import make_damage_settlement, make_inspection
from thinknxg_rental.thinknxg_rental.doctype.rental_damage_settlement.rental_damage_settlement import make_sales_invoice


class TestContractClosure(tem.TestExcessMaterial):
	# the parent's tests run in their own class
	for _name in [n for n in dir(tem.TestExcessMaterial) if n.startswith("test_")]:
		locals()[_name] = None
	del _name

	# ------------------------------------------------------------------ fixtures
	def returned(self, returned, lost=0, inspect=False, delivered=10):
		"""Contract with one item: delivered 20 days ago, off-hired 10 days ago."""
		item = self.item()
		if inspect:
			old = frappe.db.get_single_value("Rental Settings", "inspection_required")
			frappe.db.set_single_value("Rental Settings", "inspection_required", 1)
			self.addCleanup(frappe.db.set_single_value, "Rental Settings", "inspection_required", old)
			frappe.db.set_value("Rental Item Profile", item, "inspection_required", 1)
			frappe.clear_document_cache("Rental Item Profile", item)
		rc = self.contract([(item, delivered)])
		self.deliver(rc, [(item, delivered)], days_ago=20)
		note = self.off_hire(rc, [(item, {"returned_qty": returned, "lost_qty": lost, "requires_inspection": 1 if inspect else 0})], days_ago=10)
		return frappe._dict(item=item, rc=rc, note=frappe.get_doc("Hire Off-Hire Note", note.name))

	def inspect(self, s, good, repairable=0, damaged=0):
		doc = make_inspection(s.note.name)
		doc.items[0].update({"good_qty": good, "repairable_qty": repairable, "damaged_qty": damaged})
		doc.insert()
		doc.submit()
		return doc

	def settle(self, s, submit=True, invoice=True, liability=100, rows=None):
		if rows is None:
			doc = make_damage_settlement(s.note.name)
		else:
			doc = frappe.get_doc({"doctype": "Rental Damage Settlement", "company": s.note.company, "hire_off_hire_note": s.note.name,
				"rental_contract": s.rc, "customer": s.note.customer, "posting_date": nowdate()})
			for classification, qty in rows:
				doc.append("items", {"item_code": s.item, "classification": classification, "qty": qty, "rate": 10,
					"liability_percent": liability, "ownership": "Own"})
		for d in doc.items:
			d.liability_percent = liability
			d.rate = d.rate or 10
		doc.insert()
		if submit:
			doc.submit()
			if invoice and flt(doc.grand_total) > 0:
				si = frappe.get_doc("Sales Invoice", make_sales_invoice(doc.name))
				if si.docstatus == 0:
					si.submit()
		return frappe.get_doc("Rental Damage Settlement", doc.name)

	def close(self, rc):
		frappe.get_doc("Rental Contract", rc).close_contract()
		return frappe.db.get_value("Rental Contract", rc, "status")

	def blocked(self, rc, *expect):
		with self.assertRaises(frappe.ValidationError) as cm:
			self.close(rc)
		for text in expect:
			self.assertIn(text, str(cm.exception))
		self.assertNotEqual(frappe.db.get_value("Rental Contract", rc, "status"), "Completed")

	# ------------------------------------------------------------------ inspection
	def test_inspection_pending_blocks_closure(self):
		s = self.returned(10, inspect=True)
		self.blocked(s.rc, "Inspection pending", s.note.name)
		self.inspect(s, good=10)
		self.assertEqual(closure.pending(s.rc), [])
		self.assertEqual(self.close(s.rc), "Completed")

	def test_api_closure_is_refused_too(self):
		"""The REST / desk route (run_doc_method) goes through the same server check, whatever the UI shows."""
		from frappe.handler import run_doc_method

		s = self.returned(10, inspect=True)
		frappe.local.request = frappe._dict(method="POST")
		try:
			with self.assertRaises(frappe.ValidationError):
				run_doc_method("close_contract", dt="Rental Contract", dn=s.rc)
		finally:
			del frappe.local.request
		self.assertNotEqual(frappe.db.get_value("Rental Contract", s.rc, "status"), "Completed")

	# ------------------------------------------------------------------ damage settlement
	def test_lost_material_must_be_settled_and_invoiced(self):
		s = self.returned(7, lost=3)
		self.blocked(s.rc, "Damage settlement pending", "3 " + s.item + " lost")
		draft = self.settle(s, submit=False)
		self.blocked(s.rc, draft.name, "draft")
		draft.submit()
		self.blocked(s.rc, draft.name, "not invoiced")
		si = frappe.get_doc("Sales Invoice", make_sales_invoice(draft.name))
		if si.docstatus == 0:
			si.submit()
		self.assertEqual(frappe.db.get_value("Rental Damage Settlement", draft.name, "status"), "Invoiced")
		self.assertEqual(self.close(s.rc), "Completed")

	def test_partial_settlement_still_blocks(self):
		s = self.returned(7, lost=3)
		self.settle(s, rows=[("Lost", 2)])
		self.blocked(s.rc, "1 " + s.item + " lost not settled")
		self.settle(s, rows=[("Lost", 1)])
		self.assertEqual(self.close(s.rc), "Completed")

	def test_damaged_from_inspection_must_be_settled(self):
		s = self.returned(10, inspect=True)
		self.inspect(s, good=6, repairable=3, damaged=1)
		self.blocked(s.rc, "4 " + s.item + " damaged")
		self.settle(s)
		self.assertEqual(self.close(s.rc), "Completed")

	def test_waived_settlement_counts_as_completed(self):
		"""Nothing to invoice (liability waived): the settlement is complete once submitted."""
		s = self.returned(7, lost=3)
		st = self.settle(s, liability=0)
		self.assertEqual((flt(st.grand_total), st.status), (0, "To Invoice"))
		self.assertEqual(self.close(s.rc), "Completed")

	def test_exception_does_not_bypass_settlement(self):
		s = self.returned(7, lost=3)
		frappe.get_doc("Rental Contract", s.rc).approve_reconciliation_exception("Manager says close it")
		self.blocked(s.rc, "Damage settlement pending")
		project = frappe.get_doc({"doctype": "Project", "project_name": f"Closure {tem.tag()}", "company": self.company}).insert()
		frappe.db.set_value("Rental Contract", s.rc, "project", project.name)
		project.status = "Completed"
		with self.assertRaises(frappe.ValidationError):
			project.save()

	def test_clean_return_closes_as_before(self):
		s = self.returned(10)
		self.assertEqual(self.close(s.rc), "Completed")

	# ------------------------------------------------------------------ settlement quantities
	def test_settlement_cannot_exceed_the_return(self):
		s = self.returned(7, lost=3)
		with self.assertRaises(frappe.ValidationError):  # 3 lost + 0 still at site
			self.settle(s, rows=[("Lost", 4)])
		with self.assertRaises(frappe.ValidationError):  # only 7 came back
			self.settle(s, rows=[("Repairable", 8)])
		self.settle(s, rows=[("Lost", 3)])
		with self.assertRaises(frappe.ValidationError):  # already settled
			self.settle(s, rows=[("Lost", 1)])
		p = self.returned(5, inspect=True)
		with self.assertRaises(frappe.ValidationError):  # inspection first
			self.settle(p, rows=[("Repairable", 1)])

	# ------------------------------------------------------------------ rental stops for settled loss
	def test_loss_settled_while_at_site_stops_rental_at_the_off_hire(self):
		"""Off-hire returned 7 of 10; the other 3 are settled as lost later. They used to stay at site and be
		billed to the current date; now the settlement records the loss and rental stops at the note's
		last billable day."""
		s = self.returned(7)
		site_wh = self.site_warehouse(s.rc)
		self.assertEqual(flt(self.contract_row(s.rc, s.item).at_site_qty), 3)
		before = tem.bin_qty(s.item, site_wh)
		st = self.settle(s, rows=[("Lost", 3)])
		self.assertEqual(flt(st.items[0].recorded_loss_qty), 3)
		self.assertTrue(st.loss_stock_entry)
		self.assertEqual(flt(self.contract_row(s.rc, s.item).at_site_qty), 0)
		self.assertEqual(tem.bin_qty(s.item, site_wh), before - 3)
		loss = frappe.get_all("Rental Ownership Ledger", filters={"voucher_no": st.name}, fields=["movement_type", "qty", "billing_date"])
		self.assertEqual([(r.movement_type, flt(r.qty), getdate(r.billing_date)) for r in loss],
			[("Loss", -3, getdate(add_days(s.note.last_billable_date, 1)))])
		self.assertEqual(self.close(s.rc), "Completed")
		last = frappe.db.get_value("Rental Contract", s.rc, "last_billed_upto")
		self.assertEqual(getdate(last), getdate(s.note.last_billable_date))  # not today
		lines = frappe.get_all("Rental Billing Schedule Item", filters={"parent": ["in", frappe.get_all(
			"Rental Billing Schedule", filters={"rental_contract": s.rc}, pluck="name")]}, fields=["to_date"])
		self.assertTrue(lines)
		self.assertTrue(all(getdate(l.to_date) <= getdate(s.note.last_billable_date) for l in lines))
		self.assertLess(getdate(s.note.last_billable_date), getdate(nowdate()))

	def test_cancelling_a_settlement_reverses_its_recorded_loss(self):
		s = self.returned(7)
		site_wh = self.site_warehouse(s.rc)
		before = tem.bin_qty(s.item, site_wh)
		st = self.settle(s, rows=[("Lost", 3)], invoice=False)
		st.cancel()
		self.assertEqual(flt(self.contract_row(s.rc, s.item).at_site_qty), 3)
		self.assertEqual(tem.bin_qty(s.item, site_wh), before)
		self.assertFalse(frappe.db.exists("Rental Ownership Ledger", {"voucher_no": st.name}))
		self.assertEqual(ledger.get_site_balance(s.rc).get((s.item, "Own", "")), 3)

	def test_reconciliation_view_lists_closure_issues(self):
		s = self.returned(7, lost=3)
		result = frappe.get_doc("Rental Contract", s.rc).get_reconciliation()
		self.assertTrue(any(s.note.name in i for i in result["closure_issues"]))
		self.assertEqual(frappe.get_doc("Rental Contract", s.rc).get_closure_blockers(), result["closure_issues"])
