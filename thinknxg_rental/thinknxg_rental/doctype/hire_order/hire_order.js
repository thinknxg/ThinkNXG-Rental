frappe.provide("thinknxg_rental");

thinknxg_rental.fetch_rental_details = function (frm, cdt, cdn, extra) {
	const row = locals[cdt][cdn];
	if (!row.item_code) return;
	frappe.call({
		method: "thinknxg_rental.services.utils.get_item_rental_details",
		args: {
			item_code: row.item_code,
			customer: frm.doc.customer,
			rate_basis: row.rate_basis || frm.doc.rate_basis,
			posting_date: frm.doc.order_date || frm.doc.contract_date,
		},
		callback(r) {
			if (!r.message) return;
			const m = r.message;
			const values = { item_name: m.item_name, uom: m.uom, rate_basis: m.rate_basis, rate: m.rate };
			(extra || []).forEach((f) => (values[f] = m[f]));
			frappe.model.set_value(cdt, cdn, values);
		},
	});
};

frappe.ui.form.on("Hire Order", {
	setup(frm) {
		frm.set_query("item_code", "items", () => ({ filters: { is_stock_item: 1, disabled: 0 } }));
		frm.set_query("rental_site", () => ({ filters: { customer: frm.doc.customer, disabled: 0 } }));
	},
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		if (frm.doc.status === "Open") {
			frm.add_custom_button(
				__("Rental Contract"),
				() => frappe.model.open_mapped_doc({ method: "thinknxg_rental.thinknxg_rental.doctype.hire_order.hire_order.make_contract", frm }),
				__("Create")
			);
		}
		if (["Open", "Contracted"].includes(frm.doc.status)) {
			frm.add_custom_button(
				__("Material Reservation"),
				() => frappe.model.open_mapped_doc({ method: "thinknxg_rental.thinknxg_rental.doctype.hire_order.hire_order.make_reservation", frm }),
				__("Create")
			);
		}
		frm.page.set_inner_btn_group_as_primary(__("Create"));
	},
});

frappe.ui.form.on("Hire Order Item", {
	item_code(frm, cdt, cdn) {
		thinknxg_rental.fetch_rental_details(frm, cdt, cdn, ["security_deposit_rate", "replacement_value", "available_qty"]);
	},
	rate_basis(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "rate", 0);
		thinknxg_rental.fetch_rental_details(frm, cdt, cdn);
	},
});

// Rate Basis Amount = Qty x Hire Rate
function nxg_rate_basis_amount(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    frappe.model.set_value(cdt, cdn, "rate_basis_amount", flt(row.qty) * flt(row.rate));
}

frappe.ui.form.on("Hire Order Item", {
    qty(frm, cdt, cdn) {
        nxg_rate_basis_amount(frm, cdt, cdn);
    },
    rate(frm, cdt, cdn) {
        nxg_rate_basis_amount(frm, cdt, cdn);
    },
});

// A user who saved their own grid columns gets the new column next to Estimated Amount, once.
frappe.ui.form.on("Hire Order", {
    onload() {
        try {
            const grid = frappe.get_user_settings("Hire Order", "GridView") || {};
            const cols = grid["Hire Order Item"];
            if (!cols || !cols.length || cols.some((c) => c.fieldname === "rate_basis_amount")) return;
            if (localStorage.getItem("nxg_ho_cols_v1") === "1") return;
            localStorage.setItem("nxg_ho_cols_v1", "1");
            const next = cols.slice();
            const at = next.findIndex((c) => c.fieldname === "estimated_amount");
            next.splice(at >= 0 ? at : next.length, 0, { fieldname: "rate_basis_amount", columns: 1 });
            frappe.model.user_settings.save("Hire Order", "GridView", { "Hire Order Item": next }).then(() => location.reload());
        } catch (e) {
            console.warn("Hire Order grid layout not updated", e);
        }
    },
});
