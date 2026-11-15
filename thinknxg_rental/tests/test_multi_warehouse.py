"""Multi-location own rental warehouses and cross hire warehouses (scenarios A-J of the brief).

Three own rental warehouses at three locations (Kochi, Calicut, Trivandrum) and two cross hire
warehouses (Kochi, Calicut), added to Rental Settings next to the existing default yard, which stays
the default so the single-warehouse tests keep running against it.

    bench --site <site> run-tests --module thinknxg_rental.tests.test_multi_warehouse
"""
import threading

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, nowdate

from thinknxg_rental.services import inventory, ledger
from thinknxg_rental.services import warehouses as rw
from thinknxg_rental.tests.test_admin_portal import STAFF, _leaf, create, ensure_item, form, prepare, save
from thinknxg_rental.tests import test_reservation_warehouses as trw
from thinknxg_rental.thinknxg_rental.doctype.hire_delivery_order.hire_delivery_order import get_dispatch_items
from thinknxg_rental.thinknxg_rental.doctype.rental_material_reservation import rental_material_reservation as rmr

LOCATIONS = ("MW Kochi", "MW Calicut", "MW Trivandrum")


def hash5():
	return frappe.generate_hash(length=5).upper()


def bin_qty(item, warehouse):
	return flt(frappe.db.get_value("Bin", {"item_code": item, "warehouse": warehouse}, "actual_qty"))


def rolled_back(fn):
	"""fn in a savepoint, undone when it fails (as the request would be), so a refused cancel leaves no trace."""
	def run(*args, **kwargs):
		frappe.db.savepoint("mw_test")
		try:
			return fn(*args, **kwargs)
		except Exception:
			frappe.db.rollback(save_point="mw_test")
			raise

	return run


def ensure_warehouse(name, company, parent, is_group=0):
	existing = frappe.db.get_value("Warehouse", {"warehouse_name": name, "company": company})
	if existing:
		return existing
	return frappe.get_doc({"doctype": "Warehouse", "warehouse_name": name, "company": company, "parent_warehouse": parent,
		"is_group": is_group}).insert(ignore_permissions=True).name


