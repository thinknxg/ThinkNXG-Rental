// Create -> Rental Site, listed above Hire Order (this handler is registered before the Hire Order one).
// Opens a new Rental Site with the quotation's Customer and Company filled in.
function nxg_make_rental_site(frm) {
        frappe.flags.nxg_site_quotation = { quotation: frm.doc.name, at: Date.now() };
	const open_site = (customer) => frappe.new_doc("Rental Site", {
		customer: customer,
		customer_name: frm.doc.customer_name,
		company: frm.doc.company,
		nxg_quotation: frm.doc.name,
	});
	if (frm.doc.quotation_to === "Customer" && frm.doc.party_name) {
		open_site(frm.doc.party_name);
		return;
	}
	// Lead or Prospect: find or make the Customer first
	frappe.call({
		method: "thinknxg_rental.services.deal_flow.make_customer_from_quotation",
		args: { source_name: frm.doc.name },
		freeze: true,
		freeze_message: __("Creating Customer..."),
		callback(r) {
			if (r.message) open_site(r.message);
		},
	});
}

frappe.ui.form.on("Quotation", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus === 2) return;
		if (!["Material Hire", "Hire Order Contract"].includes(frm.doc.deal_type)) return;
		frm.add_custom_button(__("Rental Site"), () => nxg_make_rental_site(frm), __("Create"));
	},
});

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
	const show = frm.doc.deal_type === "Hire Order Contract";
	const show_dims = frm.doc.deal_type === "Hire Order Contract";
	const dur = grid.get_docfield("nxg_duration");
	if (!!df.hidden === !show_dims && (!dur || !!dur.hidden === !show)) return; // already in the right state
	grid.set_column_disp(["nxg_duration"], show);
	grid.set_column_disp(["nxg_length", "nxg_breadth", "nxg_height"], show_dims);
	grid.reset_grid();
}

