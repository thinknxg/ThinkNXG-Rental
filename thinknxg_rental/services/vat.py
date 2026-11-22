"""UAE and Oman VAT for rental documents (pro forma invoices).

Each VAT country is its own engine: a Rental VAT Profile per company holds the country, its currency
(AED, 2 decimals / OMR, 3 decimals), the company's VAT registration number, the number series and a table
of treatment rules that finance reviews. Nothing here is tied to the customer's address alone: a rule is
picked by

* the charge category (rental, transport, loading, installation, ..., security deposit, advance payment),
* the supply: Domestic when the material is used in the profile's country (or, when the place of use is
  not known, the customer is in that country), otherwise Cross-Border,
* whether the customer is VAT registered (has a VAT registration number).

The most specific matching rule wins (an exact supply or registration beats Any; then the first row).
A category with no rule falls back to the standard rate, except Security Deposit, which is Out of Scope:
a refundable deposit is not consideration for the rental until it is applied. The treatment of a single
line can still be set by hand on the document; approving such a document needs an Accounts Manager.

The tax invoice itself is a Sales Invoice: its VAT is worked out again by the profile's Sales Taxes and
Charges Template and the Item Tax Template of each line's treatment, on the invoice date.
"""
import frappe
from frappe import _
from frappe.utils import flt

PROFILE = "Rental Company Profile"
STANDARD, ZERO, EXEMPT, OUT = "Standard", "Zero-Rated", "Exempt", "Out of Scope"
TREATMENTS = (STANDARD, ZERO, EXEMPT, OUT)
DOMESTIC, CROSS = "Domestic", "Cross-Border"
DEPOSIT, ADVANCE, RENTAL = "Security Deposit", "Advance Payment", "Rental"

# per VAT country: currency, decimals, label of the VAT number, number series
COUNTRIES = {
	"Oman": dict(currency="OMR", precision=3, label="VATIN", code="OM"),
	"United Arab Emirates": dict(currency="AED", precision=2, label="TRN", code="AE"),
}
STATEMENT = ("This is a preliminary commercial document issued for confirmation of rental requirements and estimated "
	"charges. This document is not a VAT Tax Invoice.")
# treatment -> profile field holding the Item Tax Template used on the tax invoice
ITEM_TAX_FIELD = {ZERO: "zero_rated_item_tax_template", EXEMPT: "exempt_item_tax_template", OUT: "out_of_scope_item_tax_template"}


def country_info(country):
	info = COUNTRIES.get(country)
	if not info:
		frappe.throw(_("VAT country {0} is not supported. Use Oman or United Arab Emirates.").format(country))
	return info


def precision_of(currency):
	"""Decimals of an amount in this currency: OMR 3, AED 2, anything else 2."""
	for info in COUNTRIES.values():
		if info["currency"] == currency:
			return info["precision"]
	return 2


def get_profile(company, throw=True):
	name = frappe.db.get_value(PROFILE, {"company": company, "disabled": 0}, "name")
	if not name:
		if throw:
			frappe.throw(_("Set up a Rental Company Profile for company {0} (Oman or United Arab Emirates) first.").format(company),
				title=_("No VAT Profile"))
		return None
	return frappe.get_cached_doc(PROFILE, name)


def supply_scope(profile_country, equipment_country=None, customer_country=None):
	"""Domestic when the material is used in the VAT country; with no place of use, when the customer is there."""
	place = equipment_country or customer_country
	if not place:
		return DOMESTIC
	return DOMESTIC if place == profile_country else CROSS


def resolve(profile, category, scope, registered):
	"""(treatment, rate, rule remarks) for one charge category."""
	best, best_score = None, -1
	status = "Registered" if registered else "Not Registered"
	for rule in profile.rules:
		if rule.charge_category != category:
			continue
		if (rule.supply_scope or "Any") not in ("Any", scope):
			continue
		if (rule.customer_vat_status or "Any") not in ("Any", status):
			continue
		score = (rule.supply_scope not in (None, "", "Any")) + (rule.customer_vat_status not in (None, "", "Any"))
		if score > best_score:
			best, best_score = rule, score
	if best:
		treatment = best.vat_treatment or STANDARD
		return treatment, rate_for(profile, treatment, best.vat_rate), best.remarks or ""
	if category == DEPOSIT:
		return OUT, 0.0, _("No rule: a refundable deposit is not charged VAT")
	return STANDARD, flt(profile.standard_vat_rate), _("No rule: standard rate")


def rate_for(profile, treatment, rate=None):
	if treatment != STANDARD:
		return 0.0
	return flt(rate) if flt(rate) > 0 else flt(profile.standard_vat_rate)


def item_tax_template(profile, treatment):
	field = ITEM_TAX_FIELD.get(treatment)
	return profile.get(field) if field else None


def is_reviewed(profile):
	return bool(profile.reviewed_by and profile.reviewed_on)


def default_rules(country):
	"""Starting rules for a new profile, to be reviewed by finance before use."""
	rows = [dict(charge_category=c, supply_scope="Any", customer_vat_status="Any", vat_treatment=STANDARD,
		remarks=_("Standard-rated supply in {0}").format(country)) for c in (
		RENTAL, "Transportation", "Loading", "Unloading", "Installation", "Dismantling", "Handling", "Damage and Loss", "Other Service", ADVANCE)]
	rows.append(dict(charge_category=DEPOSIT, supply_scope="Any", customer_vat_status="Any", vat_treatment=OUT,
		remarks=_("Refundable deposit: not consideration until applied")))
	return rows


