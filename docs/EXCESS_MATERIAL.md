# Excess material, dismantling entries and material reconciliation

Version 2.6.0. This covers material a customer hands back over and above what is at site, returning that
excess to the customer, settling material the customer still owes against it, and the reconciliation
that must pass before a contract or project is closed.

## The three records, kept apart

| What | Where it lives | Moved by |
|---|---|---|
| Physical stock | ERPNext Stock Entries (never Bin or the Stock Ledger directly) | Off-hire note (excess in), Excess Material Return Note (excess out), Dismantling Entry (settled units out of the site warehouse) |
| What the customer owes | Rental Ownership Ledger, *At Site* position | Delivery Order (Dispatch), Off-hire note (Return, Loss), Dismantling Entry (**Adjustment**) |
| Commercial record of excess | Excess Material Register | Made by the off-hire note; balances recalculated from submitted return notes and dismantling entries |

Item codes are never treated as interchangeable. No item is converted into another; an adjustment names
both items and both quantities.

## Document relationships

```
Rental Contract ──< Hire Delivery Order            (Dispatch, +qty At Site)
       │
       ├──< Hire Off-Hire Note ──< Hire Off-Hire Item ──1:1── Excess Material Register
       │        (Return / Loss, −qty At Site)   (row with excess)       │  customer, project, contract,
       │        Material Receipt → Excess WH                            │  off-hire note, delivery order
       │                                                                │
       ├──< Dismantling Entry ──< Dismantling Adjustment ───────────────┤  (excess used)
       │        (Adjustment, −qty At Site)                              │
       │        Material Issue from the site WH                         │
       │                                                                │
       └── (customer) Excess Material Return Note ──< Return Item ──────┘  (excess returned)
                Material Issue / Transfer out of the Excess WH
```

## Workflow

1. **Off-hire.** On each row enter **Received** (everything that physically came back), or Returned and
   Excess as before. With Received filled in, the note works out:
   - Returned = what is at site for the item (less lost units), up to the quantity received;
   - Excess = the rest.

   Delivered 10 and received 15 gives Returned 10 and Excess 5. A row for an item the contract never
   delivered is all excess.

   On submit:
   - the excess goes into the row's **Excess Warehouse** (Rental Settings default) as one zero-value
     Material Receipt;
   - each row with excess gets an **Excess Material Register** record, and the row and the note carry
     links to it and to the stock entry. A row can be registered only once.

   Excess Category is set automatically: *Excess from Delivered Items* if the contract ever dispatched
   the item, otherwise *Additional Undelivered Items*.
2. **Return excess to the customer.** Use *Create → Excess Material Return* on the off-hire note or the
   register, or *Get Excess Items* on a new return note.
   - Return Qty can be at most what is Available on the register.
   - On submit the material leaves the excess warehouse: a Material Issue, or a Material Transfer when
     *To Warehouse* is set.
3. **Settle outstanding material (Dismantling Entry).** Use *Create → Dismantling Entry* on the contract
   or the off-hire note. Two tables are recalculated from submitted transactions:
   - **Outstanding Delivered Materials:** delivered, previously returned, lost, previously adjusted and
     outstanding.
   - **Available Excess Materials:** for the same customer and the same project. Without a project it
     is the same contract.

   Each adjustment row names the outstanding item and **Outstanding Settled**, and the excess register
   and **Excess Used**.

   On submit:
   - **Ledger:** an Adjustment movement settles the outstanding item. It stops being billed from the day
     after the posting date.
   - **Stock:** the settled units are issued out of the customer-site warehouse, because they will not
     come back (the same treatment as lost material).
   - **Register:** it records the excess used. The excess item stays in the excess warehouse as itself.
     Moving it into rental stock later is an ordinary, separate Material Transfer.
4. **Reconcile and close.** *View → Material Reconciliation* on the contract shows, per item, Delivered =
   Returned + Lost + Adjusted + Outstanding, and lists every open issue. *Close Contract* refuses while
   any issue is open. Setting a Project to *Completed* runs the same check for every contract on it.

