# thinkNXG Rental Command Center

The staff application at **/rental/admin** (v2.1.0). This document covers how it is built, how it is
secured, how to install and deploy it, and how it was tested.

## 1. Principles

The Command Center is a new front end on the existing app, not a second system.

* **One source of truth.** No new DocTypes, tables or database. Quantities come from the Stock Ledger and
  the Rental Ownership Ledger through the existing reports (Rental Stock Position, Material at Site,
  Cross Hire Position, Unbilled Rental, Damage and Loss Register, Hire Contract Profitability).
* **No second engine.** Saving, submitting, mapping one document to the next and document actions go
  through `thinknxg_rental.portal.entry` (`save_entry`, `submit_entry`, `prepare_mapped`, `run_action`),
  which saves the real DocType with its own validations. Billing runs
  `thinknxg_rental.services.billing.generate_billing` and `services.jcr_billing.make_combined_invoice`,
  unchanged. Cancelling calls the document's own `cancel()`.
* **Permissions on the server.** Every API method checks the staff roles first, then the DocType or
  document permission the action needs. The sidebar hides what a user cannot open, but hiding is never
  the only check.
* **No invented numbers.** Every figure on screen is read from the database when the page loads. Empty
  data shows as zero or an empty state, never a sample.

## 2. Architecture

```
Browser (single-page app, vanilla JS, no build step)
  public/command_center/cc_core.js    helpers: DOM, fetch with CSRF, formatting, dialogs, toasts
  public/command_center/cc_charts.js  SVG line / column / stacked / horizontal bar charts, stock tube
  public/command_center/cc_list.js    universal list: server paging, sorting, filters, columns, export
  public/command_center/cc_form.js    universal document form (portal/entry.py specs) + timeline,
                                      attachments, comments, assignment, cancel, print
  public/command_center/cc_pages.js   dashboard, boards, request inbox, reports, customers, users
  public/command_center/cc_app.js     shell: sidebar, top bar, router, search, Quick Create
  public/command_center/cc.css        design system (tokens, components, responsive, print)
        │  fetch /api/method/... with X-Frappe-CSRF-Token
        ▼
Frappe (website page + whitelisted methods)
  www/rental/admin/index.{html,py}    the shell page; staff only; inlines the boot data and CSRF token
  hooks.website_route_rules           /rental/admin/<path:app_path> -> rental/admin
  command_center/registry.py          the map: sidebar groups, list views, reports, Quick Create, badges
  command_center/api.py               whitelisted endpoints (below)
  command_center/dashboard.py         KPIs, work queue, charts, today/recent (per-user 60 s cache)
        │
        ▼
Existing app (unchanged business logic)
  portal/entry.py   ENTRY_TYPES form specs, save_entry / prepare_mapped / run_action
  portal/admin.py   boards: stock rows, site groups, billing, cross hire, request inbox
  services/*.py     billing, JCR billing, ledgers
  report/*          the six rental reports
```

### Routes

| Path | Page |
|---|---|
| `/rental/admin`, `/dashboard` | Dashboard (`?period=today|week|month|quarter|year|custom&from=&to=`) |
| `/notifications`, `/tasks` | Notification Log and ToDo of the user |
| `/requests`, `/requests/<name>` | Customer request inbox, request form |
| `/sales/leads`, `/sales/quotations`, `/sites`, `/hire-orders`, `/hire-contracts`, `/contracts`, `/jcr`, `/deliveries`, `/off-hire`, `/reservations`, `/inspections`, `/settlements`, `/cross-hire`, `/cross-hire-receipts`, `/supplier-off-hire`, `/invoices` | Lists; `/<list>/<name>` opens the form, `/<list>/new` a new document |
| `/supplier-bills`, `/billing-schedules`, `/jcr-billing`, `/item-profiles`, `/items`, `/warehouses` | Lists of other DocTypes (rows open in the desk) |
| `/customers`, `/customers/<name>` | Customer list and 360 view |
| `/inventory` (`?category=`, `?item=`) | Rental Yard, item movement history |
| `/material-at-site`, `/supplier-position`, `/billing`, `/outstanding`, `/utilization` | Boards |
| `/reports/<key>` | Report runner (filters in the address) |
| `/settings`, `/users` | Rental Settings summary, Users & Roles (System Manager) |
| `/doc/<entry>/<name>` | Form of an entry type with no list of its own (Sales Order, Delivery Note) |
| `/entry?type=&name=`, `/entries?type=`, `/yard`, `/suppliers`, `/board` | Old admin portal addresses, redirected |

