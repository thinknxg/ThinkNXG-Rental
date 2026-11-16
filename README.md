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

### Changes in 2.4.3 - blank reservation, delivery and off-hire forms

- Rental Material Reservation, Hire Delivery Order, Hire Off-Hire Note, Cross Hire Order and Rental
  Return Inspection could open with their section headings but no fields. Their setup called a helper
  (`thinknxg_rental.rental_warehouses`) defined only in a separately loaded desk script
  (`rental_flow.js`); when that file was missing, late or an old cached copy, setup failed with
  "thinknxg_rental is not defined" and the desk stopped drawing the form. The helper now ships with
  each of these forms (`doctype_js`), so they work whatever the desk scripts' state.

### Changes in 2.4.2 - desk forms: reservation, delivery order, off-hire note

- Item tables on Rental Material Reservation, Hire Delivery Order and Hire Off-Hire Note fit the form:
  at most 10 grid units with short headings (Qty, Available, Reserved, Shortfall; At Site, Returned,
  Lost, Excess, Return To). Further figures stay in the row editor and can be added with the grid's
  column settings. Cross Hire Order appears only on cross hire rows.
- On laptop screens (992-1365 px) thinkNXG Rental forms use the full width: the form's sidebar (assign,
  attachments, tags, share) moves below the form instead of squeezing it to about 450-700 px.
- Hire Off-Hire Item keeps its quantities together (Excess next to Lost) and its warehouses together.
- Vehicle, driver, transporter, gate pass and remarks stay visible and editable after submit.
- The floating thinkNXG Rental menu steps aside while scrolling down, so it never covers fields.

### Changes in 2.4.1 - website review

- Draft hire quotations from the website now carry the hire days and rate basis, so they price the
  enquired period. Fixed account-page links (profile, log out, sign-up), escaped visitor text in staff
  notifications, refused malformed requests, unsafe links and private images, rate-limited the guest API.
- One money format on pages and in the API; translatable script texts; right-to-left pages; inline icon
  sprite instead of the 750 KB one; AA-contrast buttons for any colour; a website 404 page; tablet and
  placeholder layout fixes. See the review table in [docs/PUBLIC_WEBSITE.md](docs/PUBLIC_WEBSITE.md).

### Changes in 2.4 - public rental website

- **A public website at /hire** (optionally the site's home page): home page, catalogue with categories
  from ERPNext Item Groups, search, filters, sort, grid and list views, product pages with photos,
  specifications, datasheets, rates and availability, services, industries, about, contact, an enquiry
  basket and an account page linking to the customer portal.
- **Rates and availability come from the existing logic** (rate cards and Rental Item Profile; free own
  stock net of reservations, shown as a band). Prices and availability can each be switched off.
- **Enquiries join the sales flow**: a Rental Website Enquiry, a Lead (or the logged-in customer) and
  draft Material Hire / Material Sale quotations for the team to price and send.
- **Website builder in the desk** (Rental Website Settings): five templates, colours, typography, header,
  hero, card and catalogue layouts, home page sections with order and visibility, cards, links, contact
  and SEO fields. SEO: canonical URLs, Open Graph, JSON-LD (Organization, Product, BreadcrumbList),
  /rental_sitemap.xml and robots.txt.
- **Customer portal**: an Enquiries page and online acceptance of open quotations.
- Details, configuration and limits: [docs/PUBLIC_WEBSITE.md](docs/PUBLIC_WEBSITE.md).

### Changes in 2.3 - customer Command Center

- **/rental is now a full customer application**: dashboard, rental orders, active rentals, deliveries,
  returns, quotations, sales orders, invoices, payments, account statement, documents, history, profile,
  contacts, notifications and settings, with global search, on desktop and phone.
- **Eleven request types** with attachments and a message thread; staff complete service requests with a
  reply. Customers are notified of confirmations, deliveries, returns, invoices, payments, request updates
  and rentals ending soon.
- The old server-rendered portal pages are replaced; their URLs open the new pages.

### Changes in 2.2 - multi-location warehouses

- **Several own rental warehouses and cross hire warehouses**, at any locations, in two tables of Rental
  Settings (warehouse, location, default, active). The existing yards become the defaults on
  `bench migrate`; a single-yard setup works as before.
- **Reservations per warehouse**: a row is placed and split over the warehouses with free stock; submits
  are locked so two reservations never take the same stock.
- **Deliveries from several warehouses**, held to each warehouse's reservation and ownership category.
- **Returns to any warehouse**, split per row (e.g. 60 to Calicut, 40 to Kochi), with Delivered From,
  Return Warehouse and Good Stock Returns To kept apart; inspection sends good stock to the chosen warehouse.
- **Transfers between locations** with ordinary Stock Entries, checked for ownership and reservations.
- New **Rental Inventory** report; Stock Position, Material at Site and Cross Hire Position by warehouse
  and location. Full details: [docs/MULTI_LOCATION_WAREHOUSES.md](docs/MULTI_LOCATION_WAREHOUSES.md).

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

## Customer Command Center (customer portal)

A single-page application at **/rental** for the customer's own people, served by this app (no extra
frontend framework, no build step): `www/rental/index.html` is the shell, `public/customer_portal/` the
interface, `portal/customer.py` the API. Every path under `/rental` opens it, except `/rental/admin`
(the staff Command Center). Old links (`/rental/contracts`, `/rental/contract?name=`, `/rental/material`,
`/rental/invoices`, `/rental/requests`) open the matching new page.

