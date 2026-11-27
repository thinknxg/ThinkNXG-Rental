# Subcontracting (Hire Order Contracts)

Module **Subcontracting** inside `thinknxg_rental`. It lets a Hire Order Contract's job lines be handed to approved subcontractors, tracks the company material they hold, the work they complete, and settles them through standard ERPNext documents. Customer billing is untouched.

## Documents

| Document | Purpose |
|---|---|
| Supplier (custom fields) | Subcontractor Master: Is Subcontractor, Provides (Labour / Equipment / Both), Category, Approved Work Categories, Approval Status, Default Retention %, Performance Rating, Terms. No second party record. |
| Subcontract Work Order (+ Work Item) | The agreement. Submittable; submitting = approval. Rows are Labour or Equipment, optionally Additional work. |
| Subcontract Work Progress | Site-engineer verified accepted / rejected quantity per work item. |
| Subcontract Completion Report | Completion certification; sends the work order to Pending Final Verification. |
| Subcontract Material Allocation | Company-owned material issued to the subcontractor. |
| Subcontract Material Return | Reconciles issued material: installed, returned good, damaged, missing. |
| Subcontract Settlement | Turns accepted, not-yet-invoiced quantity into one Purchase Invoice with deductions. |
| Purchase Order / Purchase Invoice / Payment Entry | Standard documents, each with a `Subcontract Work Order` link. |

## Quantity rule

`Available = Contract Quantity of the job line − quantity on approved (submitted) work orders`

- Draft and Pending Approval work orders do not consume quantity.
- The rule is enforced on save and again on approval, with the Hire Order Contract row locked (`select … for update`), so two simultaneous approvals cannot both take the last quantity: the second waits, then fails.
- Cancelling releases the quantity. Amending creates a new draft that must be approved again.
- **Full** allocation must take the whole remaining balance of every job line; **Partial** can take any part. Several subcontractors may share one line.
- Rows marked **Additional work** are costed but never count against the contract quantity.
- A Hire Order Contract with live work orders cannot be cancelled.

## Status and approvals

`Draft → Pending Approval → Approved → Work In Progress → Partially Completed → Completed → Pending Final Verification → Verified → Closed`, and `Cancelled`.

Status is read-only and moves only through role-checked server methods or document events:

| Step | Who | How |
|---|---|---|
| Send for approval, return to draft | Subcontracting Executive / Manager | `submit_for_approval`, `reject` |
| Work order approval | Subcontracting Manager | `approve` (the only way to submit) |
| Progress verification | Site Engineer / Manager | submit a Work Progress |
| Material issue | Store Manager / Manager | submit a Material Allocation |
| Completion certification | Site Engineer / Manager | submit a Completion Report (needs status Completed) |
| Final verification, close | Subcontracting Manager | `verify_completion` (needs a certified report and no material left with the subcontractor), `close` |
| Settlement | Accounts User / Manager (Final: Accounts Manager) | submit a Settlement |

Editing the status field or calling `submit` directly does not bypass any of this.

## Material and equipment

