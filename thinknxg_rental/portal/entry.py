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
from urllib.parse import quote, urlencode

import frappe
from frappe import _
from frappe.utils import cint, flt

from thinknxg_rental.services.utils import BASIS_FACTOR

HIRE = ["Material Hire", "Hire Order Contract"]
MH = ["Material Hire"]
HOC = ["Hire Order Contract"]
NOT_MH = [None, "", "Material Sale", "Hire Order Contract"]
LIVE_CONTRACT = {"docstatus": 1, "status": ["not in", ["Completed", "Cancelled"]]}
STOCK_ITEM = {"is_stock_item": 1, "disabled": 0}
ITEM_FETCH = {"item_name": "item_name", "uom": "stock_uom"}
COST_CENTER = {"fieldname": "cost_center", "filters": {"company": "$company", "is_group": 0}}
# "create" puts a "New Project" button beside the field (name typed in place, company and customer from the form).
PROJECT = {"fieldname": "project", "filters": {"company": "$company"},
	"create": {"doctype": "Project", "name_field": "project_name", "label": "Project name", "defaults": {"company": "company", "customer": "customer"}}}
# "loads" refills a table when the field changes: the template's tax rows, as the desk form does.
TAX_TEMPLATE = {"fieldname": "taxes_and_charges", "filters": {"company": "$company", "disabled": 0},
	"loads": {"table": "taxes", "method": "thinknxg_rental.portal.entry.get_tax_rows"}}
