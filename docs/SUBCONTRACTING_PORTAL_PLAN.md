# Subcontracting v2: audit, architecture and plan

Branch `subcontracting-portal`, from `main` at 0aaa6cc (Subcontracting v2.9.0, PR #31 and #35, is merged).

## 1. Audit: what exists today

### Application shape
| Area | Where | How it works |
|---|---|---|
| Desk DocTypes | `thinknxg_rental/thinknxg_rental/doctype` (rental), `thinknxg_rental/subcontracting/doctype` (subcontracting) | Frappe controllers, business rules in `services/*.py` |
| Staff Command Center | `/rental/admin` → `www/rental/admin`, `command_center/{api,registry,dashboard}.py`, `public/command_center/cc_*.js` | Vanilla-JS single-page app. `registry.py` is the map: `NAV` groups, `VIEWS` (list views over real DocTypes), `REPORTS`, `BADGES`, `QUICK_CREATE`. A view of kind `entry` opens the shared form (`portal/entry.py ENTRY_TYPES`), kind `doctype` lists and opens in the desk. Custom page kinds are functions on `cc.pages` |
| Customer portal | `/rental` → `www/rental`, `portal/customer.py`, `public/customer_portal/cp_*.js` | Vanilla-JS SPA. The user → Customer mapping comes from Customer `Portal User` rows and Contact links. Every API filters by the resolved customers; portal users get no desk permission |
| Public site | `/hire` → `www/hire`, `website/api.py` (with `rate_limit`) | |
| Routing | `hooks.website_route_rules` | `/rental/admin/<path>`, `/hire/<path>`, `/rental/<path>` |

### Existing Subcontracting module (v2.9.0)
| DocType | Kind | Role today |
|---|---|---|
| Supplier + custom fields | master | Is Subcontractor, Provides (Labour/Equipment/Both), Category, Approved Work Categories, Approval Status (Pending/Approved/Suspended/Blacklisted), Default Retention %, Rating, Terms |
| Subcontract Work Order (+ Subcontract Work Item) | submittable | The commercial order. **Hire Order Contract is mandatory.** Status Draft → Pending Approval → Approved → Work In Progress → Partially Completed → Completed → Pending Final Verification → Verified → Closed / Cancelled, moved only by whitelisted, role-checked methods. Allocation against HOC job-line quantity under a row lock. Additional-work rows. Advance %, retention %, tax template, PO link |
| Subcontract Work Progress (+ Progress Item) | submittable | Site-engineer verification: accepted / rejected quantity per work item. Drives `accepted_qty`, so it is today's inspection and certification step |
| Subcontract Completion Report | submittable | Completion certification → Pending Final Verification |
| Subcontract Material Allocation / Material Return (+ items) | submittable | Company material to Subcontractor Custody warehouse (Stock Entry + Rental Ownership Ledger), return reconciliation (installed, good, damaged, missing, recovery) |
| Subcontract Settlement (+ item) | submittable | Partial / Final. Accepted-not-invoiced quantity → one Purchase Invoice with retention, advance, penalty, recovery deductions. Blocks manual PIs against a work order |
| Purchase Order, Purchase Invoice, Payment Entry | ERPNext | `subcontract_work_order` link fields; advance Payment Entry |
| 13 script reports, workspace, desk sidebar | | |
| Not present | | Agreements / rate contracts, daily progress, inspection checklist / rework, material requests, variations and claims, portal invoice submission, subcontractor portal, any Command Center screen, compliance documents, scorecard |

Cross hire (Cross Hire Order, receipts, supplier off-hire, supplier hire bills) is a separate module. It is linked from work items (`equipment_ownership = Cross Hired`) and is not changed by this work.

## 2. Existing vs proposed

| Capability | Today | Proposed | How |
|---|---|---|---|
| Subcontractor master | Supplier custom fields | Extend | More Supplier fields: classification, service areas, specializations, relationship manager, contact; **Compliance Documents** child table with expiry; approval through a whitelisted method (Manager) |
| Agreement / rate contract | Attach field on work order | New | **Subcontract Agreement** (submittable) with rate card, terms, retention / advance, validity. Work orders link to it and copy rates (the snapshot) |
| Work order | Mandatory HOC | Extend | HOC optional (project / customer work orders); priority, coordinators, actual dates; new statuses *Sent to Subcontractor*, *Accepted by Subcontractor*, *Rejected by Subcontractor*, *On Hold* |
| Daily progress | none | New | **Subcontract Daily Progress**: reported quantity, labour, equipment, delays, blockers, photos; submitted from the portal, approved by staff |
| Inspection / certification | Work Progress (accepted / rejected) | Extend | Work Progress gains inspection fields: inspector, location, checklist, rework qty, corrective action, inspection status, request from portal |
| Material requests | none | New | **Subcontract Material Request** → approved → Material Allocation (existing) prefilled. Receipt confirmation from the portal on the allocation |
| Supplier invoices | Settlement → PI | Extend | **Subcontractor Invoice Submission** (portal or staff): supplier bill no., lines within billable quantity, duplicate check → verified → creates the Settlement and Purchase Invoice |
| Variations and claims | none | New | **Subcontract Variation** (submittable): extra work, quantity, rate, time extension, delay claim, material, other. Approval writes back to the work order (additional row, qty, rate, completion date) with an audit trail |
| Payments | Payment Entry | Reuse | Read-only in the portal |
| Scorecard | Supplier rating field | New | **Subcontracting Settings** (weights) + computed score |
| Command Center | none | New group | Subcontracting navigation, dashboard, action centre, work order 360, subcontractor 360 |
| Portal | none | New | `/subcontractor` SPA, **Subcontractor Portal Access** (user ↔ supplier, access level, suspension, invitation) |

Not duplicated: ERPNext Supplier, Purchase Order / Invoice, Payment Entry, Stock Entry, Quality Inspection, accounting.

## 3. DocType relationships

```
Supplier (is_subcontractor) ─┬─ Subcontractor Compliance Document (child)
                             ├─ Subcontractor Portal Access ── User
                             └─ Subcontract Agreement ── Agreement Rate (child)
                                        │
Hire Order Contract (optional) ── Subcontract Work Order ── Work Item (child, rate snapshot)
                                        ├─ Purchase Order
                                        ├─ Daily Progress (portal)          → reported qty
                                        ├─ Work Progress / Inspection        → accepted / rejected / rework
                                        ├─ Completion Report
                                        ├─ Material Request (portal) → Material Allocation → Stock Entry
                                        │                             Material Return  → Stock Entry
                                        ├─ Variation (portal or staff) → work item rows / dates / rates
                                        ├─ Invoice Submission (portal) → Settlement → Purchase Invoice
                                        └─ Payment Entry (advance, payment)
```

## 4. Workflows

Work order: `Draft → Pending Approval → Approved → Sent to Subcontractor → Accepted by Subcontractor → Work In Progress → Partially Completed → Completed → Pending Final Verification → Verified → Closed`. Side states: `Rejected by Subcontractor` (back to staff, can be re-sent), `On Hold` (staff, reversible), `Cancelled`.

Daily progress: `Draft → Submitted → Approved | Returned`.

Inspection (Work Progress): portal *Request Inspection* creates a draft with the reported quantities (`Inspection Requested`) → staff record accepted, rejected and rework quantities and submit → `Accepted | Partially Accepted | Rejected | Rework Required`. Only accepted quantity is billable.

Material request: `Draft → Submitted → Approved → Partially Issued → Issued`, or `Rejected`. Issue happens through Material Allocation.

Invoice submission: `Submitted → Verified (Settlement + Purchase Invoice created) | Rejected`. Lines are capped at accepted − invoiced − quantity on other open submissions.

Variation: `Draft → Submitted → Approved (submit) | Rejected`. On approval: extra work adds a work item marked additional; quantity variation raises the line quantity (HOC availability rechecked); rate revision changes the rate of the not-yet-invoiced quantity; time extension moves the expected completion date. Each change is logged on the work order.

## 5. Permission matrix

| Action | Exec | Manager | Site Eng. | Store | Accounts | Portal (Operational) | Portal (Commercial) |
|---|---|---|---|---|---|---|---|
| Approve subcontractor | | ✓ | | | | | |
| Agreement create / approve | create | ✓ | | | | view own | view own |
| Work order create / approve / send | create | ✓ | | | | | |
| Accept / reject work order | | | | | | ✓ | ✓ |
| See rates and amounts | ✓ | ✓ | ✓ | | ✓ | | ✓ |
| Daily progress submit / approve | | approve | approve | | | submit | submit |
| Inspection | | ✓ | ✓ | | | request | request |
| Material request / approve / issue | | approve | | issue | | request, confirm receipt | same |
| Invoice submission / verify | | verify | | | verify | | submit |
| Variation submit / approve | submit | approve | | | | submit | submit |
| Payments | | | | | ✓ | | view |

Portal rules: every endpoint resolves the supplier from the session user through Subcontractor Portal Access (enabled, supplier approved); every document is re-checked against that supplier; internal remarks and other suppliers' data never leave the server; POST endpoints are rate limited; uploads go through Frappe's file validation and are attached privately to a document of that supplier.

## 6. Command Center

New sidebar group **Subcontracting**: Overview (dashboard + action centre), Subcontractors, Agreements, Work Orders, Daily Progress, Material Requests, Material Issues, Material Returns, Inspections, Completion Reports, Supplier Invoices (submissions), Settlements, Payments, Variations & Claims, Portal Access, Settings, Reports. Lists use the existing `VIEWS` mechanism; documents open in the desk. New page kinds: `sc-dashboard`, `sc-work-order` (tabbed 360), `sc-subcontractor` (360 + account statement).

## 7. Portal sitemap (`/subcontractor`)

Dashboard · Work Orders (list, detail, accept / reject, PDF) · Progress (daily reports, submit) · Inspections (request, results) · Materials (requests, issues, confirm receipt) · Invoices (submit, status) · Payments · Variations & Claims · Messages (work-order threads) · Documents (compliance, expiry) · Profile.

## 8. APIs

`thinknxg_rental.portal.subcontractor.*` (portal, ownership-checked), `thinknxg_rental.command_center.subcontracting.*` (staff dashboard, 360, action centre), workflow methods on each DocType controller.

## 9. Stages

1. Masters: Supplier fields and compliance, Agreement, Settings, Portal Access, work order changes.
2. Execution: Daily Progress, inspection fields, Material Request, Variation.
3. Commercial: Invoice Submission → Settlement, scorecard, cost monitor.
4. Command Center: navigation, dashboard, 360 pages.
5. Portal.
6. Reports, tests, patch, documentation.
