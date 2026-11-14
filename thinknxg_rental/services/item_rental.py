"""Item, Rental Item Profile, Stock and Asset, kept apart but managed from the Item.

* Item master: the product. Rental Item Profile: its rental configuration and charges (one per Item,
  named by the Item). Stock: quantities in the Stock Ledger. Asset: each physical unit.
* The Item form carries a Rental section (only with Maintain Stock). Its profile panel is drawn by
  public/js/item_rental.js from the Rental Item Profile itself and sent with the Item as
  ``nxg_rental_profile``, which is not an Item field: the values live only in the profile, saved in the
  same transaction as the Item (Item.on_update), so either both are saved or neither is.
* Rental Classification "Stock + Asset" is a stock item whose every unit is identified: it switches on
  ERPNext's own serial numbers, so each unit is a Serial No of the Item and the Stock Ledger keeps
  quantities and units in step. It does not make the Item an ERPNext Fixed Asset: ERPNext refuses an
  Item that is both, and the same unit would be valued twice (inventory and fixed assets).
* Quotation rows take the profile's damage and loss charges as defaults (snapshots), see
  ``quotation_charges`` below.
"""
import frappe
from frappe import _
from frappe.utils import cint, flt

PROFILE = "Rental Item Profile"
STOCK, STOCK_ASSET = "Stock", "Stock + Asset"

# Quotation Item field -> Rental Item Profile field
CHARGES = {
	"nxg_repair_charge": "repair_charge",
	"nxg_lost_charge": "lost_charge",
	"nxg_beyond_repair_charge": "beyond_repair_charge",
}
# Profile fields the Item form may set (everything a user enters; never the link or fetched names)
SKIP = {"item", "item_name", "item_group", "stock_uom", "naming_series", "amended_from"}


# ----------------------------------------------------------------------------- profile values
def validate_profile_charges(doc):
	"""Money on a Rental Item Profile is never negative."""
	for df in doc.meta.fields:
		if df.fieldtype == "Currency" and flt(doc.get(df.fieldname)) < 0:
			frappe.throw(_("{0} cannot be negative").format(_(df.label)), title=_("Invalid amount"))


LAYOUT = ("Section Break", "Column Break")


def editable_profile_fields(with_layout=False):
	"""The profile fields a user fills in, in the profile's own order; with_layout keeps its section and
	column breaks so the Item form's panel looks like the Rental Item Profile form."""
	meta = frappe.get_meta(PROFILE)
	out = []
	for df in meta.fields:
		if df.fieldtype in LAYOUT:
			if with_layout:
				out.append(df)
			continue
		if df.fieldname in SKIP or df.read_only or df.hidden or df.fieldtype in ("Tab Break", "HTML", "Button", "Table", "Table MultiSelect"):
			continue
		out.append(df)
	return out


@frappe.whitelist()
def get_item_rental_profile(item_code: str | None = None):
	"""What the Item form's Rental panel needs: the profile's editable fields (from its DocType, so new
	profile fields appear without touching the Item), the profile's values, and what the user may do."""
	fields = [{"fieldname": df.fieldname, "label": _(df.label) if df.label else "", "fieldtype": df.fieldtype, "options": df.options,
		"description": _(df.description) if df.description else "", "default": df.default, "reqd": df.reqd,
		"non_negative": df.non_negative}
		for df in editable_profile_fields(with_layout=True)]
	values, exists = {}, False
	if item_code and frappe.db.exists(PROFILE, item_code):
		profile = frappe.get_doc(PROFILE, item_code)
		if profile.has_permission("read"):
			exists = True
			values = {f["fieldname"]: profile.get(f["fieldname"]) for f in fields if f["fieldtype"] not in LAYOUT}
	return {
		"fields": fields,
		"values": values,
		"exists": exists,
		"enabled": exists and not cint(values.get("disabled")),
		"can_create": frappe.has_permission(PROFILE, "create"),
		"can_write": frappe.has_permission(PROFILE, "write", doc=item_code) if exists else frappe.has_permission(PROFILE, "create"),
	}


# ----------------------------------------------------------------------------- Item events
def item_before_validate(doc, method=None):
	"""Before ERPNext's own Item validation, so its rules (serial numbers, stock transactions) judge the
	values the classification leads to."""
	sync_classification(doc)


def item_validate(doc, method=None):
	if doc.get("nxg_rental_classification") == STOCK_ASSET and not cint(frappe.db.get_single_value("Stock Settings", "enable_serial_and_batch_no_for_item")):
		frappe.throw(_("Stock + Asset identifies every unit by its serial number. Switch on Activate Serial / Batch No for Item in Stock Settings first."),
			title=_("Serial numbers are off"))
	payload = _payload(doc)
	if payload is not None and cint(payload.get("enabled")) and not cint(doc.is_stock_item):
		frappe.throw(_("A Rental Item Profile needs Maintain Stock. Tick Maintain Stock or switch the Rental Item Profile off."),
			title=_("Maintain Stock required"))
	if not cint(doc.is_stock_item) and not doc.is_new():
		active = frappe.db.get_value(PROFILE, {"item": doc.name, "disabled": 0})
		switching_off = payload is not None and not cint(payload.get("enabled"))
		if active and not switching_off:
			frappe.throw(_("{0} has an active Rental Item Profile, which needs Maintain Stock. Switch the Rental Item Profile off first.").format(doc.name),
				title=_("Maintain Stock required"))