- Company material: Material Allocation posts one Stock Entry (Material Transfer) from the issue warehouse to the **Subcontractor Custody** warehouse (created per company) and writes Rental Ownership Ledger rows with the new position type **Subcontractor Custody**. Existing ledger queries filter by position type, so rental billing and cross hire reports are unaffected. Issue is checked against `get_available_qty` (stock minus other reservations), so material promised elsewhere cannot be issued twice.
- Return: `Issued = Installed + Returned + Damaged + Missing + Outstanding`. Good goes to the chosen yard warehouse, damaged to the Rental Settings inspection warehouse, missing to the lost warehouse (Material Transfer); installed is a Material Issue (it is consumed in the works and leaves stock at its valuation cost, booked to the Stock Entry's default difference account). Damaged and missing units are charged at the row's recovery rate; the total flows into the next settlement as damage / loss recovery.
- Subcontractor-supplied equipment is only a work-item row (`Subcontractor Supplied`); it never creates stock. `Cross Hired` equipment links to the existing Cross Hire Order, so cross hire logic is not duplicated. `Company Owned (issued)` equipment is issued through Material Allocation like any material.

## Settlement and accounting

A Settlement picks accepted quantity not yet invoiced (`accepted − invoiced`, enforced under lock), values it at the work-order rate and creates **one submitted Purchase Invoice**:

- items: the job-type items; taxes: the work order's tax template, if any;
- deduction rows (category Total, Deduct, Actual): retention held → `Subcontractor Retention Payable`; penalties, material recovery and other deductions → `Subcontract Cost Recoveries`. Both accounts are created per company on first use;
- advances: advance Payment Entries tagged to the work order (Create → Advance Payment, limited to the agreed advance) are allocated with ERPNext's own advance mechanism, only those of this work order;
- Payment is an ordinary Payment Entry against the invoice; tagging is automatic.

A manual Purchase Invoice against a work order is refused, and a settlement can never invoice more than the accepted quantity, so certified quantity cannot be invoiced twice. Cancelling a Settlement cancels its invoice (blocked while payments exist) and returns the quantity.

Stock, purchase and payment ledgers are ERPNext's. The module keeps no parallel ledger; reports read the documents.

## Profitability

`Net Profit = Customer Revenue − Subcontract Cost − Other Direct Costs`

- Customer Revenue: `total_billed_amount` of the contract's Rental Contracts, i.e. what the existing billing recorded. The module does not change billing, and a customer can be billed with no subcontractor invoice.
- Subcontract Cost: settled value minus penalties and recoveries (retention is a payment delay, not a saving). Labour, equipment and additional-work cost are shown separately.
- Other Direct Costs: cross hire supplier invoices of the same contract.

Shown on the Hire Order Contract (Subcontracting → Cost Summary) and in report *HOC Subcontract Profitability*.

## Hire Order Contract integration

On a submitted contract: Create → Subcontract Work Order (prefilled with the lines that still have balance), Subcontracting menu (work orders, material allocation, progress, completion reports, cost summary) and dashboard indicators (subcontracted vs contract quantity, work orders, subcontractors, completion %).

## Reports (13)

Subcontractor Wise Work Orders · HOC Wise Subcontracting · Outstanding Subcontractor Payments · Subcontractor Payments · Subcontract Material Issue and Return · Subcontract Work Progress Report · Pending Completion Approval · Subcontract Cost Analysis · Subcontractor Performance · HOC Subcontract Profitability · Subcontract Labour Cost · Subcontract Equipment Cost · Subcontract Retention and Advance Outstanding.

## Roles

Subcontracting Manager, Subcontracting Executive, Site Engineer, Store Manager, Project Manager (created on migrate if missing); Purchase Manager, Accounts Manager, Accounts User (ERPNext). Manager has full access; others as the table above, view access elsewhere.

## Installation

```
bench get-app <repo> --branch <branch>      # or pull the branch into the existing app
bench --site <site> migrate                 # creates roles, custom fields, doctypes, reports, workspace
bench --site <site> run-tests --module thinknxg_rental.tests.test_subcontracting
bench --site <site> run-tests --module thinknxg_rental.tests.test_subcontracting_flow
```

Then mark approved subcontractors (Supplier → Is Subcontractor, Approval Status Approved), assign the roles, and make sure Rental Settings has the yard, inspection and lost warehouses.

## Known limits

- Retention release is not automated: the retention sits in `Subcontractor Retention Payable`; release it with a Journal Entry or Payment Entry. The retention report shows what is held.
- The Purchase Order is the commercial order; invoice lines are not linked to PO lines, so the PO's billed % does not move. Invoicing and duplicate control run through Settlement.
- Material and settlement amounts use the company currency; multi-currency subcontractors are not covered by the tests.
- "Installed" material is posted as a Material Issue at valuation cost; if you prefer to charge it to the customer contract instead, change the target in `subcontract_material_return.py`.
- The concurrency guarantee rests on the database row lock and was tested sequentially (second approval after the first fails); no multi-process race test is included.
