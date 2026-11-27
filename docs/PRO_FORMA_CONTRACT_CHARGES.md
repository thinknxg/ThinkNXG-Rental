# Pro Forma Invoice from a Hire Order Contract

## What existed

- The pro forma (`Rental Pro Forma Invoice`) was built from a **Hire Order** or a **Rental Contract**: rental lines priced by rate basis (daily / weekly / monthly / custom) over a rental period, plus a free-entry *charges* table (transport, services) and deposits.
- A Hire Order Contract has **no** such path. Its charges are the *Contract Charge* and *Excess Charge* of each job line, billed from the Job Completion Report (JCR) through `services/jcr_billing.py` (`plan_periods`, one billing schedule per period). A Rental Contract made from a Hire Order Contract carries material, which a Job Type Contract does not bill on hire, so a pro forma from it was empty or wrong.

## What changed

`make_from_hire_order_contract(source_name, bill_upto=None)` (button **Create → Pro Forma Invoice** on the contract, which asks for *Bill Up To*, month end by default). A Rental Contract that comes from a Hire Order Contract now uses it too. The Hire Order path is untouched.

The lines come from `jcr_billing.plan_periods`, the same planner the JCR billing uses, so the pro forma and the later tax invoices agree on days and amounts. Nothing is recalculated.

| Line | Quantity | Rate | Amount |
|---|---|---|---|
| Contract Charge | jobs on the JCR line | contract rate of that line | jobs x contract rate |
| Excess Charge | job-days (job-weeks, job-months) in the period | excess rate of that line | units x excess rate |

- Contract days = included days of the job line from its erection date; excess days are only the days after that, up to Bill Up To or the last return date, each month its own line. No excess days, no excess line.
- Every job line is worked from its own included days, rates, basis, erection and return dates, never from another line or the contract's overall span.
- Descriptions: `Contract Charge - <job type> - <JCR @ location> - <n> Jobs - <d> Days (<from> to <to>)` and `Excess Charge - ... - <n> Jobs - <d> Days (<from> to <to>) @ <rate> per job per <day|week|month>`. The item is the job type; the JCR and job line are kept on the row.
- Jobs of a contract line not yet on a JCR carry their contract charge from the contract's *Required From* date (no excess is projected). When their JCR is made later, that charge is not asked again.
- **No duplicates**: periods already on a live (not expired, not cancelled) pro forma, or already invoiced / settled as No Charge through JCR billing, are left out; a later pro forma gets only the days after them. If nothing is left the user is told. Cancel or delete a pro forma and its periods are free again.
- A job line with no excess rate has no excess line (JCR billing treats those days as No Charge); one with no contract rate has no contract line. Either is named in the pro forma's Remarks, and if that leaves nothing the message says why.
- Other charges (transport and services) stay in the existing *charges* table with their current maths, VAT treatment and totals. They are not generated from the contract today, so they cannot be duplicated by it.
- VAT, rounding, totals, deposits, advances and the status workflow are the existing ones.
- **Conversion**: a pro forma with Contract or Excess lines cannot be converted to a Sales Invoice (message points to the JCR *Create Invoice*), because that would bill the same periods a second time next to the JCR billing schedules.

## Schema

Rental Pro Forma Item: `charge_type` (Rental / Contract Charge / Excess Charge, default Rental), `job_qty`, `jcr`, `jcr_line`. Rental Pro Forma Invoice: `hire_order_contract`. Existing rows are plain Rental lines and calculate as before. No patch is needed.

## Files

`rental_pro_forma_invoice.py` (`make_from_hire_order_contract`, `contract_lines`, `_covered`, `_prebilled`, `_free_stretches`, `calculate_item`, `make_sales_invoice`, `make_from_rental_contract`), the two doctype JSONs, `hire_order_contract.js`, `tests/test_proforma_contract_charges.py`.

## Tests (13)

Worked by hand with fixed dates (erection 2026-01-01):

| Case | Input | Expected |
|---|---|---|
| Contract only | 2 jobs, 30 days, rate 1000, up to 01-30 | one Contract line, 30 days, 2000 |
| With excess | same, up to 02-14, excess 50/day | Contract 2000; Excess 01-31 (1 day) = 2 x 1 x 50 = 100; 02-01..14 (14 days) = 2 x 14 x 50 = 1400; total 3500 |
| Two job types | A: 2 jobs, 30 d, 1000, excess 50; B: 1 job, 10 d, 200, excess 20; up to 01-31 | A 2000 + 100; B 200 + 21 days x 20 = 420 |
| Weekly basis | 1 job, excess 70/week, 8 excess days | 8/7 weeks, 80.00 |
| Several JCRs | 1 and 3 jobs of one line, different erection dates | each keeps its JCR, dates and jobs; only the first has excess |
| Repeat | same pro forma twice; later date; after cancelling | second refused; later one gets only the new days; periods free again |
| Not yet erected | 3 jobs, 1 on a JCR | 1 + 2 jobs once; later JCR for the 2 adds nothing |
| Missing rates | no excess rate / no contract rate | no line, reason given |
| Rental Contract of a Hire Order Contract | | same lines, linked to both |
| Conversion | pro forma with Contract lines | refused |

The existing Hire Order and Rental Contract pro forma tests (`test_deposits_proforma`) pass unchanged.