def sync_classification(doc):
	"""Rental Classification and ERPNext's Has Serial No say the same thing: Stock + Asset is a stock
	item with serial numbers. Whichever the user changed, the other follows. Turning serial numbers off
	after units exist is refused by ERPNext itself (existing Serial and Batch Bundles)."""
	if not doc.meta.has_field("nxg_rental_classification"):
		return
	if not cint(doc.is_stock_item):
		doc.nxg_rental_classification = STOCK
		return
	before = doc.get_doc_before_save()
	class_changed = before is None or before.get("nxg_rental_classification") != doc.nxg_rental_classification
	serial_changed = before is not None and cint(before.has_serial_no) != cint(doc.has_serial_no)
	if serial_changed and not class_changed:
		doc.nxg_rental_classification = STOCK_ASSET if cint(doc.has_serial_no) else STOCK
	elif doc.nxg_rental_classification == STOCK_ASSET:
		doc.has_serial_no = 1
	elif class_changed and before is not None and doc.nxg_rental_classification == STOCK:
		doc.has_serial_no = 0
	elif cint(doc.has_serial_no):
		doc.nxg_rental_classification = STOCK_ASSET
	else:
		doc.nxg_rental_classification = doc.nxg_rental_classification or STOCK


def item_on_update(doc, method=None):
	"""Save the Rental Item Profile sent with the Item, in the Item's transaction, with the user's own
	permissions on Rental Item Profile."""
	payload = _payload(doc)
	if payload is None:
		return
	enabled = cint(payload.get("enabled"))
	values = payload.get("values") or {}
	exists = frappe.db.exists(PROFILE, doc.name)
	if not enabled and not exists:
		return
	profile = frappe.get_doc(PROFILE, doc.name) if exists else frappe.new_doc(PROFILE)
	if not exists:
		profile.item = doc.name
	allowed = {df.fieldname for df in editable_profile_fields()}
	for field, value in values.items():
		if field in allowed:
			profile.set(field, value)
	profile.disabled = 0 if enabled else 1
	profile.item_name = doc.item_name
	profile.item_group = doc.item_group
	profile.stock_uom = doc.stock_uom
	if exists:
		profile.save()  # checks write permission
	else:
		profile.insert()  # checks create permission
	doc.flags.nxg_rental_profile_saved = profile.name


def _payload(doc):
	raw = doc.get("nxg_rental_profile")
	if raw in (None, ""):
		return None
	return frappe.parse_json(raw) if isinstance(raw, str) else raw


# ----------------------------------------------------------------------------- quotation charges
@frappe.whitelist()
def get_item_rental_charges(item_code: str, company: str | None = None, currency: str | None = None, conversion_rate: float | None = None):
	"""The profile's damage and loss charges for an item, as the defaults of a quotation row, in the
	quotation's currency. Zero when the item has no Rental Item Profile."""
	frappe.has_permission("Item", "read", doc=item_code, throw=True)
	out = {k: 0.0 for k in CHARGES}
	out["has_profile"] = 0
	if not item_code or not frappe.db.exists(PROFILE, {"name": item_code, "disabled": 0}):
		return out
	values = frappe.db.get_value(PROFILE, item_code, list(CHARGES.values()), as_dict=True)
	rate = _rate_to_document(company, currency, conversion_rate)
	for row_field, profile_field in CHARGES.items():
		out[row_field] = flt(flt(values.get(profile_field)) / rate, frappe.get_precision("Quotation Item", row_field) or 2)
	out["has_profile"] = 1
	return out


def _rate_to_document(company, currency, conversion_rate):
	"""Profile charges are in company currency; a quotation in another currency gets them divided by its
	exchange rate (company currency per unit of the quotation's currency)."""
	company_currency = frappe.get_cached_value("Company", company, "default_currency") if company else None
	if currency and company_currency and currency != company_currency and flt(conversion_rate) > 0:
		return flt(conversion_rate)
	return 1.0


def quotation_item_selected(doc, method=None, item_idx=None, reset_item_details=False, parentfield="items", **kwargs):
	"""Quotation.process_item_selection (ERPNext v16 runs item selection on the server and sends the row
	back to the form): when an item is picked, its row takes the profile's charges as defaults."""
	if doc.doctype != "Quotation" or parentfield != "items" or not cint(reset_item_details):
		return
	row = doc.get_selected_item_row(parentfield, item_idx)
	if not row or not row.item_code or not row.meta.has_field("nxg_repair_charge"):
		return
	defaults = get_item_rental_charges(row.item_code, doc.company, doc.currency, doc.conversion_rate)
	for field in CHARGES:
		row.set(field, defaults[field])
	row.nxg_charges_set = 1


