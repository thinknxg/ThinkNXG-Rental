"""Subcontractor portal API (/subcontractor). Every method:

- resolves the subcontractor from the session user (services/subcontract_portal.current), never from the browser;
- reads with explicit supplier filters, or loads a document only after `own()` confirmed it belongs to that supplier;
- writes only through the documents' own validations, inserted as Portal-sourced drafts that staff review;
- never returns internal notes, other suppliers' data, or (for Operational contacts) rates and amounts.

Portal users have no desk permissions on these DocTypes, so writes run with ignore_permissions after those checks.
"""
import json

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, flt, getdate, now_datetime, nowdate

from thinknxg_rental.services import subcontract_portal as sp
from thinknxg_rental.services import subcontracting as sc

SWO = "Subcontract Work Order"
PAGE = 20
ATTACHABLE = {"Subcontract Daily Progress", "Subcontract Material Request", "Subcontract Variation", "Subcontractor Invoice Submission",
	"Subcontract Work Progress", "Subcontract Message", "Subcontract Material Allocation", SWO}
ALLOWED_EXT = {"pdf", "jpg", "jpeg", "png", "webp", "heic", "doc", "docx", "xls", "xlsx", "csv", "txt"}
MAX_UPLOAD = 10 * 1024 * 1024


def _acc(need=None, write=False):
	acc = sp.current(frappe.form_dict.get("supplier"), need)
	if write and acc.suspended:
		raise frappe.PermissionError(_("Your subcontractor account is suspended; the portal is read-only"))
	sp.touch(acc)
	return acc


def _commercial(acc):
	return acc.access_level == sp.COMMERCIAL


def _rows(value):
	if isinstance(value, str):
		value = json.loads(value or "[]")
	return value or []


def _paging(page):
	page = max(cint(page) or 1, 1)
	return (page - 1) * PAGE, PAGE


def _strip(d, acc, money=()):
	"""Drop money fields for operational contacts."""
	if not _commercial(acc):
		for f in money:
			d.pop(f, None)
	return d


def _insert(doc):
	doc.flags.ignore_permissions = True
	doc.source = "Portal"
	doc.insert()
	return doc


def _own_swo(name, acc):
	doc = sp.own(SWO, name, acc)
	if doc.docstatus != 1 or doc.status in ("Draft", "Pending Approval", "Approved"):
		# not yet released to the subcontractor
		raise frappe.PermissionError(_("{0} {1} was not found").format(_(SWO), name))
	return doc


RELEASED_FILTER = ["not in", ["Draft", "Pending Approval", "Approved", "Cancelled"]]


# ------------------------------------------------------------------------------------------------------- boot
@frappe.whitelist()
def boot():
	acc = _acc()
	s = sc.settings()
	others = [{"supplier": a.supplier, "name": a.supplier_name} for a in sp.accesses()]
	return {"user": frappe.session.user, "full_name": acc.full_name, "supplier": acc.supplier, "supplier_name": acc.supplier_name,
		"access_level": acc.access_level, "commercial": _commercial(acc), "suspended": acc.suspended, "accounts": others,
		"contact_email": s.portal_contact_email, "contact_phone": s.portal_contact_phone,
		"currency": frappe.db.get_value("Supplier", acc.supplier, "default_currency") or frappe.db.get_default("currency")}


