"""Item, Rental Item Profile, Stock and Asset, kept apart but managed from the Item.

* Item master: the product. Rental Item Profile: its rental configuration and charges (one per Item,
  named by the Item). Stock: quantities in the Stock Ledger. Asset: each physical unit.
* The Item form carries a Rental section (only with Maintain Stock). Its profile panel is drawn by
  public/js/item_rental.js from the Rental Item Profile itself and sent with the Item as
  ``nxg_rental_profile``, which is not an Item field: the values live only in the profile, saved in the
  same transaction as the Item (Item.on_update), so either both are saved or neither is.
* Quotation rows take the profile's damage and loss charges as defaults (snapshots), see
  ``quotation_charges`` below.
"""
import frappe
from frappe import _
from frappe.utils import cint, flt

PROFILE = "Rental Item Profile"

# Quotation Item field -> Rental Item Profile field
CHARGES = {
	"nxg_repair_charge": "repair_charge",
	"nxg_lost_charge": "lost_charge",
	"nxg_beyond_repair_charge": "beyond_repair_charge",
}
# Quotation Item rate field -> rate basis (Material Hire rows)
RATES = {"Daily": "nxg_daily_rate", "Weekly": "nxg_weekly_rate", "Monthly": "nxg_monthly_rate"}
BASES = ("Monthly", "Weekly", "Daily")
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
		if df.fieldname == "sb_website":
			break  # the public website content is edited on the Rental Item Profile form itself
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
def item_validate(doc, method=None):
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


@frappe.whitelist()
def get_item_rental_defaults(item_code: str, company: str | None = None, currency: str | None = None,
		conversion_rate: float | None = None, customer: str | None = None, transaction_date: str | None = None,
		rate_basis: str | None = None, quotation_to: str | None = None, deal_type: str | None = None):
	"""Everything a Material Hire quotation row takes from the item when it is picked: the damage and
	loss charges, the daily, weekly and monthly rates (customer rate card, then general rate card, then
	the Rental Item Profile, as for hire orders), the profile's default rate basis and the Rate for it.
	All in the quotation's currency. An item without a profile gets zero rates and keeps rate_basis."""
	from thinknxg_rental.services.utils import get_profile, get_rental_rate

	out = get_item_rental_charges(item_code, company, currency, conversion_rate)
	if deal_type and deal_type != "Material Hire":
		return out  # rates per basis are for material hire; other deals keep their own pricing
	if quotation_to and quotation_to != "Customer":
		customer = None  # a Lead or Prospect has no customer rate card yet
	to_doc = _rate_to_document(company, currency, conversion_rate)
	for basis, field in RATES.items():
		out[field] = flt(get_rental_rate(item_code, basis, customer, transaction_date) / to_doc,
			frappe.get_precision("Quotation Item", field) or 2)
	profile_basis = get_profile(item_code).get("default_rate_basis") if out["has_profile"] else None
	basis = profile_basis if profile_basis in RATES else (rate_basis if rate_basis in RATES else "Monthly")
	out["nxg_rate_basis"] = basis
	if out[RATES[basis]]:
		out["rate"] = out[RATES[basis]]
	return out


def quotation_customer(doc):
	"""The customer whose rate card applies: the party when the quotation is to a Customer."""
	return doc.party_name if doc.get("quotation_to") == "Customer" else None


def _apply_rates(doc, row, defaults):
	for field in RATES.values():
		row.set(field, defaults[field])
	row.nxg_rate_basis = defaults["nxg_rate_basis"]
	if defaults.get("rate"):
		row.rate = defaults["rate"]


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
	hire = doc.get("deal_type") == "Material Hire" and row.meta.has_field("nxg_daily_rate")
	defaults = (get_item_rental_defaults(row.item_code, doc.company, doc.currency, doc.conversion_rate, quotation_customer(doc),
		doc.transaction_date, row.get("nxg_rate_basis") or doc.get("nxg_default_rate_basis")) if hire
		else get_item_rental_charges(row.item_code, doc.company, doc.currency, doc.conversion_rate))
	for field in CHARGES:
		row.set(field, defaults[field])
	row.nxg_charges_set = 1
	if hire:
		_apply_rates(doc, row, defaults)
		doc.calculate_taxes_and_totals()


def quotation_rates(doc, method=None):
	"""Quotation (validate, before the hire amounts are worked out), Material Hire rows:

	* a row added without the form gets the item's rates and rate basis once (as when picked);
	* the row's Rate follows its rate basis: changing the basis takes that basis's rate, changing a
	  basis rate moves Rate when it is the row's basis, and a Rate typed by hand is kept as that
	  basis's rate. All of them stay editable; nothing is written back to the profile or rate card."""
	if doc.get("deal_type") != "Material Hire" or not frappe.get_meta("Quotation Item").has_field("nxg_daily_rate"):
		return
	before = doc.get_doc_before_save()
	previous = {r.name: r for r in (before.get("items") or [])} if before else {}
	for row in doc.get("items"):
		if not row.item_code:
			continue
		for field in RATES.values():
			if flt(row.get(field)) < 0:
				frappe.throw(_("Row #{0}: {1} cannot be negative").format(row.idx, _(row.meta.get_label(field))), title=_("Invalid amount"))
		old = previous.get(row.name)
		if old is None and not cint(row.get("nxg_charges_set")) and not any(flt(row.get(f)) for f in RATES.values()):
			defaults = get_item_rental_defaults(row.item_code, doc.company, doc.currency, doc.conversion_rate, quotation_customer(doc),
				doc.transaction_date, row.get("nxg_rate_basis") or doc.get("nxg_default_rate_basis"))
			if not flt(row.rate):
				_apply_rates(doc, row, defaults)
			else:  # a Rate given with the row stays; the basis rates are filled around it
				for field in RATES.values():
					row.set(field, defaults[field])
				row.set(RATES.get(row.nxg_rate_basis or "Monthly", "nxg_monthly_rate"), row.rate)
			continue
		basis_field = RATES.get(row.get("nxg_rate_basis") or "Monthly")
		if old is not None and old.get("nxg_rate_basis") != row.get("nxg_rate_basis"):
			if flt(row.get(basis_field)):
				row.rate = row.get(basis_field)  # basis switched: its rate
		elif old is not None and flt(old.get(basis_field)) != flt(row.get(basis_field)) and flt(old.rate) == flt(row.rate):
			row.rate = row.get(basis_field)  # the basis rate was edited
		elif flt(row.rate) and flt(row.rate) != flt(row.get(basis_field)):
			row.set(basis_field, row.rate)  # Rate typed: it is this basis's rate


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
