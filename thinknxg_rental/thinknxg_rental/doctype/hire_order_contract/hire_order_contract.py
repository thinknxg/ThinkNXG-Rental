import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.utils import cint, flt, getdate, nowdate

from thinknxg_rental.services import billing, ledger
from thinknxg_rental.services.utils import check_duplicate_items, get_rental_rate, get_settings


class HireOrderContract(Document):
    def validate(self):
        self.validate_header()
        self.load_job_type_defaults()
        self.validate_items()
        self.calculate_item_amounts()

    def validate_header(self):
        if getdate(self.end_date) < getdate(self.start_date):
            frappe.throw(_("Contract End Date cannot be before Contract Start Date"))
        site = frappe.db.get_value("Rental Site", self.rental_site, ["customer", "company", "disabled"], as_dict=True)
        if not site:
            frappe.throw(_("Rental Site {0} does not exist").format(self.rental_site))
        if site.customer != self.customer:
            frappe.throw(_("Rental Site {0} belongs to another customer").format(self.rental_site))
        if site.disabled:
            frappe.throw(_("Rental Site {0} is disabled").format(self.rental_site))
        if self.job_type:
            flags = frappe.db.get_value("Item", self.job_type, ["is_job_type_item", "is_stock_item", "disabled"], as_dict=True)
            if not flags or not flags.is_job_type_item:
                frappe.throw(_("{0} is not marked as a Job Type Item").format(self.job_type))
            if flags.disabled:
                frappe.throw(_("Job Type Item {0} is disabled").format(self.job_type))

    def load_job_type_defaults(self):
        """A Job Type Item is a reusable kit. Its Item child table supplies the
        rental component rows. Existing rows are retained so users can edit
        quantities/dimensions after the automatic expansion."""
        if not self.job_type or self.flags.in_import:
            return
        if self.items:
            # If the rows were generated from the same job type, keep edits.
            if all(frappe.db.get_value("Item", r.item_code, "is_rental_item") for r in self.items if r.item_code):
                return
        item = frappe.get_doc("Item", self.job_type)
        components = item.get("job_type_item_names") or []
        if not components:
            frappe.throw(_("Job Type Item {0} has no component items").format(self.job_type))
        self.set("items", [])
        for c in components:
            if not c.item_code:
                continue
            if not frappe.db.get_value("Item", c.item_code, "is_rental_item"):
                frappe.throw(_("Job Type component {0} must be marked as Is Rental Item").format(c.item_code))
            self.append("items", {
                "item_code": c.item_code,
                "item_name": frappe.db.get_value("Item", c.item_code, "item_name"),
                "uom": c.unit or frappe.db.get_value("Item", c.item_code, "stock_uom"),
                "qty": flt(c.quantity) or 1,
                "job_tower": item.item_name,
                "description": c.item_description,
                "rate_basis": self.billing_cycle if self.billing_cycle in ("Monthly", "Weekly", "Daily") else "Monthly",
            })

    def validate_items(self):
        check_duplicate_items(self.items)
        for row in self.items:
            if not row.item_code:
                frappe.throw(_("Row {0}: Item is required").format(row.idx))
            flags = frappe.db.get_value("Item", row.item_code, ["is_rental_item", "is_job_type_item"], as_dict=True)
            if not flags or not flags.is_rental_item:
                frappe.throw(_("Row {0}: {1} must be a Rental Item. Job Type Items are selected in the Job Type field and expand into rental components.").format(row.idx, row.item_code))
            if flt(row.qty) < 0:
                frappe.throw(_("Row {0}: Qty cannot be negative").format(row.idx))
            if flt(row.dispatched_qty) > flt(row.qty) + 1e-6:
                frappe.throw(_("Row {0}: Dispatched Qty cannot exceed Contracted Qty").format(row.idx))

    def calculate_item_amounts(self):
        total_qty = total_amount = 0
        for row in self.items:
            length, width, height = flt(row.length), flt(row.width), flt(row.height)
            if length and width and height:
                row.area = length * width * height
                row.qty = row.area
            else:
                row.area = 0
            duration = flt(row.rotation_qty) or flt(row.contract_days) or 1
            rate = flt(row.contract_rate) or flt(row.rate)
            if rate and not row.contract_rate:
                row.contract_rate = rate
            row.contract_amount = flt(row.qty) * rate * duration
            row.rent = row.contract_amount
            total_qty += flt(row.qty)
            total_amount += flt(row.contract_amount)
        self.total_contract_qty = total_qty
        self.total_contract_amount = total_amount

    def before_submit(self):
        if not self.items:
            frappe.throw(_("At least one rental item is required"))

    def on_submit(self):
        self.db_set("status", "Active")
        self.db_set("billing_start_date", None)
        self.db_set("last_billed_upto", None)
        self.db_set("next_billing_date", None)

    def on_update_after_submit(self):
        self.calculate_item_amounts()
        self.db_set("total_contract_qty", self.total_contract_qty, update_modified=False)
        self.db_set("total_contract_amount", self.total_contract_amount, update_modified=False)

    @frappe.whitelist()
    def extend_contract(self, new_end_date, remarks=None):
        new_end_date = getdate(new_end_date)
        if new_end_date <= getdate(self.end_date):
            frappe.throw(_("New End Date must be after the current End Date"))
        self.append("extensions", {"previous_end_date": self.end_date, "new_end_date": new_end_date, "remarks": remarks or ""})
        self.end_date = new_end_date
        self.save(ignore_permissions=True)
        return self.name

    @frappe.whitelist()
    def close_contract(self):
        if self.docstatus != 1:
            frappe.throw(_("Contract must be submitted"))
        if flt(self.total_at_site_qty) > 0:
            frappe.throw(_("Cannot close while material is still at site"))
        if self.billing_start_date and getdate(self.last_billed_upto or self.billing_start_date) < getdate(self.end_date):
            billing.generate_billing(self.name, self.end_date)
        self.db_set("status", "Completed")
        return self.name

    @frappe.whitelist()
    def reopen_contract(self):
        if self.status != "Completed":
            frappe.throw(_("Only a completed contract can be reopened"))
        self.db_set("status", "Active")
        ledger.update_contract_progress(self.name)