def quotation_charges(doc, method=None):
	"""Quotation (validate): rows added without the form (API, mappings, the portal before it fetched)
	get the profile's charges once. A row whose charges were set (fetched, typed or saved before) keeps
	them: the row is a snapshot and never follows later profile changes. Negative charges are refused."""
	if not doc.meta.get_field("items") or not frappe.get_meta("Quotation Item").has_field("nxg_repair_charge"):
		return
	before = doc.get_doc_before_save()
	previous = {r.name for r in (before.get("items") or [])} if before else set()
	for row in doc.get("items"):
		for field in CHARGES:
			if flt(row.get(field)) < 0:
				frappe.throw(_("Row #{0}: {1} cannot be negative").format(row.idx, _(row.meta.get_label(field))), title=_("Invalid amount"))
		if cint(row.get("nxg_charges_set")) or row.name in previous or not row.item_code:
			continue
		if any(flt(row.get(f)) for f in CHARGES):
			row.nxg_charges_set = 1  # typed in before any fetch: keep
			continue
		defaults = get_item_rental_charges(row.item_code, doc.company, doc.currency, doc.conversion_rate)
		for field in CHARGES:
			row.set(field, defaults[field])
		row.nxg_charges_set = 1


# ----------------------------------------------------------------------------- individual units (Stock + Asset)
def is_unit_tracked(item_code):
	return bool(frappe.get_cached_value("Item", item_code, "has_serial_no"))


def units(item_code):
	"""Every unit (Serial No) of a Stock + Asset item, where it is now: the yard, a customer's site,
	repair, inspection or scrap, read from the Serial No and the rental warehouses."""
	from thinknxg_rental.services.utils import get_settings

	s = get_settings()
	places = {s.rental_yard_warehouse: _("Yard"), s.get("inspection_warehouse"): _("Inspection"),
		s.get("repair_warehouse"): _("Repair"), s.get("scrap_warehouse"): _("Scrap")}
	sites = dict(frappe.get_all("Rental Site", fields=["site_warehouse", "name"], filters={"site_warehouse": ["is", "set"]}, as_list=True))
	rows = frappe.get_all("Serial No", filters={"item_code": item_code},
		fields=["name", "status", "warehouse", "customer", "purchase_rate", "warranty_expiry_date", "maintenance_status", "creation"],
		order_by="name asc", limit=2000)
	for r in rows:
		if r.warehouse in sites:
			r.place, r.site = _("At site"), sites[r.warehouse]
		else:
			r.place, r.site = places.get(r.warehouse) or (r.warehouse or _(r.status or "")), None
	return rows


def unit_history(item_code, serial_no):
	"""One unit's life: each stock movement it was part of (the Serial and Batch Bundles behind them),
	and each return inspection that graded it."""
	moves = frappe.db.sql(
		"""
		select b.posting_datetime, b.warehouse, e.qty, b.voucher_type, b.voucher_no, b.type_of_transaction
		from `tabSerial and Batch Entry` e
		join `tabSerial and Batch Bundle` b on b.name = e.parent
		where e.serial_no = %(serial)s and b.item_code = %(item)s and b.docstatus = 1 and b.is_cancelled = 0
		order by b.posting_datetime desc, b.creation desc
		limit 200
		""",
		{"serial": serial_no, "item": item_code},
		as_dict=True,
	)
	origin = {}
	vouchers = [m.voucher_no for m in moves if m.voucher_type == "Stock Entry"]
	if vouchers:
		for se in frappe.get_all("Stock Entry", filters={"name": ["in", vouchers]}, fields=["name", "nxg_hire_voucher_type", "nxg_hire_voucher_no"]):
			origin[se.name] = (se.nxg_hire_voucher_type, se.nxg_hire_voucher_no)
	for m in moves:
		src = origin.get(m.voucher_no)
		m.source_doctype, m.source_name = src if src and src[1] else (m.voucher_type, m.voucher_no)
	grades = []
	like = f"%{serial_no}%"
	for field, grade in (("good_serial_no", "Good"), ("repairable_serial_no", "Repairable"), ("damaged_serial_no", "Beyond repair")):
		for r in frappe.db.sql(
			f"""select i.parent, p.inspection_date as posting_date, i.{field} as serials from `tabRental Return Inspection Item` i
			join `tabRental Return Inspection` p on p.name = i.parent
			where i.item_code = %s and i.{field} like %s and p.docstatus = 1""", (item_code, like), as_dict=True):
			if serial_no in (r.serials or "").split():
				grades.append({"inspection": r.parent, "posting_date": r.posting_date, "grade": _(grade)})
	grades.sort(key=lambda g: str(g["posting_date"]), reverse=True)
	return {"moves": moves, "inspections": grades}
