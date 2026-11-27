import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from thinknxg_rental.services import ledger, stock
from thinknxg_rental.services import subcontracting as sc
from thinknxg_rental.services.utils import get_available_qty


class SubcontractMaterialAllocation(Document):
	"""Company-owned material issued to a subcontractor: Stock Entry (Material Transfer) into the custody warehouse
	plus a Rental Ownership Ledger row, nothing else. Subcontractor-owned equipment never comes through here."""

	def validate(self):
		swo = sc.work_order_for_document(self)
		self.company, self.supplier = swo.company, swo.supplier
		if not self.items:
			frappe.throw(_("Add the items to issue"))
		seen = set()
		for r in self.items:
			if flt(r.qty) <= 0:
				frappe.throw(_("Row {0}: Quantity must be greater than zero").format(r.idx))
			if r.item_code in seen:
				frappe.throw(_("Row {0}: {1} is repeated. Merge the quantities").format(r.idx, r.item_code))
			seen.add(r.item_code)
			if not frappe.db.get_value("Item", r.item_code, "is_stock_item"):
				frappe.throw(_("Row {0}: {1} is not a stock item").format(r.idx, r.item_code))
			r.uom = r.uom or frappe.db.get_value("Item", r.item_code, "stock_uom")

	def before_submit(self):
		sc.require_role(sc.STORE_MANAGER, sc.MANAGER)
		sc.lock_work_order(self.subcontract_work_order)
		self.validate()
		for r in self.items:
			free = get_available_qty(r.item_code, self.source_warehouse)
			if flt(r.qty) > free + 1e-9:
				frappe.throw(_("Row {0}: only {1} of {2} is free in {3} (the rest is in stock reservations or not there)").format(
					r.idx, free, r.item_code, self.source_warehouse), title=_("Not enough stock"))

	def on_submit(self):
		swo = frappe.db.get_value("Subcontract Work Order", self.subcontract_work_order, ["supplier", "customer", "project", "rental_site"], as_dict=True)
		custody = sc.custody_warehouse(self.company)
		self.db_set("custody_warehouse", custody)
		rows = [{"item_code": r.item_code, "qty": r.qty, "s_warehouse": self.source_warehouse, "t_warehouse": custody} for r in self.items]
		self.db_set("stock_entry", stock.make_stock_entry(self, "Material Transfer", rows, self.posting_date, _("Issued to subcontractor {0}").format(self.supplier)))
		for r in self.items:
			ledger.add_entry(self, posting_date=self.posting_date, position_type=sc.CUSTODY, movement_type="Dispatch", item_code=r.item_code,
				qty=flt(r.qty), ownership="Own", supplier=swo.supplier, customer=swo.customer, project=swo.project, rental_site=swo.rental_site,
				subcontract_work_order=self.subcontract_work_order, warehouse=custody, origin_warehouse=self.source_warehouse,
				source_warehouse=self.source_warehouse, target_warehouse=custody, stock_entry=self.stock_entry, voucher_detail_no=r.name)

	def before_cancel(self):
		sc.require_role(sc.STORE_MANAGER, sc.MANAGER)
		sc.lock_work_order(self.subcontract_work_order)
		bal = sc.issued_balance(self.subcontract_work_order)
		for r in self.items:
			if bal.get(r.item_code, frappe._dict(outstanding=0)).outstanding < flt(r.qty) - 1e-9:
				frappe.throw(_("{0}: part of this issue was already returned, installed or written off. Cancel those returns first").format(r.item_code))

	def on_cancel(self):
		stock.cancel_stock_entries(self)
		ledger.delete_entries(self.doctype, self.name)
