"""Excess received on off-hire notes submitted before the Excess Material Register existed: give each
such row its register (once), linked to the Material Receipt that already put it into the excess
warehouse. No stock is moved."""
import frappe
from frappe.utils import flt

from thinknxg_rental.services import excess
from thinknxg_rental.services.utils import get_settings


def execute():
	for doctype in ("Excess Material Register", "Hire Off-Hire Note", "Hire Off-Hire Item"):
		frappe.reload_doc("thinknxg_rental", "doctype", frappe.scrub(doctype))
	notes = frappe.db.sql_list(
		"""select distinct n.name from `tabHire Off-Hire Note` n inner join `tabHire Off-Hire Item` i on i.parent = n.name
		where n.docstatus = 1 and i.excess_qty > 0 and ifnull(i.excess_register, '') = ''""")
	default = get_settings().get("excess_warehouse")
	for name in notes:
		note = frappe.get_doc("Hire Off-Hire Note", name)
		entry = frappe.db.get_value("Stock Entry", {"nxg_hire_voucher_type": "Hire Off-Hire Note", "nxg_hire_voucher_no": name,
			"purpose": "Material Receipt", "docstatus": 1}, "name")
		targets = {}
		if entry:
			for r in frappe.get_all("Stock Entry Detail", filters={"parent": entry}, fields=["item_code", "t_warehouse"]):
				targets.setdefault(r.item_code, r.t_warehouse)
		rows = [d for d in note.items if flt(d.excess_qty) > 0 and not d.get("excess_register")]
		for d in rows:
			d.excess_warehouse = d.get("excess_warehouse") or targets.get(d.item_code) or default
			d.excess_category = excess.excess_category(note.rental_contract, d.item_code)
			d.db_set({"excess_warehouse": d.excess_warehouse, "excess_category": d.excess_category, "is_excess": 1}, update_modified=False)
		note.db_set({"total_excess_qty": sum(flt(d.excess_qty) for d in note.items), "excess_stock_entry": entry}, update_modified=False)
		note.items = [d for d in note.items if d in rows]
		excess.make_registers(note, entry)
