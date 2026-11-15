"""Notifications for customer portal users (thinkNXG Rental customer Command Center).

Each notification is an ordinary Frappe Notification Log for every portal user of the customer, so
read / unread state, e-mail (per the user's Notification Settings) and the desk bell all work as
usual. They are raised from document events (order confirmed, dispatched, returned, invoiced, paid,
request updates) and by a daily job (rentals ending soon or overdue).

A notification never stops the transaction that raised it: failures are logged and skipped.
"""
import frappe
from frappe import _
from frappe.utils import add_days, flt, fmt_money, formatdate, getdate, nowdate


def customer_users(customer):
	"""Enabled website or system users who can open this customer's portal."""
	if not customer:
		return []
	users = set(frappe.get_all("Portal User", filters={"parenttype": "Customer", "parent": customer}, pluck="user"))
	contacts = frappe.get_all("Dynamic Link", filters={"parenttype": "Contact", "link_doctype": "Customer", "link_name": customer},
		pluck="parent")
	if contacts:
		for c in frappe.get_all("Contact", filters={"name": ["in", contacts]}, fields=["user", "email_id"]):
			if c.user:
				users.add(c.user)
			elif c.email_id and frappe.db.exists("User", c.email_id):
				users.add(c.email_id)
	users.discard(None)
	users -= {"Guest", "Administrator"}
	if not users:
		return []
	return frappe.get_all("User", filters={"name": ["in", list(users)], "enabled": 1}, pluck="name")


def notify(customer, subject, document_type=None, document_name=None, message=None, once=False):
	"""One Notification Log per portal user. once=True: skipped for a user who already has this subject
	for this document (daily reminders)."""
	try:
		for user in customer_users(customer):
			if once and frappe.db.exists("Notification Log", {"for_user": user, "subject": subject,
					"document_type": document_type, "document_name": document_name}):
				continue
			log = frappe.new_doc("Notification Log")
			log.update({"for_user": user, "type": "Alert", "subject": subject, "email_content": message or subject,
				"document_type": document_type, "document_name": document_name, "from_user": frappe.session.user})
			log.flags.ignore_permissions = True
			log.insert()
	except Exception:
		frappe.log_error(title=_("Customer portal notification failed"))


def _money(amount, currency):
	return fmt_money(flt(amount), currency=currency)


# ----------------------------------------------------------------------------- document events
def rental_contract_submitted(doc, method=None):
	notify(doc.customer, _("Rental order {0} is confirmed for {1}").format(doc.name, doc.rental_site or doc.customer_name),
		doc.doctype, doc.name)


def delivery_submitted(doc, method=None):
	notify(doc.customer, _("{0} units dispatched to {1} ({2})").format(f"{flt(doc.total_qty):g}", doc.rental_site, doc.name),
		doc.doctype, doc.name)


def off_hire_submitted(doc, method=None):
	qty = flt(doc.total_returned_qty)
	notify(doc.customer, _("{0} units returned from {1} ({2})").format(f"{qty:g}", doc.rental_site, doc.name), doc.doctype, doc.name)


def inspection_submitted(doc, method=None):
	notify(doc.customer, _("Returned material inspected ({0}): {1} good, {2} repairable, {3} beyond repair").format(
		doc.hire_off_hire_note, f"{flt(doc.total_good_qty):g}", f"{flt(doc.total_repairable_qty):g}", f"{flt(doc.total_damaged_qty):g}"),
		doc.doctype, doc.name)


def sales_invoice_submitted(doc, method=None):
	if doc.is_return:
		subject = _("Credit note {0} for {1} issued").format(doc.name, _money(abs(doc.grand_total), doc.currency))
	else:
		subject = _("Invoice {0} for {1} is due on {2}").format(doc.name, _money(doc.grand_total, doc.currency), formatdate(doc.due_date))
	notify(doc.customer, subject, doc.doctype, doc.name)


def payment_submitted(doc, method=None):
	if doc.party_type != "Customer" or doc.payment_type != "Receive":
		return
	currency = doc.paid_from_account_currency or frappe.get_cached_value("Company", doc.company, "default_currency")
	notify(doc.party, _("Payment of {0} received ({1}). Thank you.").format(_money(doc.paid_amount, currency), doc.name),
		doc.doctype, doc.name)


def quotation_submitted(doc, method=None):
	if doc.quotation_to != "Customer":
		return
	notify(doc.party_name, _("Quotation {0} for {1} is ready").format(doc.name, _money(doc.grand_total, doc.currency)), doc.doctype, doc.name)


def sales_order_submitted(doc, method=None):
	notify(doc.customer, _("Sales order {0} is confirmed").format(doc.name), doc.doctype, doc.name)


def request_raised(doc):
	notify(doc.customer, _("We received your {0} ({1})").format(_(request_label(doc.request_type)).lower(), doc.name), doc.doctype, doc.name)


def request_status_changed(doc):
	if doc.status == "Cancelled":
		return
	words = {"In Progress": _("is being handled"), "Completed": _("is completed"), "Rejected": _("was declined")}
	if doc.status not in words:
		return
	notify(doc.customer, _("Your {0} {1} {2}").format(_(request_label(doc.request_type)).lower(), doc.name, words[doc.status]),
		doc.doctype, doc.name, message=doc.response)


def request_label(request_type):
	return {"Off-Hire Request": "Material Return Request", "Hire Enquiry": "Hire Enquiry"}.get(request_type, request_type)


# ----------------------------------------------------------------------------- daily
def rental_expiry_reminders():
	"""Rentals with material at site that end within 7 days, or ended yesterday: one reminder each."""
	today = getdate(nowdate())
	contracts = frappe.get_all("Rental Contract",
		filters={"docstatus": 1, "status": ["in", ["Active", "On Hire"]], "total_at_site_qty": [">", 0],
			"end_date": ["between", [add_days(today, -1), add_days(today, 7)]]},
		fields=["name", "customer", "rental_site", "end_date"])
	for c in contracts:
		if getdate(c.end_date) < today:
			subject = _("Rental {0} at {1} ended on {2}: return the material or ask for an extension").format(c.name, c.rental_site, formatdate(c.end_date))
		else:
			subject = _("Rental {0} at {1} ends on {2}").format(c.name, c.rental_site, formatdate(c.end_date))
		notify(c.customer, subject, "Rental Contract", c.name, once=True)