TAX_TABLE = dict(fieldname="taxes", columns=[
	{"fieldname": "charge_type", "w": 2.4},
	{"fieldname": "account_head", "w": 3, "filters": {"company": "$company", "is_group": 0}},
	{"fieldname": "description", "w": 3},
	{"fieldname": "rate", "w": 1.2},
	{"fieldname": "tax_amount", "w": 1.6, "ro": 1},
	{"fieldname": "total", "w": 1.6, "ro": 1},
])
# Row values the portal works out while typing, the same way the desk form does (public/js/quotation_deal.js)
# and the save does (events/quotation.py), so the row shows what will be saved. Each rule sets "target" to the
# product of "product": a field name, or {field, per: {field, map, default}} for field / map[other field].
# "blank_one" fields count as 1 when empty. A rule with "need_all" only runs when one of its own fields changes
# and every one of them is filled, so a Qty typed by hand stays until a dimension changes.
QUOTATION_CALC = [
	# Hire Order Contract: Qty = Length x Breadth x Height, Amount = Qty x Rate x Rotation
	{"target": "qty", "product": ["nxg_length", "nxg_breadth", "nxg_height"], "need_all": 1, "show_if": {"deal_type": HOC}},
	{"target": "amount", "product": ["qty", "rate", "nxg_duration"], "blank_one": ["nxg_duration"], "show_if": {"deal_type": HOC}},
	{"target": "amount", "product": ["qty", "rate"], "show_if": {"deal_type": [None, "", "Material Sale"]}},
	# Material Hire: Qty x Rate, and Qty x Rate x Hire Days / basis days (blank Hire Days = one rate period)
	{"target": "nxg_rate_basis_amount", "product": ["qty", "rate"], "show_if": {"deal_type": MH}},
	{"target": "nxg_estimated_amount", "show_if": {"deal_type": MH}, "blank_one": ["nxg_hire_days"],
		"product": ["qty", "rate", {"field": "nxg_hire_days", "per": {"field": "nxg_rate_basis", "map": BASIS_FACTOR, "default": 30}}]},
]
SITE = {"fieldname": "rental_site", "filters": {"customer": "$customer", "disabled": 0}, "fetch": {"project": "project"}}

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
			# v15+ Lead: Source is utm_source ("source" is gone); From Customer links the lead to an existing customer
			"utm_source", "source", "customer", "territory", "status", "company",
		],
		next=[
			# once a live quotation exists the button gives way to the quotation itself (listed below)
			dict(label="Create Quotation", target="quotation", method="thinknxg_rental.services.deal_flow.make_quotation_from_lead",
				when={"docstatus": [0], "deal_type": HIRE + ["Material Sale"]}, when_fn=lambda d: not _lead_quotations(d, live=True)),
		],
		related=[
			dict(label="Quotations", rows=lambda d: _lead_quotations(d),
				columns=[("name", "Quotation", "Data"), ("deal_type", "Deal type", "Data"), ("transaction_date", "Date", "Date"),
					("grand_total", "Total", "Currency"), ("status", "Status", "Data")]),
		],
	),
	"quotation": dict(
		doctype="Quotation",
		print=True,
		label="Quotation",
		plural="Quotations",
		title_field="customer_name",
		search_fields=["customer_name", "party_name"],
		list_columns=[("customer_name", "Party"), ("deal_type", "Deal type"), ("transaction_date", "Date"), ("grand_total", "Total")],
		header=[
			"quotation_to",
			{"fieldname": "party_name", "fetch": {}},
			"deal_type", "transaction_date", "valid_till", "company", "currency", "payment_terms_template", TAX_TEMPLATE, COST_CENTER, PROJECT,
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
				{"fieldname": "nxg_included_days", "w": 1.1, "show_if": {"deal_type": HOC}},
				{"fieldname": "nxg_excess_basis", "w": 1.3, "show_if": {"deal_type": HOC}},
				{"fieldname": "nxg_excess_rate", "w": 1.4, "show_if": {"deal_type": HOC}},
				{"fieldname": "nxg_rate_basis_amount", "w": 1.5, "ro": 1, "show_if": {"deal_type": MH}},
				{"fieldname": "nxg_estimated_amount", "w": 1.5, "ro": 1, "show_if": {"deal_type": MH}},
				{"fieldname": "amount", "w": 1.5, "ro": 1, "show_if": {"deal_type": NOT_MH}},
			], calc=QUOTATION_CALC),
			TAX_TABLE,
		],
		totals=["total_qty", "net_total", "total_taxes_and_charges", "grand_total"],
		next=[
			dict(label="Create Rental Site", target="rental-site", method="thinknxg_rental.portal.entry.make_site_from_quotation",
				when={"docstatus": [0, 1], "deal_type": HIRE}, when_fn=lambda d: not _made_from("Rental Site", "nxg_quotation", d.name)),
			dict(label="Create Hire Order", target="hire-order", method="thinknxg_rental.services.deal_flow.make_hire_order_from_quotation",
				when={"docstatus": [1], "deal_type": MH}, when_fn=lambda d: not _made_from("Hire Order", "quotation", d.name)),
			dict(label="Create Hire Order Contract", target="hire-order-contract",
				method="thinknxg_rental.services.deal_flow.make_hire_order_contract_from_quotation", when={"docstatus": [1], "deal_type": HOC},
				when_fn=lambda d: not _made_from("Hire Order Contract", "quotation", d.name)),
			dict(label="Create Sales Order", target="sales-order", method="thinknxg_rental.services.deal_flow.make_sales_order_from_quotation",
				when={"docstatus": [1], "deal_type": ["Material Sale"]},
				when_fn=lambda d: d.get("status") not in ("Ordered", "Lost", "Expired") and not _quotation_sales_orders(d)),
		],
		related=[
			dict(label="Rental Sites", rows=lambda d: linked("Rental Site", {"nxg_quotation": d.name}, ["site_name", "customer_name"], "rental-site"),
				columns=[("name", "Rental Site", "Data"), ("customer_name", "Customer", "Data")]),
			dict(label="Hire Orders", rows=lambda d: linked("Hire Order", {"quotation": d.name, "docstatus": ["<", 2]}, ["rental_site", "status"], "hire-order"),
				columns=[("name", "Hire Order", "Data"), ("rental_site", "Site", "Data"), ("status", "Status", "Data")]),
			dict(label="Hire Order Contracts", rows=lambda d: linked("Hire Order Contract", {"quotation": d.name, "docstatus": ["<", 2]}, ["rental_site", "status"], "hire-order-contract"),
				columns=[("name", "Hire Order Contract", "Data"), ("rental_site", "Site", "Data"), ("status", "Status", "Data")]),
			dict(label="Sales Orders", rows=lambda d: _quotation_sales_orders(d),
				columns=[("name", "Sales Order", "Data"), ("transaction_date", "Date", "Date"), ("grand_total", "Total", "Currency"), ("status", "Status", "Data")]),
		],
	),
	"rental-site": dict(
		doctype="Rental Site",
		label="Rental Site",
		plural="Rental Sites",
		title_field="site_name",
		search_fields=["site_name", "customer_name", "customer", "location"],
		list_columns=[("customer_name", "Customer"), ("site_contact", "Site contact"), ("contact_phone", "Phone"), ("nxg_quotation", "Quotation")],
		prefill=["customer", "company"],
		header=[
			"site_name",
			{"fieldname": "customer", "fetch": {"customer_name": "customer_name"}},
			{"fieldname": "customer_name", "ro": 1},
			"company", PROJECT, {"fieldname": "address", "filters": {"link_doctype": "Customer", "link_name": "$customer"}},
			"site_contact", "contact_phone", {"fieldname": "nxg_quotation", "ro": 1}, "disabled",
			{"fieldname": "location", "wide": 1},
		],
		# The site's quotation decides the next document; a site without one starts a blank Hire Order.
		next=[
			dict(label="Create Hire Order", target="hire-order", method="thinknxg_rental.services.deal_flow.make_hire_order_from_quotation",
				source_field="nxg_quotation", args={"rental_site": "name"}, when_fn=lambda d: _quotation_is(d, MH)),
			dict(label="Create Hire Order Contract", target="hire-order-contract",
				method="thinknxg_rental.services.deal_flow.make_hire_order_contract_from_quotation",
				source_field="nxg_quotation", args={"rental_site": "name"}, when_fn=lambda d: _quotation_is(d, HOC)),
			dict(label="New Hire Order", target="hire-order", prefill={"customer": "customer", "rental_site": "name", "company": "company"},
				when={"disabled": [0, None]}, when_fn=lambda d: not d.get("nxg_quotation")),
		],
		related=[
			dict(label="Rental Contracts", rows=lambda d: linked("Rental Contract", {"rental_site": d.name, "docstatus": ["<", 2]},
				["status", "start_date", "end_date", "total_at_site_qty"], "rental-contract"),
				columns=[("name", "Rental Contract", "Data"), ("status", "Status", "Data"), ("start_date", "Start", "Date"),
					("end_date", "End", "Date"), ("total_at_site_qty", "At site", "Float")]),
		],
	),
	"hire-order": dict(
		doctype="Hire Order",
		print=True,
		label="Hire Order",
		plural="Hire Orders",
		title_field="customer_name",
		search_fields=["customer_name", "customer", "rental_site", "customer_reference"],
		list_columns=[("customer_name", "Customer"), ("rental_site", "Site"), ("required_from", "From"), ("estimated_amount", "Estimate")],
		header=[
			{"fieldname": "customer", "fetch": {"customer_name": "customer_name"}},
			SITE, PROJECT, "company", COST_CENTER, "order_date", "required_from", "expected_return_date", "rate_basis", "billing_cycle",
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
		prefill=["customer", "rental_site", "company"],
		next=[
			dict(label="Create Rental Contract", target="rental-contract",
				method="thinknxg_rental.thinknxg_rental.doctype.hire_order.hire_order.make_contract", when={"docstatus": [1], "status": ["Open"]}),
			# optional: only offered when the yard cannot cover the order
			dict(label="Material Reservation", target="material-reservation",
				method="thinknxg_rental.thinknxg_rental.doctype.hire_order.hire_order.make_reservation",
				when={"docstatus": [1], "status": ["Open", "Contracted"]}, when_fn=lambda d: flt(d.total_shortfall_qty) > 0),
			dict(label="Cross Hire Order", target="cross-hire-order", prefill={"rental_contract": lambda d: _source_contract(d)},
				when={"docstatus": [1]}, when_fn=lambda d: flt(d.total_shortfall_qty) > 0 and _source_contract(d)),
		],
		related=[
			dict(label="Rental Contracts", rows=lambda d: linked("Rental Contract", {"source_document": d.name, "docstatus": ["<", 2]},
				["status", "start_date", "end_date", "total_at_site_qty"], "rental-contract"),
				columns=[("name", "Rental Contract", "Data"), ("status", "Status", "Data"), ("start_date", "Start", "Date"),
					("end_date", "End", "Date"), ("total_at_site_qty", "At site", "Float")]),
		],
	),
	"hire-order-contract": dict(
		doctype="Hire Order Contract",
		print=True,
		label="Hire Order Contract",
		plural="Hire Order Contracts",
		title_field="customer_name",
		search_fields=["customer_name", "customer", "rental_site", "customer_reference"],
		list_columns=[("customer_name", "Customer"), ("rental_site", "Site"), ("required_from", "Erection"), ("total_contract_amount", "Contract")],
		header=[
			{"fieldname": "customer", "fetch": {"customer_name": "customer_name"}},
			SITE, PROJECT, "company", COST_CENTER, "order_date", "required_from", "customer_reference", "customer_reference_date",
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
				{"fieldname": "jcr_qty", "w": 1.1, "ro": 1},
				{"fieldname": "balance_qty", "w": 1.1, "ro": 1},
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
		prefill=["customer", "rental_site", "company"],
		next=[
			dict(label="Create Rental Contract", target="rental-contract",
				method="thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract.make_rental_contract",
				when={"docstatus": [1], "status": ["Open"]}),
			dict(label="Material Reservation", target="material-reservation",
				method="thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract.make_reservation",
				when={"docstatus": [1]}, when_fn=lambda d: _shortfall(d, "materials") > 0),
			dict(label="Cross Hire Order", target="cross-hire-order", prefill={"rental_contract": lambda d: _source_contract(d)},
				when={"docstatus": [1]}, when_fn=lambda d: _shortfall(d, "materials") > 0 and _source_contract(d)),
			# one JCR per job line and erection: with several lines open, the button asks which one first
			dict(label="Create Job Completion Report", target="jcr",
				method="thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract.make_jcr",
				when={"docstatus": [1]}, when_fn=lambda d: _open_job_lines(d), ask=lambda d: _jcr_line_ask(d)),
		],
		related=[
			dict(label="Rental Contracts", rows=lambda d: linked("Rental Contract", {"source_document": d.name, "docstatus": ["<", 2]},
				["status", "start_date", "end_date", "total_at_site_qty"], "rental-contract"),
				columns=[("name", "Rental Contract", "Data"), ("status", "Status", "Data"), ("start_date", "Start", "Date"),
					("end_date", "End", "Date"), ("total_at_site_qty", "At site", "Float")]),
			# one row per JCR job line: a JCR can carry several job types, and one job type can sit at several locations
			dict(label="Job Completion Reports", rows=lambda d: _hoc_jcr_lines(d),
				columns=[("jcr", "JCR", "Data"), ("line", "Job line", "Data"), ("job_type_name", "Job type", "Data"), ("location", "Location", "Data"),
					("job_qty", "Jobs", "Float"), ("erection_date", "Erected", "Date"), ("contract_end_date", "Contract ends", "Date"),
					("dismantle_date", "Dismantled", "Date"), ("status", "Status", "Data"), ("billed", "Billed", "Currency"),
					("pending", "Not yet invoiced", "Currency")]),
		],
	),
	"jcr": dict(
		doctype="Job Completion Report",
		print=True,
		label="Job Completion Report",
		plural="Job Completion Reports",
		nav_label="JCRs",
		title_field="customer_name",
		search_fields=["customer_name", "customer", "hire_order_contract", "rental_contract", "rental_site"],
		list_columns=[("customer_name", "Customer"), ("hire_order_contract", "Hire Order Contract"), ("rental_site", "Site"), ("billed_upto", "Billed up to")],
		header=[
			{"fieldname": "hire_order_contract", "filters": {"docstatus": 1},
				"fetch": {"customer_name": "customer_name", "rental_site": "rental_site", "company": "company"}},
			{"fieldname": "rental_contract", "ro": 1},
			{"fieldname": "customer_name", "ro": 1},
			{"fieldname": "rental_site", "ro": 1},
			"company",
			{"fieldname": "remarks", "wide": 1},
		],
		tables=[
			# rows come from the contract's job lines (Create Job Completion Report, Get job lines), never typed in
			dict(fieldname="job_lines", no_add=1, columns=[
				{"fieldname": "job_type", "w": 2.4, "ro": 1},
				{"fieldname": "job_type_name", "w": 2.4, "ro": 1},
				{"fieldname": "location", "w": 1.8},
				{"fieldname": "nxg_contract_qty", "w": 1.1, "ro": 1},
				{"fieldname": "job_qty", "w": 1.1},
				{"fieldname": "nxg_balance_qty", "w": 1.1, "ro": 1},
				{"fieldname": "erection_date", "w": 1.9},
				{"fieldname": "included_days", "w": 1.1, "ro": 1},
				{"fieldname": "contract_end_date", "w": 1.5, "ro": 1},
				{"fieldname": "dismantle_date", "w": 1.9},
				{"fieldname": "excess_days", "w": 1.1, "ro": 1},
				{"fieldname": "contract_rate", "w": 1.4, "ro": 1},
				{"fieldname": "status", "w": 1.3, "ro": 1},
			]),
		],
		totals=["total_billed_amount", "billed_upto"],
		fill=dict(label="Get job lines", needs="hire_order_contract", arg="hire_order_contract", table="job_lines",
			method="thinknxg_rental.portal.entry.get_jcr_lines"),
		next=[
			# the desk's Record Dismantle: a part quantity returns that much, the last part closes the line
			dict(label="Record Dismantle", call="record_dismantle", when={"docstatus": [1]}, when_fn=lambda d: _standing_lines(d),
				ask=lambda d: [
					{"fieldname": "line_name", "label": "Job line", "fieldtype": "Select", "reqd": 1,
						"choices": [{"value": r.name, "label": f"{r.job_type_name or r.job_type}{' @ ' + r.location if r.location else ''} ({flt(r.job_qty):g})"}
							for r in _standing_lines(d)],
						"default": _standing_lines(d)[0].name},
					{"fieldname": "dismantle_date", "label": "Dismantle date", "fieldtype": "Date", "reqd": 1, "default": frappe.utils.nowdate()},
					{"fieldname": "return_qty", "label": "Jobs dismantled (blank = all still standing)", "fieldtype": "Float"},
					{"fieldname": "remarks", "label": "Remarks", "fieldtype": "Small Text", "wide": 1},
				], done="{0}: dismantle recorded."),
		],
		related=[
			dict(label="Dismantled", rows=lambda d: [dict(r.as_dict(), url="", name=r.job_type) for r in d.get("jcr_returns") or []],
				columns=[("job_type", "Job type", "Data"), ("return_date", "Date", "Date"), ("return_qty", "Jobs", "Float"), ("remarks", "Remarks", "Data")]),
			dict(label="Billing periods", rows=lambda d: linked("JCR Billing Schedule", {"jcr": d.name},
				["billing_type", "period_from", "period_to", "days", "amount", "status", "sales_invoice"], order_by="period_from asc"),
				columns=[("billing_type", "Charge", "Data"), ("period_from", "From", "Date"), ("period_to", "To", "Date"), ("days", "Days", "Int"),
					("amount", "Amount", "Currency"), ("status", "Status", "Data"), ("sales_invoice", "Sales Invoice", "Data")]),
		],
		# Submitted and still open: the form adds a Sales Invoice panel (this JCR, or several JCRs of the customer on one invoice).
		invoice=True,
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
			SITE, PROJECT, "company", COST_CENTER, "source_type", {"fieldname": "source_document", "filters": {"docstatus": 1, "customer": "$customer"}},
			"contract_date", "start_date", "end_date", "billing_cycle",
			{"fieldname": "billing_interval_days", "show_if": {"billing_cycle": ["Custom"]}}, "align_to_calendar_month",
			"minimum_hire_days", "grace_days",
			"security_deposit", "advance_amount", "deposit_received", "deposit_reference", "payment_terms_template", "taxes_and_charges",
			{"fieldname": "last_billed_upto", "ro": 1}, {"fieldname": "next_billing_date", "ro": 1}, {"fieldname": "total_billed_amount", "ro": 1},
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
				{"fieldname": "lost_qty", "w": 1.1, "ro": 1},
				{"fieldname": "at_site_qty", "w": 1.2, "ro": 1},
				{"fieldname": "pending_qty", "w": 1.2, "ro": 1},
			]),
			dict(fieldname="extensions", readonly=1, columns=[
				{"fieldname": "extension_date", "w": 1.5},
				{"fieldname": "previous_end_date", "w": 1.5},
				{"fieldname": "new_end_date", "w": 1.5},
				{"fieldname": "extended_by", "w": 2.5},
				{"fieldname": "remarks", "w": 4},
			]),
		],
		totals=["total_contract_qty", "total_dispatched_qty", "total_at_site_qty", "total_returned_qty"],
		next=[
			dict(label="New Delivery Order", target="delivery-order", prefill={"rental_contract": "name"}, when={"docstatus": [1], "status": ["Active", "On Hire"]}),
			dict(label="New Off-Hire Note", target="off-hire-note", prefill={"rental_contract": "name"}, when={"docstatus": [1], "status": ["On Hire", "Active"]}),
			dict(label="Material Reservation", target="material-reservation",
				method="thinknxg_rental.thinknxg_rental.doctype.rental_contract.rental_contract.make_reservation",
				when={"docstatus": [1], "status": ["Active", "On Hire"]}, when_fn=lambda d: any(flt(r.pending_qty) > 0 for r in d.items)),
			dict(label="Cross Hire Order", target="cross-hire-order",
				method="thinknxg_rental.thinknxg_rental.doctype.rental_contract.rental_contract.make_cross_hire_order",
				when={"docstatus": [1], "status": ["Active", "On Hire"]}, when_fn=lambda d: any(flt(r.pending_qty) > 0 for r in d.items)),
			dict(label="Extend Contract", call="extend_contract", when={"docstatus": [1], "status": ["Active", "On Hire", "Off Hired"]},
				ask=lambda d: [{"fieldname": "new_end_date", "label": "New end date", "fieldtype": "Date", "reqd": 1},
					{"fieldname": "remarks", "label": "Remarks", "fieldtype": "Small Text", "wide": 1}], done="{0}: end date extended."),
			dict(label="Record Deposit", fn="thinknxg_rental.portal.entry.record_deposit", source_arg="rental_contract",
				when={"docstatus": [1]}, when_fn=lambda d: d.status != "Cancelled",
				ask=lambda d: [{"fieldname": "deposit_received", "label": "Deposit received", "fieldtype": "Currency", "reqd": 1, "default": d.deposit_received or None},
					{"fieldname": "deposit_reference", "label": "Deposit reference", "fieldtype": "Data", "default": d.deposit_reference}], done="{0}: deposit recorded."),
			dict(label="Close Contract", call="close_contract", when={"docstatus": [1], "status": ["Active", "On Hire", "Off Hired"]},
				when_fn=lambda d: flt(d.total_at_site_qty) <= 0 and flt(d.total_dispatched_qty) > 0,
				confirm="Final-bill this contract and mark it Completed?", done="{0} is completed."),
			dict(label="Reopen Contract", call="reopen_contract", when={"docstatus": [1], "status": ["Completed"]},
				confirm="Reopen this completed contract?", done="{0} is open again."),
		],
		related=[
			dict(label="Delivery Orders", rows=lambda d: linked("Hire Delivery Order", {"rental_contract": d.name, "docstatus": ["<", 2]},
				["posting_date", "vehicle_no", "total_qty"], "delivery-order", order_by="posting_date desc"),
				columns=[("name", "Delivery Order", "Data"), ("posting_date", "Dispatch date", "Date"), ("vehicle_no", "Vehicle", "Data"),
					("total_qty", "Qty", "Float"), ("status", "Status", "Data")]),
			dict(label="Off-Hire Notes", rows=lambda d: linked("Hire Off-Hire Note", {"rental_contract": d.name, "docstatus": ["<", 2]},
				["return_date", "off_hire_type", "total_returned_qty", "total_lost_qty", "inspection_status"], "off-hire-note", order_by="return_date desc"),
				columns=[("name", "Off-Hire Note", "Data"), ("return_date", "Returned", "Date"), ("off_hire_type", "Type", "Data"),
					("total_returned_qty", "Qty", "Float"), ("total_lost_qty", "Lost", "Float"), ("inspection_status", "Inspection", "Data")]),
			dict(label="Material Reservations", rows=lambda d: linked("Rental Material Reservation", {"rental_contract": d.name, "docstatus": ["<", 2]},
				["required_from", "total_reserved_qty", "total_shortfall_qty", "status"], "material-reservation"),
				columns=[("name", "Reservation", "Data"), ("required_from", "From", "Date"), ("total_reserved_qty", "Reserved", "Float"),
					("total_shortfall_qty", "Shortfall", "Float"), ("status", "Status", "Data")]),
			dict(label="Cross Hire Orders", rows=lambda d: linked("Cross Hire Order", {"rental_contract": d.name, "docstatus": ["<", 2]},
				["supplier_name", "expected_return_date", "total_qty", "status"], "cross-hire-order"),
				columns=[("name", "Cross Hire Order", "Data"), ("supplier_name", "Supplier", "Data"), ("expected_return_date", "Due back", "Date"),
					("total_qty", "Qty", "Float"), ("status", "Status", "Data")]),
			dict(label="Job Completion Reports", rows=lambda d: linked("Job Completion Report", {"rental_contract": d.name, "docstatus": ["<", 2]},
				["job_type_name", "location", "erection_date", "dismantle_date", "total_billed_amount", "status"], "jcr"),
				columns=[("name", "JCR", "Data"), ("job_type_name", "Job type", "Data"), ("location", "Location", "Data"),
					("erection_date", "Erected", "Date"), ("dismantle_date", "Dismantled", "Date"), ("total_billed_amount", "Billed", "Currency"),
					("status", "Status", "Data")]),
			dict(label="Billing schedules", rows=lambda d: linked("Rental Billing Schedule", {"rental_contract": d.name, "docstatus": ["<", 2]},
				["from_date", "to_date", "total_amount", "sales_invoice", "status"], order_by="from_date desc"),
				columns=[("name", "Billing schedule", "Data"), ("from_date", "From", "Date"), ("to_date", "To", "Date"),
					("total_amount", "Amount", "Currency"), ("sales_invoice", "Sales Invoice", "Data"), ("status", "Status", "Data")]),
			dict(label="Sales Invoices", rows=lambda d: linked("Sales Invoice", {"nxg_rental_contract": d.name, "docstatus": ["<", 2]},
				["posting_date", "grand_total", "outstanding_amount", "status"], "sales-invoice", order_by="posting_date desc"),
				columns=[("name", "Sales Invoice", "Data"), ("posting_date", "Date", "Date"), ("grand_total", "Total", "Currency"),
					("outstanding_amount", "Outstanding", "Currency"), ("status", "Status", "Data")]),
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
			{"fieldname": "rental_contract", "filters": LIVE_CONTRACT,
				"fetch": {"customer_name": "customer_name", "rental_site": "rental_site", "project": "project"}},
			{"fieldname": "customer_name", "ro": 1},
			{"fieldname": "rental_site", "ro": 1},
			PROJECT,
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
	"material-reservation": dict(
		menu="more",
		doctype="Rental Material Reservation",
		label="Material Reservation",
		plural="Material Reservations",
		title_field="customer_name",
		search_fields=["customer_name", "customer", "rental_contract", "source_document", "rental_site"],
		list_columns=[("customer_name", "Customer"), ("source_document", "Order"), ("required_from", "From"), ("total_shortfall_qty", "Shortfall")],
		header=[
			"source_type", {"fieldname": "source_document", "filters": {"docstatus": 1}},
			{"fieldname": "rental_contract", "filters": LIVE_CONTRACT},
			{"fieldname": "customer", "fetch": {"customer_name": "customer_name"}},
			{"fieldname": "customer_name", "ro": 1},
			{"fieldname": "rental_site", "filters": {"customer": "$customer"}},
			"company", "reservation_date", "required_from", "required_to",
			{"fieldname": "source_warehouse", "filters": {"is_group": 0}},
			{"fieldname": "remarks", "wide": 1},
		],
		tables=[
			dict(fieldname="items", columns=[
				{"fieldname": "item_code", "w": 2.6, "filters": STOCK_ITEM, "fetch": ITEM_FETCH},
				{"fieldname": "item_name", "w": 3, "ro": 1},
				{"fieldname": "uom", "w": 1, "ro": 1},
				{"fieldname": "required_qty", "w": 1.2},
				{"fieldname": "source_warehouse", "w": 2.2, "filters": {"is_group": 0}},
				{"fieldname": "available_qty", "w": 1.2, "ro": 1},
				{"fieldname": "reserved_qty", "w": 1.2, "ro": 1},
				{"fieldname": "shortfall_qty", "w": 1.2, "ro": 1},
				{"fieldname": "dispatched_qty", "w": 1.2, "ro": 1},
			]),
		],
		totals=["total_required_qty", "total_reserved_qty", "total_shortfall_qty"],
		next=[
			dict(label="Create Cross Hire Order", target="cross-hire-order",
				method="thinknxg_rental.thinknxg_rental.doctype.rental_material_reservation.rental_material_reservation.make_cross_hire_order",
				when={"docstatus": [1]}, when_fn=lambda d: flt(d.total_shortfall_qty) > 0),
			dict(label="New Delivery Order", target="delivery-order", prefill={"rental_contract": "rental_contract"},
				when={"docstatus": [1]}, when_fn=lambda d: d.get("rental_contract")),
		],
	),
	"cross-hire-order": dict(
		menu="more",
		doctype="Cross Hire Order",
		print=True,
		# the Purchase Order made on submit
		print_links=[("Purchase Order", "purchase_order")],
		label="Cross Hire Order",
		plural="Cross Hire Orders",
		title_field="supplier_name",
		search_fields=["supplier_name", "supplier", "rental_contract", "supplier_reference"],
		list_columns=[("supplier_name", "Supplier"), ("rental_contract", "Contract"), ("hire_from", "From"), ("estimated_amount", "Estimate")],
		prefill=["rental_contract"],
		header=[
			{"fieldname": "supplier", "fetch": {"supplier_name": "supplier_name"}},
			{"fieldname": "supplier_name", "ro": 1},
			"supplier_reference", "company", "order_date",
			{"fieldname": "rental_contract", "filters": LIVE_CONTRACT, "fetch": {"project": "project"}},
			PROJECT,
			{"fieldname": "material_reservation", "filters": {"docstatus": 1}},
			"hire_from", "expected_return_date", "rate_basis", "receive_at", "taxes_and_charges",
			{"fieldname": "remarks", "wide": 1},
		],
		tables=[
			dict(fieldname="items", columns=[
				{"fieldname": "item_code", "w": 2.6, "filters": STOCK_ITEM, "fetch": ITEM_FETCH},
				{"fieldname": "item_name", "w": 3, "ro": 1},
				{"fieldname": "uom", "w": 1, "ro": 1},
				{"fieldname": "qty", "w": 1.2},
				{"fieldname": "rate_basis", "w": 1.3},
				{"fieldname": "rate", "w": 1.4},
				{"fieldname": "expected_hire_days", "w": 1.1},
				{"fieldname": "estimated_amount", "w": 1.5, "ro": 1},
				{"fieldname": "received_qty", "w": 1.2, "ro": 1},
				{"fieldname": "on_hire_qty", "w": 1.2, "ro": 1},
			]),
		],
		totals=["total_qty", "estimated_amount"],
		# The desk's Create menu: receipt (Purchase Receipt on the order's PO), off-hire back to the supplier,
		# the supplier's hire invoice (Purchase Invoice, opened in the desk) and Complete once everything is back.
		next=[
			dict(label="Cross Hire Receipt", target="cross-hire-receipt", method="thinknxg_rental.portal.entry.make_cross_hire_receipt",
				when={"docstatus": [1]}, when_fn=lambda d: d.status != "Completed" and any(flt(r.received_qty) < flt(r.qty) for r in d.items)),
			dict(label="Cross Hire Off-Hire Note", target="cross-hire-off-hire",
				method="thinknxg_rental.thinknxg_rental.doctype.cross_hire_off_hire_note.cross_hire_off_hire_note.make_cross_hire_off_hire_note",
				when={"docstatus": [1]}, when_fn=lambda d: d.status != "Completed" and sum(flt(r.on_hire_qty) for r in d.items) > 0),
			dict(label="Supplier Hire Invoice", fn="thinknxg_rental.services.cross_hire.make_supplier_invoice", source_arg="cross_hire_order",
				opens="Purchase Invoice", perm="read", when={"docstatus": [1]}, when_fn=lambda d: d.status not in ("To Receive", "Completed"),
				ask=lambda d: [{"fieldname": "upto_date", "label": "Bill up to", "fieldtype": "Date", "reqd": 1, "default": frappe.utils.nowdate()}]),
			dict(label="Complete Order", call="complete", when={"docstatus": [1], "status": ["Returned"]},
				confirm="Mark this cross hire order Completed and close its Purchase Order?", done="{0} is completed."),
		],
		related=[
			dict(label="Receipts and returns", rows=lambda d: linked("Purchase Receipt", {"nxg_cross_hire_order": d.name, "docstatus": ["<", 2]},
				["posting_date", "is_return", "total_qty", "status"], order_by="posting_date asc"),
				columns=[("name", "Purchase Receipt", "Data"), ("posting_date", "Date", "Date"), ("is_return", "Return", "Check"),
					("total_qty", "Qty", "Float"), ("status", "Status", "Data")]),
			dict(label="Cross Hire Off-Hire Notes", rows=lambda d: linked("Cross Hire Off-Hire Note", {"cross_hire_order": d.name, "docstatus": ["<", 2]},
				["off_hire_date", "total_qty", "status"], "cross-hire-off-hire"),
				columns=[("name", "Off-Hire Note", "Data"), ("off_hire_date", "Off-hire date", "Date"), ("total_qty", "Qty", "Float"), ("status", "Status", "Data")]),
			dict(label="Supplier hire invoices", rows=lambda d: linked("Purchase Invoice", {"nxg_cross_hire_order": d.name, "docstatus": ["<", 2]},
				["posting_date", "grand_total", "outstanding_amount", "status"], order_by="posting_date desc"),
				columns=[("name", "Purchase Invoice", "Data"), ("posting_date", "Date", "Date"), ("grand_total", "Total", "Currency"),
					("outstanding_amount", "Outstanding", "Currency"), ("status", "Status", "Data")]),
		],
	),
	"cross-hire-receipt": dict(
		menu="none",
		link=False,
		active="suppliers",
		list_url="/rental/admin/suppliers",
		doctype="Purchase Receipt",
		label="Cross Hire Receipt",
		plural="Cross Hire Receipts",
		title_field="supplier_name",
		search_fields=["supplier_name", "supplier"],
		list_columns=[("supplier_name", "Supplier"), ("posting_date", "Date"), ("total_qty", "Qty")],
		header=[
			{"fieldname": "nxg_cross_hire_order", "ro": 1},
			{"fieldname": "supplier", "ro": 1},
			{"fieldname": "supplier_name", "ro": 1},
			{"fieldname": "company", "ro": 1},
			"posting_date", "set_posting_time", "supplier_delivery_note",
			{"fieldname": "set_warehouse", "ro": 1},
		],
		tables=[
			dict(fieldname="items", columns=[
				{"fieldname": "item_code", "w": 2.6, "ro": 1},
				{"fieldname": "item_name", "w": 3, "ro": 1},
				{"fieldname": "uom", "w": 1, "ro": 1},
				{"fieldname": "qty", "w": 1.2},
				{"fieldname": "warehouse", "w": 2.4, "ro": 1},
				{"fieldname": "batch_no", "w": 1.6},
				{"fieldname": "purchase_order", "w": 2, "ro": 1},
			]),
		],
		totals=["total_qty"],
	),
	"cross-hire-off-hire": dict(
		menu="more",
		doctype="Cross Hire Off-Hire Note",
		label="Cross Hire Off-Hire Note",
		plural="Cross Hire Off-Hire Notes",
		nav_label="Cross Hire Returns",
		title_field="supplier_name",
		search_fields=["supplier_name", "supplier", "cross_hire_order", "vehicle_no"],
		list_columns=[("supplier_name", "Supplier"), ("cross_hire_order", "Cross hire order"), ("off_hire_date", "Off-hire date"), ("total_qty", "Qty")],
		prefill=["cross_hire_order"],
		header=[
			{"fieldname": "cross_hire_order", "filters": {"docstatus": 1, "status": ["not in", ["To Receive", "Completed", "Cancelled"]]},
				"fetch": {"supplier": "supplier", "supplier_name": "supplier_name", "purchase_order": "purchase_order", "company": "company",
					"return_from_warehouse": "receipt_warehouse"}},
			{"fieldname": "supplier_name", "ro": 1},
			{"fieldname": "purchase_order", "ro": 1},
			"company", "off_hire_date", "last_billable_date",
			{"fieldname": "return_from_warehouse", "filters": {"is_group": 0, "company": "$company"}},
			"vehicle_no", "driver_name", "supplier_acknowledgement",
			{"fieldname": "purchase_returns", "ro": 1, "wide": 1},
			{"fieldname": "remarks", "wide": 1},
		],
		tables=[
			dict(fieldname="items", columns=[
				{"fieldname": "item_code", "w": 2.6, "ro": 1},
				{"fieldname": "item_name", "w": 3, "ro": 1},
				{"fieldname": "uom", "w": 1, "ro": 1},
				{"fieldname": "on_hire_qty", "w": 1.2, "ro": 1},
				{"fieldname": "at_customer_site_qty", "w": 1.4, "ro": 1},
				{"fieldname": "qty", "w": 1.2},
				{"fieldname": "batch_no", "w": 1.6},
				{"fieldname": "remarks", "w": 2},
			]),
		],
		totals=["total_qty"],
		fill=dict(label="Get items on hire", needs="cross_hire_order", arg="cross_hire_order", table="items",
			method="thinknxg_rental.portal.entry.get_cross_hire_return_items"),
	),
	"sales-order": dict(
		menu="more",
		doctype="Sales Order",
		label="Sales Order",
		plural="Sales Orders",
		title_field="customer_name",
		search_fields=["customer_name", "customer", "po_no", "project"],
		list_columns=[("customer_name", "Customer"), ("transaction_date", "Date"), ("delivery_date", "Delivery"), ("grand_total", "Total")],
		header=[
			{"fieldname": "customer", "fetch": {"customer_name": "customer_name"}},
			{"fieldname": "customer_name", "ro": 1},
			"company", "transaction_date", "delivery_date", "po_no", "currency", "payment_terms_template",
			TAX_TEMPLATE, COST_CENTER, PROJECT, {"fieldname": "set_warehouse", "filters": {"company": "$company", "is_group": 0}},
		],
		tables=[
			dict(fieldname="items", columns=[
				{"fieldname": "item_code", "w": 2.6, "filters": {"disabled": 0}, "fetch": ITEM_FETCH},
				{"fieldname": "item_name", "w": 2.8, "ro": 1},
				{"fieldname": "delivery_date", "w": 1.5},
				{"fieldname": "qty", "w": 1.1},
				{"fieldname": "uom", "w": 1, "ro": 1},
				{"fieldname": "rate", "w": 1.4},
				{"fieldname": "amount", "w": 1.5, "ro": 1},
				{"fieldname": "warehouse", "w": 2.2, "filters": {"company": "$company", "is_group": 0}},
			]),
			TAX_TABLE,
		],
		totals=["total_qty", "net_total", "total_taxes_and_charges", "grand_total"],
		next=[
			dict(label="Create Delivery Note", target="delivery-note", method="erpnext.selling.doctype.sales_order.sales_order.make_delivery_note",
				when={"docstatus": [1]}, when_fn=lambda d: flt(d.per_delivered) < 100 and d.status not in ("Closed", "On Hold")),
			dict(label="Create Sales Invoice", target="sales-invoice", method="erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice",
				when={"docstatus": [1]}, when_fn=lambda d: flt(d.per_billed) < 100 and d.status not in ("Closed", "On Hold")),
		],
		related=[
			dict(label="Delivery Notes", rows=lambda d: _against("Delivery Note", "Delivery Note Item", "against_sales_order", d.name, "delivery-note"),
				columns=[("name", "Delivery Note", "Data"), ("posting_date", "Date", "Date"), ("grand_total", "Total", "Currency"), ("status", "Status", "Data")]),
			dict(label="Sales Invoices", rows=lambda d: _against("Sales Invoice", "Sales Invoice Item", "sales_order", d.name, "sales-invoice"),
				columns=[("name", "Sales Invoice", "Data"), ("posting_date", "Date", "Date"), ("grand_total", "Total", "Currency"), ("status", "Status", "Data")]),
		],
	),
	"delivery-note": dict(
		menu="more",
		doctype="Delivery Note",
		print=True,
		label="Delivery Note",
		plural="Delivery Notes",
		nav_label="Sales Delivery Notes",
		title_field="customer_name",
		search_fields=["customer_name", "customer", "po_no"],
		list_columns=[("customer_name", "Customer"), ("posting_date", "Date"), ("grand_total", "Total")],
		header=[
			{"fieldname": "customer", "fetch": {"customer_name": "customer_name"}},
			{"fieldname": "customer_name", "ro": 1},
			"company", "posting_date", "po_no", "currency", TAX_TEMPLATE, COST_CENTER, PROJECT,
			{"fieldname": "set_warehouse", "filters": {"company": "$company", "is_group": 0}},
			"lr_no", "vehicle_no", "transporter_name",
		],
		tables=[
			dict(fieldname="items", columns=[
				{"fieldname": "item_code", "w": 2.6, "filters": {"disabled": 0}, "fetch": ITEM_FETCH},
				{"fieldname": "item_name", "w": 2.8, "ro": 1},
				{"fieldname": "qty", "w": 1.1},
				{"fieldname": "uom", "w": 1, "ro": 1},
				{"fieldname": "rate", "w": 1.4},
				{"fieldname": "amount", "w": 1.5, "ro": 1},
				{"fieldname": "warehouse", "w": 2.2, "filters": {"company": "$company", "is_group": 0}},
				{"fieldname": "against_sales_order", "w": 2, "ro": 1},
			]),
			TAX_TABLE,
		],
		totals=["total_qty", "net_total", "total_taxes_and_charges", "grand_total"],
		next=[
			dict(label="Create Sales Invoice", target="sales-invoice", method="erpnext.stock.doctype.delivery_note.delivery_note.make_sales_invoice",
				when={"docstatus": [1]}, when_fn=lambda d: flt(d.per_billed) < 100 and d.status not in ("Closed", "Return Issued")),
		],
	),
	"sales-invoice": dict(
		menu="more",
		doctype="Sales Invoice",
		print=True,
		label="Sales Invoice",
		plural="Sales Invoices",
		title_field="customer_name",
		search_fields=["customer_name", "customer", "nxg_rental_contract", "project"],
		list_columns=[("customer_name", "Customer"), ("posting_date", "Date"), ("nxg_rental_contract", "Contract"), ("grand_total", "Total")],
		header=[
			{"fieldname": "customer", "fetch": {"customer_name": "customer_name"}},
			{"fieldname": "customer_name", "ro": 1},
			"company", "posting_date", "due_date", "currency", "payment_terms_template", TAX_TEMPLATE, COST_CENTER, PROJECT,
			{"fieldname": "nxg_rental_contract", "ro": 1},
			{"fieldname": "remarks", "wide": 1},
		],
		tables=[
			dict(fieldname="items", columns=[
				{"fieldname": "item_code", "w": 2.4, "filters": {"disabled": 0}, "fetch": ITEM_FETCH},
				{"fieldname": "item_name", "w": 2.4, "ro": 1},
				{"fieldname": "description", "w": 4},
				{"fieldname": "qty", "w": 1.1},
				{"fieldname": "uom", "w": 1, "ro": 1},
				{"fieldname": "rate", "w": 1.5},
				{"fieldname": "amount", "w": 1.6, "ro": 1},
			]),
			TAX_TABLE,
		],
		totals=["net_total", "total_taxes_and_charges", "grand_total", "outstanding_amount"],
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
				"fetch": {"customer_name": "customer_name", "rental_site": "rental_site", "grace_days": "grace_days", "project": "project"}},
			{"fieldname": "customer_name", "ro": 1},
			{"fieldname": "rental_site", "ro": 1},
			PROJECT,
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
		# Submitted: inspect what came back, then settle damage and loss (the desk's Create menu).
		next=[
			dict(label="Create Return Inspection", target="return-inspection", method="thinknxg_rental.thinknxg_rental.doctype.hire_off_hire_note.hire_off_hire_note.make_inspection",
				when={"docstatus": [1], "inspection_status": ["Pending"]}),
			dict(label="Create Damage Settlement", target="damage-settlement", method="thinknxg_rental.thinknxg_rental.doctype.hire_off_hire_note.hire_off_hire_note.make_damage_settlement",
				when={"docstatus": [1], "inspection_status": ["Not Required", "Completed"]}, when_fn=lambda d: not _settlement_of(d.name)),
		],
		related=[
			dict(label="Return inspections", rows=lambda d: linked("Rental Return Inspection", {"hire_off_hire_note": d.name, "docstatus": ["<", 2]},
				["inspection_date", "total_good_qty", "total_repairable_qty", "total_damaged_qty"], "return-inspection"),
				columns=[("name", "Inspection", "Data"), ("inspection_date", "Date", "Date"), ("total_good_qty", "Good", "Float"),
					("total_repairable_qty", "Repairable", "Float"), ("total_damaged_qty", "Beyond repair", "Float"), ("status", "Status", "Data")]),
			dict(label="Damage settlements", rows=lambda d: linked("Rental Damage Settlement", {"hire_off_hire_note": d.name, "docstatus": ["<", 2]},
				["posting_date", "grand_total", "sales_invoice", "status"], "damage-settlement"),
				columns=[("name", "Settlement", "Data"), ("posting_date", "Date", "Date"), ("grand_total", "Total", "Currency"),
					("sales_invoice", "Sales Invoice", "Data"), ("status", "Status", "Data")]),
		],
		fill=dict(label="Get items at site", needs="rental_contract", table="items",
			method="thinknxg_rental.thinknxg_rental.doctype.hire_off_hire_note.hire_off_hire_note.get_items_at_site"),
	),
	"return-inspection": dict(
		menu="more",
		doctype="Rental Return Inspection",
		label="Return Inspection",
		plural="Return Inspections",
		title_field="customer_name",
		search_fields=["customer_name", "hire_off_hire_note", "rental_contract"],
		list_columns=[("customer_name", "Customer"), ("hire_off_hire_note", "Off-hire note"), ("inspection_date", "Date"), ("total_damaged_qty", "Damaged")],
		header=[
			{"fieldname": "hire_off_hire_note", "filters": {"docstatus": 1, "inspection_status": "Pending"},
				"fetch": {"rental_contract": "rental_contract", "customer": "customer", "customer_name": "customer_name", "rental_site": "rental_site", "company": "company"}},
			{"fieldname": "rental_contract", "ro": 1},
			{"fieldname": "customer_name", "ro": 1},
			{"fieldname": "rental_site", "ro": 1},
			"company", "inspection_date", "inspector",
			{"fieldname": "remarks", "wide": 1},
		],
		tables=[
			dict(fieldname="items", columns=[
				{"fieldname": "item_code", "w": 2.4, "ro": 1},
				{"fieldname": "item_name", "w": 2.8, "ro": 1},
				{"fieldname": "uom", "w": 1, "ro": 1},
				{"fieldname": "ownership", "w": 1.3, "ro": 1},
				{"fieldname": "returned_qty", "w": 1.3, "ro": 1},
				{"fieldname": "good_qty", "w": 1.2},
				{"fieldname": "repairable_qty", "w": 1.4},
				{"fieldname": "damaged_qty", "w": 1.3},
				{"fieldname": "damage_notes", "w": 3},
			]),
		],
		totals=["total_good_qty", "total_repairable_qty", "total_damaged_qty"],
		next=[
			dict(label="Create Damage Settlement", target="damage-settlement", method="thinknxg_rental.thinknxg_rental.doctype.hire_off_hire_note.hire_off_hire_note.make_damage_settlement",
				source_field="hire_off_hire_note", when={"docstatus": [1]}, when_fn=lambda d: not _settlement_of(d.hire_off_hire_note)),
		],
	),
	"damage-settlement": dict(
		menu="more",
		doctype="Rental Damage Settlement",
		label="Damage Settlement",
		plural="Damage Settlements",
		title_field="customer_name",
		search_fields=["customer_name", "hire_off_hire_note", "rental_contract"],
		list_columns=[("customer_name", "Customer"), ("hire_off_hire_note", "Off-hire note"), ("posting_date", "Date"), ("grand_total", "Total")],
		header=[
			{"fieldname": "hire_off_hire_note", "filters": {"docstatus": 1},
				"fetch": {"rental_contract": "rental_contract", "customer": "customer", "customer_name": "customer_name", "company": "company"}},
			{"fieldname": "rental_contract", "ro": 1},
			{"fieldname": "customer_name", "ro": 1},
			"company", "posting_date", {"fieldname": "sales_invoice", "ro": 1},
			"transport_charges", "other_charges", "other_charges_description",
			{"fieldname": "remarks", "wide": 1},
		],
		tables=[
			dict(fieldname="items", columns=[
				{"fieldname": "item_code", "w": 2.4, "filters": STOCK_ITEM, "fetch": ITEM_FETCH},
				{"fieldname": "item_name", "w": 2.8, "ro": 1},
				{"fieldname": "uom", "w": 1, "ro": 1},
				{"fieldname": "ownership", "w": 1.3},
				{"fieldname": "classification", "w": 1.6},
				{"fieldname": "qty", "w": 1.1},
				{"fieldname": "rate", "w": 1.3},
				{"fieldname": "liability_percent", "w": 1.3},
				{"fieldname": "salvage_value", "w": 1.4},
				{"fieldname": "amount", "w": 1.5, "ro": 1},
			]),
		],
		totals=["total_damage_amount", "total_loss_amount", "total_salvage_value", "grand_total"],
		# make_sales_invoice saves the invoice itself, so the button opens the saved draft.
		next=[
			dict(label="Create Sales Invoice", target="sales-invoice",
				method="thinknxg_rental.thinknxg_rental.doctype.rental_damage_settlement.rental_damage_settlement.make_sales_invoice",
				creates="settlement", when={"docstatus": [1], "sales_invoice": [None, ""]}),
		],
	),
}

