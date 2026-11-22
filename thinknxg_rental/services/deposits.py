"""Security deposits and advance payments of rental contracts, posted to the accounts.

Two funds, never mixed, each held in its own liability account of the company (Rental Company Profile):

* Security Deposit: refundable security for the material on hire. Collected, refunded, or applied against an
  approved charge (damage, missing material, unpaid rental) by a deduction. Never income.
* Advance: paid towards future rental. Collected, adjusted against the customer's rental or tax invoice, or
  refunded. Never income until it is adjusted against an invoice, which carries the revenue and its VAT.

Every movement is a Rental Contract Payment, posted on submit as one balanced Journal Entry (customer as the
party on the liability account, so the customer's ledger shows it):

    Deposit Collection   Dr Bank / Cash              Cr Customer Security Deposits
    Deposit Refund       Dr Customer Security Deps.  Cr Bank / Cash
    Deposit Deduction    Dr Customer Security Deps.  Cr Debtors (against the charge invoice)
    Advance Collection   Dr Bank / Cash              Cr Customer Advances (+ Cr Output VAT, if accounted)
    Advance Adjustment   Dr Customer Advances (+ Dr Output VAT)   Cr Debtors (against the invoice)
    Advance Refund       Dr Customer Advances (+ Dr Output VAT)   Cr Bank / Cash

Balances (collected, refunded, adjusted, available, statuses) are worked out from the posted transactions,
never typed in. A posted transaction is corrected by cancelling it (its Journal Entry is cancelled with it) or
by a new transaction; the Journal Entry itself cannot be cancelled on its own.
"""
import frappe
from frappe import _
from frappe.utils import flt, now_datetime, nowdate

from thinknxg_rental.services import vat

DOCTYPE = "Rental Contract Payment"
DEPOSIT, ADVANCE = "Deposit", "Advance"
D_COLLECT, D_REFUND, D_DEDUCT = "Deposit Collection", "Deposit Refund", "Deposit Deduction"
A_COLLECT, A_ADJUST, A_REFUND = "Advance Collection", "Advance Adjustment", "Advance Refund"
FUND = {D_COLLECT: DEPOSIT, D_REFUND: DEPOSIT, D_DEDUCT: DEPOSIT, A_COLLECT: ADVANCE, A_ADJUST: ADVANCE, A_REFUND: ADVANCE}
CASH = (D_COLLECT, D_REFUND, A_COLLECT, A_REFUND)
AGAINST_INVOICE = (D_DEDUCT, A_ADJUST)
NEEDS_APPROVAL = (D_REFUND, D_DEDUCT, A_REFUND)
APPROVERS = ("Accounts Manager", "Rental Manager", "System Manager")
ACCOUNT_FIELD = {DEPOSIT: "security_deposit_account", ADVANCE: "customer_advance_account"}
EPS = 1e-6


# ------------------------------------------------------------------ balances
def _rows(rental_contract=None, hire_order=None, pro_forma_invoice=None):
	"""Posted transactions of a contract (with those made on its hire order before it existed)."""
	cond, args = [], {}
	if rental_contract:
		args["rc"] = rental_contract
		ho = frappe.db.get_value("Rental Contract", rental_contract, "hire_order")
		if ho:
			args["ho"] = ho
			cond.append("(rental_contract = %(rc)s or (ifnull(rental_contract, '') = '' and hire_order = %(ho)s))")
		else:
			cond.append("rental_contract = %(rc)s")
	elif hire_order:
		args["ho"] = hire_order
		cond.append("hire_order = %(ho)s")
	elif pro_forma_invoice:
		args["pi"] = pro_forma_invoice
		cond.append("pro_forma_invoice = %(pi)s")
	else:
		return []
	return frappe.db.sql(
		f"""select name, transaction_type, amount, vat_amount from `tab{DOCTYPE}`
		where docstatus = 1 and {' and '.join(cond)}""", args, as_dict=True)


