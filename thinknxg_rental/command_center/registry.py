"""thinkNXG Rental Command Center: what the staff application shows, and where.

The Command Center (/rental/admin) is a single-page application. This module is its map:
the sidebar groups and items, the list views behind each item, and the Quick Create menu.

Nothing here holds data or business rules. A "view" says which existing DocType, report or board
an item opens. Documents that the admin portal can already enter (portal/entry.py ENTRY_TYPES)
open in the shared document form, which saves through the real DocType with the user's own
permissions. Everything else lists real records and opens them in the desk.

Item keys are also URL paths: /rental/admin/<path>, and /rental/admin/<path>/<name> for a document.
"""
import frappe
from frappe import _

STAFF_ROLES = ("System Manager", "Rental Manager", "Rental User", "Subcontracting Manager", "Subcontracting Executive", "Site Engineer")

# ----------------------------------------------------------------------------- list views
# kind="entry": a document of portal/entry.py ENTRY_TYPES (list here, form in the Command Center).
# kind="doctype": any other DocType (list here, opens in the desk).
# filters: fixed filters of the view. columns: extra list columns (fieldname, label).
# date_field: the field the date filter works on. party: the customer / supplier field to filter on.
# tabs: named quick filters shown above the list (label, filters).
LIVE = ["Active", "On Hire", "Off Hired"]
VIEWS = {
	"sales/leads": dict(kind="entry", entry="lead", date_field="creation",
		tabs=[("Open", {"status": ["not in", ["Converted", "Do Not Contact"]]}), ("Converted", {"status": "Converted"}), ("All", {})]),
	"sales/quotations": dict(kind="entry", entry="quotation", date_field="transaction_date", party="party_name",
		columns=[("valid_till", "Valid till"), ("status", "Status")]),
	"customers": dict(kind="customers"),
	"sites": dict(kind="entry", entry="rental-site", party="customer", tabs=[("Active", {"disabled": 0}), ("Disabled", {"disabled": 1}), ("All", {})]),
	"hire-orders": dict(kind="entry", entry="hire-order", date_field="order_date", party="customer",
		columns=[("total_shortfall_qty", "Shortfall")]),
	"hire-contracts": dict(kind="entry", entry="hire-order-contract", date_field="order_date", party="customer"),
	"contracts": dict(kind="entry", entry="rental-contract", date_field="start_date", party="customer",
		columns=[("total_at_site_qty", "At site"), ("last_billed_upto", "Billed up to")],
		tabs=[("Live", {"docstatus": 1, "status": ["in", LIVE]}), ("Past end date", {"docstatus": 1, "status": "On Hire", "end_date": ["<", "$today"]}),
			("Drafts", {"docstatus": 0}), ("Completed", {"status": "Completed"}), ("All", {})]),
	"jcr": dict(kind="entry", entry="jcr", date_field="creation", party="customer",
		tabs=[("Standing", {"docstatus": 1, "status": ["in", ["Within Contract", "In Excess"]]}), ("Drafts", {"docstatus": 0}), ("All", {})]),
	"deliveries": dict(kind="entry", entry="delivery-order", date_field="posting_date", party="customer"),
	"off-hire": dict(kind="entry", entry="off-hire-note", date_field="return_date", party="customer",
		columns=[("inspection_status", "Inspection")],
		tabs=[("Inspection pending", {"docstatus": 1, "inspection_status": "Pending"}), ("Drafts", {"docstatus": 0}), ("All", {})]),
	"reservations": dict(kind="entry", entry="material-reservation", date_field="reservation_date", party="customer"),
	"inspections": dict(kind="entry", entry="return-inspection", date_field="inspection_date", party="customer"),
	"settlements": dict(kind="entry", entry="damage-settlement", date_field="posting_date", party="customer",
		tabs=[("To invoice", {"docstatus": 1, "status": "To Invoice"}), ("Drafts", {"docstatus": 0}), ("All", {})]),
	"cross-hire": dict(kind="entry", entry="cross-hire-order", date_field="order_date", party="supplier",
		columns=[("expected_return_date", "Due back")],
		tabs=[("Open", {"docstatus": 1, "status": ["not in", ["Completed", "Cancelled"]]}), ("Drafts", {"docstatus": 0}), ("All", {})]),
	"cross-hire-receipts": dict(kind="entry", entry="cross-hire-receipt", date_field="posting_date", party="supplier",
		filters={"nxg_is_cross_hire_receipt": 1, "is_return": 0}, columns=[("nxg_cross_hire_order", "Cross hire order")]),
	"supplier-off-hire": dict(kind="entry", entry="cross-hire-off-hire", date_field="off_hire_date", party="supplier"),
	"supplier-bills": dict(kind="doctype", doctype="Purchase Invoice", label="Supplier Hire Bills", date_field="posting_date",
		party="supplier", filters={"nxg_cross_hire_order": ["is", "set"]}, search=["supplier_name", "supplier", "nxg_cross_hire_order", "bill_no"],
		columns=[("supplier_name", "Supplier"), ("nxg_cross_hire_order", "Cross hire order"), ("posting_date", "Date"),
			("grand_total", "Total"), ("outstanding_amount", "Outstanding")]),
	"invoices": dict(kind="entry", entry="sales-invoice", date_field="posting_date", party="customer",
		columns=[("due_date", "Due"), ("outstanding_amount", "Outstanding")],
		tabs=[("Rental", {"nxg_rental_contract": ["is", "set"]}), ("Unpaid", {"docstatus": 1, "outstanding_amount": [">", 0]}),
			("Drafts", {"docstatus": 0}), ("All", {})]),
	"billing-schedules": dict(kind="doctype", doctype="Rental Billing Schedule", label="Billing Schedules", date_field="from_date",
		party="customer", search=["rental_contract", "customer_name", "sales_invoice"],
		columns=[("rental_contract", "Contract"), ("customer_name", "Customer"), ("from_date", "From"), ("to_date", "To"),
			("total_amount", "Amount"), ("sales_invoice", "Sales Invoice")]),
	"jcr-billing": dict(kind="doctype", doctype="JCR Billing Schedule", label="JCR Billing Periods", date_field="period_from",
		party="customer", search=["jcr", "customer", "sales_invoice"],
		columns=[("jcr", "JCR"), ("customer", "Customer"), ("billing_type", "Charge"), ("period_from", "From"), ("period_to", "To"),
			("amount", "Amount"), ("sales_invoice", "Sales Invoice")],
		tabs=[("Pending", {"status": "Pending"}), ("All", {})]),
	"item-profiles": dict(kind="doctype", doctype="Rental Item Profile", label="Rental Item Profiles", search=["item", "item_name", "category"],
		columns=[("item_name", "Item"), ("category", "Category"), ("monthly_rate", "Monthly rate"), ("replacement_value", "Replacement value"),
			("repair_charge", "Repair / unit"), ("lost_charge", "Lost / unit"), ("beyond_repair_charge", "Beyond repair / unit")]),
	"items": dict(kind="doctype", doctype="Item", label="Items", search=["item_code", "item_name", "item_group"],
		filters={"disabled": 0}, columns=[("item_name", "Item name"), ("item_group", "Item group"), ("stock_uom", "UOM"), ("is_stock_item", "Stock item")]),
	"warehouses": dict(kind="doctype", doctype="Warehouse", label="Warehouses", search=["warehouse_name", "parent_warehouse"],
		columns=[("warehouse_name", "Warehouse"), ("parent_warehouse", "Parent"), ("is_group", "Group"), ("company", "Company")]),
	"users": dict(kind="users"),
	# public website enquiries (website/api.py): followed up into quotations by staff
	"website-enquiries": dict(kind="doctype", doctype="Rental Website Enquiry", label="Website Enquiries", date_field="enquiry_date",
		party="customer", search=["full_name", "company_name", "email", "subject"],
		columns=[("full_name", "Name"), ("company_name", "Company"), ("enquiry_type", "Type"), ("enquiry_date", "Date"), ("status", "Status")],
		tabs=[("Open", {"status": ["in", ["New", "In Review"]]}), ("Quoted", {"status": "Quoted"}), ("All", {})]),
	# excess material (services/excess.py): the register lists, the documents open in the shared form
	"excess/register": dict(kind="doctype", doctype="Excess Material Register", label="Excess Material Register", date_field="posting_date",
		party="customer", search=["customer_name", "item_code", "hire_off_hire_note", "rental_contract"],
		columns=[("customer_name", "Customer"), ("item_code", "Item"), ("excess_qty", "Received"), ("available_qty", "Held for customer"),
			("convertible_qty", "To convert"), ("status", "Status")],
		tabs=[("Held for customer", {"available_qty": [">", 0], "status": ["!=", "Cancelled"]}),
			("To convert", {"convertible_qty": [">", 0], "status": ["!=", "Cancelled"]}), ("All", {})]),
	"excess/returns": dict(kind="entry", entry="excess-return-note", date_field="posting_date", party="customer"),
	"excess/dismantling": dict(kind="entry", entry="dismantling-entry", date_field="posting_date", party="customer",
		tabs=[("Drafts", {"docstatus": 0}), ("Submitted", {"docstatus": 1}), ("All", {})]),
	"excess/abandonment": dict(kind="entry", entry="excess-abandonment", date_field="posting_date", party="customer",
		tabs=[("Awaiting approval", {"docstatus": 0}), ("Approved", {"docstatus": 1}), ("All", {})]),
	"excess/conversion": dict(kind="entry", entry="excess-conversion", date_field="posting_date", party="customer"),
	# pro forma invoices and the money held for customers (services/deposits.py): documents in the shared form
	"finance/pro-forma": dict(kind="entry", entry="pro-forma-invoice", date_field="posting_date", party="customer",
		columns=[("hire_order", "Hire order"), ("grand_total_payable", "Payable")],
		tabs=[("Open", {"docstatus": 1, "status": ["in", ["Approved", "Sent to Customer", "Customer Accepted", "Advance Received"]]}),
			("Awaiting approval", {"docstatus": 0, "status": "Submitted for Approval"}), ("Drafts", {"docstatus": 0, "status": "Draft"}),
			("Converted", {"status": "Converted to Sales Invoice"}), ("Expired", {"status": "Expired"}), ("All", {})]),
	"finance/deposits": dict(kind="entry", entry="contract-payment", date_field="posting_date", party="customer",
		columns=[("rental_contract", "Contract"), ("mode_of_payment", "Paid by"), ("sales_invoice", "Against invoice")],
		tabs=[("Deposits", {"docstatus": 1, "transaction_type": ["in", ["Deposit Collection", "Deposit Refund", "Deposit Deduction"]]}),
			("Advances", {"docstatus": 1, "transaction_type": ["in", ["Advance Collection", "Advance Adjustment", "Advance Refund"]]}),
			("Pending approval", {"docstatus": 0, "status": "Pending Approval"}),
			("Drafts", {"docstatus": 0}), ("All", {})]),
}

