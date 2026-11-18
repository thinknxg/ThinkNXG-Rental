# Public rental website (v2.4.1)

A public, search-engine-readable rental website at **/hire**, built inside the app on the existing
thinkNXG ERP data and rental logic. It can also be the site's home page.

| Page | Address |
| --- | --- |
| Home (sections set in the desk) | `/hire` |
| Catalogue | `/hire/equipment` |
| Category (a thinkNXG ERP Item Group) | `/hire/equipment/<category>` |
| Product | `/hire/equipment/<category>/<product>` |
| Services, Industries, About, Contact | `/hire/services`, `/hire/industries`, `/hire/about`, `/hire/contact` |
| Enquiry basket | `/hire/basket` |
| Account (log in, register, links to the customer portal) | `/hire/account` |
| Sitemap | `/rental_sitemap.xml` |

## 1. Architecture assessment

What was already in the app and is reused:

- **Items and categories**: thinkNXG ERP Item and Item Group. A product is an Item with a **Rental Item
  Profile**, so the profile carries the website fields. Categories are the item groups of published
  items, with their parent groups, so the catalogue follows the item master. Nothing is hard-coded.
- **Rates**: `services/utils.get_rental_rate` (customer rate card, then general rate card, then the
  Rental Item Profile) and `estimate_amount` (the same formula as hire orders). The website calls these
  and nothing else. A logged-in portal customer sees their own rate card.
- **Availability**: free own stock as the Command Center computes it (`services/inventory.bins` and
  `reserved`: per active own rental warehouse, Bin minus open reservations). The website shows a band
  ("In stock", "Limited availability", "Available on request", or for a quantity "Available from stock",
  "Part available now, the rest on request"), never the figure.
- **Sales flow**: Lead (with `deal_type` and `project_title`) then Quotation (`deal_type`,
  `nxg_required_from`, `nxg_expected_return_date`) then Rental Site then Hire Order. Website enquiries
  enter this flow as a Lead and **draft** quotations; staff price and send them as today.
- **Customer portal** (`/rental`): log-in, quotations, orders, requests, invoices, documents and history
  are already there. The website links to it and two features were added to it (section 4).

Why there is one new transaction doctype: a Lead has no item lines, a Rental Portal Request needs an
existing customer, and a Quotation needs prices staff have not set yet. **Rental Website Enquiry** keeps
what the visitor asked for (items, dates, site, delivery needs) and links to the Lead or Customer and the
quotations made from it.

Why `/hire`: thinkNXG already serves `/about`, `/contact` and `/login`; a prefix avoids clashing with them
and with the customer portal at `/rental`. Ticking **Use as home page** makes `/` open the website.

## 2. New and modified files

New:

```
thinknxg_rental/website/theme.py            templates (design tokens + layout choices), colour helpers
thinknxg_rental/website/catalogue.py        categories, product queries, rates, availability bands, estimates
thinknxg_rental/website/api.py              guest API: estimate, basket, submit_enquiry, contact
thinknxg_rental/website/icons.py            the small inline icon sprite each page carries
thinknxg_rental/website/renderer.py         page renderer: the website's own 404 page, answered with HTTP 404
thinknxg_rental/www/hire/index.py|.html     the page dispatcher (all /hire pages) and SEO
thinknxg_rental/www/rental_sitemap.py|.xml  sitemap
thinknxg_rental/templates/rental_website/   base.html, macros.html (sections, cards, forms), pages/*.html
thinknxg_rental/public/rental_website/      rw.css (design system), rw.js (basket, estimates, forms)
thinknxg_rental/patches/v2_4/seed_rental_website.py, clear_section_hints.py
thinknxg_rental/tests/test_public_website.py
doctypes: Rental Website Settings, Rental Website Section, Rental Website Card, Rental Website Link,
          Rental Website Category, Rental Website Enquiry, Rental Website Enquiry Item,
          Rental Item Specification, Rental Item Image
```

Modified:

