import frappe
from frappe.utils import cint


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def customer_name_search(doctype, txt, searchfield, start, page_len, filters):
    """Link search for the Lead's Customer field: matches the customer name only."""
    return frappe.db.sql(
        """select name, customer_name from `tabCustomer`
        where disabled=0 and (customer_name like %(txt)s or name = %(exact)s)
        order by customer_name limit %(start)s, %(page_len)s""",
        {"txt": f"%{txt}%", "exact": txt, "start": cint(start), "page_len": max(cint(page_len), 100)},
    )


def _linked_primary(doctype, flag, customer):
    """Contact or Address linked to the customer: the one flagged primary, else the first one."""
    names = frappe.get_all("Dynamic Link", filters={"link_doctype": "Customer", "link_name": customer, "parenttype": doctype}, pluck="parent")
    if not names:
        return None
    flagged = frappe.get_all(doctype, filters={"name": ["in", names], flag: 1}, pluck="name", limit=1)
    return (flagged or sorted(names))[0]


@frappe.whitelist()
def get_customer_details(customer):
    """Organization, address and primary contact of an existing customer, for filling a Lead."""
    frappe.has_permission("Customer", "read", customer, throw=True)
    c = frappe.db.get_value("Customer", customer, ["customer_name", "territory", "website", "customer_primary_contact",
        "customer_primary_address", "email_id", "mobile_no"], as_dict=True)
    out = {"company_name": c.customer_name, "territory": c.territory, "website": c.website,
        "email_id": c.email_id, "mobile_no": c.mobile_no}
    contact = c.customer_primary_contact or _linked_primary("Contact", "is_primary_contact", customer)
    if contact:
        k = frappe.db.get_value("Contact", contact, ["salutation", "first_name", "middle_name", "last_name",
            "designation", "email_id", "mobile_no", "phone"], as_dict=True)
        if k:
            out.update({"salutation": k.salutation, "first_name": k.first_name, "middle_name": k.middle_name,
                "last_name": k.last_name, "job_title": k.designation, "email_id": k.email_id or out["email_id"],
                "mobile_no": k.mobile_no or out["mobile_no"], "phone": k.phone})
    address = c.customer_primary_address or _linked_primary("Address", "is_primary_address", customer)
    if address:
        a = frappe.db.get_value("Address", address, ["city", "state", "country"], as_dict=True)
        if a:
            out.update({"city": a.city, "state": a.state, "country": a.country})
    return {k: v for k, v in out.items() if v}