# ----------------------------------------------------------------------------- subcontracting
_SC_OPEN = {"docstatus": 0, "status": ["in", ["Submitted", "Under Review"]]}


def _scv(doctype, label, columns, tabs=None, date_field="creation", search=None, filters=None):
	return dict(kind="doctype", doctype=doctype, label=label, date_field=date_field, party="supplier", columns=columns,
		search=search or ["name", "supplier", "subcontract_work_order"], tabs=tabs, filters=filters or {})


VIEWS.update({
	"subcontracting/agreements": _scv("Subcontract Agreement", "Agreements & Rate Contracts", [("supplier_name", "Subcontractor"),
		("agreement_type", "Type"), ("project", "Project"), ("start_date", "From"), ("end_date", "To"), ("contract_value", "Value"), ("status", "Status")],
		[("Active", {"status": "Active"}), ("Awaiting approval", {"status": "Pending Approval"}), ("Drafts", {"status": "Draft"}), ("All", {})],
		"start_date", ["name", "supplier_name", "project", "title"]),
	"subcontracting/daily-progress": _scv("Subcontract Daily Progress", "Work Progress Reports", [("subcontract_work_order", "Work order"),
		("supplier_name", "Subcontractor"), ("report_date", "Date"), ("labour_deployed", "Labour"), ("delay_reported", "Delay"), ("source", "From"), ("status", "Status")],
		[("To review", {"docstatus": 0, "status": "Submitted"}), ("Approved", {"status": "Approved"}), ("All", {})], "report_date"),
	"subcontracting/material-requests": _scv("Subcontract Material Request", "Material Requests", [("subcontract_work_order", "Work order"),
		("supplier_name", "Subcontractor"), ("request_date", "Requested"), ("required_by", "Needed by"), ("source", "From"), ("status", "Status")],
		[("To approve", {"docstatus": 0, "status": "Submitted"}), ("To issue", {"status": ["in", ["Approved", "Partially Issued"]]}), ("All", {})], "request_date"),
	"subcontracting/material-issues": _scv("Subcontract Material Allocation", "Material Issues", [("subcontract_work_order", "Work order"),
		("supplier", "Subcontractor"), ("posting_date", "Date"), ("material_request", "Request"), ("received_by_subcontractor", "Receipt confirmed"),
		("shortage_reported", "Shortage")], [("Not confirmed", {"docstatus": 1, "received_by_subcontractor": 0}), ("Shortages", {"shortage_reported": 1}), ("All", {})],
		"posting_date"),
	"subcontracting/material-returns": _scv("Subcontract Material Return", "Material Returns", [("subcontract_work_order", "Work order"),
		("supplier", "Subcontractor"), ("posting_date", "Date"), ("total_recovery", "Recovery")], None, "posting_date"),
	"subcontracting/inspections": _scv("Subcontract Work Progress", "Work Inspections", [("subcontract_work_order", "Work order"),
		("supplier", "Subcontractor"), ("progress_date", "Date"), ("proposed_inspection_date", "Inspection date"), ("inspector", "Inspector"),
		("source", "From"), ("inspection_status", "Inspection")],
		[("Pending", {"docstatus": 0, "inspection_status": ["in", ["Inspection Requested", "Under Inspection"]]}),
			("Rework", {"inspection_status": "Rework Required"}), ("Rejected", {"inspection_status": "Rejected"}), ("All", {})], "progress_date"),
	"subcontracting/completion": _scv("Subcontract Completion Report", "Completion Certificates", [("subcontract_work_order", "Work order"),
		("supplier", "Subcontractor"), ("completion_date", "Completed"), ("certified_value", "Certified")], None, "completion_date"),
	"subcontracting/supplier-invoices": _scv("Subcontractor Invoice Submission", "Supplier Invoices", [("supplier_invoice_no", "Invoice no."),
		("supplier_name", "Subcontractor"), ("subcontract_work_order", "Work order"), ("supplier_invoice_date", "Invoice date"), ("total_claimed", "Claimed"),
		("purchase_invoice", "Purchase Invoice"), ("status", "Status")],
		[("To verify", {"docstatus": 0, "status": "Submitted"}), ("Verified", {"status": "Verified"}), ("Rejected", {"status": "Rejected"}), ("All", {})],
		"supplier_invoice_date", ["name", "supplier_invoice_no", "supplier_name", "subcontract_work_order"]),
	"subcontracting/settlements": _scv("Subcontract Settlement", "Progress Certificates & Settlements", [("subcontract_work_order", "Work order"),
		("supplier", "Subcontractor"), ("posting_date", "Date"), ("settlement_type", "Type"), ("certified_value", "Certified"), ("retention_amount", "Retention"),
		("final_payable", "Payable"), ("purchase_invoice", "Purchase Invoice"), ("outstanding", "Outstanding")], None, "posting_date"),
	"subcontracting/payments": _scv("Payment Entry", "Subcontractor Payments", [("party_name", "Subcontractor"), ("subcontract_work_order", "Work order"),
		("posting_date", "Date"), ("paid_amount", "Amount"), ("reference_no", "Reference"), ("unallocated_amount", "Unallocated (advance)")],
		None, "posting_date", ["name", "party_name", "subcontract_work_order", "reference_no"], {"subcontract_work_order": ["is", "set"], "payment_type": "Pay"}),
	"subcontracting/variations": _scv("Subcontract Variation", "Variations & Claims", [("subcontract_work_order", "Work order"),
		("supplier_name", "Subcontractor"), ("variation_type", "Type"), ("request_date", "Requested"), ("value_change", "Value change"), ("source", "From"),
		("status", "Status")], [("To decide", _SC_OPEN), ("Approved", {"status": "Approved"}), ("All", {})], "request_date"),
	"subcontracting/portal-access": _scv("Subcontractor Portal Access", "Portal Users", [("full_name", "Name"), ("supplier_name", "Subcontractor"),
		("email", "Email"), ("access_level", "Access"), ("enabled", "Enabled"), ("last_access", "Last access")],
		[("Enabled", {"enabled": 1}), ("Suspended", {"enabled": 0}), ("All", {})], None, ["full_name", "email", "supplier_name"]),
	"subcontracting/messages": _scv("Subcontract Message", "Subcontractor Messages", [("supplier", "Subcontractor"), ("subcontract_work_order", "Work order"),
		("direction", "Direction"), ("subject", "Subject"), ("sender_name", "From"), ("read_by_staff", "Read")],
		[("Unread", {"direction": "From Subcontractor", "read_by_staff": 0}), ("All", {})], "creation", ["supplier", "subject", "subcontract_work_order"]),
})