```
hooks.py                        /hire route rule, page renderer; cache clearing on Item, Rental Item Profile, Item Group
services/setup.py               Quotation fields nxg_website_enquiry, nxg_customer_accepted_on/_by; seed on install
services/item_rental.py         website fields stay off the Item form's rental panel
rental_item_profile.json        Website section (show on website, featured, for sale, URL slug, short
                                description, material, datasheet, usage, specifications, gallery)
portal/customer.py              enquiries(), accept_quotation(), quotation() returns can_accept / accepted_on
public/customer_portal/*.js     Enquiries page, Accept quotation button, status colours
patches.txt                     the seed patch
```

## 3. Doctypes

- **Rental Website Settings** (single). General: on/off, home page, name, tagline, logo, show prices,
  show availability, "limited" threshold, purchase enquiries, who is notified. Design: template, three
  colours, typography, header style, hero layout, card style, catalogue view, corners. Home: the
  sections table. Content: service / industry / process / advantage / testimonial / statistic cards,
  category descriptions and images, about text, mission, vision. Navigation and contact: header and
  footer links, footer text, phone, WhatsApp, e-mail, address, hours, map. SEO: title, description,
  social image, organisation name.
- **Rental Website Section** (child): type (Hero, Search, Categories, Featured Products, Category
  Products, Services, Process, Industries, Advantages, Testimonials, Statistics, Banner, Call to Action,
  About, Contact, Text), show, title, subtitle, item group, number of products, background tone, content,
  image and two buttons. Row order is page order.
- **Rental Website Card / Link / Category** (child): see above.
- **Rental Website Enquiry**: `RWE-YYYY-#####`; type, status (New, In Review, Quoted, Closed, Spam), contact
  details, customer or lead, user, project location, dates, delivery requirements, items with the
  server's estimate, message, the hire and purchase quotations, staff notes.
- **Rental Item Specification / Image** (child of Rental Item Profile): extra specification rows and photos.

## 4. Workflows

**Enquiry.** The visitor adds items (with quantity, and hire or buy where the item is for sale) to the
enquiry basket, which lives in their browser. The basket page asks the server for current names,
availability and estimates. On sending, the server validates everything again, recomputes the estimate,
and saves a Rental Website Enquiry. It then, with system rights:

1. links the logged-in customer, or finds a Lead by e-mail, or creates one (deal type Material Hire or
   Material Sale, request type Product Enquiry, project title from the project location);
2. creates draft Quotations: one for hire lines (Material Hire, with the hire period) and one for
   purchase lines (Material Sale), priced by the existing quotation rate logic;
3. notifies users with the chosen role and, when an outgoing e-mail account exists, e-mails a
   confirmation. The visitor sees the reference on screen.

Staff open the enquiry, Lead or quotation from the enquiry form (Open menu), or create the quotation later
(Create > Create quotation) for enquiries entered by hand.

**Contact form** creates an enquiry of the chosen type (General, Long-term Contract, Project Rental,
Purchase, Business Account) and the Lead, without quotations.

**Quotation acceptance.** In the customer portal, a submitted, open, unexpired quotation of the
customer shows **Accept quotation**. Acceptance records who and when on the quotation
(`nxg_customer_accepted_by`, `nxg_customer_accepted_on`), adds a comment and notifies the owner and the
notify role. Staff then make the order as usual.

**Customer portal.** New **Enquiries** page lists the website enquiries of the login and its customers,
with their items and, once submitted, their quotations.

## 5. API (`thinknxg_rental.website.api`, guests allowed)

| Method | Use |
| --- | --- |
| `estimate(item_code, qty, required_from, expected_return)` | days, chargeable days, rate and amount with their formatted `rate_display` / `amount_display` (if prices are shown), availability band |
| `basket(items, required_from, expected_return)` | the basket as the server sees it |
| `submit_enquiry(data)` POST | creates the enquiry, returns the reference |
| `contact(data)` POST | contact form |

