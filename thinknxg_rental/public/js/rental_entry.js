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

	// a read-only link opens the linked document: in the portal when it has a menu, else in the desk
	const link_to = (spec, value) => {
		if (!value || !["Link", "Dynamic Link"].includes(spec.fieldtype)) return null;
		const doctype = link_doctype(spec);
		if (!doctype) return null;
		const key = (boot.links || {})[doctype];
		const href = key ? `/rental/admin/entry?type=${key}&name=${encodeURIComponent(value)}`
			: `/app/${doctype.toLowerCase().replace(/ /g, "-")}/${encodeURIComponent(value)}`;
		return el("a", { href, text: value });
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
			// choices are option strings, or {value, label} for an action that asks which row
			input = el("select", { id, onchange: (e) => set(e.target.value) },
				spec.choices.map((c) => (typeof c === "object" ? c : { value: c, label: c ? __(c) : "" }))
					.map((c) => el("option", { value: c.value, selected: (value || "") === c.value, text: c.label })));
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
			if (spec.create && !row) return [input, list, creator(spec, (name) => { input.value = name; set(name); })];
			return [input, list];
		} else {
			input = el("input", { id, type: "text", onchange: (e) => set(e.target.value) });
			input.value = value || "";
		}
		return [input];
	}

	// "New Project" beside a link: type the name, the record is made with the form's company and customer
	function creator(spec, done) {
		const c = spec.create;
		const wrap = el("div", { class: "rp-create" });
		const open = el("button", { type: "button", class: "rp-btn rp-btn--plain rp-btn--small", text: __("+ New {0}", [__(c.doctype)]) });
		const name = el("input", { type: "text", "aria-label": __(c.label) , placeholder: __(c.label) });
		const make = el("button", { type: "button", class: "rp-btn rp-btn--small", text: __("Create") });
		const cancel = el("button", { type: "button", class: "rp-btn rp-btn--plain rp-btn--small", text: __("Cancel") });
		const panel = el("div", { class: "rp-create-panel", hidden: true }, name, make, cancel);
		open.addEventListener("click", () => { panel.hidden = false; open.hidden = true; name.focus(); });
		cancel.addEventListener("click", () => { panel.hidden = true; open.hidden = false; });
		const submit = () => {
			if (!name.value.trim()) return name.focus();
			const record = { doctype: c.doctype, [c.name_field]: name.value.trim() };
			Object.entries(c.defaults || {}).forEach(([k, f]) => doc[f] && (record[k] = doc[f]));
			make.disabled = true;
			call("frappe.client.insert", { doc: JSON.stringify(record) }, "POST")
				.then((r) => {
					say(__("{0} {1} created.", [__(c.doctype), r.name]));
					done(r.name);
				})
				.catch(() => (make.disabled = false));
		};
		make.addEventListener("click", submit);
		name.addEventListener("keydown", (e) => {
			if (e.key === "Enter") {
				e.preventDefault();
				submit();
			}
		});
		wrap.append(open, panel);
		return wrap;
	}

	// a field with "loads" refills a table from it (a tax template gives the tax rows)
	function load_table(spec, value) {
		const l = spec.loads;
		if (!value) {
			doc[l.table] = [];
			return draw_tables();
		}
		call(l.method, { [spec.fieldname]: value, doctype: boot.doctype }).then((rows) => {
			doc[l.table] = rows || [];
			draw_tables();
		});
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
					body = [el("div", { class: "rp-value" }, link_to(spec, doc[spec.fieldname]) || fmt(doc[spec.fieldname], spec.fieldtype) || "–")];
				} else {
					body = input_for(spec, doc, (s, v) => {
						if (s.loads) load_table(s, v);
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
							t.no_add ? null : el("button", { type: "button", class: "rp-btn", text: __("Add row"), onclick: () => { rows.push({}); draw_tables(); } })
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
				// the saved document opens with its number and a note of what was done
				window.location.href = r.url + "&done=" + (submit ? "submitted" : "saved");
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

	// next document (Lead -> Quotation -> Hire Order -> Rental Contract): map it, then open it here unsaved.
	// One that asks first (which job line a JCR is for) opens the ask panel, as the actions below do.
	document.querySelectorAll("[data-make]").forEach((button) =>
		button.addEventListener("click", () => {
			const action = (boot.next || []).find((a) => a.make === button.dataset.make) || { make: button.dataset.make, source: button.dataset.source };
			run(action, button);
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
					say(__("Sales Invoice {0} created as a draft. Opening it to check and submit.", [invoice_name]));
					window.location.href = "/rental/admin/entry?type=sales-invoice&name=" + encodeURIComponent(invoice_name);
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

	// ------------------------------------------------------------------ related documents
	// What was made from or for this document (the JCRs of a Hire Order Contract, a contract's deliveries).
	const related = el("div");
	function draw_related() {
		related.replaceChildren(...(boot.related || []).map((r) => el("section", { class: "rp-section" },
			el("h2", { text: r.label }),
			el("table", { class: "rp-table" },
				el("thead", {}, el("tr", {}, r.columns.map((c) => el("th", { scope: "col", class: NUM.includes(c.fieldtype) ? "rp-num" : null, text: c.label })))),
				el("tbody", {}, r.rows.map((row) => el("tr", {}, r.columns.map((c, i) => {
					const text = fmt(row[c.fieldname], c.fieldtype);
					const cls = [i === 0 ? "rp-first" : null, NUM.includes(c.fieldtype) ? "rp-num" : null].filter(Boolean).join(" ") || null;
					if (i === 0) return el("td", { class: cls }, el("a", { href: row.url, text: text || row.name }));
					return el("td", { class: cls, "data-label": c.label, text: c.fieldname === "status" && text ? __(text) : text });
				}))))))));
	}

	// ------------------------------------------------------------------ actions on this document
	// Extend, close, record dismantle, reject: some ask for a value first, in a panel above the form.
	const ask_panel = el("div", { class: "rp-ask", hidden: true });
	function run(action, button) {
		const values = {};
		const go_run = () => {
			ask_panel.querySelectorAll("button").forEach((b) => (b.disabled = true));
			button.disabled = true;
			say(__("Working..."));
			(action.make
				? call("thinknxg_rental.portal.entry.prepare_mapped", { make: action.make, source: action.source, values: JSON.stringify(values) }, "POST")
				: call("thinknxg_rental.portal.entry.run_action", { action: action.run, source: action.source, values: JSON.stringify(values) }, "POST"))
				.then((r) => {
					say(r.message || "");
					window.location.href = r.url;
				})
				.catch(() => {
					say("");
					button.disabled = false;
					ask_panel.querySelectorAll("button").forEach((b) => (b.disabled = false));
				});
		};
		if (!(action.ask || []).length) {
			if (action.confirm && !window.confirm(action.confirm)) return;
			return go_run();
		}
		action.ask.forEach((spec) => spec.default !== undefined && spec.default !== null && (values[spec.fieldname] = spec.default));
		const fields = el("div", { class: "rp-fields" }, action.ask.map((spec) => {
			const parts = input_for(spec, values, null);
			return el("div", { class: spec.wide ? "rp-field rp-field--wide" : "rp-field" },
				el("label", { for: parts[0].id, text: spec.label }, spec.reqd ? el("span", { class: "rp-req", text: " *" }) : null), ...parts);
		}));
		const ok = el("button", { type: "button", class: "rp-btn rp-btn--main", text: action.label, onclick: () => {
			const missing = action.ask.find((spec) => spec.reqd && [undefined, null, ""].includes(values[spec.fieldname]));
			if (missing) return say(__("Fill in {0} first.", [missing.label]), "stop");
			if (action.confirm && !window.confirm(action.confirm)) return;
			go_run();
		} });
		const cancel = el("button", { type: "button", class: "rp-btn rp-btn--plain", text: __("Cancel"), onclick: () => (ask_panel.hidden = true) });
		ask_panel.replaceChildren(el("h2", { text: action.label }), fields, el("div", { class: "rp-actions" }, ok, cancel));
		ask_panel.hidden = false;
		const first = ask_panel.querySelector("input, select, textarea");
		if (first) first.focus();
	}
	document.querySelectorAll("[data-run]").forEach((button) =>
		button.addEventListener("click", () => {
			const action = (boot.next || []).find((a) => a.run === button.dataset.run);
			if (action) run(action, button);
		})
	);

	function draw_all() {
		draw_header();
		draw_tables();
		draw_totals();
	}
	form.replaceChildren(ask_panel, header, tables, totals, invoice, related, bar);
	draw_all();
	draw_related();
	draw_invoice();
	// links already filled (a form opened from a button) bring their values along, as on a change
	if (boot.editable)
		boot.header.forEach((spec) => {
			const fetch = spec.fetch || {};
			if (doc[spec.fieldname] && Object.keys(fetch).some((k) => !doc[k])) fetch_into(spec, doc[spec.fieldname], doc, draw_all);
		});
	if (boot.editable && boot.fill && doc[boot.fill.needs] && !(doc[boot.fill.table] || []).some((r) => r.item_code || r.job_type)) fill();
	// just saved or submitted here: say so, then drop the note from the address
	const done = new URLSearchParams(window.location.search).get("done");
	if (done && boot.name) {
		say(done === "submitted" ? __("{0} submitted.", [boot.name]) : __("{0} saved.", [boot.name]));
		const url = new URL(window.location.href);
		url.searchParams.delete("done");
		window.history.replaceState(null, "", url);
	}
})();
