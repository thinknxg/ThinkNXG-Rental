import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from thinknxg_rental.services import stock
from thinknxg_rental.services.utils import require_setting


class RentalReturnInspection(Document):
	def validate(self):
		note = frappe.db.get_value(
			"Hire Off-Hire Note", self.hire_off_hire_note, ["docstatus", "inspection_status"], as_dict=True
		)
		if note.docstatus != 1:
			frappe.throw(_("Off-Hire Note {0} is not submitted").format(self.hire_off_hire_note))
		if frappe.db.exists(
			"Rental Return Inspection",
			{"hire_off_hire_note": self.hire_off_hire_note, "docstatus": 1, "name": ["!=", self.name]},
		):
			frappe.throw(_("Off-Hire Note {0} has already been inspected").format(self.hire_off_hire_note))
		self.total_good_qty = self.total_repairable_qty = self.total_damaged_qty = 0
		for d in self.items:
			if min(flt(d.good_qty), flt(d.repairable_qty), flt(d.damaged_qty)) < 0:
				frappe.throw(_("Row #{0}: quantities cannot be negative").format(d.idx))
			total = flt(d.good_qty) + flt(d.repairable_qty) + flt(d.damaged_qty)
			if abs(total - flt(d.returned_qty)) > 1e-6:
				frappe.throw(
					_("Row #{0}: Good + Repairable + Beyond Repair ({1}) must equal the returned quantity {2}").format(
						d.idx, total, flt(d.returned_qty)
					)
				)
			self.total_good_qty += flt(d.good_qty)
			self.total_repairable_qty += flt(d.repairable_qty)
			self.total_damaged_qty += flt(d.damaged_qty)

	def on_submit(self):
		"""Own material moves Good -> yard, Repairable -> repair, Beyond Repair -> scrap.
		Cross-hired material stays in the cross hire warehouse (it goes back to the supplier in any
		condition); its result only feeds the customer's damage settlement."""
		rows = []
		for d in self.items:
			if d.ownership != "Own":
				continue
			for qty, setting, serial in (
				(d.good_qty, "rental_yard_warehouse", d.good_serial_no),
				(d.repairable_qty, "repair_warehouse", d.repairable_serial_no),
				(d.damaged_qty, "scrap_warehouse", d.damaged_serial_no),
			):
				if flt(qty) > 0:
					rows.append(
						{
							"item_code": d.item_code,
							"qty": qty,
							"s_warehouse": d.warehouse,
							"t_warehouse": require_setting(setting),
							"batch_no": d.batch_no,
							"serial_no": serial,
						}
					)
		self.db_set("stock_entry", stock.make_stock_entry(self, "Material Transfer", rows, self.inspection_date))
		frappe.db.set_value(
			"Hire Off-Hire Note", self.hire_off_hire_note, {"inspection_status": "Completed", "status": "Completed"}
		)

	def on_cancel(self):
		stock.cancel_stock_entries(self)
		frappe.db.set_value(
			"Hire Off-Hire Note", self.hire_off_hire_note, {"inspection_status": "Pending", "status": "Inspection Pending"}
		)