Customer portal (`thinknxg_rental.portal.customer`, logged in): `enquiries()`, `accept_quotation(name)` POST.

Security: prices and stock are computed on the server only; the browser's figures are ignored. Only
published items (Show on Website, not disabled) can be read, estimated or enquired about. Submissions
are POST only, limited to 10 per hour per IP address, carry a hidden honeypot field, and are validated
field by field (e-mail, phone, dates not in the past and at most ten years, quantity 1 to 100,000, at
most 40 lines, purchase only for items for sale). No internal document is exposed: quotations appear to
customers only when submitted and addressed to them; datasheets only if they are public files. Customer
data stays isolated through the portal's existing `ctx()` checks.

## 6. Configuration and customisation (desk)

Open **Rental Website Settings** (search bar). After installing, it is pre-filled with sections, cards
and links; prices follow the portal's "show rates" setting.

1. **Publish products**: on each Rental Item Profile, tick *Show on Website* in the Website section; add
   a short description, material, usage, specifications, photos (the Item image comes first) and a
   datasheet (attach it as a public file). *Featured* puts it in Popular products; *Available for
   purchase* allows buy enquiries. The URL slug is made from the item name and can be changed.
2. **Categories** are your Item Groups. To add a description or an image, or hide a group, add a row
   under Content > Categories.
3. **Template**: choose one of Industrial Corporate, Modern Minimal, Premium Construction, Enterprise
   Rental, Equipment Catalogue Focus. Each sets colours, typography, header, hero layout, card style,
   catalogue layout, corners and a section order. Any of these can be overridden in the Design tab. To
   apply a template's section order, save, then **Design > Load template sections** (text you wrote for a
   kept section type stays).
4. **Home page**: in the Home tab, reorder rows by dragging, untick *Show* to hide a section, and edit
   titles, text, images, buttons and background tone. *Category Products* rows need an item group.
   Sections with nothing real to show (no products, no cards) are left out automatically.
5. **Testimonials and statistics** are empty on purpose: add Testimonial or Statistic cards only with real
   quotes and figures, and the sections appear.
6. **About** text, mission and vision, **contact details**, **header and footer links**, **SEO** fields
   are in their tabs. Links must start with `/`, `https://`, `mailto:` or `tel:`.
7. **Use as home page** makes `/` open the website. Turning the website off hides it from visitors
   (website managers still see it with a preview banner) and gives the home page back.

Saving the settings also adds the sitemap to robots.txt (and, if robots.txt is empty, keeps `/rental/`
and `/app/` out of search engines).

## 7. Install, migrate, build

```
bench get-app / git pull                # this repository
bench --site <site> migrate             # doctypes, custom fields, seed patch
bench build --app thinknxg_rental       # optional: the website's CSS/JS are plain files under public/
bench --site <site> clear-cache
```

No external services or CDNs are used: fonts and icons are served from the app and thinkNXG.

## 8. Production-readiness review (2.4.1)