# ------------------------------------------------------------------------------------------------------- dashboard
@frappe.whitelist()
def dashboard():
	acc = _acc()
	sup = acc.supplier
	today = getdate(nowdate())
	wos = frappe.get_all(SWO, filters={"supplier": sup, "docstatus": 1, "status": RELEASED_FILTER},
		fields=["name", "status", "work_description", "project", "rental_site", "start_date", "expected_completion_date", "final_contract_value", "priority"],
		order_by="modified desc")
	working = [w for w in wos if w.status in sc.WORKING]
	cards = {
		"active": len([w for w in wos if w.status not in ("Closed", "Verified", "Rejected by Subcontractor")]),
		"awaiting_acceptance": len([w for w in wos if w.status == "Sent to Subcontractor"]),
		"in_progress": len([w for w in wos if w.status in ("Work In Progress", "Partially Completed")]),
		"pending_material": frappe.db.count("Subcontract Material Request", {"supplier": sup, "status": ["in", ["Submitted", "Approved", "Partially Issued"]]}),
		"inspection_pending": frappe.db.count("Subcontract Work Progress", {"supplier": sup, "docstatus": 0,
			"inspection_status": ["in", ["Inspection Requested", "Under Inspection"]]}),
	}
	if _commercial(acc):
		approved = flt(frappe.db.sql("""select sum(wi.accepted_qty * wi.rate) from `tabSubcontract Work Item` wi join `tabSubcontract Work Order` w
			on w.name = wi.parent where w.supplier = %s and w.docstatus = 1""", sup)[0][0])
		inv = frappe.db.sql("""select count(*), sum(outstanding_amount), sum(case when due_date < %s and outstanding_amount > 0 then outstanding_amount else 0 end)
			from `tabPurchase Invoice` where supplier = %s and docstatus = 1 and ifnull(subcontract_work_order, '') != ''""", (today, sup))[0]
		cards.update(approved_value=approved, submitted_invoices=frappe.db.count("Subcontractor Invoice Submission", {"supplier": sup, "status": "Submitted"}),
			outstanding=flt(inv[1]), overdue=flt(inv[2]))
	schedule = sorted([w for w in working if w.expected_completion_date], key=lambda w: w.expected_completion_date)[:6]
	for w in schedule:
		w.days_left = (getdate(w.expected_completion_date) - today).days
	actions = []
	for w in wos:
		if w.status == "Sent to Subcontractor":
			actions.append({"kind": "accept", "label": _("Accept or reject work order {0}").format(w.name), "route": f"work-orders/{w.name}"})
	for r in frappe.get_all("Subcontract Daily Progress", filters={"supplier": sup, "status": "Returned", "docstatus": 0}, pluck="name"):
		actions.append({"kind": "progress", "label": _("Correct progress report {0}").format(r), "route": "progress"})
	for r in frappe.get_all("Subcontract Material Allocation", filters={"supplier": sup, "docstatus": 1, "received_by_subcontractor": 0}, pluck="name"):
		actions.append({"kind": "receipt", "label": _("Confirm receipt of material issue {0}").format(r), "route": "materials"})
	for r in frappe.get_all("Subcontract Work Progress", filters={"supplier": sup, "docstatus": 1, "inspection_status": "Rework Required"},
			fields=["name", "subcontract_work_order"], limit=5):
		actions.append({"kind": "rework", "label": _("Rework required: {0}").format(r.name), "route": f"work-orders/{r.subcontract_work_order}"})
	docs = frappe.get_all("Subcontractor Compliance Document", filters={"parent": sup, "parenttype": "Supplier"},
		fields=["document_type", "expiry_date", "compliance_status"])
	expiring = [d for d in docs if sc.compliance_status(d.expiry_date) in ("Expiring", "Expired")]
	payments = []
	if _commercial(acc):
		payments = frappe.db.sql("""select pe.name, pe.posting_date, pe.paid_amount, pe.reference_no, pe.mode_of_payment from `tabPayment Entry` pe
			where pe.party_type = 'Supplier' and pe.party = %s and pe.docstatus = 1 and pe.payment_type = 'Pay' order by pe.posting_date desc limit 5""", sup, as_dict=True)
	progress = []
	for w in working[:8]:
		row = frappe.db.sql("""select sum(qty), sum(accepted_qty), sum(reported_qty) from `tabSubcontract Work Item` where parent = %s""", w.name)[0]
		progress.append({"name": w.name, "title": w.work_description or w.project or w.name, "ordered": flt(row[0]),
			"accepted": flt(row[1]), "reported": flt(row[2])})
	s = sc.settings()
	announcements = [{"date": s.announcement_date, "message": s.portal_announcement}] if s.portal_announcement else []
	announcements += frappe.get_all("Subcontract Message", filters={"supplier": sup, "direction": "Announcement"},
		fields=["creation as date", "subject", "message"], order_by="creation desc", limit=3)
	unread = frappe.db.count("Subcontract Message", {"supplier": sup, "direction": ["!=", "From Subcontractor"], "read_by_supplier": 0})
	return {"cards": cards, "schedule": [_strip(dict(w), acc, ("final_contract_value",)) for w in schedule],
		"recent": [_strip(dict(w), acc, ("final_contract_value",)) for w in wos[:6]], "actions": actions[:12], "expiring": expiring,
		"payments": payments, "progress": progress, "announcements": announcements, "unread_messages": unread}


# ------------------------------------------------------------------------------------------------------- work orders
@frappe.whitelist()
def work_orders(status=None, search=None, page=1):
	acc = _acc()
	filters = {"supplier": acc.supplier, "docstatus": 1, "status": RELEASED_FILTER}
	if status == "open":
		filters["status"] = ["in", list(sc.WORKING) + ["Completed", "On Hold", "Pending Final Verification"]]
	elif status == "awaiting":
		filters["status"] = "Sent to Subcontractor"
	elif status == "closed":
		filters["status"] = ["in", ["Verified", "Closed"]]
	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = {"name": ["like", like], "work_description": ["like", like], "project": ["like", like]}
	start, length = _paging(page)
	rows = frappe.get_all(SWO, filters=filters, or_filters=or_filters, fields=["name", "status", "work_description", "project", "rental_site",
		"contract_date", "start_date", "expected_completion_date", "final_contract_value", "priority", "currency"],
		order_by="contract_date desc, name desc", start=start, page_length=length + 1)
	for r in rows:
		q = frappe.db.sql("select sum(qty), sum(accepted_qty) from `tabSubcontract Work Item` where parent = %s", r.name)[0]
		r.progress = round(100 * flt(q[1]) / flt(q[0]), 1) if flt(q[0]) else 0
	return {"rows": [_strip(dict(r), acc, ("final_contract_value",)) for r in rows[:length]], "more": len(rows) > length}


