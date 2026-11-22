"""Security deposit and advance reports, all worked out from posted Rental Contract Payments.

Filters shared by every report: company, country (the company's VAT country, from its Rental Company Profile),
customer, rental contract, from / to date and status (the deposit or advance status for the summaries, the
transaction type for the lists). Summaries are as at the To Date.
"""
import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from thinknxg_rental.services import deposits as D

DEPOSIT_TYPES = (D.D_COLLECT, D.D_REFUND, D.D_DEDUCT)
ADVANCE_TYPES = (D.A_COLLECT, D.A_ADJUST, D.A_REFUND)


def _companies(filters):
	if filters.get("company"):
		return [filters.company]
	if filters.get("country"):
		return frappe.get_all("Rental Company Profile", filters={"country": filters.country}, pluck="company") or ["__none__"]
	return None


def _transactions(filters, types, dated=True):
	cond, args = ["p.docstatus = 1", "p.transaction_type in %(types)s"], {"types": tuple(types)}
	companies = _companies(filters)
	if companies:
		cond.append("p.company in %(companies)s")
		args["companies"] = tuple(companies)
	for key in ("customer", "rental_contract"):
		if filters.get(key):
			cond.append(f"p.{key} = %({key})s")
			args[key] = filters[key]
	if dated and filters.get("from_date"):
		cond.append("p.posting_date >= %(from_date)s")
		args["from_date"] = filters.from_date
	if filters.get("to_date"):
		cond.append("p.posting_date <= %(to_date)s")
		args["to_date"] = filters.to_date
	return frappe.db.sql(f"""select p.name, p.transaction_type, p.posting_date, p.company, p.currency, p.customer, p.customer_name,
		p.rental_contract, p.hire_order, p.pro_forma_invoice, p.amount, p.vat_amount, p.mode_of_payment, p.account,
		p.reference_no, p.sales_invoice, p.deduction_reason, p.journal_entry, p.approved_by, p.owner, p.remarks
		from `tabRental Contract Payment` p where {' and '.join(cond)} order by p.posting_date, p.creation""", args, as_dict=True)


def _key(r):
	return r.rental_contract or r.hire_order or r.pro_forma_invoice


def _per_contract(filters, fund):
	types = DEPOSIT_TYPES if fund == D.DEPOSIT else ADVANCE_TYPES
	groups = {}
	for r in _transactions(filters, types, dated=False):
		groups.setdefault(_key(r), []).append(r)
	# contracts with a requirement and nothing collected yet
	field = "security_deposit" if fund == D.DEPOSIT else "advance_amount"
	cond = {"docstatus": 1, field: [">", 0]}
	companies = _companies(filters)
	if companies:
		cond["company"] = ["in", companies]
	for key in ("customer",):
		if filters.get(key):
			cond[key] = filters[key]
	if filters.get("rental_contract"):
		cond["name"] = filters.rental_contract
	for name in frappe.get_all("Rental Contract", filters=cond, pluck="name"):
		groups.setdefault(name, [])
	out = []
	for key, rows in groups.items():
		c = frappe.db.get_value("Rental Contract", key, ["customer", "customer_name", "company", "security_deposit", "advance_amount",
			"status", "currency"], as_dict=True)
		first = rows[0] if rows else frappe._dict()
		s = D.summarize(rows, c.security_deposit if c else 0, c.advance_amount if c else 0)
		out.append(frappe._dict(s, contract=key, contract_type="Rental Contract" if c else ("Hire Order" if first.hire_order else "Rental Pro Forma Invoice"),
			customer=(c or first).customer, customer_name=(c or first).customer_name, company=(c or first).company,
			currency=(c.currency if c else None) or first.currency or frappe.get_cached_value("Company", (c or first).company, "default_currency"),
			contract_status=c.status if c else ""))
	status = filters.get("status")
	if status:
		out = [r for r in out if r[("deposit_status" if fund == D.DEPOSIT else "advance_status")] == status]
	return sorted(out, key=lambda r: (r.customer or "", r.contract or ""))


def _c(fieldname, label, fieldtype="Currency", width=120, options="currency"):
	col = {"fieldname": fieldname, "label": _(label), "fieldtype": fieldtype, "width": width}
	if fieldtype == "Currency":
		col["options"] = options
	elif fieldtype in ("Link", "Dynamic Link"):
		col["options"] = options
	return col


CONTRACT_COL = _c("contract", "Contract / Order", "Dynamic Link", 150, "contract_type")
CONTRACT_TYPE_COL = dict(_c("contract_type", "Document Type", "Data", 10), hidden=1)


