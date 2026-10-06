import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate


class RentalPortalRequest(Document):
	def validate(self):
		if self.hire_contract:
			contract = frappe.db.get_value("Hire Order Contract", self.hire_contract, ["customer", "company"], as_dict=True)
			if contract.customer != self.customer:
				frappe.throw(_("Contract {0} does not belong to customer {1}").format(self.hire_contract, self.customer))
			self.company = self.company or contract.company
		if self.request_type != "Extension Request" and not self.items:
			frappe.throw(_("Add at least one item"))

	@frappe.whitelist()
	def apply_extension(self):
		"""Extend the contract to the requested end date and close the request."""
		self.check_permission("write")
		if self.request_type != "Extension Request" or self.status in ("Completed", "Rejected", "Cancelled"):
			frappe.throw(_("Nothing to extend"))
		contract = frappe.get_doc("Hire Order Contract", self.hire_contract)
		contract.extend(str(self.new_end_date), _("Customer portal request {0}").format(self.name))
		self.db_set({"status": "Completed", "reference_doctype": "Hire Order Contract", "reference_name": contract.name})


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
	return source


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
	contract = frappe.get_doc("Hire Order Contract", source.hire_contract)
	target = frappe.new_doc("Hire Off-Hire Note")
	target.update(
		{
			"company": contract.company,
			"hire_contract": contract.name,
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
