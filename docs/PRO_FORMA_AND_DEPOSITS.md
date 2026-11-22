# Pro Forma Invoice, UAE / Oman VAT, Security Deposits and Advances (2.7.0)

## Company profile (one per company)

**Rental Company Profile** holds, for each company:

- **VAT country:** Oman or United Arab Emirates. It must match the company's country.
- **Currency:** OMR with 3 decimals, or AED with 2. It must match the company's currency, so currencies never mix.
- **VAT registration number:** labelled TRN for the UAE, VATIN for Oman.
- **Standard rate:** 5%.
- **Number series:** the pro forma series (e.g. `PI-AE-GRU-.YYYY.-.#####`) and the tax invoice series.
- **Tax templates:** the Sales Taxes and Charges Template, and the Item Tax Templates for zero-rated, exempt and out-of-scope lines.
- **VAT treatment rules:** per charge category (Rental, Transportation, Loading, Unloading, Installation, Dismantling, Handling, Damage and Loss, Other Service, Security Deposit, Advance Payment). Each rule can be narrowed by:
  - **Supply:** Domestic or Cross-Border, worked out from where the material is used (the site address), else the customer's billing country.
  - **Customer VAT status:** registered or not.

  The most specific matching rule wins. A category with no rule is standard-rated, except Security Deposit, which is Out of Scope.
- **Finance review:** an Accounts Manager marks the rules reviewed. Any change to the rules clears the review. While the rules are not reviewed, pro forma invoices show a note.
- **Liability accounts** (Set Up Accounts creates them): *Customer Security Deposits* and *Customer Rental Advances*. Both are Liability accounts of type Receivable, so the customer is the party on every entry.
- **Output VAT Account** and **Account VAT on Advances Received:** off by default. Finance turns it on once the tax point is confirmed.

Setup creates a profile for the Rental Settings company when it is registered in Oman or the UAE.

## Pro Forma Invoice

- **Made from:** a Hire Order or Rental Contract (Create > Pro Forma Invoice), or entered directly. Rates come from the rate cards and the Rental Item Profile, never typed into code.
- **Material lines:** qty × rate × periods.
  - Periods are days, weeks (days / 7), months (Month Basis: 30 days or calendar days) or custom periods.
  - A minimum number of days can be set per line.
  - Rental Settings > Partial Rental Period chooses Pro Rata or Round Up to Whole Period.
- **Additional charges:** transport, loading, unloading, installation, dismantling, handling and other, each with its own VAT treatment.
- **Discount:** on rental and charges, before VAT.
- **Security deposit:** in its own section, never in the taxable total.
- **VAT:** worked out per line from the profile rules. A line can be set by hand ("treatment overridden"); approving such a document then needs an Accounts Manager.
- **Summary:**
  - charges: taxable, zero-rated, exempt, out of scope, total VAT and total including VAT;
  - deposit: shown separately;
  - **Grand Total Payable** = (charges including VAT − advance received) + (deposit − deposit received). Neither payment is counted twice.
- **Statuses:** Draft → Submitted for Approval → Approved (submit) → Sent to Customer (email with the PDF, WhatsApp, or marked as sent) → Customer Accepted → Advance Received (automatic) → Converted to Sales Invoice. Expired applies when the valid-until date passes before acceptance (daily job); Cancelled on cancel. Every change is logged in the Status History and the timeline.
- **Print:** A4 "PRO FORMA INVOICE", with the statement that it is not a VAT Tax Invoice.
- **Conversion** (Create > Tax Invoice):
  - makes a Sales Invoice in the profile's tax invoice series, with the profile's tax templates;
  - VAT is worked out again on the invoice date;
  - customer, references, material, quantities, rates, charges and discount are carried over; deposits are not;
  - only once: a second conversion is refused while the first invoice exists;
  - cancelling that invoice frees the pro forma invoice again;
  - rental invoiced this way is credited on the contract's later rental invoices (`nxg_prepaid_credit`), so the same days are not charged twice.

## Security deposits and advances

Every movement is a **Rental Contract Payment**. It has its own receipt or voucher number and print format, and it posts one balanced Journal Entry on submit:

