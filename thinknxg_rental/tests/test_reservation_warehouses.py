"""Rental Material Reservation: each row's source warehouse follows where its material comes from.

* Own stock: the Default Source Warehouse when it covers the row, else the own warehouse with the
  most free stock of the item.
* No own stock free anywhere: Cross Hire, in the warehouse cross-hired units arrive in (the open Cross
  Hire Order's receipt warehouse for the item, else the Cross Hire Yard); the whole row is shortfall.

    bench --site <site> run-tests --module thinknxg_rental.tests.test_reservation_warehouses
"""
import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, nowdate

from thinknxg_rental.tests.test_admin_portal import STAFF, create, ensure_item, form, prepare, save, settings
from thinknxg_rental.thinknxg_rental.doctype.rental_material_reservation import rental_material_reservation as rmr

MODULE = "thinknxg_rental.thinknxg_rental.doctype.rental_material_reservation.rental_material_reservation"


def hash4():
	return frappe.generate_hash(length=5).upper()


class TestReservationWarehouses(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		prepare(cls)
		frappe.set_user("Administrator")
		s = settings()
		cls.cross_yard = s.cross_hire_yard_warehouse
		# a second own warehouse that is the only place one item is stocked
		parent = frappe.db.get_value("Warehouse", cls.yard, "parent_warehouse")
		name = frappe.db.get_value("Warehouse", {"warehouse_name": "RW Second Yard", "company": cls.company})
		if not name:
			name = frappe.get_doc({"doctype": "Warehouse", "warehouse_name": "RW Second Yard", "company": cls.company,
				"parent_warehouse": parent}).insert().name
		cls.second_yard = name
		cls.prop = ensure_item("RW-PROP", "Reservation Test Prop")         # only in the second yard
		cls.genset = ensure_item("RW-GENSET", "Reservation Test Genset")   # no own stock anywhere: cross hire
		for code in (cls.prop, cls.genset):
			if not frappe.db.exists("Rental Item Profile", code):
				frappe.get_doc({"doctype": "Rental Item Profile", "item": code, "daily_rate": 5, "monthly_rate": 100}).insert()
		if flt(frappe.db.get_value("Bin", {"item_code": cls.prop, "warehouse": cls.second_yard}, "actual_qty")) < 50:
			se = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "company": cls.company,
				"set_posting_time": 1, "posting_date": add_days(nowdate(), -90),
				"items": [{"item_code": cls.prop, "t_warehouse": cls.second_yard, "qty": 50, "basic_rate": 30}]})
			se.insert()
			se.submit()
		frappe.db.commit()

	def setUp(self):
		frappe.set_user(STAFF)

	def tearDown(self):
		frappe.set_user("Administrator")

	# ------------------------------------------------------------------ helpers
	def contract(self, rows):
		"""Lead -> quotation -> site -> hire order -> rental contract, through the portal."""
		lead = form("lead")
		lead["doc"].update(first_name="Res", company_name=f"Res Co {hash4()}", deal_type="Material Hire", company=self.company)
		lead_name = save("lead", lead["doc"])
		key, q = create(form("lead", lead_name), "Create Quotation")
		q["doc"].update(items=[{"item_code": c, "qty": qty, "rate": 4, "uom": "Nos", "nxg_rate_basis": "Daily"} for c, qty in rows],
			valid_till=add_days(nowdate(), 30), nxg_required_from=nowdate(), nxg_expected_return_date=add_days(nowdate(), 30))
		quotation = save("quotation", q["doc"], submit=True)
		key, site = create(form("quotation", quotation), "Create Rental Site")
		site["doc"]["site_name"] = f"Res Site {hash4()}"
		site_name = save("rental-site", site["doc"])
		key, ho = create(form("rental-site", site_name), "Create Hire Order")
		ho["doc"]["order_date"] = nowdate()
		ho_name = save("hire-order", ho["doc"], submit=True)
		key, rc = create(form("hire-order", ho_name), "Create Rental Contract")
		return save("rental-contract", rc["doc"], submit=True), site_name

	def reservation(self, rental_contract, submit=False, **header):
		key, res = create(form("rental-contract", rental_contract), "Material Reservation")
		res["doc"].update(source_warehouse=self.yard, **header)
		return save("material-reservation", res["doc"], submit=submit)

	def rows(self, reservation):
		return {d.item_code: (d.source_warehouse, d.ownership, flt(d.reserved_qty), flt(d.shortfall_qty))
			for d in frappe.get_doc("Rental Material Reservation", reservation).items}

	# ------------------------------------------------------------------ placement
	def test_mixed_own_and_cross_hire_rows(self):
		tube_free = rmr.free_qty(self.tube, self.yard)
		rc, _site = self.contract([(self.tube, 10), (self.prop, 20), (self.genset, 4)])
		res = self.reservation(rc)
		rows = self.rows(res)
		self.assertGreater(tube_free, 10)
		self.assertEqual(rows[self.tube], (self.yard, "Own", 10, 0))           # the default covers it
		self.assertEqual(rows[self.prop], (self.second_yard, "Own", 20, 0))    # only stocked elsewhere
		self.assertEqual(rows[self.genset], (self.cross_yard, "Cross Hire", 0, 4))  # nothing free: cross hire
		doc = frappe.get_doc("Rental Material Reservation", res)
		self.assertEqual((flt(doc.total_reserved_qty), flt(doc.total_shortfall_qty)), (30, 4))

	def test_partial_own_stock_stays_own_with_its_shortfall(self):
		free = rmr.free_qty(self.prop, self.second_yard)
		rc, _site = self.contract([(self.prop, free + 7)])
		res = self.reservation(rc)
		self.assertEqual(self.rows(res)[self.prop], (self.second_yard, "Own", free, 7))

	def test_cross_hire_rows_go_on_the_cross_hire_order_and_not_on_deliveries(self):
		rc, _site = self.contract([(self.tube, 5), (self.genset, 3)])
		res = self.reservation(rc, submit=True)
		self.assertEqual(frappe.db.get_value("Rental Material Reservation", res, "status"), "Partially Reserved")
		# the Cross Hire Order for the shortfall has the genset
		frappe.set_user("Administrator")
		cho = frappe.get_attr(MODULE + ".make_cross_hire_order")(res)
		self.assertEqual([(d.item_code, flt(d.qty)) for d in cho.items], [(self.genset, 3)])
		# own-stock warehouses of the reservation leave the cross hire row out, so the delivery's own
		# lines are never sent out of the cross hire yard
		self.assertEqual(rmr.get_reservation_warehouses(res), {self.tube: self.yard})
		from thinknxg_rental.thinknxg_rental.doctype.hire_delivery_order.hire_delivery_order import get_dispatch_items

		own = [(r["item_code"], r["source_warehouse"]) for r in get_dispatch_items(rc, res) if r["ownership"] == "Own"]
		self.assertEqual(own, [(self.tube, self.yard)])

	def test_cross_hire_row_uses_the_cross_hire_orders_warehouse(self):
		rc, site = self.contract([(self.genset, 2)])
		site_cross = frappe.db.get_value("Rental Site", site, "cross_hire_site_warehouse")
		if not site_cross:
			self.skipTest("rental sites have no cross hire warehouse on this site")
		frappe.set_user("Administrator")
		supplier = frappe.db.get_value("Supplier", {"disabled": 0}, "name") or frappe.get_doc(
			{"doctype": "Supplier", "supplier_name": f"RW Supplier {hash4()}", "supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0})}).insert().name
		cho = frappe.get_doc({"doctype": "Cross Hire Order", "company": self.company, "supplier": supplier, "rental_contract": rc,
			"rental_site": site, "order_date": nowdate(), "hire_from": nowdate(), "expected_return_date": add_days(nowdate(), 30),
			"receive_at": "Direct to Site", "items": [{"item_code": self.genset, "qty": 2, "rate": 50}]})
		cho.insert()
		cho.submit()
		frappe.set_user(STAFF)
		res = self.reservation(rc)
		self.assertEqual(self.rows(res)[self.genset], (site_cross, "Cross Hire", 0, 2))

	def test_row_left_on_an_empty_default_is_placed_again(self):
		# a draft saved before this fix had every row on the Default Source Warehouse
		rc, _site = self.contract([(self.prop, 5), (self.genset, 1)])
		res = self.reservation(rc)
		frappe.set_user("Administrator")
		doc = frappe.get_doc("Rental Material Reservation", res)
		for d in doc.items:
			frappe.db.set_value(d.doctype, d.name, {"source_warehouse": self.yard, "ownership": "Own"})
		doc.reload()
		doc.save()
		self.assertEqual(self.rows(res)[self.prop][:2], (self.second_yard, "Own"))
		self.assertEqual(self.rows(res)[self.genset][:2], (self.cross_yard, "Cross Hire"))

	def test_hand_picked_own_warehouse_is_kept(self):
		rc, _site = self.contract([(self.tube, 3)])
		key, res = create(form("rental-contract", rc), "Material Reservation")
		res["doc"]["source_warehouse"] = self.second_yard  # header default without tubes
		for d in res["doc"]["items"]:
			d["source_warehouse"] = self.yard  # chosen by hand
		name = save("material-reservation", res["doc"])
		self.assertEqual(self.rows(name)[self.tube], (self.yard, "Own", 3, 0))

	def test_live_row_figures_say_where_and_how(self):
		live = rmr.get_row_availability(self.genset, self.company, default_warehouse=self.yard, required_qty=2)
		self.assertEqual((live["source_warehouse"], live["ownership"], live["available_qty"]), (self.cross_yard, "Cross Hire", 0))
		live = rmr.get_row_availability(self.prop, self.company, default_warehouse=self.yard, required_qty=2)
		self.assertEqual((live["source_warehouse"], live["ownership"]), (self.second_yard, "Own"))
		self.assertGreater(live["available_qty"], 0)

	def test_portal_shows_the_supply_column(self):
		boot = form("material-reservation")
		cols = [c["fieldname"] for c in boot["tables"][0]["columns"]]
		self.assertIn("ownership", cols)

	def test_website_availability_matches_reservable_stock(self):
		"""The public website's free stock (computed for many items at once) is the same figure the
		reservation and dispatch checks use, before and after a reservation takes stock."""
		from thinknxg_rental.services.warehouses import available_own_qty
		from thinknxg_rental.website.catalogue import free_stock

		items = [self.tube, self.prop, self.genset]
		frappe.set_user("Administrator")
		self.assertEqual({i: flt(free_stock(items)[i]) for i in items}, {i: flt(available_own_qty(i)) for i in items})
		frappe.set_user(STAFF)
		rc, _site = self.contract([(self.tube, 6), (self.prop, 9)])
		self.reservation(rc, submit=True)
		frappe.set_user("Administrator")
		after = free_stock(items)
		self.assertEqual({i: flt(after[i]) for i in items}, {i: flt(available_own_qty(i)) for i in items})