# A customer portal request, opened from /rental/admin/requests. The customer's own entries are read-only
# here; staff convert it (Hire Order, Off-Hire Note, extension) or reject it with a reply the customer sees.
ENTRY_TYPES["request"] = dict(
	menu="none",
	active="requests",
	doctype="Rental Portal Request",
	label="Customer Request",
	plural="Customer Requests",
	list_url="/rental/admin/requests",
	title_field="customer_name",
	search_fields=["customer_name", "customer", "rental_contract", "rental_site"],
	list_columns=[("customer_name", "Customer"), ("request_type", "Asking for"), ("request_date", "Date")],
	header=[
		{"fieldname": "request_type", "ro": 1}, {"fieldname": "customer", "ro": 1}, {"fieldname": "customer_name", "ro": 1},
		{"fieldname": "raised_by", "ro": 1}, {"fieldname": "request_date", "ro": 1}, {"fieldname": "status", "ro": 1},
		{"fieldname": "rental_contract", "ro": 1}, {"fieldname": "rental_site", "ro": 1},
		{"fieldname": "site_location", "ro": 1, "show_if": {"request_type": ["Hire Enquiry"]}},
		{"fieldname": "required_date", "ro": 1, "show_if": {"request_type": ["Hire Enquiry"]}},
		{"fieldname": "expected_return_date", "ro": 1, "show_if": {"request_type": ["Hire Enquiry"]}},
		{"fieldname": "new_end_date", "ro": 1, "show_if": {"request_type": ["Extension Request"]}},
		{"fieldname": "reference_doctype", "ro": 1}, {"fieldname": "reference_name", "ro": 1},
		{"fieldname": "remarks", "ro": 1, "wide": 1},
		{"fieldname": "response", "wide": 1},
	],
	tables=[
		dict(fieldname="items", readonly=1, columns=[
			{"fieldname": "item_code", "w": 2.6}, {"fieldname": "item_name", "w": 3}, {"fieldname": "uom", "w": 1}, {"fieldname": "qty", "w": 1.2},
		]),
	],
	next=[
		dict(label="Start", call="start", when={"status": ["Open"]}, done="{0} is in progress."),
		dict(label="Create Hire Order", target="hire-order",
			method="thinknxg_rental.thinknxg_rental.doctype.rental_portal_request.rental_portal_request.make_hire_order",
			when={"request_type": ["Hire Enquiry"], "status": ["Open", "In Progress"]}, when_fn=lambda d: not _request_document(d)),
		dict(label="Create Off-Hire Note", target="off-hire-note",
			method="thinknxg_rental.thinknxg_rental.doctype.rental_portal_request.rental_portal_request.make_off_hire_note",
			when={"request_type": ["Off-Hire Request"], "status": ["Open", "In Progress"]}, when_fn=lambda d: not _request_document(d)),
		dict(label="Extend Contract", call="apply_extension", when={"request_type": ["Extension Request"], "status": ["Open", "In Progress"]},
			confirm="Extend the contract to the requested end date and complete this request?", done="{0}: contract extended."),
		dict(label="Reject", call="reject", when={"status": ["Open", "In Progress"]}, when_fn=lambda d: not _request_document(d),
			ask=[{"fieldname": "reason", "label": "Reason (the customer sees this)", "fieldtype": "Small Text", "reqd": 1, "wide": 1}],
			done="{0} is rejected."),
	],
	related=[
		dict(label="Documents made for this request", rows=lambda d: _request_document(d, rows=True),
			columns=[("name", "Document", "Data"), ("doctype", "Type", "Data"), ("status", "Status", "Data")]),
	],
)

