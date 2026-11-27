"""Cost and profitability of subcontracting on a Hire Order Contract.

    Net Profit = Customer Revenue - Subcontract Cost - Other Direct Costs

Customer Revenue is what the existing billing already recorded on the contract's Rental Contracts (total_billed_amount); nothing
here changes how the customer is billed, and a customer can be billed with no subcontractor invoice at all.
Subcontract Cost is only the net of submitted, non-cancelled subcontract Purchase Invoices (the Settlement's invoice), so cost is
counted once. Other Direct Costs are the cross hire supplier invoices of the same contract, the one other cost the app already tracks.
"""
import frappe
from frappe.utils import flt


def profitability(hire_order_contract):
	contracts = frappe.get_all("Rental Contract", filters={"docstatus": 1, "source_type": "Hire Order Contract", "source_document": hire_order_contract},
		fields=["name", "total_billed_amount"])
	revenue = sum(flt(c.total_billed_amount) for c in contracts)
	orders = frappe.get_all("Subcontract Work Order", filters={"hire_order_contract": hire_order_contract, "docstatus": 1}, pluck="name")
	sub = {"labour": 0, "equipment": 0, "invoiced": 0, "retention": 0, "recoveries": 0, "penalties": 0, "additional": 0}
	if orders:
		for s in frappe.get_all("Subcontract Settlement", filters={"docstatus": 1, "subcontract_work_order": ["in", orders]},
				fields=["name", "retention_amount", "penalties", "damage_recovery", "other_deductions", "certified_value"]):
			sub["invoiced"] += flt(s.certified_value)
			sub["retention"] += flt(s.retention_amount)
			sub["penalties"] += flt(s.penalties)
			sub["recoveries"] += flt(s.damage_recovery) + flt(s.other_deductions)
		for r in frappe.db.sql("""select wi.work_category, wi.is_additional, sum(wi.invoiced_qty * wi.rate) as amt from `tabSubcontract Work Item` wi
			where wi.parent in %s group by wi.work_category, wi.is_additional""", (orders,), as_dict=True):
			sub["labour" if r.work_category == "Labour" else "equipment"] += flt(r.amt)
			if r.is_additional:
				sub["additional"] += flt(r.amt)
	# recoveries and penalties reduce what the subcontractor costs; retention is only a delay in paying, not a saving
	subcontract_cost = sub["invoiced"] - sub["penalties"] - sub["recoveries"]
	other = 0
	if contracts:
		other = flt(frappe.db.sql("""select sum(pi.base_net_total) from `tabPurchase Invoice` pi join `tabCross Hire Order` o on o.name = pi.nxg_cross_hire_order
			where pi.docstatus = 1 and o.rental_contract in %s""", ([c.name for c in contracts],))[0][0])
	return {"customer_revenue": revenue, "labour_cost": sub["labour"], "equipment_cost": sub["equipment"], "additional_work_cost": sub["additional"],
		"penalties": sub["penalties"], "recoveries": sub["recoveries"], "retention_held": sub["retention"], "subcontract_cost": subcontract_cost,
		"other_direct_costs": other, "net_profit": revenue - subcontract_cost - other,
		"margin": ((revenue - subcontract_cost - other) / revenue * 100) if revenue else 0}
