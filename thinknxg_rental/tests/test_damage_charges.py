"""Damage and loss charges end to end (scenarios A-H of the brief):

    Rental Item Profile -> Quotation Item -> Hire Order Item -> Rental Contract Item -> Damage Settlement
    Rental Item Profile -> Hire Order Contract Material -> Rental Contract Item -> Damage Settlement

Each saved row keeps its own lost / beyond repair / repair charges; later profile changes reach only
rows created afterwards, and settlements price from the Rental Contract row.

    bench --site <site> run-tests --module thinknxg_rental.tests.test_damage_charges
"""
import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, nowdate

from thinknxg_rental.services import damage_charges
from thinknxg_rental.services.deal_flow import make_hire_order_contract_from_quotation, make_hire_order_from_quotation
from thinknxg_rental.tests.test_admin_portal import STAFF, _leaf, create, ensure_item, form, prepare, save
from thinknxg_rental.thinknxg_rental.doctype.hire_delivery_order.hire_delivery_order import get_dispatch_items
from thinknxg_rental.thinknxg_rental.doctype.hire_off_hire_note.hire_off_hire_note import make_damage_settlement, make_inspection
from thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract import make_rental_contract

PROFILE = {"lost_charge": 1000, "beyond_repair_charge": 700, "repair_charge": 300}
EDITED = {"nxg_lost_charge": 1200, "nxg_beyond_repair_charge": 800, "nxg_repair_charge": 400}
AGREED = {"lost_charge": 1200, "beyond_repair_charge": 800, "repair_charge": 400}
LATER = {"lost_charge": 1500, "beyond_repair_charge": 900, "repair_charge": 500}
REPLACEMENT = 5000  # deliberately different from every charge: a settlement must never use it here


def tag():
	return frappe.generate_hash(length=5).upper()


def charges(row, fields=damage_charges.FIELDS):
	return {f: flt(row.get(f)) for f in fields}