def summarize(rows, deposit_required=0, advance_required=0):
	t = {k: 0.0 for k in FUND}
	vat_in = 0.0
	for r in rows:
		t[r.transaction_type] += flt(r.amount)
		vat_in += flt(r.vat_amount) if r.transaction_type == A_COLLECT else -flt(r.vat_amount)
	s = frappe._dict(
		deposit_required=flt(deposit_required), deposit_collected=t[D_COLLECT], deposit_refunded=t[D_REFUND],
		deposit_adjusted=t[D_DEDUCT], advance_required=flt(advance_required), advance_received=t[A_COLLECT],
		advance_utilized=t[A_ADJUST], advance_refunded=t[A_REFUND], advance_vat_held=max(vat_in, 0),
	)
	s.deposit_balance = s.deposit_collected - s.deposit_refunded - s.deposit_adjusted
	s.deposit_outstanding = max(s.deposit_required - s.deposit_collected, 0)
	s.advance_available = s.advance_received - s.advance_utilized - s.advance_refunded
	s.advance_outstanding = max(s.advance_required - s.advance_received, 0)
	s.deposit_status = deposit_status(s)
	s.advance_status = advance_status(s)
	return s


def deposit_status(s):
	if s.deposit_collected <= EPS:
		return "Not Collected"
	if s.deposit_refunded + s.deposit_adjusted > EPS:
		return "Settled" if s.deposit_balance <= EPS else "Partially Refunded"
	if s.deposit_collected + EPS >= s.deposit_required:
		return "Fully Collected"
	return "Partially Collected"


def advance_status(s):
	if s.advance_received <= EPS:
		return "Not Received"
	if s.advance_refunded > EPS:
		return "Partially Refunded"
	if s.advance_utilized > EPS:
		return "Fully Utilized" if s.advance_available <= EPS else "Partially Utilized"
	if s.advance_received + EPS >= s.advance_required:
		return "Fully Received"
	return "Partially Received"


def balances(rental_contract=None, hire_order=None, pro_forma_invoice=None):
	if rental_contract:
		c = frappe.db.get_value("Rental Contract", rental_contract, ["security_deposit", "advance_amount"], as_dict=True)
		return summarize(_rows(rental_contract=rental_contract), c.security_deposit, c.advance_amount)
	if hire_order:
		return summarize(_rows(hire_order=hire_order), frappe.db.get_value("Hire Order", hire_order, "total_security_deposit"))
	pi = frappe.db.get_value("Rental Pro Forma Invoice", pro_forma_invoice, ["total_deposit", "deposit_vat", "total_including_vat"], as_dict=True)
	return summarize(_rows(pro_forma_invoice=pro_forma_invoice), flt(pi.total_deposit) + flt(pi.deposit_vat), pi.total_including_vat)


CONTRACT_FIELDS = ("deposit_collected", "deposit_outstanding", "deposit_refunded", "deposit_adjusted", "deposit_balance",
	"deposit_status", "advance_received", "advance_utilized", "advance_refunded", "advance_available", "advance_status")


def update_contract(rental_contract):
	if not rental_contract or not frappe.db.exists("Rental Contract", rental_contract):
		return None
	s = balances(rental_contract=rental_contract)
	frappe.db.set_value("Rental Contract", rental_contract, {k: s[k] for k in CONTRACT_FIELDS}, update_modified=False)
	return s


def link_hire_order_payments(contract):
	"""A contract made from a hire order takes over the deposits and advances collected on the order."""
	if not contract.hire_order:
		return
	frappe.db.sql(f"""update `tab{DOCTYPE}` set rental_contract = %s
		where hire_order = %s and ifnull(rental_contract, '') = ''""", (contract.name, contract.hire_order))
	update_contract(contract.name)


# ------------------------------------------------------------------ validation
def liability_account(profile, fund):
	account = profile.get(ACCOUNT_FIELD[fund])
	if not account:
		frappe.throw(_("Set the {0} on Rental Company Profile {1} (Set Up Accounts) first.").format(
			_("Customer Security Deposit Account") if fund == DEPOSIT else _("Customer Advance Account"), profile.name),
			title=_("Account Missing"))
	return account