@frappe.whitelist()
def work_order(name):
	acc = _acc()
	d = _own_swo(name, acc)
	money = _commercial(acc)
	items = []
	for r in d.items:
		row = {"name": r.name, "job_type": r.job_type, "description": r.description, "work_category": r.work_category, "uom": r.uom, "qty": r.qty,
			"reported_qty": flt(r.reported_qty), "accepted_qty": flt(r.accepted_qty), "rejected_qty": flt(r.rejected_qty),
			"invoiced_qty": flt(r.invoiced_qty), "completion_date": r.completion_date, "is_additional": r.is_additional}
		if money:
			row.update(rate=r.rate, amount=r.amount)
		items.append(row)
	head = {k: d.get(k) for k in ("name", "status", "work_description", "project", "customer", "rental_site", "contract_date", "start_date",
		"expected_completion_date", "actual_start_date", "actual_completion_date", "priority", "subcontract_type", "work_instructions", "sent_on",
		"confirmed_start_date", "subcontractor_response", "hold_reason", "currency", "agreement")}
	head["site_engineer"] = frappe.utils.get_fullname(d.site_engineer) if d.site_engineer else None
	head["project_manager"] = frappe.utils.get_fullname(d.project_manager) if d.project_manager else None
	if money:
		head.update({k: d.get(k) for k in ("final_contract_value", "contract_amount", "approved_additional_cost", "retention_percentage",
			"advance_percentage", "advance_amount", "payment_terms")})
	head["can_respond"] = d.status == "Sent to Subcontractor" and not acc.suspended
	head["can_report"] = d.status in sc.WORKING and d.status != "Approved" and not acc.suspended
	sup = acc.supplier
	return {
		"doc": head, "items": items,
		"progress": frappe.get_all("Subcontract Daily Progress", filters={"subcontract_work_order": name, "supplier": sup},
			fields=["name", "report_date", "status", "labour_deployed", "delay_reported", "review_remarks"], order_by="report_date desc", limit=20),
		"inspections": frappe.get_all("Subcontract Work Progress", filters={"subcontract_work_order": name, "supplier": sup, "docstatus": ["<", 2]},
			fields=["name", "progress_date", "inspection_status", "proposed_inspection_date", "quality_remarks", "corrective_action"],
			order_by="creation desc", limit=20),
		"materials": frappe.get_all("Subcontract Material Request", filters={"subcontract_work_order": name, "supplier": sup},
			fields=["name", "request_date", "required_by", "status"], order_by="creation desc", limit=20),
		"issues": frappe.get_all("Subcontract Material Allocation", filters={"subcontract_work_order": name, "supplier": sup, "docstatus": 1},
			fields=["name", "posting_date", "received_by_subcontractor", "shortage_reported"], order_by="posting_date desc"),
		"variations": [_strip(dict(v), acc, ("claimed_amount", "approved_amount", "value_change")) for v in frappe.get_all("Subcontract Variation",
			filters={"subcontract_work_order": name, "supplier": sup}, fields=["name", "variation_type", "request_date", "status", "claimed_amount",
			"approved_amount", "value_change", "external_remarks"], order_by="creation desc")],
		"invoices": frappe.get_all("Subcontractor Invoice Submission", filters={"subcontract_work_order": name, "supplier": sup},
			fields=["name", "supplier_invoice_no", "supplier_invoice_date", "status", "total_claimed", "purchase_invoice"], order_by="creation desc") if money else [],
		"files": _files(SWO, name),
		"messages": _messages(sup, name),
	}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=60, seconds=600)
def respond_work_order(name, action, remarks=None, confirmed_start_date=None):
	acc = _acc(write=True)
	d = _own_swo(name, acc)
	if d.status != "Sent to Subcontractor":
		frappe.throw(_("This work order is not waiting for your response"))
	if action not in ("accept", "reject"):
		frappe.throw(_("Choose accept or reject"))
	if action == "reject" and not (remarks or "").strip():
		frappe.throw(_("Give the reason for rejecting the work order"))
	if confirmed_start_date and getdate(confirmed_start_date) < getdate(d.contract_date):
		frappe.throw(_("The start date cannot be before the work order date"))
	status = "Accepted by Subcontractor" if action == "accept" else "Rejected by Subcontractor"
	d.db_set({"status": status, "responded_by": frappe.session.user, "responded_on": now_datetime(), "subcontractor_response": remarks,
		"confirmed_start_date": confirmed_start_date or None})
	d.add_comment("Info", _("{0} by {1} through the portal{2}").format(status, frappe.session.user, (": " + remarks) if remarks else ""))
	sp.notify_staff(name, _("{0}: {1}").format(name, _(status)), SWO, name)
	return status


