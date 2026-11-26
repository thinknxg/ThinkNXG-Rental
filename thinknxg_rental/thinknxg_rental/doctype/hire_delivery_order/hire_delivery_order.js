frappe.ui.form.on("Hire Delivery Order", {
	setup(frm) {
		frm.set_query("rental_contract", () => ({ filters: { docstatus: 1, status: ["not in", ["Completed", "Cancelled"]] } }));
		frm.set_query("source_document", () => ({ filters: { docstatus: 1, status: "Contracted" } }));
		frm.set_query("rental_material_reservation", () => ({
			filters: { docstatus: 1, rental_contract: frm.doc.rental_contract, status: ["in", ["Reserved", "Partially Reserved"]] },
		}));
		// own rows: own rental warehouses; cross hire rows: cross hire warehouses (any location)
		thinknxg_rental.rental_warehouses().then((list) => {
			frm.set_query("source_warehouse", "items", (doc, cdt, cdn) => {
				const kind = locals[cdt][cdn].ownership === "Cross Hire" ? "Cross Hire" : "Own";
				return { filters: { name: ["in", list.filter((w) => w.category === kind).map((w) => w.warehouse)], company: frm.doc.company } };
			});
		});
		frm.set_query("cross_hire_order", "items", () => ({ filters: { docstatus: 1, status: ["!=", "Completed"] } }));
		frm.set_query("batch_no", "items", (doc, cdt, cdn) => ({ filters: { item: locals[cdt][cdn].item_code } }));
	},
	source_type(frm) {
		if (frm.doc.docstatus === 0 && !frm.doc.rental_contract) frm.set_value("source_document", null);
	},
	source_document(frm) {
		// start a delivery from the Hire Order or Hire Order Contract: find its Rental Contract and lines
		if (!frm.doc.source_type || !frm.doc.source_document || frm.doc.rental_contract || frm.doc.docstatus !== 0) return;
		frappe.call({
			method: "thinknxg_rental.thinknxg_rental.doctype.hire_delivery_order.hire_delivery_order.get_delivery_for_source",
			args: { source_type: frm.doc.source_type, source_document: frm.doc.source_document },
			callback(r) {
				if (!r.message) return;
				frm.doc.rental_contract = r.message.rental_contract;
				frm.refresh_field("rental_contract");
				frm.clear_table("items");
				r.message.items.forEach((row) => frm.add_child("items", row));
				frm.refresh_field("items");
			},
		});
	},
	rental_material_reservation(frm) {
		if (frm.doc.rental_contract && frm.doc.docstatus === 0) frm.trigger("get_items");
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Items from Contract"), () => frm.trigger("get_items"));
			frm.add_custom_button(__("Add Additional Item"), () => {
				if (!frm.doc.rental_contract) return frappe.msgprint(__("Select a Rental Contract first"));
				const row = frm.add_child("items", { additional_item: 1, ownership: "Own" });
				frm.refresh_field("items");
				frm.scroll_to_field("items");
				return row;
			}, __("Get Items"));
		}
	},
	rental_contract(frm) {
		frm._contract_info = null;
		if (frm.doc.rental_contract && !(frm.doc.items || []).some((d) => d.item_code)) frm.trigger("get_items");
	},
	get_items(frm) {
		if (!frm.doc.rental_contract) return frappe.msgprint(__("Select a Rental Contract first"));
		frappe.call({
			method: "thinknxg_rental.thinknxg_rental.doctype.hire_delivery_order.hire_delivery_order.get_dispatch_items",
			args: { rental_contract: frm.doc.rental_contract, reservation: frm.doc.rental_material_reservation || null },
			callback(r) {
				const rows = r.message || [];
				frm.clear_table("items");
				rows.forEach((row) => frm.add_child("items", row));
				frm.refresh_field("items");
				if (!rows.length) {
					frappe.msgprint(__("Nothing can be dispatched right now: the contract is fully delivered, or no free yard stock / received cross-hire material is available."));
				}
			},
		});
	},
});


// ---- Customer and Rental Source follow the Rental Contract, also when the form is pre-filled ----
function nxg_hdo_fill_from_contract(frm) {
    if (!frm.doc.rental_contract || frm.doc.docstatus !== 0) return;
    frappe.db.get_value("Rental Contract", frm.doc.rental_contract, ["customer", "customer_name", "source_type", "source_document"]).then((r) => {
        const v = (r && r.message) || {};
        const vals = {};
        ["customer", "customer_name", "source_type", "source_document"].forEach((f) => { if (v[f] && frm.doc[f] !== v[f]) vals[f] = v[f]; });
        if (Object.keys(vals).length) frm.set_value(vals);
    });
}

frappe.ui.form.on("Hire Delivery Order", {
    refresh(frm) { if (frm.is_new()) nxg_hdo_fill_from_contract(frm); },
    rental_contract(frm) { nxg_hdo_fill_from_contract(frm); },
});


// Dispatch Date follows the Rental Contract's Contract Date (falls back to the default when the contract has none)
function nxg_hdo_set_dispatch_date(frm, force) {
    if (!frm.doc.rental_contract || frm.doc.docstatus !== 0) return;
    if (!force && frm.doc.posting_date && frm.doc.posting_date !== frappe.datetime.get_today()) return;
    frappe.db.get_value("Rental Contract", frm.doc.rental_contract, "contract_date").then((r) => {
        const d = r && r.message && r.message.contract_date;
        if (d && frm.doc.posting_date !== d) frm.set_value("posting_date", d);
    });
}

frappe.ui.form.on("Hire Delivery Order", {
    rental_contract(frm) { nxg_hdo_set_dispatch_date(frm, true); },
    refresh(frm) { if (frm.is_new()) nxg_hdo_set_dispatch_date(frm, false); },
});


// ---- Additional material: an item that is not on the Rental Contract is ticked as Additional automatically ----
function nxg_hdo_contract_info(frm) {
	if (!frm.doc.rental_contract) return Promise.resolve({ items: [], job_types: [] });
	if (frm._contract_info && frm._contract_info.contract === frm.doc.rental_contract) return Promise.resolve(frm._contract_info);
	return frappe.xcall("thinknxg_rental.thinknxg_rental.doctype.hire_delivery_order.hire_delivery_order.get_contract_info", {
		rental_contract: frm.doc.rental_contract,
	}).then((info) => {
		frm._contract_info = Object.assign({ contract: frm.doc.rental_contract }, info);
		return frm._contract_info;
	});
}

frappe.ui.form.on("Hire Delivery Order", {
	refresh(frm) {
		// the Job Type column is only for a job type contract
		nxg_hdo_contract_info(frm).then((info) => {
			const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
			if (grid) grid.update_docfield_property("job_type", "hidden", info.job_types.length ? 0 : 1);
			frm.set_query("job_type", "items", () => ({ filters: { name: ["in", info.job_types] } }));
			frm.refresh_field("items");
		});
	},
});

frappe.ui.form.on("Hire Delivery Item", {
	item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item_code || !frm.doc.rental_contract || frm.doc.docstatus !== 0) return;
		nxg_hdo_contract_info(frm).then((info) => {
			if (!info.items.includes(row.item_code) && !row.additional_item) {
				frappe.model.set_value(cdt, cdn, "additional_item", 1);
				frappe.show_alert({ message: __("{0} is not on the contract: added as an Additional Item.", [row.item_code]), indicator: "blue" });
			}
			if (info.job_types.length === 1 && !row.job_type && (row.additional_item || !info.items.includes(row.item_code))) {
				frappe.model.set_value(cdt, cdn, "job_type", info.job_types[0]);
			}
		});
	},
});
