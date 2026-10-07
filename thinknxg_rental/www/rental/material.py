from frappe import _
from frappe.utils import flt

from thinknxg_rental.portal.utils import build_context, get_material


def get_context(context):
	rp = build_context(context, "material", _("Material at Site"))
	if rp.customers:
		rows = get_material(rp.customers)
		groups = {}
		for r in rows:
			groups.setdefault((r.rental_site, r.rental_contract), []).append(r)
		context.groups = [
			{"site": site, "contract": contract, "rows": items, "total": sum(flt(i.qty) for i in items)}
			for (site, contract), items in groups.items()
		]
		context.total = sum(flt(r.qty) for r in rows)
