"""Admin portal data entry (/rental/admin/entries, /rental/admin/entry).

A short, fixed set of documents can be listed, created, edited and submitted from the admin portal:
Lead, Quotation, Hire Order, Hire Order Contract, Rental Contract, Hire Delivery Order and Hire
Off-Hire Note. The portal does not keep anything of its own. Every save goes through the real
DocType (frappe.get_doc / save / submit, with the user's own permissions), so the entry is the
ERPNext document: the same validations, numbering, stock entries and ledger as the desk form.

ENTRY_TYPES says, per document, which header fields and item columns the portal shows. Labels,
field types, options and read-only flags come from the DocType meta, so a renamed label in the
DocType shows up here too. A field the site does not have (an older ERPNext Lead, say) is skipped.
"""
import json
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import cint, flt

HIRE = ["Material Hire", "Hire Order Contract"]
MH = ["Material Hire"]
HOC = ["Hire Order Contract"]
LIVE_CONTRACT = {"docstatus": 1, "status": ["not in", ["Completed", "Cancelled"]]}
STOCK_ITEM = {"is_stock_item": 1, "disabled": 0}
ITEM_FETCH = {"item_name": "item_name", "uom": "stock_uom"}

# Header field: "fieldname" or {fieldname, filters ("$field" = value of that field on the form),
# show_if {field: [values]}, fetch {target: source field on the linked record}, wide}.
# Item column: the same, plus w (relative width; the columns share the full table width) and ro.
ENTRY_TYPES = {
	"lead": dict(
		doctype="Lead",
		label="Lead",
		plural="Leads",
		title_field="lead_name",
		search_fields=["lead_name", "company_name", "email_id", "mobile_no"],
		list_columns=[("lead_name", "Name"), ("company_name", "Company"), ("deal_type", "Deal type"), ("mobile_no", "Mobile")],
		header=[
			"first_name", "last_name", "company_name", "deal_type", "email_id", "mobile_no", "phone",
			"source", "territory", "status", "company",
		],
		next=[
			dict(label="Create Quotation", target="quotation", method="thinknxg_rental.services.deal_flow.make_quotation_from_lead",
				when={"docstatus": [0], "deal_type": HIRE + ["Material Sale"]}),
		],
	),
	"quotation": dict(
		doctype="Quotation",
		label="Quotation",
		plural="Quotations",
		title_field="customer_name",
		search_fields=["customer_name", "party_name"],
		list_columns=[("customer_name", "Party"), ("deal_type", "Deal type"), ("transaction_date", "Date"), ("grand_total", "Total")],
		header=[
			"quotation_to",
			{"fieldname": "party_name", "fetch": {}},
			"deal_type", "transaction_date", "valid_till", "company",
			{"fieldname": "nxg_required_from", "show_if": {"deal_type": MH}},
			{"fieldname": "nxg_expected_return_date", "show_if": {"deal_type": MH}},
			{"fieldname": "nxg_default_rate_basis", "show_if": {"deal_type": MH}},
			{"fieldname": "nxg_billing_cycle", "show_if": {"deal_type": MH}},
		],
		tables=[
			dict(fieldname="items", columns=[
				{"fieldname": "item_code", "w": 3, "filters": {"disabled": 0}, "fetch": ITEM_FETCH},
				{"fieldname": "item_name", "w": 3, "ro": 1},
				{"fieldname": "nxg_length", "w": 1, "show_if": {"deal_type": HOC}},
				{"fieldname": "nxg_breadth", "w": 1, "show_if": {"deal_type": HOC}},
				{"fieldname": "nxg_height", "w": 1, "show_if": {"deal_type": HOC}},
				{"fieldname": "nxg_duration", "w": 1, "show_if": {"deal_type": HOC}},
				{"fieldname": "nxg_period", "w": 1.3, "show_if": {"deal_type": HOC}},
				{"fieldname": "qty", "w": 1.2},
				{"fieldname": "uom", "w": 1, "ro": 1},
				{"fieldname": "rate", "w": 1.5},
				{"fieldname": "nxg_rate_basis", "w": 1.3, "show_if": {"deal_type": MH}},
				{"fieldname": "nxg_hire_days", "w": 1, "show_if": {"deal_type": MH}},
				{"fieldname": "nxg_included_days", "w": 1.1, "show_if": {"deal_type": HIRE}},
				{"fieldname": "nxg_excess_basis", "w": 1.3, "show_if": {"deal_type": HIRE}},
				{"fieldname": "nxg_excess_rate", "w": 1.4, "show_if": {"deal_type": HIRE}},
				{"fieldname": "nxg_rate_basis_amount", "w": 1.5, "ro": 1, "show_if": {"deal_type": MH}},
				{"fieldname": "nxg_estimated_amount", "w": 1.5, "ro": 1, "show_if": {"deal_type": MH}},
				{"fieldname": "amount", "w": 1.5, "ro": 1},
			]),
		],
		totals=["total_qty", "net_total", "total_taxes_and_charges", "grand_total"],
		next=[
			dict(label="Create Hire Order", target="hire-order", method="thinknxg_rental.services.deal_flow.make_hire_order_from_quotation",
				when={"docstatus": [1], "deal_type": MH}),
			dict(label="Create Hire Order Contract", target="hire-order-contract",
				method="thinknxg_rental.services.deal_flow.make_hire_order_contract_from_quotation", when={"docstatus": [1], "deal_type": HOC}),
		],
	),
	"hire-order": dict(
		doctype="Hire Order",
		label="Hire Order",
		plural="Hire Orders",
		title_field="customer_name",
		search_fields=["customer_name", "customer", "rental_site", "customer_reference"],
		list_columns=[("customer_name", "Customer"), ("rental_site", "Site"), ("required_from", "From"), ("estimated_amount", "Estimate")],
		header=[
			{"fieldname": "customer", "fetch": {"customer_name": "customer_name"}},
			{"fieldname": "rental_site", "filters": {"customer": "$customer", "disabled": 0}},
			"company", "order_date", "required_from", "expected_return_date", "rate_basis", "billing_cycle",
			"customer_reference", "quotation", "sales_person", "payment_terms_template",
			{"fieldname": "remarks", "wide": 1},
		],
		tables=[
			dict(fieldname="items", columns=[
				{"fieldname": "item_code", "w": 3, "filters": STOCK_ITEM, "fetch": ITEM_FETCH},
				{"fieldname": "item_name", "w": 3, "ro": 1},
				{"fieldname": "uom", "w": 1, "ro": 1},
				{"fieldname": "qty", "w": 1.2},
				{"fieldname": "rate_basis", "w": 1.3},
				{"fieldname": "rate", "w": 1.4},
				{"fieldname": "expected_hire_days", "w": 1},
				{"fieldname": "security_deposit_rate", "w": 1.4},
				{"fieldname": "available_qty", "w": 1.2, "ro": 1},
				{"fieldname": "shortfall_qty", "w": 1.3, "ro": 1},
				{"fieldname": "estimated_amount", "w": 1.5, "ro": 1},
			]),
		],
		totals=["total_qty", "estimated_amount", "total_security_deposit", "total_shortfall_qty"],
		next=[
			dict(label="Create Rental Contract", target="rental-contract",
				method="thinknxg_rental.thinknxg_rental.doctype.hire_order.hire_order.make_contract", when={"docstatus": [1], "status": ["Open"]}),
		],
	),
	"hire-order-contract": dict(
		doctype="Hire Order Contract",
		label="Hire Order Contract",
		plural="Hire Order Contracts",
		title_field="customer_name",
		search_fields=["customer_name", "customer", "rental_site", "customer_reference"],
		list_columns=[("customer_name", "Customer"), ("rental_site", "Site"), ("required_from", "Erection"), ("total_contract_amount", "Contract")],
		header=[
			{"fieldname": "customer", "fetch": {"customer_name": "customer_name"}},
			{"fieldname": "rental_site", "filters": {"customer": "$customer", "disabled": 0}},
			"company", "order_date", "required_from", "customer_reference", "customer_reference_date",
			"contract_charge_billing", "taxes_and_charges", "payment_terms_template",
			{"fieldname": "remarks", "wide": 1},
		],
		tables=[
			dict(fieldname="items", columns=[
				{"fieldname": "job_type", "w": 2.6, "link": "Job Type", "filters": {"disabled": 0}, "fetch": {"job_type_name": "job_type_name"}},
				{"fieldname": "job_type_name", "w": 2.6, "ro": 1},
				{"fieldname": "location", "w": 2},
				{"fieldname": "nxg_length", "w": 1},
				{"fieldname": "nxg_breadth", "w": 1},
				{"fieldname": "nxg_height", "w": 1},
				{"fieldname": "nxg_duration", "w": 1},
				{"fieldname": "nxg_period", "w": 1.3},
				{"fieldname": "qty", "w": 1},
				{"fieldname": "included_days", "w": 1.1},
				{"fieldname": "contract_rate", "w": 1.4},
				{"fieldname": "excess_rate_basis", "w": 1.3},
				{"fieldname": "excess_rate", "w": 1.4},
				{"fieldname": "contract_amount", "w": 1.5, "ro": 1},
			]),
			# Built from the job types on first save; change it in the desk if the job needs it.
			dict(fieldname="materials", readonly=1, columns=[
				{"fieldname": "job_type", "w": 2.5},
				{"fieldname": "item_code", "w": 2.5},
				{"fieldname": "item_name", "w": 3},
				{"fieldname": "uom", "w": 1},
				{"fieldname": "qty_per_job", "w": 1.2},
				{"fieldname": "qty", "w": 1.2},
				{"fieldname": "available_qty", "w": 1.2},
				{"fieldname": "shortfall_qty", "w": 1.2},
			]),
		],
		totals=["total_jobs", "total_contract_amount"],
		next=[
			dict(label="Create Rental Contract", target="rental-contract",
				method="thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract.make_rental_contract",
				when={"docstatus": [1], "status": ["Open"]}),
		],
	),
	"rental-contract": dict(
		doctype="Rental Contract",
		label="Rental Contract",
		plural="Rental Contracts",
		title_field="customer_name",
		search_fields=["customer_name", "customer", "rental_site", "source_document"],
		list_columns=[("customer_name", "Customer"), ("rental_site", "Site"), ("start_date", "Start"), ("end_date", "End")],
		header=[
			{"fieldname": "customer", "fetch": {"customer_name": "customer_name"}},
			{"fieldname": "rental_site", "filters": {"customer": "$customer", "disabled": 0}},
			"company", "source_type", {"fieldname": "source_document", "filters": {"docstatus": 1, "customer": "$customer"}},
			"contract_date", "start_date", "end_date", "billing_cycle", "minimum_hire_days", "grace_days",
			"security_deposit", "payment_terms_template",
			{"fieldname": "remarks", "wide": 1},
		],
		tables=[
			dict(fieldname="items", columns=[
				{"fieldname": "item_code", "w": 3, "filters": STOCK_ITEM, "fetch": ITEM_FETCH},
				{"fieldname": "item_name", "w": 3, "ro": 1},
				{"fieldname": "uom", "w": 1, "ro": 1},
				{"fieldname": "qty", "w": 1.2},
				{"fieldname": "rate_basis", "w": 1.3},
				{"fieldname": "rate", "w": 1.4},
				{"fieldname": "dispatched_qty", "w": 1.2, "ro": 1},
				{"fieldname": "returned_qty", "w": 1.2, "ro": 1},
				{"fieldname": "at_site_qty", "w": 1.2, "ro": 1},
				{"fieldname": "pending_qty", "w": 1.2, "ro": 1},
			]),
		],
		totals=["total_contract_qty", "total_dispatched_qty", "total_at_site_qty", "total_returned_qty"],
		next=[
			dict(label="New Delivery Order", target="delivery-order", prefill={"rental_contract": "name"}, when={"docstatus": [1], "status": ["Active", "On Hire"]}),
			dict(label="New Off-Hire Note", target="off-hire-note", prefill={"rental_contract": "name"}, when={"docstatus": [1], "status": ["On Hire", "Active"]}),
		],
	),
	"delivery-order": dict(
		doctype="Hire Delivery Order",
		label="Delivery Order",
		plural="Delivery Orders",
		title_field="customer_name",
		search_fields=["customer_name", "rental_contract", "rental_site", "vehicle_no", "dispatch_reference"],
		list_columns=[("customer_name", "Customer"), ("rental_contract", "Contract"), ("posting_date", "Dispatch date"), ("total_qty", "Qty")],
		prefill=["rental_contract"],
		header=[
			{"fieldname": "rental_contract", "filters": LIVE_CONTRACT, "fetch": {"customer_name": "customer_name", "rental_site": "rental_site"}},
			{"fieldname": "customer_name", "ro": 1},
			{"fieldname": "rental_site", "ro": 1},
			"posting_date", "vehicle_no", "driver_name", "driver_phone", "transporter", "dispatch_reference",
			{"fieldname": "remarks", "wide": 1},
		],
		tables=[
			dict(fieldname="items", columns=[
				{"fieldname": "item_code", "w": 2.6, "filters": STOCK_ITEM, "fetch": ITEM_FETCH},
				{"fieldname": "item_name", "w": 3, "ro": 1},
				{"fieldname": "uom", "w": 1, "ro": 1},
				{"fieldname": "ownership", "w": 1.3},
				{"fieldname": "cross_hire_order", "w": 2, "filters": {"docstatus": 1, "status": ["!=", "Completed"]}},
				{"fieldname": "source_warehouse", "w": 2.2, "filters": {"is_group": 0}},
				{"fieldname": "contract_qty", "w": 1.2, "ro": 1},
				{"fieldname": "previously_delivered", "w": 1.3, "ro": 1},
				{"fieldname": "balance_to_deliver", "w": 1.3, "ro": 1},
				{"fieldname": "qty", "w": 1.2},
			]),
		],
		totals=["total_qty", "total_weight"],
		fill=dict(label="Get items from contract", needs="rental_contract", table="items",
			method="thinknxg_rental.thinknxg_rental.doctype.hire_delivery_order.hire_delivery_order.get_dispatch_items"),
		next=[
			dict(label="New Off-Hire Note", target="off-hire-note", prefill={"rental_contract": "rental_contract"}, when={"docstatus": [1]}),
		],
	),
	"off-hire-note": dict(
		doctype="Hire Off-Hire Note",
		label="Off-Hire Note",
		plural="Off-Hire Notes",
		title_field="customer_name",
		search_fields=["customer_name", "rental_contract", "rental_site", "vehicle_no"],
		list_columns=[("customer_name", "Customer"), ("rental_contract", "Contract"), ("return_date", "Returned"), ("total_returned_qty", "Qty")],
		prefill=["rental_contract"],
		header=[
			{"fieldname": "rental_contract", "filters": {"docstatus": 1, "status": ["in", ["On Hire", "Active"]]},
				"fetch": {"customer_name": "customer_name", "rental_site": "rental_site", "grace_days": "grace_days"}},
			{"fieldname": "customer_name", "ro": 1},
			{"fieldname": "rental_site", "ro": 1},
			"off_hire_type", "off_hire_date", "return_date", "grace_days", "reason", "vehicle_no", "driver_name",
			{"fieldname": "remarks", "wide": 1},
		],
		tables=[
			dict(fieldname="items", columns=[
				{"fieldname": "item_code", "w": 2.6, "filters": STOCK_ITEM, "fetch": ITEM_FETCH},
				{"fieldname": "item_name", "w": 3, "ro": 1},
				{"fieldname": "uom", "w": 1, "ro": 1},
				{"fieldname": "ownership", "w": 1.3},
				{"fieldname": "cross_hire_order", "w": 2},
				{"fieldname": "at_site_qty", "w": 1.2, "ro": 1},
				{"fieldname": "returned_qty", "w": 1.2},
				{"fieldname": "lost_qty", "w": 1.2},
				{"fieldname": "pending_qty", "w": 1.3, "ro": 1},
				{"fieldname": "remarks", "w": 2},
			]),
		],
		totals=["total_returned_qty", "total_lost_qty"],
		fill=dict(label="Get items at site", needs="rental_contract", table="items",
			method="thinknxg_rental.thinknxg_rental.doctype.hire_off_hire_note.hire_off_hire_note.get_items_at_site"),
	),
}

