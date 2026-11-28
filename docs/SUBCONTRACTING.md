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

---

# Version 2.10: agreements, execution, portal and Command Center

Architecture, gap matrix and plan: `docs/SUBCONTRACTING_PORTAL_PLAN.md`.

## New and changed documents

| Document | What it does |
|---|---|
| Supplier (more fields) | Business classification, specializations, service areas, operating locations, relationship manager, contact person, **Compliance Documents** (type, number, issue / expiry, attachment, status, verified). Approval status moves only through `approve_subcontractor` (Subcontracting Manager); approval is refused while a compliance document has expired. |
| Subcontract Agreement (+ Rate) | Rate contract: type (unit rate, fixed price, labour, equipment hire, material supply, time based, project based), validity, value ceiling, retention / advance %, guarantee, tax template, payment terms, rate card, terms. Draft → Pending Approval → Active (approve) → Expired (daily job) / Terminated. |
| Subcontract Work Order | Hire Order Contract is now **optional** (project or customer work). Links an agreement: the rate card fills empty rates and the agreement's terms are defaults; rates are stored on the rows, so later agreement changes never alter an approved order. Fixed-value agreements cap the total of their work orders. New: priority, work description, project manager, site engineer, coordinator, actual start / completion (set automatically). New statuses: Sent to Subcontractor, Accepted / Rejected by Subcontractor, On Hold (with reason, Resume returns to the earlier status). |
| Subcontract Daily Progress | Quantity done per work item, labour, equipment, delay and blockers, expected completion, photos. From the portal or staff; Site Engineer / Manager approves (submit) or returns it. Approved quantity is *reported* work (`reported_qty`), never billable by itself. |
| Subcontract Work Progress (inspection) | Now the inspection: portal *Request inspection* creates it with the submitted quantity; staff schedule it (inspector, date), record accepted / rejected / rework, checklist, quality remarks and corrective action, and submit. Result: Accepted, Partially Accepted, Rejected or Rework Required. Only accepted quantity becomes billable. |
| Subcontract Material Request | Subcontractor asks for company material. Store Manager / Manager approves or rejects; *Issue Material* makes the existing Material Allocation, which is capped at the approved, not-yet-issued quantity and keeps Issued / Partially Issued up to date. The subcontractor confirms receipt (or reports a shortage) in the portal. |
| Subcontract Variation | Extra work, quantity variation, rate revision, time extension, delay / shortage / other claims, additional material. Approval (Manager) writes to the work order: new additional rows, new quantity (Hire Order Contract balance re-checked), new rate for the not-yet-invoiced quantity, new completion date, or one accepted claim row at the approved amount (item from Subcontracting Settings). Logged on the work order; cancelling reverses it while nothing built on it was accepted or invoiced. |
| Subcontractor Invoice Submission | The subcontractor's invoice (portal or staff): invoice no. and date, lines limited to accepted − invoiced − quantity on other open submissions, duplicate invoice numbers refused (submissions and Purchase Invoices of the same supplier and company). Verifying creates the existing Settlement and its Purchase Invoice, with the supplier's bill no. and date. Final Bill needs a Verified work order. |
| Subcontract Message | Staff ↔ subcontractor messages per work order, and announcements. Desk comments stay internal. |
| Subcontractor Portal Access | One portal login per contact: supplier, email, name, access level (Operational or Commercial), enabled / suspension reason, invitation, last access. Creates the Website User with role *Subcontractor Portal User*. |
| Subcontracting Settings | Compliance and agreement alert days, claim item, portal on/off, contact details, announcement, scorecard weights. |

## Portal (`/subcontractor`)

Dashboard (work orders, acceptance, progress, materials, inspections; for Commercial contacts approved value, invoices, outstanding and overdue payments; action list, schedule, progress bars, announcements, expiring documents, recent payments), Work orders (accept / reject with start date, scope, PDF, tabs for progress, inspections, materials, variations, invoices, files, messages), Progress reports, Inspections, Materials (held, issued with receipt confirmation, requests, own-supplied), Variations and claims, Invoices, Payments (with payment advice PDF), Messages, Company and documents (upload renewed documents).

Security: every call resolves the subcontractor from the session (`services/subcontract_portal.current`) through an enabled access row of an approved (or suspended: read-only) subcontractor; every document is checked against that supplier (`own`) and answers "not found" otherwise; work orders appear only once sent; Operational contacts get no rates, amounts, invoices or payments (removed on the server); internal notes and remarks are never returned; POST endpoints are rate limited; uploads are private files on the contact's own records, by extension and size; downloads are checked against ownership.