# ----------------------------------------------------------------------------- sidebar
# (key, label, icon, kind of page). Icons are Lucide names (Frappe ships the sprite).
NAV = [
	("main", "Main", [
		("dashboard", "Dashboard", "layout-dashboard", "dashboard"),
		("notifications", "Notifications", "bell", "notifications"),
		("tasks", "My Tasks", "list-checks", "tasks"),
	]),
	("sales", "Sales & enquiries", [
		("sales/leads", "Leads", "user-plus", "list"),
		("sales/quotations", "Quotations", "file-text", "list"),
		("customers", "Customers", "building-2", "list"),
		("sites", "Rental Sites", "map-pin", "list"),
		("requests", "Customer Requests", "inbox", "requests"),
		("website-enquiries", "Website Enquiries", "globe", "list"),
	]),
	("operations", "Rental operations", [
		("hire-orders", "Hire Orders", "clipboard-list", "list"),
		("hire-contracts", "Hire Order Contracts", "signature", "list"),
		("contracts", "Rental Contracts", "file-check-2", "list"),
		("jcr", "Job Completion Reports", "hard-hat", "list"),
		("deliveries", "Delivery Orders", "truck", "list"),
		("off-hire", "Off-Hire Notes", "undo-2", "list"),
	]),
	("yard", "Inventory & yard", [
		("reservations", "Material Reservations", "bookmark", "list"),
		("inventory", "Rental Yard", "warehouse", "inventory"),
		("material-at-site", "Material at Customer Sites", "construction", "material"),
		("inspections", "Return Inspections", "search-check", "list"),
		("settlements", "Damage Settlements", "shield-alert", "list"),
		("reports/stock-availability", "Rental Stock Position", "boxes", "report"),
		("reports/rental-inventory", "Inventory by Warehouse", "warehouse", "report"),
	]),
	("excess", "Excess material", [
		("excess/register", "Excess Material Register", "package", "list"),
		("excess/returns", "Excess Returns", "package-minus", "list"),
		("excess/dismantling", "Dismantling Entries", "scale", "list"),
		("excess/abandonment", "Abandonments", "package-x", "list"),
		("excess/conversion", "Conversions to Stock", "package-plus", "list"),
		("reports/project-reconciliation", "Material Reconciliation", "list-checks", "report"),
		("reports/outstanding-materials", "Outstanding Materials", "clipboard-list", "report"),
	]),
	("crosshire", "Cross hire", [
		("cross-hire", "Cross Hire Orders", "arrow-left-right", "list"),
		("cross-hire-receipts", "Cross Hire Receipts", "package-check", "list"),
		("supplier-off-hire", "Supplier Off-Hire", "package-minus", "list"),
		("supplier-bills", "Supplier Hire Bills", "receipt", "list"),
		("supplier-position", "Supplier Position", "factory", "suppliers"),
	]),
	("subcontracting", "Subcontracting", [
		("subcontracting", "Overview", "layout-dashboard", "sc-overview"),
		("subcontracting/subcontractors", "Subcontractors", "hard-hat", "sc-subcontractors"),
		("subcontracting/agreements", "Agreements & Rate Contracts", "signature", "list"),
		("subcontracting/work-orders", "Work Orders", "clipboard-list", "sc-work-orders"),
		("subcontracting/daily-progress", "Work Progress", "trending-up", "list"),
		("subcontracting/material-requests", "Material Requests", "package-plus", "list"),
		("subcontracting/material-issues", "Material Issues", "package-check", "list"),
		("subcontracting/material-returns", "Material Returns", "package-minus", "list"),
		("subcontracting/inspections", "Work Inspections", "search-check", "list"),
		("subcontracting/completion", "Completion Certificates", "badge-check", "list"),
		("subcontracting/settlements", "Progress Certificates", "file-check-2", "list"),
		("subcontracting/supplier-invoices", "Supplier Invoices", "receipt", "list"),
		("subcontracting/payments", "Payments", "wallet", "list"),
		("subcontracting/variations", "Variations & Claims", "git-pull-request", "list"),
		("subcontracting/messages", "Messages", "message-square", "list"),
		("subcontracting/compare", "Performance & Comparison", "chart-bar", "sc-compare"),
		("subcontracting/portal-access", "Portal Users", "key-round", "list"),
		("reports/sc-register", "Subcontractor Register", "file-chart-column", "report"),
	]),
	("finance", "Billing & finance", [
		("billing", "Rental Billing", "calendar-clock", "billing"),
		("reports/unbilled", "Unbilled Rental", "hourglass", "report"),
		("invoices", "Sales Invoices", "file-spreadsheet", "list"),
		("outstanding", "Outstanding Payments", "wallet", "outstanding"),
		("reports/damage-loss", "Damage & Loss Recovery", "hammer", "report"),
	]),
	("deposits", "Pro forma, deposits & advances", [
		("finance/pro-forma", "Pro Forma Invoices", "receipt-text", "list"),
		("finance/deposits", "Deposits & Advances", "piggy-bank", "list"),
		("reports/deposits-by-contract", "Deposits by Contract", "file-check", "report"),
		("reports/deposits-by-customer", "Deposits by Customer", "building-2", "report"),
		("reports/deposits-outstanding", "Outstanding Deposits", "hourglass", "report"),
		("reports/deposit-refunds", "Deposit Refunds", "undo-2", "report"),
		("reports/deposit-ledger", "Deposit Liability Ledger", "book-open", "report"),
		("reports/advances", "Customer Advances", "wallet", "report"),
		("reports/advances-unutilized", "Unutilized Advances", "coins", "report"),
		("reports/advance-adjustments", "Advance Adjustments", "arrow-right-left", "report"),
		("reports/advance-ledger", "Advance Liability Ledger", "book-open-check", "report"),
	]),
	("reports", "Reports & analytics", [
		("utilization", "Rental Utilization", "gauge", "utilization"),
		("reports/material-at-site", "Material at Site", "map", "report"),
		("reports/stock-availability", "Stock Availability", "package-search", "report"),
		("reports/cross-hire-position", "Cross Hire Position", "repeat", "report"),
		("reports/rental-inventory", "Inventory by Warehouse", "warehouse", "report"),
		("reports/contract-profitability", "Contract Profitability", "trending-up", "report"),
		("reports/damage-loss", "Damage and Loss Register", "clipboard-x", "report"),
		("reports/excess-register", "Excess Material Register", "package", "report"),
		("reports/customer-excess", "Customer-wise Excess", "users", "report"),
		("billing-schedules", "Billing Reports", "calendar-range", "list"),
	]),
	("system", "System", [
		("settings", "Rental Settings", "settings", "settings"),
		("item-profiles", "Rental Item Profiles", "tag", "list"),
		("items", "Items", "package", "list"),
		("warehouses", "Warehouses", "warehouse", "list"),
		("users", "Users & Roles", "users", "users"),
		("desk", "Open thinkNXG Desk", "external-link", "desk"),
	]),
]