def execute(filters, mode):
	filters = frappe._dict(filters or {})
	filters.to_date = filters.get("to_date") or nowdate()
	if filters.get("from_date") and getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date"))
	result = list(globals()["_" + mode](filters))
	result[1] = with_totals(result[0], result[1])
	return tuple(result)


def with_totals(columns, data):
	"""A total row per currency: amounts in AED and OMR are never added together. A running balance is not summed."""
	money = [c["fieldname"] for c in columns if c.get("fieldtype") == "Currency" and c["fieldname"] != "balance"]
	if not data or not money:
		return data
	first = next(c["fieldname"] for c in columns if not c.get("hidden"))
	totals = {}
	for row in data:
		if row.get("name") is None and row.get("transaction_type") == _("Opening Balance"):
			continue
		t = totals.setdefault(row.get("currency"), {f: 0.0 for f in money})
		for f in money:
			t[f] += flt(row.get(f))
	out = list(data)
	for currency, t in sorted(totals.items(), key=lambda kv: kv[0] or ""):
		out.append(frappe._dict(t, **{first: _("Total ({0})").format(currency) if currency else _("Total"), "currency": currency, "is_total_row": 1}))
	return out


# ------------------------------------------------------------------ deposit summaries
def _contract_deposit(filters, only_outstanding=False):
	rows = _per_contract(filters, D.DEPOSIT)
	if only_outstanding:
		rows = [r for r in rows if r.deposit_outstanding > 0.0001]
	cols = [CONTRACT_COL, CONTRACT_TYPE_COL, _c("customer", "Customer", "Link", 150, "Customer"), _c("company", "Company", "Link", 130, "Company"),
		_c("currency", "Currency", "Link", 70, "Currency"), _c("deposit_required", "Required"), _c("deposit_collected", "Collected"),
		_c("deposit_outstanding", "Outstanding"), _c("deposit_refunded", "Refunded"), _c("deposit_adjusted", "Adjusted"),
		_c("deposit_balance", "Refundable Balance"), _c("deposit_status", "Status", "Data", 130), _c("contract_status", "Contract Status", "Data", 100)]
	return cols, rows, None, _chart(rows, "deposit_balance", _("Deposit held"))


def _outstanding_deposit(filters):
	return _contract_deposit(filters, only_outstanding=True)


def _customer_deposit(filters):
	rows = _per_contract(filters, D.DEPOSIT)
	by = {}
	for r in rows:
		g = by.setdefault((r.customer, r.currency), frappe._dict(customer=r.customer, customer_name=r.customer_name, currency=r.currency, contracts=0,
			deposit_required=0, deposit_collected=0, deposit_outstanding=0, deposit_refunded=0, deposit_adjusted=0, deposit_balance=0))
		g.contracts += 1
		for k in ("deposit_required", "deposit_collected", "deposit_outstanding", "deposit_refunded", "deposit_adjusted", "deposit_balance"):
			g[k] += flt(r[k])
	data = sorted(by.values(), key=lambda g: g.customer)
	cols = [_c("customer", "Customer", "Link", 160, "Customer"), _c("customer_name", "Customer Name", "Data", 180), _c("currency", "Currency", "Link", 70, "Currency"),
		_c("contracts", "Contracts", "Int", 80), _c("deposit_required", "Required"), _c("deposit_collected", "Collected"), _c("deposit_outstanding", "Outstanding"),
		_c("deposit_refunded", "Refunded"), _c("deposit_adjusted", "Adjusted"), _c("deposit_balance", "Refundable Balance")]
	return cols, data


# ------------------------------------------------------------------ advance summaries
def _customer_advance(filters, only_available=False):
	rows = _per_contract(filters, D.ADVANCE)
	if only_available:
		rows = [r for r in rows if r.advance_available > 0.0001]
	cols = [CONTRACT_COL, CONTRACT_TYPE_COL, _c("customer", "Customer", "Link", 150, "Customer"), _c("company", "Company", "Link", 130, "Company"),
		_c("currency", "Currency", "Link", 70, "Currency"), _c("advance_required", "Required"), _c("advance_received", "Received"),
		_c("advance_utilized", "Utilized"), _c("advance_refunded", "Refunded"), _c("advance_available", "Available"),
		_c("advance_status", "Status", "Data", 130)]
	return cols, rows, None, _chart(rows, "advance_available", _("Advance available"))


def _unutilized_advance(filters):
	return _customer_advance(filters, only_available=True)


