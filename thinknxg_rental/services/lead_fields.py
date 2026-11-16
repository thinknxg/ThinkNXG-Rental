import frappe
from frappe.utils import cint


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def customer_name_search(doctype, txt, searchfield, start, page_len, filters):
    """Link search for the Lead's Customer field: matches the customer name only."""
    return frappe.db.sql(
        """select name, customer_name from `tabCustomer`
        where disabled=0 and customer_name like %(txt)s
        order by customer_name limit %(start)s, %(page_len)s""",
        {"txt": f"%{txt}%", "start": cint(start), "page_len": cint(page_len)},
    )


@frappe.whitelist()
def get_customer_details(customer):
    """Organization, address and primary contact of an existing customer, for filling a Lead."""
    frappe.has_permission("Customer", "read", customer, throw=True)
    c = frappe.db.get_value("Customer", customer, ["customer_name", "territory", "website", "customer_primary_contact",
        "customer_primary_address", "email_id", "mobile_no"], as_dict=True)
    out = {"company_name": c.customer_name, "territory": c.territory, "website": c.website,
        "email_id": c.email_id, "mobile_no": c.mobile_no}
    if c.customer_primary_contact:
        k = frappe.db.get_value("Contact", c.customer_primary_contact, ["salutation", "first_name", "middle_name", "last_name",
            "designation", "email_id", "mobile_no", "phone"], as_dict=True)
        if k:
            out.update({"salutation": k.salutation, "first_name": k.first_name, "middle_name": k.middle_name,
                "last_name": k.last_name, "job_title": k.designation, "email_id": k.email_id or out["email_id"],
                "mobile_no": k.mobile_no or out["mobile_no"], "phone": k.phone})
    if c.customer_primary_address:
        a = frappe.db.get_value("Address", c.customer_primary_address, ["city", "state", "country"], as_dict=True)
        if a:
            out.update({"city": a.city, "state": a.state, "country": a.country})
    return {k: v for k, v in out.items() if v}
