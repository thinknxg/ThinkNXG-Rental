from frappe import _

from thinknxg_rental.portal.utils import build_context, get_contracts


def get_context(context):
	rp = build_context(context, "contracts", _("Rental Contracts"))
	if rp.customers:
		context.contracts = get_contracts(rp.customers)
