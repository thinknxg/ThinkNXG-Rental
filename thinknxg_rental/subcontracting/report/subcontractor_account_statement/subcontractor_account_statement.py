from thinknxg_rental.services.subcontract_reports import run


def execute(filters=None):
	return run("Subcontractor Account Statement", filters)