# Never taken from the browser: frappe sets these itself.
PROTECTED = {
	"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx", "doctype",
	"parent", "parentfield", "parenttype", "amended_from", "naming_series",
}
INPUT_TYPES = {
	"Data", "Small Text", "Text", "Long Text", "Text Editor", "Date", "Datetime", "Time", "Int", "Float",
	"Currency", "Percent", "Select", "Link", "Dynamic Link", "Check", "Phone",
}


def get_entry_type(key):
	cfg = ENTRY_TYPES.get(key)
	if not cfg:
		raise frappe.DoesNotExistError(_("Unknown entry type"))
	return cfg


def entry_url(key, name=None, **args):
	query = {"type": key}
	if name:
		query["name"] = name
	query.update({k: v for k, v in args.items() if v})
	return "/rental/admin/entry?" + "&".join(f"{k}={quote(str(v))}" for k, v in query.items())


def entry_nav():
	"""Entry menus the user may read, in menu order."""
	return [
		frappe._dict(key=key, route=f"/rental/admin/entries?type={key}", label=_(cfg["plural"]))
		for key, cfg in ENTRY_TYPES.items()
		if frappe.has_permission(cfg["doctype"], "read")
	]


# ----------------------------------------------------------------------------- field specs
def _spec(meta, item, table=False):
	item = {"fieldname": item} if isinstance(item, str) else dict(item)
	df = meta.get_field(item["fieldname"])
	if not df or df.fieldtype not in INPUT_TYPES:
		return None
	spec = {
		"fieldname": df.fieldname,
		"label": _(item.get("label") or df.label),
		"fieldtype": df.fieldtype,
		"options": item.get("link") or df.options or "",
		"reqd": cint(df.reqd),
		"ro": cint(item.get("ro", df.read_only)),
		"filters": item.get("filters") or {},
		"fetch": item.get("fetch") or {},
		"show_if": item.get("show_if") or {},
	}
	if df.fieldtype == "Select":
		spec["choices"] = [o for o in (df.options or "").split("\n")]
	if table:
		spec["w"] = flt(item.get("w")) or 1
	else:
		spec["wide"] = cint(item.get("wide")) or df.fieldtype in ("Small Text", "Text", "Long Text", "Text Editor")
	return spec


