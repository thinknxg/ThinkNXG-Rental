"""Subcontracting v2: agreements, work orders without a Hire Order Contract, the subcontractor portal (data isolation,
access levels, submissions), daily progress, inspections, material requests, variations, invoice submissions and the
Command Center endpoints.

    bench --site <site> run-tests --module thinknxg_rental.tests.test_subcontracting_portal
"""
import frappe
from frappe.utils import add_days, flt, nowdate

from thinknxg_rental.command_center import subcontracting as ccs
from thinknxg_rental.portal import subcontractor as portal
from thinknxg_rental.services import subcontracting as sc
from thinknxg_rental.tests import test_subcontracting as ts
from thinknxg_rental.tests.test_multi_warehouse import bin_qty

D = "thinknxg_rental.subcontracting.doctype."
SWO = D + "subcontract_work_order.subcontract_work_order."
AG = D + "subcontract_agreement.subcontract_agreement."
DP = D + "subcontract_daily_progress.subcontract_daily_progress."
MR = D + "subcontract_material_request.subcontract_material_request."
VR = D + "subcontract_variation.subcontract_variation."
INV = D + "subcontractor_invoice_submission.subcontractor_invoice_submission."
WP = D + "subcontract_work_progress.subcontract_work_progress."
call = lambda path, **kw: frappe.get_attr(path)(**kw)  # noqa: E731