| Area | Pages |
|---|---|
| Overview | Dashboard: units on site by site, 8 KPIs (each opens its list), rental operations (active rentals, upcoming deliveries, scheduled pickups, overdue returns, pending extensions), deliveries and returns per month, recent orders, upcoming activity (deliveries, pickups, return dates, inspections, payments due), recent notifications. |
| Rental operations | My Rental Orders (contracts and hire orders awaiting contract; search, status, site and date filters; detail with lines, ordered / delivered / returned / on site / to deliver, rates, timeline built only from real documents, deliveries, returns, invoices, requests, PDFs), Active Rentals (per contract and item, ending soon / overdue / partially returned, extend or return from a line), Rental Deliveries, Material Returns (returns made and pickups requested), Extension Requests, Additional Material. |
| Commercial | Quotations, Sales Orders (shown only when the customer has any), Invoices (outstanding and overdue totals), Payments (with the invoices each was applied to), Account Statement (opening balance, every debit and credit, running and closing balance, CSV and print). |
| Customer services | Service Requests, Complaints, Support Tickets, Communication History. |
| Resources | Rental Documents, Delivery Documents, Invoices & Receipts (PDF of each), Rental History. |
| Account | Company Profile (company, tax ID, addresses, authorised sites), Contacts (edit your own name, job title and phone), Notifications, Settings (e-mail notifications, password). |

Header: breadcrumb, global search (Ctrl / Cmd + K) across the customer's orders, deliveries, returns,
invoices, quotations, sales orders, requests and payments, notification bell, help menu (support request,
rental team e-mail and phone), company switcher for a login linked to several customers, account menu.
Desktop has a collapsible sidebar; tablets and phones get a drawer and record cards instead of wide tables.

**Giving a customer access:** open the Customer and add their user under *Portal Users* (or link a
Contact that has the user). A login linked to several customers can switch between them or see all.
Disabled customers no longer open the portal.

**Requests** (Rental Portal Request) now cover: Additional Material, Rental Extension, Material Return,
Material Pickup, Delivery Rescheduling, Material Replacement, Damaged Material, Missing Material, New Hire
Enquiry, Complaint and General Support. The form asks only what each type needs and the server checks
everything again (the contract is the customer's and live, quantities fit what is on site, dates are not
in the past, the new return date is later). Customers can attach photos or documents (private files, up
to 10 per request, 10 MB each) and message the team on the request; staff replies appear in the same
thread. In the staff Command Center:

- Hire Enquiry, Additional Material -> **Create Hire Order**
- Material Return, Material Pickup -> **Create Off-Hire Note**
- Extension -> **Extend Contract**
- Reschedule, replacement, damage, missing, complaint, support (and additional material) -> **Complete**
  with a reply the customer sees
- **Reject** with a reason

**Notifications:** Frappe Notification Logs for every portal user of the customer, so read / unread, the
bell and e-mail (per user) work as usual. Raised when an order is confirmed, material is dispatched or
returned, returned material is inspected, an invoice or quotation is issued, a payment is received, a
request is received or changes status, and daily for rentals that end within 7 days or have just ended
(once each).

