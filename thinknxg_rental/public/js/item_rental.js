// Item form: the Rental section (only with Maintain Stock).
// * Rental Classification: Stock, or Stock + Asset (every unit identified by its serial number).
// * Rental Item Profile panel: the profile's own fields, drawn from the Rental Item Profile DocType.
//   Values are sent with the Item save (nxg_rental_profile, not an Item field) and saved into the
//   profile in the same transaction (services/item_rental.py). The profile stays the only place they live.
frappe.provide("thinknxg_rental.item");

thinknxg_rental.item.render = function (frm) {
	const field = frm.fields_dict.nxg_rental_profile_html;
	if (!field) return;
	const $w = field.$wrapper.empty();
	if (!frm.doc.is_stock_item) return;
	$w.html(`<div class="text-muted small">${__("Loading rental settings…")}</div>`);
	frappe
		.call({ method: "thinknxg_rental.services.item_rental.get_item_rental_profile", args: { item_code: frm.is_new() ? null : frm.doc.name } })
		.then((r) => thinknxg_rental.item.draw(frm, $w, r.message));
};

thinknxg_rental.item.draw = function (frm, $w, data) {
	$w.empty();
	const state = (frm._nxg_rental = { data, touched: false, group: null });
	if (!data.exists && !data.can_create) {
		$w.html(`<p class="text-muted small">${__("This item has no Rental Item Profile, and you are not allowed to create one.")}</p>`);
		return;
	}
	const readonly = !data.can_write;
	const mark = () => {
		if (state.ready && !readonly) {
			state.touched = true;
			frm.dirty();
		}
	};
	const fields = [
		{
			fieldname: "nxg_enabled",
			fieldtype: "Check",
			label: __("Rental Item Profile"),
			description: __("Rent this item: its rates, deposit and damage charges are kept in its Rental Item Profile."),
			default: data.enabled ? 1 : 0,
			read_only: readonly,
			onchange: mark,
		},
	];
	// the profile's own layout: its sections and columns, shown once the switch is on
	data.fields
		.filter((df) => df.fieldname !== "disabled")
		.forEach((df) => {
			if (df.fieldtype === "Section Break" || df.fieldtype === "Column Break") {
				fields.push({ fieldname: "nxg_" + df.fieldname, fieldtype: df.fieldtype, label: df.label, depends_on: "eval:doc.nxg_enabled" });
				return;
			}
			fields.push(Object.assign({}, df, { depends_on: "eval:doc.nxg_enabled", read_only: readonly, reqd: 0, onchange: mark }));
		});
	const body = $(`<div class="nxg-rental-profile"></div>`).appendTo($w);
	const group = new frappe.ui.FieldGroup({ fields, body: body[0] });
	group.make();
	const values = Object.assign({}, data.values, { nxg_enabled: data.enabled ? 1 : 0 });
	if (!data.exists)
		data.fields.forEach((df) => !["Section Break", "Column Break"].includes(df.fieldtype) && df.default !== null && df.default !== undefined && (values[df.fieldname] = df.default));
	group.set_values(values).then(() => (state.ready = true));
	state.group = group;
	if (data.exists) {
		$(`<a class="small" href="/app/rental-item-profile/${encodeURIComponent(frm.doc.name)}">${__("Open Rental Item Profile")}</a>`).appendTo($w);
	}
};

thinknxg_rental.item.payload = function (frm) {
	const state = frm._nxg_rental;
	if (!state || !state.group || !state.touched) return null;
	const v = state.group.get_values(true) || {};
	const values = {};
	state.data.fields.forEach((df) => {
		if (!["Section Break", "Column Break"].includes(df.fieldtype) && df.fieldname in v && df.fieldname !== "disabled") values[df.fieldname] = v[df.fieldname];
	});
	return { enabled: v.nxg_enabled ? 1 : 0, values };
};

frappe.ui.form.on("Item", {
	refresh(frm) {
		thinknxg_rental.item.render(frm);
	},
	is_stock_item(frm) {
		const state = frm._nxg_rental;
		if (!frm.doc.is_stock_item) {
			if (state && state.group && state.group.get_value("nxg_enabled")) {
				state.group.set_value("nxg_enabled", 0);
				state.touched = true;
				frappe.show_alert({ message: __("Rental Item Profile switched off: it needs Maintain Stock."), indicator: "orange" });
			}
			if (frm.doc.nxg_rental_classification !== "Stock") frm.set_value("nxg_rental_classification", "Stock");
		} else if (!state) {
			thinknxg_rental.item.render(frm);
		}
	},
	nxg_rental_classification(frm) {
		const asset = frm.doc.nxg_rental_classification === "Stock + Asset";
		if (asset && !frm.doc.has_serial_no) {
			frm.set_value("has_serial_no", 1);
			frappe.show_alert({ message: __("Has Serial No switched on: each unit gets a serial number when it is received."), indicator: "blue" });
		} else if (!asset && frm.doc.has_serial_no) {
			frm.set_value("has_serial_no", 0);
		}
	},
	has_serial_no(frm) {
		if (!frm.doc.is_stock_item) return;
		const want = frm.doc.has_serial_no ? "Stock + Asset" : "Stock";
		if (frm.doc.nxg_rental_classification !== want) frm.set_value("nxg_rental_classification", want);
	},
	validate(frm) {
		const payload = thinknxg_rental.item.payload(frm);
		if (payload && payload.enabled && !frm.doc.is_stock_item) {
			frappe.throw(__("A Rental Item Profile needs Maintain Stock."));
		}
		frm.doc.nxg_rental_profile = payload ? JSON.stringify(payload) : null;
	},
	after_save(frm) {
		delete frm.doc.nxg_rental_profile;
		frm._nxg_rental = null;
	},
});