def payment_account(mode_of_payment, company):
	return frappe.db.get_value("Mode of Payment Account", {"parent": mode_of_payment, "company": company}, "default_account")


def lock(doc):
	"""Serialise postings on the same contract (or order): a second request waits, then sees the first."""
	if doc.rental_contract:
		frappe.db.sql("select name from `tabRental Contract` where name = %s for update", doc.rental_contract)
	elif doc.hire_order:
		frappe.db.sql("select name from `tabHire Order` where name = %s for update", doc.hire_order)


def source_balances(doc):
	# money asked for by a pro forma invoice is limited by that pro forma invoice, even once its contract exists;
	# what is held (refunds, deductions, adjustments) is the contract's, wherever it was collected
	if doc.pro_forma_invoice and doc.transaction_type in (D_COLLECT, A_COLLECT):
		return balances(pro_forma_invoice=doc.pro_forma_invoice)
	if doc.rental_contract:
		return balances(rental_contract=doc.rental_contract)
	if doc.hire_order:
		return balances(hire_order=doc.hire_order)
	return balances(pro_forma_invoice=doc.pro_forma_invoice)


def validate(doc):
	if doc.transaction_type not in FUND:
		frappe.throw(_("Choose a transaction type"))
	_set_party(doc)
	profile = vat.get_profile(doc.company)
	doc.currency = profile.currency
	precision = vat.precision_of(doc.currency)
	doc.amount = flt(doc.amount, precision)
	if doc.amount <= 0:
		frappe.throw(_("Amount must be greater than zero"))
	doc.liability_account = liability_account(profile, FUND[doc.transaction_type])
	if doc.transaction_type in CASH:
		if not doc.mode_of_payment:
			frappe.throw(_("Mode of Payment is required"))
		doc.account = doc.account or payment_account(doc.mode_of_payment, doc.company)
		if not doc.account:
			frappe.throw(_("Set the default account of Mode of Payment {0} for company {1}, or choose the bank / cash account.").format(
				doc.mode_of_payment, doc.company))
		acc = frappe.db.get_value("Account", doc.account, ["company", "account_type", "account_currency", "is_group"], as_dict=True)
		if not acc or acc.company != doc.company or acc.is_group or acc.account_type not in ("Bank", "Cash"):
			frappe.throw(_("{0} is not a bank or cash account of {1}").format(doc.account, doc.company))
		vat.check_currency(acc.account_currency, doc.currency)
		if acc.account_type == "Bank" and not doc.reference_no:
			frappe.throw(_("Enter the transaction or cheque reference of this bank payment"))
		doc.sales_invoice = None
	else:
		doc.mode_of_payment = doc.account = None
		_validate_invoice(doc)
	if doc.transaction_type != D_DEDUCT:
		doc.deduction_reason = doc.damage_settlement = None
	s = source_balances(doc)
	doc.balance_before, limit, what = _limit(doc, s)
	if limit is not None and doc.amount > flt(limit, precision) + EPS:
		frappe.throw(_("{0} of {1} is more than the {2} of {3}").format(
			doc.transaction_type, frappe.format(doc.amount, {"fieldtype": "Currency", "options": doc.currency}), what,
			frappe.format(max(flt(limit), 0), {"fieldtype": "Currency", "options": doc.currency})), title=_("Amount Too High"))
	doc.balance_after = flt(doc.balance_before) + (doc.amount if doc.transaction_type in (D_COLLECT, A_COLLECT) else -doc.amount)
	if doc.transaction_type == D_COLLECT:
		doc.balance_before, doc.balance_after = s.deposit_balance, s.deposit_balance + doc.amount
	_set_vat(doc, profile, s, precision)
	doc.status = "Pending Approval" if needs_approval(doc) and doc.docstatus == 0 else ("Draft" if doc.docstatus == 0 else doc.status)


