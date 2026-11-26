"""Subcontracting after approval: progress, completion, material custody, settlement and profitability.

    bench --site <site> run-tests --module thinknxg_rental.tests.test_subcontracting_flow
"""
import frappe
from frappe.utils import flt, nowdate

from thinknxg_rental.services import subcontract_cost
from thinknxg_rental.services import subcontracting as sc
from thinknxg_rental.tests import test_subcontracting as ts
from thinknxg_rental.tests.test_multi_warehouse import bin_qty
from thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract import make_rental_contract

SWO = "thinknxg_rental.subcontracting.doctype.subcontract_work_order.subcontract_work_order."


class TestSubcontractingFlow(ts.TestSubcontracting):
	for _name in [n for n in dir(ts.TestSubcontracting) if n.startswith("test_")]:
		locals()[_name] = None
	del _name

	# ------------------------------------------------------------------ helpers
	def doc(self, doctype, **kw):
		items = kw.pop("items")
		d = frappe.get_doc({"doctype": doctype, "posting_date": nowdate(), **kw, "items": items})
		d.insert()
		return d

	def progress(self, swo, accepted, rejected=0):
		d = frappe.get_doc({"doctype": "Subcontract Work Progress", "subcontract_work_order": swo.name, "progress_date": nowdate(),
			"items": [{"swo_item": swo.items[0].name, "accepted_qty": accepted, "rejected_qty": rejected}]})
		d.insert()
		d.submit()
		return d

	def completed_order(self, hoc, sup, qty=100, retention=10):
		w = self.swo(hoc, sup, [(0, qty, 20)])
		w.retention_percentage = retention
		w.save()
		w = self.approve(w)
		self.progress(w, qty)
		return frappe.get_doc("Subcontract Work Order", w.name)

	@property
	def kochi(self):
		return self.yard

	def stocked(self, qty=100):
		return self.item(stock=qty, inspection=0)

	def issue(self, swo, item, qty):
		a = self.doc("Subcontract Material Allocation", subcontract_work_order=swo.name, source_warehouse=self.kochi, items=[{"item_code": item, "qty": qty}])
		a.submit()
		return a

	# ------------------------------------------------------------------ progress and completion
	def test_progress_drives_status_and_cannot_exceed_order(self):
		hoc, sup = self.hoc(), self.sub()
		w = self.approve(self.swo(hoc, sup, [(0, 50)]))
		self.progress(w, 20)
		self.assertEqual(frappe.db.get_value("Subcontract Work Order", w.name, "status"), "Partially Completed")
		with self.assertRaises(frappe.ValidationError):
			self.progress(w, 31)
		self.progress(w, 30)
		self.assertEqual(frappe.db.get_value("Subcontract Work Order", w.name, "status"), "Completed")

	def test_completion_certification_and_verification(self):
		hoc, sup = self.hoc(), self.sub()
		w = self.completed_order(hoc, sup, 10)
		scr = frappe.get_doc({"doctype": "Subcontract Completion Report", "subcontract_work_order": w.name, "completion_date": nowdate()})
		scr.insert()
		scr.submit()
		self.assertEqual(scr.certified_value, 200)
		self.assertEqual(frappe.db.get_value("Subcontract Work Order", w.name, "status"), "Pending Final Verification")
		frappe.get_attr(SWO + "verify_completion")(w.name)
		frappe.get_attr(SWO + "close")(w.name)
		self.assertEqual(frappe.db.get_value("Subcontract Work Order", w.name, "status"), "Closed")

	def test_completion_report_refused_before_work_is_complete(self):
		hoc, sup = self.hoc(), self.sub()
		w = self.approve(self.swo(hoc, sup, [(0, 10)]))
		scr = frappe.get_doc({"doctype": "Subcontract Completion Report", "subcontract_work_order": w.name, "completion_date": nowdate()})
		with self.assertRaises(frappe.ValidationError):
			scr.insert()

	def test_approval_steps_are_role_gated_on_the_server(self):
		hoc, sup = self.hoc(), self.sub()
		w = self.swo(hoc, sup, [(0, 10)])
		frappe.get_attr(SWO + "submit_for_approval")(w.name)
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				frappe.get_attr(SWO + "approve")(w.name)
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------------------------------------ 5. material reconciliation
	def test_material_issue_and_reconciliation(self):
		hoc, sup = self.hoc(), self.sub()
		w = self.approve(self.swo(hoc, sup, [(0, 10)]))
		item = self.stocked(100)
		self.issue(w, item, 100)
		custody = sc.custody_warehouse(w.company)
		self.assertEqual((bin_qty(item, self.kochi), bin_qty(item, custody)), (0, 100))
		self.assertEqual(sc.issued_balance(w.name)[item].outstanding, 100)
		ret = self.doc("Subcontract Material Return", subcontract_work_order=w.name, return_warehouse=self.kochi,
			items=[{"item_code": item, "installed_qty": 70, "returned_qty": 25, "damaged_qty": 3, "missing_qty": 2, "recovery_rate": 40}])
		ret.submit()
		self.assertEqual(flt(ret.total_recovery), 200)
		b = sc.issued_balance(w.name)[item]
		self.assertEqual((b.issued, b.installed, b.returned, b.damaged, b.missing, b.outstanding), (100, 70, 25, 3, 2, 0))
		self.assertEqual((bin_qty(item, self.kochi), bin_qty(item, custody)), (25, 0))
		ledger = frappe.db.sql("select sum(qty) from `tabRental Ownership Ledger` where subcontract_work_order = %s and item_code = %s", (w.name, item))[0][0]
		self.assertEqual(flt(ledger), 0)

	def test_cannot_reconcile_more_than_issued_or_unissued_item(self):
		hoc, sup = self.hoc(), self.sub()
		w = self.approve(self.swo(hoc, sup, [(0, 10)]))
		item = self.stocked(50)
		self.issue(w, item, 50)
		with self.assertRaises(frappe.ValidationError):
			self.doc("Subcontract Material Return", subcontract_work_order=w.name, return_warehouse=self.kochi, items=[{"item_code": item, "returned_qty": 51}])
		with self.assertRaises(frappe.ValidationError):
			self.doc("Subcontract Material Return", subcontract_work_order=w.name, return_warehouse=self.kochi, items=[{"item_code": self.stocked(5), "returned_qty": 1}])

	def test_issue_cannot_exceed_free_stock_or_be_cancelled_after_return(self):
		hoc, sup = self.hoc(), self.sub()
		w = self.approve(self.swo(hoc, sup, [(0, 10)]))
		item = self.stocked(10)
		with self.assertRaises(frappe.ValidationError):
			self.issue(w, item, 11)
		a = self.issue(w, item, 10)
		r = self.doc("Subcontract Material Return", subcontract_work_order=w.name, return_warehouse=self.kochi, items=[{"item_code": item, "returned_qty": 4}])
		r.submit()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Subcontract Material Allocation", a.name).cancel()
		frappe.get_doc("Subcontract Material Return", r.name).cancel()
		frappe.get_doc("Subcontract Material Allocation", a.name).cancel()
		self.assertEqual(bin_qty(item, self.kochi), 10)

	def test_work_order_with_material_cannot_be_cancelled_or_verified(self):
		hoc, sup = self.hoc(), self.sub()
		w = self.approve(self.swo(hoc, sup, [(0, 10)]))
		item = self.stocked(10)
		self.issue(w, item, 10)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Subcontract Work Order", w.name).cancel()

	# ------------------------------------------------------------------ 6. settlement and invoice
	def settle(self, w, qty=None, **kw):
		items = [{"swo_item": w.items[0].name, "qty": qty if qty is not None else w.items[0].qty}]
		d = self.doc("Subcontract Settlement", subcontract_work_order=w.name, items=items, **kw)
		d.submit()
		return frappe.get_doc("Subcontract Settlement", d.name)

	def test_settlement_creates_one_purchase_invoice_without_duplicates(self):
		hoc, sup = self.hoc(), self.sub()
		w = self.completed_order(hoc, sup, 100, retention=10)
		s = self.settle(w, 60)
		self.assertEqual((flt(s.certified_value), flt(s.retention_amount), flt(s.final_payable)), (1200, 120, 1080))
		pi = frappe.get_doc("Purchase Invoice", s.purchase_invoice)
		self.assertEqual((pi.docstatus, flt(pi.grand_total), pi.subcontract_work_order), (1, 1080, w.name))
		self.assertEqual(flt(frappe.db.get_value("Subcontract Work Item", w.items[0].name, "invoiced_qty")), 60)
		with self.assertRaises(frappe.ValidationError):
			self.settle(w, 41)
		s2 = self.settle(w, 40)
		self.assertEqual(flt(frappe.db.get_value("Subcontract Work Item", w.items[0].name, "invoiced_qty")), 100)
		self.assertNotEqual(s.purchase_invoice, s2.purchase_invoice)
		with self.assertRaises(frappe.ValidationError):
			self.settle(w, 1)

	def test_manual_purchase_invoice_against_work_order_is_refused(self):
		hoc, sup = self.hoc(), self.sub()
		w = self.completed_order(hoc, sup, 10)
		pi = frappe.new_doc("Purchase Invoice")
		pi.update({"company": w.company, "supplier": sup, "bill_date": nowdate(), "subcontract_work_order": w.name,
			"items": [{"item_code": w.items[0].job_type, "qty": 1, "rate": 5}]})
		with self.assertRaises(frappe.ValidationError):
			pi.insert()

	def test_deductions_and_cancel_restore_quantity(self):
		hoc, sup = self.hoc(), self.sub()
		w = self.completed_order(hoc, sup, 100, retention=5)
		s = self.settle(w, 100, penalties=100, other_deductions=50)
		self.assertEqual(flt(s.final_payable), 2000 - 100 - 100 - 50)
		self.assertEqual(flt(frappe.db.get_value("Purchase Invoice", s.purchase_invoice, "grand_total")), 1750)
		s.cancel()
		self.assertEqual(flt(frappe.db.get_value("Subcontract Work Item", w.items[0].name, "invoiced_qty")), 0)
		self.assertEqual(frappe.db.get_value("Purchase Invoice", s.purchase_invoice, "docstatus"), 2)
		self.settle(w, 100)

	def test_damage_recovery_flows_into_settlement(self):
		hoc, sup = self.hoc(), self.sub()
		w = self.completed_order(hoc, sup, 100, retention=0)
		item = self.stocked(10)
		self.issue(w, item, 10)
		self.doc("Subcontract Material Return", subcontract_work_order=w.name, return_warehouse=self.kochi,
			items=[{"item_code": item, "returned_qty": 5, "damaged_qty": 3, "missing_qty": 2, "recovery_rate": 30}]).submit()
		s = self.settle(w, 100)
		self.assertEqual((flt(s.damage_recovery), flt(s.final_payable)), (150, 1850))

	def test_advance_is_recovered_on_the_settlement_invoice(self):
		hoc, sup = self.hoc(), self.sub()
		w = self.swo(hoc, sup, [(0, 100, 20)])
		w.advance_percentage = 10
		w.save()
		w = self.approve(w)
		self.assertEqual(flt(w.advance_amount), 200)
		pe_name = frappe.get_attr("thinknxg_rental.subcontracting.doctype.subcontract_work_order.subcontract_work_order.make_advance_payment")(w.name, 200)
		pe = frappe.get_doc("Payment Entry", pe_name)
		self.assertEqual(pe.subcontract_work_order, w.name)
		pe.submit()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Payment Entry", "payment_type": "Pay", "party_type": "Supplier", "party": sup, "company": w.company, "posting_date": nowdate(),
				"paid_from": pe.paid_from, "paid_to": pe.paid_to, "paid_amount": 1, "received_amount": 1, "source_exchange_rate": 1, "target_exchange_rate": 1,
				"paid_from_account_currency": pe.paid_from_account_currency, "paid_to_account_currency": pe.paid_to_account_currency,
				"subcontract_work_order": w.name}).insert()
		w = frappe.get_doc("Subcontract Work Order", w.name)
		self.progress(w, 100)
		s = self.settle(frappe.get_doc("Subcontract Work Order", w.name), 100)
		self.assertEqual(flt(s.advance_recovery), 200)
		self.assertEqual(flt(frappe.db.get_value("Purchase Invoice", s.purchase_invoice, "outstanding_amount")), 1800)

	# ------------------------------------------------------------------ 9. customer billing is independent
	def test_profitability_counts_each_cost_once_and_customer_billing_is_independent(self):
		hoc, sup = self.hoc(), self.sub()
		rc = make_rental_contract(hoc.name)
		rc.insert()
		rc.submit()
		frappe.db.set_value("Rental Contract", rc.name, "total_billed_amount", 5000)
		before = subcontract_cost.profitability(hoc.name)
		self.assertEqual((before["customer_revenue"], before["subcontract_cost"], before["net_profit"]), (5000, 0, 5000))
		w = self.completed_order(hoc, sup, 100, retention=10)
		self.settle(w, 100, penalties=100)
		after = subcontract_cost.profitability(hoc.name)
		self.assertEqual((after["customer_revenue"], after["subcontract_cost"], after["net_profit"]), (5000, 1900, 3100))
		self.assertEqual(after["retention_held"], 200)
		self.assertEqual(sc.subcontract_summary(hoc.name)["actual_cost"], 2000)
