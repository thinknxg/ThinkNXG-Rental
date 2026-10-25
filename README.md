# thinkNXG Rental

Formwork and scaffolding rental for **Frappe / ERPNext v16**: Hire Order, Rental Contract, material
reservation, Delivery Order (material dispatch), material-at-site tracking, recurring rental billing,
partial returns / off-hire, return inspection, damage and loss settlement, and a cross-hire module that
runs on the standard ERPNext Purchase Order, Purchase Receipt, Purchase Return and Purchase Invoice.

## Install

```bash
cd ~/frappe-bench
bench get-app /path/to/thinknxg_rental        # or: bench get-app <git-url>
bench --site <site> install-app thinknxg_rental
bench --site <site> migrate
bench build --app thinknxg_rental && bench restart
```

Upgrading from an earlier version: replace the app folder, then `bench --site <site> migrate`, `bench build --app thinknxg_rental`, `bench restart`.

Requires `frappe` and `erpnext` version 16 (Python 3.14).

## First-time setup

1. **Rental Settings** - choose the company and click **Create Default Warehouses and Items**
   (the installer does this automatically when a default company already exists). It creates:
   - Warehouses: Rental Yard, Cross Hire Yard, Rental Under Inspection, Rental Repair, Rental Scrap,
     and the group Customer Sites.
   - Non-stock items: `RENTAL-CHARGES`, `CROSS-HIRE-CHARGES`, `RENTAL-DAMAGE-RECOVERY`,
     `RENTAL-LOSS-RECOVERY`, with UOMs Unit-Day / Unit-Week / Unit-Month.
   Set income / expense accounts on those four items as you would for any service item.
2. **Rental Item Profile** - one per rentable Item (rates, deposit, replacement value, repair charge).
   The ERPNext Item stays the only stock master; there is no separate "rental item".
3. **Rental Site** - one per customer site. Saving it creates two warehouses under Customer Sites:
   `<Site> (Own)` and `<Site> (Cross Hire)`.
4. Roles: **Rental Manager** (everything) and **Rental User** (create / submit, no cancel). These cover the
   rental documents only. Also give rental staff the standard ERPNext roles that let them pick customers,
   items, suppliers and warehouses in link fields: typically Sales User and Stock User, plus Purchase
   User for cross hire.
5. Put opening rental stock into the Rental Yard warehouse with a normal Stock Reconciliation.

## Two order types, one execution engine (v2.0)

| | Hire Order | Hire Order Contract |
|---|---|---|
| For | Rental of stock items by quantity | A job (Job Type Item) for a fixed number of days |
| Lines | Stock items | Job types, exploded into physical rental items |
| Priced by | Rate per item per day / week / month | Contract charge per job + excess charge per day / week / month |
| Duration controlled by | Deliveries and off-hire notes | Job Completion Report (JCR): erection and dismantle dates |
| Billed by | Rental Billing Schedule (material on hire) | JCR Billing Schedule (contract period, then month-end excess) |

Both create a **Rental Contract** (Rental Source Type + Rental Source), and from there share the same
Rental Material Reservation -> Hire Delivery Order -> Material at Site -> Off-Hire engine. Reservations,
deliveries and the ledger always carry stock items, never the non-stock job type.

**Job Type Item:** an Item with Maintain Stock off and *Is Job Type Item* ticked. Its *Job Type Rental
Items* table lists the stock items one job needs.

**Hire Order Contract:** one line per job type with number of jobs, contract days, contract
charge and excess charge. On first save the job types are exploded into the Physical Rental Items table,
which can be adjusted to the actual job.

**JCR:** raised against a Hire Order Contract job. The erection date starts the clock;
contract end = erection + contract days - 1. While the job stands, excess is billed at each month end;
**Record Dismantle** stops the clock and raises the final excess bill. Each period gets one JCR Billing
Schedule row, so a period cannot be invoiced twice. The contract charge is billed on erection or at
contract end, as chosen on the Hire Order Contract.

### Changes in 2.0.2