def _set_party(doc):
	src = None
	if doc.rental_contract:
		src = frappe.db.get_value("Rental Contract", doc.rental_contract, ["company", "customer", "docstatus", "hire_order"], as_dict=True)
		if src.docstatus != 1:
			frappe.throw(_("Rental Contract {0} is not submitted").format(doc.rental_contract))
		doc.hire_order = doc.hire_order or src.hire_order
	elif doc.hire_order:
		src = frappe.db.get_value("Hire Order", doc.hire_order, ["company", "customer", "docstatus"], as_dict=True)
		if src.docstatus == 2:
			frappe.throw(_("Hire Order {0} is cancelled").format(doc.hire_order))
		contract = frappe.db.get_value("Rental Contract", {"hire_order": doc.hire_order, "docstatus": 1}, "name")
		if contract:
			doc.rental_contract = contract
	elif doc.pro_forma_invoice:
		src = frappe.db.get_value("Rental Pro Forma Invoice", doc.pro_forma_invoice,
			["company", "customer", "docstatus", "hire_order", "rental_contract"], as_dict=True)
		if src.docstatus != 1:
			frappe.throw(_("Pro Forma Invoice {0} is not approved").format(doc.pro_forma_invoice))
		doc.hire_order, doc.rental_contract = src.hire_order, src.rental_contract
	else:
		frappe.throw(_("Choose the Rental Contract (or the Hire Order or Pro Forma Invoice before the contract exists)"))
	if not doc.pro_forma_invoice and doc.transaction_type in (D_COLLECT, A_COLLECT) and doc.is_new():
		# collected on the contract or hire order: it is the money its open pro forma invoice asked for
		doc.pro_forma_invoice = open_pro_forma(src.customer, doc.rental_contract, doc.hire_order)
	if doc.pro_forma_invoice:
		pi = frappe.db.get_value("Rental Pro Forma Invoice", doc.pro_forma_invoice, ["customer", "company", "rental_contract", "hire_order"], as_dict=True)
		if (pi.customer, pi.company) != (src.customer, src.company):
			frappe.throw(_("Pro Forma Invoice {0} is for another customer or company").format(doc.pro_forma_invoice))
		if doc.rental_contract and pi.rental_contract and pi.rental_contract != doc.rental_contract:
			frappe.throw(_("Pro Forma Invoice {0} belongs to contract {1}").format(doc.pro_forma_invoice, pi.rental_contract))
	if doc.customer and doc.customer != src.customer:
		frappe.throw(_("{0} belongs to customer {1}, not {2}").format(doc.rental_contract or doc.hire_order or doc.pro_forma_invoice,
			src.customer, doc.customer))
	doc.customer, doc.company = src.customer, src.company
	doc.customer_name = frappe.db.get_value("Customer", doc.customer, "customer_name")


OPEN_PRO_FORMA = ("Approved", "Sent to Customer", "Customer Accepted", "Advance Received")


def open_pro_forma(customer, rental_contract=None, hire_order=None, statuses=OPEN_PRO_FORMA, on_or_after=None):
	"""The one open pro forma invoice of a contract (or its hire order); None when there is none or several."""
	cond = []
	args = {"customer": customer, "statuses": tuple(statuses)}
	if rental_contract:
		cond.append("rental_contract = %(rc)s")
		args["rc"] = rental_contract
	if hire_order:
		cond.append("(hire_order = %(ho)s and ifnull(rental_contract, '') in ('', %(rc_or_blank)s))")
		args.update(ho=hire_order, rc_or_blank=rental_contract or "")
	if not cond:
		return None
	date = ""
	if on_or_after:
		date = " and posting_date <= %(date)s"
		args["date"] = on_or_after
	names = frappe.db.sql_list(f"""select name from `tabRental Pro Forma Invoice`
		where docstatus = 1 and customer = %(customer)s and status in %(statuses)s and ({' or '.join(cond)}){date}""", args)
	return names[0] if len(names) == 1 else None