# Never taken from the browser: frappe sets these itself.
PROTECTED = {
	"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx", "doctype",
	"parent", "parentfield", "parenttype", "amended_from", "naming_series",
}
INPUT_TYPES = {
	"Data", "Small Text", "Text", "Long Text", "Text Editor", "Date", "Datetime", "Time", "Int", "Float",
	"Currency", "Percent", "Select", "Link", "Dynamic Link", "Check", "Phone",
}


def _quotation_is(site, deal_types):
	"""A Rental Site made from a submitted quotation of one of these deal types."""
	q = site.get("nxg_quotation")
	if not q or site.get("disabled"):
		return False
	v = frappe.db.get_value("Quotation", q, ["docstatus", "deal_type"], as_dict=True)
	return bool(v and v.docstatus == 1 and v.deal_type in deal_types)


def _source_contract(doc):
	"""The submitted Rental Contract of a Hire Order / Hire Order Contract, if it has one yet."""
	from thinknxg_rental.services.utils import get_contract_for_source

	return get_contract_for_source(doc.doctype, doc.name)


def _shortfall(doc, table):
	return sum(flt(r.get("shortfall_qty")) for r in doc.get(table) or [])


def _settlement_of(off_hire_note):
	return frappe.db.exists("Rental Damage Settlement", {"hire_off_hire_note": off_hire_note, "docstatus": ["<", 2]})


