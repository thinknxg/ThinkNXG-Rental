"""Whitelisted endpoints used by the customer portal pages."""
import json

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from thinknxg_rental.portal.utils import get_portal_customers
from thinknxg_rental.services import ledger

REQUEST_TYPES = ("Hire Enquiry", "Off-Hire Request", "Extension Request")


def _customers(customer=None):
	customers, _preview = get_portal_customers(customer)
	if not customers:
		frappe.throw(_("Your login is not linked to a customer account."), frappe.PermissionError)
	return customers


def _contract(rental_contract, customers):
	doc = frappe.db.get_value(
		"Rental Contract", rental_contract,
		["name", "customer", "company", "docstatus", "status", "end_date", "rental_site"], as_dict=True,
	)
	if not doc or doc.docstatus != 1 or doc.customer not in customers:
		frappe.throw(_("Contract not found"), frappe.PermissionError)
	return doc


@frappe.whitelist()
def get_contract_items(rental_contract: str, customer: str | None = None):
	"""Items currently at site on one of the caller's contracts."""
	contract = _contract(rental_contract, _customers(customer))
	totals = {}
	for (item_code, _ownership, _cho), qty in ledger.get_site_balance(rental_contract).items():
		totals[item_code] = totals.get(item_code, 0) + flt(qty)
	items = []
	for item_code, qty in sorted(totals.items()):
		if qty <= 0:
			continue
		item = frappe.get_cached_value("Item", item_code, ["item_name", "stock_uom"], as_dict=True)
		items.append({"item_code": item_code, "item_name": item.item_name, "uom": item.stock_uom, "at_site_qty": qty})
	return {"end_date": contract.end_date, "rental_site": contract.rental_site, "items": items}


@frappe.whitelist()
def get_catalogue(customer: str | None = None):
	"""Rentable items a customer can ask for."""
	_customers(customer)
	show_rates = cint(frappe.get_cached_doc("Rental Settings").portal_show_rates)
	fields = ["item", "item_name", "category", "stock_uom"]
	if show_rates:
		fields += ["monthly_rate", "weekly_rate", "daily_rate"]
	rows = frappe.get_all("Rental Item Profile", filters={"disabled": 0}, fields=fields, order_by="category asc, item_name asc")
	for r in rows:
		r.item_code, r.uom = r.pop("item"), r.pop("stock_uom")
	return rows


@frappe.whitelist(methods=["POST"])
def create_request(request_type: str, rental_contract: str | None = None, required_date: str | None = None,
		expected_return_date: str | None = None, new_end_date: str | None = None, site_location: str | None = None,
		remarks: str | None = None, items: str | list | None = None, customer: str | None = None):
	if not cint(frappe.get_cached_doc("Rental Settings").portal_allow_requests):
		frappe.throw(_("Online requests are currently switched off. Please contact us directly."))
	if request_type not in REQUEST_TYPES:
		frappe.throw(_("Unknown request type"))
	customers = _customers(customer)
	if isinstance(items, str):
		items = json.loads(items or "[]")
	items = [i for i in (items or []) if i.get("item_code") and flt(i.get("qty")) > 0]

	doc = frappe.new_doc("Rental Portal Request")
	doc.update(
		{
			"request_type": request_type,
			"customer": customers[0],
			"raised_by": frappe.session.user,
			"request_date": nowdate(),
			"required_date": required_date or None,
			"remarks": (remarks or "").strip()[:2000],
		}
	)
	if request_type == "Hire Enquiry":
		if not items:
			frappe.throw(_("Add at least one item and quantity"))
		if not required_date:
			frappe.throw(_("Tell us when you need the material"))
		if expected_return_date and getdate(expected_return_date) < getdate(required_date):
			frappe.throw(_("The expected return date cannot be before the start date"))
		rentable = set(frappe.get_all("Rental Item Profile", filters={"disabled": 0}, pluck="item"))
		for i in items:
			if i["item_code"] not in rentable:
				frappe.throw(_("{0} is not available for hire").format(i["item_code"]))
		doc.expected_return_date = expected_return_date or None
		doc.site_location = (site_location or "").strip()[:140]
		doc.company = frappe.get_cached_doc("Rental Settings").company
	else:
		if not rental_contract:
			frappe.throw(_("Choose a contract"))
		contract = _contract(rental_contract, customers)
		if contract.status in ("Completed", "Cancelled"):
			frappe.throw(_("Contract {0} is closed").format(rental_contract))
		doc.update({"rental_contract": contract.name, "customer": contract.customer, "company": contract.company})
		if request_type == "Extension Request":
			if not new_end_date or getdate(new_end_date) <= getdate(contract.end_date):
				frappe.throw(_("The new end date must be after the current end date {0}").format(frappe.format_value(contract.end_date, {"fieldtype": "Date"})))
			doc.new_end_date = new_end_date
			items = []
		else:
			if not items:
				frappe.throw(_("Enter the quantity you want collected for at least one item"))
			at_site = {i["item_code"]: i["at_site_qty"] for i in get_contract_items(rental_contract, contract.customer)["items"]}
			for i in items:
				if flt(i["qty"]) > flt(at_site.get(i["item_code"])) + 1e-6:
					frappe.throw(
						_("{0}: you asked to return {1} but {2} is at site").format(i["item_code"], flt(i["qty"]), flt(at_site.get(i["item_code"])))
					)
	seen = set()
	for i in items:
		if i["item_code"] in seen:
			frappe.throw(_("{0} is listed twice").format(i["item_code"]))
		seen.add(i["item_code"])
		doc.append("items", {"item_code": i["item_code"], "qty": flt(i["qty"])})
	doc.flags.ignore_permissions = True
	doc.insert()
	return {"name": doc.name}


@frappe.whitelist(methods=["POST"])
def cancel_request(name: str, customer: str | None = None):
	customers = _customers(customer)
	doc = frappe.get_doc("Rental Portal Request", name)
	if doc.customer not in customers:
		frappe.throw(_("Request not found"), frappe.PermissionError)
	if doc.status != "Open":
		frappe.throw(_("This request is already being handled. Please contact us to change it."))
	doc.db_set("status", "Cancelled")
	return {"name": doc.name}
