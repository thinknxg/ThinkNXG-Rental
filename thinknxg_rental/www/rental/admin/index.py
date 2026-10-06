from frappe import _

from thinknxg_rental.portal.admin import build_admin_context, get_board


def get_context(context):
	build_admin_context(context, "board", _("Rental Admin"))
	context.b = get_board()