def _made_from(doctype, field, name):
	"""A live (draft or submitted) document already made from this one, so its Create button is not offered twice."""
	return frappe.db.get_value(doctype, {field: name, "docstatus": ["<", 2]} if frappe.get_meta(doctype).is_submittable else {field: name}, "name")


def _lead_quotations(lead, live=False):
	"""Quotations made from a Lead: to the Customer made from it, or to the Prospect it belongs to."""
	parties = frappe.get_all("Customer", filters={"lead_name": lead.name}, pluck="name")
	parties += frappe.get_all("Prospect Lead", filters={"lead": lead.name, "parenttype": "Prospect"}, pluck="parent")
	parties.append(lead.name)
	filters = {"party_name": ["in", parties], "docstatus": ["<", 2]}
	if live:
		filters["status"] = ["not in", ["Lost", "Expired", "Cancelled"]]
	return linked("Quotation", filters, ["deal_type", "transaction_date", "grand_total", "status"], "quotation")


def _against(doctype, child, field, name, entry):
	parents = frappe.get_all(child, filters={field: name, "docstatus": ["<", 2]}, pluck="parent", distinct=True)
	if not parents:
		return []
	return linked(doctype, {"name": ["in", parents]}, ["posting_date", "grand_total", "status"], entry)


def _quotation_sales_orders(doc):
	parents = frappe.get_all("Sales Order Item", filters={"prevdoc_docname": doc.name, "docstatus": ["<", 2]}, pluck="parent", distinct=True)
	if not parents:
		return []
	return linked("Sales Order", {"name": ["in", parents]}, ["transaction_date", "grand_total", "status"], "sales-order")


