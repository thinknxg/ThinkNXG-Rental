"""Contract closure: every return inspected, every lost and damaged unit settled.

A contract (and its project) may only be closed once, for every submitted off-hire note on it:

* the return inspection is done (inspection_status is not Pending);
* every lost unit (on the off-hire note) and every repairable / beyond-repair unit (on its return
  inspection) is covered by a submitted Rental Damage Settlement of that note;
* each of those settlements is completed: invoiced, or with nothing to invoice (a zero total, e.g. the
  liability was waived);
* no settlement or inspection of the contract is left as a draft.

Enforced on the server in Rental Contract.close_contract (desk, Command Center and API all call it) and
on Project completion. Unlike the material reconciliation (services/excess.py), a Rental Manager's
reconciliation exception does not bypass it: settlement is what stops the open charges.

Rental itself is never billed for lost or damaged material past its off-hire: billing follows the
ownership ledger, and lost units leave it at the off-hire note's last billable day, whether the loss is
recorded on the off-hire note or later on the Damage Settlement (see rental_damage_settlement.py).
"""
import frappe
from frappe import _
from frappe.utils import escape_html, flt

EPS = 1e-6
SETTLEMENT = "Rental Damage Settlement"
INSPECTION = "Rental Return Inspection"


def _q(value):
	value = flt(value, 3)
	return str(int(value)) if value == int(value) else str(value)


def required(note):
	"""{(item_code, kind): qty} that a damage settlement of the off-hire note must cover, where kind is
	"Lost" (from the note) or "Damaged" (repairable + beyond repair, from its submitted inspection)."""
	need = {}
	for r in frappe.get_all("Hire Off-Hire Item", filters={"parent": note, "parenttype": "Hire Off-Hire Note", "lost_qty": [">", 0]},
			fields=["item_code", "lost_qty"]):
		need[(r.item_code, "Lost")] = need.get((r.item_code, "Lost"), 0) + flt(r.lost_qty)
	inspection = frappe.db.get_value(INSPECTION, {"hire_off_hire_note": note, "docstatus": 1}, "name")
	if inspection:
		for r in frappe.get_all("Rental Return Inspection Item", filters={"parent": inspection, "parenttype": INSPECTION},
				fields=["item_code", "repairable_qty", "damaged_qty"]):
			qty = flt(r.repairable_qty) + flt(r.damaged_qty)
			if qty > EPS:
				need[(r.item_code, "Damaged")] = need.get((r.item_code, "Damaged"), 0) + qty
	return need


def settled(note):
	"""({(item_code, kind): qty} on submitted settlements of the note, [those settlements])."""
	names = frappe.get_all(SETTLEMENT, filters={"hire_off_hire_note": note, "docstatus": 1},
		fields=["name", "status", "grand_total", "sales_invoice"], order_by="creation")
	got = {}
	if names:
		for r in frappe.get_all("Rental Damage Settlement Item", filters={"parent": ["in", [n.name for n in names]], "parenttype": SETTLEMENT},
				fields=["item_code", "classification", "qty"]):
			kind = "Lost" if r.classification == "Lost" else "Damaged"
			got[(r.item_code, kind)] = got.get((r.item_code, kind), 0) + flt(r.qty)
	return got, names


def completed(settlement):
	"""Invoiced, or nothing to invoice."""
	return settlement.status == "Invoiced" or flt(settlement.grand_total) <= EPS


def pending(rental_contract):
	"""What stops the contract from closing, as readable lines (empty: it may close)."""
	issues = []
	notes = frappe.get_all("Hire Off-Hire Note", filters={"rental_contract": rental_contract, "docstatus": 1},
		fields=["name", "inspection_status"], order_by="return_date, creation")
	for note in notes:
		if note.inspection_status == "Pending":
			draft = frappe.db.get_value(INSPECTION, {"hire_off_hire_note": note.name, "docstatus": 0}, "name")
			issues.append(_("Inspection pending on Off-Hire Note {0}: {1}").format(
				note.name, _("submit Return Inspection {0}").format(draft) if draft else _("create and submit its Return Inspection")))
			continue
		need = required(note.name)
		if not need:
			continue
		got, settlements = settled(note.name)
		short = [(item, kind, qty - flt(got.get((item, kind)))) for (item, kind), qty in sorted(need.items())
			if qty - flt(got.get((item, kind))) > EPS]
		if short:
			what = ", ".join(_("{0} {1} {2}").format(_q(left), item, _("lost") if kind == "Lost" else _("damaged")) for item, kind, left in short)
			issues.append(_("Damage settlement pending on Off-Hire Note {0}: {1} not settled").format(note.name, what))
		for s in settlements:
			if not completed(s):
				issues.append(_("Damage Settlement {0} is not invoiced yet{1}").format(
					s.name, _(" (Sales Invoice {0} is not submitted)").format(s.sales_invoice) if s.sales_invoice else ""))
	for name in frappe.get_all(SETTLEMENT, filters={"rental_contract": rental_contract, "docstatus": 0}, pluck="name"):
		issues.append(_("Damage Settlement {0} is still a draft: submit or delete it").format(name))
	return issues


def check_can_close(rental_contract):
	issues = pending(rental_contract)
	if issues:
		frappe.throw(
			_("Contract {0} cannot be closed until its returns are inspected and every lost and damaged item is settled:").format(rental_contract)
			+ "<ul>" + "".join(f"<li>{escape_html(i)}</li>" for i in issues) + "</ul>",
			title=_("Inspection and Damage Settlement Pending"),
		)
