# Multi-location own rental and cross hire warehouses (2.2)

The app used to know one **Rental Yard** and one **Cross Hire Yard**. From 2.2 a company can keep own rental
stock in any number of warehouses at any number of locations (Kochi, Calicut, Trivandrum, Bangalore, ...)
and receive cross-hired material into any number of cross hire warehouses. Each warehouse keeps its own
ERPNext stock. A setup with one yard of each kind behaves exactly as before.

## 1. Architecture in short

- **ERPNext is still the stock engine.** Every physical move is a standard Stock Entry (Material Transfer,
  Issue, Receipt) or Purchase Receipt / Return. Stock per warehouse is read from Bins.
- **Rental Ownership Ledger** is still the only rental ledger. It holds the *At Site* position (what is at
  customer sites, Own or Cross Hire) and the *Cross Hire Custody* position (supplier material we hold).
  Four fields were added so every movement can be traced to warehouses.
- **Reservations are soft.** They never post stock. A reservation row is an allocation of one item in one
  warehouse; what other reservations hold is subtracted from that warehouse's stock.
- **Rental Settings** names the warehouses. Business logic asks `services/warehouses.py`, never the old
  single-yard fields.

## 2. Single-warehouse assumptions that were removed

| Where | Before | Now |
|---|---|---|
| Rental Settings | one `rental_yard_warehouse`, one `cross_hire_yard_warehouse` | two tables, each with one default; the old fields follow the defaults |
| Reservation | one row per item; balances keyed by item | one row per item **and warehouse**; rows split over warehouses; balances keyed (item, warehouse) |
| Delivery | own rows fell back to the yard and were forced to the item's single reserved warehouse; no ownership check | rows split over reservation allocations; each row checked against its warehouse's reserved balance, its stock and its ownership category |
| Off-hire | one row per item; cross hire target forced; ledger kept only the site warehouse | several rows per item, each with its own return warehouse; *Delivered From* traced; source and target warehouses kept apart |
| Inspection | Good went to the single yard | Good goes to the row's *Good Stock To* warehouse |
| Cross Hire Order | received only at the cross hire yard | any active cross hire warehouse |
| HO / HOC / RC availability, item details | the yard only | summed over every active own rental warehouse |
| Reports, dashboard | the yard only; reserved summed over every warehouse | per warehouse and location; reserved counted only in own warehouses |

## 3. Configuration

**Rental Settings > Own Rental Warehouses** and **Cross Hire Warehouses** (child DocType *Rental Warehouse*):

| Field | Meaning |
|---|---|
| Warehouse | a leaf warehouse of the Default Company |
| Location / Branch | free text (Kochi). Left empty, it is the parent warehouse group's name. No Branch DocType is added. |
| Is Default | the warehouse used when a document does not say which one; one per table |
| Is Active | inactive warehouses keep their stock and history, but are not offered or accepted on new reservations, cross hire orders, returns or transfers into them. Reserved stock in a warehouse made inactive can still be delivered. |

Validated on save: no duplicates; a warehouse is in one table only (own and supplier stock never share a
warehouse); not a group; same company; not the inspection, repair, scrap, lost, excess or a customer site
warehouse; exactly one active default per table (the first active row becomes the default when none is
ticked). The legacy *Default Rental Yard* / *Default Cross Hire Yard* fields are read-only and always
equal the defaults; setting one of them from older code or scripts makes that warehouse the default.

## 4. Workflows

### Reservation (Rental Material Reservation)

- Each row: Source Warehouse, Location, Supply (Own / Cross Hire), Actual, Reserved for Others,
  Available, Reserved, Shortfall, Dispatched.