def _request_document(doc, rows=False):
	"""The Hire Order / Off-Hire Note already made for a customer request, draft or submitted, so the
	request is not converted twice. rows=True adds the contract an extension was applied to."""
	out = []
	for doctype, entry in (("Hire Order", "hire-order"), ("Hire Off-Hire Note", "off-hire-note")):
		for r in linked(doctype, {"portal_request": doc.name, "docstatus": ["<", 2]}, [], entry):
			out.append(dict(r, doctype=_(doctype)))
	if rows and doc.get("reference_doctype") == "Rental Contract" and doc.get("reference_name"):
		out += [dict(r, doctype=_("Rental Contract")) for r in linked("Rental Contract", {"name": doc.reference_name}, ["status"], "rental-contract")]
	return out


def _standing_lines(jcr):
	"""JCR job lines erected and not fully dismantled yet."""
	return [r for r in jcr.get("job_lines") or [] if r.get("erection_date") and not r.get("dismantle_date")]


def _hoc_jcr_lines(hoc):
	"""Every JCR job line of a Hire Order Contract, with what is billed and what is still to invoice."""
	jcrs = linked("Job Completion Report", {"hire_order_contract": hoc.name, "docstatus": ["<", 2]}, ["status"], "jcr", order_by="creation asc", limit=200)
	if not jcrs:
		return []
	names = [j.name for j in jcrs]
	lines = frappe.get_all("Job Completion Report Line", filters={"parent": ["in", names], "parenttype": "Job Completion Report"},
		fields=["name", "parent", "contract_item", "job_type", "job_type_name", "location", "job_qty", "erection_date", "contract_end_date",
			"dismantle_date", "status", "total_billed_amount"], order_by="parent asc, idx asc")
	line_no = {d.name: d.idx for d in hoc.items}
	pending = {}
	for s in frappe.get_all("JCR Billing Schedule", filters={"jcr": ["in", names], "status": "Pending"}, fields=["jcr", "jcr_line", "amount"]):
		pending[(s.jcr, s.jcr_line)] = pending.get((s.jcr, s.jcr_line), 0) + flt(s.amount)
	head = {j.name: j for j in jcrs}
	out = []
	for l in lines:
		j = head[l.parent]
		out.append(frappe._dict(l, jcr=l.parent, url=j.url, line=f"#{line_no[l.contract_item]}" if l.contract_item in line_no else "",
			status="Draft" if j.docstatus == 0 else l.status or j.status, billed=flt(l.total_billed_amount),
			pending=pending.get((l.parent, l.name), 0)))
	return out


