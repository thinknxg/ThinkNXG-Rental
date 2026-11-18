"""v2.6.0: the workspace and both sidebars gain the Excess Material group (Excess Material Register,
Return Note, Dismantling Entry, Abandonment, Conversion Entry) and the four excess reports. Re-import
them once, replacing what is stored, so a site that kept an older copy shows the new entries."""
import os

import frappe
from frappe.modules.import_file import import_file_by_path


def execute():
	for parts in (
		("thinknxg_rental", "workspace", "thinknxg_rental", "thinknxg_rental.json"),
		("thinknxg_rental", "sidebar", "thinknxg_rental", "thinknxg_rental.json"),
		("workspace_sidebar", "thinknxg_rental.json"),
	):
		path = frappe.get_app_path("thinknxg_rental", *parts)
		doctype = json_doctype(path)
		if doctype and frappe.db.exists("DocType", doctype):
			import_file_by_path(path, force=True)
	frappe.clear_cache()


def json_doctype(path):
	if not os.path.exists(path):
		return None
	import json

	with open(path) as fh:
		return json.load(fh).get("doctype")