def ensure_default_profile(company):
	"""A starting profile for a company registered in Oman or the UAE (not reviewed: finance reviews it)."""
	if not company or frappe.db.exists(PROFILE, {"company": company}):
		return None
	country = frappe.db.get_value("Company", company, "country")
	if country not in COUNTRIES:
		return None
	info = COUNTRIES[country]
	abbr = frappe.db.get_value("Company", company, "abbr") or info["code"]
	taxes = frappe.db.get_value("Sales Taxes and Charges Template", {"company": company, "is_default": 1, "disabled": 0}, "name")
	doc = frappe.get_doc({
		"doctype": PROFILE, "company": company, "country": country,
		"vat_registration_number": frappe.db.get_value("Company", company, "tax_id") or "-",
		"standard_vat_rate": 5, "proforma_naming_series": f"PI-{info['code']}-{abbr}-.YYYY.-.#####",
		"sales_taxes_template": taxes, "not_tax_invoice_statement": STATEMENT, "rules": default_rules(country),
	})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def validate_profile(doc):
	info = country_info(doc.country)
	company_country = frappe.db.get_value("Company", doc.company, "country")
	if company_country and company_country != doc.country:
		frappe.throw(_("Company {0} is registered in {1}; its VAT profile must be for {1}.").format(doc.company, company_country))
	doc.currency = info["currency"]
	company_currency = frappe.db.get_value("Company", doc.company, "default_currency")
	if company_currency and company_currency != doc.currency:
		frappe.throw(_("{0} VAT documents are in {1}, but company {2} keeps its books in {3}.").format(
			doc.country, doc.currency, doc.company, company_currency))
	doc.vat_registration_label = doc.vat_registration_label or info["label"]
	doc.not_tax_invoice_statement = doc.not_tax_invoice_statement or STATEMENT
	if not 0 < flt(doc.standard_vat_rate) <= 100:
		frappe.throw(_("Standard VAT Rate must be between 0 and 100"))
	if ".#" not in (doc.proforma_naming_series or ""):
		frappe.throw(_("Pro Forma Invoice Series needs a number part, e.g. PI-{0}-.YYYY.-.#####").format(info["code"]))
	other = frappe.db.get_value(PROFILE, {"proforma_naming_series": doc.proforma_naming_series, "name": ["!=", doc.name or ""]}, "name")
	if other:
		frappe.throw(_("Pro Forma Invoice Series {0} is already used by VAT profile {1}").format(doc.proforma_naming_series, other))
	if doc.tax_invoice_naming_series:
		options = (frappe.get_meta("Sales Invoice").get_field("naming_series").options or "").split("\n")
		if doc.tax_invoice_naming_series not in options:
			frappe.throw(_("Tax Invoice Series {0} is not a Sales Invoice series. Add it in Document Naming Settings first.").format(
				doc.tax_invoice_naming_series))
	for field in ("sales_taxes_template",):
		if doc.get(field) and frappe.db.get_value("Sales Taxes and Charges Template", doc.get(field), "company") != doc.company:
			frappe.throw(_("Sales Taxes and Charges Template {0} belongs to another company").format(doc.get(field)))
	for treatment, field in ITEM_TAX_FIELD.items():
		template = doc.get(field)
		if template and frappe.db.get_value("Item Tax Template", template, "company") != doc.company:
			frappe.throw(_("Item Tax Template {0} belongs to another company").format(template))
	for rule in doc.rules:
		if rule.vat_treatment != STANDARD:
			rule.vat_rate = 0
		elif flt(rule.vat_rate) < 0 or flt(rule.vat_rate) > 100:
			frappe.throw(_("Rule #{0}: VAT Rate must be between 0 and 100").format(rule.idx))
	# a change to the rules or rates needs a new finance review
	if not doc.is_new() and not doc.flags.reviewing and _rules_changed(doc):
		doc.reviewed_by = doc.reviewed_on = None


def _rules_changed(doc):
	old = doc.get_doc_before_save()
	if not old:
		return False
	key = lambda d: [(r.charge_category, r.supply_scope, r.customer_vat_status, r.vat_treatment, flt(r.vat_rate)) for r in d.rules]
	fields = ("country", "standard_vat_rate", "sales_taxes_template") + tuple(ITEM_TAX_FIELD.values())
	return key(old) != key(doc) or any(old.get(f) != doc.get(f) for f in fields)


def mark_reviewed(doc, note=None):
	if not frappe.get_roles() or not set(frappe.get_roles()) & {"Accounts Manager", "System Manager"}:
		frappe.throw(_("Only an Accounts Manager can mark the VAT rules reviewed"), frappe.PermissionError)
	doc.flags.reviewing = True
	doc.reviewed_by = frappe.session.user
	doc.reviewed_on = frappe.utils.now_datetime()
	if note is not None:
		doc.review_note = note
	doc.save()
	return doc


def advance_vat_included(profile, scope, registered, amount):
	"""VAT contained in an advance received (VAT is due when the advance is received, if standard-rated)."""
	treatment, rate, _remarks = resolve(profile, ADVANCE, scope, registered)
	if treatment != STANDARD or not flt(rate):
		return 0.0
	return flt(amount) * flt(rate) / (100.0 + flt(rate))


def check_currency(currency, expected):
	if currency and expected and currency != expected:
		frappe.throw(_("This document is in {0}; amounts in {1} cannot be mixed into it.").format(expected, currency))


def customer_context(customer, address=None):
	"""(country, VAT registration number) of a customer: its billing address country, its Tax ID."""
	country = None
	if not address:
		address = frappe.db.get_value("Customer", customer, "customer_primary_address")
	if not address:
		rows = frappe.get_all("Dynamic Link", filters={"link_doctype": "Customer", "link_name": customer, "parenttype": "Address"},
			pluck="parent", limit=1)
		address = rows[0] if rows else None
	if address:
		country = frappe.db.get_value("Address", address, "country")
	return country, frappe.db.get_value("Customer", customer, "tax_id")
