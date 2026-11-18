"""Install / migrate setup: custom fields on ERPNext documents, UOMs, service items, warehouses."""
import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

from thinknxg_rental.services import desk_menu


# Quotation deal types that use Length / Breadth / Height / Duration. Keep in step with
# events/quotation.py and public/js/quotation_deal.js.
HIRE_DEPENDS_ON = 'eval:["Material Hire", "Hire Order Contract"].includes(parent.deal_type)'
HOC_DEPENDS_ON = 'eval:parent.deal_type=="Hire Order Contract"'
MS_DEPENDS_ON = 'eval:["Material Sale", "Material Hire"].includes(parent.deal_type)'
MH_DEPENDS_ON = 'eval:parent.deal_type=="Material Hire"'


def get_custom_fields():
	return {
		# Rental section of the Item form (services/item_rental.py, public/js/item_rental.js). Nothing is
		# stored on the Item; the profile values live in Rental Item Profile.
		"Item": [
			dict(fieldname="nxg_rental_section", label="Rental", fieldtype="Section Break", insert_after="asset_naming_series",
				depends_on="eval:doc.is_stock_item", collapsible=0),
			dict(fieldname="nxg_rental_profile_html", label="Rental Item Profile", fieldtype="HTML",
				insert_after="nxg_rental_section", depends_on="eval:doc.is_stock_item"),
		],
		"Lead": [
			dict(fieldname="deal_type", label="Deal Type", fieldtype="Select",
				options="Material Hire\nMaterial Sale\nHire Order Contract", insert_after="status", in_standard_filter=1,
				description="Identifies the customer requirement and selects the downstream document flow."),
			# The project's intended name before a Project exists. ERPNext's Lead has no Project; the
			# Project link is filled when the Rental Site is made (services/project_link.py), only if empty.
			dict(fieldname="project_title", label="Project Title", fieldtype="Data", insert_after="deal_type",
				description="Name of the customer's project. A Project with this name is linked when the Rental Site is created."),
			dict(fieldname="project", label="Project", fieldtype="Link", options="Project", insert_after="project_title"),
			dict(fieldname="rental_site", label="Rental Site", fieldtype="Link", options="Rental Site", insert_after="project",
			        description="Optional. The customer's site for this requirement; carried to the Quotation."),
			# Layout (Nov 2026): Organization & Contact at the top, then Project & Deal, then Tender & Assignment.
			# The order itself is set by arrange_lead_layout(); Gender, Branches and the hire-period fields are hidden, not removed.
			dict(fieldname="nxg_contact_sb", label="Contact Person", fieldtype="Section Break", insert_after="last_name"),
			dict(fieldname="nxg_branches", label="Branches / Subsidiary Companies", fieldtype="Small Text", insert_after="company_name", hidden=1),
			dict(fieldname="nxg_project_sb", label="Project & Deal", fieldtype="Section Break", insert_after="phone_ext"),
			dict(fieldname="nxg_project_cb", label="", fieldtype="Column Break", insert_after="project"),
			dict(fieldname="nxg_project_contact_name", label="Project Contact Name", fieldtype="Data", insert_after="project"),
			dict(fieldname="nxg_project_contact_job_title", label="Project Contact Job Title", fieldtype="Data", insert_after="nxg_project_contact_name"),
			dict(fieldname="nxg_project_contact_gender", label="Gender", fieldtype="Link", options="Gender", insert_after="nxg_project_contact_job_title", hidden=1),
			dict(fieldname="nxg_project_contact_email", label="Project Contact Email", fieldtype="Data", options="Email", insert_after="nxg_project_contact_gender"),
			dict(fieldname="nxg_required_from", label="Required From", fieldtype="Date", insert_after="project", hidden=1, mandatory_depends_on=""),
			dict(fieldname="nxg_expected_return_date", label="Expected Return Date", fieldtype="Date", insert_after="nxg_required_from", hidden=1, mandatory_depends_on=""),
			dict(fieldname="nxg_hire_period_days", label="Hire Period (Days)", fieldtype="Int", insert_after="nxg_expected_return_date", read_only=1, no_copy=1, hidden=1),
			dict(fieldname="nxg_tender_sb", label="Tender & Assignment", fieldtype="Section Break", insert_after="nxg_project_contact_email"),
			dict(fieldname="nxg_tender_assignee", label="Tender (Assignee) Name", fieldtype="Link", options="User", insert_after="nxg_tender_sb", description="Defaults to the Lead Owner; change it if the tender is assigned to someone else."),
			dict(fieldname="nxg_tender_cb", label="", fieldtype="Column Break", insert_after="nxg_tender_assignee"),
			dict(fieldname="nxg_tender_final_submission_date", label="Tender Final Submission Date", fieldtype="Date", insert_after="nxg_tender_cb"),
			dict(fieldname="nxg_tender_finalization_date", label="Tender Finalization Date", fieldtype="Date", insert_after="nxg_tender_final_submission_date"),
			dict(fieldname="nxg_owner_sb", label="Lead Owner Details", fieldtype="Section Break", insert_after="nxg_tender_finalization_date"),
			dict(fieldname="nxg_owner_salutation", label="Salutation", fieldtype="Link", options="Salutation", insert_after="nxg_owner_sb"),
			dict(fieldname="nxg_owner_first_name", label="First Name", fieldtype="Data", insert_after="nxg_owner_salutation", read_only=1, fetch_from="lead_owner.first_name"),
			dict(fieldname="nxg_owner_last_name", label="Last Name", fieldtype="Data", insert_after="nxg_owner_first_name", read_only=1, fetch_from="lead_owner.last_name"),
			dict(fieldname="nxg_owner_job_title", label="Job Title", fieldtype="Data", insert_after="nxg_owner_last_name"),
			dict(fieldname="nxg_owner_cb", label="", fieldtype="Column Break", insert_after="nxg_owner_job_title"),
			dict(fieldname="nxg_owner_gender", label="Gender", fieldtype="Link", options="Gender", insert_after="nxg_owner_cb", read_only=1, fetch_from="lead_owner.gender", hidden=1),
			dict(fieldname="nxg_owner_email", label="Email", fieldtype="Data", options="Email", insert_after="nxg_owner_gender", read_only=1, fetch_from="lead_owner.email"),
			dict(fieldname="nxg_owner_phone", label="Tel. Number", fieldtype="Data", insert_after="nxg_owner_email", read_only=1, fetch_from="lead_owner.phone"),
			dict(fieldname="nxg_owner_ext", label="Extension", fieldtype="Data", insert_after="nxg_owner_phone"),
			dict(fieldname="nxg_owner_mobile", label="Mobile", fieldtype="Data", insert_after="nxg_owner_ext", read_only=1, fetch_from="lead_owner.mobile_no"),
		],
		"Quotation": [
			# ERPNext's Quotation has no Project or Cost Center; same names as on Sales Order so the
			# standard Quotation -> Sales Order mapping carries them.
			dict(fieldname="project_title", label="Project Title", fieldtype="Data", insert_after="order_type",
				description="Name of the customer's project, from the Lead. A Project with this name is linked when the Rental Site is created."),
			dict(fieldname="project", label="Project", fieldtype="Link", options="Project", insert_after="project_title"),
			dict(fieldname="cost_center", label="Cost Center", fieldtype="Link", options="Cost Center", insert_after="project"),
			dict(fieldname="rental_site", label="Rental Site", fieldtype="Link", options="Rental Site", insert_after="cost_center",
			        description="Optional. The customer's site for this requirement; carried from the Lead to the Hire Order and Hire Order Contract."),
			dict(fieldname="deal_type", label="Deal Type", fieldtype="Select",
				options="Material Hire\nMaterial Sale\nHire Order Contract", insert_after="quotation_to", in_standard_filter=1,
				description="Carries the Deal Type from the Lead and selects the next document."),
			dict(fieldname="nxg_hire_period_sb", label="Hire Period", fieldtype="Section Break", insert_after="amended_from", depends_on="eval:doc.deal_type=='Material Hire'"),
			dict(fieldname="nxg_required_from", label="Required From", fieldtype="Date", insert_after="nxg_hire_period_sb", depends_on="eval:doc.deal_type=='Material Hire'", mandatory_depends_on=""),
			dict(fieldname="nxg_expected_return_date", label="Expected Return Date", fieldtype="Date", insert_after="nxg_required_from", depends_on="eval:doc.deal_type=='Material Hire'", mandatory_depends_on=""),
			dict(fieldname="nxg_hire_period_cb", label="", fieldtype="Column Break", insert_after="nxg_expected_return_date"),
			dict(fieldname="nxg_default_rate_basis", label="Default Rate Basis", fieldtype="Select", options="Monthly\nWeekly\nDaily", default="Monthly", insert_after="nxg_hire_period_cb", depends_on="eval:doc.deal_type=='Material Hire'"),
			dict(fieldname="nxg_billing_cycle", label="Billing Cycle", fieldtype="Select", options="Monthly\nWeekly\nDaily\nCustom", default="Monthly", insert_after="nxg_default_rate_basis", depends_on="eval:doc.deal_type=='Material Hire'"),
			# public website: the enquiry it came from, and the customer's acceptance in the customer portal
			dict(fieldname="nxg_website_enquiry", label="Website Enquiry", fieldtype="Link", options="Rental Website Enquiry", insert_after="nxg_billing_cycle", read_only=1, no_copy=1),
			dict(fieldname="nxg_customer_accepted_on", label="Accepted by Customer On", fieldtype="Datetime", insert_after="nxg_website_enquiry", read_only=1, allow_on_submit=1, no_copy=1),
			dict(fieldname="nxg_customer_accepted_by", label="Accepted by", fieldtype="Link", options="User", insert_after="nxg_customer_accepted_on", read_only=1, allow_on_submit=1, no_copy=1),
		],
		# Dimensions and duration for hire quotations. Shown only for the hire deal types; the amount is
		# Qty x Unit Price x Duration (see events/quotation.py and public/js/quotation_deal.js).
		"Quotation Item": [
			dict(fieldname="nxg_length", label="Length", fieldtype="Float", insert_after="item_name", in_list_view=1, columns=1,
				depends_on=HOC_DEPENDS_ON),
			dict(fieldname="nxg_breadth", label="Breadth", fieldtype="Float", insert_after="nxg_length", in_list_view=1, columns=1,
				depends_on=HOC_DEPENDS_ON),
			dict(fieldname="nxg_height", label="Height", fieldtype="Float", insert_after="nxg_breadth", in_list_view=1, columns=1,
				depends_on=HOC_DEPENDS_ON),
			dict(fieldname="nxg_duration", label="Rotation", fieldtype="Int", insert_after="nxg_height", in_list_view=1, columns=1,
				depends_on=HOC_DEPENDS_ON,
				description="Number of periods. Amount = Qty x Unit Price x Duration. Blank counts as 1."),
			dict(fieldname="nxg_period", label="Period", fieldtype="Select", options="Days\nWeekly\nMonthly\nTimes",
				insert_after="nxg_duration", in_list_view=1, columns=1, depends_on=HOC_DEPENDS_ON),
                    dict(fieldname="nxg_weight", label="Weight", fieldtype="Float", insert_after="description", in_list_view=1, columns=1,
                            depends_on=MS_DEPENDS_ON),
			dict(fieldname="nxg_included_days", label="Contract Days", fieldtype="Int", insert_after="nxg_period", in_list_view=1, columns=1, depends_on=HIRE_DEPENDS_ON, description="Included contract days per job. Carried into the Hire Order Contract line."),
			dict(fieldname="nxg_excess_basis", label="Excess Basis", fieldtype="Select", options="Daily\nWeekly\nMonthly", default="Daily", insert_after="nxg_included_days", in_list_view=1, columns=1, depends_on=HIRE_DEPENDS_ON),
			dict(fieldname="nxg_excess_rate", label="Excess Rate", fieldtype="Currency", options="currency", insert_after="nxg_excess_basis", in_list_view=1, columns=1, depends_on=HIRE_DEPENDS_ON, description="Excess charge per job for each day / week / month beyond the contract days."),
			dict(fieldname="nxg_rate_basis", label="Rate Basis", fieldtype="Select", options="Monthly\nWeekly\nDaily", default="Monthly", insert_after="nxg_excess_rate", in_list_view=1, columns=1, depends_on=MH_DEPENDS_ON),
			dict(fieldname="nxg_hire_days", label="Hire Days", fieldtype="Int", insert_after="nxg_rate_basis", in_list_view=1, columns=1, depends_on=MH_DEPENDS_ON, description="Amount = Qty x Hire Days / basis days x Rate. Blank counts as one rate period."),
			dict(fieldname="nxg_rate_basis_amount", label="Rate Basis Amount", fieldtype="Currency", options="currency", read_only=1, insert_after="nxg_hire_days", in_list_view=1, columns=1, depends_on=MH_DEPENDS_ON, description="Qty x Rate"),
			dict(fieldname="nxg_estimated_amount", label="Estimated Amount", fieldtype="Currency", options="currency", read_only=1, insert_after="nxg_rate_basis_amount", in_list_view=1, columns=1, depends_on=MH_DEPENDS_ON),
			# Damage and loss charges agreed on this quotation: the Rental Item Profile's values when the
			# item is picked (services/item_rental.py), then this row's own, never written back.
			# The item's rates when it is picked (rate card or Rental Item Profile); editable, the row's Rate
			# follows its Rate Basis (services/item_rental.py quotation_rates)
			dict(fieldname="nxg_rates_section", label="Rental Rates", fieldtype="Section Break", insert_after="nxg_estimated_amount",
				depends_on=MH_DEPENDS_ON),
			dict(fieldname="nxg_daily_rate", label="Daily Rate", fieldtype="Currency", options="currency", non_negative=1,
				insert_after="nxg_rates_section", depends_on=MH_DEPENDS_ON,
				description="From the rate card or the item's Rental Item Profile. Change it for this quotation only."),
			dict(fieldname="nxg_rates_cb", fieldtype="Column Break", insert_after="nxg_daily_rate"),
			dict(fieldname="nxg_weekly_rate", label="Weekly Rate", fieldtype="Currency", options="currency", non_negative=1,
				insert_after="nxg_rates_cb", depends_on=MH_DEPENDS_ON),
			dict(fieldname="nxg_rates_cb2", fieldtype="Column Break", insert_after="nxg_weekly_rate"),
			dict(fieldname="nxg_monthly_rate", label="Monthly Rate", fieldtype="Currency", options="currency", non_negative=1,
				insert_after="nxg_rates_cb2", depends_on=MH_DEPENDS_ON),
			dict(fieldname="nxg_charges_section", label="Rental Charges", fieldtype="Section Break", insert_after="nxg_monthly_rate",
				depends_on=MH_DEPENDS_ON, collapsible=0),
			dict(fieldname="nxg_repair_charge", label="Standard Repair Charge per Unit", fieldtype="Currency", options="currency",
				insert_after="nxg_charges_section", non_negative=1, depends_on=MH_DEPENDS_ON,
				description="From the item's Rental Item Profile. Change it for this quotation only."),
			dict(fieldname="nxg_charges_cb", fieldtype="Column Break", insert_after="nxg_repair_charge"),
			dict(fieldname="nxg_lost_charge", label="Lost Charge per Unit", fieldtype="Currency", options="currency",
				insert_after="nxg_charges_cb", non_negative=1, depends_on=MH_DEPENDS_ON),
			dict(fieldname="nxg_charges_cb2", fieldtype="Column Break", insert_after="nxg_lost_charge"),
			dict(fieldname="nxg_beyond_repair_charge", label="Beyond Repair / Damage Charge per Unit", fieldtype="Currency", options="currency",
				insert_after="nxg_charges_cb2", non_negative=1, depends_on=MH_DEPENDS_ON),
			dict(fieldname="nxg_charges_set", label="Rental Charges Set", fieldtype="Check", hidden=1, read_only=1,
				insert_after="nxg_beyond_repair_charge"),
			# closes the section, so ERPNext's own row fields after it keep their place
			dict(fieldname="nxg_charges_end", fieldtype="Section Break", insert_after="nxg_charges_set"),
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
			# Job (JCR) billing rows: title / contract / excess blocks, one per JCR line and billing period.
			dict(fieldname="nxg_jcr", label="Job Completion Report", fieldtype="Link", options="Job Completion Report", hidden=1,
				read_only=1, no_copy=1, print_hide=1, insert_after="nxg_hire_days"),
			dict(fieldname="nxg_jcr_billing_schedule", label="JCR Billing Schedule", fieldtype="Link", options="JCR Billing Schedule",
				hidden=1, read_only=1, no_copy=1, print_hide=1, insert_after="nxg_jcr"),
			dict(fieldname="nxg_row_type", label="Job Row Type", fieldtype="Select", options="\nTitle\nContract\nExcess", hidden=1,
				read_only=1, no_copy=1, print_hide=1, insert_after="nxg_jcr_billing_schedule"),
			dict(fieldname="nxg_contract_from", label="Contract From", fieldtype="Date", read_only=1, no_copy=1, insert_after="nxg_row_type"),
			dict(fieldname="nxg_contract_to", label="Contract To", fieldtype="Date", read_only=1, no_copy=1, insert_after="nxg_contract_from"),
			dict(fieldname="nxg_contract_days", label="Contract Days", fieldtype="Int", read_only=1, no_copy=1, in_list_view=0,
				insert_after="nxg_contract_to"),
			dict(fieldname="nxg_contract_amount", label="Contract Amount", fieldtype="Currency", read_only=1, no_copy=1, in_list_view=0,
				options="currency", insert_after="nxg_contract_days"),
			dict(fieldname="nxg_excess_days", label="Excess Days", fieldtype="Int", read_only=1, no_copy=1, in_list_view=0,
				insert_after="nxg_contract_amount"),
			dict(fieldname="nxg_excess_period", label="Excess Period", fieldtype="Data", read_only=1, no_copy=1, insert_after="nxg_excess_days"),
			dict(fieldname="nxg_excess_charge", label="Excess Charge", fieldtype="Currency", read_only=1, no_copy=1, in_list_view=0,
				options="currency", insert_after="nxg_excess_period"),
			dict(fieldname="nxg_excess_amount", label="Excess Amount", fieldtype="Currency", read_only=1, no_copy=1, in_list_view=0,
				options="currency", insert_after="nxg_excess_charge"),
			dict(fieldname="nxg_locked_rate", label="Locked Rate", fieldtype="Currency", hidden=1, read_only=1, no_copy=1, print_hide=1,
				options="currency", insert_after="nxg_excess_amount"),
			dict(fieldname="nxg_locked_amount", label="Locked Amount", fieldtype="Currency", hidden=1, read_only=1, no_copy=1, print_hide=1,
				options="currency", insert_after="nxg_locked_rate"),
		],
		"Stock Entry": [
			dict(fieldname="nxg_rental_contract", label="Rental Contract", fieldtype="Link", options="Rental Contract",
				read_only=1, no_copy=1, insert_after="remarks", depends_on="nxg_rental_contract"),
			dict(fieldname="nxg_hire_voucher_type", label="Rental Document Type", fieldtype="Link", options="DocType",
				read_only=1, no_copy=1, insert_after="nxg_rental_contract", depends_on="nxg_hire_voucher_no"),
			dict(fieldname="nxg_hire_voucher_no", label="Rental Document", fieldtype="Dynamic Link",
				options="nxg_hire_voucher_type", read_only=1, no_copy=1, insert_after="nxg_hire_voucher_type",
				depends_on="nxg_hire_voucher_no"),
			# moving supplier-owned material between cross hire warehouses: whose material it is
			dict(fieldname="nxg_cross_hire_order", label="Cross Hire Order", fieldtype="Link", options="Cross Hire Order",
				insert_after="nxg_hire_voucher_no", no_copy=1, depends_on="eval:doc.purpose=='Material Transfer'",
				description="Required when moving cross-hired (supplier) material between cross hire warehouses."),
		],
	}