REPORTS = {
	"reports/material-at-site": "Material at Site",
	"reports/stock-availability": "Rental Stock Position",
	"reports/cross-hire-position": "Cross Hire Position",
	"reports/rental-inventory": "Rental Inventory",
	"reports/unbilled": "Unbilled Rental",
	"reports/damage-loss": "Damage and Loss Register",
	"reports/contract-profitability": "Hire Contract Profitability",
	"reports/excess-register": "Excess Material Register",
	"reports/customer-excess": "Customer-wise Excess Material",
	"reports/project-reconciliation": "Project-wise Material Reconciliation",
	"reports/outstanding-materials": "Outstanding Customer Materials",
	"reports/deposits-by-contract": "Contract-wise Security Deposit",
	"reports/deposits-by-customer": "Customer-wise Security Deposit",
	"reports/deposits-outstanding": "Outstanding Security Deposit",
	"reports/deposit-refunds": "Security Deposit Refund Report",
	"reports/deposit-ledger": "Security Deposit Liability Ledger",
	"reports/advances": "Customer Advance Report",
	"reports/advances-unutilized": "Unutilized Advance Report",
	"reports/advance-adjustments": "Advance Adjustment Report",
	"reports/advance-ledger": "Customer Advance Liability Ledger",
	"reports/sc-register": "Subcontractor Register",
	"reports/sc-work-orders": "Subcontractor Wise Work Orders",
	"reports/sc-hoc": "HOC Wise Subcontracting",
	"reports/sc-outstanding": "Outstanding Subcontractor Payments",
	"reports/sc-payments": "Subcontractor Payments",
	"reports/sc-material": "Subcontract Material Issue and Return",
	"reports/sc-progress": "Subcontract Work Progress Report",
	"reports/sc-pending-completion": "Pending Completion Approval",
	"reports/sc-cost": "Subcontract Cost Analysis",
	"reports/sc-performance": "Subcontractor Performance",
	"reports/sc-profitability": "HOC Subcontract Profitability",
	"reports/sc-labour": "Subcontract Labour Cost",
	"reports/sc-equipment": "Subcontract Equipment Cost",
	"reports/subcontract-retention": "Subcontract Retention and Advance Outstanding",
	"reports/sc-variations": "Subcontract Variation Report",
	"reports/sc-statement": "Subcontractor Account Statement",
	"reports/sc-cost-monitor": "Subcontract Cost Monitor",
	"reports/sc-delayed": "Delayed Subcontract Work Orders",
	"reports/sc-invoices": "Subcontractor Invoice Register",
}

