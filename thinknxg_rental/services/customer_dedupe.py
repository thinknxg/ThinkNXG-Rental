"""Duplicate Customer check (same name or same Tax ID as another Customer).

* The Customer form asks "Create anyway?" (Yes / No) before saving: see public/js/customer_dedupe.js
* Other ways of creating a Customer (Lead / Quotation conversions, quick entry) only show a warning.
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


def find_duplicates(customer_name, tax_id, name=None):
    messages = []
    key = normalise(customer_name)
    if key:
        word = max(key.split(), key=len)
        rows = frappe.get_all("Customer", filters={"customer_name": ["like", "%" + word + "%"], "name": ["!=", name or ""]},
                fields=["name", "customer_name"], limit_page_length=0)
        same = [r.name for r in rows if normalise(r.customer_name) == key]
        if same:
            messages.append(_("A Customer with the same name already exists: {0}.").format(_links(same)))

    tax_id = (tax_id or "").strip()
    if tax_id:
        others = frappe.get_all("Customer", filters={"tax_id": tax_id, "name": ["!=", name or ""]}, pluck="name", limit_page_length=5)
        if others:
            messages.append(_("Tax ID {0} is also used by {1}.").format(tax_id, _links(others)))
    return messages


@frappe.whitelist()
def check_duplicate_customer(customer_name=None, tax_id=None, name=None):
    frappe.has_permission("Customer", "read", throw=True)
    return find_duplicates(customer_name, tax_id, name)


def validate_customer(doc, method=None):
    flags = frappe.flags
    if flags.allow_duplicate_customer or flags.in_install or flags.in_patch or flags.in_import:
        return
    # the Customer form has already asked the user (Yes / No) before this save
    if frappe.form_dict.get("cmd") == "frappe.desk.form.save.savedocs":
        return
    if not (doc.is_new() or doc.has_value_changed("customer_name") or doc.has_value_changed("tax_id")):
        return
    messages = find_duplicates(doc.customer_name, doc.tax_id, doc.name)
    if messages:
        frappe.msgprint("<br><br>".join(messages), title=_("Possible duplicate Customer"), indicator="orange")
