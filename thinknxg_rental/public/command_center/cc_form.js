// Command Center document form. The same form engine as the admin portal (portal/entry.py): the server
// says which header fields and item columns to show, and every save, submit, mapping and action goes
// through thinknxg_rental.portal.entry (save_entry, prepare_mapped, run_action), which saves the real
// DocType with its own validations and the user's permissions. This file only draws and collects.
(function () {
	const cc = window.cc;
	const { el, __ } = cc;
	const NUM = cc.NUM;
	cc.pages = cc.pages || {};

	// path of a document of an entry type, in this app
	const entryHref = (type, name) => cc.base + "/" + ((cc.boot.routes.entries || {})[type] || "doc/" + type) + "/" + (name ? encodeURIComponent(name) : "new");
	const portalHref = (url) => cc.fromPortalUrl(url) || url;

	cc.pages.form = async function (ctx) {
		const root = ctx.root;
		root.replaceChildren(cc.skeleton(10));
		const q = new URLSearchParams(ctx.query || "");
		const prefill = {};
		q.forEach((v, k) => !["make", "source", "args", "done"].includes(k) && (prefill[k] = v));
		let boot;
		try {
			boot = await cc.api("form", { entry: ctx.entry, name: ctx.name, make: q.get("make"), source: q.get("source"), args: q.get("args"), prefill });
		} catch (e) {
			ctx.setTitle(__("Could not open this document"));
			root.replaceChildren(cc.pagehead(__("Could not open this document")), cc.failure(e));
			return;
		}
		render(ctx, boot);
	};

	function render(ctx, boot) {
		const root = ctx.root;
		const doc = boot.doc;
		let dirty = false;
		const markDirty = () => {
			if (!boot.editable) return;
			dirty = true;
			dirtyNote.hidden = false;
		};
		ctx.onLeave(() => (dirty ? __("You have unsaved changes on {0}. Leave without saving?", [boot.name || boot.label]) : null));

		const title = boot.name || __("New {0}", [boot.label]);
		ctx.setTitle(title, [{ label: boot.list_label, route: boot.route }]);
		if (boot.name) cc.remember({ href: location.pathname, title: boot.name, sub: boot.title !== boot.name ? boot.title : "", label: boot.label });

		const visible = (spec) => Object.entries(spec.show_if || {}).every(([f, values]) => values.includes(doc[f]));
		const linkDoctype = (spec) => (spec.fieldtype === "Dynamic Link" ? doc[spec.options] : spec.options);
		const resolveFilters = (filters, row) => {
			const out = {};
			Object.entries(filters || {}).forEach(([k, v]) => {
				if (typeof v === "string" && v.startsWith("$")) {
					const value = (row && row[v.slice(1)]) || doc[v.slice(1)];
					if (value) out[k] = value;
				} else out[k] = v;
			});
			return out;
		};
		const linkTo = (spec, value) => {
			if (!value || !["Link", "Dynamic Link"].includes(spec.fieldtype)) return null;
			const doctype = linkDoctype(spec);
			if (!doctype) return null;
			const type = (boot.links || {})[doctype];
			if (doctype === "Customer") return cc.link("customers/" + encodeURIComponent(value), value);
			if (type) return cc.link(entryHref(type, value), value);
			return el("a", { href: `/app/${doctype.toLowerCase().replace(/ /g, "-")}/${encodeURIComponent(value)}`, text: value });
		};

		let uid = 0;
		function inputFor(spec, target, onChange, row) {
			const id = "cc-f-" + spec.fieldname + "-" + uid++;
			const value = target[spec.fieldname];
			const set = (v) => {
				target[spec.fieldname] = v;
				markDirty();
				onChange && onChange(spec, v);
			};
			let input;
			if (spec.fieldtype === "Select") {
				input = el("select", { id, onchange: (e) => set(e.target.value) },
					(spec.choices || []).map((c) => (typeof c === "object" ? c : { value: c, label: c ? __(c) : "" }))
						.map((c) => el("option", { value: c.value, selected: (value || "") === c.value, text: c.label })));
			} else if (spec.fieldtype === "Check") {
				input = el("input", { id, type: "checkbox", checked: !!Number(value), onchange: (e) => set(e.target.checked ? 1 : 0) });
			} else if (["Small Text", "Text", "Long Text", "Text Editor"].includes(spec.fieldtype)) {
				input = el("textarea", { id, onchange: (e) => set(e.target.value) });
				input.value = value || "";
			} else if (NUM.includes(spec.fieldtype)) {
				input = el("input", { id, type: "number", step: spec.fieldtype === "Int" ? "1" : "any", inputmode: "decimal", oninput: (e) => set(e.target.value === "" ? null : Number(e.target.value)) });
				input.value = value === null || value === undefined ? "" : value;
			} else if (spec.fieldtype === "Date") {
				input = el("input", { id, type: "date", onchange: (e) => set(e.target.value || null) });
				input.value = value || "";
			} else if (["Link", "Dynamic Link"].includes(spec.fieldtype)) {
				const list = el("datalist", { id: id + "-list" });
				input = el("input", { id, list: id + "-list", autocomplete: "off", onchange: (e) => set(e.target.value.trim() || null) });
				input.value = value || "";
				const search = cc.debounce(() => {
					const doctype = linkDoctype(spec);
					if (!doctype) return;
					cc.call("frappe.desk.search.search_link", { doctype, txt: input.value, page_length: 15, filters: JSON.stringify(resolveFilters(spec.filters, row)), reference_doctype: boot.doctype }, { silent: true })
						.then((results) => list.replaceChildren(...(results || []).map((r) => el("option", { value: r.value, label: cc.strip(r.description || r.label || "") }))))
						.catch(() => {});
				}, 200);
				input.addEventListener("input", search);
				input.addEventListener("focus", search, { once: true });
				if (spec.create && !row) return [input, list, creator(spec, (name) => { input.value = name; set(name); })];
				return [input, list];
			} else {
				input = el("input", { id, type: "text", onchange: (e) => set(e.target.value) });
				input.value = value || "";
			}
			return [input];
		}

		// "+ New Project" beside a link: makes the record with the form's company and customer
		function creator(spec, done) {
			const c = spec.create;
			const open = el("button", { type: "button", class: "cc-btn cc-btn--ghost cc-btn--sm", text: __("+ New {0}", [__(c.doctype)]) });
			const name = el("input", { type: "text", "aria-label": __(c.label), placeholder: __(c.label) });
			const make = el("button", { type: "button", class: "cc-btn cc-btn--sm", text: __("Create") });
			const cancel = el("button", { type: "button", class: "cc-btn cc-btn--ghost cc-btn--sm", text: __("Cancel") });
			const panel = el("div", { class: "cc-create-panel", hidden: true }, name, make, cancel);
			open.addEventListener("click", () => { panel.hidden = false; open.hidden = true; name.focus(); });
			cancel.addEventListener("click", () => { panel.hidden = true; open.hidden = false; });
			const submit = () => {
				if (!name.value.trim()) return name.focus();
				const record = { doctype: c.doctype, [c.name_field]: name.value.trim() };
				Object.entries(c.defaults || {}).forEach(([k, f]) => doc[f] && (record[k] = doc[f]));
				make.disabled = true;
				cc.call("frappe.client.insert", { doc: JSON.stringify(record) }, { post: true })
					.then((r) => {
						cc.toast(__("{0} {1} created.", [__(c.doctype), r.name]), "ok");
						panel.hidden = true;
						open.hidden = false;
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
			return el("div", { class: "cc-create" }, open, panel);
		}

		function loadTable(spec, value) {
			const l = spec.loads;
			if (!value) {
				doc[l.table] = [];
				return drawTables();
			}
			cc.call(l.method, { [spec.fieldname]: value, doctype: boot.doctype }).then((rows) => {
				doc[l.table] = rows || [];
				drawTables();
			}).catch(() => {});
		}
		function fetchInto(spec, value, target, redraw) {
			const fields = spec.fetch || {};
			const keys = Object.keys(fields);
			if (!keys.length || !value) return;
			cc.call("thinknxg_rental.portal.entry.get_link_values", { doctype: linkDoctype(spec), name: value, fields: JSON.stringify(Object.values(fields)) }).then((values) => {
				keys.forEach((k) => (target[k] = (values || {})[fields[k]] ?? target[k]));
				redraw();
			}).catch(() => {});
		}

		// a row's defaults from a server method when a field changes (the item's rental charges): written
		// over the row's values, as picking a new item should; later edits are the row's own
		function rowDefaults(spec, value, row) {
			const d = spec.defaults;
			if (!d || !d.method) return;
			const args = {};
			Object.entries(d.args || {}).forEach(([k, v]) => (args[k] = v === "$value" ? value : typeof v === "string" && v.startsWith("$") ? doc[v.slice(1)] : v));
			if (!value) return;
			cc.call(d.method, args, { silent: true }).then((values) => {
				if (row[spec.fieldname] !== value) return;
				// only the row's own columns (the answer may carry extras, such as has_profile)
				const columns = new Set(boot.tables.flatMap((t) => t.columns.map((c) => c.fieldname)));
				Object.entries(values || {}).forEach(([k, v]) => {
					if (columns.has(k)) row[k] = v;
				});
				if (d.marker) row[d.marker] = 1;
				drawTables();
			}).catch(() => {});
		}

		// ------------------------------------------------------------------ header fields
		const header = el("div", { class: "cc-fields" });
		function drawHeader() {
			header.replaceChildren(...boot.header.filter(visible).map((spec) => {
				const label = el("label", { text: spec.label }, spec.reqd && boot.editable && !spec.ro ? el("span", { class: "cc-req", text: " *" }) : null);
				let body;
				if (!boot.editable || spec.ro) {
					body = [el("div", { class: "cc-value" }, linkTo(spec, doc[spec.fieldname]) || (spec.fieldname === "status" ? cc.pill(doc.status) : cc.fmt(doc[spec.fieldname], spec.fieldtype, boot.currency)) || el("span", { class: "cc-muted", text: "–" }))];
				} else {
					body = inputFor(spec, doc, (s, v) => {
						if (s.loads) loadTable(s, v);
						if (s.fieldtype === "Select" || Object.keys(s.fetch || {}).length) {
							fetchInto(s, v, doc, drawAll);
							if (!Object.keys(s.fetch || {}).length) drawAll();
						}
						if (s.fieldname === (boot.fill || {}).needs && v && !(doc[boot.fill.table] || []).some((r) => r.item_code || r.job_type)) fill();
					});
					label.setAttribute("for", body[0].id);
				}
				return el("div", { class: spec.wide ? "cc-field cc-field--wide" : "cc-field" }, label, ...body);
			}));
		}

		// ------------------------------------------------------------------ worked-out row values (portal/entry.py "calc")
		const cells = new WeakMap();
		const factor = (row, f, blankOne) => {
			if (typeof f === "object") {
				const n = Number(row[f.field]) || 0;
				if (!n) return (blankOne || []).includes(f.field) ? 1 : 0;
				return n / (f.per.map[row[f.per.field]] || f.per.default || 1);
			}
			const n = Number(row[f]) || 0;
			return !n && (blankOne || []).includes(f) ? 1 : n;
		};
		function recalc(t, row, changed) {
			(t.calc || []).filter(visible).forEach((rule) => {
				const names = rule.product.map((f) => (typeof f === "object" ? f.field : f));
				if (rule.need_all && (!names.includes(changed) || names.some((f) => !Number(row[f])))) return;
				const value = Math.round(rule.product.reduce((p, f) => p * factor(row, f, rule.blank_one), 1) * 1e6) / 1e6;
				if (row[rule.target] === value) return;
				row[rule.target] = value;
				changed = rule.target;
				const node = (cells.get(row) || {})[rule.target];
				const col = t.columns.find((c) => c.fieldname === rule.target);
				if (node && node.tagName === "INPUT") node.value = value;
				else if (node) node.textContent = cc.fmt(value, col && col.fieldtype, boot.currency);
			});
		}
		const newRow = (t) => {
			const row = {};
			t.columns.forEach((c) => {
				if (c.default !== undefined && c.default !== null) row[c.fieldname] = NUM.includes(c.fieldtype) || c.fieldtype === "Check" ? Number(c.default) : c.default;
			});
			return row;
		};

		// ------------------------------------------------------------------ item tables
		const tables = el("div", { class: "cc-stack" });
		function drawTables() {
			tables.replaceChildren(...boot.tables.filter((t) => !(t.readonly && !(doc[t.fieldname] || []).length)).map((t) => {
				const rows = (doc[t.fieldname] = doc[t.fieldname] || []);
				const editable = boot.editable && !t.readonly;
				if (editable) rows.forEach((row) => recalc(t, row));
				if (t.readonly && !rows.length) return null;
				const cols = t.columns.filter(visible);
				const UNIT = 2.9;
				const weight = (c) => {
					const word = Math.max(...c.label.split(/\s+/).map((w) => w.length)) + (c.reqd && editable ? 1 : 0);
					const floor = Math.max(word * 0.56 + 1.1, c.fieldtype === "Select" && editable ? 5.6 : 0) / UNIT;
					return Math.max(c.w, floor);
				};
				const total = cols.reduce((s, c) => s + weight(c), 0) + 0.6 + (editable ? 0.6 : 0);
				const pct = (w) => ((w / total) * 100).toFixed(2) + "%";
				const table = el("table", { class: "cc-grid-table", style: `min-inline-size:${(total * UNIT).toFixed(1)}rem` },
					el("colgroup", {}, el("col", { style: `inline-size:${pct(0.6)}` }), cols.map((c) => el("col", { style: `inline-size:${pct(weight(c))}` })), editable ? el("col", { style: `inline-size:${pct(0.6)}` }) : null),
					el("thead", {}, el("tr", {},
						el("th", { scope: "col", class: "cc-num", text: "#" }),
						cols.map((c) => el("th", { scope: "col", class: NUM.includes(c.fieldtype) ? "cc-num" : null }, c.label, c.reqd && editable && !c.ro ? el("span", { class: "cc-req", text: " *" }) : null)),
						editable ? el("th", { scope: "col" }, el("span", { class: "cc-sr", text: __("Remove") })) : null)),
					el("tbody", {}, rows.map((row, i) => el("tr", {},
						el("td", { class: "cc-idx", text: i + 1 }),
						cols.map((c) => {
							const cell = el("td", { class: NUM.includes(c.fieldtype) ? "cc-num" : null });
							if (!cells.has(row)) cells.set(row, {});
							if (!editable || c.ro) {
								const shown = ["Link", "Dynamic Link"].includes(c.fieldtype) && !editable ? linkTo(c, row[c.fieldname]) : null;
								cell.append((cells.get(row)[c.fieldname] = shown || el("span", { class: "cc-value", text: cc.fmt(row[c.fieldname], c.fieldtype, boot.currency) })));
							} else {
								const parts = inputFor(c, row, (s, v) => {
									(s.clears || []).forEach((f) => (row[f] = null));
									if (s.marks) row[s.marks] = 1;
									fetchInto(s, v, row, drawTables);
									rowDefaults(s, v, row);
									recalc(t, row, s.fieldname);
								}, row);
								cells.get(row)[c.fieldname] = parts[0];
								parts[0].setAttribute("aria-label", `${c.label}, ${__("row")} ${i + 1}`);
								cell.append(...parts);
							}
							return cell;
						}),
						editable ? el("td", {}, el("button", { type: "button", class: "cc-iconbtn", style: "width:30px;height:30px", "aria-label": __("Remove row {0}", [i + 1]), onclick: () => { rows.splice(i, 1); markDirty(); drawTables(); } }, cc.icon("x", "cc-i--sm"))) : null))));
				const actions = editable ? [
					boot.fill && boot.fill.table === t.fieldname ? cc.btn(__(boot.fill.label), fill, { sm: true, icon: "refresh-cw" }) : null,
					t.no_add ? null : cc.btn(__("Add row"), () => { rows.push(newRow(t)); markDirty(); drawTables(); const inputs = tables.querySelectorAll("tbody tr:last-child input, tbody tr:last-child select"); if (inputs[0]) inputs[0].focus(); }, { sm: true, icon: "plus" }),
				].filter(Boolean) : null;
				return cc.panel(t.label, rows.length ? el("div", { class: "cc-tablewrap" }, table) : el("p", { class: "cc-muted", style: "padding:0 18px 16px;margin:0", text: __("No rows yet.") }), { flush: true, actions });
			}));
		}
		function fill() {
			const f = boot.fill;
			if (!doc[f.needs]) return cc.toast(__("Fill in {0} first.", [(boot.header.find((h) => h.fieldname === f.needs) || {}).label || f.needs]), "bad");
			cc.call(f.method, { [f.arg || "rental_contract"]: doc[f.needs] }).then((rows) => {
				doc[f.table] = rows || [];
				markDirty();
				drawTables();
				if (!(rows || []).length) cc.toast(__("Nothing to add: there is no open quantity for this document."));
			}).catch(() => {});
		}

		// ------------------------------------------------------------------ totals
		const totals = el("dl", { class: "cc-terms" });
		function drawTotals() {
			totals.replaceChildren(...boot.totals.map((t) => el("div", {}, el("dt", { text: t.label }), el("dd", { text: cc.fmt(doc[t.fieldname], t.fieldtype, boot.currency) || "0" }))));
			totals.hidden = boot.is_new || !boot.totals.length;
		}

		// ------------------------------------------------------------------ save and submit
		async function save(submit) {
			if (submit && !(await cc.confirm(__("Submit {0}?", [boot.name || boot.label]), __("A submitted document is final. To change it later it has to be cancelled and amended."), __("Submit")))) return;
			saveBtns.forEach((b) => (b.disabled = true));
			const payload = Object.assign({}, doc);
			boot.tables.filter((t) => t.readonly).forEach((t) => delete payload[t.fieldname]);
			try {
				const r = await cc.call("thinknxg_rental.portal.entry.save_entry", { entry_type: boot.type, doc: JSON.stringify(payload), submit: submit ? 1 : 0 }, { post: true });
				dirty = false;
				cc.toast(submit ? __("{0} submitted.", [r.name]) : __("{0} saved.", [r.name]), "ok");
				cc.refreshBadges && cc.refreshBadges();
				cc.go(portalHref(r.url), { replace: !boot.name || boot.name === r.name });
			} catch (e) {
				saveBtns.forEach((b) => (b.disabled = false));
			}
		}
		async function submitSaved() {
			if (!(await cc.confirm(__("Submit {0}?", [boot.name]), __("A submitted document is final. To change it later it has to be cancelled and amended."), __("Submit")))) return;
			const r = await cc.call("thinknxg_rental.portal.entry.submit_entry", { entry_type: boot.type, name: boot.name }, { post: true });
			cc.toast(__("{0} submitted.", [r.name]), "ok");
			ctx.reload();
		}
		async function cancelDoc() {
			if (!(await cc.confirm(__("Cancel {0}?", [boot.name]), __("Cancelling reverses its stock, ledger and accounting entries. Documents made from it may have to be cancelled first."), __("Cancel document"), true))) return;
			await cc.api("cancel_document", { doctype: boot.doctype, name: boot.name }, { post: true });
			cc.toast(__("{0} cancelled.", [boot.name]), "ok");
			ctx.reload();
		}

		const dirtyNote = el("span", { class: "cc-dirty", hidden: true, text: __("Unsaved changes") });
		const saveBtns = [];
		const bar = el("div", { class: "cc-docbar" });
		if (boot.editable) {
			const saveBtn = cc.btn(boot.is_new ? __("Save draft") : __("Save"), () => save(false), { kind: "primary", icon: "check" });
			saveBtn.title = __("Save (Ctrl+S)");
			saveBtns.push(saveBtn);
			bar.append(saveBtn);
			if (boot.submittable) {
				const sb = cc.btn(boot.is_new ? __("Save and submit") : __("Save and submit"), () => save(true));
				saveBtns.push(sb);
				bar.append(sb);
			}
			bar.append(el("span", { class: "cc-spacer" }), dirtyNote);
		} else bar.hidden = true;
		ctx.onKey((e) => {
			if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s" && boot.editable) {
				e.preventDefault();
				save(false);
			}
		});

		// ------------------------------------------------------------------ actions (next documents, extend, close, ...)
		async function run(action, button) {
			const values = {};
			(action.ask || []).forEach((spec) => spec.default !== undefined && spec.default !== null && (values[spec.fieldname] = spec.default));
			const go = async () => {
				if (button) button.disabled = true;
				try {
					const r = action.make
						? await cc.call("thinknxg_rental.portal.entry.prepare_mapped", { make: action.make, source: action.source, values: JSON.stringify(values) }, { post: true })
						: await cc.call("thinknxg_rental.portal.entry.run_action", { action: action.run, source: action.source, values: JSON.stringify(values) }, { post: true });
					if (r.message) cc.toast(r.message, "ok");
					cc.refreshBadges && cc.refreshBadges();
					const href = portalHref(r.url);
					if (href === location.pathname) ctx.reload();
					else if (href.startsWith(cc.base)) cc.go(href);
					else window.location.href = href;
				} catch (e) {
					if (button) button.disabled = false;
				}
			};
			if (!(action.ask || []).length) {
				if (action.confirm && !(await cc.confirm(action.label, action.confirm, action.label))) return;
				return go();
			}
			const fields = el("div", { class: "cc-fields" }, action.ask.map((spec) => {
				const parts = inputFor(spec, values, null);
				return el("div", { class: spec.wide ? "cc-field cc-field--wide" : "cc-field" }, el("label", { for: parts[0].id, text: spec.label }, spec.reqd ? el("span", { class: "cc-req", text: " *" }) : null), ...parts);
			}));
			const ok = cc.btn(action.label, async () => {
				const missing = action.ask.find((spec) => spec.reqd && [undefined, null, ""].includes(values[spec.fieldname]));
				if (missing) return cc.toast(__("Fill in {0} first.", [missing.label]), "bad");
				cc.closeLayer();
				if (action.confirm && !(await cc.confirm(action.label, action.confirm, action.label))) return;
				go();
			}, { kind: "primary" });
			cc.dialog({ title: action.label, body: fields, actions: [cc.btn(__("Cancel"), () => cc.closeLayer(), { kind: "ghost" }), ok] });
		}
		const nextButtons = (boot.next || []).map((a) => {
			if (a.url) return cc.btn(a.label, null, { href: portalHref(a.url) });
			const b = cc.btn(a.label, () => run(a, b));
			return b;
		});

		// header actions: the first three next steps as buttons, the rest in a menu
		const fav = { href: location.pathname, title: boot.name, label: boot.label };
		const star = boot.name ? el("button", { type: "button", class: "cc-iconbtn", title: __("Favourite"), "aria-pressed": cc.favorites().some((d) => d.href === fav.href) ? "true" : "false" }, cc.icon("star")) : null;
		if (star) {
			const paint = () => (star.style.color = star.getAttribute("aria-pressed") === "true" ? "var(--hivis)" : "");
			paint();
			star.addEventListener("click", () => {
				star.setAttribute("aria-pressed", cc.toggleFavorite(fav) ? "true" : "false");
				paint();
			});
		}
		const shown = nextButtons.slice(0, 3);
		const more = [...nextButtons.slice(3)];
		const menuItems = [];
		(boot.prints || []).forEach((p) => menuItems.push(el("a", { href: p.url, target: "_blank", rel: "noopener" }, cc.icon("printer", "cc-i--sm"), p.label)));
		if (boot.can_submit && !boot.editable) menuItems.push(el("button", { type: "button", class: "cc-menuitem", onclick: submitSaved }, cc.icon("check", "cc-i--sm"), __("Submit")));
		if (boot.can_cancel) menuItems.push(el("button", { type: "button", class: "cc-menuitem", onclick: cancelDoc }, cc.icon("circle-x", "cc-i--sm"), __("Cancel document")));
		// rental contract: billing, material at site and the customer's view of it
		if (boot.type === "rental-contract" && boot.docstatus === 1) {
			if (cc.boot.can_bill && doc.contract_type !== "Job Type Contract")
				menuItems.push(el("button", { type: "button", class: "cc-menuitem", onclick: async () => {
					if (!(await cc.confirm(__("Generate billing for {0}?", [boot.name]), __("Runs the rental billing engine for this contract: every complete period not yet billed gets a billing schedule and invoice, as the nightly billing does."), __("Generate billing")))) return;
					const r = await cc.api("bill_contract", { rental_contract: boot.name, only_complete: 1 }, { post: true });
					const n = (r.schedules || []).length;
					cc.toast(n ? __("{0} billing period(s) billed.", [n]) : __("No complete period to bill yet."), n ? "ok" : "");
					if (n) ctx.reload();
				} }, cc.icon("receipt", "cc-i--sm"), __("Generate billing")));
			menuItems.push(cc.link("material-at-site?q=" + encodeURIComponent(boot.name), [cc.icon("construction", "cc-i--sm"), __("Material at site")]));
			menuItems.push(el("a", { href: "/rental/contract?name=" + encodeURIComponent(boot.name) + "&customer=" + encodeURIComponent(doc.customer || ""), target: "_blank", rel: "noopener" }, cc.icon("external-link", "cc-i--sm"), __("View customer portal")));
		}
		menuItems.push(el("a", { href: boot.desk_url }, cc.icon("external-link", "cc-i--sm"), __("Open in desk")));
		if (boot.can_amend) menuItems.push(el("a", { href: boot.desk_url }, cc.icon("file-pen-line", "cc-i--sm"), __("Amend in desk")));
		const moreBtn = el("button", { type: "button", class: "cc-btn", "aria-haspopup": "true" }, __("More"), cc.icon("chevron-down", "cc-i--sm"));
		moreBtn.addEventListener("click", () => cc.popover(moreBtn, [
			...more.map((b) => { const m = el("button", { type: "button", class: "cc-menuitem", text: b.textContent }); m.addEventListener("click", () => b.click()); return m; }),
			more.length ? el("hr") : null, ...menuItems].filter(Boolean)));
		const printBtn = (boot.prints || [])[0] ? cc.btn(__("Print"), null, { href: boot.prints[0].url, target: "_blank", icon: "printer" }) : null;

		const head = cc.pagehead(title, boot.name && boot.title && boot.title !== boot.name ? boot.title : boot.is_new ? __("Fill in the details and save a draft. Nothing is posted until you submit.") : "",
			[...shown, printBtn, boot.is_new ? null : moreBtn].filter(Boolean), el("span", { style: "display:inline-flex;gap:8px;align-items:center" }, boot.is_new ? null : cc.pill(boot.status), star));

		// ------------------------------------------------------------------ JCR invoicing
		const invoice = el("div");
		function drawInvoice() {
			if (!boot.invoice) return;
			const others = el("ul", { class: "cc-checks" });
			const button = cc.btn(__("Create Sales Invoice"), async () => {
				const jcrs = [boot.name, ...[...others.querySelectorAll("input:checked")].map((c) => c.value)];
				button.disabled = true;
				try {
					const name = await cc.call("thinknxg_rental.services.jcr_billing.make_combined_invoice", { jcrs: JSON.stringify(jcrs) }, { post: true });
					cc.toast(__("Sales Invoice {0} created as a draft. Check it and submit.", [name]), "ok");
					cc.go(entryHref("sales-invoice", name));
				} catch (e) {
					button.disabled = false;
				}
			}, { kind: "primary" });
			invoice.replaceChildren(cc.panel(__("Sales Invoice"), [el("p", { class: "cc-muted", style: "margin-top:0", text: __("{0} is always on the invoice. Tick other open JCRs of this customer to bill them on the same invoice.", [boot.name]) }), others, el("div", { class: "cc-actions", style: "margin-top:12px" }, button)]));
			cc.call("thinknxg_rental.services.jcr_billing.get_combinable_jcrs", { jcr: boot.name }).then((rows) => {
				others.replaceChildren(...(rows || []).map((r, i) => el("li", {}, el("input", { type: "checkbox", id: "cc-jcr-" + i, value: r.name }),
					el("label", { for: "cc-jcr-" + i, text: [r.name, r.hire_order_contract || r.rental_contract, r.pending_periods ? __("{0} period(s) pending", [r.pending_periods]) : ""].filter(Boolean).join(", ") }))));
				if (!(rows || []).length) others.replaceWith(el("p", { class: "cc-muted", text: __("No other open JCR for this customer.") }));
			}).catch(() => {});
		}

		// ------------------------------------------------------------------ related documents
		const related = el("div", { class: "cc-stack" }, (boot.related || []).map((r) => cc.panel(r.label, el("div", { class: "cc-tablewrap" }, el("table", { class: "cc-table cc-table--cards" },
			el("thead", {}, el("tr", {}, r.columns.map((c) => el("th", { scope: "col", class: NUM.includes(c.fieldtype) ? "cc-num" : null, text: c.label })))),
			el("tbody", {}, r.rows.map((row) => el("tr", {}, r.columns.map((c, i) => {
				const text = cc.fmt(row[c.fieldname], c.fieldtype, boot.currency);
				const cls = [i === 0 ? "cc-first" : null, NUM.includes(c.fieldtype) ? "cc-num" : null].filter(Boolean).join(" ") || null;
				if (i === 0) {
					const href = row.url ? portalHref(row.url) : null;
					return el("td", { class: cls }, href ? (href.startsWith(cc.base) ? cc.link(href, text || row.name) : el("a", { href, text: text || row.name })) : text || row.name);
				}
				return el("td", { class: cls, "data-label": c.label }, c.fieldname === "status" && text ? cc.pill(text) : text);
			})))))), { flush: true })));

		// ------------------------------------------------------------------ side: assignment, attachments, timeline
		const side = el("aside", { class: "cc-doc-side" });
		if (boot.name) {
			const people = el("div");
			const drawPeople = (list) => people.replaceChildren(list && list.length
				? el("ul", { class: "cc-files" }, list.map((a) => el("li", {}, el("span", { class: "cc-avatar", style: "width:24px;height:24px;font-size:11px", text: a.name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase() }), a.name)))
				: el("p", { class: "cc-muted", style: "margin:0", text: __("Nobody is assigned.") }));
			drawPeople(boot.assigned);
			const assignBtn = cc.btn(__("Assign"), async () => {
				const users = await cc.api("staff_users");
				const v = await cc.prompt(__("Assign {0}", [boot.name]), [{ fieldname: "user", label: __("Assign to"), fieldtype: "Select", options: users, default: (users.find((u) => u.value === cc.boot.user.name) || users[0] || {}).value }], __("Assign"));
				if (!v) return;
				const r = await cc.api("assign", { doctype: boot.doctype, name: boot.name, user: v.user }, { post: true });
				cc.toast(__("Assigned."), "ok");
				drawPeople(r.assigned || boot.assigned);
			}, { sm: true, icon: "user-plus" });
			side.append(cc.panel(__("Assigned to"), people, { actions: [assignBtn] }));

			const files = el("ul", { class: "cc-files" });
			const drawFiles = (list) => files.replaceChildren(...(list.length ? list.map((f) => el("li", {}, cc.icon("paperclip", "cc-i--sm"), el("a", { href: f.file_url, target: "_blank", rel: "noopener", text: f.file_name || f.file_url }))) : [el("li", { class: "cc-muted", text: __("No attachments.") })]));
			drawFiles(boot.attachments || []);
			const picker = el("input", { type: "file", hidden: true, onchange: async (e) => {
				const file = e.target.files[0];
				if (!file) return;
				const fd = new FormData();
				fd.append("file", file, file.name);
				fd.append("doctype", boot.doctype);
				fd.append("docname", boot.name);
				fd.append("is_private", "1");
				const res = await fetch("/api/method/upload_file", { method: "POST", body: fd, credentials: "same-origin", headers: { "X-Frappe-CSRF-Token": window.csrf_token } });
				if (!res.ok) return cc.toast(__("Could not attach {0}. You may not have permission to attach files to this document.", [file.name]), "bad");
				const data = await res.json();
				boot.attachments = [data.message, ...(boot.attachments || [])];
				drawFiles(boot.attachments);
				cc.toast(__("{0} attached.", [file.name]), "ok");
				picker.value = "";
			} });
			side.append(cc.panel(__("Attachments"), [files, picker], { actions: boot.can_attach ? [cc.btn(__("Attach"), () => picker.click(), { sm: true, icon: "paperclip" })] : null }));

			const timeline = el("ul", { class: "cc-timeline" });
			const drawTimeline = (list) => timeline.replaceChildren(...list.map((t) => el("li", { "data-kind": t.kind },
				el("div", {}, el("b", { text: t.by }), " ", t.kind === "comment" ? __("commented") : el("span", { html: cc.esc(cc.strip(t.content)) }), " ", el("small", { text: cc.ago(t.at), title: cc.datetime(t.at) })),
				t.kind === "comment" ? el("div", { class: "cc-comment", html: t.content }) : null)));
			drawTimeline(boot.timeline || []);
			const box = el("textarea", { class: "cc-input", rows: 2, style: "height:auto;min-height:64px;padding:8px 10px", placeholder: __("Add a comment"), "aria-label": __("Add a comment") });
			const send = cc.btn(__("Comment"), async () => {
				if (!box.value.trim()) return box.focus();
				send.disabled = true;
				try {
					await cc.api("add_comment", { doctype: boot.doctype, name: boot.name, content: box.value }, { post: true });
					boot.timeline = [{ kind: "comment", by: cc.boot.user.full_name, content: cc.esc(box.value).replace(/\n/g, "<br>"), at: new Date().toISOString().replace("T", " ") }, ...(boot.timeline || [])];
					drawTimeline(boot.timeline);
					box.value = "";
				} finally {
					send.disabled = false;
				}
			}, { sm: true, kind: "primary" });
			side.append(cc.panel(__("Activity"), [boot.can_comment ? el("div", { style: "display:grid;gap:8px;margin-bottom:14px" }, box, el("div", {}, send)) : null, timeline]));
			side.append(el("p", { class: "cc-muted", style: "font-size:12.5px;margin:0 4px", text: __("Created by {0}, {1}. Last changed {2}.", [boot.owner || "", cc.datetime(boot.creation), cc.ago(boot.modified)]) }));
		} else {
			side.append(cc.panel(__("How this works"), el("p", { class: "cc-muted", style: "margin:0", text: __("Save keeps a draft you can change. Submit posts it: stock moves, the ledgers and billing follow from the submitted document, exactly as in the desk.") })));
		}

		function drawAll() {
			drawHeader();
			drawTables();
			drawTotals();
		}
		const detail = cc.panel(__("Details"), [header], {});
		detail.append(totals);
		root.replaceChildren(head, el("div", { class: "cc-doc" }, el("div", { class: "cc-doc-main" }, detail, tables, invoice, related, bar), side));
		drawAll();
		drawInvoice();
		if (boot.editable)
			boot.header.forEach((spec) => {
				const fetch = spec.fetch || {};
				if (doc[spec.fieldname] && Object.keys(fetch).some((k) => !doc[k])) fetchInto(spec, doc[spec.fieldname], doc, drawAll);
			});
		if (boot.editable && boot.fill && doc[boot.fill.needs] && !(doc[boot.fill.table] || []).some((r) => r.item_code || r.job_type)) fill();
	}
})();
