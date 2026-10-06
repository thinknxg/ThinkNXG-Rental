import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, date_diff, flt, formatdate, getdate


class JCR(Document):
    def autoname(self):
        # Location participates in the JCR name while retaining a unique series.
        location = (self.location or "GEN").replace(" ", "-")
        prefix = frappe.scrub(location).upper() or "GEN"
        self.name = frappe.model.naming.make_autoname(f"JCR-{prefix}-.#####")

    def validate(self):
        self.calculate_excess_amounts()
        self.validate_source()

    def validate_source(self):
        if self.hire_contract:
            contract = frappe.db.get_value("Hire Order Contract", self.hire_contract, ["customer", "project", "rental_site"], as_dict=True)
            if contract:
                self.client_name = contract.customer
                self.project_name = contract.project
                self.location = contract.rental_site

    def calculate_excess_amounts(self):
        for item in self.items:
            excess_charge = flt(item.excess_charge)
            contract_days = flt(item.contract_days)
            actual_days = 0
            if item.custom_erection_date and item.custom_dismantle_date:
                actual_days = date_diff(getdate(item.custom_dismantle_date), getdate(item.custom_erection_date))
            excess_days = actual_days - contract_days
            if excess_days <= 0 or not excess_charge:
                item.excess_days = 0
                item.excess_amount = 0
                continue
            item.excess_days = excess_days
            if item.excess_period == "Weekly":
                item.excess_amount = (excess_days / 7) * excess_charge
            elif item.excess_period == "Monthly":
                item.excess_amount = (excess_days / 30) * excess_charge
            else:
                item.excess_amount = excess_days * excess_charge


def _source_item(row):
    if row.sales_order_item and frappe.db.exists("Hire Contract Item", row.sales_order_item):
        return frappe.db.get_value("Hire Contract Item", row.sales_order_item,
            ["item_code", "item_name", "uom", "qty", "contract_rate", "contract_amount"], as_dict=True)
    return None


def _append_invoice_rows(source, target, row):
    src = _source_item(row)
    item_code = src.item_code if src else None
    item_name = src.item_name if src else row.job_description
    uom = src.uom if src else None
    qty = flt(row.qty) or (flt(src.qty) if src else 1) or 1
    contract_amount = flt(src.contract_amount) if src else 0
    contract_rate = contract_amount / qty if qty else 0
    if not contract_rate:
        contract_rate = flt(src.contract_rate) if src else 0
    contract_from = row.custom_erection_date
    contract_to = add_days(contract_from, flt(row.contract_days) - 1) if contract_from and flt(row.contract_days) else None
    description = "{0} {1}".format(source.name, row.job_description or item_name or "").strip()
    target.append("items", {
        "item_code": item_code,
        "item_name": item_name,
        "uom": uom,
        "description": description,
        "qty": qty,
        "rate": contract_rate,
        "amount": contract_amount or qty * contract_rate,
        "jcr": source.name,
        "ignore_pricing_rule": 1,
        "nxg_hire_item": item_code,
        "nxg_hire_qty": qty,
        "nxg_hire_from": contract_from,
        "nxg_hire_to": contract_to,
        "nxg_hire_days": flt(row.contract_days),
    })

    excess_days = flt(row.excess_days)
    excess_charge = flt(row.excess_charge)
    if excess_days <= 0 or not excess_charge:
        return
    if row.excess_period == "Weekly":
        unit_price = excess_days / 7 * excess_charge
    elif row.excess_period == "Monthly":
        unit_price = excess_days / 30 * excess_charge
    else:
        unit_price = excess_days * excess_charge
    target.append("items", {
        "item_code": item_code,
        "item_name": item_name,
        "uom": uom,
        "description": "Excess: {0:g} days x {1:g}".format(excess_days, excess_charge),
        "qty": qty,
        "rate": unit_price,
        "amount": qty * unit_price,
        "jcr": source.name,
        "ignore_pricing_rule": 1,
    })


@frappe.whitelist()
def make_sales_invoice(source_name, target_doc=None):
    source = frappe.get_doc("JCR", source_name)
    if source.docstatus != 1:
        frappe.throw(_("JCR {0} must be submitted").format(source.name))
    target = frappe.new_doc("Sales Invoice")
    target.customer = source.client_name
    target.project = source.project_name
    target.jcr = source.name
    target.ignore_pricing_rule = 1
    for row in source.items:
        _append_invoice_rows(source, target, row)
    return target


@frappe.whitelist()
def create_sales_invoice(source_name):
    existing = _live_invoice(source_name)
    if existing:
        frappe.throw(_("JCR {0} already has Sales Invoice {1}").format(source_name, existing))
    si = make_sales_invoice(source_name)
    si.insert(ignore_permissions=True)
    return si.name


def _live_invoice(jcr):
    rows = frappe.db.sql("""select si.name from `tabSales Invoice` si
        left join `tabSales Invoice Item` sii on sii.parent = si.name
        where si.docstatus < 2 and (si.jcr = %(j)s or sii.jcr = %(j)s) limit 1""", {"j": jcr})
    return rows[0][0] if rows else None


@frappe.whitelist()
def get_invoiceable_jcrs(jcr):
    customer = frappe.db.get_value("JCR", jcr, "client_name")
    rows = frappe.get_all("JCR", filters={"docstatus": 1, "client_name": customer, "name": ["!=", jcr]},
        fields=["name", "hire_contract", "project_name", "location", "lpo_number"], order_by="creation")
    return [r for r in rows if not _live_invoice(r.name)]


@frappe.whitelist()
def create_sales_invoice_for_jcrs(jcrs):
    if isinstance(jcrs, str):
        jcrs = json.loads(jcrs)
    jcrs = list(dict.fromkeys(jcrs))
    if len(jcrs) < 2:
        frappe.throw(_("Select at least one more JCR"))
    docs = []
    customers = set()
    for name in jcrs:
        doc = frappe.get_doc("JCR", name)
        if doc.docstatus != 1:
            frappe.throw(_("JCR {0} must be submitted").format(name))
        if _live_invoice(name):
            frappe.throw(_("JCR {0} already has an invoice").format(name))
        customers.add(doc.client_name); docs.append(doc)
    if len(customers) != 1:
        frappe.throw(_("All JCRs must belong to the same customer"))
    si = frappe.new_doc("Sales Invoice")
    si.customer = docs[0].client_name
    si.project = docs[0].project_name
    si.jcr = docs[0].name
    si.ignore_pricing_rule = 1
    for doc in docs:
        for row in doc.items:
            _append_invoice_rows(doc, si, row)
    si.insert(ignore_permissions=True)
    return si.name