## Validations

- **Excess on the off-hire note:**
  - Excess is for own stock only. On a cross-hired row, Received is simply the Returned quantity.
  - Returned Qty keeps its strict check: it can never be more than what is at site.
  - The excess warehouse cannot be an own rental, cross hire or customer-site warehouse, and must belong
    to the note's company.
- **Return notes:**
  - Return Qty must be more than 0 and no more than Available. Available counts submitted documents
    only, and registers are row-locked while a note is submitted.
  - The register must belong to the same customer and company, and must not be cancelled.
  - Each register can appear only once per note, and every row must come from the same excess warehouse.
- **Dismantling Entries:**
  - The contract must be live, and the entry needs at least one adjustment row to submit.
  - Each row needs both quantities. The outstanding item must be own material that is outstanding on
    the contract; cross-hired material cannot be adjusted.
  - The register must belong to the same customer and company. It must also belong to the same project,
    unless *Allow Excess from Other Projects* is ticked with a reason; that needs a Rental Manager.
  - Totals per item can't exceed the outstanding quantity, and totals per register can't exceed
    Available. Submitted documents are counted, with registers locked.
  - The same outstanding item and register pair can appear only once per entry.
  - If Excess Used ≠ Outstanding Settled, or the units of measure differ, **Ratio Approved** must be
    ticked by a Rental Manager. The approver is recorded on the row.
  - Rental Users can draft entries; only Rental Managers can submit them, and the submitter is recorded
    as *Approved By*.
  - The posting date can't fall in a period that has already been billed.
- **Cancellation:**
  - Cancelling a Dismantling Entry deletes its ledger rows, cancels its stock entry and recalculates the
    registers and the contract.
  - Cancelling a return note puts its quantity back on the registers.
  - An off-hire note whose excess has been returned or adjusted can't be cancelled until those
    documents are cancelled. Otherwise its registers become *Cancelled* and the excess receipt is
    reversed.

## Reconciliation checks (contract and project closure)

- Nothing outstanding for any item: delivered − returned − lost − adjusted = 0.
- No excess left available. All of it must be returned or adjusted.
- Every register has a submitted excess stock entry, so no excess transfer is missing.
- The excess warehouse holds at least what the registers show as available.
- No draft Dismantling Entries, Excess Material Return Notes, or off-hire notes with excess.
- Every submitted Dismantling Entry has an approver.

A Rental Manager can **Approve Reconciliation Exception** on the contract, with a reason.
- The reason, approver and time are stored on the contract, and a timeline comment lists the issues open
  at that moment.
- The contract and its project can then close. Outstanding material at site still blocks *Close
  Contract*, as before.
- Reopening the contract clears the exception.

## Reports

- **Excess Material Register:** every register with its full trace and balances.
- **Customer-wise Excess Material:** received, returned, adjusted and available per customer and item.
- **Project-wise Material Reconciliation:** per project, contract and item, delivered, returned, lost,
  adjusted and outstanding, next to the excess received, returned, adjusted and available, with a
  reconciled state.
- **Outstanding Customer Materials:** what each customer still owes per contract and item, with the
  excess they hold on the same project.

## Permissions

| Doctype | Rental User | Rental Manager | Stock User |
|---|---|---|---|
| Excess Material Register | read | read (edits only through documents) | read |
| Excess Material Return Note | create, submit | full | read |
| Dismantling Entry | create (draft) | full, submit, approve ratios and cross-project use | — |

## Migration

```
bench --site <site> migrate
```

Patch `v2_6.register_existing_excess` gives excess already received on submitted off-hire notes its
register, linked to the existing Material Receipt. It moves no stock and is safe to run again.

The Rental Settings *Excess Warehouse* must be set before an off-hire note with excess is submitted. Setup
creates "Rental Excess".
