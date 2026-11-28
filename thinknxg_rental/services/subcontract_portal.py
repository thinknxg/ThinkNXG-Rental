"""Subcontractor portal: who the session user is, which subcontractor they act for, and notifications to and from them.

Access comes only from an enabled Subcontractor Portal Access row whose Supplier is an approved subcontractor. Every
portal API resolves it again from the session (never from a value sent by the browser) and checks that each document it
touches belongs to that supplier. Portal users hold no desk permissions on the subcontracting DocTypes.
"""
import frappe
from frappe import _
from frappe.utils import now_datetime

PORTAL_ROLE = "Subcontractor Portal User"
COMMERCIAL = "Commercial"


def accesses(user=None):
	user = user or frappe.session.user
	if not user or user == "Guest":
		return []
	rows = frappe.get_all("Subcontractor Portal Access", filters={"user": user, "enabled": 1},
		fields=["name", "supplier", "supplier_name", "access_level", "full_name"], order_by="creation")
	if not rows:
		return []
	ok = set(frappe.get_all("Supplier", filters={"name": ["in", [r.supplier for r in rows]], "disabled": 0, "is_subcontractor": 1,
		"subcontractor_approval_status": ["in", ["Approved", "Suspended"]]}, pluck="name"))
	return [r for r in rows if r.supplier in ok]


def current(supplier=None, need=None):
	"""The access row the session acts under. `need="Commercial"` refuses operational-only users."""
	if frappe.session.user == "Guest":
		raise frappe.PermissionError(_("Log in to the subcontractor portal"))
	if not frappe.db.get_single_value("Subcontracting Settings", "portal_enabled"):
		raise frappe.PermissionError(_("The subcontractor portal is switched off"))
	rows = accesses()
	if supplier:
		rows = [r for r in rows if r.supplier == supplier]
	if not rows:
		raise frappe.PermissionError(_("This login has no subcontractor portal access"))
	acc = rows[0]
	acc.suspended = frappe.db.get_value("Supplier", acc.supplier, "subcontractor_approval_status") == "Suspended"
	if need == COMMERCIAL and acc.access_level != COMMERCIAL:
		raise frappe.PermissionError(_("Your access does not include commercial information"))
	return acc


def touch(acc):
	"""Last access, at most once a minute per user."""
	key = f"sc_portal_touch:{frappe.session.user}"
	if frappe.cache.get_value(key):
		return
	frappe.cache.set_value(key, 1, expires_in_sec=60)
	frappe.db.set_value("Subcontractor Portal Access", acc.name, "last_access", now_datetime(), update_modified=False)


def own(doctype, name, acc, field="supplier"):
	"""The document, only if it belongs to the session's subcontractor. Same error for 'missing' and 'not yours'."""
	supplier = frappe.db.get_value(doctype, name, field) if name else None
	if not supplier or supplier != acc.supplier:
		raise frappe.PermissionError(_("{0} {1} was not found").format(_(doctype), name or ""))
	return frappe.get_doc(doctype, name)


# ----------------------------------------------------------------------------------------------- notifications
def supplier_users(supplier, commercial_only=False):
	filters = {"supplier": supplier, "enabled": 1, "user": ["is", "set"]}
	if commercial_only:
		filters["access_level"] = COMMERCIAL
	return frappe.get_all("Subcontractor Portal Access", filters=filters, fields=["user", "email"])


def notify_supplier(supplier, subject, message, doctype=None, name=None, commercial_only=False):
	"""Bell notification in the portal for every enabled contact, plus an email. Never fails the transaction."""
	try:
		for r in supplier_users(supplier, commercial_only):
			frappe.get_doc({"doctype": "Notification Log", "for_user": r.user, "type": "Alert", "subject": subject,
				"email_content": message, "document_type": doctype, "document_name": name, "from_user": frappe.session.user}).insert(ignore_permissions=True)
		emails = [r.email for r in supplier_users(supplier, commercial_only) if r.email]
		if emails:
			frappe.sendmail(recipients=emails, subject=subject, message=message + "<br><br>" + _("Open the portal: {0}").format(
				frappe.utils.get_url("/subcontractor")), reference_doctype=doctype, reference_name=name, now=False)
	except Exception:
		frappe.log_error(title="Subcontractor portal notification")


def staff_users(doctype, name, field_users=("site_engineer", "project_manager", "coordinator")):
	users = set()
	if doctype == "Subcontract Work Order" and name:
		row = frappe.db.get_value(doctype, name, list(field_users) + ["owner"], as_dict=True) or {}
		users.update(v for v in row.values() if v)
	if not users:
		users.update(frappe.get_all("Has Role", filters={"role": "Subcontracting Manager", "parenttype": "User"}, pluck="parent"))
	return [u for u in users if u not in ("Administrator", "Guest") and frappe.db.get_value("User", u, "enabled")]


def notify_staff(swo, subject, doctype, name):
	try:
		for u in staff_users("Subcontract Work Order", swo):
			frappe.get_doc({"doctype": "Notification Log", "for_user": u, "type": "Alert", "subject": subject,
				"document_type": doctype, "document_name": name, "from_user": frappe.session.user}).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="Subcontracting staff notification")
