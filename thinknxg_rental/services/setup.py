"""Install / migrate setup: custom fields on ERPNext documents, UOMs, service items, warehouses."""
import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def get_custom_fields():
	return {
		"Item": [
			dict(fieldname="nxg_is_job_type_item", label="Is Job Type Item", fieldtype="Check", insert_after="is_stock_item",
				depends_on="eval:!doc.is_stock_item", in_standard_filter=1,
				description="A job hired out as a unit, such as External Scaffolding. Non-stock. Its rental items are listed below."),
			# a Tab Break, not a Section Break: Frappe pushes a custom section placed at the end of a tab
			# into the top of the next tab, where nobody looks for it
			dict(fieldname="nxg_job_type_section", label="Job Type Rental Items", fieldtype="Tab Break",
				insert_after="description", depends_on="nxg_is_job_type_item"),
			dict(fieldname="nxg_job_type_items", label="Physical Rental Items for One Job", fieldtype="Table",
				options="Job Type Rental Item", insert_after="nxg_job_type_section"),
		],
		"Purchase Order": [
			dict(fieldname="nxg_is_cross_hire", label="Is Cross Hire Order", fieldtype="Check", read_only=1, no_copy=1,
				insert_after="order_confirmation_date", in_standard_filter=1, depends_on="nxg_is_cross_hire"),
			dict(fieldname="nxg_cross_hire_order", label="Cross Hire Order", fieldtype="Link", options="Cross Hire Order",
				read_only=1, no_copy=1, insert_after="nxg_is_cross_hire", depends_on="nxg_is_cross_hire"),
			dict(fieldname="nxg_rental_contract", label="Customer Rental Contract", fieldtype="Link",
				options="Rental Contract", read_only=1, no_copy=1, insert_after="nxg_cross_hire_order",
				depends_on="nxg_rental_contract"),
		],
		"Purchase Order Item": [
			dict(fieldname="nxg_is_cross_hire_charge", label="Is Cross Hire Charge Line", fieldtype="Check", read_only=1,
				insert_after="description", print_hide=1),
			dict(fieldname="nxg_cross_hire_item", label="Cross Hire Equipment", fieldtype="Link", options="Item",
				read_only=1, insert_after="nxg_is_cross_hire_charge", depends_on="nxg_is_cross_hire_charge"),
			dict(fieldname="nxg_cross_hire_rate", label="Cross Hire Rate", fieldtype="Currency", read_only=1,
				insert_after="nxg_cross_hire_item", depends_on="eval:doc.nxg_cross_hire_rate"),
			dict(fieldname="nxg_cross_hire_rate_basis", label="Cross Hire Rate Basis", fieldtype="Data", read_only=1,
				insert_after="nxg_cross_hire_rate", depends_on="eval:doc.nxg_cross_hire_rate"),
		],
		"Purchase Receipt": [
			dict(fieldname="nxg_is_cross_hire_receipt", label="Is Cross Hire Receipt", fieldtype="Check",
				insert_after="is_return", in_standard_filter=1,
				description="Quantity only: every line is received at zero rate and zero valuation"),
			dict(fieldname="nxg_cross_hire_order", label="Cross Hire Order", fieldtype="Link", options="Cross Hire Order",
				insert_after="nxg_is_cross_hire_receipt", depends_on="nxg_is_cross_hire_receipt",
				mandatory_depends_on="nxg_is_cross_hire_receipt", in_standard_filter=1),
			dict(fieldname="nxg_cross_hire_off_hire_note", label="Cross Hire Off-Hire Note", fieldtype="Link",
				options="Cross Hire Off-Hire Note", read_only=1, no_copy=1, insert_after="nxg_cross_hire_order",
				depends_on="nxg_cross_hire_off_hire_note"),
			dict(fieldname="nxg_cross_hire_last_billable_date", label="Supplier Bills Upto", fieldtype="Date",
				read_only=1, no_copy=1, insert_after="nxg_cross_hire_off_hire_note",
				depends_on="nxg_cross_hire_off_hire_note"),
		],
		"Purchase Invoice": [
			dict(fieldname="nxg_cross_hire_order", label="Cross Hire Order", fieldtype="Link", options="Cross Hire Order",
				insert_after="is_return", no_copy=1, in_standard_filter=1),
			dict(fieldname="nxg_cross_hire_billing_from", label="Hire Billing From", fieldtype="Date", no_copy=1,
				insert_after="nxg_cross_hire_order", depends_on="nxg_cross_hire_order"),
			dict(fieldname="nxg_cross_hire_billing_to", label="Hire Billing To", fieldtype="Date", no_copy=1,
				insert_after="nxg_cross_hire_billing_from", depends_on="nxg_cross_hire_order"),
		],
		"Purchase Invoice Item": [
			dict(fieldname="nxg_cross_hire_item", label="Cross Hire Equipment", fieldtype="Link", options="Item",
				read_only=1, insert_after="description"),
		],
		"Sales Invoice": [
			dict(fieldname="nxg_rental_contract", label="Rental Contract", fieldtype="Link", options="Rental Contract",
				insert_after="is_return", no_copy=1, in_standard_filter=1),
			dict(fieldname="nxg_rental_billing_schedule", label="Rental Billing Schedule", fieldtype="Link",
				options="Rental Billing Schedule", read_only=1, no_copy=1, insert_after="nxg_rental_contract",
				depends_on="nxg_rental_billing_schedule"),
			dict(fieldname="nxg_rental_damage_settlement", label="Rental Damage Settlement", fieldtype="Link",
				options="Rental Damage Settlement", read_only=1, no_copy=1, insert_after="nxg_rental_billing_schedule",
				depends_on="nxg_rental_damage_settlement"),
			dict(fieldname="nxg_jcr", label="Job Completion Report", fieldtype="Link", options="Job Completion Report",
				read_only=1, no_copy=1, insert_after="nxg_rental_damage_settlement", depends_on="nxg_jcr"),
			dict(fieldname="nxg_jcr_billing_schedule", label="JCR Billing Schedule", fieldtype="Link",
				options="JCR Billing Schedule", read_only=1, no_copy=1, insert_after="nxg_jcr", depends_on="nxg_jcr"),
		],
		"Sales Invoice Item": [
			dict(fieldname="nxg_hire_item", label="Hire Equipment", fieldtype="Link", options="Item", read_only=1,
				insert_after="description"),
			dict(fieldname="nxg_hire_qty", label="Qty on Hire", fieldtype="Float", read_only=1, insert_after="nxg_hire_item"),
			dict(fieldname="nxg_hire_from", label="Hire From", fieldtype="Date", read_only=1, insert_after="nxg_hire_qty"),
			dict(fieldname="nxg_hire_to", label="Hire To", fieldtype="Date", read_only=1, insert_after="nxg_hire_from"),
			dict(fieldname="nxg_hire_days", label="Hire Days", fieldtype="Int", read_only=1, insert_after="nxg_hire_to"),
		],
		"Stock Entry": [
			dict(fieldname="nxg_rental_contract", label="Rental Contract", fieldtype="Link", options="Rental Contract",
				read_only=1, no_copy=1, insert_after="remarks", depends_on="nxg_rental_contract"),
			dict(fieldname="nxg_hire_voucher_type", label="Rental Document Type", fieldtype="Link", options="DocType",
				read_only=1, no_copy=1, insert_after="nxg_rental_contract", depends_on="nxg_hire_voucher_no"),
			dict(fieldname="nxg_hire_voucher_no", label="Rental Document", fieldtype="Dynamic Link",
				options="nxg_hire_voucher_type", read_only=1, no_copy=1, insert_after="nxg_hire_voucher_type",
				depends_on="nxg_hire_voucher_no"),
		],
	}