- A row without a warehouse (or left on an empty default, or a cross hire row whose own stock has come
  free) is **placed on save**: split over the active own warehouses with free stock - the default first
  when it has any, then the warehouse with the most free stock - and what none can cover stays as
  shortfall on the last own row. With no own stock free anywhere the row is Cross Hire, in the cross hire
  warehouse the material will arrive in (the open Cross Hire Order's, else the default).
  Example: 100 / 80 / 60 in Kochi / Calicut / Trivandrum, Kochi default, 150 required -> Kochi 100,
  Calicut 50.
- A warehouse picked by hand is kept (e.g. 40 / 35 / 25 entered as three rows).
- **Submit** locks the Bin rows of every (item, warehouse) first, before the document itself, then re-reads
  stock and other reservations with locking reads. Two reservations or deliveries of the same stock queue
  instead of both taking it. Warehouses are never changed on submit; submitted rows cannot be edited.
- Cross Hire Order for Shortfall takes every row's shortfall, as before.

### Delivery (Hire Delivery Order)

- *Get items* proposes one row per reservation allocation (warehouse by warehouse), then free stock in
  the default and other own warehouses, then received cross hire material per Cross Hire Order.
- A row without a warehouse is split over the item's allocations; a row with a warehouse keeps it.
- Checked on the server for every row: own rows leave an own rental warehouse (cross hire rows a cross
  hire warehouse or their direct-to-site warehouse); the warehouse holds the quantity; with a reservation
  named, the quantity stays within that warehouse's reserved balance; a cross hire row's material must be
  that Cross Hire Order's material in that warehouse.
- One Material Transfer carries every row, from as many source warehouses as there are. Each ledger row
  records Delivered From, Source, Target and the Stock Entry. Partial and repeated deliveries work as before.

### Customer off-hire (Hire Off-Hire Note)

- One item can be split over rows: e.g. 60 to Calicut and 40 to Kochi.
- **Return Warehouse** = where the material is moved now; **Good Stock Returns To** = the own warehouse it
  ends up in. Material that needs inspection always goes to the inspection warehouse first; a rental
  warehouse picked as Return Warehouse then becomes Good Stock Returns To.
- Defaults: back to the warehouse it was delivered from (when active), else the default own warehouse.
- **Delivered From** is filled from what is at site (split over origins, largest first); the latest
  delivery of that item from there, the site warehouse and the Stock Entry are recorded on the row.
- Returned + lost over all rows of an item is capped at what is at site; a chosen Delivered From is capped
  at what is at site from there.
- Cross hire rows go back only to a cross hire warehouse (or the order's receipt warehouse). Returned to a
  different cross hire warehouse, the custody ledger records a same-day transfer pair (no billing effect).
- Billing is unchanged: it follows the at-site quantity and the last billable date as before.

### Inspection (Rental Return Inspection)

Good -> the row's **Good Stock To** (defaults to the off-hire's Good Stock Returns To, else the default own
warehouse; only an active own warehouse is accepted), Repairable -> repair warehouse, Beyond Repair ->
scrap warehouse. Stock under inspection is never available. Cross hire rows never move into own stock.

### Cross hire

- **Cross Hire Warehouse** on the Cross Hire Order is selectable (active cross hire warehouses) for
  *Cross Hire Yard*; *Direct to Site* still uses the site's cross hire warehouse.
- Cross Hire Receipt rows must go to a cross hire warehouse (or the order's direct-to-site warehouse).
- Supplier off-hire (Cross Hire Off-Hire Note -> Purchase Return) returns from a cross hire warehouse only
  and stays a separate document from the customer off-hire. Zero-value custody is unchanged.

### Transfers between locations

Use a standard **Stock Entry - Material Transfer**. A hook (`events/stock_entry.py`) checks entries made by
hand:

- own <-> cross hire: refused in both directions;
- into or out of a customer site warehouse: refused (only deliveries and off-hires move site stock);
- out of an own warehouse: only stock not held by open reservations;
- into an inactive rental warehouse: refused;
- issuing supplier material: refused (use the off-hire documents);
- between cross hire warehouses: the Stock Entry names its **Cross Hire Order** (new field), the quantity
  must be that order's material in the source warehouse, and the custody ledger records a transfer pair.

Transfers never touch billing or site positions.

## 5. Fields and files

New DocType: **Rental Warehouse** (child: warehouse, location, is_default, is_active).

| DocType | New fields |
|---|---|
| Rental Settings | `own_rental_warehouses`, `cross_hire_warehouses` (legacy yard fields now read-only, kept) |
| Rental Material Reservation Item | `location`; `item_code` indexed |
| Hire Delivery Item | `location` |
| Hire Off-Hire Item | `return_to_warehouse`, `location`, `delivered_from`, `delivery_order`, `site_warehouse`, `stock_entry` |
| Rental Return Inspection Item | `good_warehouse`, `delivered_from` |
| Rental Ownership Ledger | `origin_warehouse` (Delivered From), `source_warehouse`, `target_warehouse`, `stock_entry`; movement type `Transfer` |
| Cross Hire Order | `receipt_warehouse` now editable (label Cross Hire Warehouse) |
| Stock Entry (custom) | `nxg_cross_hire_order` |

New modules: `services/warehouses.py` (configuration, validation, Bin locking), `services/inventory.py`
(positions per warehouse), `events/stock_entry.py` (transfer rules), report **Rental Inventory**,
patch `patches/v2_2/seed_rental_warehouses.py`, tests `tests/test_multi_warehouse.py`.

Changed: reservation, delivery, off-hire, inspection, cross hire order / off-hire note, Purchase Receipt
hooks, HO / HOC / RC availability, `services/utils.py` (locking reads), ledger helpers, Rental Stock
Position, Material at Site, Cross Hire Position, Command Center registry / report filters / forms /
dashboard, desk form scripts.

## 6. Migration

`bench migrate` runs `thinknxg_rental.patches.v2_2.seed_rental_warehouses`:

- the existing Rental Yard becomes the default own warehouse, the Cross Hire Yard the default cross hire
  warehouse;
- warehouses already used as own sources (reservation headers and rows, deliveries) and as cross hire
  receipt warehouses (orders received at a yard) are added, so earlier documents stay valid;
- rows already in a table are never changed; running it again adds nothing;
- no warehouse is renamed or deleted; no Stock Entry, Stock Ledger Entry or rental document is changed.

Ledger rows written before 2.2 have no Delivered From: they count against the order's receipt warehouse
(cross hire) or the default own warehouse (own) in the inventory figures.

## 7. Reports and Command Center

- **Rental Inventory** (new; Command Center: Inventory & yard > Inventory by Warehouse, and Reports): one
  row per location, warehouse, item, ownership, supplier / Cross Hire Order and stock status (Available,
  Reserved, At Site, In Custody, Under Inspection, In Repair, Scrap). Filters: Location, Warehouse, Item,
  Ownership, Supplier, Stock Status. Export as any report.
- **Rental Stock Position**: Location and Warehouse filters; *Group by Warehouse* gives in-warehouse,
  reserved, available, cross hire custody and at-site (delivered from here) per warehouse.
- **Material at Site**: Site Warehouse, Delivered From and Location columns; Delivered From and Location
  filters.
- **Cross Hire Position**: Cross Hire Warehouse, Location and *Held In* (where each order's material is
  now); Warehouse and Location filters.
- Command Center forms show Location on reservation and delivery rows, Delivered From / Return Warehouse /
  Good Stock Returns To on off-hire rows, Good Stock To on inspections and the Cross Hire Warehouse on
  orders; warehouse pickers offer only the right kind of rental warehouse. The dashboard counts every own
  warehouse.

## 8. Tests

`bench --site <site> run-tests --module thinknxg_rental.tests.test_multi_warehouse` (15 tests), plus the
existing suite (91 tests in all, passing):

| Scenario | Test |
|---|---|
| A single warehouse | `test_a_single_warehouse_behaves_as_before` |
| B 100/80/60, reserve 150 | `test_b_reservation_splits_over_warehouses`, `test_b_reservation_rejects_wrong_warehouses` |
| C multi-warehouse delivery | `test_c_delivery_from_several_warehouses` |
| D return elsewhere (60 Calicut / 40 Kochi) | `test_d_return_to_a_different_warehouse` |
| E partial returns 30 + 40, 30 left | `test_e_partial_returns_on_two_dates` |
| F two cross hire warehouses | `test_f_two_cross_hire_warehouses`, `test_f_direct_to_site_cross_hire_still_works` |
| G inspection | `test_g_inspection_routes_each_quantity` |
| H cancellations | `test_h_cancellations_reverse` |
| I concurrent reservations (two DB sessions in threads) | `test_i_concurrent_reservations_never_over_reserve` |
| J migration | `test_j_migration_seeds_tables_idempotently` |
| Transfers, reports, settings | `test_transfers_between_locations`, `test_reports_by_warehouse_and_location`, `test_settings_validation` |

## 9. Install / upgrade

```
cd frappe-bench
bench get-app --branch <branch> thinknxg_rental <repo>   # or git pull in apps/thinknxg_rental
bench --site <site> migrate
bench build --app thinknxg_rental
bench restart
```

Then open Rental Settings, add the other own and cross hire warehouses with their locations, and check the
defaults. Take a backup before migrating.

## 10. Limitations

- Location is text on the Rental Warehouse row (or the parent group's name); there is no Branch master.
- Inspection, repair and scrap stay single company-wide warehouses; they show without a location, and
  location-filtered stock positions leave them out.
- Material at a site is fungible: Delivered From is traced per movement, and a return without one is
  matched to the origins largest first.
- Supplier material moved between cross hire warehouses must name its Cross Hire Order; a manual entry
  that mixes several orders' material in one row is refused.
- Manual Stock Entries touching customer site warehouses are refused; correct site stock with the
  rental documents (or a Stock Reconciliation, which the hook does not check).
