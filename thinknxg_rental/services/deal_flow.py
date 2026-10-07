import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.utils import nowdate

DEAL_TYPES = ("Material Hire", "Material Sale", "Hire Order Contract")


def _check_deal_type(doc):
    if doc.get("deal_type") not in DEAL_TYPES:
        frappe.throw(_("Please select a valid Deal Type before creating the next document."))


def _set_party_from_lead(source, target):
    # ERPNext quotations can be made against a Lead. Keep the standard quotation
    # party model intact; conversion to Customer remains an ERPNext operation.
    target.quotation_to = "Lead"
    target.party_name = source.name
    target.customer_name = source.get("lead_name") or source.get("company_name") or source.get("name")
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


def _get_customer(source):
    # A quotation created against a Lead does not have a Customer yet.
    customer = source.get("party_name") if source.get("quotation_to") == "Customer" else None
    if not customer and source.get("customer"):
        customer = source.customer
    if not customer:
        frappe.throw(_("Convert the quotation party to a Customer before creating a rental document."))
    return customer


@frappe.whitelist()
def convert_quotation_party_to_customer(source_name: str):
    """Convert a Lead-backed quotation party to an ERPNext Customer.

    This is deliberately an additive bridge for the new Lead -> Quotation ->
    Rental flow. Existing Customer-backed quotations are left unchanged.
    """
    source = frappe.get_doc("Quotation", source_name)
    source.check_permission("write")
    if source.docstatus != 1:
        frappe.throw(_("Submit the quotation before converting its party to a Customer."))
    if source.get("quotation_to") == "Customer" and source.get("party_name"):
        return source.party_name
    if source.get("quotation_to") != "Lead" or not source.get("party_name"):
        frappe.throw(_("This quotation is not linked to a Lead party."))

    lead_name = source.party_name
    lead = frappe.get_doc("Lead", lead_name)
    lead.check_permission("read")

    # Prefer ERPNext's own Lead -> Customer mapper when available so standard
    # Customer defaults and linked data remain compatible with ERPNext.
    customer = None
    for method_name in (
        "erpnext.crm.doctype.lead.lead.make_customer",
        "erpnext.crm.doctype.lead.lead.make_customer_from_lead",
    ):
        try:
            method = frappe.get_attr(method_name)
            result = method(source_name=lead.name)
            if isinstance(result, str):
                customer = result
            elif getattr(result, "name", None):
                customer = result.name
            elif isinstance(result, dict):
                customer = result.get("name") or result.get("customer")
            if customer:
                break
        except (ImportError, AttributeError, TypeError):
            continue

    if not customer:
        # Safe fallback for ERPNext versions where the mapper is not exposed.
        customer_name = lead.get("lead_name") or lead.get("company_name") or lead.name
        existing = frappe.db.get_value("Customer", {"customer_name": customer_name}, "name")
        if existing:
            customer = existing
        else:
            customer_doc = frappe.new_doc("Customer")
            customer_doc.customer_name = customer_name
            customer_doc.customer_type = "Company" if lead.get("company_name") else "Individual"
            customer_group = lead.get("customer_group") or frappe.db.get_single_value("Selling Settings", "customer_group")
            if not customer_group:
                customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
            if customer_group:
                customer_doc.customer_group = customer_group
            if lead.get("territory") and customer_doc.meta.has_field("territory"):
                customer_doc.territory = lead.territory
            customer_doc.flags.ignore_permissions = False
            customer_doc.insert()
            customer = customer_doc.name

    # The quotation is already submitted, so update only its party identity.
    source.db_set("quotation_to", "Customer")
    source.db_set("party_name", customer)
    if source.meta.has_field("customer_name"):
        source.db_set("customer_name", frappe.db.get_value("Customer", customer, "customer_name"))
    return customer


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
    if source.get("quotation_to") != "Customer" or not source.get("party_name"):
        frappe.throw(_("Convert the quotation party to a Customer before creating a Sales Order."))

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