- **JCR with several job types.** Create > Job Completion Report on a Hire Order Contract now asks which job
  line was erected, and the JCR form fills that line's location, contract days and charges. Changing the
  Job Type on the form switches to that line; the same job type at two locations asks which one. Each
  JCR is linked to its job line, so every job type (and each location) has its own JCR and erection date.
  One job erected in stages can be split over several JCRs with part quantities (for example 0.5 + 0.5).
- **Source warehouse per reservation row.** Each row of a Rental Material Reservation has its own Source
  Warehouse with its own stock, reserved-for-others and available figures. A blank row takes the Default
  Source Warehouse when that can cover it, otherwise the rentable warehouse holding the most free stock.
  Deliveries take each item from the warehouse it was reserved in.
- **Workspace and sidebar refresh on upgrade.** Earlier releases shipped them with an unchanged timestamp,
  so Frappe kept the layout from the first installed version. This release re-imports both once.
- **Item form.** Job Type Rental Items has its own tab (2.0.1).

### Upgrading from 1.x

`bench migrate` renames the old "Hire Order Contract" DocType to "Rental Contract" (with its child
tables), renames the `hire_contract` link field to `rental_contract` everywhere including the `nxg_`
custom fields, fills Rental Source Type / Rental Source from the old Hire Order link, and moves the
series to `RC-`. Existing contracts keep their `HC-` numbers. Take a backup first. Any custom
scripts, reports or print formats of your own that mention the old DocType or field names need updating.

## Customer flow

| Step | Document | What it does in ERPNext |
|---|---|---|
| 1 | **Hire Order** | Commercial order; shows yard availability and shortfall per line. |
| 2 | **Rental Contract** | The rental agreement: rates, billing cycle, grace days, minimum hire, deposit. Items, quantities and rates can be revised after submit. |
| 3 | **Rental Material Reservation** | Soft reservation against yard stock. No stock posting; it reduces what other contracts may reserve or dispatch. Shortfall -> **Cross Hire Order**. |
| 4 | **Hire Delivery Order** | Stock Entry (Material Transfer) yard -> site warehouse, plus the at-site ledger. Lines are Own or Cross Hire. |
| 5 | **Hire Off-Hire Note** | Partial or full return. Stock Entry site -> inspection / yard; lost quantity is written off by Material Issue. Sets the last billable date. |
| 6 | **Rental Return Inspection** | Good -> yard, Repairable -> repair, Beyond Repair -> scrap. |
| 7 | **Rental Damage Settlement** | Repair / replacement / loss charges, liability %, salvage, transport -> Sales Invoice. |
| - | **Rental Billing Schedule** | One per contract per billing period -> Sales Invoice. Created by the daily scheduler or **Generate Billing** on the contract. |

### Billing rules

- Billing is in arrears and **movement based**: each day is billed for the quantity actually at site that
  day, read from the Rental Ownership Ledger. A partial return reduces the bill from the next day
  automatically; the schedule shows one line per item per constant-quantity stretch.
- Rate basis per item: Daily, Weekly (days / 7) or Monthly (days / 30, or days / days-in-month when
  *Monthly Rate Pro-rata Basis* is Actual Calendar Days).
- Billing cycle per contract: Daily, Weekly, Monthly (calendar month or anniversary) or Custom days.
- **Grace period**: returned within the grace days -> billed up to the off-hire date. Returned later ->
  billed up to the day before the material came back. (Off-hire 31-Oct, grace 2, returned 03-Nov ->
  01-Nov and 02-Nov are billable.) The return day itself is not billed.
- **Minimum hire days**: billing never stops before billing start + minimum hire days.
- A dispatch or off-hire cannot be dated inside a period that is already billed; cancel the later
  schedule / invoice first (or credit it) so billing and the ledger can never disagree.

## Cross-hire flow

