"""Page renderer for the rental website: the /hire pages are ordinary Frappe template pages, except that
a missing product or page inside the website is shown with the website's own layout and still answered
with HTTP 404 (so search engines drop it). Registered through the page_renderer hook."""
import frappe
from frappe.website.page_renderers.template_page import TemplatePage


class RentalWebsitePage(TemplatePage):
	def can_render(self):
		return self.path == "hire" and super().can_render()

	def render(self):
		frappe.local.flags.rw_not_found = False
		response = super().render()
		if frappe.local.flags.get("rw_not_found"):
			response.status_code = 404
		return response
