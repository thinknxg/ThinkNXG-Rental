"""Per project, contract and item: delivered = returned + lost + adjusted + outstanding, next to the
excess received from the same contract and what became of it. All from submitted transactions."""
import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	conditions, values = ["l.position_type = 'At Site'"], {}
	for field in ("company", "customer", "project", "rental_contract", "item_code"):
		if filters.get(field):
			conditions.append(f"l.{field} = %({field})s")
			values[field] = filters[field]
	moved = frappe.db.sql(
		f"""select ifnull(c.project, '') as project, l.rental_contract, max(c.customer) as customer, max(c.customer_name) as customer_name,
			l.item_code,
			sum(case when l.movement_type = 'Dispatch' then l.qty else 0 end) as delivered_qty,
			-sum(case when l.movement_type = 'Return' then l.qty else 0 end) as returned_qty,
			-sum(case when l.movement_type = 'Loss' then l.qty else 0 end) as lost_qty,
			-sum(case when l.movement_type = 'Adjustment' then l.qty else 0 end) as adjusted_qty,
			sum(l.qty) as outstanding_qty
		from `tabRental Ownership Ledger` l inner join `tabRental Contract` c on c.name = l.rental_contract
		where {" and ".join(conditions)}
		group by ifnull(c.project, ''), l.rental_contract, l.item_code""",
		values, as_dict=True,
	)
	rconds, rvalues = ["status != 'Cancelled'"], {}
	for field in ("company", "customer", "project", "rental_contract", "item_code"):
		if filters.get(field):
			rconds.append(f"{field} = %({field})s")
			rvalues[field] = filters[field]
	excess = {}
	for r in frappe.db.sql(
		f"""select ifnull(project, '') as project, rental_contract, max(customer) as customer, max(customer_name) as customer_name,
			item_code, sum(excess_qty) as excess_qty, sum(returned_to_customer_qty) as excess_returned_qty,
			sum(adjusted_qty) as excess_adjusted_qty, sum(abandoned_qty) as excess_abandoned_qty, sum(available_qty) as excess_available_qty
		from `tabExcess Material Register` where {" and ".join(rconds)}
		group by ifnull(project, ''), rental_contract, item_code""",
		rvalues, as_dict=True,
	):
		excess[(r.project, r.rental_contract, r.item_code)] = r

	rows, seen = [], set()
	for m in moved:
		key = (m.project, m.rental_contract, m.item_code)
		seen.add(key)
		rows.append(_row(m, excess.get(key)))
	for key, e in excess.items():
		if key not in seen:  # excess of an item never delivered on the contract
			rows.append(_row(frappe._dict(project=e.project, rental_contract=e.rental_contract, customer=e.customer,
				customer_name=e.customer_name, item_code=e.item_code), e))
	names = frappe.get_all("Item", filters={"name": ["in", list({r.item_code for r in rows}) or [""]]}, fields=["name", "item_name"])
	item_names = {i.name: i.item_name for i in names}
	for r in rows:
		r.item_name = item_names.get(r.item_code)
		r.state = _("Reconciled") if flt(r.outstanding_qty) <= 1e-6 and flt(r.excess_available_qty) <= 1e-6 else _("Not Reconciled")
	if filters.get("unreconciled_only"):
		rows = [r for r in rows if r.state != _("Reconciled")]
	rows.sort(key=lambda r: (r.project or "~", r.rental_contract, r.item_code))
	columns = [
		{"label": _("Project"), "fieldname": "project", "fieldtype": "Link", "options": "Project", "width": 130},
		{"label": _("Contract"), "fieldname": "rental_contract", "fieldtype": "Link", "options": "Rental Contract", "width": 140},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 120},
		{"label": _("Customer Name"), "fieldname": "customer_name", "width": 150},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 130},
		{"label": _("Item Name"), "fieldname": "item_name", "width": 160},
		{"label": _("Delivered"), "fieldname": "delivered_qty", "fieldtype": "Float", "width": 90},
		{"label": _("Returned"), "fieldname": "returned_qty", "fieldtype": "Float", "width": 90},
		{"label": _("Lost"), "fieldname": "lost_qty", "fieldtype": "Float", "width": 80},
		{"label": _("Adjusted"), "fieldname": "adjusted_qty", "fieldtype": "Float", "width": 90},
		{"label": _("Outstanding"), "fieldname": "outstanding_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Excess Received"), "fieldname": "excess_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Excess Returned"), "fieldname": "excess_returned_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Excess Adjusted"), "fieldname": "excess_adjusted_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Excess Abandoned"), "fieldname": "excess_abandoned_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Excess Available"), "fieldname": "excess_available_qty", "fieldtype": "Float", "width": 110},
		{"label": _("State"), "fieldname": "state", "width": 120},
	]
	return columns, rows


def _row(m, e):
	e = e or {}
	return frappe._dict(
		project=m.project or None, rental_contract=m.rental_contract, customer=m.customer, customer_name=m.customer_name,
		item_code=m.item_code, delivered_qty=flt(m.get("delivered_qty")), returned_qty=flt(m.get("returned_qty")),
		lost_qty=flt(m.get("lost_qty")), adjusted_qty=flt(m.get("adjusted_qty")), outstanding_qty=flt(m.get("outstanding_qty")),
		excess_qty=flt(e.get("excess_qty")), excess_returned_qty=flt(e.get("excess_returned_qty")),
		excess_adjusted_qty=flt(e.get("excess_adjusted_qty")), excess_abandoned_qty=flt(e.get("excess_abandoned_qty")), excess_available_qty=flt(e.get("excess_available_qty")),
	)
