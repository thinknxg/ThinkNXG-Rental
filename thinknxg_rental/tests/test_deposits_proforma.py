"""Security deposits and advances posted to the accounts, and the Pro Forma Invoice with UAE / Oman VAT.

    bench --site <site> run-tests --module thinknxg_rental.tests.test_deposits_proforma

The eight scenarios of the brief run on an Oman (OMR) contract; the UAE (AED) company runs the same money
flow through a pro forma invoice, its tax invoice and VAT accounted on the advance.
"""
import frappe
from frappe.utils import add_days, flt, nowdate

from thinknxg_rental.services import deposit_reports, deposits, vat
from thinknxg_rental.services.setup import ensure_company_profile
from thinknxg_rental.tests import test_excess_material as tem
from thinknxg_rental.thinknxg_rental.doctype.rental_contract_payment.rental_contract_payment import create
from thinknxg_rental.thinknxg_rental.doctype.rental_pro_forma_invoice import rental_pro_forma_invoice as pf

UAE = "Gulf Rental UAE"
APPROVER_LESS = "deposit.rental.user@example.com"


def gl_balance(account, party=None):
	sql = "select ifnull(sum(credit) - sum(debit), 0) from `tabGL Entry` where account = %s and is_cancelled = 0"
	args = [account]
	if party:
		sql += " and party_type = 'Customer' and party = %s"
		args.append(party)
	return flt(frappe.db.sql(sql, args)[0][0])


def ensure_bank_account(company):
	abbr = frappe.get_cached_value("Company", company, "abbr")
	name = frappe.db.get_value("Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name")
	if name:
		return name
	parent = frappe.db.get_value("Account", {"company": company, "is_group": 1, "account_name": ["like", "Bank Accounts%"]}, "name") \
		or frappe.db.get_value("Account", {"company": company, "is_group": 1, "root_type": "Asset"}, "name", order_by="lft desc")
	return frappe.get_doc({"doctype": "Account", "account_name": "Test Bank", "company": company, "parent_account": parent,
		"account_type": "Bank", "root_type": "Asset", "is_group": 0}).insert().name or f"Test Bank - {abbr}"


def ensure_mop(name, kind, company):
	account = frappe.get_cached_value("Company", company, "default_cash_account") if kind == "Cash" else ensure_bank_account(company)
	if not account:
		account = frappe.db.get_value("Account", {"company": company, "account_type": "Cash", "is_group": 0}, "name")
	if not frappe.db.exists("Mode of Payment", name):
		frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": name, "type": kind, "enabled": 1}).insert()
	mop = frappe.get_doc("Mode of Payment", name)
	if not any(a.company == company for a in mop.accounts):
		mop.append("accounts", {"company": company, "default_account": account})
		mop.save()
	return name


def ensure_uae_company():
	if not frappe.db.exists("Company", UAE):
		frappe.get_doc({"doctype": "Company", "company_name": UAE, "abbr": "GRU", "country": "United Arab Emirates",
			"default_currency": "AED", "chart_of_accounts": "Standard", "create_chart_of_accounts_based_on": "Standard Template"}).insert()
	abbr = "GRU"
	duties = frappe.db.get_value("Account", {"company": UAE, "is_group": 1, "account_name": "Duties and Taxes"}, "name")
	vat_account = frappe.db.get_value("Account", {"company": UAE, "account_name": "VAT 5%"}, "name") or frappe.get_doc({
		"doctype": "Account", "account_name": "VAT 5%", "company": UAE, "parent_account": duties, "account_type": "Tax",
		"tax_rate": 5, "is_group": 0}).insert().name
	template = frappe.db.get_value("Sales Taxes and Charges Template", {"company": UAE, "title": "UAE VAT 5%"}, "name") or frappe.get_doc({
		"doctype": "Sales Taxes and Charges Template", "title": "UAE VAT 5%", "company": UAE,
		"taxes": [{"charge_type": "On Net Total", "account_head": vat_account, "rate": 5, "description": "VAT 5%"}]}).insert().name
	ensure_company_profile(UAE)
	profile = frappe.get_doc("Rental Company Profile", UAE)
	profile.update({"vat_registration_number": "100123456700003", "sales_taxes_template": template, "vat_on_advances": 1,
		"output_vat_account": vat_account})
	profile.save()
	vat.mark_reviewed(profile, "Test review")
	ensure_mop("Cash", "Cash", UAE)
	return frappe._dict(vat_account=vat_account, template=template, abbr=abbr)