// Period is for Hire Order Contract quotations only: hidden for Material Hire (and every other deal type).
function nxg_toggle_period_column(frm) {
        const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
        const df = grid && grid.get_docfield && grid.get_docfield("nxg_period");
        if (!df) return;
        const show = frm.doc.deal_type === "Hire Order Contract";
        const drawn = (grid.visible_columns || []).some((c) => c[0].fieldname === "nxg_period");
        if (show === drawn && !!df.hidden === !show) return; // already right
        grid.set_column_disp(["nxg_period"], show);
        grid.reset_grid(); // the grid fixes its columns when it is built, so rebuild it
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
		const typed_qty = rows.map((row) => row.qty);
		rows.forEach((row) => {
			row.qty = flt(row.qty) * nxg_multiplier(frm, row);
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
		nxg_toggle_period_column(frm);
	},
	deal_type(frm) {
		nxg_toggle_dimension_columns(frm);
		nxg_toggle_period_column(frm);
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
	nxg_duration(frm) {
	    if (nxg_is_hire(frm)) frm.cscript.calculate_taxes_and_totals();
	},
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

// Default Quotation Item grid: Item Code, UOM, Length, Breadth, Height, Rotation, Quantity, Period, Rate, Amount.
// Frappe keeps each user's own column choice and it overrides the doctype defaults, so users who saved
// their columns earlier would never see UOM / Period. When their saved columns lack either of those,
// replace them with this layout once (after that the user can still adjust the grid as usual).
const NXG_DEFAULT_ITEM_COLUMNS = [
    { fieldname: "item_code", columns: 2 },
    { fieldname: "uom", columns: 1 },
    { fieldname: "nxg_length", columns: 1 },
    { fieldname: "nxg_breadth", columns: 1 },
    { fieldname: "nxg_height", columns: 1 },
    { fieldname: "nxg_duration", columns: 1 },
    { fieldname: "qty", columns: 1 },
    { fieldname: "nxg_period", columns: 1 },
    { fieldname: "rate", columns: 1 },
    { fieldname: "amount", columns: 1 },
];

frappe.ui.form.on("Quotation", {
    onload(frm) {
        try {
            const grid = frappe.get_user_settings("Quotation", "GridView") || {};
            const saved = grid["Quotation Item"] || [];
            if (!saved.length) return; // no saved choice: the doctype defaults apply
            const names = saved.map((c) => c.fieldname);
            if (names.includes("uom") && names.includes("nxg_period")) return;
            frappe.model.user_settings.save("Quotation", "GridView", { "Quotation Item": NXG_DEFAULT_ITEM_COLUMNS }).then(() => location.reload());
        } catch (e) {
            console.warn("Quotation grid defaults not applied", e);
        }
    },
});


// ---------------------------------------------------------------------------------------------
// Contract Days / Excess Basis / Excess Rate on the item rows: Hire Order Contract quotations only.
// They are carried into the Hire Order Contract lines (services/deal_flow.py).
// ---------------------------------------------------------------------------------------------
const NXG_CONTRACT_COLUMNS = ["nxg_included_days", "nxg_excess_basis", "nxg_excess_rate"];

function nxg_toggle_contract_columns(frm) {
    const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
    const df = grid && grid.get_docfield && grid.get_docfield("nxg_included_days");
    if (!df) return; // custom fields not created yet (migrate pending)
    const show = nxg_is_hire(frm);
    const drawn = (grid.visible_columns || []).some((c) => c[0].fieldname === "nxg_included_days");
    if (show === drawn && !!df.hidden === !show) return;
    grid.set_column_disp(NXG_CONTRACT_COLUMNS, show);
    grid.reset_grid();
}

frappe.ui.form.on("Quotation", {
    refresh(frm) {
        nxg_toggle_contract_columns(frm);
    },
    deal_type(frm) {
        nxg_toggle_contract_columns(frm);
    },
});

// Default layout with the three contract columns, applied once to each user's saved grid settings.
const NXG_QUOTE_COLUMNS_V2 = [
    { fieldname: "item_code", columns: 2 },
    { fieldname: "uom", columns: 1 },
    { fieldname: "nxg_length", columns: 1 },
    { fieldname: "nxg_breadth", columns: 1 },
    { fieldname: "nxg_height", columns: 1 },
    { fieldname: "nxg_duration", columns: 1 },
    { fieldname: "qty", columns: 1 },
    { fieldname: "nxg_rate_basis", columns: 1 },
    { fieldname: "rate", columns: 1 },
    { fieldname: "nxg_hire_days", columns: 1 },
    { fieldname: "nxg_rate_basis_amount", columns: 1 },
    { fieldname: "nxg_estimated_amount", columns: 1 },
    { fieldname: "nxg_period", columns: 1 },
    { fieldname: "nxg_included_days", columns: 1 },
];

frappe.ui.form.on("Quotation", {
    onload(frm) {
        try {
            const grid = frappe.get_user_settings("Quotation", "GridView") || {};
            const names = (grid["Quotation Item"] || []).map((c) => c.fieldname);
            if (names.includes("nxg_included_days")) return;
            if (names.length && !(names.includes("uom") && names.includes("nxg_period"))) return; // the earlier default above handles this first
            if (sessionStorage.getItem("nxg_quote_cols_v2") === "1") return; // never reload more than once
            sessionStorage.setItem("nxg_quote_cols_v2", "1");
            frappe.model.user_settings.save("Quotation", "GridView", { "Quotation Item": NXG_QUOTE_COLUMNS_V2 }).then(() => location.reload());
        } catch (e) {
            console.warn("Quotation contract columns not applied", e);
        }
    },
});

// Job Type items are offered only on Hire Order Contract quotations; other deals never list them.
function nxg_set_item_query(frm) {
    frm.set_query("item_code", "items", (doc) => {
        const filters = { is_sales_item: 1, has_variants: 0 };
        if (doc.customer) filters.customer = doc.customer;
        if (doc.deal_type === "Hire Order Contract") filters.nxg_job_types_only = 1;
        return { query: "thinknxg_rental.events.job_type.quotation_item_query", filters };
    });
}

frappe.ui.form.on("Quotation", {
    refresh(frm) {
        nxg_set_item_query(frm);
    },
    deal_type(frm) {
        nxg_set_item_query(frm);
    },
});

// Users who were given the earlier 13-column layout (too wide for the grid) get the Hire Order Contract style layout once.
frappe.ui.form.on("Quotation", {
    onload() {
        try {
            const grid = frappe.get_user_settings("Quotation", "GridView") || {};
            const names = (grid["Quotation Item"] || []).map((c) => c.fieldname);
            if (!names.includes("nxg_excess_basis")) return;
            if (localStorage.getItem("nxg_quote_cols_v3") === "1") return;
            localStorage.setItem("nxg_quote_cols_v3", "1");
            frappe.model.user_settings.save("Quotation", "GridView", { "Quotation Item": NXG_QUOTE_COLUMNS_V2 }).then(() => location.reload());
        } catch (e) {
            console.warn("Quotation grid layout not updated", e);
        }
    },
});

// ---------------------------------------------------------------------------------------------
// Material Hire quotations use the Hire Order item columns: Rate Basis, Hire Days, Estimated Amount.
// Amount = Qty x Hire Days / basis days x Rate, the same estimate as the Hire Order (services/utils.py).
// ---------------------------------------------------------------------------------------------
const NXG_BASIS_FACTOR = {"Daily": 1, "Weekly": 7, "Monthly": 30};
const NXG_HIRE_ORDER_COLUMNS = ["nxg_rate_basis", "nxg_hire_days", "nxg_rate_basis_amount", "nxg_estimated_amount"];

function nxg_multiplier(frm, row) {
    if (frm.doc.deal_type === "Material Hire") {
        const days = cint(row.nxg_hire_days);
        return days > 0 ? days / (NXG_BASIS_FACTOR[row.nxg_rate_basis || "Monthly"] || 30) : 1;
    }
    return cint(row.nxg_duration) || 1;
}

function nxg_update_estimate(frm, cdt, cdn) {
    if (frm.doc.deal_type !== "Material Hire") return;
    const row = locals[cdt][cdn];
    frappe.model.set_value(cdt, cdn, {
        nxg_rate_basis_amount: flt(row.qty) * flt(row.rate),
        nxg_estimated_amount: flt(row.qty) * nxg_multiplier(frm, row) * flt(row.rate),
    });
}

function nxg_toggle_hire_order_columns(frm) {
    const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
    const df = grid && grid.get_docfield && grid.get_docfield("nxg_rate_basis");
    if (!df) return; // custom fields not created yet (migrate pending)
    const show = frm.doc.deal_type === "Material Hire";
    if (!!df.hidden === !show) return;
    grid.set_column_disp(NXG_HIRE_ORDER_COLUMNS, show);
    grid.reset_grid();
}

frappe.ui.form.on("Quotation", {
    refresh(frm) {
        nxg_toggle_hire_order_columns(frm);
    },
    deal_type(frm) {
        nxg_toggle_hire_order_columns(frm);
    },
    onload() {
        try {
            const grid = frappe.get_user_settings("Quotation", "GridView") || {};
            const names = (grid["Quotation Item"] || []).map((c) => c.fieldname);
            if (!names.length || names.includes("nxg_rate_basis")) return;
            if (localStorage.getItem("nxg_quote_cols_v4") === "1") return;
            localStorage.setItem("nxg_quote_cols_v4", "1");
            frappe.model.user_settings.save("Quotation", "GridView", { "Quotation Item": NXG_QUOTE_COLUMNS_V2 }).then(() => location.reload());
        } catch (e) {
            console.warn("Quotation grid layout not updated", e);
        }
    },
});

frappe.ui.form.on("Quotation Item", {
    qty(frm, cdt, cdn) {
        nxg_update_estimate(frm, cdt, cdn);
    },
    rate(frm, cdt, cdn) {
        nxg_update_estimate(frm, cdt, cdn);
    },
    nxg_hire_days(frm, cdt, cdn) {
        nxg_update_estimate(frm, cdt, cdn);
        frm.cscript.calculate_taxes_and_totals();
    },
    nxg_rate_basis(frm, cdt, cdn) {
        nxg_update_estimate(frm, cdt, cdn);
        frm.cscript.calculate_taxes_and_totals();
    },
});

// Users with a saved Quotation grid layout get Rate Basis Amount before Estimated Amount, once.
frappe.ui.form.on("Quotation", {
    onload() {
        try {
            const grid = frappe.get_user_settings("Quotation", "GridView") || {};
            const cols = grid["Quotation Item"];
            if (!cols || !cols.length || !cols.some((c) => c.fieldname === "nxg_rate_basis")) return;
            if (cols.some((c) => c.fieldname === "nxg_rate_basis_amount")) return;
            if (localStorage.getItem("nxg_quote_cols_v5") === "1") return;
            localStorage.setItem("nxg_quote_cols_v5", "1");
            const next = cols.slice();
            const at = next.findIndex((c) => c.fieldname === "nxg_estimated_amount");
            next.splice(at >= 0 ? at : next.length, 0, { fieldname: "nxg_rate_basis_amount", columns: 1 });
            frappe.model.user_settings.save("Quotation", "GridView", { "Quotation Item": next }).then(() => location.reload());
        } catch (e) {
            console.warn("Quotation grid layout not updated", e);
        }
    },
});

// ---- Hire period -> item rows: rate basis follows Default Rate Basis, hire days = Return - From ----
function nxg_is_material_hire(frm) {
    return frm.doc.deal_type === "Material Hire";
}

function nxg_period_days(frm) {
    if (!frm.doc.nxg_required_from || !frm.doc.nxg_expected_return_date) return null;
    const d = frappe.datetime.get_diff(frm.doc.nxg_expected_return_date, frm.doc.nxg_required_from);
    return d >= 0 ? d : null;
}

function nxg_apply_hire_period(frm, what) {
    if (!nxg_is_material_hire(frm)) return;
    const days = nxg_period_days(frm);
    (frm.doc.items || []).forEach((row) => {
        if ((what === "all" || what === "basis") && frm.doc.nxg_default_rate_basis
            && row.nxg_rate_basis !== frm.doc.nxg_default_rate_basis) {
            frappe.model.set_value(row.doctype, row.name, "nxg_rate_basis", frm.doc.nxg_default_rate_basis);
        }
        if ((what === "all" || what === "days") && days !== null && row.nxg_hire_days !== days) {
            frappe.model.set_value(row.doctype, row.name, "nxg_hire_days", days);
        }
    });
}

frappe.ui.form.on("Quotation", {
    nxg_default_rate_basis(frm) { nxg_apply_hire_period(frm, "basis"); },
    nxg_required_from(frm) { nxg_apply_hire_period(frm, "days"); },
    nxg_expected_return_date(frm) { nxg_apply_hire_period(frm, "days"); },
    deal_type(frm) { nxg_apply_hire_period(frm, "all"); },
});

// new rows pick up the header values; Hire Days stays editable afterwards
frappe.ui.form.on("Quotation Item", {
    items_add(frm, cdt, cdn) {
        if (!nxg_is_material_hire(frm)) return;
        const days = nxg_period_days(frm);
        if (frm.doc.nxg_default_rate_basis) frappe.model.set_value(cdt, cdn, "nxg_rate_basis", frm.doc.nxg_default_rate_basis);
        if (days !== null) frappe.model.set_value(cdt, cdn, "nxg_hire_days", days);
    },
});
