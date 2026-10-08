"""Convert legacy one-line JCRs to JCR Job Lines and link existing billing schedules."""
import frappe
from frappe.utils import flt


def execute():
    for j in frappe.get_all("Job Completion Report", filters={"docstatus":["<",2]}, pluck="name"):
        doc=frappe.get_doc("Job Completion Report",j)
        if doc.job_lines: continue
        if not doc.hire_order_contract or not doc.job_type: continue
        doc.append("job_lines",{
            "contract_item":doc.contract_item,"job_type":doc.job_type,"job_type_name":doc.job_type_name,
            "location":doc.location,"job_qty":flt(doc.job_qty),"erection_date":doc.erection_date,
            "included_days":doc.included_days,"contract_end_date":doc.contract_end_date,
            "dismantle_date":doc.dismantle_date,"actual_days":doc.actual_days,"excess_days":doc.excess_days,
            "contract_rate":doc.contract_rate,"contract_charge_billing":doc.contract_charge_billing,
            "excess_rate_basis":doc.excess_rate_basis,"excess_rate":doc.excess_rate,
            "billed_upto":doc.billed_upto,"total_billed_amount":doc.total_billed_amount,
            "status":doc.status,"remarks":doc.remarks,
        })
        doc.flags.ignore_validate_update_after_submit=True
        doc.flags.ignore_validate=True
        doc.save(ignore_permissions=True)
        if doc.job_lines:
            frappe.db.sql("update `tabJCR Billing Schedule` set jcr_line=%s where jcr=%s and ifnull(jcr_line,'')=''",(doc.job_lines[0].name,doc.name))
