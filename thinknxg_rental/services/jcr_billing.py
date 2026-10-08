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
def generate_jcr_billing(jcr: str, invoice: int = 1):
    """Create the due billing periods of a JCR. With invoice=0 only the schedules are created (they stay Pending)."""
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
                    if flt(p.amount)>0 and cint(invoice): make_sales_invoice(row.name); created.append(row.name)
                continue
            schedule=_make_schedule(doc,line,p)
            if flt(p.amount)>0:
                if cint(invoice): make_sales_invoice(schedule.name)
                created.append(schedule.name)
    update_jcr_progress(doc.name); return created


def _n(value):
    """Plain number for descriptions: 150, 12.5 (no trailing zeros, no exponent)."""
    return format(flt(value,2),"f").rstrip("0").rstrip(".") or "0"


def _dmy(value):
    return getdate(value).strftime("%d-%m-%Y")


def _title_text(jcr,line):
    head=f"{jcr.name} {line.job_type_name or line.job_type}"
    return f"{head} @ {line.location}" if line.location else head


def _period_rows(jcr,line,row,hoc):
    """Invoice row values for one billing period (contract or excess) of a JCR line."""
    qty=flt(line.job_qty) or 1; qty=qty if qty==int(qty) else 1
    span=f"{_dmy(row.period_from)} to {_dmy(row.period_to)}"; amount=flt(row.amount); unit=flt(amount/qty,3)
    values={"item_code":line.job_type,"item_name":line.job_type_name,"qty":qty,"rate":unit,"project":hoc.project,"cost_center":hoc.cost_center,
            "nxg_jcr":jcr.name,"nxg_jcr_billing_schedule":row.name,"nxg_locked_rate":unit,"nxg_locked_amount":amount}
    if row.billing_type=="Contract":
        values.update({"nxg_row_type":"Contract","description":f"{span}={row.days} Days","nxg_contract_from":row.period_from,"nxg_contract_to":row.period_to,
                       "nxg_contract_days":row.days,"nxg_contract_amount":amount})
    else:
        basis=line.excess_rate_basis or "Daily"
        if basis=="Daily": calc=f"{row.days} Days x {_n(line.excess_rate)}={_n(unit)}"
        else: calc=f"{row.days} Days @ {_n(line.excess_rate)} ({basis})={_n(unit)}"
        values.update({"nxg_row_type":"Excess","description":f"{span}={calc}","nxg_excess_days":row.days,"nxg_excess_period":span,
                       "nxg_excess_charge":unit,"nxg_excess_amount":amount})
    return values


