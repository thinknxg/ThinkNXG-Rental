"""Multi-line JCR billing. Each JCR line owns its own billing periods."""
import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, formatdate, get_last_day, getdate, nowdate
from thinknxg_rental.services.billing import append_taxes
from thinknxg_rental.services.utils import as_system, billable_units, get_settings


def get_contract_end(erection_date, included_days):
    return add_days(getdate(erection_date), max(cint(included_days),1)-1)


def plan_periods(line, today=None):
    today=getdate(today or nowdate()); erection=getdate(line.erection_date)
    contract_end=getdate(line.contract_end_date or get_contract_end(erection,line.included_days))
    dismantle=getdate(line.dismantle_date) if line.dismantle_date else None
    qty=flt(line.job_qty) or 1; month_basis=get_settings().month_basis; periods=[]
    if line.contract_charge_billing=="At Contract End": contract_due=min(contract_end,dismantle) if dismantle else contract_end
    else: contract_due=erection
    if today>=contract_due:
        charge=flt(line.contract_rate)*qty
        periods.append(frappe._dict(period_from=erection,period_to=contract_end,billing_type="Contract",days=date_diff(contract_end,erection)+1,contract_charge=charge,excess_charge=0,amount=charge))
    start=add_days(contract_end,1)
    while not dismantle or dismantle>=start:
        period_to=getdate(get_last_day(start)); final=bool(dismantle and dismantle<=period_to)
        if final: period_to=dismantle
        elif today<=period_to: break
        units=billable_units(qty,start,period_to,line.excess_rate_basis or "Daily",month_basis)
        charge=flt(units*flt(line.excess_rate),3)
        periods.append(frappe._dict(period_from=start,period_to=period_to,billing_type="Final Excess" if final else "Excess",days=date_diff(period_to,start)+1,contract_charge=0,excess_charge=charge,amount=charge))
        if final: break
        start=add_days(period_to,1)
    return periods


def get_schedules(jcr_name,line_name=None):
    filters={"jcr":jcr_name}
    if line_name: filters["jcr_line"]=line_name
    return frappe.get_all("JCR Billing Schedule",filters=filters,fields=["name","jcr","jcr_line","period_from","period_to","billing_type","amount","status","billed","sales_invoice","job_type"],order_by="period_from asc")


def _make_schedule(doc,line,p):
    schedule=frappe.new_doc("JCR Billing Schedule")
    schedule.update({"jcr":doc.name,"jcr_line":line.name,"rental_contract":doc.rental_contract,"hire_order_contract":doc.hire_order_contract,"customer":doc.customer,"job_type":line.job_type,"company":doc.company,"billing_type":p.billing_type,"status":"Pending" if flt(p.amount)>0 else "No Charge","period_from":p.period_from,"period_to":p.period_to,"days":p.days,"contract_charge":p.contract_charge,"excess_charge":p.excess_charge,"amount":p.amount})
    schedule.flags.ignore_permissions=True; schedule.insert(); return schedule


@frappe.whitelist()
def generate_jcr_billing(jcr: str):
    doc=frappe.get_doc("Job Completion Report",jcr); doc.check_permission("write")
    if doc.docstatus!=1: frappe.throw(_("Submit the JCR first"))
    created=[]
    for line in doc.job_lines:
        existing={(getdate(s.period_from),s.billing_type):s for s in get_schedules(doc.name,line.name)}
        for p in plan_periods(line):
            row=existing.get((getdate(p.period_from),p.billing_type))
            if row:
                if row.status=="Pending" and not row.sales_invoice:
                    if getdate(row.period_to)!=getdate(p.period_to): frappe.db.set_value("JCR Billing Schedule",row.name,{"period_to":p.period_to,"days":p.days,"contract_charge":p.contract_charge,"excess_charge":p.excess_charge,"amount":p.amount})
                    if flt(p.amount)>0: make_sales_invoice(row.name); created.append(row.name)
                continue
            schedule=_make_schedule(doc,line,p)
            if flt(p.amount)>0:
                make_sales_invoice(schedule.name); created.append(schedule.name)
    update_jcr_progress(doc.name); return created