def get_form_specs(cfg):
	meta = frappe.get_meta(cfg["doctype"])
	header = [s for s in (_spec(meta, f) for f in cfg["header"]) if s]
	tables = []
	for t in cfg.get("tables", []):
		df = meta.get_field(t["fieldname"])
		if not df:
			continue
		child = frappe.get_meta(df.options)
		columns = [s for s in (_spec(child, c, table=True) for c in t["columns"]) if s]
		tables.append({"fieldname": df.fieldname, "label": _(df.label), "readonly": cint(t.get("readonly")), "columns": columns})
	totals = []
	for f in cfg.get("totals", []):
		df = meta.get_field(f)
		if df:
			totals.append({"fieldname": f, "label": _(df.label), "fieldtype": df.fieldtype})
	return header, tables, totals


def _clean(row):
	return {k: v for k, v in row.items() if not k.startswith("_") and k not in PROTECTED}


def _doc_for_browser(doc, keep_child_names=True):
	out = frappe.parse_json(frappe.as_json(doc.as_dict(convert_dates_to_str=True)))
	for key, value in list(out.items()):
		if isinstance(value, list):
			rows = []
			for r in value:
				name = r.get("name") if keep_child_names else None
				r = _clean(r)
				if name:
					r["name"] = name
				rows.append(r)
			out[key] = rows
	return out


