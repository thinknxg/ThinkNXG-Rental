from thinknxg_rental.services.subcontract_reports import run


def execute(filters=None):
	return run("Subcontract Cost Analysis", filters)
