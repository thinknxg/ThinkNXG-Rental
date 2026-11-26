from thinknxg_rental.services.subcontract_reports import run


def execute(filters=None):
	return run("Subcontractor Wise Work Orders", filters)
