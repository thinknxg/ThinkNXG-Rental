"""2.5: Hire Order, Hire Order Contract material and Rental Contract rows keep their own damage and loss
charges (lost, beyond repair, repair). Rows made before then have none: give each the charges of the
document it was made from, so settlements use agreed values and not the profile's current ones:

* Hire Order rows: the quotation row of the same item (its saved snapshot);
* Hire Order Contract materials: the quotation row of the same item, when the quotation lists it;
* Rental Contract rows: the Hire Order row or the Hire Order Contract material of the same item.

Rows without a replacement value (rows made from a quotation never got one) take the Hire Order row's,
else the profile's: Lost and Beyond Repair fall back to it when no charge was agreed.

Only when there is no such source does a row take the Rental Item Profile's values (the best record of
what was agreed). Rows that already have charges are left alone, so the patch can run again safely."""
import frappe
from frappe.utils import flt

from thinknxg_rental.services.damage_charges import FIELDS, FROM_QUOTATION, profile_charges

ZERO = " and ".join(f"ifnull(c.{f}, 0) = 0" for f in FIELDS)


def execute():
	for doctype in ("Hire Order Item", "Hire Order Contract Material", "Rental Contract Item"):
		frappe.reload_doc("thinknxg_rental", "doctype", frappe.scrub(doctype))
	profiles = {}

	def profile(item_code):
		if item_code not in profiles:
			profiles[item_code] = profile_charges(item_code)
		return profiles[item_code]

	def quoted(quotation):
		out = {}
		if quotation and frappe.get_meta("Quotation Item").has_field("nxg_lost_charge"):
			for r in frappe.get_all("Quotation Item", filters={"parent": quotation, "parenttype": "Quotation"},
					fields=["item_code", *FROM_QUOTATION], order_by="idx"):
				out.setdefault(r.item_code, {t: flt(r.get(s)) for s, t in FROM_QUOTATION.items()})
		return out

	def fill(child, parent, source_of):
		rows = frappe.db.sql(f"""select c.name, c.parent, c.item_code from `tab{child}` c
			where c.parenttype = %s and ifnull(c.item_code, '') != '' and {ZERO}""", parent, as_dict=True)
		cache = {}
		for r in rows:
			if r.parent not in cache:
				cache[r.parent] = source_of(r.parent)
			values = cache[r.parent].get(r.item_code) or profile(r.item_code)
			if any(flt(v) for v in values.values()):
				frappe.db.set_value(child, r.name, values, update_modified=False)

	fill("Hire Order Item", "Hire Order", lambda name: quoted(frappe.db.get_value("Hire Order", name, "quotation")))
	fill("Hire Order Contract Material", "Hire Order Contract",
		lambda name: quoted(frappe.db.get_value("Hire Order Contract", name, "quotation")))

	def contract_source(name):
		source_type, source = frappe.db.get_value("Rental Contract", name, ["source_type", "source_document"]) or (None, None)
		if not source:
			return {}
		child = {"Hire Order": "Hire Order Item", "Hire Order Contract": "Hire Order Contract Material"}.get(source_type)
		out = {}
		for r in frappe.get_all(child, filters={"parent": source, "parenttype": source_type}, fields=["item_code", *FIELDS], order_by="idx"):
			if any(flt(r.get(f)) for f in FIELDS):
				out.setdefault(r.item_code, {f: flt(r.get(f)) for f in FIELDS})
		return out

	fill("Rental Contract Item", "Rental Contract", contract_source)

	# the replacement value (fallback for Lost / Beyond Repair when no charge was agreed): rows made from a
	# quotation never got one; take the Hire Order row's, else the profile's
	for child in ("Hire Order Item", "Rental Contract Item"):
		for r in frappe.db.sql(f"""select c.name, c.parent, c.item_code from `tab{child}` c
				where ifnull(c.item_code, '') != '' and ifnull(c.replacement_value, 0) = 0""", as_dict=True):
			value = 0
			if child == "Rental Contract Item":
				source_type, source = frappe.db.get_value("Rental Contract", r.parent, ["source_type", "source_document"]) or (None, None)
				if source_type == "Hire Order":
					value = flt(frappe.db.get_value("Hire Order Item", {"parent": source, "item_code": r.item_code}, "replacement_value"))
			if not value and frappe.db.exists("Rental Item Profile", r.item_code):
				value = flt(frappe.db.get_value("Rental Item Profile", r.item_code, "replacement_value"))
			if value:
				frappe.db.set_value(child, r.name, "replacement_value", value, update_modified=False)
