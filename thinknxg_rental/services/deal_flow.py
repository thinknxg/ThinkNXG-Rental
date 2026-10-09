import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.utils import nowdate

DEAL_TYPES = ("Material Hire", "Material Sale", "Hire Order Contract")


def _check_deal_type(doc):
    if doc.get("deal_type") not in DEAL_TYPES:
        frappe.throw(_("Please select a valid Deal Type before creating the next document."))


def _customer_from_lead(lead):
    """The Customer already made from this Lead, otherwise a new one made with ERPNext's own
    Lead -> Customer routine (contacts and addresses come across the standard way; the Lead is marked converted)."""
    customer = frappe.db.get_value("Customer", {"lead_name": lead.name}, "name")
    if customer:
        return customer
    frappe.has_permission("Customer", "create", throw=True)
    make_customer = frappe.get_attr("erpnext.crm.doctype.lead.lead.make_customer")
    doc = make_customer(lead.name)
    if not hasattr(doc, "insert"):
        doc = frappe.get_doc(doc)
    if not doc.get("customer_group"):
        doc.customer_group = frappe.db.get_single_value("Selling Settings", "customer_group")
    if not doc.get("territory"):
        doc.territory = frappe.db.get_single_value("Selling Settings", "territory")
    doc.insert()
    return doc.name


def _set_party_from_lead(source, target):
    # The quotation is addressed to the Customer made from the Lead, so nothing has to be edited by hand.
    customer = _customer_from_lead(source)
    target.quotation_to = "Customer"
    target.party_name = customer
    target.customer_name = frappe.db.get_value("Customer", customer, "customer_name") or source.get("lead_name") or source.name
    if source.get("email_id") and target.meta.has_field("contact_email"):
        target.contact_email = source.email_id
    if source.get("phone") and target.meta.has_field("contact_mobile"):
        target.contact_mobile = source.phone


@frappe.whitelist()
def make_quotation_from_lead(source_name: str, target_doc=None):
    source = frappe.get_doc("Lead", source_name)
    source.check_permission("read")
    _check_deal_type(source)
    if source.docstatus != 0:
        frappe.throw(_("Lead {0} cannot be converted because it is not open.").format(source.name))

    def post_process(src, target):
        target.transaction_date = nowdate()
        target.deal_type = src.deal_type
        _set_party_from_lead(src, target)
        if src.get("company") and target.meta.has_field("company"):
            target.company = src.company

    return get_mapped_doc(
        "Lead",
        source_name,
        {"Lead": {"doctype": "Quotation", "validation": {"docstatus": ["=", 0]}}},
        target_doc,
        post_process,
    )


def _quotation_source(source_name):
    source = frappe.get_doc("Quotation", source_name)
    source.check_permission("read")
    if source.docstatus != 1:
        frappe.throw(_("Quotation {0} must be submitted before creating the next document.").format(source.name))
    _check_deal_type(source)
    return source


def _make_customer_from_quotation(quotation_name):
    """The Customer of a quotation made for a Lead or Prospect: the one already made from that Lead
    if there is one, otherwise a new one. This is ERPNext's own routine (the one its Sales Order
    uses), so Customer Group, Territory, contacts and addresses come across the standard way."""
    make_customer = frappe.get_attr("erpnext.selling.doctype.quotation.quotation._make_customer")
    customer = make_customer(quotation_name)
    if not customer:
        frappe.throw(_("A Customer could not be created from the party of quotation {0}.").format(quotation_name))
    return customer


def _get_customer(source):
    # A quotation created against a Lead has no Customer yet. Do not stop there: use the Customer
    # already made from the Lead, or make it now.
    if source.get("quotation_to") == "Customer" and source.get("party_name"):
        return source.party_name
    if source.get("customer"):
        return source.customer
    return _make_customer_from_quotation(source.name).name


@frappe.whitelist()
def make_customer_from_quotation(source_name: str):
    """Convert the Lead (or Prospect) of a quotation to a Customer, before or after it is submitted.
    Returns the Customer name; if the Lead already has one, that Customer is returned."""
    source = frappe.get_doc("Quotation", source_name)
    source.check_permission("read")
    if source.docstatus == 2:
        frappe.throw(_("Quotation {0} is cancelled.").format(source.name))
    return _get_customer(source)


@frappe.whitelist()
def make_hire_order_from_quotation(source_name: str, target_doc=None):
    source = _quotation_source(source_name)
    if source.deal_type != "Material Hire":
        frappe.throw(_("This quotation is not a Material Hire deal."))
    customer = _get_customer(source)

    def post_process(src, target):
        target.quotation = src.name
        target.customer = customer
        target.customer_name = src.get("customer_name") or frappe.db.get_value("Customer", customer, "customer_name")
        target.company = src.get("company") or frappe.defaults.get_global_default("company")
        target.order_date = src.transaction_date or nowdate()
        if src.get("items"):
            # Preserve the existing Hire Order validation/rate logic; quotation values
            # are only used as initial values for the existing fields.
            target.set("items", [])
            for row in src.items:
                if not row.item_code:
                    continue
                target.append("items", {
                    "item_code": row.item_code,
                    "item_name": row.item_name,
                    "uom": row.uom,
                    "qty": row.qty,
                    "rate": row.rate,
                })

    return _new_mapped_doc(
        source, "Hire Order", target_doc, post_process
    )


@frappe.whitelist()
def make_hire_order_contract_from_quotation(source_name: str, target_doc=None):
    source = _quotation_source(source_name)
    if source.deal_type != "Hire Order Contract":
        frappe.throw(_("This quotation is not a Hire Order Contract deal."))
    customer = _get_customer(source)

    def post_process(src, target):
        target.customer = customer
        target.company = src.get("company") or frappe.defaults.get_global_default("company")
        target.required_from = src.transaction_date or nowdate()
        target.items = []
        for row in src.items:
            if not row.item_code:
                continue
            target.append("items", {
                "job_type": row.item_code,
                "job_type_name": row.item_name,
                "qty": row.qty,
                "contract_rate": row.rate,
            })

    return _new_mapped_doc(source, "Hire Order Contract", target_doc, post_process)


@frappe.whitelist()
def make_sales_order_from_quotation(source_name: str, target_doc=None):
    source = _quotation_source(source_name)
    if source.deal_type != "Material Sale":
        frappe.throw(_("This quotation is not a Material Sale deal."))
    # Use ERPNext's standard quotation -> sales order mapper so the existing
    # sales flow and validations remain untouched.
    method = frappe.get_attr("erpnext.selling.doctype.quotation.quotation.make_sales_order")
    return method(source_name=source.name, target_doc=target_doc)


def _new_mapped_doc(source, target_doctype, target_doc, post_process):
    # This mapper copies only the generic fields we explicitly want. The target
    # DocType's own validate/on_submit logic remains responsible for all rental rules.
    target = frappe.new_doc(target_doctype)
    target.flags.ignore_permissions = False
    post_process(source, target)
    return target