@frappe.whitelist()
def make_sales_invoice(schedule: str):
    row=frappe.get_doc("JCR Billing Schedule",schedule); row.check_permission("read")
    if row.sales_invoice: frappe.throw(_("Sales Invoice {0} already exists for this period").format(row.sales_invoice))
    if flt(row.amount)<=0: frappe.throw(_("Nothing to invoice for this period"))
    jcr=frappe.get_doc("Job Completion Report",row.jcr); line=next((x for x in jcr.job_lines if x.name==row.jcr_line),None)
    if not line: frappe.throw(_("JCR Job Line {0} not found").format(row.jcr_line))
    hoc=frappe.get_doc("Hire Order Contract",jcr.hire_order_contract)
    qty=flt(line.job_qty) or 1; period=_("{0} to {1} ({2} days)").format(formatdate(row.period_from),formatdate(row.period_to),row.days); where=f" - {line.location}" if line.location else ""
    if row.billing_type=="Contract": desc=_("Contract charge: {0}{1}, {2} included days, {3}").format(line.job_type_name,where,line.included_days,period)
    else: desc=_("Excess charge: {0}{1}, {2}, at {3} per job ({4})").format(line.job_type_name,where,period,frappe.format_value(line.excess_rate,{"fieldtype":"Currency"}),line.excess_rate_basis)
    si=frappe.new_doc("Sales Invoice"); si.update({"company":jcr.company,"customer":jcr.customer,"posting_date":nowdate(),"project":hoc.project,"cost_center":hoc.cost_center,"payment_terms_template":hoc.payment_terms_template,"nxg_rental_contract":jcr.rental_contract,"nxg_jcr":jcr.name,"nxg_jcr_billing_schedule":row.name,"remarks":_("{0} - JCR {1}, Hire Order Contract {2}").format(desc,jcr.name,hoc.name)})
    si.append("items",{"item_code":line.job_type,"item_name":line.job_type_name,"description":desc,"qty":qty if qty==int(qty) else 1,"rate":flt(row.amount)/(qty if qty==int(qty) else 1),"project":hoc.project,"cost_center":hoc.cost_center})
    append_taxes(si,"Sales Taxes and Charges Template",hoc.taxes_and_charges); si.flags.ignore_permissions=True
    with as_system(): si.insert(); frappe.db.set_value("JCR Billing Schedule",row.name,{"sales_invoice":si.name,"status":"Invoiced","billed":1})
    if cint(get_settings().auto_submit_sales_invoice): si.submit()
    return si.name


def update_jcr_progress(jcr_name):
    doc=frappe.get_doc("Job Completion Report",jcr_name)
    if doc.docstatus!=1: return
    today=getdate(nowdate()); all_done=True; any_excess=False; any_dismantled=False; total=0; max_upto=None
    for line in doc.job_lines:
        erection=getdate(line.erection_date); end=getdate(line.contract_end_date); dismantle=getdate(line.dismantle_date) if line.dismantle_date else None
        upto=dismantle or max(today,erection); line.actual_days=max(date_diff(upto,erection)+1,0); line.excess_days=max(date_diff(upto,end),0)
        schedules=get_schedules(doc.name,line.name); settled=[s for s in schedules if s.status in ("Invoiced","No Charge")]
        total+=sum(flt(s.amount) for s in schedules if s.status=="Invoiced")
        billed_upto=max((getdate(s.period_to) for s in settled),default=None); line.billed_upto=billed_upto; line.total_billed_amount=sum(flt(s.amount) for s in schedules if s.status=="Invoiced")
        contract_done=any(s.billing_type=="Contract" and s.status in ("Invoiced","No Charge") for s in schedules)
        if dismantle:
            any_dismantled=True; done=contract_done and billed_upto and billed_upto>=max(dismantle,end) and all(s.status!="Pending" for s in schedules); line.status="Completed" if done else "Dismantled"; all_done &= done
        else:
            line.status="In Excess" if today>end else "Within Contract"; any_excess |= line.status=="In Excess"; all_done=False
        line.db_update()
    if all_done and doc.job_lines: status="Completed"
    elif any_dismantled: status="Dismantled"
    elif any_excess: status="In Excess"
    else: status="Within Contract"
    doc.db_set({"status":status,"total_billed_amount":total,"billed_upto":max((getdate(r.billed_upto) for r in doc.job_lines if r.billed_upto),default=None)},update_modified=False); doc.notify_update()


def run_daily_jcr_billing():
    if not cint(get_settings().auto_generate_jcr_billing): return
    for name in frappe.get_all("Job Completion Report",filters={"docstatus":1,"status":["not in",["Completed","Cancelled"]]},pluck="name"):
        try: generate_jcr_billing(name); frappe.db.commit()
        except Exception: frappe.db.rollback(); frappe.log_error(title=f"JCR billing failed for {name}",message=frappe.get_traceback())