class TestSubcontractingPortal(ts.TestSubcontracting):
	for _name in [n for n in dir(ts.TestSubcontracting) if n.startswith("test_")]:
		locals()[_name] = None
	del _name

	def setUp(self):
		super().setUp() if hasattr(super(), "setUp") else None
		frappe.set_user("Administrator")
		s = frappe.get_single("Subcontracting Settings")
		s.portal_enabled = 1
		s.claim_item = s.claim_item or self.job()
		s.save()

	def tearDown(self):
		frappe.set_user("Administrator")

	# ------------------------------------------------------------------ helpers
	def released(self, hoc=None, sup=None, qty=100, rate=20):
		hoc, sup = hoc or self.hoc(), sup or self.sub()
		w = self.approve(self.swo(hoc, sup, [(0, qty, rate)]))
		call(SWO + "send_to_subcontractor", name=w.name)
		return frappe.get_doc("Subcontract Work Order", w.name)

	def portal_user(self, supplier, level="Commercial"):
		email = f"{frappe.generate_hash(length=8)}@sub.example.com"
		acc = frappe.get_doc({"doctype": "Subcontractor Portal Access", "supplier": supplier, "email": email, "full_name": "Site Contact",
			"access_level": level, "enabled": 1}).insert()
		return acc.user

	def as_user(self, user):
		frappe.set_user(user)
		frappe.form_dict.pop("supplier", None)

	def accepted(self, swo, qty):
		d = frappe.get_doc({"doctype": "Subcontract Work Progress", "subcontract_work_order": swo.name, "progress_date": nowdate(),
			"items": [{"swo_item": swo.items[0].name, "accepted_qty": qty}]}).insert()
		d.submit()
		return d

	# ------------------------------------------------------------------ master and agreement
	def test_approval_status_only_through_manager_method_and_compliance(self):
		sup = self.sub(approved=False)
		doc = frappe.get_doc("Supplier", sup)
		doc.append("compliance_documents", {"document_type": "Insurance Certificate", "document_no": "INS-1", "issue_date": add_days(nowdate(), -400),
			"expiry_date": add_days(nowdate(), -1)})
		doc.save()
		self.assertEqual(frappe.get_doc("Supplier", sup).compliance_documents[0].compliance_status, "Expired")
		with self.assertRaisesRegex(frappe.ValidationError, "Renew the expired"):
			sc.approve_subcontractor(sup)
		doc = frappe.get_doc("Supplier", sup)
		doc.compliance_documents[0].expiry_date = add_days(nowdate(), 365)
		doc.save()
		self.assertEqual(sc.approve_subcontractor(sup), "Approved")
		user = self.portal_user(sup)
		self.as_user(user)
		with self.assertRaises(frappe.PermissionError):
			sc.approve_subcontractor(sup, "Suspended")

	def test_agreement_rates_are_copied_and_snapshotted(self):
		sup, job = self.sub(), None
		hoc = self.hoc()
		job = hoc.items[0].job_type
		ag = frappe.get_doc({"doctype": "Subcontract Agreement", "supplier": sup, "company": hoc.company, "agreement_type": "Unit Rate",
			"start_date": add_days(nowdate(), -1), "end_date": add_days(nowdate(), 90), "retention_percentage": 7,
			"rates": [{"rate_type": "Labour", "item_code": job, "rate": 33}]}).insert()
		with self.assertRaises(frappe.PermissionError):
			ag.submit()
		call(AG + "submit_for_approval", name=ag.name)
		self.assertEqual(call(AG + "approve", name=ag.name), "Active")
		w = self.swo(hoc, sup, [(0, 10, 0)], save=False)
		w.agreement = ag.name
		w.insert()
		self.assertEqual((flt(w.items[0].rate), flt(w.retention_percentage)), (33, 7))
		w = self.approve(w)
		frappe.db.set_value("Subcontract Agreement Rate", {"parent": ag.name}, "rate", 99)   # the agreement changes later
		self.assertEqual(flt(frappe.get_doc("Subcontract Work Order", w.name).items[0].rate), 33)

	def test_work_order_without_hire_order_contract(self):
		sup, job = self.sub(), self.job()
		company = frappe.db.get_single_value("Rental Settings", "company")
		w = frappe.get_doc({"doctype": "Subcontract Work Order", "supplier": sup, "company": company, "allocation_type": "Partial",
			"subcontract_type": "Labour", "work_description": "Façade cleaning", "items": [{"job_type": job, "qty": 5, "rate": 10, "work_category": "Labour"}]}).insert()
		w = self.approve(w)
		self.assertEqual((w.status, flt(w.final_contract_value)), ("Approved", 50))
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Subcontract Work Order", "supplier": sup, "company": company, "allocation_type": "Partial", "subcontract_type": "Labour",
				"items": [{"qty": 5, "rate": 10, "work_category": "Labour"}]}).insert()

	# ------------------------------------------------------------------ portal: visibility, isolation, access level
	def test_portal_sees_only_released_own_work_orders(self):
		hoc = self.hoc()
		a, b = self.sub(), self.sub()
		ua, ub = self.portal_user(a), self.portal_user(b)
		draft = self.approve(self.swo(hoc, a, [(0, 10)]))
		self.as_user(ua)
		self.assertEqual(portal.work_orders()["rows"], [])          # approved but not yet sent
		with self.assertRaises(frappe.PermissionError):
			portal.work_order(draft.name)
		frappe.set_user("Administrator")
		call(SWO + "send_to_subcontractor", name=draft.name)
		self.as_user(ua)
		self.assertEqual([r["name"] for r in portal.work_orders()["rows"]], [draft.name])
		self.as_user(ub)
		self.assertEqual(portal.work_orders()["rows"], [])
		for fn in (lambda: portal.work_order(draft.name), lambda: portal.respond_work_order(draft.name, "accept"),
				lambda: portal.submit_progress(draft.name, [{"swo_item": draft.items[0].name, "qty_done": 1}]),
				lambda: portal.messages(draft.name)):
			with self.assertRaises(frappe.PermissionError):
				fn()
		frappe.form_dict["supplier"] = a                            # asking for another supplier's account is refused too
		with self.assertRaises(frappe.PermissionError):
			portal.work_orders()
		frappe.form_dict.pop("supplier")

	def test_operational_contact_never_receives_rates_or_invoices(self):
		w = self.released()
		user = self.portal_user(w.supplier, "Operational")
		self.as_user(user)
		d = portal.work_order(w.name)
		self.assertNotIn("rate", d["items"][0])
		self.assertNotIn("final_contract_value", d["doc"])
		self.assertNotIn("final_contract_value", portal.work_orders()["rows"][0])
		for fn in (lambda: portal.billable(w.name), lambda: portal.invoices(), lambda: portal.payments(),
				lambda: portal.submit_invoice(w.name, "X1", nowdate(), [{"swo_item": w.items[0].name, "qty": 1}])):
			with self.assertRaises(frappe.PermissionError):
				fn()

	def test_portal_without_access_row_or_suspended(self):
		w = self.released()
		user = self.portal_user(w.supplier)
		frappe.db.set_value("Supplier", w.supplier, "subcontractor_approval_status", "Suspended")
		self.as_user(user)
		self.assertTrue(portal.boot()["suspended"])
		with self.assertRaises(frappe.PermissionError):
			portal.respond_work_order(w.name, "accept")
		frappe.set_user("Administrator")
		frappe.db.set_value("Subcontractor Portal Access", {"user": user}, {"enabled": 0, "suspended_reason": "test"})
		self.as_user(user)
		with self.assertRaises(frappe.PermissionError):
			portal.boot()
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			portal.dashboard()

	# ------------------------------------------------------------------ acceptance, progress, inspection
	def test_accept_progress_inspection_and_billing_eligibility(self):
		w = self.released(qty=100)
		user = self.portal_user(w.supplier)
		self.as_user(user)
		with self.assertRaisesRegex(frappe.ValidationError, "reason"):
			portal.respond_work_order(w.name, "reject")
		self.assertEqual(portal.respond_work_order(w.name, "accept", confirmed_start_date=nowdate()), "Accepted by Subcontractor")
		item = w.items[0].name
		with self.assertRaises(frappe.ValidationError):
			portal.submit_progress(w.name, [{"swo_item": item, "qty_done": 101}])
		dp = portal.submit_progress(w.name, [{"swo_item": item, "qty_done": 40}], labour_deployed=6)
		self.assertEqual(frappe.db.get_value("Subcontract Daily Progress", dp, ["status", "source"]), ("Submitted", "Portal"))
		with self.assertRaises(frappe.PermissionError):         # a portal user cannot approve its own report
			call(DP + "approve", name=dp)
		frappe.set_user("Administrator")
		call(DP + "approve", name=dp, review_remarks="ok")
		self.assertEqual(flt(frappe.db.get_value("Subcontract Work Item", item, "reported_qty")), 40)
		self.assertEqual(frappe.db.get_value("Subcontract Work Order", w.name, "status"), "Work In Progress")
		self.as_user(user)
		self.assertEqual(portal.billable(w.name)["rows"][0]["billable_qty"], 0)   # reported is not billable
		insp = portal.request_inspection(w.name, [{"swo_item": item, "reported_qty": 40}], proposed_date=nowdate())
		frappe.set_user("Administrator")
		call(WP + "start_inspection", name=insp)
		doc = frappe.get_doc("Subcontract Work Progress", insp)
		doc.items[0].accepted_qty, doc.items[0].rejected_qty, doc.items[0].rework_qty = 30, 5, 5
		doc.quality_remarks = "Joints"
		doc.save()
		doc.submit()
		self.assertEqual(frappe.db.get_value("Subcontract Work Progress", insp, "inspection_status"), "Partially Accepted")
		self.as_user(user)
		self.assertEqual(portal.billable(w.name)["rows"][0]["billable_qty"], 30)
		ins = portal.inspections()["rows"]
		self.assertEqual(ins[0]["quality_remarks"], "Joints")

	# ------------------------------------------------------------------ materials
	def test_material_request_issue_and_receipt(self):
		w = self.released()
		user = self.portal_user(w.supplier)
		item = self.item(stock=50, inspection=0)
		self.as_user(user)
		mr = portal.create_material_request(w.name, [{"item_code": item, "qty": 30}], add_days(nowdate(), 3), "Gate 2")
		frappe.set_user("Administrator")
		call(MR + "approve", name=mr)
		alloc = call(MR + "make_material_allocation", source_name=mr, source_warehouse=self.yard)
		alloc.items[0].qty = 20
		alloc.insert()
		alloc.submit()
		self.assertEqual(frappe.db.get_value("Subcontract Material Request", mr, "status"), "Partially Issued")
		self.assertEqual(bin_qty(item, self.yard), 30)
		over = call(MR + "make_material_allocation", source_name=mr, source_warehouse=self.yard)
		over.items[0].qty = 11
		with self.assertRaisesRegex(frappe.ValidationError, "still to issue"):
			over.insert()
		self.as_user(user)
		with self.assertRaisesRegex(frappe.ValidationError, "Describe"):
			portal.confirm_receipt(alloc.name, shortage=1)
		portal.confirm_receipt(alloc.name, shortage=1, remarks="2 short")
		self.assertEqual(frappe.db.get_value("Subcontract Material Allocation", alloc.name, ["received_by_subcontractor", "shortage_reported"]), (1, 1))
		held = {h["item_code"]: h["qty"] for h in portal.materials()["held"]}
		self.assertEqual(held[item], 20)

	# ------------------------------------------------------------------ invoices
	def test_invoice_submission_limits_duplicates_and_purchase_invoice(self):
		w = self.released(qty=100, rate=20)
		w.db_set("retention_percentage", 10)
		self.accepted(w, 50)
		user = self.portal_user(w.supplier)
		item = w.items[0].name
		self.as_user(user)
		with self.assertRaisesRegex(frappe.ValidationError, "accepted and not yet invoiced"):
			portal.submit_invoice(w.name, "INV-A", nowdate(), [{"swo_item": item, "qty": 51}])
		s1 = portal.submit_invoice(w.name, "INV-A", nowdate(), [{"swo_item": item, "qty": 30}])
		with self.assertRaisesRegex(frappe.ValidationError, "already recorded"):
			portal.submit_invoice(w.name, "INV-A", nowdate(), [{"swo_item": item, "qty": 10}])
		with self.assertRaisesRegex(frappe.ValidationError, "accepted and not yet invoiced"):   # 30 is claimed on the open submission
			portal.submit_invoice(w.name, "INV-B", nowdate(), [{"swo_item": item, "qty": 21}])
		with self.assertRaises(frappe.PermissionError):
			call(INV + "verify", name=s1)
		frappe.set_user("Administrator")
		call(INV + "verify", name=s1)
		sub = frappe.get_doc("Subcontractor Invoice Submission", s1)
		pi = frappe.get_doc("Purchase Invoice", sub.purchase_invoice)
		self.assertEqual((sub.status, pi.bill_no, pi.docstatus), ("Verified", "INV-A", 1))
		self.assertEqual(flt(pi.net_total), 600)
		self.assertEqual(flt(frappe.db.get_value("Subcontract Settlement", sub.settlement, "retention_amount")), 60)
		self.assertEqual(flt(frappe.db.get_value("Subcontract Work Item", item, "invoiced_qty")), 30)
		self.as_user(user)
		self.assertEqual(portal.billable(w.name)["rows"][0]["billable_qty"], 20)
		self.assertEqual(portal.invoices()["rows"][0]["payable"], pi.grand_total)

	# ------------------------------------------------------------------ variations
	def test_variations_change_the_work_order_and_reverse_on_cancel(self):
		w = self.released(hoc=self.hoc((200,)), qty=100, rate=20)
		user = self.portal_user(w.supplier)
		self.as_user(user)
		t = portal.submit_variation(w.name, "Time Extension", "Rain", new_completion_date=add_days(nowdate(), 60))
		x = portal.submit_variation(w.name, "Extra Work", "Extra bay", items=[{"job_type": w.items[0].job_type, "qty": 4, "rate": 25}])
		c = portal.submit_variation(w.name, "Delay Claim", "Standby", claimed_amount=500)
		with self.assertRaises(frappe.PermissionError):
			call(VR + "approve", name=x)
		frappe.set_user("Administrator")
		frappe.db.set_value("Subcontract Work Order", w.name, "expected_completion_date", add_days(nowdate(), 10))
		call(VR + "approve", name=t)
		self.assertEqual(str(frappe.db.get_value("Subcontract Work Order", w.name, "expected_completion_date")), add_days(nowdate(), 60))
		call(VR + "approve", name=x)
		wo = frappe.get_doc("Subcontract Work Order", w.name)
		self.assertEqual((len(wo.items), flt(wo.final_contract_value), flt(wo.approved_additional_cost)), (2, 2100, 100))
		with self.assertRaisesRegex(frappe.ValidationError, "approved amount"):
			call(VR + "approve", name=c)
		call(VR + "approve", name=c, approved_amount=300)
		wo = frappe.get_doc("Subcontract Work Order", w.name)
		claim = [r for r in wo.items if r.variation == c][0]
		self.assertEqual((flt(claim.amount), flt(claim.accepted_qty)), (300, 1))   # an approved claim is billable at once
		q = frappe.get_doc({"doctype": "Subcontract Variation", "subcontract_work_order": w.name, "variation_type": "Quantity Variation", "description": "More",
			"items": [{"swo_item": w.items[0].name, "qty": 120}]}).insert()
		call(VR + "approve", name=q.name)
		self.assertEqual(flt(frappe.db.get_value("Subcontract Work Item", w.items[0].name, "qty")), 120)
		frappe.get_doc("Subcontract Variation", q.name).cancel()
		frappe.get_doc("Subcontract Variation", x).cancel()
		wo = frappe.get_doc("Subcontract Work Order", w.name)
		self.assertEqual((flt(wo.items[0].qty), len(wo.items), flt(wo.final_contract_value)), (100, 2, 2300))
		self.as_user(user)
		types = {r["name"]: r["status"] for r in portal.variations()["rows"]}
		self.assertEqual(types[t], "Approved")
		self.assertNotIn("internal_remarks", portal.variations()["rows"][0])

	def test_quantity_variation_respects_hire_order_contract_balance(self):
		hoc = self.hoc((100,))
		w = self.released(hoc=hoc, qty=90)
		v = frappe.get_doc({"doctype": "Subcontract Variation", "subcontract_work_order": w.name, "variation_type": "Quantity Variation", "description": "More",
			"items": [{"swo_item": w.items[0].name, "qty": 111}]}).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "more is available"):
			call(VR + "approve", name=v.name)

	# ------------------------------------------------------------------ messages, hold, command center
	def test_messages_hold_and_command_center(self):
		w = self.released()
		user = self.portal_user(w.supplier)
		frappe.get_doc("Subcontract Work Order", w.name).add_comment("Comment", "internal: price is high")
		self.as_user(user)
		portal.post_message("When is inspection?", work_order=w.name)
		d = portal.work_order(w.name)
		self.assertNotIn("internal", str(d))
		frappe.set_user("Administrator")
		ccs.send_message(w.supplier, "Tomorrow 9am", work_order=w.name)
		self.as_user(user)
		self.assertEqual(len(portal.messages(w.name)["rows"]), 2)
		frappe.set_user("Administrator")
		ccs.act("Subcontract Work Order", w.name, "hold", remarks="Client stop")
		self.assertEqual(frappe.db.get_value("Subcontract Work Order", w.name, "status"), "On Hold")
		ccs.act("Subcontract Work Order", w.name, "resume")
		self.assertEqual(frappe.db.get_value("Subcontract Work Order", w.name, "status"), "Sent to Subcontractor")
		dash = ccs.dashboard()
		self.assertTrue(any(k["key"] == "work_orders" for k in dash["kpis"]))
		one = ccs.work_order(w.name)
		self.assertEqual(one["doc"]["name"], w.name)
		self.assertIn("hold", one["actions"])
		prof = ccs.subcontractor(w.supplier)
		self.assertIn("score", prof["scorecard"])
		self.assertTrue(ccs.subcontractors()["rows"])
		self.assertTrue(ccs.compare()["rows"])
		self.as_user(user)
		with self.assertRaises(frappe.PermissionError):
			ccs.dashboard()

	def test_reports_run(self):
		w = self.released()
		self.accepted(w, 10)
		from thinknxg_rental.services.subcontract_reports import REPORTS, run

		for name in REPORTS:
			filters = {"supplier": w.supplier} if name == "Subcontractor Account Statement" else {}
			cols, rows = run(name, filters)
			self.assertTrue(cols, name)