@frappe.whitelist()
def work_order_pdf(name):
	acc = _acc()
	d = _own_swo(name, acc)
	if not _commercial(acc):
		frappe.throw(_("Your access does not include the priced work order"), frappe.PermissionError)
	frappe.local.response.filename = f"{d.name}.pdf"
	frappe.local.response.filecontent = frappe.get_print(SWO, d.name, as_pdf=True, no_letterhead=0, doc=d)
	frappe.local.response.type = "pdf"


# ------------------------------------------------------------------------------------------------------- daily progress
def _item_rows(swo, rows, field):
	valid = {r.name for r in swo.items}
	out = []
	for r in _rows(rows):
		if r.get("swo_item") not in valid:
			frappe.throw(_("A line does not belong to work order {0}").format(swo.name))
		if flt(r.get(field)):
			out.append({"swo_item": r["swo_item"], field: flt(r.get(field)), "remarks": r.get("remarks")})
	return out


@frappe.whitelist()
def progress_reports(work_order=None, page=1):
	acc = _acc()
	filters = {"supplier": acc.supplier}
	if work_order:
		filters["subcontract_work_order"] = work_order
	start, length = _paging(page)
	rows = frappe.get_all("Subcontract Daily Progress", filters=filters, fields=["name", "subcontract_work_order", "report_date", "status",
		"labour_deployed", "delay_reported", "delay_reason", "review_remarks", "expected_completion_date"], order_by="report_date desc, creation desc",
		start=start, page_length=length + 1)
	return {"rows": rows[:length], "more": len(rows) > length}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=60, seconds=600)
def submit_progress(work_order, items, report_date=None, labour_deployed=None, labour_details=None, equipment_deployed=None,
		delay_reported=0, delay_reason=None, blockers=None, expected_completion_date=None, remarks=None):
	acc = _acc(write=True)
	swo = _own_swo(work_order, acc)
	doc = frappe.get_doc({"doctype": "Subcontract Daily Progress", "subcontract_work_order": swo.name, "report_date": report_date or nowdate(),
		"items": _item_rows(swo, items, "qty_done"), "labour_deployed": cint(labour_deployed), "labour_details": labour_details,
		"equipment_deployed": equipment_deployed, "delay_reported": cint(delay_reported), "delay_reason": delay_reason, "blockers": blockers,
		"expected_completion_date": expected_completion_date or None, "subcontractor_remarks": remarks})
	_insert(doc)
	doc.flags.workflow_move = True
	doc.flags.ignore_permissions = True
	doc.status = "Submitted"
	doc.save()
	sp.notify_staff(swo.name, _("Progress report {0} for {1}").format(doc.name, swo.name), doc.doctype, doc.name)
	return doc.name


# ------------------------------------------------------------------------------------------------------- inspections
@frappe.whitelist()
def inspections(work_order=None, page=1):
	acc = _acc()
	filters = {"supplier": acc.supplier, "docstatus": ["<", 2]}
	if work_order:
		filters["subcontract_work_order"] = work_order
	start, length = _paging(page)
	rows = frappe.get_all("Subcontract Work Progress", filters=filters, fields=["name", "subcontract_work_order", "progress_date", "inspection_status",
		"proposed_inspection_date", "quality_remarks", "corrective_action", "docstatus"], order_by="creation desc", start=start, page_length=length + 1)
	for r in rows:
		r["items"] = frappe.get_all("Subcontract Progress Item", filters={"parent": r.name}, fields=["job_type", "reported_qty", "accepted_qty",
			"rejected_qty", "rework_qty"])
	return {"rows": rows[:length], "more": len(rows) > length}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=30, seconds=600)
def request_inspection(work_order, items, proposed_date=None, location=None, remarks=None):
	acc = _acc(write=True)
	swo = _own_swo(work_order, acc)
	rows = _item_rows(swo, items, "reported_qty")
	if not rows:
		frappe.throw(_("Enter the quantity to inspect"))
	if proposed_date and getdate(proposed_date) < getdate(nowdate()):
		frappe.throw(_("The proposed date cannot be in the past"))
	doc = frappe.get_doc({"doctype": "Subcontract Work Progress", "subcontract_work_order": swo.name, "progress_date": nowdate(),
		"inspection_status": "Inspection Requested", "proposed_inspection_date": proposed_date, "inspection_location": location,
		"subcontractor_remarks": remarks, "items": [{"swo_item": r["swo_item"], "reported_qty": r["reported_qty"]} for r in rows]})
	_insert(doc)
	sp.notify_staff(swo.name, _("Inspection requested on {0}").format(swo.name), doc.doctype, doc.name)
	return doc.name


