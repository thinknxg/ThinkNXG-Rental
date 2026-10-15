frappe.ui.form.on("Hire Order Contract", {
	setup(frm) {
		frm.set_query("job_type", "items", () => ({ query: "thinknxg_rental.events.job_type.job_type_query" }));
		frm.set_query("nxg_item_code", "items", () => ({ query: "thinknxg_rental.events.job_type.quotation_item_query", filters: { nxg_job_types_only: 1 } }));
		frm.set_query("item_code", "materials", () => ({ filters: { is_stock_item: 1, disabled: 0 } }));
		frm.set_query("job_type", "materials", () => ({ query: "thinknxg_rental.events.job_type.job_type_query" }));
		frm.set_query("rental_site", () => ({ filters: { customer: frm.doc.customer, disabled: 0 } }));
		frm.set_query("taxes_and_charges", () => ({ filters: { company: frm.doc.company } }));
		frm.set_query("cost_center", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
	},
	make_jcr(frm) {
		const method = "thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract.make_jcr";
		frappe.model.open_mapped_doc({ method, frm });
	},
	refresh(frm) {
		const base = "thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract.";
		if (frm.doc.docstatus === 0) {
			frm.set_intro(
				__("Physical Rental Items are filled from the job types when you first save. Edit them to match the actual job, or rebuild them after changing the jobs.")
			);
			if (!frm.is_new()) {
				frm.add_custom_button(__("Rebuild Materials from Job Types"), () =>
					frappe.confirm(__("Replace the Physical Rental Items table with a fresh explosion of the job types?"), () =>
						frm.call("refresh_materials").then(() => frm.reload_doc())
					)
				);
			}
			return;
		}
		if (frm.doc.docstatus !== 1) return;
		const create = (label, method) =>
			frm.add_custom_button(__(label), () => frappe.model.open_mapped_doc({ method: base + method, frm }), __("Create"));
		if (frm.doc.status === "Open") create("Rental Contract", "make_rental_contract");
		create("Material Reservation", "make_reservation");
		frm.add_custom_button(__("Job Completion Report (JCR)"), () => frm.trigger("make_jcr"), __("Create"));
		frm.page.set_inner_btn_group_as_primary(__("Create"));
	},
});

frappe.ui.form.on("Hire Order Contract Item", {
	qty: (frm, cdt, cdn) => set_contract_amount(cdt, cdn),
	contract_rate: (frm, cdt, cdn) => set_contract_amount(cdt, cdn),
});

function set_contract_amount(cdt, cdn) {
	const d = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "contract_amount", flt(d.qty) * flt(d.contract_rate));
}

// Physical Rental Items (Materials): Job Type, Rental Item and Qty Per Job are editable and are filled
// from the job type's rental items on the Item master. Total Qty follows Qty Per Job.
function nxg_job_type_items(job_type) {
        if (!job_type) return Promise.resolve([]);
        return frappe.db.get_doc("Job Type", job_type).then((doc) => doc.rental_items || []).catch(() => []);
}

function nxg_fill_material(row, c) {
        Object.assign(row, { item_code: c.item_code, item_name: c.item_name, uom: c.uom, qty_per_job: flt(c.qty), qty: flt(c.qty) });
}

frappe.ui.form.on("Hire Order Contract Material", {
        job_type(frm, cdt, cdn) {
                const row = locals[cdt][cdn];
                nxg_job_type_items(row.job_type).then((list) => {
                        if (!list.length) return;
                        const match = list.find((c) => c.item_code === row.item_code);
                        if (match) {
                                // the row's item belongs to this job type: only fetch its quantity
                                row.qty_per_job = flt(match.qty);
                                row.qty = flt(match.qty);
                        } else {
                                nxg_fill_material(row, list[0]);
                                const present = new Set((frm.doc.materials || []).filter((m) => m.job_type === row.job_type).map((m) => m.item_code));
                                list.slice(1).forEach((c) => {
                                        if (present.has(c.item_code)) return;
                                        const child = frm.add_child("materials");
                                        child.job_type = row.job_type;
                                        nxg_fill_material(child, c);
                                });
                        }
                        frm.refresh_field("materials");
                });
        },
        item_code(frm, cdt, cdn) {
                const row = locals[cdt][cdn];
                nxg_job_type_items(row.job_type).then((list) => {
                        const match = list.find((c) => c.item_code === row.item_code);
                        if (!match) return;
                        row.qty_per_job = flt(match.qty);
                        row.qty = flt(match.qty);
                        frm.refresh_field("materials");
                });
        },
        qty_per_job(frm, cdt, cdn) {
                frappe.model.set_value(cdt, cdn, "qty", flt(locals[cdt][cdn].qty_per_job));
        },
});


// Default grid columns for the contract items: quotation details first, then the two charges users must fill.
const NXG_HOC_ITEM_COLUMNS = [
    ["nxg_item_code", 1], ["nxg_uom", 1], ["nxg_length", 1], ["nxg_breadth", 1], ["nxg_height", 1],
    ["nxg_duration", 1], ["nxg_qty", 1], ["nxg_period", 1], ["qty", 1], ["included_days", 1], ["contract_rate", 1],
];

function nxg_apply_default_item_columns(frm) {
    const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
    if (!grid) return;
    const flag = "nxg_hoc_item_cols_v2";
    try {
        if (localStorage.getItem(flag) === "1") return;
    } catch (e) {}
    const cols = NXG_HOC_ITEM_COLUMNS.map(([fieldname, columns]) => ({ fieldname, columns }));
    const us = frappe.get_user_settings("Hire Order Contract") || {};
    const gv = Object.assign({}, us.GridView || {});
    gv["Hire Order Contract Item"] = cols;
    frappe.model.user_settings.save("Hire Order Contract", "GridView", gv);
    if (grid.setup_user_defined_columns) grid.setup_user_defined_columns();
    if (grid.reset_grid) grid.reset_grid();
    try {
        localStorage.setItem(flag, "1");
    } catch (e) {}
}

frappe.ui.form.on("Hire Order Contract", {
    onload(frm) {
        nxg_apply_default_item_columns(frm);
    },
    refresh(frm) {
        nxg_apply_default_item_columns(frm);
    },
});

// Quantity = Length x Breadth x Height (as on the Quotation); No. of Jobs follows the Quantity.
function nxg_dimension_qty(cdt, cdn) {
    const row = locals[cdt][cdn];
    const length = flt(row.nxg_length), breadth = flt(row.nxg_breadth), height = flt(row.nxg_height);
    if (!(length && breadth && height)) return;
    frappe.model.set_value(cdt, cdn, "nxg_qty", flt(length * breadth * height, precision("nxg_qty", row)));
}

frappe.ui.form.on("Hire Order Contract Item", {
    nxg_length: (frm, cdt, cdn) => nxg_dimension_qty(cdt, cdn),
    nxg_breadth: (frm, cdt, cdn) => nxg_dimension_qty(cdt, cdn),
    nxg_height: (frm, cdt, cdn) => nxg_dimension_qty(cdt, cdn),
    nxg_qty: (frm, cdt, cdn) => {
        const row = locals[cdt][cdn];
        if (flt(row.nxg_qty) > 0) frappe.model.set_value(cdt, cdn, "qty", flt(row.nxg_qty));
    },
});
