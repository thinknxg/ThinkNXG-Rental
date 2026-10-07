import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, date_diff, flt, getdate, nowdate

from thinknxg_rental.services import jcr_billing
from thinknxg_rental.services.utils import get_contract_for_source


class JobCompletionReport(Document):
    """JCR supports one or many job lines from a Hire Order Contract.

    The multi-line table is the preferred model. Legacy single-line fields are retained so
    existing JCRs and billing records continue to work without migration of business data.
    """

    def validate(self):
        hoc = frappe.get_doc("Hire Order Contract", self.hire_order_contract)
        if hoc.docstatus != 1:
            frappe.throw(_("Hire Order Contract {0} is not submitted").format(hoc.name))
        self.company = self.company or hoc.company
        self.rental_contract = get_contract_for_source("Hire Order Contract", hoc.name)
        self.contract_charge_billing = hoc.contract_charge_billing

        if self.items:
            self._prepare_items(hoc)
            self._sync_header_from_first_item()
            return

        # Backward-compatible single-line JCR.
        line = self.get_job_line(hoc)
        self._validate_line_qty(hoc, line, flt(self.job_qty))
        self.included_days = cint(line.included_days)
        self.contract_rate = flt(line.contract_rate)
        self.excess_rate_basis = line.excess_rate_basis
        self.excess_rate = flt(line.excess_rate)
        self.location = self.location or line.location
        self.set_duration()

    def _prepare_items(self, hoc):
        contract_lines = {d.name: d for d in hoc.items}
        if not self.items:
            return
        for row in self.items:
            line = contract_lines.get(row.contract_item)
            if not line:
                # Older/manual rows can identify a line by job type + location.
                candidates = [d for d in hoc.items if d.job_type == row.job_type]
                wanted = (row.location or "").strip().lower()
                line = next((d for d in candidates if wanted and (d.location or "").strip().lower() == wanted), None)
                if not line:
                    line = next((d for d in candidates if flt(d.qty) - flt(get_reported_qty(hoc.name).get(d.name, 0)) > 1e-6), None)
            if not line:
                frappe.throw(_("{0} is not a job line on Hire Order Contract {1}").format(row.job_type or _("Selected job"), hoc.name))
            row.contract_item = line.name
            row.job_type = line.job_type
            row.location = row.location or line.location
            row.included_days = cint(line.included_days)
            row.contract_rate = flt(line.contract_rate)
            row.contract_charge_billing = hoc.contract_charge_billing
            row.excess_rate_basis = line.excess_rate_basis
            row.excess_rate = flt(line.excess_rate)
            if flt(row.job_qty) <= 0:
                row.job_qty = flt(line.qty) - flt(get_reported_qty(hoc.name, exclude=self.name).get(line.name, 0))
            if flt(row.job_qty) <= 0:
                frappe.throw(_("No remaining quantity for {0} {1}").format(row.job_type, row.location or ""))
            self._validate_line_qty(hoc, line, flt(row.job_qty))
            if not row.erection_date:
                frappe.throw(_("Erection Date is required for {0}{1}").format(row.job_type, f" ({row.location})" if row.location else ""))
            row.contract_end_date = jcr_billing.get_contract_end(row.erection_date, row.included_days)
            if row.dismantle_date and getdate(row.dismantle_date) < getdate(row.erection_date):
                frappe.throw(_("Dismantle Date cannot be before the Erection Date for {0}").format(row.job_type))
            upto = getdate(row.dismantle_date) if row.dismantle_date else max(getdate(nowdate()), getdate(row.erection_date))
            row.actual_days = date_diff(upto, row.erection_date) + 1
            row.excess_days = max(date_diff(upto, row.contract_end_date), 0)

        # Do not allow the same contract line twice in one JCR; use one row and its quantity.
        seen = set()
        for row in self.items:
            if row.contract_item in seen:
                frappe.throw(_("Contract job line {0} appears more than once in this JCR. Combine its quantity into one row.").format(row.contract_item))
            seen.add(row.contract_item)

    def _validate_line_qty(self, hoc, line, qty):
        if qty <= 0:
            frappe.throw(_("No. of Jobs must be greater than zero"))
        others = get_reported_qty(hoc.name, exclude=self.name).get(line.name, 0)
        if flt(others) + qty > flt(line.qty) + 1e-6:
            where = f" ({line.location})" if line.location else ""
            frappe.throw(
                _("{0}{1}: {2} on the contract line, {3} already on other JCRs, so at most {4} can go on this one.").format(
                    frappe.bold(line.job_type), where, flt(line.qty), flt(others), flt(line.qty) - flt(others)
                )
            )

    def _sync_header_from_first_item(self):
        if not self.items:
            return
        row = self.items[0]
        for field in ("contract_item", "job_type", "job_type_name", "location", "job_qty", "erection_date", "included_days",
                      "contract_end_date", "dismantle_date", "actual_days", "excess_days", "contract_rate",
                      "contract_charge_billing", "excess_rate_basis", "excess_rate"):
            if hasattr(row, field):
                setattr(self, field, row.get(field))

    def get_job_line(self, hoc):
        lines = [d for d in hoc.items if d.job_type == self.job_type]
        if not lines:
            frappe.throw(_("{0} is not a job type on Hire Order Contract {1}").format(frappe.bold(self.job_type), hoc.name))
        line = next((d for d in lines if d.name == self.contract_item), None)
        if not line:
            reported = get_reported_qty(hoc.name, exclude=self.name)
            wanted = (self.location or "").strip().lower()
            line = (next((d for d in lines if wanted and (d.location or "").strip().lower() == wanted), None)
                    or next((d for d in lines if flt(d.qty) - flt(reported.get(d.name)) > 1e-6), None)
                    or lines[0])
        self.contract_item = line.name
        return line

    def set_duration(self):
        self.contract_end_date = jcr_billing.get_contract_end(self.erection_date, self.included_days)
        if self.dismantle_date and getdate(self.dismantle_date) < getdate(self.erection_date):
            frappe.throw(_("Dismantle Date cannot be before the Erection Date"))
        upto = getdate(self.dismantle_date) if self.dismantle_date else max(getdate(nowdate()), getdate(self.erection_date))
        self.actual_days = date_diff(upto, self.erection_date) + 1
        self.excess_days = max(date_diff(upto, self.contract_end_date), 0)

    def before_update_after_submit(self):
        before = self.get_doc_before_save()
        if self.items:
            # Erection dates and quantities remain fixed after submission; dismantle is updated through the button/API.
            return
        if before and str(before.dismantle_date or "") != str(self.dismantle_date or ""):
            self.validate_dismantle_change(before)

    def validate_dismantle_change(self, before):
        if self.dismantle_date and getdate(self.dismantle_date) < getdate(self.erection_date):
            frappe.throw(_("Dismantle Date cannot be before the Erection Date"))
        billed_excess = [s for s in jcr_billing.get_schedules(self.name) if s.billing_type != "Contract" and (s.sales_invoice or s.status != "Pending")]
        if not billed_excess:
            return
        last = max(getdate(s.period_to) for s in billed_excess)
        if before.dismantle_date:
            frappe.throw(_("Excess is already billed up to {0}. Cancel those invoices and their JCR Billing Schedule rows before changing the dismantle date.").format(frappe.format(last, {"fieldtype": "Date"})))
        if self.dismantle_date and getdate(self.dismantle_date) <= last:
            frappe.throw(_("Excess is already billed up to {0}. Use a dismantle date after that, or cancel the later invoice and delete its JCR Billing Schedule row first.").format(frappe.format(last, {"fieldtype": "Date"})))

    def on_submit(self):
        self.update_contract_jobs()
        jcr_billing.update_jcr_progress(self.name)
        jcr_billing.generate_jcr_billing(self.name)

    def on_update_after_submit(self):
        jcr_billing.update_jcr_progress(self.name)
        if self.dismantle_date:
            jcr_billing.generate_jcr_billing(self.name)

    def on_cancel(self):
        for s in jcr_billing.get_schedules(self.name):
            if s.sales_invoice:
                docstatus = frappe.db.get_value("Sales Invoice", s.sales_invoice, "docstatus")
                if docstatus == 1:
                    frappe.throw(_("Cancel Sales Invoice {0} before cancelling this JCR").format(s.sales_invoice))
                if docstatus == 0:
                    frappe.delete_doc("Sales Invoice", s.sales_invoice, ignore_permissions=True)
            frappe.delete_doc("JCR Billing Schedule", s.name, ignore_permissions=True, force=True)
        self.db_set("status", "Cancelled")
        self.update_contract_jobs()

    def update_contract_jobs(self):
        hoc = frappe.get_doc("Hire Order Contract", self.hire_order_contract)
        reported = get_reported_qty(hoc.name)
        for d in hoc.items:
            d.db_set("jcr_qty", flt(reported.get(d.name)), update_modified=False)

    @frappe.whitelist()
    def record_dismantle(self, dismantle_date: str, remarks: str | None = None):
        self.check_permission("write")
        if self.docstatus != 1:
            frappe.throw(_("Submit the JCR first"))
        if self.items:
            for row in self.items:
                if not row.dismantle_date:
                    self._set_item_dismantle(row, dismantle_date)
            if remarks:
                self.remarks = remarks
            self.flags.ignore_validate_update_after_submit = True
            self.save()
            return
        self.dismantle_date = dismantle_date
        if remarks:
            self.remarks = remarks
        self.set_duration()
        self.flags.ignore_validate_update_after_submit = True
        self.save()

    @frappe.whitelist()
    def record_item_dismantle(self, contract_item: str, dismantle_date: str, remarks: str | None = None):
        self.check_permission("write")
        if self.docstatus != 1 or not self.items:
            frappe.throw(_("Submit a multi-item JCR first"))
        row = next((d for d in self.items if d.contract_item == contract_item), None)
        if not row:
            frappe.throw(_("Contract job line {0} is not in this JCR").format(contract_item))
        self._set_item_dismantle(row, dismantle_date)
        if remarks:
            self.remarks = remarks
        self.flags.ignore_validate_update_after_submit = True
        self.save()

    def _set_item_dismantle(self, row, dismantle_date):
        if getdate(dismantle_date) < getdate(row.erection_date):
            frappe.throw(_("Dismantle Date cannot be before the Erection Date for {0}").format(row.job_type))
        schedules = jcr_billing.get_schedules(self.name)
        billed = [s for s in schedules if (s.jcr_item or "") == row.name and s.billing_type != "Contract" and (s.sales_invoice or s.status != "Pending")]
        if billed:
            last = max(getdate(s.period_to) for s in billed)
            if getdate(dismantle_date) <= last:
                frappe.throw(_("{0} is already billed up to {1}. Cancel that billing first.").format(row.job_type, frappe.format(last, {"fieldtype":"Date"})))
        row.dismantle_date = dismantle_date
        row.actual_days = date_diff(row.dismantle_date, row.erection_date) + 1
        row.excess_days = max(date_diff(row.dismantle_date, row.contract_end_date), 0)


def get_reported_qty(hire_order_contract, exclude=None):
    """Return reported quantity by Hire Order Contract job-line name, for old and new JCRs."""
    result = frappe._dict()
    rows = frappe.db.sql(
        """select name, job_qty, contract_item, items from `tabJob Completion Report`
        where docstatus = 1 and hire_order_contract = %s and name != %s""",
        (hire_order_contract, exclude or ""), as_dict=True,
    )
    for d in rows:
        if d.items:
            try:
                child = frappe.parse_json(d.items)
                for row in child or []:
                    key = row.get("contract_item")
                    if key:
                        result[key] = flt(result.get(key)) + flt(row.get("job_qty"))
            except Exception:
                pass
        elif d.contract_item:
            result[d.contract_item] = flt(result.get(d.contract_item)) + flt(d.job_qty)
    return result