# ------------------------------------------------------------------------------------------------------- materials
@frappe.whitelist()
def materials(page=1):
	acc = _acc()
	sup = acc.supplier
	start, length = _paging(page)
	reqs = frappe.get_all("Subcontract Material Request", filters={"supplier": sup}, fields=["name", "subcontract_work_order", "request_date",
		"required_by", "delivery_location", "status", "review_remarks"], order_by="creation desc", start=start, page_length=length + 1)
	for r in reqs:
		r["items"] = frappe.get_all("Subcontract Material Request Item", filters={"parent": r.name}, fields=["item_code", "item_name", "uom", "qty", "issued_qty"])
	issues = frappe.get_all("Subcontract Material Allocation", filters={"supplier": sup, "docstatus": 1}, fields=["name", "subcontract_work_order",
		"posting_date", "material_request", "received_by_subcontractor", "received_on", "shortage_reported", "receipt_remarks"],
		order_by="posting_date desc", limit=30)
	for r in issues:
		r["items"] = frappe.get_all("Subcontract Material Item", filters={"parent": r.name}, fields=["item_code", "item_name", "uom", "qty"])
	held = [{"item_code": k, **v} for k, v in _held(sup).items()]
	supplied = frappe.db.sql("""select w.name as work_order, wi.job_type, wi.description, wi.qty from `tabSubcontract Work Item` wi
		join `tabSubcontract Work Order` w on w.name = wi.parent where w.supplier = %s and w.docstatus = 1
		and wi.equipment_ownership = 'Subcontractor Supplied' and w.status not in ('Closed', 'Cancelled')""", sup, as_dict=True)
	return {"requests": reqs[:length], "more": len(reqs) > length, "issues": issues, "held": held, "own_supplied": supplied}


def _held(supplier):
	out = {}
	for w in frappe.get_all(SWO, filters={"supplier": supplier, "docstatus": 1}, pluck="name"):
		for item, b in sc.issued_balance(w).items():
			if flt(b.outstanding) > 1e-9:
				row = out.setdefault(item, {"item_name": frappe.db.get_value("Item", item, "item_name"), "qty": 0})
				row["qty"] += flt(b.outstanding)
	return out


@frappe.whitelist()
def request_options(work_order):
	"""Items the subcontractor can ask for: company stock items that were issued before on this work order, or any stock item."""
	acc = _acc()
	_own_swo(work_order, acc)
	return frappe.get_all("Item", filters={"is_stock_item": 1, "disabled": 0}, fields=["name", "item_name", "stock_uom"], order_by="item_name", limit=500)


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=30, seconds=600)
def create_material_request(work_order, items, required_by, delivery_location=None, remarks=None):
	acc = _acc(write=True)
	swo = _own_swo(work_order, acc)
	rows = [{"item_code": r.get("item_code"), "qty": flt(r.get("qty")), "remarks": r.get("remarks")} for r in _rows(items) if flt(r.get("qty"))]
	if not rows:
		frappe.throw(_("Add at least one item"))
	doc = frappe.get_doc({"doctype": "Subcontract Material Request", "subcontract_work_order": swo.name, "required_by": required_by,
		"delivery_location": delivery_location, "remarks": remarks, "items": rows})
	_insert(doc)
	doc.flags.workflow_move = doc.flags.ignore_permissions = True
	doc.status = "Submitted"
	doc.save()
	sp.notify_staff(swo.name, _("Material request {0} for {1}").format(doc.name, swo.name), doc.doctype, doc.name)
	return doc.name


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=30, seconds=600)
def confirm_receipt(allocation, shortage=0, remarks=None):
	acc = _acc(write=True)
	doc = sp.own("Subcontract Material Allocation", allocation, acc)
	if doc.docstatus != 1:
		frappe.throw(_("This issue is not posted"))
	if doc.received_by_subcontractor:
		frappe.throw(_("Receipt is already confirmed"))
	if cint(shortage) and not (remarks or "").strip():
		frappe.throw(_("Describe the shortage"))
	doc.db_set({"received_by_subcontractor": 1, "received_on": now_datetime(), "receipt_confirmed_by": frappe.session.user,
		"shortage_reported": cint(shortage), "receipt_remarks": remarks})
	if cint(shortage):
		sp.notify_staff(doc.subcontract_work_order, _("Shortage reported on {0}").format(doc.name), doc.doctype, doc.name)
	return True


# ------------------------------------------------------------------------------------------------------- variations and claims
VARIATION_TYPES = ("Extra Work", "Quantity Variation", "Rate Revision", "Time Extension", "Delay Claim", "Material Shortage Claim",
	"Additional Material", "Other Claim")


@frappe.whitelist()
def variations(page=1):
	acc = _acc()
	start, length = _paging(page)
	rows = frappe.get_all("Subcontract Variation", filters={"supplier": acc.supplier}, fields=["name", "subcontract_work_order", "variation_type",
		"request_date", "status", "description", "claimed_amount", "approved_amount", "value_change", "new_completion_date", "external_remarks"],
		order_by="creation desc", start=start, page_length=length + 1)
	return {"rows": [_strip(dict(r), acc, ("claimed_amount", "approved_amount", "value_change")) for r in rows[:length]], "more": len(rows) > length,
		"types": VARIATION_TYPES}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=20, seconds=600)