**Security:** every API call resolves the customers from the session user (Portal Users and linked
Contacts); a customer passed by the browser only narrows that set. Portal users get no desk permissions
on the rental DocTypes: every read is a query filtered by those customers, and single documents are
checked for ownership and submission before anything is returned, printed or attached. Never sent:
other customers' data, warehouses, own / cross hire ownership, suppliers, costs, internal comments.

**Staff preview:** Rental Manager / Rental User / System Manager open `/rental`, pick a customer, and see
exactly what that customer sees, read-only.

Rental Settings > Customer Portal: switch requests on or off, show standard rates in the request catalogue,
and set the help phone / e-mail. PDFs use each document's default print format; on a server without
Chromium set `chromium_path` in `common_site_config.json` (Frappe's own setting). Full details:
[docs/CUSTOMER_PORTAL.md](docs/CUSTOMER_PORTAL.md).

## Items, rental profiles, rates and damage charges

**Rental section on the Item form** (shown only with Maintain Stock):

* **Rental Item Profile**: switch it on and the profile's own fields appear on the Item (category,
  rates, deposit, replacement value and the three damage charges). Saving the Item saves the profile in
  the same transaction; switching it off later disables the profile (it is kept for its history). The
  values live only in Rental Item Profile, which can still be edited on its own form.

**Rates** in Material Hire quotations: when an item is picked, its row gets the Daily, Weekly and
Monthly Rate (customer rate card, then general rate card, then the Rental Item Profile, as for hire
orders), the profile's Default Rate Basis, and the Rate of that basis. All of them can be changed on the
row: switching the Rate Basis takes that basis's rate, changing the rate of the row's basis moves Rate,
and a Rate typed by hand becomes that basis's rate. Nothing is written back to the profile or rate card.
Changing the quotation's Default Rate Basis still sets every row's basis (and so its Rate).

**Damage charges** on Rental Item Profile: Standard Repair Charge per Unit (existing), **Lost Charge per
Unit** and **Beyond Repair / Damage Charge per Unit** (new; never negative). Each Quotation row takes
them as defaults when the item is picked (desk and Command Center), converted into the quotation's
currency. They can be changed per row, are saved on the row, and are never written back to the profile;
a saved quotation keeps its values even when the profile changes later. Items without a profile get zero.
The Damage Settlement made from an off-hire still charges replacement value and repair charge as before.

## Command Center (staff portal)

**/rental/admin** is the staff application: a single-page Command Center for System Manager, Rental
Manager and Rental User (anyone else gets a 403, guests are sent to the login page). It has no data of
its own. Every figure comes from the same reports, ledgers and DocTypes as the desk, and every save,
submit, mapping and action goes through the DocType or the app's existing whitelisted methods with the
user's own permissions. Full details: [docs/COMMAND_CENTER.md](docs/COMMAND_CENTER.md).