| Rental document | ERPNext document | Behaviour |
|---|---|---|
| **Cross Hire Order** | **Purchase Order** (created on submit) | Per equipment item: one stock line at **zero rate** (custody) and one non-stock `CROSS-HIRE-CHARGES` line carrying the supplier rate x estimated hire period. |
| Cross Hire Receipt | **Purchase Receipt** (*Is Cross Hire Receipt*) | Charge lines are dropped; every equipment line is forced to rate 0 with *Allow Zero Valuation Rate*. Stock quantity goes up, stock value does not. |
| **Cross Hire Off-Hire Note** | **Purchase Return** (created on submit) | Quantity-only return against the original receipts, oldest first. Blocked while the material is still at a customer site. |
| Supplier hire bill | **Purchase Invoice** (**Supplier Hire Invoice** button) | Charge lines only, computed from the quantity in custody each day; linked to the PO charge lines up to the ordered amount, any overrun on unlinked lines. Never touches stock. |

Cross-hired equipment uses the **same Item** as own stock (Maintain Stock = Yes). Ownership is kept apart
by warehouse - Cross Hire Yard and `<Site> (Cross Hire)` only ever hold supplier-owned stock - and by the
Rental Ownership Ledger. That separation is what keeps your own stock's moving-average valuation from
being diluted by zero-value supplier stock.

*Receive At* on the Cross Hire Order chooses **Cross Hire Yard** or **Direct to Site**. For direct
delivery, still raise a Hire Delivery Order with Cross Hire lines: it posts no stock transfer (the
material is already in the site warehouse) but starts customer billing.

When everything is back, **Complete Order** closes the Cross Hire Order and its Purchase Order (the PO
never reaches 100 % received on its own because the charge lines are billed, not received).

## Customer portal

Server-rendered Frappe website pages inside this app (no separate frontend), at **/rental**:

| Page | Shows |
|---|---|
| `/rental` | Units on hire and sites, live contracts, unpaid invoices, requests in progress, latest deliveries and returns. |
| `/rental/contracts`, `/rental/contract?name=` | Contract terms, each item's contracted / delivered / returned / at-site quantity, movements, invoices, extensions. |
| `/rental/material` | Printable material-at-site list by site and contract. |
| `/rental/invoices` | Rental and damage invoices with billing period; each links to the standard ERPNext `/invoices/<name>` page. |
| `/rental/requests` | Raise and track requests: collect material (off-hire), hire more material, extend a hire. |

**Giving a customer access:** open the Customer, add their user under *Portal Users* (ERPNext gives the
user the Customer role). A user linked through a Contact also works for the rental pages, but the
standard invoice page needs the Portal Users entry. "Rental Portal" is added to the portal menu on
`bench migrate`.

**Requests** arrive as **Rental Portal Request** documents (workspace > Hire Operations):

- Hire Enquiry -> **Create Hire Order**
- Off-Hire Request -> **Create Off-Hire Note**, pre-filled with the requested quantities. The note's
  off-hire date is the day the customer raised the request, so the grace period runs from their notice.
- Extension Request -> **Extend Contract**
- **Reject** asks for a reason, which the customer sees. Anything typed in *Response to Customer* is shown.

Submitting the Hire Order or Off-Hire Note marks the request Completed.

**Staff preview:** Rental Manager / Rental User / System Manager can open `/rental?customer=<Customer ID>`
to see exactly what that customer sees.

**What customers never see:** other customers' data, supplier names, or whether material is own stock
or cross-hired. Portal users get no permissions on the rental DocTypes; every page reads through
queries filtered by the customers linked to the logged-in user.

Rental Settings > Customer Portal: switch requests on or off, show standard rates in the enquiry
catalogue, and set the help phone / email shown in the footer. The stylesheet is
`public/css/rental_portal.css` (scoped under `.rp`, logical properties so Arabic / RTL lays out
correctly). It loads the Barlow typefaces from Google Fonts and falls back to system fonts if blocked.

## Admin portal

A staff-only operations board at **/rental/admin**, built as website pages in this app. It is for
System Manager, Rental Manager and Rental User; anyone else gets a 403. It reads the same data as
the desk reports, so the numbers always agree with them.