def submit_variation(work_order, variation_type, description, items=None, new_completion_date=None, claimed_amount=None):
	acc = _acc(write=True)
	swo = _own_swo(work_order, acc)
	if variation_type not in VARIATION_TYPES:
		frappe.throw(_("Choose a variation type"))
	if variation_type in ("Rate Revision", "Delay Claim", "Material Shortage Claim", "Other Claim", "Extra Work", "Additional Material") and not _commercial(acc):
		frappe.throw(_("Your access does not include commercial requests"), frappe.PermissionError)
	valid = {r.name: r for r in swo.items}
	rows = []
	for r in _rows(items):
		if r.get("swo_item") and r["swo_item"] not in valid:
			frappe.throw(_("A line does not belong to work order {0}").format(swo.name))
		rows.append({"swo_item": r.get("swo_item"), "job_type": r.get("job_type") or (valid[r["swo_item"]].job_type if r.get("swo_item") else None),
			"description": r.get("description"), "qty": flt(r.get("qty")), "rate": flt(r.get("rate")), "uom": r.get("uom"),
			"work_category": r.get("work_category") or "Labour"})
	doc = frappe.get_doc({"doctype": "Subcontract Variation", "subcontract_work_order": swo.name, "variation_type": variation_type,
		"description": description, "items": rows, "new_completion_date": new_completion_date or None, "claimed_amount": flt(claimed_amount)})
	_insert(doc)
	doc.flags.workflow_move = doc.flags.ignore_permissions = True
	doc.status = "Submitted"
	doc.save()
	sp.notify_staff(swo.name, _("{0} requested on {1}").format(_(variation_type), swo.name), doc.doctype, doc.name)
	return doc.name


# ------------------------------------------------------------------------------------------------------- invoices and payments
@frappe.whitelist()
def billable(work_order):
	acc = _acc(sp.COMMERCIAL)
	swo = _own_swo(work_order, acc)
	from thinknxg_rental.subcontracting.doctype.subcontractor_invoice_submission.subcontractor_invoice_submission import billable_lines

	rows = [{"swo_item": r.name, "job_type": r.job_type, "description": r.description, "rate": r.rate, "billable_qty": r.billable_qty,
		"accepted_qty": r.accepted_qty, "invoiced_qty": r.invoiced_qty} for r in billable_lines(swo.name).values()]
	return {"rows": rows, "final_allowed": swo.status == "Verified", "retention_percentage": swo.retention_percentage}


@frappe.whitelist()
def invoices(page=1):
	acc = _acc(sp.COMMERCIAL)
	start, length = _paging(page)
	rows = frappe.get_all("Subcontractor Invoice Submission", filters={"supplier": acc.supplier}, fields=["name", "subcontract_work_order",
		"supplier_invoice_no", "supplier_invoice_date", "bill_type", "status", "total_claimed", "review_remarks", "purchase_invoice"],
		order_by="creation desc", start=start, page_length=length + 1)
	for r in rows:
		if r.purchase_invoice:
			pi = frappe.db.get_value("Purchase Invoice", r.purchase_invoice, ["grand_total", "outstanding_amount", "status", "due_date", "docstatus"], as_dict=True)
			r.update(payable=pi.grand_total, outstanding=pi.outstanding_amount, payment_status=pi.status, due_date=pi.due_date) if pi and pi.docstatus == 1 else None
	return {"rows": rows[:length], "more": len(rows) > length}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=20, seconds=600)
def submit_invoice(work_order, supplier_invoice_no, supplier_invoice_date, items, bill_type="Running Bill", remarks=None):
	acc = _acc(sp.COMMERCIAL, write=True)
	swo = _own_swo(work_order, acc)
	if bill_type not in ("Running Bill", "Final Bill"):
		frappe.throw(_("Choose Running Bill or Final Bill"))
	if getdate(supplier_invoice_date) > getdate(nowdate()):
		frappe.throw(_("The invoice date cannot be in the future"))
	rows = _item_rows(swo, items, "qty")
	if not rows:
		frappe.throw(_("Enter the quantity you invoice"))
	doc = frappe.get_doc({"doctype": "Subcontractor Invoice Submission", "subcontract_work_order": swo.name, "supplier_invoice_no": supplier_invoice_no,
		"supplier_invoice_date": supplier_invoice_date, "bill_type": bill_type, "remarks": remarks,
		"items": [{"swo_item": r["swo_item"], "qty": r["qty"]} for r in rows]})
	_insert(doc)
	doc.flags.workflow_move = doc.flags.ignore_permissions = True
	doc.status = "Submitted"
	doc.save()
	sp.notify_staff(swo.name, _("Invoice {0} submitted for {1}").format(supplier_invoice_no, swo.name), doc.doctype, doc.name)
	return doc.name


