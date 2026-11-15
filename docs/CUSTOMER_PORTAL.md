# thinkNXG Rental customer Command Center (2.3)

The customer portal at `/rental` is a complete customer application. Customers use it to follow their
rentals, raise requests, read their commercial documents and manage their account, without the Frappe
desk. It runs on the existing rental documents and ERPNext records. There is no extra database
structure apart from new request types and one Subject field.

## 1. Audit of what existed

| Area | Found | Outcome |
|---|---|---|
| Routes | Six server-rendered Jinja pages: `www/rental/index`, `contracts`, `contract`, `material`, `invoices` and `requests`. Plus the staff SPA at `/rental/admin`, served by `website_route_rules`. | All six pages are replaced by one SPA shell at `www/rental/index.html`. A route rule sends `/rental/<anything>` to it. `/rental/admin` keeps its own explicit rules. Old URLs are mapped by the client router. |
| Customer resolution | `portal.utils.get_portal_customers`: Portal Users of the Customer, or Contacts linked to it. Staff can preview with `?customer=`. | Reused for every call. Disabled customers are now excluded. |
| Data helpers | `portal.utils` builds contract lists, contract detail, material at site and invoices for the old pages. | The new API in `portal/customer.py` uses paged SQL with the customer filter on every query. `ledger.get_site_balance` and `get_contract_reservations` are reused. |
| Requests | `Rental Portal Request` with Hire Enquiry, Off-Hire Request and Extension Request. Staff actions: create hire order, create off-hire note, extend, reject. | Extended to 11 types and given a Subject field. Staff get a new **Complete** action. The existing make_* functions accept the new types where they apply. |
| Old API | `portal/api.py` had create_request, cancel_request, get_catalogue and get_contract_items. | Kept for compatibility, but now delegates to the new API so there is one set of checks. |
| ERPNext | Quotations come from the deal flow. Sales Invoices are rental, job and damage invoices. Payment Entries and the GL. Sales Orders are not used by the rental flow. | Quotations, Sales Invoices, Payment Entries and GL Entries are read directly. Sales Orders appear only when the customer has some. Delivery Notes are not used: deliveries are Hire Delivery Orders. |
| Notifications | None for customers. | Notification Logs per portal user, raised by document events and a daily job. |

## 2. Architecture

```
www/rental/index.html / index.py   shell page; guests go to /login; staff may preview
public/customer_portal/
  cp.css         design tokens and components (navy shell, blue action, teal "on site")
  cp_core.js     DOM helpers, API wrapper, formatting, badges, modal, popover, data table, charts
  cp_app.js      shell, sidebar, header, router, global search, notification panel
  cp_pages.js    dashboard, orders, active rentals, deliveries, returns, history, documents, staff preview
  cp_commerce.js quotations, sales orders, invoices, payments, account statement
  cp_requests.js requests (list, new, detail), communications, notifications, profile, contacts, settings
portal/customer.py                 the API (all whitelisted, all customer-scoped)
services/customer_notify.py        Notification Logs for portal users
```

The interface uses no framework and needs no build step. Charts are plain SVG. Fonts are the local
Barlow files of the staff Command Center.

## 3. API (`thinknxg_rental.portal.customer.*`)

- `boot`
- `dashboard`
- `orders` and `order`
- `active_rentals`
- `deliveries` and `delivery`
- `returns` and `return_note`
- `quotations` and `quotation`
- `sales_orders` and `sales_order`
- `invoices` and `invoice`
- `payments`
- `statement`
- `requests`, `request` and `request_options`
- `submit_request`, `cancel_request`, `add_request_message` and `upload_attachment` (POST)
- `download_attachment` and `download_pdf`
- `documents` and `history`
- `notifications` and `mark_notifications_read` (POST)
- `communications`
- `search`
- `profile` and `update_my_contact` (POST)
- `get_settings` and `save_settings` (POST)
- `preview_customers` (staff only)

Lists are paged on the server: 20 rows by default and at most 100. Each list returns its rows, the total
and the page count. Dashboard figures are SQL aggregates; no list is loaded just to count it.

## 4. Security

- **Who the customer is.** Every call starts from `frappe.session.user`. A `customer` argument only
  narrows the user's own set, so passing someone else's customer raises PermissionError. Guests are
  refused.
- **No desk permissions for portal users.** Portal users hold no permissions on the rental DocTypes.
  Lists are queries that always carry `customer in (session customers)`, or `party in (...)` for payments
  and GL entries.
- **Single documents.** Each one goes through `own_document`, which checks the customer or party and
  that the document is submitted.
- **Writes.** Raising and cancelling requests, messages and attachments are rechecked on the server:
  - ownership of the contract
  - the contract is live
  - quantities do not exceed what is on site
  - only catalogue items can be requested
  - requested dates are not in the past
  - a new return date is after the current one
  - file type and size
  - the request is open
- **PDFs.** Limited to an allow-list of document types, and only for the customer's own submitted
  documents.
- **Attachments.** Private files, served only through `download_attachment` after the ownership check.
- **Never sent.** Warehouses, own versus cross hire ownership, suppliers, costs, comments, other
  customers' data.
- **Staff previews.** Read-only: requests, messages and edits are refused.

## 5. Notifications

Notifications are raised for:

- a rental order confirmed
- material dispatched or returned
- returned material inspected
- an invoice or credit note issued
- a quotation issued
- a sales order confirmed
- a payment received
- a request received, or its status changing (with the team's reply)
- daily: rentals ending within 7 days, or ended yesterday (once each)

Read and unread state, the bell and e-mail (per the user's Notification Settings) are Frappe's own.

## 6. Tests

`tests/test_customer_portal.py` has 17 tests. Two customers each get their own portal user. They cover:

- boot and the guest refusal
- a customer argument that tries to widen access
- dashboard figures
- orders and order detail (by contract and by hire order number)
- active rentals and deliveries, including that no warehouse is exposed
- invoices, statement and documents
- PDF download for own documents only (a real PDF is generated)
- scoped search
- the return request flow: over-quantity, missing date, message, attachment (a bad file type is
  refused), download, notification, and every write refused for the other customer
- validation for each request type
- staff completing a request and the customer being notified
- staff preview read-only
- requests switched off
- profile, contact edit and settings
- notifications isolated, including that marking someone else's as read does nothing
- the expiry reminder sent once
- every portal URL, including the old ones, served by the application while `/rental/admin` stays the
  staff page

The full suite has 108 tests, all passing. In the browser I checked, with no console or API errors:

- all 18 pages on desktop, and the main pages on a phone
- a request submitted through the form, with an attachment and a message
- search, the notification panel and the staff preview

## 7. Upgrade

```
bench --site <site> migrate          # request types and Subject field; nothing to migrate in data
bench build --app thinknxg_rental
bench restart
```

## 8. Limits

- Rates and values shown are the contract's own. The standard catalogue rates appear in the request
  form only when *Show standard rates* is on.
- A request that becomes a document is completed by that document. Service requests are completed by
  the team with a reply.
- No live vehicle tracking: deliveries show the vehicle and driver recorded on the delivery order.
- The communication history shows Communications on the customer's requests and those linked to the
  customer record. It does not show internal comments.
