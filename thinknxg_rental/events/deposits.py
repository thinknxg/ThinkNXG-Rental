"""Deposits, advances and pro forma invoices around the contract and the Sales Invoice."""
from thinknxg_rental.services import deposits
from thinknxg_rental.thinknxg_rental.doctype.rental_pro_forma_invoice import rental_pro_forma_invoice as pro_forma


def contract_submitted(doc, method=None):
	deposits.link_hire_order_payments(doc)
	pro_forma.link_contract(doc)


def sales_invoice_submitted(doc, method=None):
	pro_forma.sales_invoice_submitted(doc)
	if doc.get("nxg_rental_contract") and not doc.is_return:
		deposits.auto_adjust(doc.name)


def sales_invoice_removed(doc, method=None):
	pro_forma.sales_invoice_removed(doc)