def _matches(when, doc):
	for field, values in (when or {}).items():
		if doc.get(field) not in values:
			return False
	return True


def get_next_actions(key, cfg, doc):
	actions = []
	if doc.is_new():
		return actions
	for i, a in enumerate(cfg.get("next", [])):
		target = ENTRY_TYPES[a["target"]]
		if not _matches(a.get("when"), doc) or not frappe.has_permission(target["doctype"], "create"):
			continue
		if a.get("method"):
			actions.append({"label": _(a["label"]), "make": f"{key}:{i}", "source": doc.name})
		else:
			actions.append({"label": _(a["label"]), "url": entry_url(a["target"], **{k: doc.get(v) for k, v in a["prefill"].items()})})
	return actions


def _mapped(make, source):
	"""The unsaved document an existing mapper (Lead -> Quotation, Hire Order -> Rental Contract, ...) builds."""
	src_key, _sep, idx = (make or "").partition(":")
	action = get_entry_type(src_key)["next"][cint(idx)]
	doc = frappe.get_attr(action["method"])(source_name=source)
	if isinstance(doc, dict):
		doc = frappe.get_doc(doc)
	return doc


@frappe.whitelist(methods=["POST"])
def prepare_mapped(make: str, source: str):
	"""Run the mapper once in a POST, so what it creates on the way (the Customer made from a Lead)
	is committed; the form page then maps again, finds that record and shows the unsaved document."""
	src_key, _sep, idx = make.partition(":")
	target = get_entry_type(src_key)["next"][cint(idx)]["target"]
	frappe.has_permission(ENTRY_TYPES[target]["doctype"], "create", throw=True)
	_mapped(make, source)
	return {"url": entry_url(target, make=make, source=source)}