class TestMultiWarehouse(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		prepare(cls)
		frappe.set_user("Administrator")
		root = frappe.db.get_value("Warehouse", {"company": cls.company, "is_group": 1, "parent_warehouse": ["in", ["", None]]}, "name")
		cls.own, cls.cross = {}, {}
		for loc in LOCATIONS:
			group = ensure_warehouse(loc, cls.company, root, is_group=1)
			cls.own[loc] = ensure_warehouse(f"{loc} Yard", cls.company, group)
			if loc != "MW Trivandrum":
				cls.cross[loc] = ensure_warehouse(f"{loc} Cross Hire", cls.company, group)
		s = frappe.get_doc("Rental Settings")
		have = {r.warehouse for r in s.own_rental_warehouses} | {r.warehouse for r in s.cross_hire_warehouses}
		for wh in cls.own.values():
			if wh not in have:
				s.append("own_rental_warehouses", {"warehouse": wh, "is_active": 1})
		for wh in cls.cross.values():
			if wh not in have:
				s.append("cross_hire_warehouses", {"warehouse": wh, "is_active": 1})
		s.save(ignore_permissions=True)
		cls.kochi, cls.calicut, cls.tvm = (cls.own[loc] for loc in LOCATIONS)
		cls.kochi_x, cls.calicut_x = cls.cross["MW Kochi"], cls.cross["MW Calicut"]
		cls.supplier = "MW Test Supplier"
		if not frappe.db.exists("Supplier", cls.supplier):
			frappe.get_doc({"doctype": "Supplier", "supplier_name": cls.supplier, "supplier_group": _leaf("Supplier Group")}).insert()
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.clear_cache(doctype="Rental Settings")

	def tearDown(self):
		frappe.set_user("Administrator")

	# ------------------------------------------------------------------ fixtures
	def item(self, stock=None, inspection=0, prefix="MW"):
		"""A fresh rental item with stock in the given warehouses, so tests never share free stock."""
		code = ensure_item(f"{prefix}-{hash5()}", "Multi Warehouse Test Item")
		frappe.get_doc({"doctype": "Rental Item Profile", "item": code, "daily_rate": 3, "monthly_rate": 60,
			"inspection_required": inspection, "replacement_value": 100, "repair_charge": 10}).insert()
		rows = [{"item_code": code, "t_warehouse": wh, "qty": qty, "basic_rate": 50} for wh, qty in (stock or {}).items()]
		if rows:
			se = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "company": self.company,
				"set_posting_time": 1, "posting_date": add_days(nowdate(), -60), "items": rows})
			se.insert()
			se.submit()
		return code

	def contract(self, rows):
		frappe.set_user(STAFF)
		try:
			return trw.TestReservationWarehouses.contract(self, rows)
		finally:
			frappe.set_user("Administrator")

	def reserve(self, rental_contract, default=None, submit=True):
		frappe.set_user(STAFF)
		try:
			key, res = create(form("rental-contract", rental_contract), "Material Reservation")
			res["doc"]["source_warehouse"] = default or self.kochi
			return save("material-reservation", res["doc"], submit=submit)
		finally:
			frappe.set_user("Administrator")

	def rows(self, reservation):
		return sorted((d.item_code, d.source_warehouse, d.ownership, flt(d.reserved_qty), flt(d.shortfall_qty))
			for d in frappe.get_doc("Rental Material Reservation", reservation).items)

	def deliver(self, rental_contract, items, reservation=None, days_ago=10, submit=True):
		doc = frappe.get_doc({"doctype": "Hire Delivery Order", "company": self.company, "rental_contract": rental_contract,
			"rental_material_reservation": reservation, "posting_date": add_days(nowdate(), -days_ago), "items": items})
		doc.insert()
		if submit:
			doc.submit()
		return doc

	def off_hire(self, rental_contract, items, days_ago=5, submit=True):
		date = add_days(nowdate(), -days_ago)
		doc = frappe.get_doc({"doctype": "Hire Off-Hire Note", "company": self.company, "rental_contract": rental_contract,
			"off_hire_date": date, "return_date": date, "items": items})
		doc.insert()
		if submit:
			doc.submit()
		return doc

	def cross_hire(self, rental_contract, item, qty, warehouse, receive_at="Cross Hire Yard"):
		cho = frappe.get_doc({"doctype": "Cross Hire Order", "company": self.company, "supplier": self.supplier,
			"rental_contract": rental_contract, "order_date": add_days(nowdate(), -30), "hire_from": add_days(nowdate(), -30),
			"expected_return_date": add_days(nowdate(), 30), "receive_at": receive_at, "receipt_warehouse": warehouse,
			"items": [{"item_code": item, "qty": qty, "rate": 5, "rate_basis": "Daily"}]})
		cho.insert()
		cho.submit()
		po = frappe.db.get_value("Cross Hire Order", cho.name, "purchase_order")
		if frappe.db.get_value("Purchase Order", po, "docstatus") == 0:
			frappe.get_doc("Purchase Order", po).submit()
		return cho.reload() or cho

	def receive(self, cho, warehouse=None):
		from thinknxg_rental.services.cross_hire import make_cross_hire_receipt

		pr = make_cross_hire_receipt(cho.name)
		pr.posting_date = add_days(nowdate(), -25)
		if warehouse:
			pr.set_warehouse = warehouse
			for row in pr.items:
				row.warehouse = warehouse
		pr.insert()
		pr.submit()
		return pr

	# ------------------------------------------------------------------ A: single warehouse
	def test_a_single_warehouse_behaves_as_before(self):
		item = self.item({self.yard: 40})
		rc, _site = self.contract([(item, 25)])
		res = self.reserve(rc, default=self.yard)
		self.assertEqual(self.rows(res), [(item, self.yard, "Own", 25, 0)])
		dispatch = get_dispatch_items(rc, res)
		self.assertEqual([(r["source_warehouse"], r["qty"]) for r in dispatch], [(self.yard, 25)])
		do = self.deliver(rc, dispatch, res)
		self.assertEqual(do.items[0].source_warehouse, self.yard)
		self.assertEqual(frappe.db.get_value("Rental Material Reservation", res, "status"), "Dispatched")
		# no return warehouse chosen: back where it came from (the default yard)
		oh = self.off_hire(rc, [{"item_code": item, "ownership": "Own", "returned_qty": 25}])
		self.assertEqual((oh.items[0].delivered_from, oh.items[0].target_warehouse), (self.yard, self.yard))
		self.assertEqual(bin_qty(item, self.yard), 40)
		# the legacy fields still name the defaults
		s = frappe.get_cached_doc("Rental Settings")
		self.assertEqual(s.rental_yard_warehouse, rw.default_own_warehouse())
		self.assertEqual(s.cross_hire_yard_warehouse, rw.default_cross_hire_warehouse())

	# ------------------------------------------------------------------ B: split reservation
	def test_b_reservation_splits_over_warehouses(self):
		item = self.item({self.kochi: 100, self.calicut: 80, self.tvm: 60})
		rc, _site = self.contract([(item, 150)])
		res = self.reserve(rc, default=self.kochi)
		self.assertEqual(self.rows(res), sorted([(item, self.kochi, "Own", 100, 0), (item, self.calicut, "Own", 50, 0)]))
		doc = frappe.get_doc("Rental Material Reservation", res)
		self.assertEqual({d.source_warehouse: d.location for d in doc.items}, {self.kochi: "MW Kochi", self.calicut: "MW Calicut"})
		# a second contract gets only what is still free in each warehouse: nothing is reserved twice
		rc2, _site = self.contract([(item, 100)])
		res2 = self.reserve(rc2, default=self.kochi)
		# the most free first (Trivandrum 60, then Calicut 30); what none can cover stays shortfall on the last row
		self.assertEqual(self.rows(res2), sorted([(item, self.tvm, "Own", 60, 0), (item, self.calicut, "Own", 30, 10)]))
		self.assertEqual(rmr.free_qty(item, self.kochi), 0)
		self.assertEqual(rmr.free_qty(item, self.calicut), 0)
		self.assertEqual(rmr.free_qty(item, self.tvm), 0)
		# a hand-picked split (40 / 35 / 25) is kept as entered
		item2 = self.item({self.kochi: 50, self.calicut: 50, self.tvm: 50})
		rc3, _site = self.contract([(item2, 100)])
		frappe.set_user(STAFF)
		key, draft = create(form("rental-contract", rc3), "Material Reservation")
		draft["doc"]["source_warehouse"] = self.kochi
		base = draft["doc"]["items"][0]
		draft["doc"]["items"] = [dict(base, required_qty=q, source_warehouse=w) for w, q in ((self.kochi, 40), (self.calicut, 35), (self.tvm, 25))]
		res3 = save("material-reservation", draft["doc"], submit=True)
		frappe.set_user("Administrator")
		self.assertEqual(self.rows(res3), sorted([(item2, self.kochi, "Own", 40, 0), (item2, self.calicut, "Own", 35, 0), (item2, self.tvm, "Own", 25, 0)]))
		# the warehouse of a submitted row cannot be changed
		doc = frappe.get_doc("Rental Material Reservation", res3)
		doc.items[0].source_warehouse = self.calicut
		self.assertRaises(frappe.ValidationError, doc.save)

	def test_b_reservation_rejects_wrong_warehouses(self):
		item = self.item({self.kochi: 10})
		rc, _site = self.contract([(item, 5)])
		frappe.set_user(STAFF)
		key, draft = create(form("rental-contract", rc), "Material Reservation")
		draft["doc"]["source_warehouse"] = self.kochi
		draft["doc"]["items"][0]["source_warehouse"] = frappe.get_cached_doc("Rental Settings").inspection_warehouse
		self.assertRaises(frappe.ValidationError, save, "material-reservation", draft["doc"])
		frappe.set_user("Administrator")
		# an inactive warehouse is not offered and not accepted on new reservations
		self._set_active(self.tvm, 0)
		try:
			self.assertNotIn(self.tvm, rw.own_warehouses())
			frappe.set_user(STAFF)
			key, draft = create(form("rental-contract", rc), "Material Reservation")
			draft["doc"]["source_warehouse"] = self.kochi
			draft["doc"]["items"][0]["source_warehouse"] = self.tvm
			self.assertRaises(frappe.ValidationError, save, "material-reservation", draft["doc"])
		finally:
			frappe.set_user("Administrator")
			self._set_active(self.tvm, 1)

	def _set_active(self, warehouse, active):
		s = frappe.get_doc("Rental Settings")
		for r in s.own_rental_warehouses:
			if r.warehouse == warehouse:
				r.is_active = active
		s.save(ignore_permissions=True)
		frappe.clear_cache(doctype="Rental Settings")

	# ------------------------------------------------------------------ C: multi-warehouse delivery
	def test_c_delivery_from_several_warehouses(self):
		item = self.item({self.kochi: 100, self.calicut: 80, self.tvm: 60})
		rc, site = self.contract([(item, 150)])
		res = self.reserve(rc, default=self.kochi)
		dispatch = get_dispatch_items(rc, res)
		self.assertEqual(sorted((r["source_warehouse"], r["qty"]) for r in dispatch), sorted([(self.kochi, 100), (self.calicut, 50)]))
		# more than the reservation holds in a warehouse is refused
		too_much = [dict(r, qty=r["qty"] + 5) if r["source_warehouse"] == self.calicut else r for r in dispatch]
		self.assertRaises(frappe.ValidationError, self.deliver, rc, too_much, res)
		# own material out of a cross hire warehouse is refused
		wrong = [dict(dispatch[0], source_warehouse=self.kochi_x)]
		self.assertRaises(frappe.ValidationError, self.deliver, rc, wrong)
		# a row without a warehouse is split over the reservation's warehouses
		do = self.deliver(rc, [{"item_code": item, "qty": 150, "ownership": "Own"}], res)
		self.assertEqual(sorted((d.source_warehouse, flt(d.qty)) for d in do.items), sorted([(self.kochi, 100), (self.calicut, 50)]))
		self.assertEqual((bin_qty(item, self.kochi), bin_qty(item, self.calicut), bin_qty(item, self.tvm)), (0, 30, 60))
		se = frappe.get_doc("Stock Entry", do.stock_entry)
		self.assertEqual(sorted((r.s_warehouse, flt(r.qty)) for r in se.items), sorted([(self.kochi, 100), (self.calicut, 50)]))
		entries = frappe.get_all("Rental Ownership Ledger", filters={"voucher_no": do.name},
			fields=["origin_warehouse", "source_warehouse", "target_warehouse", "stock_entry", "qty"])
		site_wh = frappe.db.get_value("Rental Site", site, "site_warehouse")
		self.assertEqual(sorted((e.origin_warehouse, e.target_warehouse, e.stock_entry, flt(e.qty)) for e in entries),
			sorted([(self.kochi, site_wh, do.stock_entry, 100), (self.calicut, site_wh, do.stock_entry, 50)]))
		self.assertEqual(frappe.db.get_value("Rental Material Reservation", res, "status"), "Dispatched")
		# what is at site is traced to the warehouse it left
		by_origin = ledger.get_site_balance_by_origin(rc)
		self.assertEqual(by_origin[(item, "Own", "", self.kochi)], 100)
		self.assertEqual(by_origin[(item, "Own", "", self.calicut)], 50)

	# ------------------------------------------------------------------ D: return elsewhere
	def test_d_return_to_a_different_warehouse(self):
		item = self.item({self.kochi: 100})
		rc, _site = self.contract([(item, 100)])
		res = self.reserve(rc, default=self.kochi)
		self.deliver(rc, get_dispatch_items(rc, res), res)
		calicut_before = bin_qty(item, self.calicut)
		oh = self.off_hire(rc, [
			{"item_code": item, "ownership": "Own", "returned_qty": 60, "target_warehouse": self.calicut},
			{"item_code": item, "ownership": "Own", "returned_qty": 40, "target_warehouse": self.kochi},
		])
		self.assertEqual(bin_qty(item, self.calicut) - calicut_before, 60)
		self.assertEqual(bin_qty(item, self.kochi), 40)
		for d in oh.items:
			# where it came from and where it went are kept apart
			self.assertEqual(d.delivered_from, self.kochi)
			self.assertTrue(d.delivery_order)
			self.assertTrue(d.site_warehouse)
			self.assertEqual(d.stock_entry, oh.stock_entry)
		self.assertEqual({d.target_warehouse: d.location for d in oh.items}, {self.calicut: "MW Calicut", self.kochi: "MW Kochi"})
		self.assertEqual(oh.off_hire_type, "Full")
		self.assertFalse(ledger.get_site_balance(rc))
		# an own return can never go into a cross hire warehouse
		rc2, _site = self.contract([(item, 10)])
		res2 = self.reserve(rc2, default=self.kochi)
		self.deliver(rc2, get_dispatch_items(rc2, res2), res2, days_ago=2)
		self.assertRaises(frappe.ValidationError, self.off_hire, rc2,
			[{"item_code": item, "ownership": "Own", "returned_qty": 10, "target_warehouse": self.kochi_x}], days_ago=1)

	# ------------------------------------------------------------------ E: partial returns
	def test_e_partial_returns_on_two_dates(self):
		item = self.item({self.kochi: 100})
		rc, _site = self.contract([(item, 100)])
		res = self.reserve(rc, default=self.kochi)
		self.deliver(rc, get_dispatch_items(rc, res), res, days_ago=10)
		first = self.off_hire(rc, [{"item_code": item, "ownership": "Own", "returned_qty": 30, "target_warehouse": self.calicut}], days_ago=6)
		second = self.off_hire(rc, [{"item_code": item, "ownership": "Own", "returned_qty": 40, "target_warehouse": self.tvm}], days_ago=3)
		self.assertEqual((first.off_hire_type, second.off_hire_type), ("Partial", "Partial"))
		self.assertEqual(second.items[0].pending_qty, 30)
		self.assertEqual(ledger.get_site_balance(rc), {(item, "Own", ""): 30})
		# no more than is at site comes back, over all rows
		self.assertRaises(frappe.ValidationError, self.off_hire, rc, [
			{"item_code": item, "ownership": "Own", "returned_qty": 20, "target_warehouse": self.kochi},
			{"item_code": item, "ownership": "Own", "returned_qty": 20, "target_warehouse": self.calicut},
		], days_ago=1)
		# billing still follows the quantity at site: 100 for 4 days, 70 for 3, then 30
		segments = ledger.get_segments(add_days(nowdate(), -10), nowdate(), ledger.AT_SITE, rental_contract=rc)[item]
		self.assertEqual([flt(s[2]) for s in segments], [100, 70, 30])

	# ------------------------------------------------------------------ F: cross hire warehouses
	def test_f_two_cross_hire_warehouses(self):
		genset = self.item()
		rc, site = self.contract([(genset, 6)])
		cho1 = self.cross_hire(rc, genset, 4, self.kochi_x)
		cho2 = self.cross_hire(rc, genset, 2, self.calicut_x)
		self.assertEqual((cho1.receipt_warehouse, cho2.receipt_warehouse), (self.kochi_x, self.calicut_x))
		# supplier material is never received into an own rental warehouse
		from thinknxg_rental.services.cross_hire import make_cross_hire_receipt

		bad = make_cross_hire_receipt(cho1.name)
		for row in bad.items:
			row.warehouse = self.kochi
		self.assertRaises(frappe.ValidationError, bad.insert)
		# a cross hire order cannot be received at an own warehouse either
		self.assertRaises(frappe.ValidationError, self.cross_hire, rc, genset, 1, self.kochi)
		self.receive(cho1)
		self.receive(cho2)
		self.assertEqual((bin_qty(genset, self.kochi_x), bin_qty(genset, self.calicut_x)), (4, 2))
		# the reservation has no own stock: the whole row is to cross hire
		# (a reservation that is all cross hire is not submitted: it holds no stock)
		res = self.reserve(rc, default=self.kochi, submit=False)
		self.assertEqual([r[2] for r in self.rows(res)], ["Cross Hire"])
		dispatch = get_dispatch_items(rc)
		self.assertEqual(sorted((r["cross_hire_order"], r["source_warehouse"], r["qty"]) for r in dispatch),
			sorted([(cho1.name, self.kochi_x, 4), (cho2.name, self.calicut_x, 2)]))
		# one order's material is not taken from the other order's warehouse
		wrong = [dict(dispatch[0], source_warehouse=self.calicut_x if dispatch[0]["source_warehouse"] == self.kochi_x else self.kochi_x)]
		self.assertRaises(frappe.ValidationError, self.deliver, rc, wrong)
		do = self.deliver(rc, dispatch)
		site_x = frappe.db.get_value("Rental Site", site, "cross_hire_site_warehouse")
		self.assertEqual(bin_qty(genset, site_x), 6)
		self.assertTrue(all(flt(r.valuation_rate) == 0 for r in frappe.get_doc("Stock Entry", do.stock_entry).items))
		# customer off-hire: never into an own warehouse; into another cross hire warehouse is fine
		self.assertRaises(frappe.ValidationError, self.off_hire, rc,
			[{"item_code": genset, "ownership": "Cross Hire", "cross_hire_order": cho1.name, "returned_qty": 4, "target_warehouse": self.kochi}])
		oh = self.off_hire(rc, [{"item_code": genset, "ownership": "Cross Hire", "cross_hire_order": cho1.name, "returned_qty": 4,
			"target_warehouse": self.calicut_x}])
		self.assertEqual(bin_qty(genset, self.calicut_x), 4)
		custody = inventory.in_custody_not_at_site([genset], cho1.name)
		self.assertEqual(flt(custody.get((cho1.name, genset, self.calicut_x))), 4)
		self.assertEqual(flt(custody.get((cho1.name, genset, self.kochi_x))), 0)
		self.assertEqual(oh.items[0].delivered_from, self.kochi_x)
		# supplier off-hire is its own document and goes back from a cross hire warehouse only
		from thinknxg_rental.thinknxg_rental.doctype.cross_hire_off_hire_note.cross_hire_off_hire_note import make_cross_hire_off_hire_note

		back = make_cross_hire_off_hire_note(cho1.name)
		back.off_hire_date = nowdate()
		back.return_from_warehouse = self.kochi
		for d in back.items:
			d.qty = 4
		self.assertRaises(frappe.ValidationError, back.insert)
		back.return_from_warehouse = self.calicut_x
		back.insert()
		back.submit()
		self.assertEqual(bin_qty(genset, self.calicut_x), 0)
		self.assertEqual(frappe.db.get_value("Cross Hire Order", cho1.name, "status"), "Returned")
		# nothing supplier-owned ever reached an own rental warehouse
		self.assertTrue(all(bin_qty(genset, w) == 0 for w in rw.own_warehouses(active_only=False)))

	def test_f_direct_to_site_cross_hire_still_works(self):
		genset = self.item()
		rc, site = self.contract([(genset, 3)])
		site_x = frappe.db.get_value("Rental Site", site, "cross_hire_site_warehouse")
		cho = self.cross_hire(rc, genset, 3, None, receive_at="Direct to Site")
		self.assertEqual(cho.receipt_warehouse, site_x)
		self.receive(cho)
		do = self.deliver(rc, get_dispatch_items(rc))
		self.assertEqual(do.items[0].source_warehouse, site_x)
		self.assertFalse(do.stock_entry)  # already at site: nothing moves
		self.off_hire(rc, [{"item_code": genset, "ownership": "Cross Hire", "cross_hire_order": cho.name, "returned_qty": 3}])
		self.assertEqual(bin_qty(genset, site_x), 3)  # waits at site for the supplier

	# ------------------------------------------------------------------ G: inspection
	def test_g_inspection_routes_each_quantity(self):
		inspect = frappe.db.get_single_value("Rental Settings", "inspection_required")
		frappe.db.set_single_value("Rental Settings", "inspection_required", 1)
		frappe.clear_cache(doctype="Rental Settings")
		try:
			s = frappe.get_cached_doc("Rental Settings")
			item = self.item({self.kochi: 20}, inspection=1)
			rc, _site = self.contract([(item, 20)])
			res = self.reserve(rc, default=self.kochi)
			self.deliver(rc, get_dispatch_items(rc, res), res)
			# Calicut chosen as the return warehouse: it goes to inspection first, good stock to Calicut
			oh = self.off_hire(rc, [{"item_code": item, "ownership": "Own", "returned_qty": 20, "target_warehouse": self.calicut}])
			d = oh.items[0]
			self.assertEqual((d.target_warehouse, d.return_to_warehouse, d.requires_inspection), (s.inspection_warehouse, self.calicut, 1))
			self.assertEqual(bin_qty(item, s.inspection_warehouse), 20)
			# under inspection is never available
			self.assertEqual(rw.available_own_qty(item), 0)
			statuses = {r.stock_status: r.qty for r in inventory.get_inventory({"item_code": item})}
			self.assertEqual(statuses.get("Under Inspection"), 20)
			self.assertNotIn("Available", statuses)
			from thinknxg_rental.thinknxg_rental.doctype.hire_off_hire_note.hire_off_hire_note import make_inspection

			ri = make_inspection(oh.name)
			self.assertEqual(ri.items[0].good_warehouse, self.calicut)
			ri.items[0].update({"good_qty": 15, "repairable_qty": 3, "damaged_qty": 2})
			ri.insert()
			ri.submit()
			self.assertEqual((bin_qty(item, self.calicut), bin_qty(item, s.repair_warehouse), bin_qty(item, s.scrap_warehouse),
				bin_qty(item, s.inspection_warehouse)), (15, 3, 2, 0))
			# good stock can only go to an own rental warehouse
			rc2, _site = self.contract([(item, 5)])
			res2 = self.reserve(rc2, default=self.calicut)
			self.deliver(rc2, get_dispatch_items(rc2, res2), res2, days_ago=0)
			oh2 = self.off_hire(rc2, [{"item_code": item, "ownership": "Own", "returned_qty": 5}], days_ago=0)
			ri2 = make_inspection(oh2.name)
			ri2.items[0].good_warehouse = self.kochi_x
			self.assertRaises(frappe.ValidationError, ri2.insert)
		finally:
			frappe.db.set_single_value("Rental Settings", "inspection_required", inspect)
			frappe.clear_cache(doctype="Rental Settings")

	# ------------------------------------------------------------------ H: cancellations
	def test_h_cancellations_reverse(self):
		item = self.item({self.kochi: 30, self.calicut: 30})
		rc, _site = self.contract([(item, 50)])
		res = self.reserve(rc, default=self.kochi)
		do = self.deliver(rc, get_dispatch_items(rc, res), res)
		oh = self.off_hire(rc, [{"item_code": item, "ownership": "Own", "returned_qty": 50, "target_warehouse": self.tvm}])
		self.assertEqual(bin_qty(item, self.tvm), 50)
		# a delivery cannot be cancelled while its material is off-hired
		self.assertRaises(frappe.ValidationError, rolled_back(frappe.get_doc("Hire Delivery Order", do.name).cancel))
		frappe.get_doc("Hire Off-Hire Note", oh.name).cancel()
		self.assertEqual(bin_qty(item, self.tvm), 0)
		self.assertEqual(ledger.get_site_balance(rc), {(item, "Own", ""): 50})
		frappe.get_doc("Hire Delivery Order", do.name).cancel()
		self.assertEqual((bin_qty(item, self.kochi), bin_qty(item, self.calicut)), (30, 30))
		self.assertFalse(frappe.get_all("Rental Ownership Ledger", filters={"voucher_no": do.name}))
		self.assertEqual(sum(flt(d.dispatched_qty) for d in frappe.get_doc("Rental Material Reservation", res).items), 0)
		self.assertEqual((rmr.free_qty(item, self.kochi), rmr.free_qty(item, self.calicut)), (0, 10))
		frappe.get_doc("Rental Material Reservation", res).cancel()
		self.assertEqual((rmr.free_qty(item, self.kochi), rmr.free_qty(item, self.calicut)), (30, 30))
		# inspection and cross hire receipt
		inspect = frappe.db.get_single_value("Rental Settings", "inspection_required")
		frappe.db.set_single_value("Rental Settings", "inspection_required", 1)
		frappe.clear_cache(doctype="Rental Settings")
		try:
			s = frappe.get_cached_doc("Rental Settings")
			item2 = self.item({self.kochi: 10}, inspection=1)
			rc2, _site = self.contract([(item2, 10)])
			res2 = self.reserve(rc2, default=self.kochi)
			self.deliver(rc2, get_dispatch_items(rc2, res2), res2)
			oh2 = self.off_hire(rc2, [{"item_code": item2, "ownership": "Own", "returned_qty": 10}])
			from thinknxg_rental.thinknxg_rental.doctype.hire_off_hire_note.hire_off_hire_note import make_inspection

			ri = make_inspection(oh2.name)
			ri.insert()
			ri.submit()
			self.assertEqual(bin_qty(item2, self.kochi), 10)
			ri.reload()
			ri.cancel()
			self.assertEqual((bin_qty(item2, self.kochi), bin_qty(item2, s.inspection_warehouse)), (0, 10))
			self.assertEqual(frappe.db.get_value("Hire Off-Hire Note", oh2.name, "inspection_status"), "Pending")
		finally:
			frappe.db.set_single_value("Rental Settings", "inspection_required", inspect)
			frappe.clear_cache(doctype="Rental Settings")
		genset = self.item()
		rc3, _site = self.contract([(genset, 2)])
		cho = self.cross_hire(rc3, genset, 2, self.calicut_x)
		pr = self.receive(cho)
		self.assertEqual(bin_qty(genset, self.calicut_x), 2)
		pr.reload()
		pr.cancel()
		self.assertEqual(bin_qty(genset, self.calicut_x), 0)
		self.assertEqual(flt(inventory.in_custody_not_at_site([genset], cho.name).get((cho.name, genset, self.calicut_x))), 0)

	# ------------------------------------------------------------------ transfers between locations
	def test_transfers_between_locations(self):
		item = self.item({self.kochi: 50})
		rc, _site = self.contract([(item, 30)])
		self.reserve(rc, default=self.kochi)

		def transfer(s, t, qty, **extra):
			se = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Transfer", "company": self.company,
				"items": [{"item_code": item, "s_warehouse": s, "t_warehouse": t, "qty": qty}], **extra})
			se.insert()
			se.submit()
			return se

		# free stock moves; reserved stock stays where it is reserved
		transfer(self.kochi, self.calicut, 20)
		self.assertEqual((bin_qty(item, self.kochi), bin_qty(item, self.calicut)), (30, 20))
		self.assertRaises(frappe.ValidationError, transfer, self.kochi, self.calicut, 1)
		# own stock never into a cross hire warehouse, nor to a customer site by hand
		self.assertRaises(frappe.ValidationError, transfer, self.calicut, self.kochi_x, 5)
		site_wh = frappe.db.get_value("Rental Site", _site, "site_warehouse")
		self.assertRaises(frappe.ValidationError, transfer, self.calicut, site_wh, 5)
		# the inventory follows the move: no billing or site effect
		self.assertFalse(ledger.get_site_balance(rc))
		rows = {(r.warehouse, r.stock_status): r.qty for r in inventory.get_inventory({"item_code": item})}
		self.assertEqual(rows, {(self.kochi, "Reserved"): 30, (self.calicut, "Available"): 20})
		# supplier material between cross hire warehouses: names its order, custody moves with it
		genset = self.item()
		rc2, _site = self.contract([(genset, 3)])
		cho = self.cross_hire(rc2, genset, 3, self.kochi_x)
		self.receive(cho)
		se = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Transfer", "company": self.company,
			"items": [{"item_code": genset, "s_warehouse": self.kochi_x, "t_warehouse": self.calicut_x, "qty": 3, "allow_zero_valuation_rate": 1}]})
		self.assertRaises(frappe.ValidationError, se.insert)
		se.nxg_cross_hire_order = cho.name
		se.insert()
		se.submit()
		custody = inventory.in_custody_not_at_site([genset], cho.name)
		self.assertEqual((flt(custody.get((cho.name, genset, self.kochi_x))), flt(custody.get((cho.name, genset, self.calicut_x)))), (0, 3))
		# the move did not change what the supplier bills
		self.assertEqual(frappe.db.get_value("Cross Hire Order Item", {"parent": cho.name}, "on_hire_qty"), 3)
		se.reload()
		se.cancel()
		custody = inventory.in_custody_not_at_site([genset], cho.name)
		self.assertEqual(flt(custody.get((cho.name, genset, self.kochi_x))), 3)

	# ------------------------------------------------------------------ reports
	def test_reports_by_warehouse_and_location(self):
		item = self.item({self.kochi: 100, self.calicut: 80, self.tvm: 60})
		rc, _site = self.contract([(item, 150)])
		res = self.reserve(rc, default=self.kochi)
		self.deliver(rc, get_dispatch_items(rc, res)[:1], res)  # Kochi's 100 go to site, Calicut's 50 stay reserved
		from thinknxg_rental.thinknxg_rental.report.rental_inventory.rental_inventory import execute as inventory_report
		from thinknxg_rental.thinknxg_rental.report.rental_stock_position.rental_stock_position import execute as position

		rows = {(r.warehouse, r.stock_status): r.qty for r in inventory_report({"item_code": item})[1]}
		self.assertEqual(rows, {(self.kochi, "At Site"): 100, (self.calicut, "Reserved"): 50, (self.calicut, "Available"): 30,
			(self.tvm, "Available"): 60})
		calicut_only = inventory_report({"item_code": item, "location": "MW Calicut"})[1]
		self.assertEqual({r.warehouse for r in calicut_only}, {self.calicut})
		whole = position({"item_code": item})[1][0]
		self.assertEqual((whole["yard_qty"], whole["reserved_qty"], whole["available_qty"], whole["at_site_own"]), (140, 50, 90, 100))
		kochi = position({"item_code": item, "location": "MW Kochi"})[1][0]
		self.assertEqual((kochi["yard_qty"], kochi["at_site_own"]), (0, 100))
		by_wh = {r.warehouse: r for r in position({"item_code": item, "group_by_warehouse": 1})[1]}
		self.assertEqual((by_wh[self.calicut].in_stock, by_wh[self.calicut].reserved_qty, by_wh[self.kochi].at_site), (80, 50, 100))
		from thinknxg_rental.thinknxg_rental.report.material_at_site.material_at_site import execute as at_site

		site_rows = at_site({"item_code": item})[1]
		self.assertEqual([(r.delivered_from, r.location, r.qty) for r in site_rows], [(self.kochi, "MW Kochi", 100)])
		# the Command Center report page offers the locations
		from thinknxg_rental.command_center.api import report_meta

		frappe.set_user(STAFF)
		meta = report_meta("reports/rental-inventory")
		location = next(f for f in meta["filters"] if f["fieldname"] == "location")
		self.assertTrue({"MW Kochi", "MW Calicut", "MW Trivandrum"} <= set(location["options"]))

	# ------------------------------------------------------------------ settings
	def test_settings_validation(self):
		s = frappe.get_doc("Rental Settings")
		s.append("cross_hire_warehouses", {"warehouse": self.kochi, "is_active": 1})
		self.assertRaises(frappe.ValidationError, s.save)  # own and cross hire cannot share a warehouse
		s = frappe.get_doc("Rental Settings")
		s.append("own_rental_warehouses", {"warehouse": self.kochi, "is_active": 1})
		self.assertRaises(frappe.ValidationError, s.save)  # listed twice
		s = frappe.get_doc("Rental Settings")
		for r in s.own_rental_warehouses:
			r.is_default = 1
		self.assertRaises(frappe.ValidationError, s.save)  # one default
		s = frappe.get_doc("Rental Settings")
		s.append("own_rental_warehouses", {"warehouse": s.inspection_warehouse, "is_active": 1})
		self.assertRaises(frappe.ValidationError, s.save)  # not a workshop warehouse
		s = frappe.get_doc("Rental Settings")
		group = frappe.db.get_value("Warehouse", self.kochi, "parent_warehouse")
		s.append("own_rental_warehouses", {"warehouse": group, "is_active": 1})
		self.assertRaises(frappe.ValidationError, s.save)  # not a group
		self.assertEqual(rw.location_of(self.calicut), "MW Calicut")

	# ------------------------------------------------------------------ I: concurrent reservations
	def test_i_concurrent_reservations_never_over_reserve(self):
		item = self.item({self.calicut: 100})
		rc1, _site = self.contract([(item, 80)])
		rc2, _site = self.contract([(item, 80)])
		drafts = [self.reserve(rc, default=self.calicut, submit=False) for rc in (rc1, rc2)]
		# both drafts saw 100 free
		self.assertEqual([self.rows(d)[0][3] for d in drafts], [80, 80])
		frappe.db.commit()
		site, sites_path = frappe.local.site, frappe.local.sites_path
		barrier, errors = threading.Barrier(2), []

		def submit(name):
			try:
				frappe.init(site=site, sites_path=sites_path)
				frappe.connect()
				frappe.set_user("Administrator")
				barrier.wait(timeout=30)
				frappe.get_doc("Rental Material Reservation", name).submit()
				frappe.db.commit()
			except Exception as e:  # noqa: BLE001 - reported below
				errors.append(repr(e))
				frappe.db.rollback()
			finally:
				frappe.destroy()

		threads = [threading.Thread(target=submit, args=(n,)) for n in drafts]
		for t in threads:
			t.start()
		for t in threads:
			t.join(timeout=120)
		self.assertFalse(errors, errors)
		frappe.db.commit()  # a fresh snapshot: this session's last one is older than the threads' commits
		reserved = sorted(flt(frappe.db.get_value("Rental Material Reservation Item", {"parent": n}, "reserved_qty")) for n in drafts)
		self.assertEqual(reserved, [20, 80])  # the second waited for the first and got what was left
		self.assertEqual(rmr.free_qty(item, self.calicut), 0)

	# ------------------------------------------------------------------ J: migration
	def test_j_migration_seeds_tables_idempotently(self):
		from thinknxg_rental.patches.v2_2.seed_rental_warehouses import execute

		s = frappe.get_doc("Rental Settings")
		keep = {t: [r.as_dict() for r in s.get(t)] for t in ("own_rental_warehouses", "cross_hire_warehouses")}
		legacy = (s.rental_yard_warehouse, s.cross_hire_yard_warehouse)
		try:
			# an install from before this change: empty tables, only the two yard fields
			frappe.db.delete("Rental Warehouse", {"parent": "Rental Settings"})
			frappe.clear_cache(doctype="Rental Settings")
			execute()
			execute()  # twice: nothing doubles
			s = frappe.get_doc("Rental Settings")
			own = [r.warehouse for r in s.own_rental_warehouses]
			cross = [r.warehouse for r in s.cross_hire_warehouses]
			self.assertEqual(len(own), len(set(own)))
			self.assertEqual(len(cross), len(set(cross)))
			self.assertEqual(rw.default_own_warehouse(), legacy[0])
			self.assertEqual(rw.default_cross_hire_warehouse(), legacy[1])
			self.assertEqual((s.rental_yard_warehouse, s.cross_hire_yard_warehouse), legacy)
			# warehouses earlier documents used stay usable
			self.assertIn(self.kochi, own)
			self.assertIn(self.kochi_x, cross)
			self.assertFalse(set(own) & set(cross))
		finally:
			s = frappe.get_doc("Rental Settings")
			for t, rows in keep.items():
				s.set(t, [{k: r[k] for k in ("warehouse", "location", "is_default", "is_active")} for r in rows])
			s.save(ignore_permissions=True)
			frappe.clear_cache(doctype="Rental Settings")