| Area | Finding | Change |
| --- | --- | --- |
| Quotation workflow | Draft hire quotations had no hire days, so thinkNXG ERP priced one rate period, not the enquired period | Each hire line now carries the item's rate basis and the chargeable hire days (minimum hire included); the quotation's amount equals the website estimate |
| Broken links | Account page linked to `/update-profile` (no such page in thinkNXG Framework 16) and logged out with a GET to a POST-only method | Profile goes to `/rental/profile` (customers) or `/me`; Log out is a POST with the CSRF token |
| Broken links | "Create a login" shown even when sign-up is disabled | Shown only when Website Settings allow sign-up |
| Placeholder content | The seed put an administrator hint in two section subtitles, visible once those sections were switched on | Removed from the defaults; patch `clear_section_hints` removes it from existing sites |
| Security | Notification subjects carried the visitor's name unescaped into the desk | Escaped; visitor text is stored as plain text (markup removed) |
| Security | Malformed basket / enquiry payloads raised server errors | Refused with a clear validation message |
| Security | Website links in sections, cards and the map link were not checked (`javascript:` possible); private files could be chosen as images | All links checked; private images refused in settings and never shown for items, galleries or datasheets |
| Security | Estimate and basket endpoints had no request limit | Rate limited per IP (600 and 300 per 10 minutes) |
| Consistency | Amounts were formatted twice (Jinja with the currency symbol, the browser with Intl) and looked different | One server formatter: ISO code + system number format + currency decimals (e.g. "OMR 95.000"), used by pages and returned by the API |
| Translation | Script texts could not be translated | Sent translated with the page; a test keeps the list in step with rw.js |
| RTL / Arabic | No `dir` attribute; layout used left/right | `dir="rtl"` for RTL languages, logical CSS properties, mirrored arrows, figures isolated |
| Performance | Every page loaded thinkNXG's 750 KB icon sprite | Each page inlines only the icons it uses (about 13 KB) |
| Accessibility | White text on the default teal button was 3.9:1 | Button and link colours are computed to reach WCAG AA (4.5:1) for any colour an administrator picks |
| Design | Tablet hero stacked a full-height drawing; empty photo frames for categories and products; About page half empty without a photo; centred hero chips cut off on phones; "System Fonts" option had no styling | Split hero from 768 px; compact category rows and a drawn grid placeholder; single-column About; chips scroll from the start; system font stack |
| 404 | thinkNXG's generic 404 page inside the website | The website's own page (search, categories), still HTTP 404, noindex; a switched-off website still shows nothing of itself |
| Availability | Batch free-stock logic duplicated the reservation check | Kept for speed, now proven equal to `available_own_qty` by a test before and after a reservation |

## 9. Tests

```
bench --site <site> run-tests --module thinknxg_rental.tests.test_public_website
```

39 tests (plus one in `test_reservation_warehouses`): pages and 404s, disabled website, categories from item groups, unpublished items, search /
filters / sort / paging, product page and canonical 301, rates from the rate logic and minimum hire,
prices switched off, availability bands, the basket ignoring browser prices, enquiry to Lead and draft
quotations, validation, purchase switch, honeypot, logged-in customer enquiries and portal isolation,
contact form, staff quotation creation, quotation acceptance (own, open, unexpired, once), sitemap,
home page and robots sync, templates changing layout, template section loading, empty sections hidden,
and from the review: quotation amount equals the estimate, private files, unsafe links and settings values,
malformed payloads, the website 404, one money format, translatable script texts, the icon sprite
covering every icon used, AA contrast for all templates, RTL, account page links, escaped staff
notifications, customer permissions, the hint-removal patch; website free stock equal to the
reservation check.
The pages, basket, estimate, enquiry, contact, account and log-out flows were driven in Chromium at
1366, 820 and 390 px, in all five templates and in Arabic (RTL), with a crawl of every linked page.

## 10. Limitations

- **Availability is current free stock**, not stock on the requested dates: future returns and future
  reservations are not projected. The website therefore shows a band and the quotation confirms.
- The estimate uses each item's default rate basis; the quotation may use another basis or discount.
- There is no online payment or checkout; purchase is by enquiry and quotation.
- The basket is stored in the visitor's browser; it does not follow them to another device.
- Accepting a quotation records the acceptance; it does not create the Rental Site or order by itself.
- Confirmation e-mails need an outgoing e-mail account on the site.
- The draft quotation's grand total can differ from the estimate by a few fils: the quotation engine
  rounds Qty x days / basis to the quantity precision before pricing (existing behaviour, unchanged).
- Search engines and social networks need a PNG or JPG for previews: set *Social image* in the SEO
  tab (the default is the SVG logo).
- The app ships no Arabic translations; pages switch to right-to-left, and texts appear translated
  once translations are added.
- Self sign-up uses thinkNXG's login page and follows Website Settings > *Disable Signup*; a new login is
  linked to a customer by the rental team (the Business Account enquiry asks for this).