def get_form_boot(key, name=None, form_dict=None):
	cfg = get_entry_type(key)
	form_dict = form_dict or {}
	doctype = cfg["doctype"]
	if name:
		doc = frappe.get_doc(doctype, name)
		doc.check_permission("read")
	elif form_dict.get("make") and form_dict.get("source"):
		frappe.has_permission(doctype, "create", throw=True)
		doc = _mapped(form_dict.get("make"), form_dict.get("source"))
	else:
		frappe.has_permission(doctype, "create", throw=True)
		doc = frappe.new_doc(doctype)
		for field in cfg.get("prefill", []):
			if form_dict.get(field):
				doc.set(field, form_dict.get(field))
	header, tables, totals = get_form_specs(cfg)
	data = _doc_for_browser(doc, keep_child_names=not doc.is_new())
	if doc.is_new():
		data.pop("name", None)
	editable = doc.docstatus == 0 and (doc.is_new() or doc.has_permission("write"))
	return frappe._dict(
		type=key,
		doctype=doctype,
		label=_(cfg["label"]),
		name=None if doc.is_new() else doc.name,
		is_new=doc.is_new(),
		docstatus=doc.docstatus,
		status=doc.get("status") or ("Draft" if doc.docstatus == 0 else "Submitted" if doc.docstatus == 1 else "Cancelled"),
		editable=editable,
		submittable=cint(frappe.get_meta(doctype).is_submittable),
		can_submit=bool(not doc.is_new() and doc.docstatus == 0 and frappe.get_meta(doctype).is_submittable and doc.has_permission("submit")),
		header=header,
		tables=tables,
		totals=totals,
		fill=cfg.get("fill"),
		doc=data,
		currency=doc.get("currency"),
		next=get_next_actions(key, cfg, doc),
		desk_url=f"/app/{doctype.lower().replace(' ', '-')}" + (f"/{quote(doc.name)}" if not doc.is_new() else "/new"),
		list_url=f"/rental/admin/entries?type={key}",
	)


