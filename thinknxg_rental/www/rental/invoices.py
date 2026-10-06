from frappe import _
from frappe.utils import flt

from thinknxg_rental.portal.utils import build_context, get_invoices


def get_context(context):
	rp = build_context(context, "invoices", _("Rental Invoices"))
	if rp.customers:
		context.invoices = get_invoices(rp.customers, limit=200)
		unpaid = [i for i in context.invoices if i.unpaid and not i.is_return]
		context.unpaid_total = sum(flt(i.outstanding_amount) for i in unpaid)
		context.currency = context.invoices[0].currency if context.invoices else None
