"""Damage and loss charges: lost, beyond repair and repair, per unit.

The Rental Item Profile holds the defaults. Every transaction row keeps its own copy (a snapshot) taken
once, when the row is created, from the document it was made from:

    Rental Item Profile -> Quotation Item (nxg_* fields, editable; services/item_rental.py)
                        -> Hire Order Item              (from its quotation row)
                        -> Hire Order Contract Material (from its quotation, else the profile when exploded)
                        -> Rental Contract Item         (from the Hire Order row or Hire Order Contract material)
                        -> Rental Damage Settlement     (rate from the Rental Contract row)

A row is filled only while it is new and has no charges yet; after that its values are never refreshed
from the profile or the source, so editing the profile changes only rows created later. Nothing here
reads the profile for a saved row.
"""
import frappe
from frappe import _
from frappe.utils import flt

FIELDS = ("lost_charge", "beyond_repair_charge", "repair_charge")
# Quotation Item custom field -> transaction row field
FROM_QUOTATION = {"nxg_lost_charge": "lost_charge", "nxg_beyond_repair_charge": "beyond_repair_charge", "nxg_repair_charge": "repair_charge"}
# settlement classification -> charge, and the snapshot used when no charge was agreed
SETTLEMENT = {
	"Lost": ("lost_charge", "replacement_value"),
	"Beyond Repair": ("beyond_repair_charge", "replacement_value"),
	"Repairable": ("repair_charge", None),
}


def has_charges(row):
	return any(flt(row.get(f)) for f in FIELDS)


def profile_charges(item_code):
	"""Defaults from the Rental Item Profile (zero without a profile). Used only for a new row."""
	out = dict.fromkeys(FIELDS, 0.0)
	if item_code and frappe.db.exists("Rental Item Profile", item_code):
		values = frappe.db.get_value("Rental Item Profile", item_code, list(FIELDS), as_dict=True) or {}
		out.update({f: flt(values.get(f)) for f in FIELDS})
	return out


def quotation_row_charges(row):
	"""The charges a quotation row was saved with (its own snapshot, edits included)."""
	return {target: flt(row.get(source)) for source, target in FROM_QUOTATION.items()}


def check_non_negative(doc, table="items"):
	for row in doc.get(table) or []:
		for f in FIELDS:
			if flt(row.get(f)) < 0:
				frappe.throw(_("Row #{0}: {1} cannot be negative").format(row.idx, _(row.meta.get_label(f))), title=_("Invalid amount"))


def new_rows(doc, table):
	"""Rows of ``table`` not saved before (all rows of a new document)."""
	before = doc.get_doc_before_save() if not doc.is_new() else None
	saved = {r.name for r in (before.get(table) or [])} if before else set()
	return [row for row in doc.get(table) or [] if row.get("item_code") and row.name not in saved]


def fill_replacement_value(doc, table, source_for):
	"""The replacement value is part of the same snapshot (Lost and Beyond Repair fall back to it when no
	charge was agreed): a new row without one takes its source row's, else the profile's."""
	for row in new_rows(doc, table):
		if flt(row.get("replacement_value")):
			continue
		value = flt((source_for(row) or {}).get("replacement_value"))
		if not value and frappe.db.exists("Rental Item Profile", row.item_code):
			value = flt(frappe.db.get_value("Rental Item Profile", row.item_code, "replacement_value"))
		row.replacement_value = value


def fill_new_rows(doc, table, source_for):
	"""Give each new row of ``table`` without charges its snapshot: ``source_for(row)`` returns the charges
	of the row it came from (a dict, zeros allowed: an agreed zero stays zero), or None to take the
	profile's defaults. Rows saved before keep what they have."""
	before = doc.get_doc_before_save() if not doc.is_new() else None
	saved = {r.name for r in (before.get(table) or [])} if before else set()
	for row in doc.get(table) or []:
		if not row.get("item_code") or row.name in saved or has_charges(row):
			continue
		values = source_for(row)
		row.update(values if values is not None else profile_charges(row.item_code))