# ----------------------------------------------------------------------------- list
def get_entries(key, view=None, search=None, limit=100):
	cfg = get_entry_type(key)
	doctype = cfg["doctype"]
	frappe.has_permission(doctype, "read", throw=True)
	meta = frappe.get_meta(doctype)
	submittable = cint(meta.is_submittable)
	filters = {}
	if submittable:
		view = view if view in ("draft", "submitted", "all") else "draft"
		if view == "draft":
			filters["docstatus"] = 0
		elif view == "submitted":
			filters["docstatus"] = 1
	else:
		view = "all"
	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = [["name", "like", like]] + [[f, "like", like] for f in cfg["search_fields"] if meta.has_field(f)]
	columns = [(f, label) for f, label in cfg["list_columns"] if meta.has_field(f)]
	fields = ["name", "docstatus", "modified"] + [f for f, _label in columns]
	if meta.has_field("status"):
		fields.append("status")
	if meta.has_field("currency"):
		fields.append("currency")
	rows = frappe.get_list(doctype, filters=filters, or_filters=or_filters, fields=list(dict.fromkeys(fields)),
		order_by="modified desc", limit_page_length=limit)
	kinds = {f: meta.get_field(f).fieldtype for f, _label in columns}
	for r in rows:
		r.status = r.get("status") or ("Draft" if r.docstatus == 0 else "Submitted" if r.docstatus == 1 else "Cancelled")
		r.url = entry_url(key, r.name)
	return frappe._dict(
		cfg=cfg, view=view, submittable=submittable, rows=rows,
		columns=[frappe._dict(fieldname=f, label=_(label), fieldtype=kinds[f]) for f, label in columns],
		can_create=frappe.has_permission(doctype, "create"),
	)


