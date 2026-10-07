import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from thinknxg_rental.services import cross_hire, ledger
from thinknxg_rental.services.utils import check_duplicate_items, get_bin_qty


class CrossHireOffHireNote(Document):
	"""Hands supplier-owned material back. On submit it raises standard ERPNext Purchase Returns
	(quantity only, zero rate) against the original Cross Hire Receipts."""

	def validate(self):
		cho = frappe.get_doc("Cross Hire Order", self.cross_hire_order)
		if cho.docstatus != 1 or cho.status == "Completed":
			frappe.throw(_("Cross Hire Order {0} is not open").format(self.cross_hire_order))
		self.return_from_warehouse = self.return_from_warehouse or cho.receipt_warehouse
		self.last_billable_date = self.last_billable_date or self.off_hire_date
		if getdate(self.last_billable_date) > getdate(self.off_hire_date):
			frappe.throw(_("Supplier Bills Upto cannot be after the Off-Hire Date"))
		if cho.last_billed_upto and getdate(self.last_billable_date) < getdate(cho.last_billed_upto):
			frappe.msgprint(
				_("The supplier has already invoiced up to {0}. Expect a credit note for the days after {1}.").format(
					cho.last_billed_upto, self.last_billable_date
				),
				indicator="orange",
				alert=True,
			)
		check_duplicate_items(self)
		on_hire = {d.item_code: flt(d.on_hire_qty) for d in cho.items}
		self.total_qty = 0
		for d in self.items:
			if d.item_code not in on_hire:
				frappe.throw(_("Row #{0}: {1} is not on Cross Hire Order {2}").format(d.idx, d.item_code, cho.name))
			if flt(d.qty) <= 0:
				frappe.throw(_("Row #{0}: Off-Hire Qty must be greater than zero").format(d.idx))
			d.on_hire_qty = on_hire[d.item_code]
			d.at_customer_site_qty = ledger.get_cross_hire_qty(cho.name, d.item_code, ledger.AT_SITE)
			free = flt(d.on_hire_qty) - flt(d.at_customer_site_qty)
			if flt(d.qty) > free + 1e-6:
				frappe.throw(
					_("Row #{0}: {1} - {2} on hire, {3} still at customer site, so at most {4} can go back now. "
						"Off-hire the rest from the customer first.").format(
						d.idx, frappe.bold(d.item_code), d.on_hire_qty, d.at_customer_site_qty, free
					)
				)
			in_stock = get_bin_qty(d.item_code, self.return_from_warehouse)
			if flt(d.qty) > in_stock + 1e-6:
				frappe.throw(
					_("Row #{0}: only {1} of {2} is in {3}").format(d.idx, in_stock, d.item_code, self.return_from_warehouse)
				)
			self.total_qty += flt(d.qty)

	def on_submit(self):
		returns = cross_hire.create_purchase_returns(self)
		self.db_set({"purchase_returns": "\n".join(returns), "status": "Returned"})

	def on_cancel(self):
		for name in frappe.get_all(
			"Purchase Receipt",
			filters={"nxg_cross_hire_off_hire_note": self.name, "docstatus": 1},
			pluck="name",
			order_by="creation desc",
		):
			pr = frappe.get_doc("Purchase Receipt", name)
			pr.flags.ignore_permissions = True
			with cross_hire.as_system():
				pr.cancel()
		self.db_set({"purchase_returns": None, "status": "Cancelled"})


@frappe.whitelist()
def make_cross_hire_off_hire_note(source_name: str, target_doc=None):
	cho = frappe.get_doc("Cross Hire Order", source_name)
	cho.check_permission("read")
	target = frappe.new_doc("Cross Hire Off-Hire Note")
	target.update({"company": cho.company, "cross_hire_order": cho.name, "return_from_warehouse": cho.receipt_warehouse})
	for d in cho.items:
		at_site = ledger.get_cross_hire_qty(cho.name, d.item_code, ledger.AT_SITE)
		free = flt(d.on_hire_qty) - at_site
		if free > 0:
			target.append(
				"items",
				{
					"item_code": d.item_code,
					"item_name": d.item_name,
					"uom": d.uom,
					"on_hire_qty": d.on_hire_qty,
					"at_customer_site_qty": at_site,
					"qty": max(free, 0),
				},
			)
	if not target.items:
		frappe.throw(_("Nothing can go back to the supplier yet: the material is either fully returned or still at customer sites"))
	return target