# The filters each report page offers (the same fields as the report's own filters in the desk).
# default: "$company" (Rental Settings company), "$today", "$year_start".
def _f(fieldname, label, fieldtype="Data", options=None, default=None):
	return dict(fieldname=fieldname, label=label, fieldtype=fieldtype, options=options, default=default)


REPORT_FILTERS = {
	"Material at Site": [_f("company", "Company", "Link", "Company", "$company"), _f("as_on_date", "As on", "Date"),
		_f("customer", "Customer", "Link", "Customer"), _f("rental_site", "Site", "Link", "Rental Site"),
		_f("rental_contract", "Rental contract", "Link", "Rental Contract"), _f("item_code", "Item", "Link", "Item"),
		_f("ownership", "Ownership", "Select", ["", "Own", "Cross Hire"]), _f("supplier", "Supplier", "Link", "Supplier"),
		_f("delivered_from", "Delivered from", "Link", "Warehouse"), _f("location", "Location", "Select", "$locations")],
	"Rental Stock Position": [_f("category", "Category", "Select", ["", "Formwork", "Scaffolding", "Shoring / Props", "Accessories", "Other"]),
		_f("item_code", "Item", "Link", "Item"), _f("location", "Location", "Select", "$locations"),
		_f("warehouse", "Warehouse", "Link", "Warehouse"), _f("group_by_warehouse", "Group by warehouse", "Check")],
	"Rental Inventory": [_f("location", "Location", "Select", "$locations"), _f("warehouse", "Warehouse", "Link", "Warehouse"),
		_f("item_code", "Item", "Link", "Item"), _f("ownership", "Ownership", "Select", ["", "Own", "Cross Hire"]),
		_f("supplier", "Supplier", "Link", "Supplier"),
		_f("stock_status", "Stock status", "Select", ["", "Available", "Reserved", "At Site", "In Custody", "Under Inspection", "In Repair", "Scrap"])],
	"Cross Hire Position": [_f("company", "Company", "Link", "Company", "$company"), _f("supplier", "Supplier", "Link", "Supplier"),
		_f("rental_contract", "Rental contract", "Link", "Rental Contract"), _f("item_code", "Item", "Link", "Item"),
		_f("location", "Location", "Select", "$locations"), _f("warehouse", "Cross hire warehouse", "Link", "Warehouse"),
		_f("include_closed", "Include closed orders", "Check")],
	"Unbilled Rental": [_f("company", "Company", "Link", "Company", "$company"), _f("upto_date", "Up to", "Date", default="$today"),
		_f("customer", "Customer", "Link", "Customer"), _f("show_zero", "Show fully billed contracts", "Check")],
	"Damage and Loss Register": [_f("company", "Company", "Link", "Company", "$company"),
		_f("from_date", "From", "Date", default="$year_start"), _f("to_date", "To", "Date", default="$today"),
		_f("customer", "Customer", "Link", "Customer"), _f("rental_contract", "Rental contract", "Link", "Rental Contract"),
		_f("classification", "Classification", "Select", ["", "Repairable", "Beyond Repair", "Lost"])],
	"Hire Contract Profitability": [_f("company", "Company", "Link", "Company", "$company"), _f("from_date", "Invoices from", "Date"),
		_f("to_date", "Invoices to", "Date"), _f("customer", "Customer", "Link", "Customer"),
		_f("status", "Status", "Select", ["", "Active", "On Hire", "Off Hired", "Completed"]), _f("show_zero", "Show contracts with no invoices", "Check")],
}

