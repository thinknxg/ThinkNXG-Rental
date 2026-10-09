frappe.ui.form.on("Quotation", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 1 || !frm.doc.deal_type) return;
		const method = "thinknxg_rental.services.deal_flow.";
		if (frm.doc.deal_type === "Material Hire") {
			frm.add_custom_button(__("Hire Order"), () => frappe.model.open_mapped_doc({
				method: method + "make_hire_order_from_quotation", frm
			}), __("Create"));
		} else if (frm.doc.deal_type === "Material Sale") {
			frm.add_custom_button(__("Sales Order"), () => frappe.model.open_mapped_doc({
				method: method + "make_sales_order_from_quotation", frm
			}), __("Create"));
		} else if (frm.doc.deal_type === "Hire Order Contract") {
			frm.add_custom_button(__("Hire Order Contract"), () => frappe.model.open_mapped_doc({
				method: method + "make_hire_order_contract_from_quotation", frm
			}), __("Create"));
		}
		frm.page.set_inner_btn_group_as_primary(__("Create"));
	},
});

// ---------------------------------------------------------------------------------------------
// Hire quotations: Length / Breadth / Height / Duration on the item rows.
//   Qty    = Length x Breadth x Height once all three are filled (otherwise the typed Qty stays)
//   Amount = Qty x Unit Price x Duration   (blank Duration counts as 1)
// Only for the deal types below; other deal types keep the standard Qty x Rate.
// The same rule runs on save in thinknxg_rental/events/quotation.py. Keep both lists in step.
// ---------------------------------------------------------------------------------------------
const NXG_HIRE_DEAL_TYPES = ["Material Hire", "Hire Order Contract"];
const NXG_DIMENSION_FIELDS = ["nxg_length", "nxg_breadth", "nxg_height", "nxg_duration"];

function nxg_is_hire(frm) {
	return NXG_HIRE_DEAL_TYPES.includes(frm.doc.deal_type);
}

function nxg_dimension_qty(row) {
	// Length x Breadth x Height, or null when any of the three is empty
	const length = flt(row.nxg_length), breadth = flt(row.nxg_breadth), height = flt(row.nxg_height);
	return length && breadth && height ? flt(length * breadth * height, precision("qty", row)) : null;
}

function nxg_toggle_dimension_columns(frm) {
	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	const df = grid && grid.get_docfield && grid.get_docfield("nxg_length");
	if (!df) return; // custom fields not created yet (bench migrate pending)
	const show = nxg_is_hire(frm);
	if (!!df.hidden === !show) return; // already in the right state
	grid.set_column_disp(NXG_DIMENSION_FIELDS, show);
}

// ERPNext computes every item amount as Qty x Rate inside _calculate_taxes_and_totals(). For hire
// quotations Qty is multiplied by Duration for the length of that call and then put back, so
// taxes, discounts and rounding all follow ERPNext while the unit price is never changed.
function nxg_install_calculation(frm) {
	const cscript = frm.cscript;
	if (!cscript || cscript._nxg_calc_installed || typeof cscript._calculate_taxes_and_totals !== "function") return;
	const original = cscript._calculate_taxes_and_totals;
	cscript._calculate_taxes_and_totals = function (...args) {
		if (!nxg_is_hire(frm)) return original.apply(this, args);
		const rows = frm.doc.items || [];
		rows.forEach((row) => {
			const qty = nxg_dimension_qty(row);
			if (qty !== null) row.qty = qty;
		});
		const typed_qty = rows.map((row) => row.qty);
		rows.forEach((row) => {
			row.qty = flt(row.qty) * (cint(row.nxg_duration) || 1);
		});
		try {
			return original.apply(this, args);
		} finally {
			rows.forEach((row, i) => {
				row.qty = typed_qty[i];
			});
			frm.doc.total_qty = rows.reduce((total, row) => total + flt(row.qty), 0);
		}
	};
	cscript._nxg_calc_installed = true;
}

frappe.ui.form.on("Quotation", {
	onload(frm) {
		nxg_install_calculation(frm);
	},
	refresh(frm) {
		nxg_install_calculation(frm);
		nxg_toggle_dimension_columns(frm);
	},
	deal_type(frm) {
		nxg_toggle_dimension_columns(frm);
		frm.cscript.calculate_taxes_and_totals();
		frm.refresh_field("items");
	},
});

function nxg_dimension_changed(frm, cdt, cdn) {
	if (!nxg_is_hire(frm)) return;
	const qty = nxg_dimension_qty(locals[cdt][cdn]);
	if (qty !== null && flt(locals[cdt][cdn].qty) !== qty) {
		// through ERPNext's own Qty handler, so stock quantity and totals follow
		frappe.model.set_value(cdt, cdn, "qty", qty);
	} else {
		frm.cscript.calculate_taxes_and_totals();
	}
}

frappe.ui.form.on("Quotation Item", {
	nxg_length: nxg_dimension_changed,
	nxg_breadth: nxg_dimension_changed,
	nxg_height: nxg_dimension_changed,
	nxg_duration: nxg_dimension_changed,
});

// Quotation made for a Lead or Prospect (saved or submitted): one click makes (or finds) the Customer.
// The Hire Order, Hire Order Contract and Sales Order buttons do the same on their own when they need a Customer.
frappe.ui.form.on("Quotation", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus === 2 || !["Lead", "Prospect"].includes(frm.doc.quotation_to)) return;
		frm.add_custom_button(__("Customer"), () => {
			frappe.call({
				method: "thinknxg_rental.services.deal_flow.make_customer_from_quotation",
				args: { source_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Creating Customer..."),
				callback(r) {
					if (r.message) frappe.set_route("Form", "Customer", r.message);
				},
			});
		}, __("Create"));
	},
});