The list views, sidebar and reports are configured in `command_center/registry.py` (`VIEWS`, `NAV`,
`REPORTS`, `REPORT_FILTERS`, `QUICK_CREATE`, `BADGES`). Which fields a form shows is still set in
`ENTRY_TYPES` in `portal/entry.py`, so the desk menu, the tests and the Command Center share one definition.

### API (`thinknxg_rental.command_center.api`)

| Method | Does | Checks |
|---|---|---|
| `boot` | user, rental roles, sidebar, routes, Quick Create, badges, currency | staff |
| `dashboard(period, from_date, to_date)` | KPIs, work queue, charts, today, recent | staff; each block also needs read on its DocType |
| `list_view(view, search, tab, filters, sort, page, page_size)` | one page of a list and its count | staff + read; only whitelisted filters (status, docstatus, party, date range) and sortable columns |
| `export_list(...)` | CSV, up to 5,000 rows | staff + export |
| `form(entry, name, make, source, args, prefill)` | form boot + timeline, attachments, assignees | staff + read / create (in `get_form_boot`) |
| `add_comment`, `cancel_document`, `assign`, `close_task` | timeline comment, cancel, Assign To, close own ToDo | staff + read / cancel / write; POST only |
| `search(q)` | documents by number or name across 15 DocTypes | staff + read per DocType (`frappe.get_list`) |
| `notifications`, `mark_notifications_read`, `my_tasks` | the user's own records | staff |
| `inventory`, `material_at_site`, `supplier_position`, `billing_center`, `outstanding`, `utilization` | boards | staff + read |
| `bill_contract(rental_contract)` | `generate_billing(only_complete=1)` | staff + submit on Rental Billing Schedule + write on the contract; POST only |
| `requests`, `staff_users`, `customers`, `customer_overview` | inbox and customers | staff + read |
| `report_meta(view)` | the report's filters | staff + `Report.is_permitted()`; the report runs through `frappe.desk.query_report.run` |
| `users_roles` | staff users and roles | System Manager |
| `settings_summary` | Rental Settings read-only | staff + read |

### Dashboard figures

| KPI | Source |
|---|---|
| Total rental units, Available, Reserved, Under inspection, Under repair | Rental Stock Position (same as the desk report) |
| On hire, Active cross-hire units | Rental Ownership Ledger (At Site, Cross Hire Custody) via Rental Stock Position |
| Utilization % | on hire / rental units |
| Change since period start | the same ledgers summed to the day before the period |
| Active contracts, Past end date | Rental Contract status and end date |
| Unbilled rental | Unbilled Rental report to yesterday + pending JCR Billing Schedules (the billing page shows the same total) |
| Outstanding rental invoices | submitted Sales Invoices with a rental contract, JCR or damage settlement |

Charts: utilization and own vs cross-hired at site (ledger history per day / week / month), revenue and
revenue by customer (Sales Invoices), billing (Rental Billing Schedules and JCR periods), cross-hire cost
(Purchase Invoices with a Cross Hire Order), availability by category and most-rented items (stock
position), contract profitability (Hire Contract Profitability report). Every chart has a table view.
The dashboard is cached for 60 seconds per user and per period (`thinknxg_rental:cc_dashboard:<user>:...`),
never shared between users.

## 3. Security

* Page: guests are redirected to `/login?redirect-to=...`; signed-in users without a rental role get 403.
* API: `check_staff()` first in every method, then DocType / document permissions through `frappe.get_list`,
  `has_permission`, `check_permission` or the existing engine.