| Page | Shows |
|---|---|
| `/rental/admin` | Units out and free, utilization, a work queue (customer requests, draft deliveries, inspections pending, settlements to invoice, billing due, hires past end date, cross hire overdue), today's vehicles in and out, items running short. |
| `/rental/admin/requests` | Customer portal requests, oldest first. **Start** marks one In Progress; **Handle in desk** opens it for conversion. |
| `/rental/admin/contracts` (More > Contract status) | Live / past end date / all contracts with search, delivered and at-site quantities, billed-up-to, and a link to the customer's own view. |
| `/rental/admin/sites` | All material at customer sites by customer, site and contract, with ownership, supplier and replacement value. Printable. |
| `/rental/admin/yard` | Every rentable item: yard, reserved, free, at sites (own / cross hire), inspection, repair, utilization. |
| `/rental/admin/billing` | Accrued unbilled rental per contract with **Bill now** / **Bill all due** (whole completed periods only, same as the nightly job), and unpaid rental invoices with days late. |
| `/rental/admin/suppliers` | Open cross hire by supplier and order: on hire, at customer site, idle, overdue days. |

### Data entry in the admin portal

The menu bar follows the order of work; the optional documents and the boards above sit under **More**.

| Menu | Document | Next step offered on the form |
|---|---|---|
| Leads | Lead | Create Quotation (makes the Customer from the Lead, as the desk does) |
| Quotations | Quotation (deal type decides the item columns, as in the desk) | Create Rental Site; once submitted, Create Hire Order / Create Hire Order Contract, or Create Sales Order for a Material Sale |
| Rental Sites | Rental Site (keeps the quotation it was made from) | Create Hire Order / Hire Order Contract from that quotation, with the site filled in |
| Hire Orders | Hire Order | Create Rental Contract; when there is a shortfall, Material Reservation and Cross Hire Order |
| Hire Order Contracts | Hire Order Contract (job types; physical items shown after save) | Create Rental Contract, Create Job Completion Report; on a shortfall, Material Reservation and Cross Hire Order |
| JCRs | Job Completion Report (erection / dismantle dates per job line) | Sales Invoice panel: this JCR alone, or ticked with other open JCRs of the customer on one invoice |
| Rental Contracts | Rental Contract | New Delivery Order, New Off-Hire Note |
| Delivery Orders | Hire Delivery Order (**Get items from contract**) | New Off-Hire Note |
| Off-Hire Notes | Hire Off-Hire Note (**Get items at site**) | Once submitted: Create Return Inspection (when returned items need inspecting), then Create Damage Settlement |
| More > Return Inspections | Rental Return Inspection (good / repairable / damaged per item) | Create Damage Settlement |
| More > Damage Settlements | Rental Damage Settlement | Create Sales Invoice (saves the draft invoice and opens it) |
| More > Material Reservations | Rental Material Reservation | Create Cross Hire Order (shortfall), New Delivery Order |
| More > Cross Hire Orders | Cross Hire Order | Receipts and supplier bills stay in the desk |
| More > Sales Orders | Sales Order (made from a submitted Material Sale quotation, or entered directly) | Delivery and billing stay in the desk |
| More > Sales Invoices | Sales Invoice (opened after invoicing JCRs, or entered directly) | |

