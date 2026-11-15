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

STAFF_ROLES = ("System Manager", "Rental Manager", "Rental User")

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
}

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
	]),
	("crosshire", "Cross hire", [
		("cross-hire", "Cross Hire Orders", "arrow-left-right", "list"),
		("cross-hire-receipts", "Cross Hire Receipts", "package-check", "list"),
		("supplier-off-hire", "Supplier Off-Hire", "package-minus", "list"),
		("supplier-bills", "Supplier Hire Bills", "receipt", "list"),
		("supplier-position", "Supplier Position", "factory", "suppliers"),
	]),
	("finance", "Billing & finance", [
		("billing", "Rental Billing", "calendar-clock", "billing"),
		("reports/unbilled", "Unbilled Rental", "hourglass", "report"),
		("invoices", "Sales Invoices", "file-spreadsheet", "list"),
		("outstanding", "Outstanding Payments", "wallet", "outstanding"),
		("reports/damage-loss", "Damage & Loss Recovery", "hammer", "report"),
	]),
	("reports", "Reports & analytics", [
		("utilization", "Rental Utilization", "gauge", "utilization"),
		("reports/material-at-site", "Material at Site", "map", "report"),
		("reports/stock-availability", "Stock Availability", "package-search", "report"),
		("reports/cross-hire-position", "Cross Hire Position", "repeat", "report"),
		("reports/contract-profitability", "Contract Profitability", "trending-up", "report"),
		("reports/damage-loss", "Damage and Loss Register", "clipboard-x", "report"),
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
	"reports/unbilled": "Unbilled Rental",
	"reports/damage-loss": "Damage and Loss Register",
	"reports/contract-profitability": "Hire Contract Profitability",
}

# The filters each report page offers (the same fields as the report's own filters in the desk).
# default: "$company" (Rental Settings company), "$today", "$year_start".
def _f(fieldname, label, fieldtype="Data", options=None, default=None):
	return dict(fieldname=fieldname, label=label, fieldtype=fieldtype, options=options, default=default)


REPORT_FILTERS = {
	"Material at Site": [_f("company", "Company", "Link", "Company", "$company"), _f("as_on_date", "As on", "Date"),
		_f("customer", "Customer", "Link", "Customer"), _f("rental_site", "Site", "Link", "Rental Site"),
		_f("rental_contract", "Rental contract", "Link", "Rental Contract"), _f("item_code", "Item", "Link", "Item"),
		_f("ownership", "Ownership", "Select", ["", "Own", "Cross Hire"]), _f("supplier", "Supplier", "Link", "Supplier")],
	"Rental Stock Position": [_f("category", "Category", "Select", ["", "Formwork", "Scaffolding", "Shoring / Props", "Accessories", "Other"]),
		_f("item_code", "Item", "Link", "Item")],
	"Cross Hire Position": [_f("company", "Company", "Link", "Company", "$company"), _f("supplier", "Supplier", "Link", "Supplier"),
		_f("rental_contract", "Rental contract", "Link", "Rental Contract"), _f("item_code", "Item", "Link", "Item"),
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

QUICK_CREATE = [
	("lead", "sales/leads"), ("quotation", "sales/quotations"), ("rental-site", "sites"), ("hire-order", "hire-orders"),
	("hire-order-contract", "hire-contracts"), ("rental-contract", "contracts"), ("delivery-order", "deliveries"),
	("off-hire-note", "off-hire"), ("material-reservation", "reservations"), ("cross-hire-order", "cross-hire"),
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