* Writes are POST-only (`@frappe.whitelist(methods=["POST"])` or the engine's own methods) and carry the
  session's CSRF token (`X-Frappe-CSRF-Token`, inlined in the page). A POST without it is refused (400).
* List filters accept plain values for known fields only; the browser cannot pass operators, other fields,
  or SQL. Sorting is limited to the view's columns and dates.
* Comments are escaped then sanitised; timeline content is sanitised HTML.
* The browser keeps only per-user conveniences in localStorage (sidebar state, page size, hidden columns,
  recent and favourite documents). Nothing permission-sensitive is cached across users.

## 4. Install and deploy

```bash
cd ~/frappe-bench
bench get-app https://github.com/thinknxg/ThinkNXG-Rental      # or update the existing app
bench --site <site> migrate
bench build --app thinknxg_rental
bench --site <site> clear-cache
bench restart
```

No migration patches are needed: there are no new DocTypes or fields. The route rule and the new page
are picked up by `clear-cache`. The Command Center's scripts and styles are plain files under
`public/command_center` and need no bundling; `bench build` only links them into `sites/assets`.

Roles: give staff **Rental User** (enter and submit) or **Rental Manager** (also cancel, settings). They
also need the ERPNext roles for the standard documents they work with (Sales User for Leads, Quotations
and Customers; Accounts User for Sales Invoices and outstanding; Stock User for Items and Warehouses;
Purchase User for supplier bills). Pages a user cannot read are not in their sidebar.

Fonts (Barlow, Barlow Condensed, SIL Open Font License) are served from the app; icons are Frappe's
Lucide sprite. The page makes no requests to other sites.

## 5. Testing

Automated (`bench --site <site> run-tests --app thinknxg_rental`): 27 tests, all passing.

* `tests/test_command_center.py` (14): guests and customers refused on 13 endpoints and the page; Users
  & Roles for System Manager only; sidebar only lists readable pages; unreadable lists refused on the
  server; list counts, tabs, ignored unknown filters and sort fallback; export; dashboard KPIs equal the
  Rental Stock Position totals and live contract count; unbilled KPI equals the billing page; per-user
  dashboard cache; form, search, comment escaping; cancel needs Cancel permission; assignment into My
  Tasks and closing only your own task; every route, column, report and icon exists.
* `tests/test_admin_portal.py` (10): the full document flows through the same entry engine (material
  hire, contract hire with JCRs, material sale, cross hire, customer requests, permissions, JCR per job
  line, quotation calculations, UOM, rotation columns).
* `tests/test_desk_menu.py` (3): the desk bar links to the Command Center pages.

Manual, in Chromium at 1440 × 900 and 390 × 844 (phone), as Rental User, Rental Manager and System
Manager:

* every sidebar page loads; pages without permission show "You do not have access" and are absent from
  the sidebar; an unknown address shows "Page not found";
* old addresses (`/rental/admin/entry?type=rental-contract&name=...`) open the new form;
* global search (Ctrl K) finds contracts and opens them in the app; Quick Create lists only creatable types;
* a Rental Site created and saved in the form, then commented on; Extend Contract opens its dialog;
* navigation keeps the page loaded (no reload) and Back returns to the previous page;
* direct HTTP: customer and guest get 403 on the API and on the page; POST without CSRF gets 400;
* customer portal `/rental`, `/rental/contracts`, `/rental/requests`, `/rental/material` still return 200
  for a customer, and staff preview `/rental?customer=...` still works.

## 6. Notes and limits

* Interface strings written in the browser are English; labels from the server (DocType labels, field
  labels, statuses) are translated as in the desk.
* "Receive payment" opens the invoice in the desk (Create > Payment): payment entry has no portal form.
* Supplier hire bills, billing schedules, items and warehouses list in the Command Center and open in
  the desk, as they have no portal form.
* Bill all due bills each due contract in turn through the billing engine; a contract the engine refuses
  shows its own message and the rest continue.
* Found while testing on a plain ERPNext site: the Job Type DocType fetches `tax_code`, `is_zero_rated`
  and `is_exempt` from Item. Those fields come from an e-invoicing app, not ERPNext, so on a site without
  it saving a Job Type fails with "Unknown column 'tax_code'". Unchanged in this release; worth either
  adding those fields as custom fields or removing the fetches.
