# Additional Physical Rental Items on a Hire Delivery Order (v2.8.0)

## The problem
After the Hire Order Contract and Rental Contract are submitted, a customer may need material that was not
contracted. Before 2.8.0 the Hire Delivery Order refused any item that was not on the Rental Contract, so users
had to edit the contract first.

## How it works
1. On a Hire Delivery Order, **Get Items → Add Additional Item** adds a line. Choosing an item that is not on the
   contract ticks **Additional** automatically. Tick it by hand for extra quantity of an item that is already on the contract.
2. On submit the delivery adds the material to the live Rental Contract:
   * an item not on the contract becomes a new contract row (**Added During Delivery**, with the delivery that first added it);
   * an item already on the contract keeps its row; **Additional Qty** records the part added by deliveries
     (original quantity = Contracted Qty − Additional Qty).
   The Hire Order Contract, the original rows and their quantities are not changed, and nothing is cancelled or amended.
3. From then on the item is an ordinary contract item, so everything downstream sees it with no special cases:
   Rental Ownership Ledger (`Dispatch`, linked to the contract and its source), Material at Site, billing from the
   dispatch date, off-hire (partial and full), return inspection, lost and damaged settlement, reconciliation and closure.
4. Several additional items can be on one delivery, and further deliveries can add more. Own stock, several
   warehouses and cross-hired material all work; the usual stock, cross hire order and warehouse checks apply on the server.
5. Cancelling the delivery takes the additional quantity off the contract again (a row that exists only because of
   deliveries is removed). It is refused once any of the material has been off-hired or billed.

## Updates in 2.8.0 (follow-up)
* **Server error fixed.** The form looked up the contract's items with `frappe.db.get_list(..., parent=...)`, which v16
  rejects (`DatabaseQuery.execute() got an unexpected keyword argument 'parent'`). It now calls the server method
  `get_contract_info`. Additional items can be added on a new delivery at any time, also when every contracted
  quantity has already been delivered; earlier deliveries and their quantities are not touched.
* **Job Type.** On a Job Type Contract an additional line carries the Job Type it is for (the contract's job types are
  those of its Hire Order Contract). With a single job type it is filled in automatically; with several the user picks
  one, and the server refuses a missing or foreign job type. It is stored on the delivery line and on the contract row
  the delivery adds. The column is not used for any other contract, and no interface change is needed there.
* An item that is not on the contract is always treated as additional (the tick is no longer required).
* **Command Center.** The delivery order form has the Additional and Job Type columns, the Rental Contract items table
  shows Additional Qty, Added During Delivery and Job Type, and **New Delivery Order** is also offered on an Off Hired
  contract (material can be added after everything was returned, until the contract is closed).

## Rules kept
* Additional lines are not held to a reservation (they were never reserved); they leave from the default own rental
  warehouse unless a warehouse is chosen, and the free-stock check against other contracts' reservations still applies.
* A line that is not ticked and is not on the contract, or is more than the contract balance, is refused, with a hint to tick Additional.
* Only stock items that are not disabled can be hired out.
* Job Type Contracts are billed from the Job Completion Report, not from material on hire (unchanged): additional
  material is tracked, off-hired and reconciled, but adds no per-item rental charge there.

## Off-hire and closure (checked, unchanged)
A Hire Off-Hire Note records the return and moves the contract to **Off Hired**; it never closes it. Billing runs to
the last billable day of the material. The contract is closed only by the explicit **Close Contract** action, which
checks that nothing is at site, inspections and settlements are done, and the material is reconciled.

## Data changes
New fields: `Hire Delivery Item.additional_item`; `Rental Contract Item.is_additional`, `additional_qty`,
`added_by_delivery`. Existing data needs no patch (all default to 0). Run `bench migrate`.

## Tests
`bench --site <site> run-tests --module thinknxg_rental.tests.test_additional_delivery_items`
