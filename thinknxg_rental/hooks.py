app_name = "thinknxg_rental"
app_title = "thinkNXG Rental"
app_publisher = "thinkNXG"
app_description = "Formwork and scaffolding rental for ERPNext"
app_email = "info@thinknxg.com"
app_license = "mit"
required_apps = ["erpnext"]

add_to_apps_screen = [
	{
		"name": "thinknxg_rental",
		"logo": "/assets/thinknxg_rental/images/logo.svg",
		"title": "thinkNXG Rental",
		"route": "/app/thinknxg-rental",
	}
]

after_install = "thinknxg_rental.services.setup.after_install"
after_migrate = ["thinknxg_rental.services.job_type_migration.run", 
    "thinknxg_rental.services.setup.after_migrate",
    "thinknxg_rental.services.print_formats.sync",
    "thinknxg_rental.services.hide_rotation.run",
    "thinknxg_rental.services.jcr_columns.run",
]
before_uninstall = "thinknxg_rental.services.setup.before_uninstall"

_N = "thinknxg_rental.services.customer_notify."  # customer portal notifications

doc_events = {
	# customer portal notifications (services/customer_notify.py)
	"Rental Contract": {"on_submit": _N + "rental_contract_submitted"},
	"Hire Delivery Order": {"on_submit": _N + "delivery_submitted"},
	"Hire Off-Hire Note": {"on_submit": _N + "off_hire_submitted"},
	"Rental Return Inspection": {"on_submit": _N + "inspection_submitted"},
	"Payment Entry": {"on_submit": _N + "payment_submitted"},
	"Sales Order": {"on_submit": _N + "sales_order_submitted"},
	# Rental section of the Item form: Rental Item Profile saved with the Item
	"Item": {
		"validate": "thinknxg_rental.services.item_rental.item_validate",
		"on_update": ["thinknxg_rental.services.item_rental.item_on_update", "thinknxg_rental.website.catalogue.clear_cache"],
	},
	# public rental website (/hire): product slugs and the category cache
	"Rental Item Profile": {
		"validate": "thinknxg_rental.website.catalogue.ensure_route",
		"on_update": "thinknxg_rental.website.catalogue.clear_cache",
		"on_trash": "thinknxg_rental.website.catalogue.clear_cache",
	},
	"Item Group": {"on_update": "thinknxg_rental.website.catalogue.clear_cache", "on_trash": "thinknxg_rental.website.catalogue.clear_cache"},
	"Hire Order Contract": {
	    "validate": "thinknxg_rental.events.default_terms.apply",
	},
	# a project is not completed while its rental material is not reconciled (services/excess.py)
	"Project": {"validate": "thinknxg_rental.services.excess.project_validate"},
	"Purchase Order": {
		"before_validate": "thinknxg_rental.events.purchase.po_before_validate",
		"validate": "thinknxg_rental.events.purchase.po_validate",
	},
	"Purchase Receipt": {
		"before_validate": "thinknxg_rental.events.purchase.pr_before_validate",
		"validate": "thinknxg_rental.events.purchase.pr_validate",
		"on_submit": "thinknxg_rental.events.purchase.pr_on_submit",
		"on_cancel": "thinknxg_rental.events.purchase.pr_on_cancel",
	},
	"Purchase Invoice": {
		"on_submit": "thinknxg_rental.events.purchase.pi_update_cross_hire",
		"on_cancel": "thinknxg_rental.events.purchase.pi_update_cross_hire",
	},
	"Quotation": {
		"on_submit": _N + "quotation_submitted",
		"validate": [
		    # rates and rate basis first: the hire amounts below are worked out from Rate
		    "thinknxg_rental.services.item_rental.quotation_rates",
		    "thinknxg_rental.events.quotation.validate",
		    "thinknxg_rental.events.default_terms.apply",
		    "thinknxg_rental.services.item_rental.quotation_charges",
		],
		# item picked in the form (ERPNext v16 does this on the server): the row's rental charge defaults
		"process_item_selection": "thinknxg_rental.services.item_rental.quotation_item_selected",
	},
	# transfers between rental locations: ownership kept apart, reservations respected, nothing at sites
	"Stock Entry": {
		"validate": "thinknxg_rental.events.stock_entry.validate",
		"on_submit": "thinknxg_rental.events.stock_entry.on_submit",
		"on_cancel": "thinknxg_rental.events.stock_entry.on_cancel",
	},
	"Sales Invoice": {
		"validate": [
		    "thinknxg_rental.events.sales_invoice.validate",
		    "thinknxg_rental.events.default_terms.apply",
		],
		"on_submit": ["thinknxg_rental.events.sales_invoice.on_submit", _N + "sales_invoice_submitted"],
		"before_cancel": "thinknxg_rental.events.sales_invoice.unlink",
		"on_trash": "thinknxg_rental.events.sales_invoice.unlink",
		"on_cancel": "thinknxg_rental.events.sales_invoice.on_cancel",
	},
}

app_include_js = ["/assets/thinknxg_rental/js/rental_flow.js", "/assets/thinknxg_rental/js/rental_menu.js"]
app_include_css = ["/assets/thinknxg_rental/css/thinknxg_rental.css", "/assets/thinknxg_rental/css/rental_menu.css"]

doctype_js = {
	"Item": "public/js/item_rental.js",
	"Lead": "public/js/lead_deal.js",
	"Quotation": "public/js/quotation_deal.js",
	"Purchase Order": "public/js/purchase_order.js",
	"Purchase Receipt": "public/js/purchase_receipt.js",
	"Sales Invoice": "public/js/sales_invoice.js",
	# forms whose setup uses thinknxg_rental.rental_warehouses(): the helper travels with the form
	"Rental Material Reservation": "public/js/rental_warehouses.js",
	"Hire Delivery Order": "public/js/rental_warehouses.js",
	"Hire Off-Hire Note": ["public/js/rental_warehouses.js", "public/js/excess_material.js"],
	# excess material, returns and adjustments: shared dialogs travel with each form
	"Rental Contract": "public/js/excess_material.js",
	"Excess Material Register": "public/js/excess_material.js",
	"Excess Material Return Note": "public/js/excess_material.js",
	"Dismantling Entry": "public/js/excess_material.js",
	"Excess Material Conversion Entry": ["public/js/rental_warehouses.js", "public/js/excess_material.js"],
	"Cross Hire Order": "public/js/rental_warehouses.js",
	"Rental Return Inspection": "public/js/rental_warehouses.js",
}

# Command Center: one single-page application answers every path under /rental/admin
# (www/rental/admin/index.html).
page_renderer = ["thinknxg_rental.website.renderer.RentalWebsitePage"]

website_route_rules = [
	{"from_route": "/rental/admin", "to_route": "rental/admin"},
	{"from_route": "/rental/admin/<path:app_path>", "to_route": "rental/admin"},
	# public rental website: every page under /hire is served by www/hire/index.py
	{"from_route": "/hire/<path:app_path>", "to_route": "hire"},
	# customer Command Center: one single-page application for /rental and every path under it
	{"from_route": "/rental/<path:app_path>", "to_route": "rental"},
]

# Customer Command Center (www/rental/index.html, public/customer_portal)
standard_portal_menu_items = [
	{"title": "Rental Portal", "route": "/rental", "role": "Customer"},
	{"title": "Rental Command Center", "route": "/rental/admin", "role": "Rental User"},
]

scheduler_events = {
	"daily": [
		"thinknxg_rental.services.billing.run_daily_billing",
		"thinknxg_rental.services.jcr_billing.run_daily_jcr_billing",
		"thinknxg_rental.services.customer_notify.rental_expiry_reminders",
	],
}
