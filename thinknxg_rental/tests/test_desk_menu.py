"""The desk workspace menu bar (services/desk_menu.py) against the admin portal's ENTRY_TYPES."""
import json

import frappe
from frappe.tests import IntegrationTestCase

from thinknxg_rental.portal.entry import ENTRY_TYPES
from thinknxg_rental.services import desk_menu


class TestDeskMenu(IntegrationTestCase):
	def test_every_portal_entry_is_on_the_bar(self):
		menu = desk_menu.get_menu()
		portal = {i["portal"] for g in menu["groups"] for i in g["items"] if i.get("doctype") and i.get("portal")}
		for key, cfg in ENTRY_TYPES.items():
			if cfg.get("menu") != "none" and frappe.db.exists("DocType", cfg["doctype"]):
				self.assertIn(f"/rental/admin/entries?type={key}", portal, key)

	def test_flow_follows_the_portal_order(self):
		flow = [d["label"] for step in desk_menu.get_menu()["flow"] for d in step]
		order = ["Lead", "Quotation", "Rental Site", "Hire Order", "Rental Contract", "Delivery Order", "Sales Invoice"]
		self.assertEqual([x for x in flow if x in order], order)

	def test_block_and_workspace(self):
		desk_menu.sync()
		self.assertTrue(frappe.db.exists("Custom HTML Block", desk_menu.BLOCK))
		ws = frappe.get_doc("Workspace", "thinkNXG Rental")
		blocks = [b["data"].get("custom_block_name") for b in json.loads(ws.content) if b["type"] == "custom_block"]
		self.assertEqual(blocks, [desk_menu.BLOCK])
		# Newer v16 reads the module's Sidebar; earlier v16 the app's Workspace Sidebar.
		sidebar = "Sidebar" if frappe.db.exists("DocType", "Sidebar") else "Workspace Sidebar"
		sections = [i.label for i in frappe.get_doc(sidebar, "thinkNXG Rental").items if i.type == "Section Break"]
		self.assertEqual(sections, [g["label"] for g in desk_menu.MENU])
