"""Thin wrapper around ERPNext Stock Entry. The rental app never writes stock ledger rows itself."""
import frappe
from frappe.utils import flt, nowtime


def make_stock_entry(doc, purpose, rows, posting_date, remarks=None):
	"""rows: dicts with item_code, qty, s_warehouse, t_warehouse, zero_value, batch_no, serial_no."""
	rows = [r for r in rows if flt(r.get("qty")) > 0 and r.get("s_warehouse") != r.get("t_warehouse")]
	if not rows:
		return None
	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = purpose
	se.purpose = purpose
	se.company = doc.company
	se.posting_date = posting_date
	se.posting_time = doc.get("posting_time") or nowtime()
	se.set_posting_time = 1
	se.project = doc.get("project")
	se.remarks = remarks or f"{doc.doctype} {doc.name}"
	se.nxg_hire_voucher_type = doc.doctype
	se.nxg_hire_voucher_no = doc.name
	se.nxg_hire_contract = doc.get("hire_contract")
	for r in rows:
		item = {
			"item_code": r["item_code"],
			"qty": flt(r["qty"]),
			"s_warehouse": r.get("s_warehouse"),
			"t_warehouse": r.get("t_warehouse"),
			# supplier-owned (cross hire) material is carried at zero value
			"allow_zero_valuation_rate": 1 if r.get("zero_value") else 0,
		}
		if r.get("batch_no") or r.get("serial_no"):
			item.update({"use_serial_batch_fields": 1, "batch_no": r.get("batch_no"), "serial_no": r.get("serial_no")})
		se.append("items", item)
	se.flags.ignore_permissions = True
	se.insert()
	se.submit()
	return se.name


def cancel_stock_entries(doc):
	names = frappe.get_all(
		"Stock Entry",
		filters={"nxg_hire_voucher_type": doc.doctype, "nxg_hire_voucher_no": doc.name, "docstatus": 1},
		pluck="name",
		order_by="creation desc",
	)
	for name in names:
		se = frappe.get_doc("Stock Entry", name)
		se.flags.ignore_permissions = True
		se.cancel()