@frappe.whitelist()
def make_cross_hire_receipt(source_name: str, target_doc=None):
	"""Cross Hire Order -> Purchase Receipt for what is still to arrive (services.cross_hire does the mapping)."""
	from thinknxg_rental.services.cross_hire import make_cross_hire_receipt as make

	return make(source_name)


@frappe.whitelist()
def get_cross_hire_return_items(cross_hire_order: str):
	"""Rows a Cross Hire Off-Hire Note takes: what is on hire from the supplier and not at a customer site."""
	from thinknxg_rental.thinknxg_rental.doctype.cross_hire_off_hire_note.cross_hire_off_hire_note import make_cross_hire_off_hire_note

	return [_clean(d.as_dict()) for d in make_cross_hire_off_hire_note(cross_hire_order).items]


@frappe.whitelist(methods=["POST"])
def record_deposit(rental_contract: str, deposit_received: float, deposit_reference: str | None = None):
	"""Deposit received and its reference, which may change on a submitted contract (allow on submit)."""
	doc = frappe.get_doc("Rental Contract", rental_contract)
	doc.check_permission("write")
	if doc.docstatus != 1:
		frappe.throw(_("Save the deposit on the draft form, or submit the contract first."))
	if flt(deposit_received) < 0:
		frappe.throw(_("Deposit received cannot be negative"))
	doc.deposit_received = flt(deposit_received)
	doc.deposit_reference = deposit_reference
	doc.save()
	return doc.name


def _open_job_lines(doc):
	from thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract import get_open_job_lines

	return get_open_job_lines(doc)


def _jcr_line_ask(hoc):
	"""Create Job Completion Report on a contract with several open job lines: which line the JCR is for."""
	lines = _open_job_lines(hoc)
	if len(lines) < 2:
		return []
	return [{"fieldname": "contract_item", "label": "Job line", "fieldtype": "Select", "reqd": 1, "default": "",
		"choices": [{"value": "", "label": _("Select the job line")}] + [{"value": l.name,
			"label": _("#{0} {1} ({2} of {3} jobs open)").format(l.idx, " @ ".join(x for x in [l.job_type_name or l.job_type, l.location] if x),
				f"{flt(l.remaining, 3):g}", f"{flt(l.qty, 3):g}")} for l in lines]}]


@frappe.whitelist()
def get_jcr_lines(hire_order_contract: str):
	"""The job lines a new JCR takes from its Hire Order Contract (every job not yet reported)."""
	from thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract import make_jcr

	return [_clean(d.as_dict()) for d in make_jcr(hire_order_contract).job_lines]


@frappe.whitelist()
def make_site_from_quotation(source_name: str, target_doc=None):
	"""Quotation -> Rental Site, as Quotation > Create > Rental Site does in the desk: the Customer
	(made from the Lead if the quotation is still addressed to one), the company and the quotation."""
	from thinknxg_rental.services.deal_flow import make_customer_from_quotation

	quotation = frappe.get_doc("Quotation", source_name)
	quotation.check_permission("read")
	customer = make_customer_from_quotation(source_name)
	site = frappe.new_doc("Rental Site")
	site.update({
		"customer": customer,
		"customer_name": frappe.db.get_value("Customer", customer, "customer_name"),
		"company": quotation.company,
		"project": quotation.get("project"),
		"nxg_quotation": quotation.name,
	})
	return site


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


def entry_nav(menu="main"):
	"""Entry menus the user may read, in menu order. menu="more" gives the optional documents."""
	return [
		frappe._dict(key=key, route=f"/rental/admin/entries?type={key}", label=_(cfg.get("nav_label") or cfg["plural"]))
		for key, cfg in ENTRY_TYPES.items()
		if cfg.get("menu", "main") == menu and frappe.has_permission(cfg["doctype"], "read")
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
		"create": item.get("create"),
		"loads": item.get("loads"),
	}
	if df.fieldtype == "Select":
		spec["choices"] = [o for o in (df.options or "").split("\n")]
	if table:
		spec["w"] = flt(item.get("w")) or 1
		# a new row starts with the field's plain default (Rotation 1, Rate Basis Monthly), as in the desk grid
		if df.default and df.fieldtype in ("Int", "Float", "Currency", "Percent", "Check", "Select") and not str(df.default).startswith(("eval:", ":")):
			spec["default"] = df.default
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
		tables.append({"fieldname": df.fieldname, "label": _(df.label), "readonly": cint(t.get("readonly")), "no_add": cint(t.get("no_add")),
			"columns": columns, "calc": t.get("calc") or []})
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


def _matches(action, doc):
	for field, values in (action.get("when") or {}).items():
		if doc.get(field) not in values:
			return False
	return not action.get("when_fn") or bool(action["when_fn"](doc))


def _print_url(doctype, name):
	return "/printview?" + urlencode({"doctype": doctype, "name": name, "trigger_print": 1})


def get_print_links(cfg, doc):
	"""Print buttons for a saved document (its default print format, in a new tab), and for documents
	it made (the Cross Hire Order's Purchase Order)."""
	if doc.is_new() or not cfg.get("print"):
		return []
	links = []
	if frappe.has_permission(doc.doctype, "print", doc=doc):
		links.append({"label": _("Print"), "url": _print_url(doc.doctype, doc.name)})
	for doctype, field in cfg.get("print_links", []):
		name = doc.get(field)
		if name and frappe.has_permission(doctype, "print", doc=name):
			links.append({"label": _("Print {0}").format(_(doctype)), "url": _print_url(doctype, name)})
	return links


def _ask(action, doc):
	"""The values an action asks for before it runs (a date, a reason, which job line)."""
	ask = action.get("ask") or []
	ask = ask(doc) if callable(ask) else ask
	return [dict(s, label=_(s["label"])) for s in ask]


def get_next_actions(key, cfg, doc):
	"""Buttons on a saved document. Three kinds: a mapper that opens the next document unsaved here
	(method), a link to a new document with values carried over (prefill), and an action that runs on
	this document or for it and stays here (call: a method of the document, fn: a module function),
	optionally after asking for a few values."""
	actions = []
	if doc.is_new():
		return actions
	for i, a in enumerate(cfg.get("next", [])):
		if not _matches(a, doc):
			continue
		if a.get("call") or a.get("fn"):
			if not doc.has_permission(a.get("perm", "write")):
				continue
			actions.append({"label": _(a["label"]), "run": f"{key}:{i}", "source": doc.name, "ask": _ask(a, doc),
				"confirm": _(a["confirm"]) if a.get("confirm") else None})
			continue
		target = ENTRY_TYPES[a["target"]]
		if not frappe.has_permission(target["doctype"], "create"):
			continue
		if a.get("method"):
			actions.append({"label": _(a["label"]), "make": f"{key}:{i}", "source": doc.name, "ask": _ask(a, doc)})
		else:
			values = {k: (v(doc) if callable(v) else doc.get(v)) for k, v in a["prefill"].items()}
			actions.append({"label": _(a["label"]), "url": entry_url(a["target"], **values)})
	return actions


