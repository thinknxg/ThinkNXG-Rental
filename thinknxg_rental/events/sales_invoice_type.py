import frappe
from frappe import _

# Set to False to allow submitting an invoice with no Invoice Type (its print then shows a plain "TAX INVOICE").
REQUIRE_ON_SUBMIT = True


def _quotation_deal_type(doc):
    """Sales Invoice -> Sales Order (directly, or through the Delivery Note) -> Quotation.deal_type"""
    for row in doc.get("items") or []:
        so = row.get("sales_order")
        if not so and row.get("dn_detail"):
            so = frappe.db.get_value("Delivery Note Item", row.dn_detail, "against_sales_order")
        if not so:
            continue
        if frappe.get_meta("Sales Order").has_field("deal_type"):
            deal_type = frappe.db.get_value("Sales Order", so, "deal_type")
            if deal_type:
                return deal_type
        quotation = frappe.db.get_value("Sales Order Item", {"parent": so, "prevdoc_docname": ["!=", ""]}, "prevdoc_docname")
        if quotation:
            deal_type = frappe.db.get_value("Quotation", quotation, "deal_type")
            if deal_type:
                return deal_type
    return None


def get_deal_type(doc):
    if doc.get("return_against"):
        deal_type = frappe.db.get_value("Sales Invoice", doc.return_against, "deal_type")
        if deal_type:
            return deal_type
    deal_type = _quotation_deal_type(doc)
    if deal_type:
        return deal_type
    if doc.get("nxg_rental_contract"):
        return "Material Hire"  # Rental Contracts come from Hire Orders, which come from Material Hire quotations
    return None


def autofill(doc, method=None):
    if not doc.get("deal_type"):
        deal_type = get_deal_type(doc)
        if deal_type:
            doc.deal_type = deal_type


def require_on_submit(doc, method=None):
    if REQUIRE_ON_SUBMIT and not doc.get("deal_type"):
        frappe.throw(_("Please select the Invoice Type (Material Hire, Material Sale or Hire Order Contract) before submitting."))


def backfill():
    """One-off: fill the type on existing invoices where it can be worked out.
    Run with: bench --site <site> execute thinknxg_rental.events.sales_invoice_type.backfill"""
    rows = frappe.get_all("Sales Invoice", fields=["name", "deal_type"])
    todo = [r.name for r in rows if not r.deal_type]
    done = 0
    for name in todo:
        deal_type = get_deal_type(frappe.get_doc("Sales Invoice", name))
        if deal_type:
            frappe.db.set_value("Sales Invoice", name, "deal_type", deal_type, update_modified=False)
            done += 1
    frappe.db.commit()
    print(f"{done} of {len(todo)} invoices without a type were filled")


def backfill_sales_orders():
    """One-off: fill Deal Type on existing Sales Orders from their Quotation.
    Run with: bench --site <site> execute thinknxg_rental.events.sales_invoice_type.backfill_sales_orders"""
    done = 0
    for so in frappe.get_all("Sales Order", fields=["name", "deal_type"]):
        if so.deal_type:
            continue
        quotation = frappe.db.get_value("Sales Order Item", {"parent": so.name, "prevdoc_docname": ["!=", ""]}, "prevdoc_docname")
        deal_type = frappe.db.get_value("Quotation", quotation, "deal_type") if quotation else None
        if deal_type:
            frappe.db.set_value("Sales Order", so.name, "deal_type", deal_type, update_modified=False)
            done += 1
    frappe.db.commit()
    print(f"{done} sales orders filled")