Quotations, Sales Orders and Sales Invoices show Currency, a **Payment Term** link (custom field
`nxg_payment_term`: the payment schedule is one row for that term, and on a Sales Invoice the due date
follows it), the **Sales Taxes and Charges Template** and the **Sales Taxes and Charges** table (choosing
a template fills the table; rows can be edited). Quotations and Sales Orders also show the **Payment
Terms Template**; when both are filled, the template decides the schedule. Rental Contracts also take a
taxes template. Cost Center and Project show wherever the document has them; the app adds both to the
Quotation (ERPNext's Quotation has neither) and they carry on to the Sales Order, Hire Order and Hire
Order Contract. On Hire Orders, Hire Order Contracts and Rental Contracts, Project fills from the Rental
Site when left empty and can be changed. Deliveries, off-hires and cross hire take it from the Rental
Contract, so a new Rental
Contract, Delivery Order or Off-Hire Note opened from the previous step already has Project, Customer
Name and Rental Site filled; a Job Completion Report fills Customer Name from its Hire Order Contract.
Wherever Project is entered, **+ New Project** creates one without leaving the form. Cost Center is
entered on Hire Orders, Hire Order Contracts and Rental Contracts (a Hire Order's Cost Center is carried
to its Rental Contract).

Run `bench --site <site> migrate` after updating the app so the new custom fields (Payment Term; Project and
Cost Center on Quotation) and the field changes are applied.

Each menu lists drafts, submitted documents or all, with search. The form is
`/rental/admin/entry?type=<menu>&name=<document>`. Saving goes through the DocType itself
(`thinknxg_rental.portal.entry.save_entry`) with the user's own permissions, so a portal entry *is* the
ERPNext document: same naming series, validations, stock entries and ledger, and it shows straight away
in the desk. A menu only appears for users who can read that DocType. Cancelling and amending stay in
the desk (**Open in desk** on every form). Item tables use the full page width: columns share it by
weight, headings wrap between words, and a table with many columns scrolls sideways on small screens.
Which fields and columns each document shows is set in `ENTRY_TYPES` in `portal/entry.py`.

Everything else links through to the desk form. The workspace
has an **Admin Portal** shortcut, and the admin bar links back to the desk and to the customer portal.

## Reports

Material at Site, Rental Stock Position (availability, reservations, utilization %), Cross Hire Position
(with overdue days), Unbilled Rental (accrued to date), Damage and Loss Register, Rental Contract
Profitability (rental revenue + recoveries - cross hire cost).

## Verification

Version 2.0.0 was tested on a Frappe 16.36 / ERPNext 16.37 bench (Python 3.14, MariaDB 10.11), from the
server side, in three ways: a fresh install; an upgrade of a site holding v1.2.1 transactions; and the
flows as a user holding only the Rental User role. Covered: both order tracks end to end, cross hire,
rental billing, JCR billing (contract charge, month-end excess, final excess, re-invoicing after a
cancelled invoice), the daily jobs, cancellations, every report and every portal page. Quantities,
stock values and amounts matched hand calculations. The desk forms' client scripts and the portal's
browser-side form were not driven in a browser.

## Design notes and limits

- ERPNext remains the stock and accounting engine; this app adds the rental lifecycle and one ledger
  (`Rental Ownership Ledger`) with two positions: *At Site* and *Cross Hire Custody*.
- Custom fields on ERPNext documents are prefixed `nxg_` and are created on install / migrate.
- Sales Invoices, Purchase Orders, Purchase Returns and Stock Entries that the app raises on a user's
  behalf are written as Administrator, after checking the user's permission on the rental document.
  ERPNext otherwise refuses them for users who cannot read the party's ledger account.
- Job type contracts: one excess rate per job line; a dismantle date inside an already-invoiced month
  needs that invoice cancelled first; material quantities per job are set on the Hire Order Contract.
- Rental Settings holds one set of default warehouses, so the app is designed for one rental company
  per site. Rental Sites of another company still get their own site warehouses.
- Transactions are in company currency.
- Security deposit is recorded on the contract (required / received / reference); take the money with a
  normal Payment Entry.
- Serial and batch numbers can be entered on delivery, off-hire, inspection and cross hire off-hire
  lines and are passed to the stock documents. Bulk (non-serialised) items are the primary path; test
  serialised items in UAT before relying on them.
- Damage assessment is part of Rental Return Inspection; there is no separate assessment document.
- Lost cross-hired material is removed from custody when the customer off-hire is submitted. Book the
  supplier's claim for it with an ordinary Purchase Invoice.
- DocType names such as *Cross Hire Order* are generic. Do not install this app on a site that already
  has another app defining DocTypes with the same names.

## Uninstall

```bash
bench --site <site> uninstall-app thinknxg_rental
```

Removes the `nxg_` custom fields. Warehouses, items and stock transactions are left in place.
