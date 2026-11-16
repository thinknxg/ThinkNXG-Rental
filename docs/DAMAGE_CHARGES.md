# Damage and loss charges (v2.5)

Three charges per unit decide what a customer pays for material that does not come back in good order:

| Charge | Used for | Rental Item Profile field |
| --- | --- | --- |
| Lost Charge per Unit | units not returned (off-hire note, Lost Qty) | `lost_charge` |
| Beyond Repair Charge per Unit | units returned damaged beyond repair (return inspection, Damaged Qty) | `beyond_repair_charge` |
| Repair Charge per Unit | units returned repairable (return inspection, Repairable Qty) | `repair_charge` |

## How the values travel

```
Rental Item Profile ─(default for a new row)─► Quotation Item  nxg_lost_charge / nxg_beyond_repair_charge / nxg_repair_charge
                                                    │ (editable on the quotation; saved values are its own)
                                                    ▼
                                              Hire Order Item  lost_charge / beyond_repair_charge / repair_charge
                                                    ▼
                                              Rental Contract Item ──► Rental Damage Settlement (rate per classification)

Rental Item Profile ─(default when materials are exploded)─► Hire Order Contract Material ─► Rental Contract Item ─► settlement
```

* **Snapshot rule.** A row takes its charges once, when it is created, from the document it is made from
  (its quotation row, its Hire Order row, its Hire Order Contract material). Only a row with no source (a
  hire order or contract entered by hand, or a contract's physical materials, which a job-type quotation
  never priced) starts from the Rental Item Profile. After that the row keeps its own values: editing the
  profile changes only rows created later. An agreed zero stays zero.
* **Editing.** Quotation rows (Rental Charges section of the row) and Hire Order, Hire Order Contract
  material and Rental Contract rows (Damage and Loss Charges section of the row editor) are editable
  while the document is a draft.
* **Hire Order Contract.** Its quotation is priced by job type, not by physical item, so the charges live
  on the Materials table (the physical rental items exploded from the job types), taken from the quotation
  when it lists the same item, else from the profile. One item carries one set of charges on a contract.
* **Settlement.** `Create > Damage Settlement` on a submitted off-hire note prices each row from the
  Rental Contract row of the item: Lost x Lost Charge, Beyond Repair x Beyond Repair Charge, Repairable x
  Repair Charge. The row's *Charge From* shows which contract value was used. Liability %, salvage value,
  transport and other charges, totals, taxes and invoicing work as before.
* **Replacement value.** It is no longer the settlement rate. It is kept on Hire Order and Rental Contract
  rows as part of the same snapshot, and is used only for Lost and Beyond Repair rows of a contract that
  has no agreed charge for them (contracts made before 2.5 with no profile charges). Repairs never fall
  back to it.

## Existing records (patch `v2_4.backfill_damage_charges`)

Rows created before 2.5 have no charges. The patch gives each its source's values: Hire Order rows from
their quotation row, Hire Order Contract materials from their quotation (when listed), Rental Contract
rows from their Hire Order row or material. Only rows with no source take the profile's current values.
Rows without a replacement value take their Hire Order row's, else the profile's. Rows that already have
values are not touched, so the patch can run again.

## Code

* `thinknxg_rental/services/damage_charges.py`: the rules (snapshot of new rows, sources, settlement rate).
* `services/item_rental.py`: quotation row defaults and snapshot (unchanged, from 2.1).
* `services/deal_flow.py`: Quotation -> Hire Order copies the row's saved charges.
* Controllers: Hire Order, Hire Order Contract, Rental Contract call the rules in `validate`;
  `hire_order_contract.make_rental_contract` carries the materials' charges; `hire_off_hire_note.make_damage_settlement`
  prices from the contract.
* Desk: picking an item on a Hire Order or Rental Contract row shows the profile defaults straight away.
* Tests: `tests/test_damage_charges.py` (scenarios A-H, the Hire Order Contract path, fallbacks, the patch).

## Currency

Quotation charges are in the quotation's currency (converted from the profile when fetched). They are
copied to the Hire Order unchanged, as the Hire Rate already is.
