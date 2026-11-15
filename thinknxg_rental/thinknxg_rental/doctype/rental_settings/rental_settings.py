import frappe
from frappe import _
from frappe.model.document import Document

from thinknxg_rental.services import warehouses as rw


class RentalSettings(Document):
	def validate(self):
		self.validate_rental_warehouses()

	def validate_rental_warehouses(self):
		"""Own Rental Warehouses and Cross Hire Warehouses: leaf warehouses of the company, each in one
		table once, one active default per table. The legacy yard fields follow the defaults."""
		special = {self.get(f): self.meta.get_label(f) for f in rw.SPECIAL_FIELDS if self.get(f)}
		if self.customer_sites_warehouse:
			special[self.customer_sites_warehouse] = self.meta.get_label("customer_sites_warehouse")
		seen = {}
		for category, (table, legacy) in rw.TABLES.items():
			label = self.meta.get_label(table)
			rows = self.get(table)
			# the legacy field set by hand (or by older code) becomes the table's default
			value = self.get(legacy)
			if value and (not rows or (self.has_value_changed(legacy) and value not in [r.warehouse for r in rows if r.is_default])):
				row = next((r for r in rows if r.warehouse == value), None) or self.append(table, {"warehouse": value, "is_active": 1})
				for r in self.get(table):
					r.is_default = 1 if r is row else 0
				row.is_active = 1
				rows = self.get(table)
			for r in rows:
				prefix = _("{0} row #{1}: ").format(label, r.idx)
				if not r.warehouse:
					frappe.throw(prefix + _("Warehouse is mandatory"))
				wh = frappe.db.get_value("Warehouse", r.warehouse, ["is_group", "company", "disabled"], as_dict=True)
				if not wh:
					frappe.throw(prefix + _("Warehouse {0} does not exist").format(r.warehouse))
				if wh.is_group:
					frappe.throw(prefix + _("{0} is a group warehouse; select a warehouse that holds stock").format(frappe.bold(r.warehouse)))
				if self.company and wh.company != self.company:
					frappe.throw(prefix + _("{0} belongs to {1}, not {2}").format(frappe.bold(r.warehouse), wh.company, self.company))
				if r.warehouse in special:
					frappe.throw(prefix + _("{0} is the {1} and cannot also be a rental warehouse").format(frappe.bold(r.warehouse), special[r.warehouse]))
				if rw.is_site_warehouse(r.warehouse):
					frappe.throw(prefix + _("{0} is a customer site warehouse").format(frappe.bold(r.warehouse)))
				if r.warehouse in seen:
					other = seen[r.warehouse]
					if other == table:
						frappe.throw(prefix + _("{0} is listed twice").format(frappe.bold(r.warehouse)))
					frappe.throw(prefix + _("{0} is already in {1}: own and cross hire stock are kept in separate warehouses").format(
						frappe.bold(r.warehouse), self.meta.get_label(other)))
				seen[r.warehouse] = table
				if wh.disabled and r.is_active:
					r.is_active = 0
				r.location = r.location or rw.default_location(r.warehouse)
			if not rows:
				continue
			defaults = [r for r in rows if r.is_default]
			if len(defaults) > 1:
				frappe.throw(_("{0}: only one warehouse can be the default ({1})").format(label, ", ".join(r.warehouse for r in defaults)))
			if not defaults:
				first = next((r for r in rows if r.is_active), None)
				if not first:
					frappe.throw(_("{0}: at least one warehouse must be active").format(label))
				first.is_default = 1
				defaults = [first]
			if not defaults[0].is_active:
				frappe.throw(_("{0}: the default warehouse {1} must be active").format(label, frappe.bold(defaults[0].warehouse)))
			self.set(legacy, defaults[0].warehouse)

	def on_update(self):
		frappe.clear_cache(doctype="Rental Settings")
