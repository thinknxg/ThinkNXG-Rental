from frappe import _

from thinknxg_rental.portal.utils import build_context, get_overview


def get_context(context):
	rp = build_context(context, "overview", _("Rental Portal"))
	if rp.customers:
		context.o = get_overview(rp.customers)
