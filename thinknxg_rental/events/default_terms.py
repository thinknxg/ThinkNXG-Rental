"""Default Terms and Conditions by Deal Type.

On save of a draft, if the terms are empty (or still an unedited template for a different Deal Type),
fill in the template that belongs to the document's Deal Type. Terms the user typed or a template
they chose themselves are never replaced. Add an entry to TEMPLATES to cover a new case; a template
that does not exist yet is skipped, so documents without one print as before.
"""
import frappe

TEMPLATES = {
    "Quotation": {
        "Material Hire": "Material Hire - Quotation",
        "Material Sale": "Material Sale - Quotation",
        "Hire Order Contract": "Hire Order Contract - Quotation",
    },
    "Hire Order Contract": {
        "Hire Order Contract": "Hire Order Contract - Quotation",
    },
    "Sales Invoice": {
        "Material Hire": "Material Hire - Invoice",
        "Material Sale": "Material Sale - Invoice",
        "Hire Order Contract": "Hire Order Contract - Invoice",
    },
}


def _deal_type(doc):
    if doc.doctype == "Hire Order Contract":
        return "Hire Order Contract"
    deal_type = doc.get("deal_type")
    if not deal_type and doc.doctype == "Sales Invoice":
        try:
            from thinknxg_rental.events.sales_invoice_type import get_deal_type
            deal_type = get_deal_type(doc)
        except Exception:
            deal_type = None
    return deal_type


def _render(name, doc):
    try:
        from erpnext.setup.doctype.terms_and_conditions.terms_and_conditions import get_terms_and_conditions
        return get_terms_and_conditions(name, doc)
    except Exception:
        return frappe.db.get_value("Terms and Conditions", name, "terms")


def apply(doc, method=None):
    if doc.docstatus != 0:
        return
    wanted = (TEMPLATES.get(doc.doctype) or {}).get(_deal_type(doc) or "")
    if not wanted or not frappe.db.exists("Terms and Conditions", wanted):
        return
    meta = frappe.get_meta(doc.doctype)
    if not meta.has_field("terms"):
        return
    has_tc = meta.has_field("tc_name")
    managed = {t for m in TEMPLATES.values() for t in m.values()}
    current = (doc.get("terms") or "").strip()
    if current:
        if has_tc:
            if doc.get("tc_name") not in managed or doc.get("tc_name") == wanted:
                return
        else:
            others = {
                (frappe.db.get_value("Terms and Conditions", t, "terms") or "").strip()
                for t in managed if t != wanted
            }
            if current not in others:
                return
    text = _render(wanted, doc)
    if not text:
        return
    doc.terms = text
    if has_tc:
        doc.tc_name = wanted