def after_install():
	after_migrate()
	company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
	if company:
		try:
			setup_company(company)
		except Exception:
			frappe.log_error(title="thinkNXG Rental: default setup failed", message=frappe.get_traceback())


def after_migrate():
	create_custom_fields(get_custom_fields(), ignore_validate=True)
	setup_uoms()
	ensure_settings_defaults()
	frappe.clear_cache()


def ensure_settings_defaults():
	"""A setting added in an upgrade has no stored value on an existing site, so its default
	(for example "on") would silently read as off. Store the default once."""
	stored = set(frappe.db.sql_list("select field from `tabSingles` where doctype = 'Rental Settings'"))
	if not stored:
		return  # never saved: defaults apply when it is first opened
	for df in frappe.get_meta("Rental Settings").fields:
		if df.default and df.fieldname not in stored and df.fieldtype not in ("Section Break", "Column Break", "Tab Break"):
			frappe.db.set_single_value("Rental Settings", df.fieldname, df.default)


def before_uninstall():
	for dt, custom_fields in get_custom_fields().items():
		for df in custom_fields:
			name = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": df["fieldname"]})
			if name:
				frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)


def setup_uoms():
	for uom in ("Unit-Day", "Unit-Week", "Unit-Month", "Charge"):
		if not frappe.db.exists("UOM", uom):
			frappe.get_doc({"doctype": "UOM", "uom_name": uom, "must_be_whole_number": 0}).insert(ignore_permissions=True)


