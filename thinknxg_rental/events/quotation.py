"""Hire quotations: Amount = Qty x Unit Price x Duration.

For the deal types in HIRE_DEAL_TYPES a row can carry Length, Breadth, Height and Duration:

* Qty is Length x Breadth x Height once all three are filled; otherwise the typed Qty is kept.
* Amount is Qty x Unit Price x Duration. A blank Duration counts as 1.

The same rule runs in the form (public/js/quotation_deal.js) and here on save. ERPNext's own totals
calculation is reused, so taxes, discounts and rounding keep working: while it runs, Qty is
temporarily multiplied by Duration, then the typed Qty is put back. The unit price is never touched,
which keeps price list, margin and discount fields intact. Other deal types use the standard Qty x Rate.
"""
from frappe.utils import cint, flt

# Keep in step with HIRE_DEPENDS_ON in services/setup.py and quotation_deal.js
HIRE_DEAL_TYPES = ("Material Hire", "Hire Order Contract")


def set_dimension_qty(row):
	"""Qty = Length x Breadth x Height when all three are given; return True if Qty was set."""
	length, breadth, height = flt(row.get("nxg_length")), flt(row.get("nxg_breadth")), flt(row.get("nxg_height"))
	if length and breadth and height:
		row.qty = flt(length * breadth * height, row.precision("qty"))
		return True
	return False


def duration_of(row):
	return cint(row.get("nxg_duration")) or 1


def validate(doc, method=None):
	if doc.get("deal_type") not in HIRE_DEAL_TYPES or not doc.get("items"):
		return

	rows = doc.items
	for row in rows:
		set_dimension_qty(row)

	typed_qty = [row.qty for row in rows]
	try:
		for row in rows:
			row.qty = flt(row.qty) * duration_of(row)
		doc.calculate_taxes_and_totals()
	finally:
		for row, qty in zip(rows, typed_qty):
			row.qty = qty

	# the totals pass counted Qty x Duration; the quantity column and its total stay as typed
	doc.total_qty = sum(flt(row.qty) for row in rows)
