"""Desk forms of Rental Material Reservation, Hire Delivery Order and Hire Off-Hire Note: every field
is synced to the site, the item tables fit the form (Frappe's 10 grid units, short headings), related
fields sit together in the row editor, and the details that may follow a submitted document stay
editable.

    bench --site <site> run-tests --module thinknxg_rental.tests.test_desk_forms
"""
import json
import os

import frappe
from frappe.tests import IntegrationTestCase

LAYOUT = ("Section Break", "Column Break", "Tab Break")
FORMS = {
	"Rental Material Reservation": "Rental Material Reservation Item",
	"Hire Delivery Order": "Hire Delivery Item",
	"Hire Off-Hire Note": "Hire Off-Hire Item",
}
# grid columns as the user sees them: (fieldname, label)
GRIDS = {
	"Rental Material Reservation Item": [("item_code", "Item"), ("required_qty", "Qty"), ("source_warehouse", "Warehouse"),
		("available_qty", "Available"), ("reserved_qty", "Reserved"), ("shortfall_qty", "Shortfall")],
	"Hire Delivery Item": [("item_code", "Item"), ("qty", "Qty"), ("ownership", "Ownership"), ("source_warehouse", "From Warehouse")],
	"Hire Off-Hire Item": [("item_code", "Item"), ("at_site_qty", "At Site"), ("received_qty", "Received"), ("returned_qty", "Returned"), ("lost_qty", "Lost"),
		("excess_qty", "Excess"), ("target_warehouse", "Return To")],
}
AFTER_SUBMIT = {
	"Hire Delivery Order": {"vehicle_no", "driver_name", "driver_phone", "transporter", "dispatch_reference", "remarks"},
	"Hire Off-Hire Note": {"vehicle_no", "driver_name", "remarks"},
	"Rental Material Reservation": {"remarks"},
}
# hidden on purpose: naming series, amendment link, and the legacy source links kept for old records
HIDDEN = {"Rental Material Reservation": {"hire_order", "hire_order_contract"}}


def json_meta(doctype):
	name = frappe.scrub(doctype)
	path = frappe.get_app_path("thinknxg_rental", "thinknxg_rental", "doctype", name, name + ".json")
	with open(path) as f:
		return json.load(f)


class TestDeskForms(IntegrationTestCase):
	def test_every_field_is_synced_to_the_site(self):
		for parent, child in FORMS.items():
			for doctype in (parent, child):
				in_file = [f["fieldname"] for f in json_meta(doctype)["fields"]]
				in_db = frappe.get_all("DocField", filters={"parent": doctype}, pluck="fieldname", order_by="idx")
				self.assertEqual(in_db, in_file, doctype)
				self.assertEqual(json_meta(doctype)["field_order"], in_file, doctype)

	def test_no_field_is_hidden_by_accident(self):
		for parent, child in FORMS.items():
			for doctype in (parent, child):
				meta = frappe.get_meta(doctype)
				hidden = {f.fieldname for f in meta.fields if f.hidden and f.fieldtype not in LAYOUT}
				self.assertEqual(hidden, HIDDEN.get(doctype, set()), doctype)
				self.assertFalse(frappe.get_all("Property Setter", filters={"doc_type": doctype, "property": "hidden", "value": "1"}), doctype)

	def test_item_tables_fit_the_form(self):
		for child, expected in GRIDS.items():
			meta = frappe.get_meta(child)
			grid = [(f.fieldname, f.label) for f in meta.fields if f.in_list_view]
			self.assertEqual(grid, expected, child)
			self.assertLessEqual(sum(f.columns or 1 for f in meta.fields if f.in_list_view), 10, child)
			for f in meta.fields:
				if f.in_list_view:
					self.assertLessEqual(len(f.label), 14, f"{child}.{f.fieldname}: a long heading is cut off in the grid")

	def test_off_hire_row_keeps_quantities_and_warehouses_together(self):
		order = [f.fieldname for f in frappe.get_meta("Hire Off-Hire Item").fields]
		quantities = ["at_site_qty", "returned_qty", "lost_qty", "excess_qty", "pending_qty"]
		self.assertEqual([order.index(n) for n in quantities], sorted(order.index(n) for n in quantities))
		self.assertEqual(order.index("excess_qty"), order.index("lost_qty") + 1)
		self.assertEqual(order.index("return_to_warehouse"), order.index("target_warehouse") + 1)
		self.assertLess(order.index("excess_qty"), order.index("sb_68"))  # before Serial / Batch

	def test_cross_hire_order_column_only_where_it_applies(self):
		f = frappe.get_meta("Hire Delivery Item").get_field("cross_hire_order")
		self.assertFalse(f.in_list_view)
		self.assertIn("Cross Hire", f.depends_on)

	def test_details_after_submit_are_editable(self):
		for doctype, names in AFTER_SUBMIT.items():
			meta = frappe.get_meta(doctype)
			editable = {f.fieldname for f in meta.fields if f.allow_on_submit}
			self.assertTrue(names <= editable, doctype)
			# nothing that moves stock or money opens up after submit
			self.assertFalse(editable & {"items", "company", "posting_date", "off_hire_date", "return_date", "source_warehouse"}, doctype)

	def test_rental_forms_get_room_on_laptops(self):
		css = open(frappe.get_app_path("thinknxg_rental", "public", "css", "rental_menu.css")).read()
		js = open(frappe.get_app_path("thinknxg_rental", "public", "js", "rental_menu.js")).read()
		self.assertIn("body.nxg-rental-form .layout-main.layout-two-column", css)
		self.assertIn("max-width: 1365.98px", css)
		self.assertIn('classList.toggle("nxg-rental-form"', js)
		# the floating menu steps aside while scrolling down
		self.assertIn(".nxg-fbar.nxg-fbar-away", css)
		self.assertIn("function watch_scroll", js)
		hooks = frappe.get_hooks("app_include_css", app_name="thinknxg_rental")
		self.assertTrue(any(h.endswith("rental_menu.css") for h in hooks))
		self.assertTrue(os.path.exists(frappe.get_app_path("thinknxg_rental", "public", "js", "rental_menu.js")))


class TestFormScriptsStandAlone(IntegrationTestCase):
	"""A form must not depend on a separately loaded desk script (app_include_js): when that file was
	missing or an old cached copy, setup stopped at "thinknxg_rental is not defined" and the form showed
	its section headings with no fields. Helpers a form script calls travel with the form."""

	def test_forms_ship_the_warehouse_helper(self):
		import re

		from frappe.desk.form.meta import get_meta

		root = frappe.get_app_path("thinknxg_rental", "thinknxg_rental", "doctype")
		users = []
		for name in sorted(os.listdir(root)):
			path = os.path.join(root, name, name + ".js")
			if os.path.exists(path) and re.search(r"thinknxg_rental\.rental_warehouses\(", open(path).read()):
				with open(os.path.join(root, name, name + ".json")) as f:
					users.append(json.load(f)["name"])
		self.assertTrue({"Rental Material Reservation", "Hire Delivery Order", "Hire Off-Hire Note"} <= set(users))
		hooks = frappe.get_hooks("doctype_js", app_name="thinknxg_rental")
		for doctype in users:
			self.assertIn("public/js/rental_warehouses.js", hooks.get(doctype, []), doctype)
			js = get_meta(doctype, cached=False).get("__js") or ""
			self.assertIn("thinknxg_rental.rental_warehouses = function", js, doctype)
			self.assertIn('frappe.provide("thinknxg_rental")', js, doctype)