def get_root(doctype, parent_field, company=None):
	filters = {"is_group": 1, parent_field: ["is", "not set"]}
	if company:
		filters["company"] = company
	return frappe.db.get_value(doctype, filters, "name")


def ensure_warehouse(warehouse_name, company, parent=None, is_group=0):
	existing = frappe.db.get_value("Warehouse", {"warehouse_name": warehouse_name, "company": company}, "name")
	if existing:
		return existing
	wh = frappe.get_doc(
		{
			"doctype": "Warehouse",
			"warehouse_name": warehouse_name,
			"company": company,
			"is_group": is_group,
			"parent_warehouse": parent or get_root("Warehouse", "parent_warehouse", company),
		}
	)
	wh.flags.ignore_permissions = True
	wh.insert()
	return wh.name


def ensure_service_item(item_code, item_name, item_group, uom, sales, purchase, with_period_uoms=False):
	if frappe.db.exists("Item", item_code):
		return item_code
	item = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_name,
			"description": item_name,
			"item_group": item_group,
			"stock_uom": uom,
			"is_stock_item": 0,
			"is_sales_item": sales,
			"is_purchase_item": purchase,
			"include_item_in_manufacturing": 0,
		}
	)
	if with_period_uoms:
		item.append("uoms", {"uom": "Unit-Day", "conversion_factor": 1})
		item.append("uoms", {"uom": "Unit-Week", "conversion_factor": 7})
		item.append("uoms", {"uom": "Unit-Month", "conversion_factor": 30})
	item.flags.ignore_permissions = True
	item.insert()
	return item.name


@frappe.whitelist()
def setup_company(company: str | None = None):
	"""Create default warehouses and service items and store them in Rental Settings. Safe to re-run."""
	frappe.only_for(("System Manager", "Rental Manager"))
	setup_uoms()
	settings = frappe.get_doc("Rental Settings")
	company = company or settings.company
	if not company:
		frappe.throw(_("Select a company first"))
	settings.company = company

	warehouses = {
		"rental_yard_warehouse": ("Rental Yard", 0),
		"cross_hire_yard_warehouse": ("Cross Hire Yard", 0),
		"inspection_warehouse": ("Rental Under Inspection", 0),
		"repair_warehouse": ("Rental Repair", 0),
		"scrap_warehouse": ("Rental Scrap", 0),
		"customer_sites_warehouse": ("Customer Sites", 1),
	}
	for field, (label, is_group) in warehouses.items():
		current = settings.get(field)
		if not current or frappe.db.get_value("Warehouse", current, "company") != company:
			settings.set(field, ensure_warehouse(label, company, is_group=is_group))

	group = frappe.db.exists("Item Group", "Rental Services")
	if not group:
		doc = frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": "Rental Services",
				"parent_item_group": get_root("Item Group", "parent_item_group"),
				"is_group": 0,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		group = doc.name
	items = {
		"rental_charge_item": ("RENTAL-CHARGES", "Rental Charges", "Unit-Day", 1, 0, True),
		"cross_hire_charge_item": ("CROSS-HIRE-CHARGES", "Cross Hire Charges", "Unit-Day", 0, 1, True),
		"damage_recovery_item": ("RENTAL-DAMAGE-RECOVERY", "Rental Damage Recovery", "Charge", 1, 0, False),
		"loss_recovery_item": ("RENTAL-LOSS-RECOVERY", "Rental Loss Recovery", "Charge", 1, 0, False),
	}
	for field, (code, name, uom, sales, purchase, period) in items.items():
		if not settings.get(field):
			settings.set(field, ensure_service_item(code, name, group, uom, sales, purchase, period))
	settings.flags.ignore_permissions = True
	settings.save()
	return settings.as_dict()
