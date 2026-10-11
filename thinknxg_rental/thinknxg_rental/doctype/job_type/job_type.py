import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class JobType(Document):
    def validate(self):
        item = frappe.get_cached_value("Item", self.item_code, ["is_stock_item", "is_fixed_asset", "disabled"], as_dict=True)
        if not item:
            frappe.throw(_("Item {0} not found").format(frappe.bold(self.item_code)))
        if cint(item.is_stock_item):
            frappe.throw(_("A Job Type Item must be a non-stock item. Untick Maintain Stock on {0}.").format(frappe.bold(self.item_code)))
        if cint(item.is_fixed_asset):
            frappe.throw(_("A Job Type Item cannot be a fixed asset."))
        if not self.rental_items and not self.flags.from_migration:
            frappe.throw(_("Add at least one rental item for one job."))
        seen = set()
        for r in self.rental_items:
            if r.item_code in seen:
                frappe.throw(_("Row #{0}: {1} is listed twice").format(r.idx, frappe.bold(r.item_code)))
            seen.add(r.item_code)
            if not cint(frappe.get_cached_value("Item", r.item_code, "is_stock_item")):
                frappe.throw(_("Row #{0}: {1} must be a stock item").format(r.idx, frappe.bold(r.item_code)))
            if flt(r.qty) <= 0:
                frappe.throw(_("Row #{0}: Qty per Job must be greater than zero").format(r.idx))