@frappe.whitelist()
def payments():
	acc = _acc(sp.COMMERCIAL)
	sup = acc.supplier
	invoices = frappe.get_all("Purchase Invoice", filters={"supplier": sup, "docstatus": 1, "subcontract_work_order": ["is", "set"]},
		fields=["name", "bill_no", "posting_date", "due_date", "subcontract_work_order", "grand_total", "outstanding_amount", "status", "total_advance"],
		order_by="posting_date desc", limit=100)
	pays = frappe.db.sql("""select pe.name, pe.posting_date, pe.paid_amount, pe.reference_no, pe.reference_date, pe.mode_of_payment,
		pe.subcontract_work_order, pe.unallocated_amount from `tabPayment Entry` pe where pe.party_type = 'Supplier' and pe.party = %s
		and pe.docstatus = 1 and pe.payment_type = 'Pay' order by pe.posting_date desc limit 100""", sup, as_dict=True)
	retention = flt(frappe.db.sql("""select sum(retention_amount) from `tabSubcontract Settlement` where supplier = %s and docstatus = 1""", sup)[0][0])
	advances = flt(frappe.db.sql("""select sum(unallocated_amount) from `tabPayment Entry` where party_type = 'Supplier' and party = %s and docstatus = 1
		and ifnull(subcontract_work_order, '') != ''""", sup)[0][0])
	return {"invoices": invoices, "payments": pays, "summary": {"outstanding": sum(flt(i.outstanding_amount) for i in invoices),
		"paid": sum(flt(p.paid_amount) for p in pays), "retention_held": retention, "unadjusted_advance": advances}}


@frappe.whitelist()
def payment_advice(name):
	acc = _acc(sp.COMMERCIAL)
	pe = frappe.db.get_value("Payment Entry", name, ["party_type", "party", "docstatus"], as_dict=True)
	if not pe or pe.party_type != "Supplier" or pe.party != acc.supplier or pe.docstatus != 1:
		raise frappe.PermissionError(_("Payment {0} was not found").format(name))
	frappe.local.response.filename = f"{name}.pdf"
	frappe.local.response.filecontent = frappe.get_print("Payment Entry", name, as_pdf=True)
	frappe.local.response.type = "pdf"


# ------------------------------------------------------------------------------------------------------- messages
def _messages(supplier, work_order=None, limit=50):
	filters = {"supplier": supplier}
	if work_order:
		filters["subcontract_work_order"] = work_order
	return frappe.get_all("Subcontract Message", filters=filters, fields=["name", "subcontract_work_order", "direction", "subject", "message",
		"attachment", "sender_name", "creation", "read_by_supplier"], order_by="creation desc", limit=limit)


@frappe.whitelist()
def messages(work_order=None):
	acc = _acc()
	if work_order:
		_own_swo(work_order, acc)
	rows = _messages(acc.supplier, work_order)
	threads = frappe.db.sql("""select subcontract_work_order, count(*) as n, max(creation) as last,
		sum(case when read_by_supplier = 0 and direction != 'From Subcontractor' then 1 else 0 end) as unread
		from `tabSubcontract Message` where supplier = %s group by subcontract_work_order order by last desc""", acc.supplier, as_dict=True)
	return {"rows": rows, "threads": threads}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=60, seconds=600)
def post_message(message, work_order=None, subject=None):
	acc = _acc(write=True)
	if work_order:
		_own_swo(work_order, acc)
	if len(message or "") > 5000:
		frappe.throw(_("The message is too long"))
	doc = frappe.get_doc({"doctype": "Subcontract Message", "supplier": acc.supplier, "subcontract_work_order": work_order or None,
		"direction": "From Subcontractor", "subject": subject, "message": message, "read_by_supplier": 1})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


@frappe.whitelist(methods=["POST"])
def mark_messages_read(work_order=None):
	acc = _acc()
	filters = {"supplier": acc.supplier, "direction": ["!=", "From Subcontractor"], "read_by_supplier": 0}
	if work_order:
		filters["subcontract_work_order"] = work_order
	for n in frappe.get_all("Subcontract Message", filters=filters, pluck="name"):
		frappe.db.set_value("Subcontract Message", n, "read_by_supplier", 1, update_modified=False)
	return True


# ------------------------------------------------------------------------------------------------------- notifications
@frappe.whitelist()
def notifications():
	_acc()
	rows = frappe.get_all("Notification Log", filters={"for_user": frappe.session.user}, fields=["name", "subject", "document_type", "document_name",
		"read", "creation"], order_by="creation desc", limit=30)
	return {"rows": rows, "unread": len([r for r in rows if not r.read])}


@frappe.whitelist(methods=["POST"])
def mark_notifications_read():
	_acc()
	frappe.db.sql("update `tabNotification Log` set `read` = 1 where for_user = %s and `read` = 0", frappe.session.user)
	return True