def after_install():
	after_migrate()
	try:
		from thinknxg_rental.thinknxg_rental.doctype.rental_website_settings.rental_website_settings import seed_defaults

		seed_defaults()
	except Exception:
		frappe.log_error(title="thinkNXG Rental: website defaults not created", message=frappe.get_traceback())
	company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
	if company:
		try:
			setup_company(company)
		except Exception:
			frappe.log_error(title="thinkNXG Rental: default setup failed", message=frappe.get_traceback())


# Lead layout: the order the sections appear in. Anything not listed keeps its place after these.
LEAD_LAYOUT = [
	"organization_section", "naming_series", "customer", "company_name", "column_break_31", "territory", "fax",
	"address_section", "address_html", "column_break_38", "city", "state", "country", "column_break2", "contact_html",
	"nxg_contact_sb", "salutation", "first_name", "middle_name", "last_name", "column_break_1", "lead_name", "job_title",
	"contact_info_tab", "email_id", "website", "column_break_20", "mobile_no", "whatsapp_no", "column_break_16", "phone", "phone_ext",
	"nxg_project_sb", "deal_type", "project_title", "project",
	"nxg_project_cb", "status", "utm_source", "nxg_project_contact_name", "nxg_project_contact_job_title", "nxg_project_contact_email",
	"nxg_tender_sb", "lead_owner", "nxg_tender_assignee", "nxg_tender_cb", "nxg_tender_final_submission_date", "nxg_tender_finalization_date",
	"nxg_owner_sb", "nxg_owner_salutation", "nxg_owner_first_name", "nxg_owner_last_name", "nxg_owner_job_title",
	"nxg_owner_cb", "nxg_owner_email", "nxg_owner_phone", "nxg_owner_ext", "nxg_owner_mobile",
	# hidden fields stay in the last section
	"gender", "type", "request_type", "nxg_owner_gender", "nxg_branches", "nxg_project_contact_gender",
	"nxg_required_from", "nxg_expected_return_date", "nxg_hire_period_days",
]
LEAD_OBSOLETE = ("nxg_project_contact_sb", "nxg_project_contact_cb", "nxg_hire_period_sb", "nxg_hire_period_cb")