# deposit and advance reports (services/deposit_reports.py): the same filters as in the desk
_DEP_STATUS = ["", "Not Collected", "Partially Collected", "Fully Collected", "Partially Refunded", "Settled"]
_ADV_STATUS = ["", "Not Received", "Partially Received", "Fully Received", "Partially Utilized", "Fully Utilized", "Partially Refunded"]


def _money_filters(status_label=None, status=None):
	out = [_f("company", "Company", "Link", "Company", "$company"), _f("country", "Country", "Select", ["", "Oman", "United Arab Emirates"]),
		_f("customer", "Customer", "Link", "Customer"), _f("rental_contract", "Rental contract", "Link", "Rental Contract"),
		_f("from_date", "From", "Date"), _f("to_date", "To", "Date", default="$today")]
	if status:
		out.append(_f("status", status_label, "Select", status))
	return out


REPORT_FILTERS.update({
	"Contract-wise Security Deposit": _money_filters("Deposit status", _DEP_STATUS),
	"Customer-wise Security Deposit": _money_filters("Deposit status", _DEP_STATUS),
	"Outstanding Security Deposit": _money_filters("Deposit status", _DEP_STATUS),
	"Security Deposit Refund Report": _money_filters("Transaction", ["", "Deposit Refund", "Deposit Deduction"]),
	"Security Deposit Liability Ledger": _money_filters("Transaction", ["", "Deposit Collection", "Deposit Refund", "Deposit Deduction"]),
	"Customer Advance Report": _money_filters("Advance status", _ADV_STATUS),
	"Unutilized Advance Report": _money_filters("Advance status", _ADV_STATUS),
	"Advance Adjustment Report": _money_filters(),
	"Customer Advance Liability Ledger": _money_filters("Transaction", ["", "Advance Collection", "Advance Adjustment", "Advance Refund"]),
})