# ----------------------------------------------------------------------------- save / submit
def _merge_rows(doc, fieldname, rows):
	"""Rows from the browser over the stored rows, so fields the portal does not show are kept."""
	existing = {d.name: d.as_dict() for d in doc.get(fieldname)}
	out = []
	for r in rows or []:
		name = r.get("name")
		base = _clean(existing[name]) if name in existing else {}
		base.update(_clean(r))
		if name in existing:
			base["name"] = name
		out.append(base)
	return out


@frappe.whitelist(methods=["POST"])
def save_entry(entry_type: str, doc: str | dict, submit: int | str = 0):
	"""Insert or update the real document with the user's own permissions, optionally submit it."""
	cfg = get_entry_type(entry_type)
	doctype = cfg["doctype"]
	data = frappe.parse_json(doc) if isinstance(doc, str) else doc
	name = data.get("name")
	table_fields = {t["fieldname"] for t in cfg.get("tables", []) if not t.get("readonly")}
	if name:
		target = frappe.get_doc(doctype, name)
		if target.docstatus != 0:
			frappe.throw(_("{0} {1} is already submitted. Open it in the desk to amend it.").format(_(doctype), name))
		if data.get("modified") and str(target.modified) != str(data.get("modified")):
			frappe.throw(_("{0} was changed by someone else after you opened it. Reload the page and try again.").format(name))
		for key, value in data.items():
			if key in PROTECTED or key.startswith("_") or key == "modified":
				continue
			if isinstance(value, list):
				if key in table_fields:
					target.set(key, _merge_rows(target, key, value))
				continue
			if target.meta.has_field(key):
				target.set(key, value)
		_set_missing(target)
		target.save()
	else:
		target = frappe.new_doc(doctype)
		for key, value in data.items():
			if key in PROTECTED or key.startswith("_") or key == "modified" or not target.meta.has_field(key):
				continue
			target.set(key, [_clean(r) for r in value] if isinstance(value, list) else value)
		_set_missing(target)
		target.insert()
	if cint(submit):
		target.submit()
	return {"name": target.name, "url": entry_url(entry_type, target.name)}


def _set_missing(doc):
	# Selling documents fill currency, price list, item rates and taxes the way the desk form does.
	if doc.doctype == "Quotation" and hasattr(doc, "set_missing_values"):
		doc.set_missing_values(for_validate=not doc.is_new())


@frappe.whitelist(methods=["POST"])
def submit_entry(entry_type: str, name: str):
	cfg = get_entry_type(entry_type)
	doc = frappe.get_doc(cfg["doctype"], name)
	if doc.docstatus != 0:
		frappe.throw(_("{0} is not a draft").format(name))
	doc.submit()
	return {"name": doc.name, "url": entry_url(entry_type, doc.name)}


@frappe.whitelist()
def get_link_values(doctype: str, name: str, fields: str | list):
	"""Values the form copies from a selected link (item name and UOM, customer name, ...)."""
	if isinstance(fields, str):
		fields = json.loads(fields)
	frappe.has_permission(doctype, "read", doc=name, throw=True)
	meta = frappe.get_meta(doctype)
	fields = [f for f in fields if f == "name" or meta.has_field(f)]
	return frappe.db.get_value(doctype, name, fields, as_dict=True) or {}
