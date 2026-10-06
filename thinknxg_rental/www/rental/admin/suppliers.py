from frappe import _

from thinknxg_rental.portal.admin import build_admin_context, get_cross_hire


def get_context(context):
	build_admin_context(context, "suppliers", _("Cross Hire"))
	context.groups, context.totals = get_cross_hire()
