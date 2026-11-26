"""Subcontracting of Hire Order Contracts: allocation, approval, cancel/amend.

    bench --site <site> run-tests --module thinknxg_rental.tests.test_subcontracting
"""
import frappe
from frappe.utils import flt, nowdate

from thinknxg_rental.services import subcontracting as sc
from thinknxg_rental.tests import test_damage_charges as tdc
from thinknxg_rental.services.deal_flow import make_hire_order_contract_from_quotation


class TestSubcontracting(tdc.TestDamageCharges):
	for _name in [n for n in dir(tdc.TestDamageCharges) if n.startswith("test_")]:
		locals()[_name] = None
	del _name

	# ------------------------------------------------------------------ helpers
	def job(self):
		code = f"SC-JOB-{tdc.tag()}"
		frappe.get_doc({"doctype": "Item", "item_code": code, "item_name": "Sub Job", "item_group": tdc._leaf("Item Group"),
			"stock_uom": "Nos", "is_stock_item": 0}).insert()
		frappe.get_doc({"doctype": "Job Type", "item_code": code, "job_type_name": code}).insert()
		return code

	def hoc(self, qtys=(100,)):
		jobs = [self.job() for _ in qtys]
		q = self.quotation([{"item_code": j, "qty": n, "rate": 50, "uom": "Nos", "nxg_included_days": 30, "nxg_excess_basis": "Daily",
			"nxg_excess_rate": 10} for j, n in zip(jobs, qtys)], deal_type="Hire Order Contract")
		self.submit_quotation(q)
		doc = make_hire_order_contract_from_quotation(q, args={"rental_site": self.site_from(q)})
		doc.order_date = nowdate()
		doc.insert()
		doc.submit()
		return doc

	def sub(self, approved=True):
		name = f"Sub-{tdc.tag()}"
		doc = frappe.get_doc({"doctype": "Supplier", "supplier_name": name, "supplier_group": tdc._leaf("Supplier Group") if False else frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
			"is_subcontractor": 1, "subcontractor_type": "Both", "subcontractor_approval_status": "Approved" if approved else "Pending"})
		doc.insert()
		return doc.name

	def swo(self, hoc, supplier, rows, allocation_type="Partial", subcontract_type="Labour", category="Labour", save=True, **kw):
		"""rows: (job line index, qty[, rate])"""
		items = []
		for r in rows:
			line = hoc.items[r[0]]
			items.append({"hoc_item": line.name, "job_type": line.job_type, "qty": r[1], "rate": r[2] if len(r) > 2 else 20,
				"uom": "Nos", "work_category": kw.get("category", category)})
		doc = frappe.get_doc({"doctype": "Subcontract Work Order", "hire_order_contract": hoc.name, "supplier": supplier,
			"allocation_type": allocation_type, "subcontract_type": subcontract_type, "items": items})
		if save:
			doc.insert()
		return doc

	def approve(self, doc):
		sc_wo = "thinknxg_rental.subcontracting.doctype.subcontract_work_order.subcontract_work_order"
		frappe.get_attr(f"{sc_wo}.submit_for_approval")(doc.name)
		frappe.get_attr(f"{sc_wo}.approve")(doc.name)
		return frappe.get_doc("Subcontract Work Order", doc.name)

	def avail(self, hoc, idx=0):
		return flt(sc.line_availability(hoc.name)[idx].available_qty)

	# ------------------------------------------------------------------ 1. partial labour allocation
	def test_partial_labour_allocation(self):
		hoc, sup = self.hoc(), self.sub()
		a = self.approve(self.swo(hoc, sup, [(0, 40)]))
		self.assertEqual((a.status, a.docstatus), ("Approved", 1))
		self.assertEqual(self.avail(hoc), 60)
		self.approve(self.swo(hoc, sup, [(0, 30)]))
		self.assertEqual(self.avail(hoc), 30)
		self.assertEqual(sc.subcontract_summary(hoc.name)["subcontracted_qty"], 70)

	def test_draft_does_not_consume_quantity(self):
		hoc, sup = self.hoc(), self.sub()
		self.swo(hoc, sup, [(0, 90)])
		self.assertEqual(self.avail(hoc), 100)
		d2 = self.swo(hoc, sup, [(0, 90)])
		first = frappe.get_all("Subcontract Work Order", {"hire_order_contract": hoc.name}, pluck="name", order_by="creation")[0]
		self.approve(frappe.get_doc("Subcontract Work Order", first))
		with self.assertRaises(frappe.ValidationError):
			self.approve(d2)

	# ------------------------------------------------------------------ 2. full allocation
	def test_full_allocation_blocks_more(self):
		hoc, sup = self.hoc(), self.sub()
		self.approve(self.swo(hoc, sup, [(0, 100)], allocation_type="Full", subcontract_type="Equipment", category="Equipment"))
		self.assertEqual(self.avail(hoc), 0)
		with self.assertRaises(frappe.ValidationError):
			self.swo(hoc, sup, [(0, 1)])

	def test_full_must_cover_whole_balance(self):
		hoc, sup = self.hoc(), self.sub()
		doc = self.swo(hoc, sup, [(0, 60)], allocation_type="Full")
		with self.assertRaises(frappe.ValidationError):
			self.approve(doc)

	# ------------------------------------------------------------------ 3. three subcontractors
	def test_three_subcontractors(self):
		hoc = self.hoc()
		for n in (30, 30, 40):
			self.approve(self.swo(hoc, self.sub(), [(0, n)]))
		s = sc.subcontract_summary(hoc.name)
		self.assertEqual((s["subcontractors"], s["work_orders"], s["balance_qty"]), (3, 3, 0))

	# ------------------------------------------------------------------ 4. labour and equipment cost independently
	def test_labour_and_equipment_costed_independently(self):
		hoc, sup = self.hoc(), self.sub()
		doc = self.swo(hoc, sup, [(0, 10, 20)], subcontract_type="Labour and Equipment")
		doc.items[0].work_category = "Labour"
		doc.append("items", {"hoc_item": hoc.items[0].name, "job_type": hoc.items[0].job_type, "qty": 10, "rate": 75, "uom": "Nos",
			"work_category": "Equipment", "equipment_ownership": "Subcontractor Supplied"})
		doc.save()
		self.assertEqual((flt(doc.labour_cost), flt(doc.equipment_cost), flt(doc.final_contract_value)), (200, 750, 950))

	# ------------------------------------------------------------------ 7. over-allocation
	def test_over_allocation_rejected_on_save_and_approval(self):
		hoc, sup = self.hoc(), self.sub()
		with self.assertRaises(frappe.ValidationError):
			self.swo(hoc, sup, [(0, 101)])
		self.approve(self.swo(hoc, sup, [(0, 70)]))
		with self.assertRaises(frappe.ValidationError):
			self.swo(hoc, sup, [(0, 31)])

	def test_approval_rechecks_on_server(self):
		"""A draft that was fine when saved is refused at approval once the balance has gone."""
		hoc, sup = self.hoc(), self.sub()
		x, y = self.swo(hoc, sup, [(0, 60)]), self.swo(hoc, sup, [(0, 60)])
		self.approve(x)
		with self.assertRaises(frappe.ValidationError):
			self.approve(y)
		self.assertEqual(frappe.db.get_value("Subcontract Work Order", y.name, "docstatus"), 0)

	# ------------------------------------------------------------------ 8. status cannot be bypassed
	def test_cannot_submit_directly_or_edit_status(self):
		hoc, sup = self.hoc(), self.sub()
		doc = self.swo(hoc, sup, [(0, 10)])
		with self.assertRaises(frappe.PermissionError):
			doc.submit()
		doc.reload()
		doc.status = "Approved"
		doc.save()
		self.assertEqual(frappe.db.get_value("Subcontract Work Order", doc.name, "status"), "Draft")

	def test_unapproved_subcontractor_refused(self):
		hoc = self.hoc()
		doc = self.swo(hoc, self.sub(approved=False), [(0, 10)])
		with self.assertRaises(frappe.ValidationError):
			self.approve(doc)

	# ------------------------------------------------------------------ 10. cancel releases quantity
	def test_cancel_releases_quantity_and_keeps_history(self):
		hoc, sup = self.hoc(), self.sub()
		a = self.approve(self.swo(hoc, sup, [(0, 40)]))
		self.assertEqual(self.avail(hoc), 60)
		a.cancel()
		self.assertEqual(self.avail(hoc), 100)
		self.assertEqual(frappe.db.get_value("Subcontract Work Order", a.name, ["docstatus", "status"]), (2, "Cancelled"))
		b = frappe.copy_doc(a)
		b.docstatus, b.amended_from = 0, a.name
		b.insert()
		self.assertTrue(b.name.startswith(a.name.split("-")[0]))
		self.approve(b)
		self.assertEqual(self.avail(hoc), 60)
