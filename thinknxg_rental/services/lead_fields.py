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
