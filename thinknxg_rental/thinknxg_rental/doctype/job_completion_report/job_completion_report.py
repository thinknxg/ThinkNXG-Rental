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
            self.append("job_lines", self.line_values(line))

    def line_values(self, line, default_erection=None):
        erection = default_erection  # blank unless a date is passed in; the user enters the real erection date
        return {
            "contract_item": line.name,
            "job_type": line.job_type,
            "job_type_name": line.job_type_name,
            "location": line.location,
            "job_qty": None,  # Qty Done starts blank; the user enters it
            "nxg_contract_qty": flt(line.get("qty")),
            "erection_date": erection,
            "included_days": cint(line.included_days),
            "nxg_duration": cint(line.get("nxg_duration")),
            "contract_end_date": jcr_billing.get_contract_end(erection, line.included_days) if erection else None,
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
        returned_other = get_returned_qty_by_line(hoc.name, exclude=self.name)
        seen = set()
        for row in self.job_lines:
            if not row.contract_item or row.contract_item not in contract_lines:
                frappe.throw(_("Row {0}: select a valid Hire Order Contract job line").format(row.idx))
            if row.contract_item in seen:
                frappe.throw(_("Row {0}: the same contract job line cannot be added twice to one JCR").format(row.idx))
            seen.add(row.contract_item)
            src = contract_lines[row.contract_item]
            n_rot = flt(row.get("nxg_rotations_done"))
            if n_rot < 0:
                frappe.throw(_("Row {0}: Rotations Done cannot be negative").format(row.idx))
            if n_rot > 0:
                row.job_qty = n_rot * flt(src.qty)
            if flt(row.job_qty) <= 0:
                frappe.throw(_("Row {0}: Enter Qty Done (it must be greater than zero)").format(row.idx))
            remaining = remaining_jobs(src, reported_other, returned_other)
            current_rotation = rotation_state(src, reported_other, returned_other)[1]
            if n_rot > 0 and flt(row.job_qty) > remaining + 1e-6:
                # several rotations in one JCR: allowed once the earlier jobs are back, up to No. of Jobs x Rotation in total
                done_other = flt(reported_other.get(src.name))
                at_site_other = done_other - flt(returned_other.get(src.name))
                if at_site_other <= 1e-6:
                    remaining = max(flt(src.qty) * max(cint(src.nxg_duration), 1) - done_other, 0)
            rot_no = cint(row.get("nxg_rotation"))
            if rot_no:
                if rot_no < 1 or rot_no > max(cint(src.nxg_duration), 1):
                    frappe.throw(_("Row {0}: Rotation No. must be between 1 and {1}").format(row.idx, max(cint(src.nxg_duration), 1)))
                if rot_no > current_rotation:
                    frappe.throw(_("Row {0}: Rotation {1} is not open yet. The current rotation is {2}").format(row.idx, rot_no, current_rotation))
            else:
                row.nxg_rotation = current_rotation
            if flt(row.job_qty) > remaining + 1e-6:
                frappe.throw(_("Row {0}: only {1} jobs remain for {2}").format(row.idx, max(remaining,0), row.job_type))
            row.job_type = src.job_type
            row.job_type_name = src.job_type_name
            row.location = row.location or src.location
            row.included_days = cint(src.included_days)
            row.nxg_duration = cint(src.nxg_duration)
            row.nxg_contract_qty = flt(src.qty)
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
            row.nxg_balance_qty, row.nxg_balance_rotation = line_balances(src.qty, src.nxg_duration, reported_other.get(src.name), row.job_qty)
            row.nxg_rotations_completed = flt((flt(reported_other.get(src.name)) + flt(row.job_qty)) / flt(src.qty), 3) if flt(src.qty) > 0 else 0

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
        self.update_contract_jobs()
        if any(r.dismantle_date for r in self.job_lines) or self.get("jcr_returns"):
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
        returned=get_returned_qty_by_line(hoc.name)
        for d in hoc.items:
            balance,rotation,rotations=rotation_state(d,reported,returned)
            d.db_set({"jcr_qty":flt(reported.get(d.name)),"balance_qty":balance,"rotation_no":rotation},update_modified=False)

    @frappe.whitelist()
    def record_dismantle(self, dismantle_date: str, line_name: str | None = None, remarks: str | None = None, return_qty: float | None = None):
        self.check_permission("write")
        if self.docstatus!=1: frappe.throw(_("Submit the JCR first"))
        candidates=[r for r in self.job_lines if not r.dismantle_date]
        if line_name: row=next((r for r in self.job_lines if r.name==line_name),None)
        elif len(candidates)==1: row=candidates[0]
        else: frappe.throw(_("Select the JCR Job Line to dismantle"))
        if not row: frappe.throw(_("JCR Job Line not found"))
        billed=[x for x in jcr_billing.get_schedules(self.name,row.name) if x.billing_type!="Contract" and (x.sales_invoice or x.status!="Pending")]
        if billed and getdate(dismantle_date)<=max(getdate(x.period_to) for x in billed):
            frappe.throw(_("Excess is already billed up to {0} for {1}. Use a later return date or cancel the later billing first.").format(frappe.format(max(getdate(x.period_to) for x in billed),{"fieldtype":"Date"}),row.job_type))
        if getdate(dismantle_date)<getdate(row.erection_date): frappe.throw(_("Return date cannot be before the Erection Date"))
        back=[r for r in self.get("jcr_returns") if r.jcr_line==row.name]
        left=flt(row.job_qty)-sum(flt(r.return_qty) for r in back)
        qty=flt(return_qty) or left
        if qty<=0 or qty>left+1e-6: frappe.throw(_("Qty Returned must be more than 0 and not above the {0} still outstanding").format(left))
        self.append("jcr_returns",{"jcr_line":row.name,"job_type":row.job_type,"return_date":dismantle_date,"return_qty":qty,"remarks":remarks})
        if remarks: row.remarks=remarks
        if left-qty<=1e-6:
            row.dismantle_date=max([getdate(dismantle_date)]+[getdate(r.return_date) for r in back])
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


def get_returned_qty_by_line(hire_order_contract, exclude=None):
    """{contract job line: jobs already returned on submitted JCRs}. A full dismantle recorded before returns existed counts as all returned."""
    result = {}
    names = frappe.get_all("Job Completion Report", filters={"docstatus": 1, "hire_order_contract": hire_order_contract, "name": ["!=", exclude or ""]}, pluck="name")
    for name in names:
        doc = frappe.get_doc("Job Completion Report", name)
        by_line = {}
        for x in doc.get("jcr_returns") or []:
            by_line[x.jcr_line] = by_line.get(x.jcr_line, 0) + flt(x.return_qty)
        for r in doc.job_lines:
            qty = by_line.get(r.name)
            if qty is None and r.dismantle_date:
                qty = flt(r.job_qty)
            if qty:
                result[r.contract_item] = result.get(r.contract_item, 0) + qty
    return result


def rotation_state(item, reported, returned):
    """(balance, rotation, rotations) of a contract line.
    Rotation 1 is jobs 1..N, rotation 2 is N+1..2N and so on (N = No. of Jobs). A JCR cannot run past the end of the
    current rotation, the jobs at the site can never exceed N, and the total is capped at N x Rotation."""
    qty = flt(item.qty)
    rotations = max(cint(item.get("nxg_duration")), 1)
    if qty <= 0:
        return 0, 1, rotations
    done = flt(reported.get(item.name))
    at_site = done - flt(returned.get(item.name))
    full = int(done / qty + 1e-9)
    rotation_balance = qty - (done - full * qty)
    balance = max(min(qty * rotations - done, rotation_balance, qty - at_site), 0)
    return balance, min(full + 1, rotations), rotations


def remaining_jobs(item, reported, returned):
    return rotation_state(item, reported, returned)[0]


def line_balances(qty, rotations, done_other, job_qty):
    """(balance jobs, balance rotations) of a contract line after this JCR row.
    Total = jobs per rotation x rotations; done = other submitted JCRs + this row."""
    qty = flt(qty)
    rotations = max(cint(rotations), 1)
    done = flt(done_other) + flt(job_qty)
    balance_qty = max(qty * rotations - done, 0)
    balance_rotation = max(rotations - done / qty, 0) if qty > 0 else 0
    return flt(balance_qty, 3), flt(balance_rotation, 3)


@frappe.whitelist()
def get_line_balance(hire_order_contract, contract_item, job_qty=0, exclude=None):
    frappe.has_permission("Job Completion Report", "read", throw=True)
    src = frappe.db.get_value("Hire Order Contract Item", contract_item, ["qty", "nxg_duration"], as_dict=True)
    if not src:
        return {"balance_qty": 0, "balance_rotation": 0}
    reported = get_reported_qty_by_line(hire_order_contract, exclude=exclude)
    bq, br = line_balances(src.qty, src.nxg_duration, reported.get(contract_item), job_qty)
    rd = flt((flt(reported.get(contract_item)) + flt(job_qty)) / flt(src.qty), 3) if flt(src.qty) > 0 else 0
    return {"balance_qty": bq, "balance_rotation": br, "rotations_done": rd}
