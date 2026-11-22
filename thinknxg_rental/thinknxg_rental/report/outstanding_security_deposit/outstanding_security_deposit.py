from thinknxg_rental.services import deposit_reports


def execute(filters=None):
	return deposit_reports.execute(filters, "outstanding_deposit")