def _create_invoice(schedule_names):
    """One Sales Invoice for the given pending JCR billing periods, possibly of several JCRs.

    Per JCR job line the invoice carries a title row ("JCR-no item @ location") followed by one
    row per billing period. The row-level nxg_jcr / nxg_jcr_billing_schedule links tie each row
    back to its schedule; the header links are set only when there is one JCR / one schedule.
    """
    rows=[frappe.get_doc("JCR Billing Schedule",n) for n in dict.fromkeys(schedule_names)]
    if not rows: frappe.throw(_("Nothing to invoice"))
    for r in rows:
        r.check_permission("read")
        if r.sales_invoice: frappe.throw(_("Sales Invoice {0} already exists for this period").format(r.sales_invoice))
        if flt(r.amount)<=0: frappe.throw(_("Nothing to invoice for {0}").format(r.name))
    if len({r.customer for r in rows})>1: frappe.throw(_("All JCRs on one invoice must belong to the same customer"))
    if len({r.company for r in rows})>1: frappe.throw(_("All JCRs on one invoice must belong to the same company"))
    by_jcr={}
    for r in rows: by_jcr.setdefault(r.jcr,[]).append(r)
    jcrs={n:frappe.get_doc("Job Completion Report",n) for n in sorted(by_jcr)}
    hocs={n:frappe.get_doc("Hire Order Contract",j.hire_order_contract) for n,j in jcrs.items()}
    for n,j in jcrs.items():
        if j.docstatus!=1: frappe.throw(_("JCR {0} is not submitted").format(n))
    if len({h.taxes_and_charges or "" for h in hocs.values()})>1: frappe.throw(_("The Hire Order Contracts of these JCRs use different tax templates. Invoice them separately."))
    first_jcr=next(iter(jcrs.values())); first_hoc=hocs[first_jcr.name]
    contracts={j.rental_contract for j in jcrs.values()}; projects={h.project for h in hocs.values()}; centers={h.cost_center for h in hocs.values()}; terms={h.payment_terms_template or "" for h in hocs.values()}
    si=frappe.new_doc("Sales Invoice")
    si.update({"company":first_jcr.company,"customer":first_jcr.customer,"posting_date":nowdate(),
               "project":first_hoc.project if len(projects)==1 else None,"cost_center":first_hoc.cost_center if len(centers)==1 else None,
               "payment_terms_template":first_hoc.payment_terms_template if len(terms)==1 else None,
               "nxg_rental_contract":first_jcr.rental_contract if len(contracts)==1 else None,
               "nxg_jcr":first_jcr.name if len(jcrs)==1 else None,
               "nxg_jcr_billing_schedule":rows[0].name if len(rows)==1 else None,
               "remarks":_("JCR {0}").format(", ".join(jcrs))})
    for n,j in jcrs.items():
        hoc=hocs[n]; mine={r.jcr_line:[] for r in by_jcr[n]}
        for r in sorted(by_jcr[n],key=lambda x:(getdate(x.period_from),x.billing_type)): mine[r.jcr_line].append(r)
        for line in j.job_lines:
            if line.name not in mine: continue
            si.append("items",{"item_code":line.job_type,"item_name":line.job_type_name,"description":_title_text(j,line),"qty":1,"rate":0,
                               "project":hoc.project,"cost_center":hoc.cost_center,"nxg_jcr":j.name,"nxg_row_type":"Title","nxg_locked_rate":0,"nxg_locked_amount":0})
            for r in mine[line.name]: si.append("items",_period_rows(j,line,r,hoc))
        missing=set(mine)-{l.name for l in j.job_lines}
        if missing: frappe.throw(_("JCR Job Line {0} not found").format(", ".join(missing)))
    append_taxes(si,"Sales Taxes and Charges Template",first_hoc.taxes_and_charges); si.flags.ignore_permissions=True
    with as_system():
        si.insert()
        for r in rows: frappe.db.set_value("JCR Billing Schedule",r.name,{"sales_invoice":si.name,"status":"Invoiced","billed":1})
    if cint(get_settings().auto_submit_sales_invoice): si.submit()
    for n in jcrs: update_jcr_progress(n)
    return si.name


@frappe.whitelist()
def make_sales_invoice(schedule: str):
    """Invoice a single billing period (used by the schedule form and the daily job)."""
    return _create_invoice([schedule])


@frappe.whitelist()
def get_combinable_jcrs(jcr: str):
    """Other open JCRs of the same customer and company that can share one invoice."""
    doc=frappe.get_doc("Job Completion Report",jcr); doc.check_permission("read")
    rows=frappe.get_all("Job Completion Report",filters={"docstatus":1,"customer":doc.customer,"company":doc.company,"name":["!=",jcr],"status":["not in",["Completed","Cancelled"]]},
                        fields=["name","rental_contract","hire_order_contract"],order_by="creation asc")
    pending={r.jcr:r for r in frappe.db.sql("""select jcr, count(*) as periods, sum(amount) as amount from `tabJCR Billing Schedule`
        where status='Pending' and ifnull(sales_invoice,'')='' and jcr in %s group by jcr""",[tuple(r.name for r in rows) or ("",)],as_dict=True)}
    for r in rows:
        p=pending.get(r.name); r.pending_periods=p.periods if p else 0; r.pending_amount=flt(p.amount) if p else 0
    return rows


@frappe.whitelist()
def make_combined_invoice(jcrs: str):
    """Create the due billing periods of the given JCRs (without invoicing them one by one) and put
    every pending period on a single Sales Invoice."""
    names=list(dict.fromkeys(frappe.parse_json(jcrs) or []))
    if not names: frappe.throw(_("Select at least one JCR"))
    for n in names:
        frappe.get_doc("Job Completion Report",n).check_permission("write")
        generate_jcr_billing(n,invoice=0)
    pending=frappe.get_all("JCR Billing Schedule",filters={"jcr":["in",names],"status":"Pending","amount":[">",0]},fields=["name","sales_invoice"])
    pending=[r.name for r in pending if not r.sales_invoice]
    if not pending: frappe.throw(_("No billing period is due for the selected JCRs."))
    return _create_invoice(pending)


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