def _live_contract(source):
    if source.docstatus != 1 or source.status in ("Completed", "Cancelled"):
        frappe.throw(_("Contract {0} is not live").format(source.name))


@frappe.whitelist()
def load_job_type_items(source_name):
    item = frappe.get_doc("Item", source_name)
    if not item.get("is_job_type_item"):
        frappe.throw(_("{0} is not a Job Type Item").format(source_name))
    return [{
        "item_code": row.item_code,
        "item_name": frappe.db.get_value("Item", row.item_code, "item_name"),
        "uom": row.unit or frappe.db.get_value("Item", row.item_code, "stock_uom"),
        "qty": flt(row.quantity) or 1,
        "description": row.item_description,
        "job_tower": item.item_name,
    } for row in (item.get("job_type_item_names") or []) if row.item_code]


@frappe.whitelist()
def make_jcr(source_name):
    source = frappe.get_doc("Hire Order Contract", source_name)
    if source.docstatus != 1:
        frappe.throw(_("Hire Order Contract must be submitted"))
    target = frappe.new_doc("JCR")
    target.hire_contract = source.name
    target.client_name = source.customer
    target.project_name = source.project
    target.location = source.rental_site
    for row in source.items:
        target.append("items", {
            "job_no": row.job_no,
            "job_description": row.description or row.item_name,
            "qty": flt(row.qty) or 1,
            "sales_order_item": row.name,
            "contract_days": cint(row.contract_days or row.rotation_qty),
            "excess_charge": 0,
            "excess_period": "Days",
        })
    return target


@frappe.whitelist()
def make_reservation(source_name: str, target_doc=None):
    def post_process(source, target):
        _live_contract(source)
        target.reservation_date = nowdate()
        target.required_from = source.start_date
        target.required_to = source.end_date
        target.source_warehouse = get_settings().rental_yard_warehouse

    return get_mapped_doc(
        "Hire Order Contract", source_name,
        {
            "Hire Order Contract": {"doctype": "Rental Material Reservation", "field_map": {"name": "hire_contract"}},
            "Hire Contract Item": {"doctype": "Rental Material Reservation Item", "field_map": {"pending_qty": "required_qty"}, "condition": lambda d: flt(d.pending_qty) > 0},
        }, target_doc, post_process,
    )


@frappe.whitelist()
def make_delivery_order(source_name: str, target_doc=None):
    from thinknxg_rental.thinknxg_rental.doctype.hire_delivery_order.hire_delivery_order import get_dispatch_items
    source = frappe.get_doc("Hire Order Contract", source_name)
    _live_contract(source)
    target = frappe.new_doc("Hire Delivery Order")
    target.update({"company": source.company, "hire_contract": source.name, "posting_date": nowdate()})
    for row in get_dispatch_items(source.name): target.append("items", row)
    target.run_method("set_missing_values")
    return target


@frappe.whitelist()
def make_off_hire_note(source_name: str, target_doc=None):
    from thinknxg_rental.thinknxg_rental.doctype.hire_off_hire_note.hire_off_hire_note import get_items_at_site
    source = frappe.get_doc("Hire Order Contract", source_name); _live_contract(source)
    target = frappe.new_doc("Hire Off-Hire Note")
    target.update({"company": source.company,"hire_contract": source.name,"off_hire_date": nowdate(),"return_date": nowdate(),"grace_days": cint(source.grace_days)})
    for row in get_items_at_site(source.name): target.append("items", row)
    return target


@frappe.whitelist()
def make_cross_hire_order(source_name: str, target_doc=None):
    source = frappe.get_doc("Hire Order Contract", source_name); _live_contract(source)
    settings = get_settings(); target = frappe.new_doc("Cross Hire Order")
    target.update({"company": source.company,"hire_contract": source.name,"order_date": nowdate(),"hire_from": max(getdate(source.start_date), getdate(nowdate())),"expected_return_date": max(getdate(source.end_date), getdate(nowdate()))})
    yard = settings.rental_yard_warehouse
    from thinknxg_rental.services.utils import get_available_qty
    for d in source.items:
        pending = flt(d.pending_qty)
        if pending <= 0: continue
        available = max(get_available_qty(d.item_code, yard, source.name, source.hire_order), 0) if yard else 0
        shortfall = pending - available
        if shortfall > 0:
            target.append("items", {"item_code": d.item_code,"item_name": d.item_name,"uom": d.uom,"qty": shortfall,"rate_basis": d.rate_basis})
    return target
