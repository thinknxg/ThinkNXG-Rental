import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, nowdate

from thinknxg_rental.services.billing import append_taxes
from thinknxg_rental.services.utils import as_system, get_settings, require_setting


class RentalDamageSettlement(Document):
	def validate(self):
		self.total_damage_amount = self.total_loss_amount = self.total_salvage_value = 0
		for d in self.items:
			if flt(d.qty) <= 0:
				frappe.throw(_("Row #{0}: Qty must be greater than zero").format(d.idx))
			liability = flt(d.liability_percent) if d.liability_percent is not None else 100
			d.amount = max(flt(d.qty) * flt(d.rate) * liability / 100.0 - flt(d.salvage_value), 0)
			if d.classification == "Lost":
				self.total_loss_amount += d.amount
			else:
				self.total_damage_amount += d.amount
			self.total_salvage_value += flt(d.salvage_value)
		self.grand_total = (
			self.total_damage_amount + self.total_loss_amount + flt(self.transport_charges) + flt(self.other_charges)
		)

	def on_submit(self):
		self.db_set("status", "To Invoice")

	def on_cancel(self):
		self.db_set("status", "Cancelled")


@frappe.whitelist()
def make_sales_invoice(settlement: str):
	doc = frappe.get_doc("Rental Damage Settlement", settlement)
	doc.check_permission("write")
	if doc.docstatus != 1:
		frappe.throw(_("Submit the settlement first"))
	if doc.sales_invoice:
		frappe.throw(_("Sales Invoice {0} already exists for this settlement").format(doc.sales_invoice))
	damage_item = require_setting("damage_recovery_item")
	loss_item = require_setting("loss_recovery_item")
	contract = frappe.get_doc("Rental Contract", doc.rental_contract)

	si = frappe.new_doc("Sales Invoice")
	si.update(
		{
			"company": doc.company,
			"customer": doc.customer,
			"posting_date": nowdate(),
			"project": contract.project,
			"cost_center": contract.cost_center,
			"nxg_rental_contract": contract.name,
			"nxg_rental_damage_settlement": doc.name,
			"remarks": _("Damage and loss settlement {0} - Contract {1}").format(doc.name, contract.name),
		}
	)
	for d in doc.items:
		if flt(d.amount) <= 0:
			continue
		si.append(
			"items",
			{
				"item_code": loss_item if d.classification == "Lost" else damage_item,
				"item_name": f"{d.classification} - {d.item_name}",
				"description": _("{0}: {1} x {2} ({3}% customer liability)").format(
					d.classification, flt(d.qty), d.item_name, flt(d.liability_percent)
				),
				"qty": d.qty,
				"rate": flt(d.amount) / flt(d.qty),
				"project": contract.project,
				"cost_center": contract.cost_center,
				"nxg_hire_item": d.item_code,
			},
		)
	for label, amount in (
		(_("Return transport charges"), doc.transport_charges),
		(doc.other_charges_description or _("Other charges"), doc.other_charges),
	):
		if flt(amount) > 0:
			si.append(
				"items",
				{"item_code": damage_item, "item_name": label, "description": label, "qty": 1, "rate": amount,
					"project": contract.project, "cost_center": contract.cost_center},
			)
	if not si.items:
		frappe.throw(_("Nothing to invoice on this settlement"))
	append_taxes(si, "Sales Taxes and Charges Template", contract.taxes_and_charges)
	si.flags.ignore_permissions = True
	with as_system():
		si.insert()
		doc.db_set("sales_invoice", si.name)
		if cint(get_settings().auto_submit_sales_invoice):
			si.submit()
	return si.name