# ------------------------------------------------------------------ transaction lists
def _list_cols(extra=()):
	return [_c("posting_date", "Date", "Date", 95), _c("name", "Receipt / Voucher", "Link", 140, "Rental Contract Payment"),
		_c("transaction_type", "Transaction", "Data", 140), _c("customer", "Customer", "Link", 140, "Customer"),
		_c("rental_contract", "Rental Contract", "Link", 130, "Rental Contract"), _c("currency", "Currency", "Link", 70, "Currency"),
		_c("amount", "Amount")] + list(extra) + [_c("journal_entry", "Journal Entry", "Link", 140, "Journal Entry")]


def _filter_type(rows, filters):
	return [r for r in rows if not filters.get("status") or r.transaction_type == filters.status]


def _deposit_refund(filters):
	rows = _filter_type(_transactions(filters, (D.D_REFUND, D.D_DEDUCT)), filters)
	extra = [_c("mode_of_payment", "Payment Method", "Link", 110, "Mode of Payment"), _c("reference_no", "Reference", "Data", 110),
		_c("sales_invoice", "Against Invoice", "Link", 130, "Sales Invoice"), _c("deduction_reason", "Deduction Reason", "Data", 110),
		_c("approved_by", "Approved By", "Link", 130, "User")]
	return _list_cols(extra), rows


def _advance_adjustment(filters):
	rows = _transactions(filters, (D.A_ADJUST,))
	for r in rows:
		si = frappe.db.get_value("Sales Invoice", r.sales_invoice, ["posting_date", "grand_total", "outstanding_amount"], as_dict=True) or {}
		r.invoice_date, r.invoice_total, r.invoice_outstanding = si.get("posting_date"), si.get("grand_total"), si.get("outstanding_amount")
	extra = [_c("sales_invoice", "Sales Invoice", "Link", 140, "Sales Invoice"), _c("invoice_date", "Invoice Date", "Date", 95),
		_c("invoice_total", "Invoice Total"), _c("invoice_outstanding", "Invoice Outstanding"), _c("vat_amount", "VAT Reversed")]
	return _list_cols(extra), rows


def _ledger(filters, fund):
	types = DEPOSIT_TYPES if fund == D.DEPOSIT else ADVANCE_TYPES
	increase = D.D_COLLECT if fund == D.DEPOSIT else D.A_COLLECT
	all_rows = _transactions(filters, types, dated=False)
	data, balance, opening = [], {}, {}
	start = getdate(filters.from_date) if filters.get("from_date") else None
	for r in all_rows:
		key = (r.customer, r.currency)
		signed = flt(r.amount) if r.transaction_type == increase else -flt(r.amount)
		if start and getdate(r.posting_date) < start:
			opening[key] = opening.get(key, 0) + signed
			continue
		if key not in balance:
			balance[key] = opening.get(key, 0)
			if balance[key]:
				data.append(frappe._dict(customer=r.customer, currency=r.currency, transaction_type=_("Opening Balance"), balance=balance[key]))
		balance[key] += signed
		data.append(frappe._dict(r, debit=flt(r.amount) if signed < 0 else 0, credit=signed if signed > 0 else 0, balance=balance[key]))
	if filters.get("status"):
		data = [r for r in data if r.transaction_type in (filters.status, _("Opening Balance"))]
	cols = [_c("posting_date", "Date", "Date", 95), _c("name", "Receipt / Voucher", "Link", 140, "Rental Contract Payment"),
		_c("transaction_type", "Transaction", "Data", 140), _c("customer", "Customer", "Link", 140, "Customer"),
		_c("rental_contract", "Rental Contract", "Link", 130, "Rental Contract"), _c("currency", "Currency", "Link", 70, "Currency"),
		_c("debit", "Debit (Reduces Liability)"), _c("credit", "Credit (Increases Liability)"), _c("balance", "Liability Balance"),
		_c("sales_invoice", "Against Invoice", "Link", 130, "Sales Invoice"), _c("journal_entry", "Journal Entry", "Link", 140, "Journal Entry")]
	return cols, data


def _deposit_ledger(filters):
	return _ledger(filters, D.DEPOSIT)


def _advance_ledger(filters):
	return _ledger(filters, D.ADVANCE)


def _chart(rows, field, label):
	top = sorted([r for r in rows if flt(r[field]) > 0], key=lambda r: -flt(r[field]))[:10]
	if not top:
		return None
	return {"data": {"labels": [r.contract for r in top], "datasets": [{"name": label, "values": [flt(r[field]) for r in top]}]},
		"type": "bar", "colors": ["#0b3d5c"]}
