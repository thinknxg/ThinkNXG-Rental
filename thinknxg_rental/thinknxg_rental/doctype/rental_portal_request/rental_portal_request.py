import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate


class RentalPortalRequest(Document):
	def validate(self):
		if self.rental_contract:
			contract = frappe.db.get_value("Rental Contract", self.rental_contract, ["customer", "company"], as_dict=True)
			if contract.customer != self.customer:
				frappe.throw(_("Contract {0} does not belong to customer {1}").format(self.rental_contract, self.customer))
			self.company = self.company or contract.company
		if self.request_type != "Extension Request" and not self.items:
			frappe.throw(_("Add at least one item"))
		if self.status == "Rejected" and not (self.response or "").strip():
			frappe.throw(_("Give the customer a reason in Response before rejecting the request"))

	@frappe.whitelist()
	def start(self):
		"""Staff have picked the request up; the customer sees In Progress."""
		self.check_permission("write")
		if self.status != "Open":
			frappe.throw(_("Request {0} is already {1}").format(self.name, self.status))
		self.db_set("status", "In Progress")

	@frappe.whitelist()
	def reject(self, reason: str):
		"""Close the request with a reply the customer sees on the portal."""
		self.check_permission("write")
		if self.status not in ("Open", "In Progress"):
			frappe.throw(_("Request {0} is already {1}").format(self.name, self.status))
		if existing := _existing_document(self.name):
			frappe.throw(_("{0} {1} was already made for this request. Cancel or delete it before rejecting.").format(_(existing[0]), existing[1]))
		self.status = "Rejected"
		self.response = (reason or "").strip()
		self.save()

	@frappe.whitelist()
	def apply_extension(self):
		"""Extend the contract to the requested end date and close the request."""
		self.check_permission("write")
		if self.request_type != "Extension Request" or self.status in ("Completed", "Rejected", "Cancelled"):
			frappe.throw(_("Nothing to extend"))
		if not self.rental_contract or not self.new_end_date:
			frappe.throw(_("The request has no contract or new end date to apply"))
		contract = frappe.get_doc("Rental Contract", self.rental_contract)
		contract.extend_contract(str(self.new_end_date), _("Customer portal request {0}").format(self.name))
		self.db_set({"status": "Completed", "reference_doctype": "Rental Contract", "reference_name": contract.name})


def check_request_unused(doc):
	"""Called by Hire Order / Hire Off-Hire Note on validate: one customer request makes one document."""
	request = doc.get("portal_request")
	if not request:
		return
	status = frappe.db.get_value("Rental Portal Request", request, "status")
	if doc.is_new() and status in ("Completed", "Rejected", "Cancelled"):
		frappe.throw(_("Customer request {0} is already {1}").format(request, status))
	for doctype in ("Hire Order", "Hire Off-Hire Note"):
		other = frappe.db.get_value(doctype, {"portal_request": request, "docstatus": ["<", 2], "name": ["!=", doc.name or ""]}, "name")
		if other:
			frappe.throw(_("Customer request {0} is already handled by {1} {2}").format(request, _(doctype), other))


def set_request_reference(doc, completed=True):
	"""Called by Hire Order / Hire Off-Hire Note on submit and cancel."""
	request = doc.get("portal_request")
	if not request or not frappe.db.exists("Rental Portal Request", request):
		return
	if completed:
		values = {"status": "Completed", "reference_doctype": doc.doctype, "reference_name": doc.name}
	else:
		values = {"status": "In Progress", "reference_doctype": None, "reference_name": None}
	frappe.db.set_value("Rental Portal Request", request, values)


def _open_request(source_name, request_type):
	source = frappe.get_doc("Rental Portal Request", source_name)
	source.check_permission("read")
	if source.request_type != request_type:
		frappe.throw(_("This is not a {0}").format(request_type))
	if source.status in ("Completed", "Rejected", "Cancelled"):
		frappe.throw(_("Request {0} is {1}").format(source.name, source.status))
	if existing := _existing_document(source.name):
		frappe.throw(_("{0} {1} was already made for request {2}. Open it instead of making another.").format(_(existing[0]), existing[1], source.name))
	return source


def _existing_document(request):
	"""(doctype, name) of a draft or submitted document already made from this request."""
	for doctype in ("Hire Order", "Hire Off-Hire Note"):
		name = frappe.db.get_value(doctype, {"portal_request": request, "docstatus": ["<", 2]}, "name")
		if name:
			return doctype, name
	return None


@frappe.whitelist()
def make_hire_order(source_name: str, target_doc=None):
	from thinknxg_rental.services.utils import get_settings

	source = _open_request(source_name, "Hire Enquiry")
	start = max(getdate(source.required_date or nowdate()), getdate(nowdate()))
	target = frappe.new_doc("Hire Order")
	target.update(
		{
			"company": source.company or get_settings().company,
			"customer": source.customer,
			"portal_request": source.name,
			"order_date": nowdate(),
			"required_from": start,
			"expected_return_date": max(getdate(source.expected_return_date or start), start),
			"remarks": "\n".join(filter(None, [source.site_location, source.remarks])),
		}
	)
	for d in source.items:
		target.append("items", {"item_code": d.item_code, "item_name": d.item_name, "uom": d.uom, "qty": d.qty})
	return target


@frappe.whitelist()
def make_off_hire_note(source_name: str, target_doc=None):
	"""Off-hire note pre-filled with the requested quantities. The off-hire (notice) date is the day
	the customer raised the request, which is what the grace period is measured from."""
	from thinknxg_rental.thinknxg_rental.doctype.hire_off_hire_note.hire_off_hire_note import get_items_at_site

	source = _open_request(source_name, "Off-Hire Request")
	contract = frappe.get_doc("Rental Contract", source.rental_contract)
	target = frappe.new_doc("Hire Off-Hire Note")
	target.update(
		{
			"company": contract.company,
			"rental_contract": contract.name,
			"portal_request": source.name,
			"off_hire_date": source.request_date,
			"return_date": nowdate(),
			"grace_days": contract.grace_days,
			"reason": _("Customer portal request {0}").format(source.name),
		}
	)
	wanted = {d.item_code: flt(d.qty) for d in source.items}
	# own material first, then cross-hired
	rows = sorted(get_items_at_site(contract.name), key=lambda r: (r["item_code"], r["ownership"] != "Own"))
	for row in rows:
		take = min(wanted.get(row["item_code"], 0), flt(row["at_site_qty"]))
		if take <= 0:
			continue
		wanted[row["item_code"]] -= take
		target.append("items", dict(row, returned_qty=take, pending_qty=flt(row["at_site_qty"]) - take))
	if not target.items:
		frappe.throw(_("None of the requested items are at site any more"))
	return target