## Command Center (`/rental/admin/subcontracting`)

Sidebar group **Subcontracting**: Overview (14 KPIs, each opening its filtered list; action centre with approve / reject / send / return / verify / hold buttons that call the documents' own methods; status, financial, monthly value, planned vs actual, progress by project, top subcontractors, projects, delayed and rejected work; all reports), Subcontractors (list with compliance and score; 360 with business information, scorecard, compliance, agreements, work orders, inspections, variations, material, invoices, portal users, messages and a GL-based account statement), Work Orders (filters: status tabs incl. delayed / on schedule, search, project, subcontractor, site, manager, dates; 360 with overview and cost monitor, scope, progress, materials, inspections, variations, invoices, payments, communication and a document timeline), lists of every new document, Performance & Comparison, Portal Users. Subcontracting Manager, Executive and Site Engineer can open the Command Center; each item still checks the DocType permission.

## Reports (6 new, 19 in all)

Subcontractor Register, Subcontract Variation Report, Subcontractor Account Statement (GL), Subcontract Cost Monitor (original, variations, revised, completed, certified, invoiced, paid, retention, advance, outstanding, utilisation, forecast), Delayed Subcontract Work Orders, Subcontractor Invoice Register.

## Roles and permissions

| Action | Who (server-checked) |
|---|---|
| Approve / suspend subcontractor | Subcontracting Manager |
| Agreement: send / approve / terminate | Executive, Manager / Manager / Manager |
| Work order: send, start | Manager, Executive / Manager, Site Engineer; hold / resume: Manager |
| Daily progress approve / return | Site Engineer, Manager |
| Inspection schedule / certify | Site Engineer, Manager |
| Material request approve / reject / issue | Store Manager, Manager |
| Variation approve / reject | Manager |
| Invoice verify (Running / Final) / reject | Accounts User, Accounts Manager, Manager / Accounts Manager |
| Portal (Operational / Commercial) | own records only; Commercial also rates, invoices, payments, commercial variations |

## APIs

- `thinknxg_rental.portal.subcontractor.*`: boot, dashboard, work_orders, work_order, respond_work_order, work_order_pdf, progress_reports, submit_progress, inspections, request_inspection, materials, request_options, create_material_request, confirm_receipt, variations, submit_variation, billable, invoices, submit_invoice, payments, payment_advice, messages, post_message, mark_messages_read, notifications, mark_notifications_read, profile, add_compliance_document, upload, download.
- `thinknxg_rental.command_center.subcontracting.*`: dashboard, act, work_orders, work_order, wo_action, send_message, subcontractors, subcontractor, compare.
- Workflow methods on each controller (`approve`, `reject`, `submit_for_review`, `return_for_correction`, `start_inspection`, `make_material_allocation`, `submit_variation`, `start_review`, `verify`, `send_to_subcontractor`, `put_on_hold`, `resume`, `invite`, `terminate`) and `services.subcontracting.approve_subcontractor`.

## Upgrade

```
git pull                                     # branch subcontracting-portal
bench --site <site> migrate                  # new doctypes, Supplier fields, role, settings defaults, patch v2_10
bench build --app thinknxg_rental            # only if assets are not symlinked
bench --site <site> run-tests --module thinknxg_rental.tests.test_subcontracting_portal
```

Patch `v2_10.subcontracting_inspection_status` only writes the new inspection result on existing Work Progress records from their accepted / rejected quantities; no submitted quantity or ledger changes. Existing work orders keep their status; approved ones are not visible in the portal until *Send to Subcontractor*.

Then: set the claim item and contacts in Subcontracting Settings, add compliance documents to subcontractors, create Subcontractor Portal Access rows and send invitations.

## Known limits (v2.10)

- Subcontractor-supplied material is recorded on work items; delivery advice, goods receipt and quality inspection of supplier material use ERPNext's Purchase Receipt and Quality Inspection, not a portal flow.
- Retention release is still a manual Journal / Payment Entry; the cost monitor and reports show what is held.
- Document versions are Frappe's file attachments and version history; there is no separate document repository.
- Notifications use Notification Log and email; no SMS or push.
- The portal and Command Center screens were checked in a headless browser on desktop and phone sizes with demo data; no load test and no multi-currency test.
