import frappe
from frappe.model.document import Document

from thinknxg_rental.services.project_link import link_site_project
from thinknxg_rental.services.setup import ensure_warehouse
from thinknxg_rental.services.utils import get_settings


class RentalSite(Document):
	def validate(self):
		if self.nxg_quotation and (self.is_new() or self.has_value_changed("nxg_quotation")):
			# Project from the quotation / lead, or found or created from their Project Title;
			# only empty Project links are filled (services/project_link.py)
			link_site_project(self)
		if not self.site_warehouse or not self.cross_hire_site_warehouse:
			self.create_warehouses()

	def create_warehouses(self):
		"""Two leaf warehouses per site so own stock and supplier-owned stock never share a valuation pool."""
		parent = get_settings().customer_sites_warehouse
		if not parent or frappe.db.get_value("Warehouse", parent, "company") != self.company:
			parent = ensure_warehouse("Customer Sites", self.company, is_group=1)
		if not self.site_warehouse:
			self.site_warehouse = ensure_warehouse(f"{self.site_name} (Own)", self.company, parent)
		if not self.cross_hire_site_warehouse:
			self.cross_hire_site_warehouse = ensure_warehouse(f"{self.site_name} (Cross Hire)", self.company, parent)
