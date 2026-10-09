import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

from thinknxg_rental.services import jcr_billing
from thinknxg_rental.services.utils import get_contract_for_source


class JobCompletionReport(Document):
    """Multi-line JCR. One report can contain several Hire Order Contract job lines.
    Each row has independent erection/dismantle dates and billing terms. Legacy single-line
    fields are retained hidden for backward compatibility with older JCRs."""

    def validate(self):
        self.resolve_source_contract()
        hoc = frappe.get_doc("Hire Order Contract", self.hire_order_contract)
        if hoc.docstatus != 1:
            frappe.throw(_("Hire Order Contract {0} is not submitted").format(hoc.name))
        self.company = self.company or hoc.company
        self.rental_contract = self.rental_contract or get_contract_for_source("Hire Order Contract", hoc.name)
        if not self.job_lines:
            self.populate_job_lines(hoc)
        self.validate_lines(hoc)
        self.sync_legacy_fields()
        self.update_parent_status_preview()

    def resolve_source_contract(self):
        if self.rental_contract and not self.hire_order_contract:
            rc = frappe.db.get_value("Rental Contract", self.rental_contract, ["source_type","source_document","customer","company","rental_site"], as_dict=True)
            if rc and rc.source_type == "Hire Order Contract":
                self.hire_order_contract = rc.source_document
            elif rc and not self.customer:
                self.customer = rc.customer
        if not self.hire_order_contract and self.get("job_lines"):
            self.hire_order_contract = None

    def populate_job_lines(self, hoc):
        from thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract import get_open_job_lines
        lines = get_open_job_lines(hoc)
        self.set("job_lines", [])
        for line in lines:
            self.append("job_lines", self.line_values(line, default_erection=nowdate()))

    def line_values(self, line, default_erection=None):
        erection = default_erection or nowdate()
        return {
            "contract_item": line.name,
            "job_type": line.job_type,
            "job_type_name": line.job_type_name,
            "location": line.location,
            "job_qty": flt(line.remaining if hasattr(line, "remaining") else line.qty),
            "erection_date": erection,
            "included_days": cint(line.included_days),
            "contract_end_date": jcr_billing.get_contract_end(erection, line.included_days),
            "contract_rate": flt(line.contract_rate),
            "contract_charge_billing": self.contract_charge_billing or "On Erection",
            "excess_rate_basis": line.excess_rate_basis,
            "excess_rate": flt(line.excess_rate),
            "status": "Draft",
        }

    def validate_lines(self, hoc):
        if not self.job_lines:
            frappe.throw(_("Add at least one JCR Job Line"))
        contract_lines = {d.name:d for d in hoc.items}
        reported_other = get_reported_qty_by_line(hoc.name, exclude=self.name)
        seen = set()
        for row in self.job_lines:
            if not row.contract_item or row.contract_item not in contract_lines:
                frappe.throw(_("Row {0}: select a valid Hire Order Contract job line").format(row.idx))
            if row.contract_item in seen:
                frappe.throw(_("Row {0}: the same contract job line cannot be added twice to one JCR").format(row.idx))
            seen.add(row.contract_item)
            src = contract_lines[row.contract_item]
            if flt(row.job_qty) <= 0:
                frappe.throw(_("Row {0}: No. of Jobs must be greater than zero").format(row.idx))
            remaining = flt(src.qty) - flt(reported_other.get(row.contract_item, 0))
            if flt(row.job_qty) > remaining + 1e-6:
                frappe.throw(_("Row {0}: only {1} jobs remain for {2}").format(row.idx, max(remaining,0), row.job_type))
            row.job_type = src.job_type
            row.job_type_name = src.job_type_name
            row.location = src.location
            row.included_days = cint(src.included_days)
            row.contract_rate = flt(src.contract_rate)
            row.excess_rate_basis = src.excess_rate_basis
            row.excess_rate = flt(src.excess_rate)
            row.contract_charge_billing = hoc.contract_charge_billing
            if not row.erection_date:
                frappe.throw(_("Row {0}: Erection Date is required").format(row.idx))
            row.contract_end_date = jcr_billing.get_contract_end(row.erection_date, row.included_days)
            if row.dismantle_date and getdate(row.dismantle_date) < getdate(row.erection_date):
                frappe.throw(_("Row {0}: Dismantle Date cannot be before Erection Date").format(row.idx))
            upto = getdate(row.dismantle_date) if row.dismantle_date else max(getdate(nowdate()), getdate(row.erection_date))
            row.actual_days = max(date_diff(upto, row.erection_date) + 1, 0)
            row.excess_days = max(date_diff(upto, row.contract_end_date), 0)

    def sync_legacy_fields(self):
        """Keep old fields populated from the first row for compatibility with old reports/integrations."""
        first = self.job_lines[0] if self.job_lines else None
        if not first:
            return
        for name in ["job_type","job_type_name","contract_item","location","job_qty","erection_date","included_days","contract_end_date","dismantle_date","actual_days","excess_days","contract_rate","contract_charge_billing","excess_rate_basis","excess_rate","billed_upto","total_billed_amount"]:
            if hasattr(first, name):
                setattr(self, name, first.get(name))
        self.customer = self.customer or frappe.db.get_value("Hire Order Contract", self.hire_order_contract, "customer")
        self.customer_name = self.customer_name or frappe.db.get_value("Customer", self.customer, "customer_name")
        self.rental_site = self.rental_site or frappe.db.get_value("Hire Order Contract", self.hire_order_contract, "rental_site")

    def update_parent_status_preview(self):
        statuses=[r.status for r in self.job_lines]
        if not statuses: self.status="Draft"; return
        if all(s=="Completed" for s in statuses): self.status="Completed"
        elif any(s=="Dismantled" for s in statuses): self.status="Dismantled"
        elif any(s=="In Excess" for s in statuses): self.status="In Excess"
        else: self.status="Within Contract"

    def before_update_after_submit(self):
        before=self.get_doc_before_save()
        if not before: return
        old={r.name:r for r in before.job_lines}
        for row in self.job_lines:
            b=old.get(row.name)
            if b and str(b.dismantle_date or "") != str(row.dismantle_date or ""):
                self.validate_dismantle_change(row,b)

    def validate_dismantle_change(self,row,before):
        if row.dismantle_date and getdate(row.dismantle_date)<getdate(row.erection_date):
            frappe.throw(_("Dismantle Date cannot be before Erection Date for {0}").format(row.job_type))
        billed=[s for s in jcr_billing.get_schedules(self.name,row.name) if s.billing_type!="Contract" and (s.sales_invoice or s.status!="Pending")]
        if not billed: return
        last=max(getdate(s.period_to) for s in billed)
        if before.dismantle_date:
            frappe.throw(_("Excess is already billed up to {0} for {1}. Cancel those invoices/schedules before changing the dismantle date.").format(frappe.format(last,{"fieldtype":"Date"}),row.job_type))
        if row.dismantle_date and getdate(row.dismantle_date)<=last:
            frappe.throw(_("Excess is already billed up to {0} for {1}. Use a later dismantle date or cancel the later billing first.").format(frappe.format(last,{"fieldtype":"Date"}),row.job_type))

    def on_submit(self):
        self.update_contract_jobs()
        jcr_billing.generate_jcr_billing(self.name, invoice=0)
        jcr_billing.update_jcr_progress(self.name)

    def on_update_after_submit(self):
        jcr_billing.update_jcr_progress(self.name)
        if any(r.dismantle_date for r in self.job_lines):
            jcr_billing.generate_jcr_billing(self.name, invoice=0)

    def on_cancel(self):
        for s in jcr_billing.get_schedules(self.name):
            if s.sales_invoice:
                docstatus=frappe.db.get_value("Sales Invoice",s.sales_invoice,"docstatus")
                if docstatus==1: frappe.throw(_("Cancel Sales Invoice {0} before cancelling this JCR").format(s.sales_invoice))
                if docstatus==0: frappe.delete_doc("Sales Invoice",s.sales_invoice,ignore_permissions=True)
            frappe.delete_doc("JCR Billing Schedule",s.name,ignore_permissions=True,force=True)
        self.db_set("status","Cancelled")
        self.update_contract_jobs()

    def update_contract_jobs(self):
        hoc=frappe.get_doc("Hire Order Contract",self.hire_order_contract)
        reported=get_reported_qty_by_line(hoc.name)
        for d in hoc.items: d.db_set("jcr_qty",flt(reported.get(d.name)),update_modified=False)

    @frappe.whitelist()
    def record_dismantle(self, dismantle_date: str, line_name: str | None = None, remarks: str | None = None):
        self.check_permission("write")
        if self.docstatus!=1: frappe.throw(_("Submit the JCR first"))
        candidates=[r for r in self.job_lines if not r.dismantle_date]
        if line_name: row=next((r for r in self.job_lines if r.name==line_name),None)
        elif len(candidates)==1: row=candidates[0]
        else: frappe.throw(_("Select the JCR Job Line to dismantle"))
        if not row: frappe.throw(_("JCR Job Line not found"))
        row.dismantle_date=dismantle_date
        if remarks: row.remarks=remarks
        row.status="Dismantled"
        self.flags.ignore_validate_update_after_submit=True
        self.save()
        return row.name


def get_reported_qty_by_line(hire_order_contract, exclude=None):
    result={}
    rows=frappe.get_all("Job Completion Report",filters={"docstatus":1,"hire_order_contract":hire_order_contract,"name":["!=",exclude or ""]},pluck="name")
    if not rows: return result
    for name in rows:
        doc=frappe.get_doc("Job Completion Report",name)
        for r in doc.job_lines:
            result[r.contract_item]=result.get(r.contract_item,0)+flt(r.job_qty)
    return result


def get_reported_qty(hire_order_contract, exclude=None):
    """Legacy API: {contract job line: jobs on submitted JCRs}."""
    return get_reported_qty_by_line(hire_order_contract, exclude)
