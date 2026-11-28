import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, validate_email_address

from thinknxg_rental.services import subcontracting as sc
from thinknxg_rental.services.subcontract_portal import PORTAL_ROLE


class SubcontractorPortalAccess(Document):
	"""One portal login of one subcontractor contact. The User is created (or reused) on save; the portal opens only while
	this row is enabled and the Supplier is an approved (or suspended: read only) subcontractor."""

	def validate(self):
		self.email = (self.email or "").strip().lower()
		validate_email_address(self.email, throw=True)
		if not frappe.db.get_value("Supplier", self.supplier, "is_subcontractor"):
			frappe.throw(_("{0} is not set up as a Subcontractor").format(self.supplier))
		dup = frappe.db.exists("Subcontractor Portal Access", {"supplier": self.supplier, "email": self.email, "name": ["!=", self.name]})
		if dup:
			frappe.throw(_("{0} already has portal access for {1}").format(self.email, self.supplier))
		if not self.enabled and not (self.suspended_reason or "").strip() and not self.is_new():
			frappe.throw(_("Give the reason for suspending this access"))
		self.ensure_user()

	def ensure_user(self):
		user = frappe.db.get_value("User", {"email": self.email}, "name") or frappe.db.get_value("User", self.email, "name")
		if user:
			doc = frappe.get_doc("User", user)
			if doc.name in ("Administrator", "Guest"):
				frappe.throw(_("This email cannot be used for portal access"))
		else:
			first, _sp, last = (self.full_name or self.email).partition(" ")
			doc = frappe.get_doc({"doctype": "User", "email": self.email, "first_name": first, "last_name": last, "mobile_no": self.mobile_no,
				"user_type": "Website User", "send_welcome_email": 0, "enabled": 1})
			doc.flags.ignore_permissions = True
			doc.insert()
		if PORTAL_ROLE not in [r.role for r in doc.roles]:
			doc.flags.ignore_permissions = True
			doc.append_roles(PORTAL_ROLE)
			doc.save()
		self.user = doc.name


@frappe.whitelist()
def invite(name):
	"""Email the contact a link to set their password and open the portal."""
	sc.require_role(sc.MANAGER, sc.EXECUTIVE)
	acc = frappe.get_doc("Subcontractor Portal Access", name)
	if not acc.enabled:
		frappe.throw(_("Enable the access first"))
	user = frappe.get_doc("User", acc.user)
	if not user.enabled:
		frappe.throw(_("User {0} is disabled").format(user.name))
	key = user.reset_password(send_email=False)
	link = frappe.utils.get_url(f"/update-password?key={key}&redirect-to=/subcontractor") if key and not key.startswith("http") else key
	frappe.sendmail(recipients=[acc.email], subject=_("Your subcontractor portal access"),
		message=_("Hello {0},<br><br>{1} has given you access to the subcontractor portal for {2}.<br>"
			"Set your password here: <a href=\"{3}\">{3}</a><br><br>Afterwards, sign in at {4}.").format(
			acc.full_name, frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company") or "",
			acc.supplier_name or acc.supplier, link, frappe.utils.get_url("/subcontractor")), now=False)
	acc.db_set("invited_on", now_datetime())
	return True