| Transaction | Debit | Credit |
| --- | --- | --- |
| Deposit Collection | Bank / Cash | Customer Security Deposits |
| Deposit Refund | Customer Security Deposits | Bank / Cash |
| Deposit Deduction | Customer Security Deposits | Debtors, against the charge invoice (damage, missing, unpaid rental) |
| Advance Collection | Bank / Cash | Customer Rental Advances (+ Output VAT, if accounted) |
| Advance Adjustment | Customer Rental Advances (+ Output VAT) | Debtors, against the rental or tax invoice |
| Advance Refund | Customer Rental Advances (+ Output VAT) | Bank / Cash |

- **Contract balances:** collected, outstanding, refunded, adjusted, balance and the statuses are worked out from posted transactions only. The required amounts stay editable on the submitted contract.
- **Hire Order or Pro Forma Invoice:** money can be collected against either before the contract exists. It moves to the contract when the contract is submitted.
- **Limits:**
  - collections up to the outstanding requirement;
  - refunds and deductions up to the deposit held;
  - adjustments up to both the advance available and the invoice outstanding.
- **Matching:** the customer, company and currency must match the source document.
- **Concurrency:** postings on one contract are serialised (row lock).
- **Retries:** a retried request posts once (`request_id`).
- **Approval:** refunds and deductions, and advance refunds, wait as *Pending Approval* until an Accounts Manager or Rental Manager submits them (Rental Settings > Refunds and Deductions Need Approval).
- **Corrections:**
  - cancel the transaction, which cancels its Journal Entry;
  - the Journal Entry cannot be cancelled on its own;
  - a collection that was already refunded or adjusted cannot be cancelled;
  - an invoice with adjustments cannot be cancelled until they are.
- **Closed periods and frozen accounts:** these apply as for any Journal Entry.
- **Rental invoices:** the Sales Invoice shows the advance available. **Adjust Advance** applies part or all of it. Rental Settings > Adjust Advances on Rental Invoices does this automatically on submit.
- **Customer ledger:** the contract's View Ledger buttons open the General Ledger for the customer and the liability account.

## Reports (Deposits & Advances menu)

- Contract-wise Security Deposit
- Customer-wise Security Deposit
- Outstanding Security Deposit
- Security Deposit Refund Report
- Security Deposit Liability Ledger
- Customer Advance Report
- Unutilized Advance Report
- Advance Adjustment Report
- Customer Advance Liability Ledger

Filters: company, country, customer, contract, date range and status.

## Command Center (/rental/admin)

**Sidebar group "Pro forma, deposits & advances":**

- **Pro Forma Invoices:** tabs Open, Awaiting approval, Drafts, Converted, Expired and All, with a badge for invoices waiting for approval. The form has the same fields, material, charges, deposit, VAT summary and status history as the desk. Submit is the approval. Actions on the form:
  - Submit for Approval;
  - Email to Customer, Mark as Sent, and Share on WhatsApp beside Print;
  - Customer Accepted;
  - Collect Advance and Collect Security Deposit;
  - Create Tax Invoice, which opens the drafted Sales Invoice.
- **Deposits & Advances:** every Rental Contract Payment, with tabs Deposits, Advances, Pending approval, Drafts and All, and a badge for pending approvals. The form shows the receipt, its balances and its Journal Entry, and has a Print button. Submit posts it.
- **The nine reports:** company filter defaulting to the Rental Settings company. Each row shows its own currency, with one total row per currency.

**Actions on other forms:**

- **Rental Contract:** Collect Deposit, Refund Deposit, Adjust Deposit, Collect Advance, Adjust Advance Against Invoice, Refund Advance and New Pro Forma Invoice. Each opens its receipt. A refund by a user who cannot approve it waits as Pending Approval. The form also lists its deposit and advance transactions and its pro forma invoices.
- **Hire Order:** New Pro Forma Invoice.
- **Sales Invoice:** Adjust Advance, shown when the invoice's contract has advance available. It suggests the smaller of the advance and the outstanding amount.

Amounts throughout the Command Center are shown with their currency's decimals: OMR 3, AED 2.
