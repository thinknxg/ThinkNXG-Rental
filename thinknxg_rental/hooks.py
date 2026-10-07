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
after_migrate = "thinknxg_rental.services.setup.after_migrate"
before_uninstall = "thinknxg_rental.services.setup.before_uninstall"

doc_events = {
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
	"Item": {"validate": "thinknxg_rental.events.item.validate"},
	"Sales Invoice": {
		"on_submit": "thinknxg_rental.events.sales_invoice.on_submit",
		"before_cancel": "thinknxg_rental.events.sales_invoice.unlink",
		"on_trash": "thinknxg_rental.events.sales_invoice.unlink",
		"on_cancel": "thinknxg_rental.events.sales_invoice.on_cancel",
	},
}

doctype_js = {
	"Item": "public/js/item.js",
	"Purchase Order": "public/js/purchase_order.js",
	"Purchase Receipt": "public/js/purchase_receipt.js",
}

# Customer portal (Frappe website pages under /rental)
standard_portal_menu_items = [
	{"title": "Rental Portal", "route": "/rental", "role": "Customer"},
	{"title": "Rental Admin", "route": "/rental/admin", "role": "Rental User"},
]

scheduler_events = {
	"daily": [
		"thinknxg_rental.services.billing.run_daily_billing",
		"thinknxg_rental.services.jcr_billing.run_daily_jcr_billing",
	],
}
