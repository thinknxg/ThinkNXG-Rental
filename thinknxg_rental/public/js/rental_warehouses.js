// Rental warehouses of Rental Settings (own and cross hire, with their locations), fetched once per page.
//
// Shipped with each form that needs it (hooks.py doctype_js), so the form never depends on a separately
// loaded desk script: when an app_include_js file was missing, late or an old cached copy, the form's
// setup stopped at "thinknxg_rental is not defined" and Frappe drew no fields. Defined only once, so the
// copy in rental_flow.js and this one share the same cached request.
frappe.provide("thinknxg_rental");
if (typeof thinknxg_rental.rental_warehouses !== "function") {
	thinknxg_rental.rental_warehouses = function () {
		if (!thinknxg_rental._rental_warehouses) {
			thinknxg_rental._rental_warehouses = frappe
				.xcall("thinknxg_rental.services.warehouses.get_rental_warehouses")
				.catch(() => {
					thinknxg_rental._rental_warehouses = null;
					return [];
				});
		}
		return thinknxg_rental._rental_warehouses;
	};
}