# ----------------------------------------------------------------------------- per document
def hire_order(doc, method=None):
	"""Hire Order rows: from the quotation row of the same item, else the profile."""
	check_non_negative(doc)
	quoted = {}
	if doc.get("quotation"):
		for r in frappe.get_all("Quotation Item", filters={"parent": doc.quotation, "parenttype": "Quotation"},
				fields=["item_code", *FROM_QUOTATION], order_by="idx"):
			quoted.setdefault(r.item_code, quotation_row_charges(r))
	fill_new_rows(doc, "items", lambda row: quoted.get(row.item_code))
	fill_replacement_value(doc, "items", lambda row: None)


def hire_order_contract(doc, method=None):
	"""Hire Order Contract materials (the physical items): from its quotation when the quotation lists the
	item, else the profile. One item carries one set of charges on a contract."""
	check_non_negative(doc, "materials")
	quoted = {}
	if doc.get("quotation"):
		for r in frappe.get_all("Quotation Item", filters={"parent": doc.quotation, "parenttype": "Quotation"},
				fields=["item_code", *FROM_QUOTATION], order_by="idx"):
			quoted.setdefault(r.item_code, quotation_row_charges(r))
	fill_new_rows(doc, "materials", lambda row: quoted.get(row.item_code))
	first = {}
	for m in doc.get("materials") or []:
		values = tuple(flt(m.get(f)) for f in FIELDS)
		if m.item_code in first and first[m.item_code] != values:
			frappe.throw(_("Materials row #{0}: {1} has different damage and loss charges on another row. Use the same charges for one item on a contract.")
				.format(m.idx, frappe.bold(m.item_code)), title=_("Different charges"))
		first.setdefault(m.item_code, values)


def material_charges(contract):
	"""{item_code: charges} of a submitted Hire Order Contract's materials."""
	out = {}
	for m in frappe.get_all("Hire Order Contract Material", filters={"parent": contract, "parenttype": "Hire Order Contract"},
			fields=["item_code", *FIELDS], order_by="idx"):
		out.setdefault(m.item_code, {f: flt(m.get(f)) for f in FIELDS})
	return out


def rental_contract(doc, method=None):
	"""Rental Contract rows: from the Hire Order row or the Hire Order Contract material of the same item,
	else the profile (a contract entered by hand)."""
	check_non_negative(doc)
	source, replacement = {}, {}
	if doc.get("source_type") == "Hire Order" and doc.get("source_document"):
		for r in frappe.get_all("Hire Order Item", filters={"parent": doc.source_document, "parenttype": "Hire Order"},
				fields=["item_code", "replacement_value", *FIELDS], order_by="idx"):
			source.setdefault(r.item_code, {f: flt(r.get(f)) for f in FIELDS})
			replacement.setdefault(r.item_code, {"replacement_value": flt(r.replacement_value)})
	elif doc.get("source_type") == "Hire Order Contract" and doc.get("source_document"):
		source = material_charges(doc.source_document)
	fill_new_rows(doc, "items", lambda row: source.get(row.item_code))
	fill_replacement_value(doc, "items", lambda row: replacement.get(row.item_code))


# ----------------------------------------------------------------------------- settlement
def contract_rows(contract):
	"""{item_code: Rental Contract Item values} for the charges of a settlement."""
	if not contract:
		return {}
	rows = frappe.get_all("Rental Contract Item", filters={"parent": contract, "parenttype": "Rental Contract"},
		fields=["item_code", "replacement_value", *FIELDS], order_by="idx")
	return {r.item_code: r for r in rows}


def settlement_rate(contract, row, classification):
	"""(rate, source note) for a settlement row: the contract row's agreed charge for the classification;
	for Lost and Beyond Repair rows agreed before these charges existed (charge zero), the replacement
	value saved on the same contract row."""
	charge_field, fallback_field = SETTLEMENT[classification]
	if not row:
		return 0.0, _("No row for this item on Rental Contract {0}").format(contract)
	label = frappe.get_meta("Rental Contract Item").get_label
	if flt(row.get(charge_field)):
		return flt(row.get(charge_field)), _("{0}: {1}").format(contract, _(label(charge_field)))
	if fallback_field and flt(row.get(fallback_field)):
		return flt(row.get(fallback_field)), _("{0}: {1} (no {2} agreed)").format(contract, _(label(fallback_field)), _(label(charge_field)).lower())
	return 0.0, _("{0}: no {1} agreed").format(contract, _(label(charge_field)).lower())
