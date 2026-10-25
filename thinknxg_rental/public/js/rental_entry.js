// thinkNXG Rental admin portal: one form for every portal document (see portal/entry.py).
// The page hands over the document and the fields to show; this script draws the header fields and
// the item tables, and saves through thinknxg_rental.portal.entry.save_entry, which saves the real
// DocType. Nothing is kept in the browser beyond the open form.
(function () {
	const boot = window.rp_entry;
	const form = document.getElementById("rp-entry");
	if (!boot || !form) return;

	const doc = boot.doc;
	const NUM = ["Int", "Float", "Currency", "Percent"];
	const box = document.getElementById("ra-msg");
	const say = (text, tone) => {
		box.textContent = text;
		box.dataset.tone = tone || "";
		box.hidden = !text;
	};
	const call = (method, args, type) =>
		new Promise((resolve, reject) =>
			frappe.call({ method, args, type: type || "GET", callback: (r) => resolve(r.message), error: reject })
		);
	const el = (tag, attrs, ...children) => {
		const node = document.createElement(tag);
		Object.entries(attrs || {}).forEach(([k, v]) => {
			if (v === null || v === undefined || v === false) return;
			if (k === "text") node.textContent = v;
			else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
			else node.setAttribute(k, v === true ? "" : v);
		});
		children.flat().forEach((c) => c && node.append(c));
		return node;
	};
	const fmt = (value, fieldtype) => {
		if (value === null || value === undefined || value === "") return "";
		if (NUM.includes(fieldtype)) {
			const n = Number(value);
			const digits = fieldtype === "Currency" ? 2 : Number.isInteger(n) ? 0 : 2;
			return n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
		}
		if (fieldtype === "Date" && frappe.datetime && frappe.datetime.str_to_user) return frappe.datetime.str_to_user(value);
		if (fieldtype === "Check") return Number(value) ? __("Yes") : __("No");
		return String(value);
	};

	// show_if {field: [values]} looks at the header, so a column follows the Deal Type.
	const visible = (spec) => Object.entries(spec.show_if || {}).every(([f, values]) => values.includes(doc[f]));
	const link_doctype = (spec) => (spec.fieldtype === "Dynamic Link" ? doc[spec.options] : spec.options);
	const resolve_filters = (filters, row) => {
		const out = {};
		Object.entries(filters || {}).forEach(([k, v]) => {
			if (typeof v === "string" && v.startsWith("$")) {
				const value = (row && row[v.slice(1)]) || doc[v.slice(1)];
				if (value) out[k] = value;
			} else out[k] = v;
		});
		return out;
	};

	let list_id = 0;
	function input_for(spec, target, on_change, row) {
		const id = "rp-f-" + spec.fieldname + "-" + list_id++;
		const value = target[spec.fieldname];
		const set = (v) => {
			target[spec.fieldname] = v;
			on_change && on_change(spec, v);
		};
		let input;
		if (spec.fieldtype === "Select") {
			input = el("select", { id, onchange: (e) => set(e.target.value) },
				spec.choices.map((c) => el("option", { value: c, selected: (value || "") === c, text: c ? __(c) : "" })));
		} else if (spec.fieldtype === "Check") {
			input = el("input", { id, type: "checkbox", checked: !!Number(value), onchange: (e) => set(e.target.checked ? 1 : 0) });
		} else if (["Small Text", "Text", "Long Text", "Text Editor"].includes(spec.fieldtype)) {
			input = el("textarea", { id, onchange: (e) => set(e.target.value) });
			input.value = value || "";
		} else if (NUM.includes(spec.fieldtype)) {
			input = el("input", { id, type: "number", step: spec.fieldtype === "Int" ? "1" : "any", inputmode: "decimal",
				onchange: (e) => set(e.target.value === "" ? null : Number(e.target.value)) });
			input.value = value === null || value === undefined ? "" : value;
		} else if (spec.fieldtype === "Date") {
			input = el("input", { id, type: "date", onchange: (e) => set(e.target.value || null) });
			input.value = value || "";
		} else if (["Link", "Dynamic Link"].includes(spec.fieldtype)) {
			const list = el("datalist", { id: id + "-list" });
			input = el("input", { id, list: id + "-list", autocomplete: "off", onchange: (e) => set(e.target.value.trim() || null) });
			input.value = value || "";
			let timer;
			input.addEventListener("input", () => {
				clearTimeout(timer);
				timer = setTimeout(() => {
					const doctype = link_doctype(spec);
					if (!doctype) return;
					call("frappe.desk.search.search_link", {
						doctype, txt: input.value, page_length: 15,
						filters: JSON.stringify(resolve_filters(spec.filters, row)),
						reference_doctype: boot.doctype,
					}).then((results) => {
						list.replaceChildren(...(results || []).map((r) => el("option", { value: r.value, label: r.description || r.label || "" })));
					});
				}, 200);
			});
			input.addEventListener("focus", () => input.dispatchEvent(new Event("input")), { once: true });
			return [input, list];
		} else {
			input = el("input", { id, type: "text", onchange: (e) => set(e.target.value) });
			input.value = value || "";
		}
		return [input];
	}

	// a selected link copies values from its record (item name and UOM, customer name, ...)
	function fetch_into(spec, value, target, redraw) {
		const fields = spec.fetch || {};
		const keys = Object.keys(fields);
		if (!keys.length || !value) return;
		call("thinknxg_rental.portal.entry.get_link_values", {
			doctype: link_doctype(spec), name: value, fields: JSON.stringify(Object.values(fields)),
		}).then((values) => {
			keys.forEach((k) => (target[k] = (values || {})[fields[k]] ?? target[k]));
			redraw();
		});
	}

	// ------------------------------------------------------------------ header
	const header = el("div", { class: "rp-fields rp-entry-head" });
	function draw_header() {
		header.replaceChildren(
			...boot.header.filter(visible).map((spec) => {
				const label = el("label", { text: spec.label }, spec.reqd && boot.editable && !spec.ro ? el("span", { class: "rp-req", text: " *" }) : null);
				let body;
				if (!boot.editable || spec.ro) {
					body = [el("div", { class: "rp-value", text: fmt(doc[spec.fieldname], spec.fieldtype) || "–" })];
				} else {
					body = input_for(spec, doc, (s, v) => {
						if (s.fieldtype === "Select" || Object.keys(s.fetch || {}).length) {
							fetch_into(s, v, doc, draw_all);
							if (!Object.keys(s.fetch || {}).length) draw_all();
						}
						if (s.fieldname === (boot.fill || {}).needs && v && !(doc[boot.fill.table] || []).some((r) => r.item_code || r.job_type)) fill();
					});
					label.setAttribute("for", body[0].id);
				}
				return el("div", { class: spec.wide ? "rp-field rp-field--wide" : "rp-field" }, label, ...body);
			})
		);
	}

	// ------------------------------------------------------------------ item tables
	// Columns share the whole width by weight; headings wrap instead of being cut off.
	const tables = el("div");
	function draw_tables() {
		tables.replaceChildren(
			...boot.tables.map((t) => {
				const rows = (doc[t.fieldname] = doc[t.fieldname] || []);
				const editable = boot.editable && !t.readonly;
				if (t.readonly && !rows.length) return null;
				const cols = t.columns.filter(visible);
				// One unit of weight is at least UNIT rem. A column is never narrower than its longest heading
				// word (or a usable dropdown), so headings wrap between words, never inside one; below that
				// width the table scrolls sideways.
				const UNIT = 2.9;
				const weight = (c) => {
					const word = Math.max(...c.label.split(/\s+/).map((w) => w.length)) + (c.reqd && editable ? 1 : 0);
					const floor = Math.max(word * 0.56 + 1.1, c.fieldtype === "Select" && editable ? 5.6 : 0) / UNIT;
					return Math.max(c.w, floor);
				};
				const total = cols.reduce((s, c) => s + weight(c), 0) + 0.6 + (editable ? 0.6 : 0);
				const pct = (w) => ((w / total) * 100).toFixed(2) + "%";
				const table = el("table", { class: "rp-grid", style: `min-inline-size:${(total * UNIT).toFixed(1)}rem` },
					el("colgroup", {}, el("col", { style: `inline-size:${pct(0.6)}` }), cols.map((c) => el("col", { style: `inline-size:${pct(weight(c))}` })),
						editable ? el("col", { style: `inline-size:${pct(0.6)}` }) : null),
					el("thead", {}, el("tr", {},
						el("th", { scope: "col", class: "rp-num", text: "#" }),
						cols.map((c) => el("th", { scope: "col", class: NUM.includes(c.fieldtype) ? "rp-num" : null },
							c.label, c.reqd && editable && !c.ro ? el("span", { class: "rp-req", text: " *" }) : null)),
						editable ? el("th", { scope: "col" }, el("span", { class: "rp-sr", text: __("Remove") })) : null)),
					el("tbody", {}, rows.map((row, i) => el("tr", {},
						el("td", { class: "rp-num rp-idx", text: i + 1 }),
						cols.map((c) => {
							const cell = el("td", { class: NUM.includes(c.fieldtype) ? "rp-num" : null, "data-label": c.label });
							if (!editable || c.ro) cell.append(el("span", { class: "rp-value", text: fmt(row[c.fieldname], c.fieldtype) }));
							else {
								const parts = input_for(c, row, (s, v) => fetch_into(s, v, row, draw_tables), row);
								parts[0].setAttribute("aria-label", `${c.label}, ${__("row")} ${i + 1}`);
								cell.append(...parts);
							}
							return cell;
						}),
						editable ? el("td", { class: "rp-act" }, el("button", { type: "button", class: "rp-btn rp-btn--plain", text: "×",
							"aria-label": __("Remove row {0}", [i + 1]), onclick: () => { rows.splice(i, 1); draw_tables(); } })) : null
					))),
				);
				return el("section", { class: "rp-section" },
					el("div", { class: "rp-head rp-head--table" }, el("h2", { text: t.label }),
						editable ? el("div", { class: "rp-actions" },
							boot.fill && boot.fill.table === t.fieldname ? el("button", { type: "button", class: "rp-btn", text: __(boot.fill.label), onclick: fill }) : null,
							el("button", { type: "button", class: "rp-btn", text: __("Add row"), onclick: () => { rows.push({}); draw_tables(); } })
						) : null),
					rows.length ? el("div", { class: "rp-grid-wrap" }, table) : el("p", { class: "rp-none", text: __("No rows yet.") })
				);
			})
		);
	}

	function fill() {
		const f = boot.fill;
		if (!doc[f.needs]) return say(__("Fill in {0} first.", [(boot.header.find((h) => h.fieldname === f.needs) || {}).label || f.needs]), "stop");
		call(f.method, { [f.arg || "rental_contract"]: doc[f.needs] }).then((rows) => {
			doc[f.table] = rows || [];
			draw_tables();
			say(rows && rows.length ? "" : __("Nothing to add: there is no open quantity for this document."), rows && rows.length ? "" : "stop");
		});
	}

	// ------------------------------------------------------------------ totals and buttons
	const totals = el("dl", { class: "rp-terms rp-entry-totals" });
	function draw_totals() {
		totals.replaceChildren(...boot.totals.map((t) => el("div", {}, el("dt", { text: t.label }), el("dd", { text: fmt(doc[t.fieldname], t.fieldtype) || "0" }))));
		totals.hidden = boot.is_new || !boot.totals.length;
	}

	function save(submit) {
		const buttons = form.querySelectorAll(".rp-entry-bar button");
		buttons.forEach((b) => (b.disabled = true));
		say(submit ? __("Saving and submitting...") : __("Saving..."));
		const payload = Object.assign({}, doc);
		boot.tables.filter((t) => t.readonly).forEach((t) => delete payload[t.fieldname]);
		call("thinknxg_rental.portal.entry.save_entry", { entry_type: boot.type, doc: JSON.stringify(payload), submit: submit ? 1 : 0 }, "POST")
			.then((r) => {
				say(submit ? __("{0} submitted.", [r.name]) : __("{0} saved.", [r.name]));
				window.location.href = r.url;
			})
			.catch(() => {
				say("");
				buttons.forEach((b) => (b.disabled = false));
			});
	}

	const bar = el("div", { class: "rp-actions rp-entry-bar", hidden: !boot.editable });
	if (boot.editable) {
		bar.append(el("button", { type: "submit", class: "rp-btn rp-btn--main", text: boot.is_new ? __("Save draft") : __("Save") }));
		if (boot.submittable)
			bar.append(el("button", { type: "button", class: "rp-btn", text: __("Save and submit"), onclick: () => {
				if (window.confirm(__("Submit this {0}? A submitted document can only be changed by cancelling and amending it in the desk.", [boot.label]))) save(true);
			} }));
	}
	form.addEventListener("submit", (e) => {
		e.preventDefault();
		if (boot.editable) save(false);
	});

	// next document (Lead -> Quotation -> Hire Order -> Rental Contract): map it, then open it here unsaved
	document.querySelectorAll("[data-make]").forEach((button) =>
		button.addEventListener("click", () => {
			button.disabled = true;
			call("thinknxg_rental.portal.entry.prepare_mapped", { make: button.dataset.make, source: button.dataset.source }, "POST")
				.then((r) => (window.location.href = r.url))
				.catch(() => (button.disabled = false));
		})
	);

	// JCR: invoice this JCR, alone or with other open JCRs of the same customer (the desk's Create > Multiple JCRs)
	const invoice = el("section", { class: "rp-section rp-invoice" });
	function draw_invoice() {
		if (!boot.invoice) return (invoice.hidden = true);
		const others = el("ul", { class: "rp-checks" });
		const button = el("button", { type: "button", class: "rp-btn rp-btn--main", text: __("Create Sales Invoice"), onclick: () => {
			const jcrs = [boot.name, ...[...others.querySelectorAll("input:checked")].map((c) => c.value)];
			button.disabled = true;
			say(__("Creating the Sales Invoice..."));
			call("thinknxg_rental.services.jcr_billing.make_combined_invoice", { jcrs: JSON.stringify(jcrs) }, "POST")
				.then((invoice_name) => {
					say(__("Sales Invoice {0} created as a draft. Opening it in the desk to check and submit.", [invoice_name]));
					window.location.href = "/app/sales-invoice/" + encodeURIComponent(invoice_name);
				})
				.catch(() => {
					say("");
					button.disabled = false;
				});
		} });
		invoice.replaceChildren(
			el("h2", { text: __("Sales Invoice") }),
			el("p", { class: "rp-muted", text: __("{0} is always on the invoice. Tick other open JCRs of this customer to bill them on the same invoice.", [boot.name]) }),
			others,
			el("div", { class: "rp-actions" }, button)
		);
		call("thinknxg_rental.services.jcr_billing.get_combinable_jcrs", { jcr: boot.name }).then((rows) => {
			others.replaceChildren(...(rows || []).map((r, i) => el("li", {},
				el("input", { type: "checkbox", id: "rp-jcr-" + i, value: r.name }),
				el("label", { for: "rp-jcr-" + i, text: [r.name, r.hire_order_contract || r.rental_contract,
					r.pending_periods ? __("{0} period(s) pending", [r.pending_periods]) : ""].filter(Boolean).join(" \u00b7 ") }))));
			if (!(rows || []).length) others.replaceWith(el("p", { class: "rp-none", text: __("No other open JCR for this customer.") }));
		});
	}

	function draw_all() {
		draw_header();
		draw_tables();
		draw_totals();
	}
	form.replaceChildren(header, tables, totals, invoice, bar);
	draw_all();
	draw_invoice();
	if (boot.editable && boot.fill && doc[boot.fill.needs] && !(doc[boot.fill.table] || []).some((r) => r.item_code || r.job_type)) fill();
})();
