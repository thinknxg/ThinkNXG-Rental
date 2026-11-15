"""An enquiry sent from the public rental website (/hire): what was asked for, by whom, for when.

On a website submission (flags.from_website) it is joined to the sales flow the app already uses:
the logged-in customer, or a Lead found by e-mail (else created) with the deal type of the request,
and draft Quotations - one for hire lines (Material Hire, with the hire period) and one for purchase
lines (Material Sale) - for the rental team to price and send. Nothing is submitted automatically.
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, date_diff, flt, getdate, now_datetime, nowdate


class RentalWebsiteEnquiry(Document):
	def validate(self):
		self.enquiry_date = self.enquiry_date or now_datetime()
		if self.required_from and self.expected_return and getdate(self.expected_return) < getdate(self.required_from):
			frappe.throw(_("The expected return date cannot be before the rental start"))
		self.rental_days = date_diff(self.expected_return, self.required_from) + 1 if self.required_from and self.expected_return else 0
		self.set_estimates()

	def set_estimates(self):
		"""Item details and the estimate the website showed, recomputed here from the rate logic: a figure
		sent by the browser is never trusted."""
		from thinknxg_rental.website.catalogue import estimate, rate_customer, settings

		show = cint(settings().show_prices)
		customer = self.customer or (rate_customer() if self.flags.from_website else None)
		total = 0
		for d in self.items:
			item = frappe.get_cached_value("Item", d.item_code, ["item_name", "stock_uom"], as_dict=True)
			if not item:
				frappe.throw(_("Row #{0}: item {1} not found").format(d.idx, d.item_code))
			d.item_name, d.uom = item.item_name, item.stock_uom
			d.estimated_rate = d.estimated_amount = 0
			d.rate_basis = None
			if show and d.line_type == "Hire" and self.required_from and self.expected_return:
				e = estimate(d.item_code, d.qty, self.required_from, self.expected_return, customer)
				d.rate_basis, d.estimated_rate, d.estimated_amount = e.rate_basis, e.rate, e.amount
				total += flt(e.amount)
		self.estimated_total = total

	def after_insert(self):
		if not self.flags.from_website:
			return
		# the Lead and the draft quotations are back-office documents: they are made with system rights
		# (ERPNext reads the Lead with a permission check), never with the visitor's
		user = frappe.session.user
		frappe.db.savepoint("rwe_follow_up")
		try:
			frappe.set_user("Administrator")
			self.link_party()
			self.create_quotations()
		except Exception:
			frappe.db.rollback(save_point="rwe_follow_up")
			frappe.log_error(title=_("Website enquiry {0}: follow-up documents not created").format(self.name))
		finally:
			frappe.set_user(user)
		self.notify_team()
		self.confirm_to_sender()

	# ------------------------------------------------------------------ sales flow
	def deal_type(self, purchase=False):
		return "Material Sale" if purchase else "Material Hire"

	def link_party(self):
		if self.customer or not self.email:
			return
		lead = frappe.db.get_value("Lead", {"email_id": self.email, "status": ["not in", ["Converted", "Do Not Contact"]]}, "name", order_by="creation desc")
		if not lead:
			names = (self.full_name or "").strip().split(" ", 1)
			doc = frappe.get_doc({
				"doctype": "Lead", "first_name": names[0][:140] or self.email, "last_name": names[1][:140] if len(names) > 1 else None,
				"company_name": self.company_name, "email_id": self.email, "mobile_no": self.phone, "request_type": "Product Enquiry",
				"deal_type": self.deal_type(purchase=self.enquiry_type == "Purchase"), "project_title": (self.project_location or "")[:140] or None,
				"company": frappe.db.get_single_value("Rental Settings", "company"), "status": "Lead",
			})
			doc.flags.ignore_permissions = True
			doc.flags.ignore_mandatory = True
			doc.insert()
			lead = doc.name
		self.db_set("lead", lead, update_modified=False)

	@frappe.whitelist()
	def make_quotations(self):
		"""Staff: create the draft quotations now (if they were not made on submission)."""
		self.check_permission("write")
		if not (self.customer or self.lead):
			self.link_party()
			self.reload()
		return self.create_quotations()

	def create_quotations(self):
		"""Draft quotations for the hire lines and the purchase lines (each once)."""
		party_type, party = ("Customer", self.customer) if self.customer else ("Lead", self.lead)
		if not party:
			frappe.throw(_("Link a Customer or a Lead first"))
		made = []
		for line_type, field, purchase in (("Hire", "hire_quotation", False), ("Purchase", "purchase_quotation", True)):
			rows = [d for d in self.items if d.line_type == line_type]
			if not rows or self.get(field):
				continue
			start = getdate(self.required_from) if self.required_from else getdate(nowdate())
			end = getdate(self.expected_return) if self.expected_return else add_days(start, 29)
			q = frappe.get_doc({
				"doctype": "Quotation", "quotation_to": party_type, "party_name": party, "company": frappe.db.get_single_value("Rental Settings", "company"),
				"transaction_date": nowdate(), "valid_till": add_days(nowdate(), 30), "order_type": "Sales",
				"deal_type": self.deal_type(purchase), "project_title": (self.project_location or "")[:140] or None,
				"nxg_website_enquiry": self.name,
				"items": [{"item_code": d.item_code, "qty": flt(d.qty), "uom": d.uom} for d in rows],
			})
			if not purchase:
				q.update({"nxg_required_from": start, "nxg_expected_return_date": end})
			q.flags.ignore_permissions = True
			q.insert()
			self.db_set(field, q.name, update_modified=False)
			made.append(q.name)
		if made and self.status == "New":
			self.db_set("status", "In Review", update_modified=False)
		return made

	# ------------------------------------------------------------------ messages
	def notify_team(self):
		from thinknxg_rental.website.catalogue import settings

		role = settings().enquiry_notify_role or "Rental Manager"
		users = frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent")
		users = frappe.get_all("User", filters={"name": ["in", users or [""]], "enabled": 1, "user_type": "System User"}, pluck="name")
		subject = _("New website enquiry {0}: {1} from {2}").format(self.name, _(self.enquiry_type), self.company_name or self.full_name)
		for user in users:
			if user in ("Administrator", "Guest"):
				continue
			try:
				log = frappe.new_doc("Notification Log")
				log.update({"for_user": user, "type": "Alert", "subject": subject, "document_type": self.doctype, "document_name": self.name})
				log.flags.ignore_permissions = True
				log.insert()
			except Exception:
				frappe.log_error(title=_("Website enquiry notification failed"))

	def confirm_to_sender(self):
		from thinknxg_rental.website.catalogue import settings

		if not frappe.db.exists("Email Account", {"default_outgoing": 1, "enable_outgoing": 1}):
			return  # no outgoing mail set up on this site: the reference is still shown on screen
		try:
			s = settings()
			lines = "".join(f"<li>{frappe.utils.escape_html(d.item_name)}: {flt(d.qty):g} {d.uom or ''} ({_(d.line_type)})</li>" for d in self.items)
			frappe.sendmail(
				recipients=[self.email],
				subject=_("We received your enquiry {0}").format(self.name),
				message=_("<p>Dear {0},</p><p>Thank you for your enquiry. Our rental team will contact you shortly. Your reference is <b>{1}</b>.</p>{2}<p>{3}</p>").format(
					frappe.utils.escape_html(self.full_name), self.name, f"<ul>{lines}</ul>" if lines else "", frappe.utils.escape_html(s.site_name or "")),
				reference_doctype=self.doctype, reference_name=self.name, now=False,
			)
		except Exception:
			frappe.log_error(title=_("Website enquiry confirmation e-mail not queued"))
