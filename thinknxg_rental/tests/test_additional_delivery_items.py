"""Additional physical rental items dispatched on a Hire Delivery Order after the Rental Contract is submitted.

    bench --site <site> run-tests --module thinknxg_rental.tests.test_additional_delivery_items

The contract keeps its original rows and quantities; the delivery adds the extra material to the live contract
(Additional Qty, or a new row flagged Added During Delivery), so billing, material at site, off-hire, inspection
and closure treat it like any contracted item.
"""
import frappe
from frappe.utils import add_days, flt, getdate, nowdate

from thinknxg_rental.services import billing, closure, ledger
from thinknxg_rental.tests import test_multi_warehouse as tmw
from thinknxg_rental.tests.test_multi_warehouse import bin_qty


class TestAdditionalDeliveryItems(tmw.TestMultiWarehouse):
	# the parent's tests run in their own class
	for _name in [n for n in dir(tmw.TestMultiWarehouse) if n.startswith("test_")]:
		locals()[_name] = None
	del _name

	# ------------------------------------------------------------------ helpers
	def row(self, rc, item):
		return frappe.db.get_value(
			"Rental Contract Item", {"parent": rc, "item_code": item},
			["qty", "additional_qty", "is_additional", "added_by_delivery", "dispatched_qty", "at_site_qty", "pending_qty", "rate"], as_dict=True)

	def contract_doc(self, rc):
		return frappe.get_doc("Rental Contract", rc)

	def dispatch(self, rc, rows, days_ago=10, submit=True):
		"""rows: (item, qty, warehouse, additional[, cross_hire_order])"""
		items = []
		for r in rows:
			item, qty, warehouse, additional = r[:4]
			d = {"item_code": item, "qty": qty, "ownership": "Cross Hire" if len(r) > 4 else "Own", "source_warehouse": warehouse,
				"additional_item": 1 if additional else 0}
			if len(r) > 4:
				d["cross_hire_order"] = r[4]
			items.append(d)
		doc = frappe.get_doc({"doctype": "Hire Delivery Order", "company": self.company, "rental_contract": rc,
			"posting_date": add_days(nowdate(), -days_ago), "items": items})
		doc.insert()
		if submit:
			doc.submit()
		return doc

	def ledger_rows(self, rc, item):
		return frappe.get_all("Rental Ownership Ledger", filters={"rental_contract": rc, "item_code": item, "position_type": ledger.AT_SITE},
			fields=["voucher_no", "movement_type", "qty", "billing_date", "origin_warehouse", "warehouse", "source_type", "source_document"],
			order_by="creation")

	def setup_contract(self, original_qty=10, stock=50):
		a = self.item({self.kochi: stock})
		rc, site = self.contract([(a, original_qty)])
		return a, rc, frappe.db.get_value("Rental Site", site, "site_warehouse") if site else None

	def site_wh(self, rc):
		return frappe.db.get_value("Rental Site", frappe.db.get_value("Rental Contract", rc, "rental_site"), "site_warehouse")

	# ------------------------------------------------------------------ 1. original flow is unchanged
	def test_a_original_items_unchanged(self):
		a, rc, _ = self.setup_contract()
		self.dispatch(rc, [(a, 10, self.kochi, False)])
		r = self.row(rc, a)
		self.assertEqual((flt(r.qty), flt(r.additional_qty), r.is_additional, flt(r.dispatched_qty), flt(r.pending_qty)), (10, 0, 0, 10, 0))
		self.assertEqual(self.contract_doc(rc).status, "On Hire")

	# ------------------------------------------------------------------ 2. one additional item
	def test_b_one_additional_item(self):
		a, rc, _ = self.setup_contract()
		extra = self.item({self.kochi: 20})
		hdo = self.dispatch(rc, [(a, 10, self.kochi, False), (extra, 6, self.kochi, True)])
		site = self.site_wh(rc)
		self.assertEqual(bin_qty(extra, site), 6)
		self.assertEqual(bin_qty(extra, self.kochi), 14)
		r = self.row(rc, extra)
		self.assertEqual((flt(r.qty), flt(r.additional_qty), r.is_additional, r.added_by_delivery, flt(r.dispatched_qty), flt(r.at_site_qty)),
			(6, 6, 1, hdo.name, 6, 6))
		# the original row and its quantity are untouched
		orig = self.row(rc, a)
		self.assertEqual((flt(orig.qty), flt(orig.additional_qty), orig.is_additional), (10, 0, 0))
		# ledger: linked to the contract and its source, billing from the dispatch date
		(entry,) = self.ledger_rows(rc, extra)
		src = frappe.db.get_value("Rental Contract", rc, ["source_type", "source_document"])
		self.assertEqual((entry.voucher_no, entry.movement_type, flt(entry.qty), entry.origin_warehouse, entry.warehouse),
			(hdo.name, "Dispatch", 6, self.kochi, site))
		self.assertEqual((entry.source_type, entry.source_document), tuple(src))
		self.assertEqual(getdate(entry.billing_date), getdate(hdo.posting_date))
		# material at site, per item
		self.assertEqual(ledger.get_site_balance(rc)[(extra, "Own", "")], 6)
		self.assertEqual(flt(self.contract_doc(rc).total_at_site_qty), 16)

	# ------------------------------------------------------------------ 3. several items, several deliveries
	def test_c_multiple_items_and_second_delivery(self):
		a, rc, _ = self.setup_contract()
		x, y = self.item({self.kochi: 20}), self.item({self.kochi: 20})
		self.dispatch(rc, [(a, 10, self.kochi, False), (x, 4, self.kochi, True), (y, 3, self.kochi, True)])
		self.assertEqual([flt(self.row(rc, i).qty) for i in (x, y)], [4, 3])
		# a second delivery of the same additional item extends the same contract row
		self.dispatch(rc, [(x, 5, self.kochi, True)], days_ago=3)
		r = self.row(rc, x)
		self.assertEqual((flt(r.qty), flt(r.additional_qty), flt(r.dispatched_qty), flt(r.at_site_qty)), (9, 9, 9, 9))
		self.assertEqual(frappe.db.count("Rental Contract Item", {"parent": rc, "item_code": x}), 1)
		self.assertEqual(len(self.ledger_rows(rc, x)), 2)

	def test_d_extra_quantity_of_a_contracted_item(self):
		"""More than the contracted quantity of an item already on the contract: the original quantity stays visible."""
		a, rc, _ = self.setup_contract(original_qty=10)
		self.dispatch(rc, [(a, 10, self.kochi, False), (a, 4, self.kochi, True)])
		r = self.row(rc, a)
		self.assertEqual((flt(r.qty), flt(r.additional_qty), r.is_additional, flt(r.dispatched_qty)), (14, 4, 0, 14))
		self.assertEqual(flt(r.qty) - flt(r.additional_qty), 10)  # the original contracted quantity

	# ------------------------------------------------------------------ 4. guards
	def test_e_guards(self):
		a, rc, _ = self.setup_contract()
		extra = self.item({self.kochi: 5})
		# an item that is not on the contract needs the Additional Item tick
		with self.assertRaises(frappe.ValidationError) as cm:
			self.dispatch(rc, [(extra, 2, self.kochi, False)])
		self.assertIn("Additional Item", str(cm.exception))
		# not more than the stock in the warehouse
		with self.assertRaises(frappe.ValidationError) as cm:
			self.dispatch(rc, [(extra, 9, self.kochi, True)])
		self.assertIn("is in stock there", str(cm.exception))
		# an ordinary line is still held to the contracted balance
		with self.assertRaises(frappe.ValidationError):
			self.dispatch(rc, [(a, 11, self.kochi, False)])
		# a non-stock item cannot be hired out
		service = frappe.get_all("Item", filters={"is_stock_item": 0, "disabled": 0}, pluck="name", limit=1)
		if service:
			with self.assertRaises(frappe.ValidationError):
				self.dispatch(rc, [(service[0], 1, self.kochi, True)])
		# nothing was added by the refused deliveries
		self.assertFalse(frappe.db.exists("Rental Contract Item", {"parent": rc, "item_code": extra}))
		self.assertEqual(bin_qty(extra, self.kochi), 5)

	def test_f_a_closed_contract_takes_nothing(self):
		a, rc, _ = self.setup_contract()
		extra = self.item({self.kochi: 5})
		frappe.db.set_value("Rental Contract", rc, "status", "Completed")
		with self.assertRaises(frappe.ValidationError):
			self.dispatch(rc, [(extra, 1, self.kochi, True)])

	# ------------------------------------------------------------------ 5. warehouses and ownership
	def test_g_two_warehouses(self):
		a, rc, _ = self.setup_contract()
		extra = self.item({self.kochi: 4, self.calicut: 6})
		self.dispatch(rc, [(a, 10, self.kochi, False), (extra, 4, self.kochi, True), (extra, 6, self.calicut, True)])
		self.assertEqual((bin_qty(extra, self.kochi), bin_qty(extra, self.calicut)), (0, 0))
		by_origin = {k[3]: q for k, q in ledger.get_site_balance_by_origin(rc).items() if k[0] == extra}
		self.assertEqual(by_origin, {self.kochi: 4, self.calicut: 6})
		self.assertEqual(flt(self.row(rc, extra).qty), 10)

	def test_h_additional_cross_hire_item(self):
		a, rc, _ = self.setup_contract()
		extra = self.item({})
		cho = self.cross_hire(rc, extra, 5, self.kochi_x)
		self.receive(cho, self.kochi_x)
		site_x = frappe.db.get_value("Rental Site", frappe.db.get_value("Rental Contract", rc, "rental_site"), "cross_hire_site_warehouse")
		# more than was received on the order is refused
		with self.assertRaises(frappe.ValidationError):
			self.dispatch(rc, [(extra, 6, self.kochi_x, True, cho.name)])
		self.dispatch(rc, [(a, 10, self.kochi, False), (extra, 5, self.kochi_x, True, cho.name)])
		r = self.row(rc, extra)
		self.assertEqual((flt(r.qty), r.is_additional, flt(r.at_site_qty)), (5, 1, 5))
		self.assertEqual(ledger.get_site_balance(rc)[(extra, "Cross Hire", cho.name)], 5)
		self.assertEqual(bin_qty(extra, site_x), 5)
		# delivered once: nothing left to deliver from that order
		with self.assertRaises(frappe.ValidationError):
			self.dispatch(rc, [(extra, 1, self.kochi_x, True, cho.name)])

	# ------------------------------------------------------------------ 6. billing
	def test_i_billing_starts_on_the_dispatch_date(self):
		a, rc, _ = self.setup_contract()
		extra = self.item({self.kochi: 10})
		self.dispatch(rc, [(a, 10, self.kochi, False)], days_ago=20)
		hdo = self.dispatch(rc, [(extra, 4, self.kochi, True)], days_ago=5)
		billing.generate_billing(rc, upto_date=add_days(nowdate(), -1))
		lines = frappe.db.sql(
			"""select i.item_code, i.from_date, i.to_date, i.qty from `tabRental Billing Schedule Item` i
			join `tabRental Billing Schedule` s on s.name = i.parent where s.rental_contract = %s and s.docstatus = 1""", rc, as_dict=True)
		mine = [l for l in lines if l.item_code == extra]
		self.assertTrue(mine, "the additional item is billed")
		self.assertEqual(min(getdate(l.from_date) for l in mine), getdate(hdo.posting_date))
		self.assertTrue(all(flt(l.qty) == 4 for l in mine))
		# the original item is billed from its own, earlier date
		self.assertEqual(min(getdate(l.from_date) for l in lines if l.item_code == a), getdate(add_days(nowdate(), -20)))
		# delivery cannot be back-dated into a billed period
		with self.assertRaises(frappe.ValidationError):
			self.dispatch(rc, [(extra, 1, self.kochi, True)], days_ago=8)

	# ------------------------------------------------------------------ 7. off-hire, closure is separate
	def test_j_partial_and_full_off_hire_then_explicit_closure(self):
		a, rc, _ = self.setup_contract()
		extra = self.item({self.kochi: 10})
		self.dispatch(rc, [(a, 10, self.kochi, False), (extra, 6, self.kochi, True)])
		self.off_hire(rc, [{"item_code": extra, "ownership": "Own", "returned_qty": 2}], days_ago=4)
		self.assertEqual(ledger.get_site_balance(rc)[(extra, "Own", "")], 4)
		self.assertEqual(flt(frappe.db.get_value("Rental Contract Item", {"parent": rc, "item_code": extra}, "returned_qty")), 2)
		self.off_hire(rc, [{"item_code": extra, "ownership": "Own", "returned_qty": 4}, {"item_code": a, "ownership": "Own", "returned_qty": 10}], days_ago=2)
		# everything is back, but the off-hire note does not close the contract
		doc = self.contract_doc(rc)
		self.assertEqual((doc.status, flt(doc.total_at_site_qty)), ("Off Hired", 0))
		self.assertEqual(bin_qty(extra, self.kochi), 10)
		doc.close_contract()
		self.assertEqual(frappe.db.get_value("Rental Contract", rc, "status"), "Completed")

	def test_k_inspection_and_closure_see_additional_items(self):
		a, rc, _ = self.setup_contract()
		extra = self.item({self.kochi: 10}, inspection=1)
		inspect = frappe.db.get_single_value("Rental Settings", "inspection_required")
		frappe.db.set_single_value("Rental Settings", "inspection_required", 1)
		frappe.clear_cache(doctype="Rental Settings")
		try:
			self.dispatch(rc, [(a, 10, self.kochi, False), (extra, 5, self.kochi, True)])
			# the item is still at site: the contract cannot close
			with self.assertRaises(frappe.ValidationError):
				self.contract_doc(rc).close_contract()
			self.off_hire(rc, [{"item_code": a, "ownership": "Own", "returned_qty": 10}, {"item_code": extra, "ownership": "Own", "returned_qty": 5}], days_ago=2)
			# the returned additional item waits for its inspection
			self.assertTrue(closure.pending(rc))
			with self.assertRaises(frappe.ValidationError):
				self.contract_doc(rc).close_contract()
			self.assertEqual(frappe.db.get_value("Rental Contract", rc, "status"), "Off Hired")
		finally:
			frappe.db.set_single_value("Rental Settings", "inspection_required", inspect)
			frappe.clear_cache(doctype="Rental Settings")

	def test_l_lost_additional_item_needs_settlement(self):
		a, rc, _ = self.setup_contract()
		extra = self.item({self.kochi: 10})
		self.dispatch(rc, [(a, 10, self.kochi, False), (extra, 5, self.kochi, True)])
		self.off_hire(rc, [{"item_code": a, "ownership": "Own", "returned_qty": 10},
			{"item_code": extra, "ownership": "Own", "returned_qty": 3, "lost_qty": 2}], days_ago=2)
		self.assertTrue(any("lost" in str(p).lower() for p in closure.pending(rc)))
		with self.assertRaises(frappe.ValidationError):
			self.contract_doc(rc).close_contract()

	# ------------------------------------------------------------------ 8. cancelling
	def test_m_cancel_takes_the_additional_quantity_off_again(self):
		a, rc, _ = self.setup_contract()
		extra = self.item({self.kochi: 10})
		first = self.dispatch(rc, [(a, 10, self.kochi, False), (extra, 4, self.kochi, True), (a, 2, self.kochi, True)])
		second = self.dispatch(rc, [(extra, 3, self.kochi, True)], days_ago=3)
		self.assertEqual(flt(self.row(rc, extra).qty), 7)
		second.cancel()
		self.assertEqual((flt(self.row(rc, extra).qty), flt(self.row(rc, extra).at_site_qty)), (4, 4))
		first.cancel()
		# the row that existed only because of deliveries is gone; the original row is back to its contracted quantity
		self.assertFalse(frappe.db.exists("Rental Contract Item", {"parent": rc, "item_code": extra}))
		self.assertEqual((flt(self.row(rc, a).qty), flt(self.row(rc, a).additional_qty), flt(self.row(rc, a).dispatched_qty)), (10, 0, 0))
		self.assertEqual(bin_qty(extra, self.kochi), 10)
		self.assertFalse(self.ledger_rows(rc, extra))
		self.assertEqual(self.contract_doc(rc).status, "Active")

	def test_n_cancel_is_blocked_after_off_hire(self):
		a, rc, _ = self.setup_contract()
		extra = self.item({self.kochi: 10})
		hdo = self.dispatch(rc, [(extra, 4, self.kochi, True), (a, 10, self.kochi, False)])
		self.off_hire(rc, [{"item_code": extra, "ownership": "Own", "returned_qty": 4}], days_ago=2)
		with self.assertRaises(frappe.ValidationError):
			hdo.cancel()
		self.assertEqual(flt(self.row(rc, extra).qty), 4)
