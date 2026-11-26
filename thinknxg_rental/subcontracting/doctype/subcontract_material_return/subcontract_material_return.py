import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from thinknxg_rental.services import ledger, stock
from thinknxg_rental.services import subcontracting as sc
from thinknxg_rental.services.utils import get_settings

EPS = 1e-9


class SubcontractMaterialReturn(Document):
	"""Reconciles issued material: Issued = Installed + Returned Good + Damaged + Missing + still outstanding.
	Good goes back to the yard, damaged to the inspection warehouse, missing to the lost warehouse, installed is consumed
	in the works. Damaged and missing units are charged to the subcontractor and flow into the next settlement."""

	def validate(self):
		swo = sc.work_order_for_document(self, None)
		self.company, self.supplier = swo.company, swo.supplier
		bal = sc.issued_balance(self.subcontract_work_order, exclude_return=self.name)
		total = 0
		seen = set()
		for r in self.items:
			if r.item_code in seen:
				frappe.throw(_("Row {0}: {1} is repeated").format(r.idx, r.item_code))
			seen.add(r.item_code)
			b = bal.get(r.item_code)
			if not b:
				frappe.throw(_("Row {0}: {1} was never issued to this work order").format(r.idx, r.item_code))
			for f in ("installed_qty", "returned_qty", "damaged_qty", "missing_qty"):
				if flt(r.get(f)) < 0:
					frappe.throw(_("Row {0}: quantities cannot be negative").format(r.idx))
			r.issued_qty, r.outstanding_qty = b.issued, b.outstanding
			used = flt(r.installed_qty) + flt(r.returned_qty) + flt(r.damaged_qty) + flt(r.missing_qty)
			if used <= 0:
				frappe.throw(_("Row {0}: nothing reconciled").format(r.idx))
			if used > b.outstanding + EPS:
				frappe.throw(_("Row {0}: {1} reconciled but only {2} is outstanding with the subcontractor").format(r.idx, used, b.outstanding))
			r.recovery_amount = (flt(r.damaged_qty) + flt(r.missing_qty)) * flt(r.recovery_rate)
			total += r.recovery_amount
		self.total_recovery = total

	def before_submit(self):
		sc.require_role(sc.STORE_MANAGER, sc.SITE_ENGINEER, sc.MANAGER)
		sc.lock_work_order(self.subcontract_work_order)
		self.validate()
		if any(flt(r.returned_qty) for r in self.items) and not self.return_warehouse:
			frappe.throw(_("Choose where the returned material goes"))

	def on_submit(self):
		swo = frappe.db.get_value("Subcontract Work Order", self.subcontract_work_order, ["supplier", "customer", "project", "rental_site"], as_dict=True)
		custody = sc.custody_warehouse(self.company)
		s = get_settings()
		moves = []
		for r in self.items:
			for qty, target, movement, label in (
				(r.returned_qty, self.return_warehouse, "Return", "returned"), (r.damaged_qty, s.get("inspection_warehouse"), "Return", "damaged"),
				(r.missing_qty, s.get("lost_warehouse"), "Loss", "missing")):
				if flt(qty) > 0:
					if not target:
						frappe.throw(_("Set the {0} warehouse in Rental Settings").format(label))
					moves.append((r, qty, target, movement))
			if flt(r.installed_qty) > 0:
				moves.append((r, r.installed_qty, None, "Loss"))
		rows = [{"item_code": r.item_code, "qty": q, "s_warehouse": custody, "t_warehouse": t} for r, q, t, m in moves]
		transfers = [x for x in rows if x["t_warehouse"]]
		issues = [x for x in rows if not x["t_warehouse"]]
		# one Stock Entry per purpose: Material Transfer for physical movement, Material Issue for what was installed
		se_transfer = stock.make_stock_entry(self, "Material Transfer", transfers, self.posting_date, _("Returned by subcontractor {0}").format(self.supplier)) if transfers else None
		se_issue = stock.make_stock_entry(self, "Material Issue", issues, self.posting_date, _("Installed by subcontractor {0}").format(self.supplier)) if issues else None
		for r, q, t, m in moves:
			ledger.add_entry(self, posting_date=self.posting_date, position_type=sc.CUSTODY, movement_type=m, item_code=r.item_code, qty=-flt(q),
				ownership="Own", supplier=swo.supplier, customer=swo.customer, project=swo.project, rental_site=swo.rental_site,
				subcontract_work_order=self.subcontract_work_order, warehouse=custody, origin_warehouse=custody, source_warehouse=custody, target_warehouse=t,
				voucher_detail_no=r.name, stock_entry=se_transfer if t else se_issue)

	def before_cancel(self):
		sc.require_role(sc.MANAGER, sc.STORE_MANAGER)
		sc.lock_work_order(self.subcontract_work_order)
		used = frappe.db.sql("""select name from `tabSubcontract Settlement` where subcontract_work_order = %s and docstatus = 1 and ifnull(damage_recovery, 0) > 0""",
			self.subcontract_work_order)
		if used and flt(self.total_recovery):
			frappe.throw(_("Recovery from this return was already taken in settlement {0}. Cancel that settlement first").format(used[0][0]))

	def on_cancel(self):
		stock.cancel_stock_entries(self)
		ledger.delete_entries(self.doctype, self.name)