def _validate_invoice(doc):
	if not doc.sales_invoice:
		frappe.throw(_("Choose the Sales Invoice to adjust against"))
	si = frappe.db.get_value("Sales Invoice", doc.sales_invoice,
		["docstatus", "customer", "company", "currency", "outstanding_amount", "is_return", "nxg_rental_contract", "debit_to"], as_dict=True)
	if not si or si.docstatus != 1:
		frappe.throw(_("Sales Invoice {0} is not submitted").format(doc.sales_invoice))
	if si.is_return:
		frappe.throw(_("{0} is a credit note").format(doc.sales_invoice))
	if si.customer != doc.customer or si.company != doc.company:
		frappe.throw(_("Sales Invoice {0} is for another customer or company").format(doc.sales_invoice), title=_("Unrelated Invoice"))
	vat.check_currency(si.currency, doc.currency)
	if si.nxg_rental_contract and doc.rental_contract and si.nxg_rental_contract != doc.rental_contract:
		frappe.throw(_("Sales Invoice {0} belongs to contract {1}").format(doc.sales_invoice, si.nxg_rental_contract), title=_("Unrelated Invoice"))
	doc.invoice_outstanding = flt(si.outstanding_amount)


def _limit(doc, s):
	"""(balance before, the most this transaction may be, what that limit is)"""
	t = doc.transaction_type
	if t == D_COLLECT:
		if s.deposit_required > EPS:
			return s.deposit_outstanding, s.deposit_outstanding, _("outstanding security deposit")
		return s.deposit_balance, None, ""
	if t == A_COLLECT:
		if s.advance_required > EPS:
			return s.advance_outstanding, s.advance_outstanding, _("outstanding advance")
		return s.advance_available, None, ""
	if t in (D_REFUND, D_DEDUCT):
		limit, what = s.deposit_balance, _("security deposit held")
	else:
		limit, what = s.advance_available, _("advance available")
	if t in AGAINST_INVOICE and doc.invoice_outstanding < limit:
		return (s.deposit_balance if t == D_DEDUCT else s.advance_available), doc.invoice_outstanding, _("invoice outstanding")
	return limit, limit, what


def _set_vat(doc, profile, s, precision):
	doc.vat_rate = doc.vat_amount = 0
	if FUND[doc.transaction_type] != ADVANCE or not profile.vat_on_advances:
		return
	if doc.transaction_type == A_COLLECT:
		scope, registered = _scope(doc, profile)
		treatment, rate, _remarks = vat.resolve(profile, vat.ADVANCE, scope, registered)
		if treatment == vat.STANDARD and flt(rate):
			doc.vat_rate = flt(rate)
			doc.vat_amount = flt(doc.amount * flt(rate) / (100.0 + flt(rate)), precision)
	elif s.advance_available > EPS and s.advance_vat_held > EPS:
		# the VAT still held on the remaining advance, in proportion
		doc.vat_amount = flt(s.advance_vat_held * doc.amount / s.advance_available, precision)
		doc.vat_rate = flt(doc.vat_amount * 100.0 / (doc.amount - doc.vat_amount), 2) if doc.amount > doc.vat_amount else 0


def _scope(doc, profile):
	country, vat_number = vat.customer_context(doc.customer)
	return vat.supply_scope(profile.country, None, country), bool(vat_number)


def needs_approval(doc):
	if doc.transaction_type not in NEEDS_APPROVAL:
		return False
	return bool(frappe.db.get_single_value("Rental Settings", "approve_deposit_refunds"))


def before_submit(doc):
	lock(doc)
	validate(doc)  # again, under the lock: the balance may have moved since the form was saved
	if needs_approval(doc):
		if not set(frappe.get_roles()) & set(APPROVERS):
			frappe.throw(_("{0} needs approval: an Accounts Manager or Rental Manager posts it").format(doc.transaction_type),
				frappe.PermissionError, title=_("Approval Required"))
	if needs_approval(doc) or doc.transaction_type in AGAINST_INVOICE:
		doc.approved_by, doc.approved_on = frappe.session.user, now_datetime()


