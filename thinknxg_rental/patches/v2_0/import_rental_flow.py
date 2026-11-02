"""Import the Rental Flow workspace and its sidebar. Touches only Rental Flow; the existing
thinkNXG Rental workspace and sidebar are never opened. force=True because Frappe skips
files whose timestamp has not changed."""
import os

import frappe
from frappe.modules.import_file import import_file_by_path


def execute():
	for parts in (
		("thinknxg_rental", "workspace", "rental_flow", "rental_flow.json"),
		("workspace_sidebar", "rental_flow.json"),
	):
		path = frappe.get_app_path("thinknxg_rental", *parts)
		if os.path.exists(path):
			import_file_by_path(path, force=True)
	if frappe.db.exists("Workspace", "Rental Flow"):
		frappe.db.set_value("Workspace", "Rental Flow", "sequence_id", 31, update_modified=False)
	frappe.clear_cache()
