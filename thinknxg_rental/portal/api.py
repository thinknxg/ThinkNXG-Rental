"""Endpoints of the first customer portal, kept so links and scripts written against them keep working.
They delegate to portal/customer.py, which holds the checks for the customer Command Center."""
import json

import frappe

from thinknxg_rental.portal import customer as cp
from thinknxg_rental.thinknxg_rental.doctype.rental_portal_request.rental_portal_request import REQUEST_TYPES  # noqa: F401


@frappe.whitelist()
def get_contract_items(rental_contract: str, customer: str | None = None):
	"""Items currently at site on one of the caller's contracts."""
	data = cp.request_options(customer=customer, contract=rental_contract)
	contract = next(c for c in data["contracts"] if c.name == rental_contract)
	return {"end_date": contract.end_date, "rental_site": contract.rental_site, "items": data["site_items"]}


@frappe.whitelist()
def get_catalogue(customer: str | None = None):
	"""Rentable items a customer can ask for."""
	return cp.request_options(customer=customer)["catalogue"]


@frappe.whitelist(methods=["POST"])
def create_request(request_type: str, rental_contract: str | None = None, required_date: str | None = None,
		expected_return_date: str | None = None, new_end_date: str | None = None, site_location: str | None = None,
		remarks: str | None = None, items: str | list | None = None, customer: str | None = None):
	if isinstance(items, str):
		items = json.loads(items or "[]")
	data = {"request_type": request_type, "rental_contract": rental_contract, "required_date": required_date,
		"expected_return_date": expected_return_date, "new_end_date": new_end_date, "site_location": site_location,
		"remarks": remarks, "items": items or []}
	return {"name": cp.submit_request(data, customer)["name"]}


@frappe.whitelist(methods=["POST"])
def cancel_request(name: str, customer: str | None = None):
	return cp.cancel_request(name, customer)