class TestDamageCharges(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		prepare(cls)
		frappe.set_user("Administrator")
		cls.settings = frappe.get_single("Rental Settings")

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	# ------------------------------------------------------------------ fixtures
	def item(self, stock=100, inspection=1, **profile):
		code = ensure_item(f"DC-{tag()}", "Damage Charge Test Panel")
		frappe.get_doc(dict({"doctype": "Rental Item Profile", "item": code, "daily_rate": 4, "monthly_rate": 80,
			"replacement_value": REPLACEMENT, "inspection_required": inspection}, **(profile or PROFILE))).insert()
		se = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "company": self.company,
			"set_posting_time": 1, "posting_date": add_days(nowdate(), -60),
			"items": [{"item_code": code, "t_warehouse": self.yard, "qty": stock, "basic_rate": 50}]})
		se.insert()
		se.submit()
		return code

	def set_profile(self, item, values):
		p = frappe.get_doc("Rental Item Profile", item)
		p.update(values)
		p.save()

	def quotation(self, rows, deal_type="Material Hire"):
		"""A draft quotation made the way staff make it (lead -> quotation, through the admin portal)."""
		frappe.set_user(STAFF)
		lead = form("lead")
		lead["doc"].update(first_name="Charge", company_name=f"Charge Co {tag()}", deal_type=deal_type, company=self.company)
		lead_name = save("lead", lead["doc"])
		_key, q = create(form("lead", lead_name), "Create Quotation")
		q["doc"].update(items=rows, valid_till=add_days(nowdate(), 30), nxg_required_from=nowdate(),
			nxg_expected_return_date=add_days(nowdate(), 30))
		name = save("quotation", q["doc"])
		frappe.set_user("Administrator")
		return name

	def quotation_charges(self, quotation):
		row = frappe.get_doc("Quotation", quotation).items[0]
		return {f: flt(row.get(f)) for f in damage_charges.FROM_QUOTATION}

	def submit_quotation(self, quotation):
		frappe.set_user(STAFF)
		doc = form("quotation", quotation)
		save("quotation", doc["doc"], submit=True)
		frappe.set_user("Administrator")

	def site_from(self, quotation):
		frappe.set_user(STAFF)
		_key, site = create(form("quotation", quotation), "Create Rental Site")
		site["doc"]["site_name"] = f"Charge Site {tag()}"
		name = save("rental-site", site["doc"])
		frappe.set_user("Administrator")
		return name

	def hire_order_via_portal(self, site):
		frappe.set_user(STAFF)
		_key, ho = create(form("rental-site", site), "Create Hire Order")
		ho["doc"]["order_date"] = nowdate()
		name = save("hire-order", ho["doc"], submit=True)
		frappe.set_user("Administrator")
		return name

	def contract_from_hire_order(self, hire_order):
		frappe.set_user(STAFF)
		_key, rc = create(form("hire-order", hire_order), "Create Rental Contract")
		name = save("rental-contract", rc["doc"], submit=True)
		frappe.set_user("Administrator")
		return name

	def deliver_and_return(self, contract, lost, repairable, beyond):
		"""Deliver everything, off-hire it with `lost` units missing, inspect the rest into good,
		repairable and beyond repair. Returns the off-hire note."""
		do = frappe.get_doc({"doctype": "Hire Delivery Order", "company": self.company, "rental_contract": contract,
			"posting_date": add_days(nowdate(), -10), "items": get_dispatch_items(contract)})
		do.insert()
		do.submit()
		row = do.items[0]
		date = add_days(nowdate(), -2)
		oh = frappe.get_doc({"doctype": "Hire Off-Hire Note", "company": self.company, "rental_contract": contract,
			"off_hire_date": date, "return_date": date, "items": [{"item_code": row.item_code, "ownership": "Own",
				"returned_qty": flt(row.qty) - lost, "lost_qty": lost, "target_warehouse": self.settings.inspection_warehouse,
				"return_to_warehouse": self.yard}]})
		oh.insert()
		oh.submit()
		ins = make_inspection(oh.name)
		d = ins.items[0]
		d.repairable_qty, d.damaged_qty = repairable, beyond
		d.good_qty = flt(d.returned_qty) - repairable - beyond
		ins.insert()
		ins.submit()
		return oh.reload() or oh

	def settle(self, off_hire_note):
		st = make_damage_settlement(off_hire_note)
		st.insert()
		return st

	# ------------------------------------------------------------------ A-D, F-H: material hire
	def test_material_hire_flow_keeps_the_quotation_charges(self):
		item = self.item()
		# A: a new quotation row takes the profile's charges
		q = self.quotation([{"item_code": item, "qty": 20, "rate": 4, "uom": "Nos", "nxg_rate_basis": "Daily"}])
		self.assertEqual(self.quotation_charges(q), {"nxg_lost_charge": 1000, "nxg_beyond_repair_charge": 700, "nxg_repair_charge": 300})
		# B: edited on the quotation, saved and reopened
		frappe.set_user(STAFF)
		doc = form("quotation", q)
		doc["doc"]["items"][0].update(EDITED)
		save("quotation", doc["doc"])
		frappe.set_user("Administrator")
		self.assertEqual(self.quotation_charges(q), EDITED)
		# C: the profile changes; the saved quotation does not
		self.set_profile(item, LATER)
		self.assertEqual(self.quotation_charges(q), EDITED)
		self.submit_quotation(q)
		self.assertEqual(self.quotation_charges(q), EDITED)
		# D: the hire order (made through the admin portal) carries the quotation's values
		ho = self.hire_order_via_portal(self.site_from(q))
		self.assertEqual(charges(frappe.get_doc("Hire Order", ho).items[0]), AGREED)
		# F: so does the rental contract
		rc = self.contract_from_hire_order(ho)
		self.assertEqual(charges(frappe.get_doc("Rental Contract", rc).items[0]), AGREED)
		# the replacement value is kept with them (it was never set on rows made from a quotation)
		self.assertEqual(flt(frappe.get_doc("Hire Order", ho).items[0].replacement_value), REPLACEMENT)
		self.assertEqual(flt(frappe.get_doc("Rental Contract", rc).items[0].replacement_value), REPLACEMENT)
		# H: the profile changes again after the documents exist
		self.set_profile(item, {"lost_charge": 9999, "beyond_repair_charge": 9998, "repair_charge": 9997, "replacement_value": 7777})
		for doctype, name in (("Hire Order", ho), ("Rental Contract", rc)):
			self.assertEqual(charges(frappe.get_doc(doctype, name).items[0]), AGREED, doctype)
		self.assertEqual(self.quotation_charges(q), EDITED)
		# G: lost 2 x 1200 + beyond repair 3 x 800 + repairable 4 x 400 = 6400
		st = self.settle(self.deliver_and_return(rc, lost=2, repairable=4, beyond=3).name)
		got = {d.classification: (flt(d.qty), flt(d.rate), flt(d.amount)) for d in st.items}
		self.assertEqual(got, {"Lost": (2, 1200, 2400), "Beyond Repair": (3, 800, 2400), "Repairable": (4, 400, 1600)})
		self.assertEqual((flt(st.total_loss_amount), flt(st.total_damage_amount), flt(st.grand_total)), (2400, 4000, 6400))
		self.assertTrue(all(rc in d.rate_source for d in st.items))
		self.assertNotIn(REPLACEMENT, [flt(d.rate) for d in st.items])
		self.assertNotIn(7777, [flt(d.rate) for d in st.items])
		# existing totals, liability and invoicing rules still apply
		st.items[0].liability_percent = 50
		st.transport_charges = 100
		st.save()
		self.assertEqual(flt(st.grand_total), 6400 - flt(st.items[0].qty) * flt(st.items[0].rate) / 2 + 100)

	def test_hire_order_from_the_desk_copies_the_quotation_row(self):
		item = self.item()
		q = self.quotation([{"item_code": item, "qty": 5, "rate": 4, "uom": "Nos", "nxg_rate_basis": "Daily", **EDITED, "nxg_charges_set": 1}])
		self.submit_quotation(q)
		self.set_profile(item, LATER)
		site = self.site_from(q)
		ho = make_hire_order_from_quotation(q, args={"rental_site": site})
		self.assertEqual(charges(ho.items[0]), AGREED, "shown on the new hire order before it is saved")
		ho.order_date = nowdate()
		ho.insert()
		self.assertEqual(charges(ho.reload().items[0]), AGREED)

	def test_an_agreed_zero_is_not_replaced_by_the_profile(self):
		item = self.item()
		zero = {"nxg_lost_charge": 0, "nxg_beyond_repair_charge": 0, "nxg_repair_charge": 0, "nxg_charges_set": 1}
		q = self.quotation([{"item_code": item, "qty": 5, "rate": 4, "uom": "Nos", "nxg_rate_basis": "Daily", **zero}])
		self.submit_quotation(q)
		ho = self.hire_order_via_portal(self.site_from(q))
		self.assertEqual(charges(frappe.get_doc("Hire Order", ho).items[0]), dict.fromkeys(damage_charges.FIELDS, 0))

	def test_rows_without_a_source_take_the_profile_once_and_keep_it(self):
		item = self.item()
		customer = frappe.get_doc({"doctype": "Customer", "customer_name": f"Charge Direct {tag()}",
			"customer_group": _leaf("Customer Group"), "territory": _leaf("Territory")}).insert().name
		site = frappe.get_doc({"doctype": "Rental Site", "site_name": f"Direct Site {tag()}", "customer": customer, "company": self.company}).insert().name
		ho = frappe.get_doc({"doctype": "Hire Order", "company": self.company, "customer": customer, "rental_site": site,
			"order_date": nowdate(), "required_from": nowdate(), "expected_return_date": add_days(nowdate(), 10),
			"items": [{"item_code": item, "qty": 3}]}).insert()
		self.assertEqual(charges(ho.items[0]), PROFILE)
		self.set_profile(item, LATER)
		ho.items[0].qty = 4
		ho.save()
		self.assertEqual(charges(ho.reload().items[0]), PROFILE, "a saved row never follows the profile")
		# a row edited on the hire order keeps the edit
		ho.items[0].lost_charge = 1111
		ho.save()
		self.assertEqual(flt(ho.reload().items[0].lost_charge), 1111)
		with self.assertRaises(frappe.ValidationError):
			ho.items[0].repair_charge = -1
			ho.save()

	# ------------------------------------------------------------------ E: hire order contract
	def test_hire_order_contract_materials_carry_the_charges(self):
		tube = self.item()
		job = f"DC-JOB-{tag()}"
		frappe.get_doc({"doctype": "Item", "item_code": job, "item_name": "Damage Charge Test Job", "item_group": _leaf("Item Group"),
			"stock_uom": "Nos", "is_stock_item": 0}).insert()
		frappe.get_doc({"doctype": "Job Type", "item_code": job, "job_type_name": job, "rental_items": [{"item_code": tube, "qty": 20}]}).insert()
		q = self.quotation([{"item_code": job, "qty": 1, "rate": 10000, "uom": "Nos", "nxg_included_days": 30,
			"nxg_excess_basis": "Daily", "nxg_excess_rate": 100}], deal_type="Hire Order Contract")
		self.submit_quotation(q)
		site = self.site_from(q)
		hoc = make_hire_order_contract_from_quotation(q, args={"rental_site": site})
		hoc.order_date = nowdate()
		hoc.insert()
		# the physical item was not on the quotation: its charges come from the profile when exploded
		self.assertEqual(charges(hoc.materials[0]), PROFILE)
		hoc.materials[0].update(AGREED)  # agreed on the contract
		hoc.save()
		hoc.submit()
		self.set_profile(tube, LATER)
		self.assertEqual(charges(frappe.get_doc("Hire Order Contract", hoc.name).materials[0]), AGREED)
		rc = make_rental_contract(hoc.name)
		self.assertEqual(charges(rc.items[0]), AGREED)
		rc.insert()
		rc.submit()
		self.assertEqual(charges(frappe.get_doc("Rental Contract", rc.name).items[0]), AGREED)
		self.set_profile(tube, {"lost_charge": 9999, "repair_charge": 9997, "beyond_repair_charge": 9998})
		st = self.settle(self.deliver_and_return(rc.name, lost=2, repairable=4, beyond=3).name)
		self.assertEqual(flt(st.grand_total), 6400)

	def test_one_item_one_set_of_charges_on_a_contract(self):
		tube = self.item()
		hoc = frappe.new_doc("Hire Order Contract")
		hoc.materials = []
		hoc.append("materials", {"item_code": tube, "qty": 5, **PROFILE})
		hoc.append("materials", {"item_code": tube, "qty": 5, **AGREED})
		with self.assertRaises(frappe.ValidationError):
			damage_charges.hire_order_contract(hoc)

	# ------------------------------------------------------------------ settlement edge cases
	def test_contract_without_agreed_charges_falls_back_to_its_replacement_value(self):
		"""A contract agreed before these charges existed (zero charges): Lost and Beyond Repair use the
		replacement value saved on the contract row, repairs stay at zero - not the profile's values."""
		item = self.item(lost_charge=0, beyond_repair_charge=0, repair_charge=0)
		q = self.quotation([{"item_code": item, "qty": 10, "rate": 4, "uom": "Nos", "nxg_rate_basis": "Daily"}])
		self.submit_quotation(q)
		rc = self.contract_from_hire_order(self.hire_order_via_portal(self.site_from(q)))
		self.set_profile(item, {"replacement_value": 7777, "repair_charge": 55})
		st = self.settle(self.deliver_and_return(rc, lost=1, repairable=1, beyond=1).name)
		self.assertEqual({d.classification: flt(d.rate) for d in st.items}, {"Lost": REPLACEMENT, "Beyond Repair": REPLACEMENT, "Repairable": 0})

	def test_settlement_rate_rules(self):
		row = frappe._dict(item_code="X", replacement_value=500, lost_charge=0, beyond_repair_charge=80, repair_charge=0)
		self.assertEqual(damage_charges.settlement_rate("RC-1", row, "Beyond Repair")[0], 80)
		# agreed before these charges existed: the replacement value saved on the same contract row
		rate, source = damage_charges.settlement_rate("RC-1", row, "Lost")
		self.assertEqual(rate, 500)
		self.assertIn("RC-1", source)
		# repairs never fall back to the replacement value
		self.assertEqual(damage_charges.settlement_rate("RC-1", row, "Repairable")[0], 0)
		self.assertEqual(damage_charges.settlement_rate("RC-1", None, "Lost")[0], 0)

	def test_backfill_patch_uses_the_source_documents(self):
		from thinknxg_rental.patches.v2_4 import backfill_damage_charges

		item = self.item()
		q = self.quotation([{"item_code": item, "qty": 5, "rate": 4, "uom": "Nos", "nxg_rate_basis": "Daily", **EDITED, "nxg_charges_set": 1}])
		self.submit_quotation(q)
		ho = self.hire_order_via_portal(self.site_from(q))
		rc = self.contract_from_hire_order(ho)
		# as a row saved before 2.5 looks: no charges, no replacement value
		for child, parent in (("Hire Order Item", ho), ("Rental Contract Item", rc)):
			for name in frappe.get_all(child, filters={"parent": parent}, pluck="name"):
				frappe.db.set_value(child, name, dict(dict.fromkeys(damage_charges.FIELDS, 0), replacement_value=0), update_modified=False)
		self.set_profile(item, LATER)
		backfill_damage_charges.execute()
		self.assertEqual(charges(frappe.get_doc("Hire Order", ho).items[0]), AGREED, "from the quotation row, not the profile")
		self.assertEqual(charges(frappe.get_doc("Rental Contract", rc).items[0]), AGREED, "from the hire order row")
		self.assertEqual(flt(frappe.get_doc("Rental Contract", rc).items[0].replacement_value), REPLACEMENT)
		backfill_damage_charges.execute()  # again: nothing changes
		self.assertEqual(charges(frappe.get_doc("Rental Contract", rc).items[0]), AGREED)

	def test_fields_are_on_every_transaction_row(self):
		for doctype in ("Hire Order Item", "Hire Order Contract Material", "Rental Contract Item"):
			meta = frappe.get_meta(doctype)
			for f in damage_charges.FIELDS:
				df = meta.get_field(f)
				self.assertTrue(df, f"{doctype}.{f}")
				self.assertEqual(df.fieldtype, "Currency")
				self.assertTrue(df.non_negative)
				self.assertFalse(df.in_list_view, "kept out of the full grid; shown in the row editor")
		self.assertTrue(frappe.get_meta("Rental Damage Settlement Item").get_field("rate_source").read_only)
		for f in damage_charges.FROM_QUOTATION:
			self.assertTrue(frappe.get_meta("Quotation Item").get_field(f), f)