def lead_order(current):
	"""New field order: LEAD_LAYOUT first (only fields that exist), then the rest in their present order."""
	wanted = [f for f in LEAD_LAYOUT if f in current]
	listed = set(wanted)
	return wanted + [f for f in current if f not in listed]


def arrange_lead_layout():
	import json
	for fieldname in LEAD_OBSOLETE:  # layout-only breaks of the earlier Lead layout
		name = frappe.db.get_value("Custom Field", {"dt": "Lead", "fieldname": fieldname})
		if name:
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
	frappe.clear_cache(doctype="Lead")
	current = [f.fieldname for f in frappe.get_meta("Lead").fields]
	make_property_setter("Lead", None, "field_order", json.dumps(lead_order(current)), "Data", for_doctype=True, validate_fields_for_doctype=False)
	frappe.clear_cache(doctype="Lead")


def ensure_quotation_extras():
	"""Quotation: Purchase Cost / Total Cost on Material Sale rows, contact details copied from the Lead,
	and Weight / Purchase Cost / Total Cost kept off the printed quotation."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
	ms = "eval:parent.deal_type=='Material Sale'"
	create_custom_fields({
		"Quotation Item": [
			dict(fieldname="nxg_purchase_cost", label="Purchase Cost", fieldtype="Currency", options="currency", insert_after="nxg_weight", depends_on=ms, no_copy=0, description="Defaults to the item's valuation rate. Not printed."),
			dict(fieldname="nxg_total_cost", label="Total Cost", fieldtype="Currency", options="currency", insert_after="nxg_purchase_cost", depends_on=ms, read_only=1, description="Qty x Purchase Cost. Not printed."),
		],
		"Quotation": [
			dict(fieldname="nxg_contact_salutation", label="Contact Salutation", fieldtype="Data", insert_after="contact_email", read_only=1),
			dict(fieldname="nxg_contact_first_name", label="Contact First Name", fieldtype="Data", insert_after="nxg_contact_salutation", read_only=1),
			dict(fieldname="nxg_contact_last_name", label="Contact Last Name", fieldtype="Data", insert_after="nxg_contact_first_name", read_only=1),
			dict(fieldname="nxg_contact_job_title", label="Contact Job Title", fieldtype="Data", insert_after="nxg_contact_last_name", read_only=1),
			dict(fieldname="nxg_contact_phone_ext", label="Contact Extension", fieldtype="Data", insert_after="nxg_contact_job_title", read_only=1),
			dict(fieldname="nxg_project_contact_name", label="Project Contact Name", fieldtype="Data", insert_after="nxg_contact_phone_ext", read_only=1),
			dict(fieldname="nxg_project_contact_job_title", label="Project Contact Job Title", fieldtype="Data", insert_after="nxg_project_contact_name", read_only=1),
			dict(fieldname="nxg_project_contact_email", label="Project Contact Email", fieldtype="Data", options="Email", insert_after="nxg_project_contact_job_title", read_only=1),
		],
	}, update=True)
	for fieldname in ("nxg_weight", "nxg_purchase_cost", "nxg_total_cost"):
		make_property_setter("Quotation Item", fieldname, "print_hide", "1", "Check", validate_fields_for_doctype=False)


def after_migrate():
	ensure_quotation_extras()
	create_custom_fields(get_custom_fields(), ignore_validate=True)
	create_custom_fields({
	    "Sales Order": [
	        dict(fieldname="deal_type", label="Deal Type", fieldtype="Select",
	             options="\nMaterial Hire\nMaterial Sale\nHire Order Contract",
	             insert_after="order_type", in_standard_filter=1),
	    ]
	}, ignore_validate=True)
	create_custom_fields({
	    "Sales Invoice": [
	        dict(fieldname="deal_type", label="Invoice Type", fieldtype="Select",
	             options="\nMaterial Hire\nMaterial Sale\nHire Order Contract",
	             insert_after="customer_name", in_standard_filter=1),
	    ]
	}, ignore_validate=True)
	make_property_setter("Quotation Item", "uom", "in_list_view", "1", "Check", validate_fields_for_doctype=False)
	make_property_setter("Quotation Item", "uom", "columns", "1", "Int", validate_fields_for_doctype=False)
	make_property_setter("Quotation Item", "item_code", "columns", "1", "Int", validate_fields_for_doctype=False)
	make_property_setter("Quotation Item", "qty", "columns", "1", "Int", validate_fields_for_doctype=False)
	make_property_setter("Quotation Item", "rate", "columns", "1", "Int", validate_fields_for_doctype=False)
	make_property_setter("Quotation Item", "amount", "columns", "1", "Int", validate_fields_for_doctype=False)
	make_property_setter("Sales Invoice Item", "description", "in_list_view", "1", "Check", validate_fields_for_doctype=False)
	make_property_setter("Sales Invoice Item", "description", "columns", "3", "Int", validate_fields_for_doctype=False)
	# Lead: Deal Type replaces Request Type; fields the client does not use are hidden (not removed)
	for fieldname in ("request_type", "qualified_by", "qualified_on", "qualification_status", "annual_revenue", "no_of_employees",
			"market_segment", "industry", "utm_content", "utm_medium", "utm_campaign", "blog_subscriber", "unsubscribed"):
		make_property_setter("Lead", fieldname, "hidden", "1", "Check", validate_fields_for_doctype=False)
	make_property_setter("Lead", "customer", "label", "Customer", "Data", validate_fields_for_doctype=False)
	# Lead layout: Gender and Lead Type are not used; Customer is always shown (not only for the Existing Customer source)
	for fieldname in ("gender", "type"):
		make_property_setter("Lead", fieldname, "hidden", "1", "Check", validate_fields_for_doctype=False)
	make_property_setter("Lead", "customer", "depends_on", "", "Data", validate_fields_for_doctype=False)
	make_property_setter("Lead", "organization_section", "label", "Organization Details", "Data", validate_fields_for_doctype=False)
	# Project link is hidden on the Lead and the Quotation (not removed): it is filled from the Project Title / Rental Site
	for doctype in ("Lead", "Quotation"):
		make_property_setter(doctype, "project", "hidden", "1", "Check", validate_fields_for_doctype=False)
	arrange_lead_layout()
	setup_uoms()
	ensure_settings_defaults()
	ensure_extra_warehouses()
	desk_menu.sync()
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


def ensure_extra_warehouses():
	"""Lost and Excess warehouses were added in an upgrade. Fill an empty setting with a warehouse of the
	settings company; a value that is already saved is never changed."""
	company = frappe.db.get_single_value("Rental Settings", "company")
	if not company:
		return  # no company chosen yet: the setup action creates the warehouses
	for field, label in (("lost_warehouse", "Rental Lost"), ("excess_warehouse", "Rental Excess")):
		if frappe.db.get_single_value("Rental Settings", field):
			continue
		try:
			frappe.db.set_single_value("Rental Settings", field, ensure_warehouse(label, company))
		except Exception:
			frappe.log_error(title="thinkNXG Rental: %s setup failed" % field, message=frappe.get_traceback())


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
		"lost_warehouse": ("Rental Lost", 0),
		"excess_warehouse": ("Rental Excess", 0),
		"customer_sites_warehouse": ("Customer Sites", 1),
	}
	for field, (label, is_group) in warehouses.items():
		current = settings.get(field)
		if not current or frappe.db.get_value("Warehouse", current, "company") != company:
			settings.set(field, ensure_warehouse(label, company, is_group=is_group))
	# rental warehouse tables: rows of another company go; an empty table takes the yard as its default
	for table in ("own_rental_warehouses", "cross_hire_warehouses"):
		settings.set(table, [r for r in settings.get(table) if frappe.db.get_value("Warehouse", r.warehouse, "company") == company])

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
