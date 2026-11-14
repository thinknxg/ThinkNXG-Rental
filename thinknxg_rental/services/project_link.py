"""Project Title and the Project link across Lead -> Quotation -> Rental Site.

Before there is a Project master, the Lead and the Quotation carry the intended project name in
Project Title. When a Rental Site is made from the quotation, the Project is found or created from
that title and linked on the site, the quotation and the lead.

The one rule everywhere: a Project link is only ever filled when it is empty. A link that is already
set is never changed, whatever the Project Title says.
"""
import frappe
from frappe import _

LINK = "project"
TITLE = "project_title"


def _clean(title):
	return " ".join((title or "").split())


# ----------------------------------------------------------------------------- where a quotation came from
def lead_of_quotation(quotation):
	"""The Lead a quotation was made from: the Lead it is addressed to, the Lead of its Customer, or
	the Lead of its Prospect when the Prospect has exactly one (with several it cannot be told apart)."""
	party_type, party = quotation.get("quotation_to"), quotation.get("party_name")
	if not party:
		return None
	if party_type == "Lead":
		return party
	if party_type == "Customer":
		return frappe.db.get_value("Customer", party, "lead_name") or None
	if party_type == "Prospect":
		leads = frappe.get_all("Prospect Lead", filters={"parent": party, "parenttype": "Prospect"}, pluck="lead", limit=2)
		return leads[0] if len(leads) == 1 else None
	return None


# ----------------------------------------------------------------------------- find or create the Project
def find_project(title, company, customer=None):
	"""An existing Project named exactly like the title (spaces and letter case aside), of the same
	company, and either for this customer or for no customer. Project names are unique in ERPNext."""
	title = _clean(title)
	if not title:
		return None
	row = frappe.db.get_value("Project", {"project_name": title}, ["name", "company", "customer"], as_dict=True)
	if row and _suits(row, company, customer):
		return row.name
	return None


def _suits(row, company, customer):
	return (not company or row.company == company) and (not row.customer or not customer or row.customer == customer)


def find_or_create_project(title, company, customer=None):
	"""The Project for this title: an existing one that suits, else a new one. Returns None when there
	is no title, or the user may not create Projects and none exists.

	Concurrent saves cannot make two: project_name is unique in the database, so a second insert of the
	same name waits for the first and then fails, and the first one's Project is used."""
	title = _clean(title)
	if not title:
		return None
	existing = find_project(title, company, customer)
	if existing:
		return existing
	if not frappe.has_permission("Project", "create"):
		frappe.msgprint(_("Project {0} was not created because you are not allowed to create Projects. Link one on the Rental Site when it exists.").format(frappe.bold(title)),
			indicator="orange", alert=True)
		return None
	names = [title]
	taken = frappe.db.get_value("Project", {"project_name": title}, ["company", "customer"], as_dict=True)
	if taken and not _suits(taken, company, customer):
		# the name belongs to another company's or customer's project: keep this one apart
		customer_name = frappe.db.get_value("Customer", customer, "customer_name") if customer else None
		names = [f"{title} - {customer_name or customer or company}"]
		found = find_project(names[0], company, customer)
		if found:
			return found
	project = frappe.new_doc("Project")
	project.project_name = names[0]
	project.company = company
	if customer and project.meta.has_field("customer"):
		project.customer = customer
	frappe.db.savepoint("nxg_project")
	try:
		project.insert()
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		# made a moment ago by someone else: use theirs
		frappe.db.rollback(save_point="nxg_project")
		existing = find_project(names[0], company, customer)
		if existing:
			return existing
		raise
	return project.name


# ----------------------------------------------------------------------------- fill empty links only
def fill_if_empty(doctype, name, project, source=None):
	"""Set the Project on a Lead or Quotation only when it is empty and the user may change that
	document. Submitted quotations get it too (it is a reference, not a commercial term). Never
	replaces an existing link. Returns True when it was set."""
	if not (name and project) or not frappe.get_meta(doctype).has_field(LINK):
		return False
	if frappe.db.get_value(doctype, name, LINK):
		return False
	if not frappe.has_permission(doctype, "write", doc=name) and not frappe.has_permission(doctype, "submit", doc=name):
		return False
	frappe.db.set_value(doctype, name, LINK, project)
	if source:
		frappe.get_doc(doctype, name).add_comment("Info", _("Project {0} linked from {1} {2}").format(project, _(source.doctype), source.name))
	return True


def link_site_project(site):
	"""Rental Site (before save): resolve its Project from the quotation and lead, then fill every empty
	link (the site, the quotation, the lead). Existing links are kept as they are."""
	if not site.get("nxg_quotation"):
		return
	quotation = frappe.db.get_value("Quotation", site.nxg_quotation,
		["name", "quotation_to", "party_name", "company", LINK] + ([TITLE] if frappe.get_meta("Quotation").has_field(TITLE) else []), as_dict=True)
	if not quotation:
		return
	lead_name = lead_of_quotation(quotation)
	lead_fields = [f for f in (LINK, TITLE) if frappe.get_meta("Lead").has_field(f)]
	lead = frappe.db.get_value("Lead", lead_name, ["name"] + lead_fields, as_dict=True) if lead_name and lead_fields else None

	# the nearest existing link wins; nothing that is set is changed
	project = site.get("project") or quotation.get(LINK) or (lead or {}).get(LINK)
	if not project:
		title = quotation.get(TITLE) or (lead or {}).get(TITLE)
		project = find_or_create_project(title, site.company or quotation.company, site.get("customer"))
	if not project:
		return
	if not site.get("project"):
		site.project = project
	fill_if_empty("Quotation", quotation.name, project, site)
	if lead:
		fill_if_empty("Lead", lead.name, project, site)


def carry_to_quotation(lead, quotation):
	"""Lead -> Quotation: Project Title and Project, each only into an empty field."""
	for field in (TITLE, LINK):
		if quotation.meta.has_field(field) and lead.get(field) and not quotation.get(field):
			quotation.set(field, lead.get(field))