QUICK_CREATE = [
	("lead", "sales/leads"), ("quotation", "sales/quotations"), ("rental-site", "sites"), ("hire-order", "hire-orders"),
	("hire-order-contract", "hire-contracts"), ("rental-contract", "contracts"), ("delivery-order", "deliveries"),
	("off-hire-note", "off-hire"), ("material-reservation", "reservations"), ("cross-hire-order", "cross-hire"),
	("pro-forma-invoice", "finance/pro-forma"), ("contract-payment", "finance/deposits"),
]

# Old admin portal addresses, so bookmarks and desk links keep working.
LEGACY_ROUTES = {"yard": "inventory", "suppliers": "supplier-position", "board": "dashboard"}

# Badge counts beside sidebar items: (doctype, filters). Cheap counts, no lists.
BADGES = {
	"requests": ("Rental Portal Request", {"status": "Open"}),
	"off-hire": ("Hire Off-Hire Note", {"docstatus": 1, "inspection_status": "Pending"}),
	"settlements": ("Rental Damage Settlement", {"docstatus": 1, "status": "To Invoice"}),
	"deliveries": ("Hire Delivery Order", {"docstatus": 0}),
	"jcr-billing": ("JCR Billing Schedule", {"status": "Pending"}),
	"finance/pro-forma": ("Rental Pro Forma Invoice", {"docstatus": 0, "status": "Submitted for Approval"}),
	"finance/deposits": ("Rental Contract Payment", {"docstatus": 0, "status": "Pending Approval"}),
	"subcontracting/daily-progress": ("Subcontract Daily Progress", {"docstatus": 0, "status": "Submitted"}),
	"subcontracting/material-requests": ("Subcontract Material Request", {"docstatus": 0, "status": "Submitted"}),
	"subcontracting/inspections": ("Subcontract Work Progress", {"docstatus": 0, "inspection_status": "Inspection Requested"}),
	"subcontracting/supplier-invoices": ("Subcontractor Invoice Submission", {"docstatus": 0, "status": "Submitted"}),
	"subcontracting/variations": ("Subcontract Variation", {"docstatus": 0, "status": ["in", ["Submitted", "Under Review"]]}),
	"subcontracting/messages": ("Subcontract Message", {"direction": "From Subcontractor", "read_by_staff": 0}),
}


def is_staff(user=None):
	return bool(set(STAFF_ROLES) & set(frappe.get_roles(user or frappe.session.user)))


def check_staff():
	if frappe.session.user == "Guest":
		raise frappe.PermissionError(_("Log in to open the rental Command Center."))
	if not is_staff():
		raise frappe.PermissionError(_("The rental Command Center is for rental staff only."))


def entry_types():
	from thinknxg_rental.portal.entry import ENTRY_TYPES

	return ENTRY_TYPES


def view_doctype(key):
	view = VIEWS.get(key) or {}
	if view.get("kind") == "entry":
		return entry_types()[view["entry"]]["doctype"]
	return view.get("doctype")