class TestDepositsAndProForma(tem.TestExcessMaterial):
	# the parent's tests run in their own class
	for _name in [n for n in dir(tem.TestExcessMaterial) if n.startswith("test_")]:
		locals()[_name] = None
	del _name

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		ensure_company_profile(cls.company)
		frappe.db.set_single_value("Rental Settings", "approve_deposit_refunds", 1)
		frappe.db.set_single_value("Rental Settings", "auto_adjust_advance", 0)
		tem.ensure_user(APPROVER_LESS, ["Rental User", "Accounts User"])
		ensure_mop("Cash", "Cash", cls.company)
		ensure_mop("Wire Transfer", "Bank", cls.company)
		cls.uae = ensure_uae_company()
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		self.profile = vat.get_profile(self.company)

	# ------------------------------------------------------------------ helpers
	def rc(self, deposit=10000, advance=5000):
		item = self.item()
		name = self.contract([(item, 10)])
		frappe.db.set_value("Rental Contract", name, {"security_deposit": deposit, "advance_amount": advance})
		return frappe._dict(name=name, item=item, customer=frappe.db.get_value("Rental Contract", name, "customer"))

	def pay(self, type_, amount, **values):
		values = dict({"transaction_type": type_, "amount": amount, "posting_date": nowdate()}, **values)
		if type_ in deposits.CASH:
			values.setdefault("mode_of_payment", "Cash")
		return frappe.get_doc(deposits.DOCTYPE, create(values)["name"])

	def invoice(self, company, customer, amount, contract=None, taxes=None):
		si = frappe.get_doc({"doctype": "Sales Invoice", "company": company, "customer": customer, "posting_date": nowdate(),
			"nxg_rental_contract": contract, "items": [{"item_code": frappe.db.get_single_value("Rental Settings", "damage_recovery_item"),
			"qty": 1, "rate": amount, "uom": "Charge"}]})
		if taxes:
			si.taxes_and_charges = taxes
			si.set_taxes()
		si.insert()
		si.submit()
		return si

	def balances(self, rc):
		return deposits.balances(rental_contract=rc)

	# ------------------------------------------------------------------ the eight scenarios (OMR)
	def test_deposit_and_advance_lifecycle_omr(self):
		c = self.rc()
		dep, adv = self.profile.security_deposit_account, self.profile.customer_advance_account
		# 1. the contract asks for 10,000 deposit and 5,000 advance; nothing collected yet
		b = self.balances(c.name)
		self.assertEqual((b.deposit_required, b.advance_required, b.deposit_status, b.advance_status), (10000, 5000, "Not Collected", "Not Received"))
		# 2. 6,000 deposit collected: 4,000 outstanding, posted as a liability (never income)
		r = self.pay("Deposit Collection", 6000, rental_contract=c.name)
		self.assertEqual((r.docstatus, r.status, r.currency), (1, "Posted", "OMR"))
		b = self.balances(c.name)
		self.assertEqual((b.deposit_collected, b.deposit_outstanding, b.deposit_status), (6000, 4000, "Partially Collected"))
		self.assertEqual(gl_balance(dep, c.customer), 6000)
		self.assertEqual(frappe.db.get_value("Rental Contract", c.name, "deposit_outstanding"), 4000)
		je = frappe.get_doc("Journal Entry", r.journal_entry)
		self.assertEqual((je.total_debit, je.total_credit, je.docstatus), (6000, 6000, 1))
		# 3. 3,000 advance received: 3,000 available, in its own liability account
		self.pay("Advance Collection", 3000, rental_contract=c.name, mode_of_payment="Wire Transfer", reference_no="TT-881")
		b = self.balances(c.name)
		self.assertEqual((b.advance_received, b.advance_available, b.advance_status), (3000, 3000, "Partially Received"))
		self.assertEqual((gl_balance(adv, c.customer), gl_balance(dep, c.customer)), (3000, 6000))
		# 4. an 8,000 rental invoice; 2,000 of the advance adjusted against it
		si = self.invoice(self.company, c.customer, 8000, c.name)
		a = self.pay("Advance Adjustment", 2000, rental_contract=c.name, sales_invoice=si.name)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount")), flt(si.grand_total) - 2000)
		self.assertEqual(a.approved_by, "Administrator")
		# 5. 1,000 advance left
		b = self.balances(c.name)
		self.assertEqual((b.advance_utilized, b.advance_available, b.advance_status), (2000, 1000, "Partially Utilized"))
		self.assertEqual(gl_balance(adv, c.customer), 1000)
		# 6. material returned damaged: 1,000 deducted from the deposit against the damage invoice
		damage = self.invoice(self.company, c.customer, 1000, c.name)
		self.pay("Deposit Deduction", 1000, rental_contract=c.name, sales_invoice=damage.name, deduction_reason="Damage")
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", damage.name, "outstanding_amount")), flt(damage.grand_total) - 1000)
		self.assertEqual(self.balances(c.name).deposit_balance, 5000)
		# 7. the remaining 5,000 refunded: a user who cannot approve leaves it pending, a manager posts it
		frappe.set_user(APPROVER_LESS)
		pending = self.pay("Deposit Refund", 5000, rental_contract=c.name)
		frappe.set_user("Administrator")
		self.assertEqual((pending.docstatus, pending.status), (0, "Pending Approval"))
		self.assertEqual(self.balances(c.name).deposit_balance, 5000)
		pending.submit()
		self.assertEqual((pending.approved_by, frappe.db.get_value(deposits.DOCTYPE, pending.name, "status")), ("Administrator", "Posted"))
		# 8. ledgers, liabilities and history agree
		b = self.balances(c.name)
		self.assertEqual((b.deposit_collected, b.deposit_refunded, b.deposit_adjusted, b.deposit_balance, b.deposit_status),
			(6000, 5000, 1000, 0, "Settled"))
		self.assertEqual((gl_balance(dep, c.customer), gl_balance(adv, c.customer)), (0, 1000))
		row = frappe.db.get_value("Rental Contract", c.name, deposits.CONTRACT_FIELDS, as_dict=True)
		self.assertEqual((row.deposit_balance, row.advance_available, row.deposit_status, row.advance_status), (0, 1000, "Settled", "Partially Utilized"))
		self.assertEqual(len(deposits.history(c.name)), 5)
		jes = frappe.get_all("Journal Entry", filters={"nxg_rental_contract_payment": ["in", [h.name for h in deposits.history(c.name)]], "docstatus": 1},
			fields=["total_debit", "total_credit"])
		self.assertEqual(len(jes), 5)
		self.assertTrue(all(flt(j.total_debit) == flt(j.total_credit) for j in jes))
		body = lambda rows: [r for r in rows if not r.get("is_total_row")]
		_cols, ledger = deposit_reports.execute({"rental_contract": c.name}, "deposit_ledger")
		self.assertEqual([flt(r.balance) for r in body(ledger)], [6000, 5000, 0])
		total = [r for r in ledger if r.get("is_total_row")]
		self.assertEqual([(r.currency, flt(r.credit), flt(r.debit)) for r in total], [("OMR", 6000, 6000)])  # one total per currency
		_cols, rows, *_ = deposit_reports.execute({"rental_contract": c.name}, "contract_deposit")
		self.assertEqual((rows[0].deposit_balance, rows[0].deposit_status), (0, "Settled"))
		_cols, rows, *_ = deposit_reports.execute({"customer": c.customer}, "unutilized_advance")
		self.assertEqual([flt(r.advance_available) for r in body(rows)], [1000])
		_cols, rows = deposit_reports.execute({"customer": c.customer, "country": "Oman"}, "advance_adjustment")
		self.assertEqual([(r.sales_invoice, flt(r.amount)) for r in body(rows)], [(si.name, 2000)])

	def test_limits_and_controls(self):
		c = self.rc(deposit=1000, advance=500)
		with self.assertRaises(frappe.ValidationError):  # more than the outstanding deposit
			self.pay("Deposit Collection", 1500, rental_contract=c.name)
		with self.assertRaises(frappe.ValidationError):  # nothing to refund yet
			self.pay("Deposit Refund", 10, rental_contract=c.name)
		with self.assertRaises(frappe.ValidationError):  # bank payment without its reference
			self.pay("Advance Collection", 100, rental_contract=c.name, mode_of_payment="Wire Transfer")
		col = self.pay("Deposit Collection", 1000, rental_contract=c.name, request_id="dup-" + tem.tag())
		again = self.pay("Deposit Collection", 1000, rental_contract=c.name, request_id=col.request_id)  # a retried request
		self.assertEqual(again.name, col.name)
		self.assertEqual(self.balances(c.name).deposit_collected, 1000)
		self.pay("Advance Collection", 500, rental_contract=c.name)
		other = self.rc(deposit=0, advance=0)
		foreign = self.invoice(self.company, other.customer, 300, other.name)
		with self.assertRaises(frappe.ValidationError):  # another customer's invoice
			self.pay("Advance Adjustment", 100, rental_contract=c.name, sales_invoice=foreign.name)
		small = self.invoice(self.company, c.customer, 200, c.name)
		with self.assertRaises(frappe.ValidationError):  # beyond the invoice outstanding
			self.pay("Advance Adjustment", 300, rental_contract=c.name, sales_invoice=small.name)
		adj = self.pay("Advance Adjustment", 200, rental_contract=c.name, sales_invoice=small.name)
		with self.assertRaises(frappe.ValidationError):  # the same invoice again: nothing outstanding
			self.pay("Advance Adjustment", 1, rental_contract=c.name, sales_invoice=small.name)
		with self.assertRaises(frappe.ValidationError):  # the invoice carries an adjustment
			frappe.get_doc("Sales Invoice", small.name).cancel()
		with self.assertRaises(frappe.ValidationError):  # the journal entry is cancelled only through its transaction
			frappe.get_doc("Journal Entry", adj.journal_entry).cancel()
		refund = self.pay("Deposit Refund", 400, rental_contract=c.name)
		with self.assertRaises(frappe.ValidationError):  # part of the collection is refunded
			frappe.get_doc(deposits.DOCTYPE, col.name).cancel()
		frappe.get_doc(deposits.DOCTYPE, refund.name).cancel()
		self.assertEqual(frappe.db.get_value("Journal Entry", refund.journal_entry, "docstatus"), 2)
		self.assertEqual(self.balances(c.name).deposit_balance, 1000)
		frappe.get_doc(deposits.DOCTYPE, adj.name).cancel()
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", small.name, "outstanding_amount")), flt(small.grand_total))
		self.assertEqual(self.balances(c.name).advance_available, 500)

	def test_collected_on_hire_order_moves_to_contract(self):
		c = self.rc(deposit=0, advance=0)
		ho = frappe.db.get_value("Rental Contract", c.name, "hire_order")
		p = self.pay("Advance Collection", 50, hire_order=ho)
		self.assertEqual(p.rental_contract, c.name)  # the order already has its contract
		frappe.db.set_value(deposits.DOCTYPE, p.name, "rental_contract", None)  # as if collected before the contract existed
		self.assertEqual(self.balances(c.name).advance_available, 50)  # the order's money counts for its contract
		deposits.link_hire_order_payments(frappe.get_doc("Rental Contract", c.name))
		self.assertEqual(frappe.db.get_value(deposits.DOCTYPE, p.name, "rental_contract"), c.name)
		self.assertEqual(frappe.db.get_value("Rental Contract", c.name, "advance_available"), 50)

	# ------------------------------------------------------------------ pro forma invoice (AED) and its tax invoice
	def pro_forma(self, company, customer, item, **values):
		doc = frappe.get_doc(dict({"doctype": pf.DOCTYPE, "company": company, "customer": customer, "posting_date": nowdate(),
			"valid_until": add_days(nowdate(), 15),
			"items": [{"item_code": item, "qty": 10, "rate_basis": "Monthly", "rate": 300, "rental_from": nowdate(), "rental_to": add_days(nowdate(), 44)}],
			"charges": [{"charge_type": "Transportation", "qty": 1, "rate": 200}],
			"discount_percentage": 10,
			"deposits": [{"description": "Refundable deposit", "basis_qty": 1, "rate": 1000, "deposit_type": "Refundable"}]}, **values))
		doc.insert()
		return doc

	def uae_customer(self):
		return frappe.get_doc({"doctype": "Customer", "customer_name": f"Dubai Builders {tem.tag()}", "customer_type": "Company"}).insert().name

	def test_pro_forma_uae_vat_and_conversion(self):
		item, customer = self.item(), self.uae_customer()
		vat_before = gl_balance(self.uae.vat_account)  # other runs may have left entries on the company's VAT account
		doc = self.pro_forma(UAE, customer, item)
		# 45 days = 1.5 months; transport 200; 10% discount; VAT 5%; deposit kept apart
		self.assertEqual((doc.currency, doc.vat_country, doc.company_vat_number), ("AED", "United Arab Emirates", "100123456700003"))
		self.assertTrue(doc.name.startswith("PI-AE-GRU-"))
		self.assertEqual((doc.items[0].billable_periods, doc.items[0].amount), (1.5, 4500))
		self.assertEqual((doc.total_rental, doc.total_transport, doc.subtotal, doc.total_discount, doc.net_total), (4500, 200, 4700, 470, 4230))
		self.assertEqual((doc.taxable_amount, doc.total_vat, doc.total_including_vat), (4230, 211.5, 4441.5))
		self.assertEqual((doc.total_deposit, doc.deposits[0].vat_treatment, doc.deposit_vat), (1000, "Out of Scope", 0))
		self.assertEqual(doc.grand_total_payable, 5441.5)
		self.assertNotIn("GST", doc.in_words)
		# workflow and its audit trail
		doc.submit_for_approval()
		doc.submit()
		doc.mark_sent("PDF")
		doc.mark_accepted("Site manager")
		self.assertEqual(frappe.db.get_value(pf.DOCTYPE, doc.name, "status"), "Customer Accepted")
		log = [r.status for r in frappe.get_doc(pf.DOCTYPE, doc.name).status_log]
		self.assertEqual(log, ["Draft", "Submitted for Approval", "Approved", "Sent to Customer", "Customer Accepted"])
		# money against it: a liability, with the VAT of the advance accounted (profile setting)
		adv = self.pay("Advance Collection", 2100, pro_forma_invoice=doc.name)
		self.assertEqual((adv.currency, adv.vat_amount), ("AED", 100))
		self.pay("Deposit Collection", 1000, pro_forma_invoice=doc.name)
		doc.reload()
		self.assertEqual((doc.status, doc.advance_received, doc.deposit_received, doc.grand_total_payable), ("Advance Received", 2100, 1000, 2341.5))
		profile = vat.get_profile(UAE)
		self.assertEqual((gl_balance(profile.customer_advance_account, customer), gl_balance(self.uae.vat_account) - vat_before), (2000, 100))
		# the tax invoice: its own series, VAT worked out again, once only
		si_name = pf.make_sales_invoice(doc.name)
		with self.assertRaises(frappe.ValidationError):
			pf.make_sales_invoice(doc.name)
		si = frappe.get_doc("Sales Invoice", si_name)
		self.assertEqual((si.currency, si.nxg_pro_forma_invoice, flt(si.net_total), flt(si.total_taxes_and_charges)), ("AED", doc.name, 4230, 211.5))
		si.submit()
		self.assertEqual(frappe.db.get_value(pf.DOCTYPE, doc.name, "status"), "Converted to Sales Invoice")
		# the advance adjusted against it: liability and its VAT reversed, the invoice reduced
		self.pay("Advance Adjustment", 2100, pro_forma_invoice=doc.name, sales_invoice=si.name)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount")), flt(si.rounded_total or si.grand_total) - 2100)
		self.assertEqual(gl_balance(profile.customer_advance_account, customer), 0)
		self.assertEqual(gl_balance(self.uae.vat_account) - vat_before, 211.5)  # only the tax invoice's VAT is left
		with self.assertRaises(frappe.ValidationError):  # an OMR invoice cannot take an AED advance
			self.pay("Advance Adjustment", 1, pro_forma_invoice=doc.name, sales_invoice=self.invoice(self.company, customer, 10).name)
		# deposit refunded in full, in AED
		self.pay("Deposit Refund", 1000, pro_forma_invoice=doc.name)
		self.assertEqual(gl_balance(profile.security_deposit_account, customer), 0)
		# cancelling the tax invoice is refused while the adjustment stands
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Sales Invoice", si.name).cancel()

	def test_pro_forma_omr_precision_rules_and_approval(self):
		c = self.rc(deposit=0, advance=0)
		doc = frappe.get_doc(pf.make_from_rental_contract(c.name))
		doc.items[0].update({"rate": 1.333, "rate_basis": "Weekly", "rental_from": nowdate(), "rental_to": add_days(nowdate(), 9), "qty": 7})
		doc.append("charges", {"charge_type": "Installation", "qty": 1, "rate": 12.5})
		doc.insert()
		self.assertEqual(doc.currency, "OMR")
		self.assertTrue(doc.name.startswith("PI-OM-"))
		self.assertEqual(doc.items[0].amount, flt(7 * 1.333 * 10 / 7.0, 3))  # 10 days = 1.4286 weeks, OMR to 3 decimals
		self.assertEqual(doc.total_vat, flt(doc.net_total * 0.05, 3))
		frappe.db.set_single_value("Rental Settings", "pro_forma_rounding", "Round Up to Whole Period")
		try:
			doc.save()
			self.assertEqual(doc.items[0].billable_periods, 2)
		finally:
			frappe.db.set_single_value("Rental Settings", "pro_forma_rounding", "Pro Rata")
		# a VAT treatment set by hand: a Rental Manager cannot approve, an Accounts Manager can
		doc.reload()
		doc.charges[0].update({"vat_treatment": "Zero-Rated", "treatment_overridden": 1})
		doc.save()
		self.assertEqual((doc.charges[0].vat_rate, doc.zero_rated_amount > 0), (0, True))
		self.assertIn("Accounts Manager", doc.vat_review_note)
		tem.ensure_user("pf.rental.manager@example.com", ["Rental Manager", "Rental User"])
		frappe.set_user("pf.rental.manager@example.com")
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(pf.DOCTYPE, doc.name).submit()
		frappe.set_user("Administrator")
		frappe.get_doc(pf.DOCTYPE, doc.name).submit()
		# expiry before acceptance
		frappe.db.set_value(pf.DOCTYPE, doc.name, "valid_until", add_days(nowdate(), -1))
		pf.expire()
		self.assertEqual(frappe.db.get_value(pf.DOCTYPE, doc.name, "status"), "Expired")
		with self.assertRaises(frappe.ValidationError):
			pf.make_sales_invoice(doc.name)

	def test_rental_invoiced_on_pro_forma_is_credited_on_billing(self):
		item = self.item()
		rc = self.contract([(item, 10)])
		self.deliver(rc, [(item, 10)], days_ago=20)
		doc = frappe.get_doc(pf.make_from_rental_contract(rc))
		doc.items[0].update({"rate_basis": "Daily", "rate": 4, "rental_from": add_days(nowdate(), -20), "rental_to": add_days(nowdate(), -11)})
		doc.insert()
		doc.submit()
		si = frappe.get_doc("Sales Invoice", pf.make_sales_invoice(doc.name))
		si.submit()
		self.assertEqual(pf.prepaid_rental(rc), flt(si.net_total))  # 10 units x 10 days x 4 = 400
		from thinknxg_rental.services import billing

		billing.generate_billing(rc, upto_date=add_days(nowdate(), -1))
		schedules = frappe.get_all("Rental Billing Schedule", filters={"rental_contract": rc, "docstatus": 1}, pluck="name")
		self.assertTrue(schedules)
		credited = 0
		for s in schedules:
			name = frappe.db.get_value("Rental Billing Schedule", s, "sales_invoice") or billing.make_sales_invoice(s)
			credited += flt(frappe.db.get_value("Sales Invoice", name, "nxg_prepaid_credit"))
		self.assertEqual(credited, 400)
		self.assertEqual(pf.prepaid_rental(rc), 0)

	# ------------------------------------------------------------------ Command Center screens
	def test_command_center_screens(self):
		from thinknxg_rental.command_center import api as cc_api, registry
		from thinknxg_rental.portal import entry as E
		from thinknxg_rental.tests.test_admin_portal import STAFF, create, form, labels, run, save

		c = self.rc(deposit=800, advance=600)
		frappe.set_user(STAFF)
		try:
			# sidebar, list views, report pages, quick create
			nav = {i["key"] for g in registry.get_nav() for i in g["items"]}
			for key in ("finance/pro-forma", "finance/deposits", "reports/deposit-ledger", "reports/advances-unutilized"):
				self.assertIn(key, nav)
			self.assertEqual(registry.entry_route("pro-forma-invoice"), "finance/pro-forma")
			self.assertEqual(registry.entry_route("contract-payment"), "finance/deposits")
			self.assertIn("pro-forma-invoice", [q["entry"] for q in registry.get_quick_create()])
			for view, name in registry.REPORTS.items():
				if "deposit" in view or "advance" in view:
					meta = cc_api.report_meta(view)
					self.assertEqual(meta["name"], name)
					self.assertIn("country", [f["fieldname"] for f in meta["filters"]])
			# the contract's deposit and advance actions post receipts
			boot = form("rental-contract", c.name)
			self.assertIn("Collect Deposit", labels(boot))
			self.assertNotIn("Refund Deposit", labels(boot))  # nothing held yet
			# every deposit and advance panel asks for the posting date (today by default), right after the amount
			for action in boot["next"]:
				if action["label"] in ("Collect Deposit", "Collect Advance"):
					self.assertEqual([f["fieldname"] for f in action["ask"]][:2], ["amount", "posting_date"])
					self.assertEqual((action["ask"][1]["default"], action["ask"][1]["reqd"]), (nowdate(), 1))
			yesterday = add_days(nowdate(), -1)
			r = run(boot, "Collect Deposit", amount=800, posting_date=yesterday, mode_of_payment="Cash", remarks="At signing")
			self.assertIn("type=contract-payment", r["url"])
			run(form("rental-contract", c.name), "Collect Advance", amount=600, posting_date=yesterday, mode_of_payment="Cash")
			for p in frappe.get_all(deposits.DOCTYPE, filters={"rental_contract": c.name}, fields=["posting_date", "journal_entry"]):
				self.assertEqual(str(p.posting_date), yesterday)
				self.assertEqual(str(frappe.db.get_value("Journal Entry", p.journal_entry, "posting_date")), yesterday)
			row = frappe.db.get_value("Rental Contract", c.name, ["deposit_collected", "advance_available"], as_dict=True)
			self.assertEqual((row.deposit_collected, row.advance_available), (800, 600))
			boot = form("rental-contract", c.name)
			self.assertTrue({"Refund Deposit", "Adjust Deposit", "Adjust Advance Against Invoice", "Refund Advance"} <= set(labels(boot)))
			related = {g["label"]: g for g in boot["related"]}
			self.assertEqual(len(related["Deposits and advances"]["rows"]), 2)
			# a refund by a Rental Manager is approved and posted at once
			run(boot, "Refund Deposit", amount=300, posting_date=nowdate(), mode_of_payment="Cash")
			self.assertEqual(frappe.db.get_value("Rental Contract", c.name, "deposit_balance"), 500)
		finally:
			frappe.set_user("Administrator")
		# the rental invoice offers its contract's advance
		si = self.invoice(self.company, c.customer, 400, c.name)
		frappe.set_user(STAFF)
		try:
			boot = form("sales-invoice", si.name)
			a = next(x for x in boot["next"] if x["label"] == "Adjust Advance")
			self.assertEqual(a["ask"][0]["default"], 400)
			run(boot, "Adjust Advance", amount=400, posting_date=nowdate())
			self.assertEqual(flt(frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount")), flt(si.grand_total) - 400)
			self.assertNotIn("Adjust Advance", labels(form("sales-invoice", si.name)))
			# a transaction entered directly in its own form, then posted with Submit
			key = "contract-payment"
			new = form(key, None, rental_contract=c.name, transaction_type="Advance Refund")
			doc = dict(new["doc"], amount=200, mode_of_payment="Cash")
			name = save(key, doc)
			E.submit_entry(key, name)
			self.assertEqual(frappe.db.get_value(deposits.DOCTYPE, name, "status"), "Posted")
			self.assertEqual(frappe.db.get_value("Rental Contract", c.name, "advance_available"), 0)
			self.assertTrue(form(key, name)["prints"])
			# pro forma invoice from the hire order, through approval, sharing, acceptance, payment and the tax invoice
			ho = frappe.db.get_value("Rental Contract", c.name, "hire_order")
			key, pi = create(form("hire-order", ho), "New Pro Forma Invoice")
			self.assertEqual(key, "pro-forma-invoice")
			pi_name = save(key, pi["doc"])
			boot = form(key, pi_name)
			self.assertEqual(boot["doc"]["currency"], "OMR")
			run(boot, "Submit for Approval")
			E.submit_entry(key, pi_name)  # a Rental Manager approves
			boot = form(key, pi_name)
			self.assertEqual(boot["doc"]["status"], "Approved")
			self.assertIn("Share on WhatsApp", [p["label"] for p in boot["prints"]])
			run(boot, "Mark as Sent", via="WhatsApp")
			run(form(key, pi_name), "Customer Accepted", accepted_by="Site engineer")
			r = run(form(key, pi_name), "Collect Advance", amount=100, posting_date=nowdate(), mode_of_payment="Cash")
			self.assertIn("type=contract-payment", r["url"])
			self.assertEqual(frappe.db.get_value(pf.DOCTYPE, pi_name, "status"), "Advance Received")
			skey, sinv = create(form(key, pi_name), "Create Tax Invoice")
			self.assertEqual((skey, sinv["doc"]["nxg_pro_forma_invoice"]), ("sales-invoice", pi_name))
			self.assertNotIn("Create Tax Invoice", labels(form(key, pi_name)))
			log = [r["status"] for r in form(key, pi_name)["doc"]["status_log"]]
			self.assertEqual(log[:5], ["Draft", "Submitted for Approval", "Approved", "Sent to Customer", "Customer Accepted"])
		finally:
			frappe.set_user("Administrator")

	def test_advance_on_contract_reaches_its_pro_forma(self):
		"""Money collected on the contract or hire order is shown on its one open pro forma invoice."""
		c = self.rc(deposit=0, advance=0)
		ho = frappe.db.get_value("Rental Contract", c.name, "hire_order")
		doc = frappe.get_doc(pf.make_from_rental_contract(c.name))
		doc.insert()
		doc.submit()
		a = self.pay("Advance Collection", 70, rental_contract=c.name)
		self.assertEqual(a.pro_forma_invoice, doc.name)
		self.pay("Advance Collection", 30, hire_order=ho)
		self.pay("Deposit Collection", 40, rental_contract=c.name)
		pi = frappe.get_doc(pf.DOCTYPE, doc.name)
		self.assertEqual((pi.status, pi.advance_received, pi.deposit_received), ("Advance Received", 100, 40))
		# deposit received never reduces the rental and charges payable
		self.assertEqual(pi.grand_total_payable, flt(pi.total_including_vat - 100 + max(pi.total_deposit - 40, 0), 3))
		self.assertEqual(self.balances(c.name).advance_available, 100)  # still the contract's advance too
		# two open pro forma invoices: which one is not guessed
		other = frappe.get_doc(pf.make_from_rental_contract(c.name))
		other.insert()
		other.submit()
		self.assertFalse(self.pay("Advance Collection", 10, rental_contract=c.name).pro_forma_invoice)
		# collections posted before this change are linked by the upgrade patch
		from thinknxg_rental.patches.v2_7 import link_pro_forma_payments

		other.cancel()
		frappe.db.set_value(deposits.DOCTYPE, a.name, "pro_forma_invoice", None)
		pf.refresh_payments(doc.name)
		self.assertEqual(frappe.db.get_value(pf.DOCTYPE, doc.name, "advance_received"), 30)
		link_pro_forma_payments.execute()
		self.assertEqual(frappe.db.get_value(deposits.DOCTYPE, a.name, "pro_forma_invoice"), doc.name)
		self.assertEqual(frappe.db.get_value(pf.DOCTYPE, doc.name, "advance_received"), 110)  # the 10 has its one pro forma now too
