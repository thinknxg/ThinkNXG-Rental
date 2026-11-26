"""Warns when a Customer is saved with the same name or Tax ID as an existing Customer.

ERPNext names Customers by series (CUST-.YYYY.-), so two Customers with the same customer_name are
allowed, and the conversions (Lead, Prospect, Quotation) never look for an existing one. This runs on
Customer validate, for every way a Customer is created or renamed. It only shows a message and never
blocks the save:

* same name (ignoring case, spaces and punctuation) as another Customer;
* same Tax ID as another Customer (group companies can share one, so this is only a hint).

Imports and scripts that load duplicates on purpose set frappe.flags.allow_duplicate_customer = True.
"""
import re

import frappe
from frappe import _
from frappe.utils import get_link_to_form


def normalise(name):
    text = re.sub(r"\.", "", (name or "").lower())
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _links(names):
    return ", ".join(get_link_to_form("Customer", n) for n in names)


def validate_customer(doc, method=None):
    flags = frappe.flags
    if flags.allow_duplicate_customer or flags.in_install or flags.in_patch or flags.in_import:
        return
    if not (doc.is_new() or doc.has_value_changed("customer_name") or doc.has_value_changed("tax_id")):
        return

    messages = []
    key = normalise(doc.customer_name)
    if key:
        word = max(key.split(), key=len)
        rows = frappe.get_all("Customer", filters={"customer_name": ["like", "%" + word + "%"], "name": ["!=", doc.name or ""]},
                fields=["name", "customer_name"], limit_page_length=0)
        same = [r.name for r in rows if normalise(r.customer_name) == key]
        if same:
            messages.append(_("A Customer with the same name already exists: {0}. If this is the same company, use the existing Customer and merge this one into it.").format(_links(same)))

    tax_id = (doc.tax_id or "").strip()
    if tax_id:
        others = frappe.get_all("Customer", filters={"tax_id": tax_id, "name": ["!=", doc.name or ""]}, pluck="name", limit_page_length=5)
        if others:
            messages.append(_("Tax ID {0} is also used by {1}. Check that this is not the same company.").format(tax_id, _links(others)))

    if messages:
        frappe.msgprint("<br><br>".join(messages), title=_("Possible duplicate Customer"), indicator="orange")