# ------------------------------------------------------------------ posting
def post(doc):
	"""The Journal Entry of a transaction (submitted with it)."""
	profile = vat.get_profile(doc.company)
	party = dict(party_type="Customer", party=doc.customer)
	contract = frappe.db.get_value("Rental Contract", doc.rental_contract, ["project", "cost_center"], as_dict=True) if doc.rental_contract else frappe._dict()
	cost_center = contract.cost_center or frappe.get_cached_value("Company", doc.company, "cost_center")
	common = dict(cost_center=cost_center, project=contract.project)
	amount, tax = flt(doc.amount), flt(doc.vat_amount)
	L, t = doc.liability_account, doc.transaction_type
	rows = []
	if t == D_COLLECT:
		rows = [dict(account=doc.account, debit_in_account_currency=amount),
			dict(account=L, credit_in_account_currency=amount, is_advance="Yes", **party)]
	elif t == A_COLLECT:
		rows = [dict(account=doc.account, debit_in_account_currency=amount),
			dict(account=L, credit_in_account_currency=amount - tax, is_advance="Yes", **party)]
		if tax:
			rows.append(dict(account=_vat_account(profile), credit_in_account_currency=tax))
	else:
		if t in (D_REFUND, A_REFUND):
			other = dict(account=doc.account, credit_in_account_currency=amount)
		else:
			debit_to = frappe.db.get_value("Sales Invoice", doc.sales_invoice, "debit_to")
			other = dict(account=debit_to, credit_in_account_currency=amount, reference_type="Sales Invoice",
				reference_name=doc.sales_invoice, **party)
		rows = [dict(account=L, debit_in_account_currency=amount - tax, **party), other]
		if tax:
			rows.insert(1, dict(account=_vat_account(profile), debit_in_account_currency=tax))
	cash_type = frappe.db.get_value("Account", doc.account, "account_type") if doc.account else None
	je = frappe.new_doc("Journal Entry")
	je.update({
		"company": doc.company,
		"posting_date": doc.posting_date,
		"voucher_type": "Bank Entry" if cash_type == "Bank" else ("Cash Entry" if cash_type == "Cash" else "Journal Entry"),
		"cheque_no": doc.reference_no if cash_type == "Bank" else None,
		"cheque_date": (doc.reference_date or doc.posting_date) if cash_type == "Bank" else None,
		"mode_of_payment": doc.mode_of_payment,
		"multi_currency": 0,
		"title": f"{t} {doc.name}",
		"user_remark": _("{0} {1} - Contract {2}, customer {3}. {4}").format(t, doc.name, doc.rental_contract or doc.hire_order or doc.pro_forma_invoice,
			doc.customer_name, doc.remarks or ""),
		"nxg_rental_contract_payment": doc.name,
	})
	for r in rows:
		je.append("accounts", dict(r, **common))
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	doc.db_set("journal_entry", je.name)
	return je.name


def _vat_account(profile):
	if not profile.output_vat_account:
		frappe.throw(_("Set the Output VAT Account on Rental Company Profile {0}").format(profile.name))
	return profile.output_vat_account


def on_submit(doc):
	post(doc)
	doc.db_set("status", "Posted")
	after_change(doc)


def before_cancel(doc):
	lock(doc)
	if doc.transaction_type in (D_COLLECT, A_COLLECT):
		s = source_balances(doc)
		left = (s.deposit_balance if doc.transaction_type == D_COLLECT else s.advance_available) - flt(doc.amount)
		if left < -EPS:
			frappe.throw(_("Cannot cancel: {0} of this collection has already been refunded, deducted or adjusted. Cancel those first.").format(
				frappe.format(-left, {"fieldtype": "Currency", "options": doc.currency})))


def on_cancel(doc):
	if doc.journal_entry and frappe.db.get_value("Journal Entry", doc.journal_entry, "docstatus") == 1:
		je = frappe.get_doc("Journal Entry", doc.journal_entry)
		je.flags.ignore_permissions = True
		je.flags.from_rental_contract_payment = True
		je.cancel()
	doc.db_set("status", "Cancelled")
	after_change(doc)