| Area | Pages |
|---|---|
| Main | Dashboard (12 live KPIs, itemised work queue, charts, today's deliveries and returns, recent documents; Today / Week / Month / Quarter / Year / Custom), Notifications, My Tasks |
| Sales & enquiries | Leads, Quotations, Customers (360 view), Rental Sites, Customer Requests (inbox with Take, Handle, Assign, Reject, Create Hire Order / Off-Hire Note, Apply extension) |
| Rental operations | Hire Orders, Hire Order Contracts, Rental Contracts, JCRs, Delivery Orders, Off-Hire Notes |
| Inventory & yard | Material Reservations, Rental Yard (tube per item, movement history), Material at Customer Sites, Return Inspections, Damage Settlements, Rental Stock Position, Inventory by Warehouse |
| Cross hire | Cross Hire Orders, Cross Hire Receipts, Supplier Off-Hire, Supplier Hire Bills, Supplier Position |
| Billing & finance | Rental Billing (Bill now / Bill all due through the billing engine), Unbilled Rental, Sales Invoices, Outstanding Payments (aged by customer), Damage & Loss Recovery |
| Reports & analytics | Rental Utilization, the six rental reports with their filters and CSV export, Billing schedules |
| System | Rental Settings, Rental Item Profiles, Items, Warehouses, Users & Roles (System Manager), Open the desk |

The sidebar shows only what the user may read, and the server checks again on every call. Global search
(Ctrl K), Quick Create (n), breadcrumbs, favourites and recent documents, toasts, confirmations and
keyboard shortcuts work across the app; lists page, sort, filter and export on the server. Old portal
addresses (`/rental/admin/entry?type=...`, `/yard`, `/suppliers`, `/entries?type=...`) open the matching
Command Center page.

### Data entry in the Command Center

Each document opens in the shared form at `/rental/admin/<list>/<name>` (`/new` for a new one). The next steps it offers:

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
| Return Inspections | Rental Return Inspection (good / repairable / damaged per item) | Create Damage Settlement |
| Damage Settlements | Rental Damage Settlement | Create Sales Invoice (saves the draft invoice and opens it) |
| Material Reservations | Rental Material Reservation | Create Cross Hire Order (shortfall), New Delivery Order |
| Cross Hire Orders | Cross Hire Order | Receipts and supplier bills stay in the desk |
| Sales Orders | Sales Order (made from a submitted Material Sale quotation, or entered directly) | Delivery and billing stay in the desk |
| Sales Invoices | Sales Invoice (opened after invoicing JCRs, or entered directly) | |

Quotations, Sales Orders and Sales Invoices show Currency, the **Payment Terms Template**, the **Sales
Taxes and Charges Template** and the **Sales Taxes and Charges** table (choosing a template fills the
table; rows can be edited); a Sales Order made from a quotation keeps its Payment Terms Template. Rental Contracts also take a
taxes template. Cost Center and Project show wherever the document has them; the app adds both to the
Quotation (ERPNext's Quotation has neither) and they carry on to the Sales Order, Hire Order and Hire
Order Contract. On Hire Orders, Hire Order Contracts and Rental Contracts, Project fills from the Rental
Site when left empty and can be changed. Deliveries, off-hires and cross hire take it from the Rental
Contract, so a new Rental
Contract, Delivery Order or Off-Hire Note opened from the previous step already has Project, Customer
Name and Rental Site filled; a Job Completion Report fills Customer Name from its Hire Order Contract.
Wherever Project is entered, **+ New Project** creates one without leaving the form.

**Project Title** (Lead and Quotation) holds the customer's project name before a Project exists. It and
the Lead's Project go to the Quotation made from the Lead. When a Rental Site is saved from a quotation
(desk or Command Center), its Project is the site's own, else the quotation's, else the lead's; if none of
them has one, the Project named like the Project Title is used (same company, this customer or none), or
created. The site, the quotation and the lead then get that Project **only where their Project is empty**:
an existing Project link is never replaced, and changing the Project Title later does not relink anything.
Users who may not create Projects get none made for them. See `services/project_link.py`. Cost Center is
entered on Hire Orders, Hire Order Contracts and Rental Contracts (a Hire Order's Cost Center is carried
to its Rental Contract).

Run `bench --site <site> migrate` after updating the app so the new custom fields (Project and Cost Center on
Quotation) and the field changes are applied, and the earlier Payment Term field is removed.

Quotations, Hire Orders, Hire Order Contracts, JCRs, Sales Invoices and Cross Hire Orders have a **Print**
button once saved. It opens ERPNext's print view with the document's default print format and starts
printing; Get PDF is on the same page. A Cross Hire Order also has **Print Purchase Order** for the
Purchase Order it made on submit.

Each list pages, sorts, filters and exports on the server. Saving goes through the DocType itself
(`thinknxg_rental.portal.entry.save_entry`) with the user's own permissions, so a portal entry *is* the
ERPNext document: same naming series, validations, stock entries and ledger, and it shows straight away
in the desk. A menu only appears for users who can read that DocType. Users with Cancel permission can
cancel a submitted document from the form's **More** menu; amending stays in the desk (**Open in desk** on
every form). Item tables use the full page width: columns share it by
weight, headings wrap between words, and a table with many columns scrolls sideways on small screens.
Which fields and columns each document shows is set in `ENTRY_TYPES` in `portal/entry.py`.

Everything else links through to the desk form. The desk workspace bar has an **Admin Portal** group that
opens the Command Center pages.

## Reports

Material at Site (with the warehouse it was delivered from), Rental Stock Position (availability,
reservations, utilization %; by location or warehouse), Rental Inventory (per location, warehouse,
ownership and stock status), Cross Hire Position (with overdue days and cross hire warehouse), Unbilled Rental (accrued to date), Damage and Loss Register, Rental Contract
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
- Rental Settings holds the rental warehouses of one company (any number of own rental and cross hire
  warehouses, at any locations), so the app is designed for one rental company per site. Rental Sites of
  another company still get their own site warehouses.
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