def can_open(key, kind):
	"""Whether the logged-in user may see this sidebar item (server side; the API checks again)."""
	user_roles = set(frappe.get_roles())
	if kind in ("list",):
		if key == "customers":
			return frappe.has_permission("Customer", "read")
		if key == "users":
			return "System Manager" in user_roles
		doctype = view_doctype(key)
		return bool(doctype) and frappe.has_permission(doctype, "read")
	if kind == "users":
		return "System Manager" in user_roles
	if kind == "report":
		name = REPORTS[key]
		return frappe.db.exists("Report", name) and frappe.has_permission("Report", "read", name) and _report_roles_ok(name, user_roles)
	if kind == "requests":
		return frappe.has_permission("Rental Portal Request", "read")
	if kind in ("billing",):
		return frappe.has_permission("Rental Contract", "read")
	if kind == "outstanding":
		return frappe.has_permission("Sales Invoice", "read")
	if kind == "suppliers":
		return frappe.has_permission("Cross Hire Order", "read")
	if kind == "settings":
		return frappe.has_permission("Rental Settings", "read")
	if kind == "tasks":
		return frappe.has_permission("ToDo", "read")
	if kind in ("sc-overview", "sc-work-orders"):
		return frappe.has_permission("Subcontract Work Order", "read")
	if kind in ("sc-subcontractors", "sc-compare"):
		return frappe.has_permission("Supplier", "read") and frappe.has_permission("Subcontract Work Order", "read")
	return True


def _report_roles_ok(name, user_roles):
	roles = set(frappe.get_all("Has Role", filters={"parent": name, "parenttype": "Report"}, pluck="role"))
	return not roles or bool(roles & user_roles) or "System Manager" in user_roles


def entry_route(entry_key):
	"""The Command Center path whose form shows documents of this entry type."""
	for key, view in VIEWS.items():
		if view.get("kind") == "entry" and view["entry"] == entry_key:
			return key
	return f"doc/{entry_key}"


def get_nav():
	groups = []
	seen = set()
	for gkey, glabel, items in NAV:
		out = []
		for key, label, icon, kind in items:
			if not can_open(key, kind):
				continue
			item = {"key": key, "label": _(label), "icon": icon, "kind": kind}
			if key in seen:
				item["alias"] = 1  # the same page listed under a second group
			seen.add(key)
			out.append(item)
		if out:
			groups.append({"key": gkey, "label": _(glabel), "items": out})
	return groups


def get_quick_create():
	types = entry_types()
	out = []
	for entry, route in QUICK_CREATE:
		cfg = types.get(entry)
		if cfg and frappe.has_permission(cfg["doctype"], "create"):
			out.append({"entry": entry, "route": route, "label": _("New {0}").format(_(cfg["label"])), "doctype": cfg["doctype"]})
	return out


def get_routes():
	"""What the browser needs to turn a path into a page: each list view's kind and entry type,
	and the path of each entry type's form."""
	types = entry_types()
	views = {k: {"kind": v["kind"], "entry": v.get("entry")} for k, v in VIEWS.items()}
	return {"views": views, "entries": {e: entry_route(e) for e in types}, "legacy": LEGACY_ROUTES,
		"reports": REPORTS}


def get_badges():
	out = {}
	for key, (doctype, filters) in BADGES.items():
		if frappe.has_permission(doctype, "read"):
			out[key] = frappe.db.count(doctype, filters)
	return out


# subcontracting reports (services/subcontract_reports.py): the filters of their desk versions
_SC_STATUS = ["", "Approved", "Sent to Subcontractor", "Accepted by Subcontractor", "Work In Progress", "Partially Completed", "Completed",
	"Pending Final Verification", "Verified", "On Hold", "Closed"]
_SC_F = [_f("company", "Company", "Link", "Company", "$company"), _f("supplier", "Subcontractor", "Link", "Supplier"),
	_f("hire_order_contract", "Hire Order Contract", "Link", "Hire Order Contract"), _f("status", "Status", "Select", _SC_STATUS),
	_f("from_date", "From", "Date"), _f("to_date", "To", "Date")]
for _name in ("Subcontractor Wise Work Orders", "HOC Wise Subcontracting", "Outstanding Subcontractor Payments", "Subcontractor Payments",
		"Subcontract Material Issue and Return", "Subcontract Work Progress Report", "Pending Completion Approval", "Subcontract Cost Analysis",
		"Subcontractor Performance", "HOC Subcontract Profitability", "Subcontract Labour Cost", "Subcontract Equipment Cost",
		"Subcontract Retention and Advance Outstanding", "Subcontract Variation Report", "Subcontractor Invoice Register"):
	REPORT_FILTERS[_name] = _SC_F
REPORT_FILTERS["Subcontract Cost Monitor"] = _SC_F + [_f("project", "Project", "Link", "Project")]
REPORT_FILTERS["Delayed Subcontract Work Orders"] = [_SC_F[0], _SC_F[1], _f("project", "Project", "Link", "Project")]
REPORT_FILTERS["Subcontractor Register"] = [_f("supplier", "Subcontractor", "Link", "Supplier"),
	_f("status", "Approval", "Select", ["", "Pending", "Approved", "Suspended", "Blacklisted"])]
REPORT_FILTERS["Subcontractor Account Statement"] = [_SC_F[0], _f("supplier", "Subcontractor (required)", "Link", "Supplier"),
	_f("from_date", "From", "Date", default="$year_start"), _f("to_date", "To", "Date", default="$today")]
del _name