@frappe.whitelist(methods=["POST"])
def run_action(action: str, source: str, values: str | dict | None = None):
	"""Run a call/fn action from get_next_actions. Only the configured method runs, only with the values
	the action asks for, and only while the document still qualifies for the button."""
	key, _sep, idx = action.partition(":")
	cfg = get_entry_type(key)
	actions = cfg.get("next", [])
	if cint(idx) >= len(actions) or not (actions[cint(idx)].get("call") or actions[cint(idx)].get("fn")):
		frappe.throw(_("Unknown action"))
	a = actions[cint(idx)]
	doc = frappe.get_doc(cfg["doctype"], source)
	doc.check_permission(a.get("perm", "write"))
	if not _matches(a, doc):
		frappe.throw(_("{0} is no longer available for {1}. Reload the page.").format(_(a["label"]), source))
	values = (frappe.parse_json(values) if isinstance(values, str) else values) or {}
	kwargs = {}
	for spec in _ask(a, doc):
		value = values.get(spec["fieldname"])
		if value in (None, ""):
			if spec.get("reqd"):
				frappe.throw(_("{0} is required").format(spec["label"]))
			continue
		kwargs[spec["fieldname"]] = value
	if a.get("call"):
		result = getattr(doc, a["call"])(**kwargs)
	else:
		result = frappe.get_attr(a["fn"])(**{a.get("source_arg", "source_name"): source}, **kwargs)
	opens = a.get("opens")
	if opens and result:
		name = result if isinstance(result, str) else result.get("name")
		if opens in ENTRY_TYPES:
			return {"url": entry_url(opens, name)}
		return {"url": f"/app/{opens.lower().replace(' ', '-')}/{quote(name)}"}
	return {"url": entry_url(key, source), "message": _(a.get("done") or "{0}: done.").format(source)}


# ----------------------------------------------------------------------------- related documents
def linked(doctype, filters, fields, entry=None, order_by="creation desc", limit=50):
	"""Rows of another document type for a form's related list. entry is the portal menu that opens
	them (else the desk form). Rows the user may not read are left out by frappe.get_list."""
	if not frappe.has_permission(doctype, "read"):
		return []
	rows = frappe.get_list(doctype, filters=filters, fields=list(dict.fromkeys(["name", "docstatus", *fields])),
		order_by=order_by, limit_page_length=limit)
	for r in rows:
		r.url = entry_url(entry, r.name) if entry else f"/app/{doctype.lower().replace(' ', '-')}/{quote(r.name)}"
		r.status = r.get("status") or ("Draft" if r.docstatus == 0 else "Submitted" if r.docstatus == 1 else "Cancelled")
	return rows


def get_related(cfg, doc):
	"""Lists of the documents made from or for this one (JCRs of a Hire Order Contract, deliveries of a
	contract, ...), each row linking to its own form. columns: (fieldname, label, fieldtype)."""
	if doc.is_new():
		return []
	out = []
	for r in cfg.get("related", []):
		rows = r["rows"](doc)
		if not rows:
			continue
		out.append({"label": _(r["label"]), "columns": [{"fieldname": f, "label": _(l), "fieldtype": t} for f, l, t in r["columns"]],
			"rows": frappe.parse_json(frappe.as_json(rows))})
	return out


def entry_links():
	"""DocType -> portal menu, so a read-only link on a form opens the linked document in the portal."""
	out = {}
	for key, cfg in ENTRY_TYPES.items():
		if cfg["doctype"] not in out and cfg.get("link", True) and frappe.has_permission(cfg["doctype"], "read"):
			out[cfg["doctype"]] = key
	return out


def _asked_values(action, doc, values):
	"""The values the user gave for an action's ask panel: only the asked fields, required ones present,
	and a choice list value one of its choices."""
	values = (frappe.parse_json(values) if isinstance(values, str) else values) or {}
	out = {}
	for spec in _ask(action, doc):
		value = values.get(spec["fieldname"])
		if value in (None, ""):
			if spec.get("reqd"):
				frappe.throw(_("Select {0} first").format(spec["label"]) if spec["fieldtype"] == "Select" else _("{0} is required").format(spec["label"]))
			continue
		choices = [c["value"] if isinstance(c, dict) else c for c in spec.get("choices") or []]
		if choices and value not in choices:
			frappe.throw(_("{0}: {1} is not one of the choices. Reload the page and try again.").format(spec["label"], value))
		out[spec["fieldname"]] = value
	return out


def _mapped(make, source, values=None):
	"""The unsaved document an existing mapper (Lead -> Quotation, Hire Order -> Rental Contract, ...) builds.
	source is the document the button was on. An action with source_field maps from a document it links
	to instead (Rental Site -> its quotation), and args are read from it (the site goes to the Hire Order).
	values are the answers to the action's ask panel (the job line of a JCR); they go to the mapper in args."""
	src_key, _sep, idx = (make or "").partition(":")
	cfg = get_entry_type(src_key)
	action = cfg["next"][cint(idx)]
	kwargs = {"source_name": source}
	if action.get("source_field") or action.get("args") or action.get("ask"):
		current = frappe.get_doc(cfg["doctype"], source)
		current.check_permission("read")
		if action.get("source_field"):
			kwargs["source_name"] = current.get(action["source_field"])
		args = {k: current.get(v) for k, v in (action.get("args") or {}).items()}
		args.update(_asked_values(action, current, values) if action.get("ask") else {})
		if args:
			kwargs["args"] = json.dumps(args)
	doc = frappe.get_attr(action["method"])(**kwargs)
	if isinstance(doc, dict):
		doc = frappe.get_doc(doc)
	return doc


@frappe.whitelist(methods=["POST"])
def prepare_mapped(make: str, source: str, values: str | dict | None = None):
	"""Run the mapper once in a POST, so what it creates on the way (the Customer made from a Lead)
	is committed; the form page then maps again, finds that record and shows the unsaved document."""
	src_key, _sep, idx = make.partition(":")
	action = get_entry_type(src_key)["next"][cint(idx)]
	target = action["target"]
	frappe.has_permission(ENTRY_TYPES[target]["doctype"], "create", throw=True)
	if action.get("creates"):
		# a method that saves the new document itself: open that document
		return {"url": entry_url(target, frappe.get_attr(action["method"])(**{action["creates"]: source}))}
	_mapped(make, source, values)
	values = (frappe.parse_json(values) if isinstance(values, str) else values) or {}
	return {"url": entry_url(target, make=make, source=source, args=json.dumps(values) if values else None)}


def get_form_boot(key, name=None, form_dict=None):
	cfg = get_entry_type(key)
	form_dict = form_dict or {}
	doctype = cfg["doctype"]
	if name:
		doc = frappe.get_doc(doctype, name)
		doc.check_permission("read")
	elif form_dict.get("make") and form_dict.get("source"):
		frappe.has_permission(doctype, "create", throw=True)
		doc = _mapped(form_dict.get("make"), form_dict.get("source"), form_dict.get("args"))
	else:
		frappe.has_permission(doctype, "create", throw=True)
		doc = frappe.new_doc(doctype)
		for field in cfg.get("prefill", []):
			if form_dict.get(field):
				doc.set(field, form_dict.get(field))
	if doc.is_new():
		_apply_fetches(doc, cfg)
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
		related=get_related(cfg, doc),
		links=entry_links(),
		prints=get_print_links(cfg, doc),
		invoice=bool(cfg.get("invoice") and doc.docstatus == 1 and doc.get("status") not in ("Completed", "Cancelled")
			and frappe.has_permission("Sales Invoice", "create")),
		desk_url=f"/app/{doctype.lower().replace(' ', '-')}" + (f"/{quote(doc.name)}" if not doc.is_new() else "/new"),
		list_url=cfg.get("list_url") or f"/rental/admin/entries?type={key}",
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


def _apply_fetches(doc, cfg):
	"""A new document opened from a button carries only its links (the Rental Contract on a Delivery
	Order, the Hire Order Contract on a JCR). Show what those links bring along straight away:
	customer name, site, project, rather than only after the first save."""
	meta = frappe.get_meta(cfg["doctype"])
	for item in cfg["header"]:
		if isinstance(item, str) or not item.get("fetch") or not doc.get(item["fieldname"]):
			continue
		df = meta.get_field(item["fieldname"])
		doctype = item.get("link") or (df and df.options)
		if not doctype or not frappe.has_permission(doctype, "read"):
			continue
		missing = {k: v for k, v in item["fetch"].items() if not doc.get(k) and meta.has_field(k)}
		if not missing:
			continue
		values = frappe.db.get_value(doctype, doc.get(item["fieldname"]), list(set(missing.values())), as_dict=True) or {}
		for target, source in missing.items():
			if values.get(source):
				doc.set(target, values[source])


@frappe.whitelist()
def get_tax_rows(taxes_and_charges: str, doctype: str | None = None):
	"""The tax rows of a Sales Taxes and Charges Template, as ERPNext copies them into a document."""
	from erpnext.controllers.accounts_controller import get_taxes_and_charges

	return get_taxes_and_charges("Sales Taxes and Charges Template", taxes_and_charges) or []


def _set_missing(doc):
	# Selling documents fill currency, price list, item rates and taxes the way the desk form does.
	if doc.doctype in ("Quotation", "Sales Order", "Sales Invoice") and hasattr(doc, "set_missing_values"):
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