def after_change(doc):
	update_contract(doc.rental_contract)
	if doc.pro_forma_invoice:
		from thinknxg_rental.thinknxg_rental.doctype.rental_pro_forma_invoice.rental_pro_forma_invoice import refresh_payments

		refresh_payments(doc.pro_forma_invoice)


# ------------------------------------------------------------------ guards on the accounting documents
def journal_entry_before_cancel(doc, method=None):
	name = doc.get("nxg_rental_contract_payment")
	if name and not doc.flags.from_rental_contract_payment and frappe.db.get_value(DOCTYPE, name, "docstatus") == 1:
		frappe.throw(_("This Journal Entry posts Rental Contract Payment {0}. Cancel the Rental Contract Payment instead.").format(name))


def sales_invoice_before_cancel(doc, method=None):
	names = frappe.get_all(DOCTYPE, filters={"sales_invoice": doc.name, "docstatus": 1}, pluck="name")
	if names:
		frappe.throw(_("Advance adjustments or deposit deductions are posted against this invoice ({0}). Cancel them first.").format(
			", ".join(names)), title=_("Adjustments Exist"))


# ------------------------------------------------------------------ actions
def make(values, submit=True):
	"""Create (and post) a transaction once per request_id: a retried request returns the first one."""
	values = frappe._dict(values)
	if values.get("request_id"):
		existing = frappe.db.get_value(DOCTYPE, {"request_id": values.request_id}, "name")
		if existing:
			return frappe.get_doc(DOCTYPE, existing)
	doc = frappe.get_doc(dict(values, doctype=DOCTYPE))
	doc.insert()
	if submit and not (needs_approval(doc) and not set(frappe.get_roles()) & set(APPROVERS)):
		doc.submit()
	return doc


def adjustable_advance(sales_invoice):
	"""What the advance panel of a rental invoice shows."""
	si = frappe.db.get_value("Sales Invoice", sales_invoice, ["name", "customer", "company", "grand_total", "rounded_total",
		"outstanding_amount", "nxg_rental_contract", "docstatus", "currency", "is_return"], as_dict=True)
	if not si or not si.nxg_rental_contract or si.is_return:
		return None
	s = balances(rental_contract=si.nxg_rental_contract)
	adjusted = frappe.db.sql(f"""select ifnull(sum(amount), 0) from `tab{DOCTYPE}`
		where docstatus = 1 and transaction_type = %s and sales_invoice = %s""", (A_ADJUST, sales_invoice))[0][0]
	can = max(min(s.advance_available, flt(si.outstanding_amount)), 0) if si.docstatus == 1 else 0
	return frappe._dict(
		rental_contract=si.nxg_rental_contract, currency=si.currency, invoice_amount=flt(si.rounded_total or si.grand_total),
		outstanding=flt(si.outstanding_amount), advance_available=s.advance_available, already_adjusted=flt(adjusted),
		suggested=can, remaining=flt(si.outstanding_amount) - can, docstatus=si.docstatus,
	)


def auto_adjust(sales_invoice):
	"""Rental Settings > Adjust Advances on Rental Invoices: the contract's advance goes against a new invoice."""
	if not frappe.db.get_single_value("Rental Settings", "auto_adjust_advance"):
		return None
	info = adjustable_advance(sales_invoice)
	if not info or info.suggested <= EPS:
		return None
	return make({"transaction_type": A_ADJUST, "rental_contract": info.rental_contract, "sales_invoice": sales_invoice,
		"amount": info.suggested, "posting_date": nowdate(), "remarks": _("Adjusted automatically on submit of {0}").format(sales_invoice)})


def history(rental_contract, fund=None):
	filters = {"rental_contract": rental_contract, "docstatus": ["!=", 2]}
	rows = frappe.get_all(DOCTYPE, filters=filters, order_by="posting_date, creation", fields=["name", "transaction_type",
		"posting_date", "amount", "currency", "mode_of_payment", "reference_no", "sales_invoice", "journal_entry", "status",
		"vat_amount", "remarks", "docstatus"])
	return [r for r in rows if not fund or FUND[r.transaction_type] == fund]