# ------------------------------------------------------------------------------------------------------- documents and profile
@frappe.whitelist()
def profile():
	acc = _acc()
	s = frappe.db.get_value("Supplier", acc.supplier, ["supplier_name", "tax_id", "email_id", "mobile_no", "website", "business_classification",
		"specializations", "service_areas", "operating_locations", "subcontractor_approval_status", "subcontractor_type"], as_dict=True)
	docs = frappe.get_all("Subcontractor Compliance Document", filters={"parent": acc.supplier, "parenttype": "Supplier"},
		fields=["name", "document_type", "document_no", "issue_date", "expiry_date", "verified", "attachment"], order_by="idx")
	for d in docs:
		d.compliance_status = sc.compliance_status(d.expiry_date)
		d.attachment = bool(d.attachment)
	agreements = frappe.get_all("Subcontract Agreement", filters={"supplier": acc.supplier, "docstatus": 1},
		fields=["name", "agreement_type", "title", "start_date", "end_date", "status"], order_by="start_date desc")
	contacts = frappe.get_all("Subcontractor Portal Access", filters={"supplier": acc.supplier}, fields=["full_name", "email", "access_level", "enabled"])
	return {"supplier": s, "documents": docs, "agreements": agreements, "contacts": contacts, "access_level": acc.access_level}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=20, seconds=600)
def add_compliance_document(document_type, document_no=None, issue_date=None, expiry_date=None):
	"""A renewed or new compliance document from the subcontractor: added unverified, staff verify it in the desk."""
	acc = _acc(write=True)
	sup = frappe.get_doc("Supplier", acc.supplier)
	options = frappe.get_meta("Subcontractor Compliance Document").get_field("document_type").options.split("\n")
	if document_type not in options:
		frappe.throw(_("Choose a document type"))
	row = sup.append("compliance_documents", {"document_type": document_type, "document_no": document_no, "issue_date": issue_date or None,
		"expiry_date": expiry_date or None, "verified": 0, "remarks": _("Uploaded through the portal by {0}").format(frappe.session.user)})
	sup.flags.ignore_permissions = True
	sup.save()
	return row.name


# ------------------------------------------------------------------------------------------------------- files
def _files(doctype, name):
	return frappe.get_all("File", filters={"attached_to_doctype": doctype, "attached_to_name": name}, fields=["name", "file_name", "creation"],
		order_by="creation desc")


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=60, seconds=600)
def upload(doctype, name):
	"""Attach a photo or document to one of this subcontractor's own records (private file)."""
	acc = _acc(write=True)
	if doctype not in ATTACHABLE and doctype != "Supplier Compliance":
		raise frappe.PermissionError(_("Files cannot be attached here"))
	f = frappe.request.files.get("file") if frappe.request and frappe.request.files else None
	if not f:
		frappe.throw(_("Choose a file"))
	content = f.stream.read()
	ext = (f.filename.rsplit(".", 1)[-1] if "." in f.filename else "").lower()
	if ext not in ALLOWED_EXT:
		frappe.throw(_("Upload a PDF, image or office document"))
	if len(content) > MAX_UPLOAD:
		frappe.throw(_("The file is larger than 10 MB"))
	if doctype == "Supplier Compliance":
		row = frappe.db.get_value("Subcontractor Compliance Document", name, ["parent", "parenttype"], as_dict=True)
		if not row or row.parenttype != "Supplier" or row.parent != acc.supplier:
			raise frappe.PermissionError(_("Document not found"))
		target_dt, target_name = "Supplier", acc.supplier
	else:
		field = "supplier"
		sp.own(doctype, name, acc, field)
		target_dt, target_name = doctype, name
	from frappe.utils.file_manager import save_file

	saved = save_file(f.filename, content, target_dt, target_name, is_private=1)
	if doctype == "Supplier Compliance":
		frappe.db.set_value("Subcontractor Compliance Document", name, "attachment", saved.file_url)
	return {"name": saved.name, "file_name": saved.file_name}


@frappe.whitelist()
def download(file):
	acc = _acc()
	f = frappe.db.get_value("File", file, ["attached_to_doctype", "attached_to_name", "file_name", "file_url"], as_dict=True)
	if not f:
		raise frappe.PermissionError(_("File not found"))
	if f.attached_to_doctype == "Supplier":
		ok = f.attached_to_name == acc.supplier
	elif f.attached_to_doctype in ATTACHABLE:
		ok = frappe.db.get_value(f.attached_to_doctype, f.attached_to_name, "supplier") == acc.supplier
	else:
		ok = False
	if not ok:
		raise frappe.PermissionError(_("File not found"))
	doc = frappe.get_doc("File", file)
	frappe.local.response.filename = f.file_name
	frappe.local.response.filecontent = doc.get_content()
	frappe.local.response.type = "download"
