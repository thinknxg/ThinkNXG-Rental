// Command Center list page: one page of real records at a time, filtered, sorted and counted on the
// server with the user's permissions (command_center.api.list_view). The filters live in the address,
// so a filtered list can be bookmarked or sent to a colleague.
(function () {
	const cc = window.cc;
	const { el, __ } = cc;
	cc.pages = cc.pages || {};

	// A link field with suggestions from the desk's own link search (permission-aware).
	cc.linkInput = function (doctype, value, onchange, opts) {
		opts = opts || {};
		const id = "cc-l-" + Math.random().toString(36).slice(2, 8);
		const list = el("datalist", { id: id + "-list" });
		const input = el("input", { id, list: id + "-list", autocomplete: "off", placeholder: opts.placeholder || "", "aria-label": opts.label || doctype, class: opts.cls || null });
		input.value = value || "";
		const search = cc.debounce(() => {
			cc.call("frappe.desk.search.search_link", { doctype, txt: input.value, page_length: 12, filters: opts.filters ? JSON.stringify(opts.filters) : null, reference_doctype: opts.reference_doctype || null }, { silent: true })
				.then((r) => list.replaceChildren(...(r || []).map((x) => el("option", { value: x.value, label: cc.strip(x.description || x.label || "") }))))
				.catch(() => {});
		}, 200);
		input.addEventListener("input", search);
		input.addEventListener("focus", search, { once: true });
		input.addEventListener("change", () => onchange && onchange(input.value.trim()));
		return [input, list];
	};

	cc.pages.list = async function (ctx) {
		const key = ctx.key;
		const q = new URLSearchParams(ctx.query || "");
		const state = {
			search: q.get("q") || "",
			tab: q.get("tab"),
			page: Number(q.get("page")) || 1,
			page_size: Number(q.get("size")) || cc.store.get("pagesize", 20),
			sort: q.get("sort") || "",
			filters: { status: q.get("status") || "", docstatus: q.get("docstatus") || "", party: q.get("party") || "", from_date: q.get("from") || "", to_date: q.get("to") || "" },
		};
		const root = ctx.root;
		let data;
		const tableBox = el("div", { class: "cc-tablewrap" });
		const pager = el("div", { class: "cc-pager" });
		const head = el("div");
		const tabs = el("div");
		const toolbar = el("div", { class: "cc-toolbar" });
		root.replaceChildren(head, el("section", { class: "cc-panel" }, tabs, toolbar, tableBox, pager));
		tableBox.append(cc.skeleton(8));

		const writeUrl = () => {
			const p = new URLSearchParams();
			if (state.search) p.set("q", state.search);
			if (state.tab !== null && state.tab !== undefined && state.tab !== "") p.set("tab", state.tab);
			if (state.page > 1) p.set("page", state.page);
			if (state.sort) p.set("sort", state.sort);
			if (state.filters.status) p.set("status", state.filters.status);
			if (state.filters.docstatus) p.set("docstatus", state.filters.docstatus);
			if (state.filters.party) p.set("party", state.filters.party);
			if (state.filters.from_date) p.set("from", state.filters.from_date);
			if (state.filters.to_date) p.set("to", state.filters.to_date);
			const s = p.toString();
			history.replaceState(history.state, "", cc.base + "/" + key + (s ? "?" + s : ""));
		};

		let seq = 0;
		async function load() {
			const mine = ++seq;
			root.querySelector(".cc-panel").setAttribute("aria-busy", "true");
			try {
				const r = await cc.api("list_view", {
					view: key, search: state.search, tab: state.tab, page: state.page, page_size: state.page_size, sort: state.sort,
					filters: state.filters,
				});
				if (mine !== seq) return;
				data = r;
				state.tab = r.tab;
				state.sort = r.sort.field + " " + r.sort.order;
				writeUrl();
				draw();
			} catch (e) {
				if (mine === seq) {
					if (!data) {
						ctx.setTitle(__("No access"));
						root.replaceChildren(cc.failure(e));
					} else tableBox.replaceChildren(cc.failure(e));
				}
			} finally {
				const p = root.querySelector(".cc-panel");
				if (p) p.removeAttribute("aria-busy");
			}
		}

		const hiddenCols = () => cc.store.get("cols:" + key, []);
		function draw() {
			ctx.setTitle(data.label);
			const actions = [];
			if (data.can_export) actions.push(cc.btn(__("Export"), exportCsv, { icon: "download" }));
			actions.push(cc.btn(__("Open in desk"), null, { icon: "external-link", href: data.desk_url, kind: "ghost" }));
			if (data.can_create) actions.push(cc.btn(__("New {0}", [singular(data)]), null, { icon: "plus", kind: "primary", href: cc.base + "/" + key + "/new" }));
			head.replaceChildren(cc.pagehead(data.label, data.description, actions,
				el("span", { class: "cc-muted", style: "font:500 16px var(--font)", text: __("{0} records", [cc.num(data.total)]) })));
			// tabs
			tabs.replaceChildren(data.tabs.length ? el("div", { style: "padding:12px 14px 0" }, el("div", { class: "cc-tabs", role: "tablist" },
				data.tabs.map((t, i) => el("button", { type: "button", role: "tab", "aria-selected": i === data.tab ? "true" : "false", text: t, onclick: () => {
					state.tab = i;
					state.page = 1;
					load();
				} })))) : "");
			drawToolbar();
			drawTable();
			drawPager();
		}

		function drawToolbar() {
			if (toolbar.dataset.ready) return;
			toolbar.dataset.ready = "1";
			const search = el("input", { type: "search", placeholder: __("Search by number, customer or site"), "aria-label": __("Search this list"), value: state.search });
			search.addEventListener("input", cc.debounce(() => {
				state.search = search.value.trim();
				state.page = 1;
				load();
			}, 300));
			const parts = [el("div", { class: "cc-search" }, cc.icon("search", "cc-i--sm"), search)];
			if (data.statuses.length) {
				parts.push(el("select", { "aria-label": __("Status"), onchange: (e) => { state.filters.status = e.target.value; state.page = 1; load(); } },
					el("option", { value: "", text: __("Any status") }), data.statuses.map((s) => el("option", { value: s, text: __(s), selected: s === state.filters.status }))));
			} else if (data.submittable) {
				parts.push(el("select", { "aria-label": __("Document state"), onchange: (e) => { state.filters.docstatus = e.target.value; state.page = 1; load(); } },
					[["", __("Any state")], ["0", __("Draft")], ["1", __("Submitted")], ["2", __("Cancelled")]].map(([v, l]) => el("option", { value: v, text: l, selected: v === state.filters.docstatus }))));
			}
			if (data.party && data.party_doctype) {
				const [input, list] = cc.linkInput(data.party_doctype, state.filters.party, (v) => { state.filters.party = v; state.page = 1; load(); },
					{ placeholder: __(data.party_doctype), label: __(data.party_doctype) });
				input.style.width = "190px";
				parts.push(input, list);
			}
			if (data.date_field) {
				const from = el("input", { type: "date", "aria-label": __("From date"), value: state.filters.from_date, onchange: (e) => { state.filters.from_date = e.target.value; state.page = 1; load(); } });
				const to = el("input", { type: "date", "aria-label": __("To date"), value: state.filters.to_date, onchange: (e) => { state.filters.to_date = e.target.value; state.page = 1; load(); } });
				parts.push(el("span", { class: "cc-muted", style: "font-size:13px", text: __("Date") }), from, el("span", { class: "cc-muted", text: "–" }), to);
			}
			parts.push(el("span", { class: "cc-spacer" }));
			const colBtn = el("button", { type: "button", class: "cc-btn cc-btn--sm cc-btn--ghost", "aria-haspopup": "true" }, cc.icon("columns-3", "cc-i--sm"), __("Columns"));
			colBtn.addEventListener("click", () => {
				const hidden = new Set(hiddenCols());
				cc.popover(colBtn, [el("h3", { text: __("Show columns") }), ...data.columns.filter((c) => c.fieldname !== "name").map((c) => {
					const id = "cc-col-" + c.fieldname;
					const box = el("input", { type: "checkbox", id, checked: !hidden.has(c.fieldname), onchange: (e) => {
						if (e.target.checked) hidden.delete(c.fieldname);
						else hidden.add(c.fieldname);
						cc.store.set("cols:" + key, [...hidden]);
						drawTable();
					} });
					return el("label", { for: id, style: "display:flex;gap:8px;align-items:center;padding:6px 10px;cursor:pointer" }, box, c.label);
				})]);
			});
			parts.push(colBtn);
			toolbar.replaceChildren(...parts);
		}

		function drawTable() {
			const hidden = new Set(hiddenCols());
			const cols = data.columns.filter((c) => !hidden.has(c.fieldname));
			if (!cols.some((c) => c.fieldname === "name")) cols.unshift({ fieldname: "name", label: __("ID"), fieldtype: "Data" });
			const hasStatus = !cols.some((c) => c.fieldname === "status");
			const [sortField, sortOrder] = state.sort.split(" ");
			const th = (c) => {
				const sorted = c.fieldname === sortField;
				return el("th", { scope: "col", class: cc.NUM.includes(c.fieldtype) ? "cc-num" : null, "aria-sort": sorted ? (sortOrder === "asc" ? "ascending" : "descending") : null },
					el("button", { type: "button", onclick: () => {
						state.sort = c.fieldname + " " + (sorted && sortOrder === "desc" ? "asc" : "desc");
						load();
					} }, c.label, sorted ? cc.icon(sortOrder === "asc" ? "arrow-up" : "arrow-down", "cc-i--sm") : null));
			};
			if (!data.rows.length) {
				tableBox.replaceChildren(cc.empty(__("Nothing here"), state.search || Object.values(state.filters).some(Boolean)
					? __("No records match these filters. Clear the search or filters to see more.")
					: __("No {0} yet.", [data.label]), data.can_create ? cc.btn(__("New {0}", [singular(data)]), null, { kind: "primary", icon: "plus", href: cc.base + "/" + key + "/new" }) : null));
				return;
			}
			const rowHref = (r) => (data.opens === "form" ? cc.base + "/" + key + "/" + encodeURIComponent(r.name) : data.desk_url + "/" + encodeURIComponent(r.name));
			const table = el("table", { class: "cc-table cc-table--cards" },
				el("thead", {}, el("tr", {}, cols.map(th), hasStatus ? el("th", { scope: "col", text: __("Status") }) : null)),
				el("tbody", {}, data.rows.map((r) => {
					const href = rowHref(r);
					const tr = el("tr", { "data-href": href },
						cols.map((c, i) => {
							const v = r[c.fieldname];
							const td = el("td", { "data-label": c.label, class: [i === 0 ? "cc-first" : null, cc.NUM.includes(c.fieldtype) ? "cc-num" : null].filter(Boolean).join(" ") || null });
							if (c.fieldname === "name") {
								const a = el("a", { href, text: v });
								if (href.startsWith(cc.base)) a.addEventListener("click", (e) => cc.linkClick(e, href));
								td.append(a);
							} else if (c.fieldname === "status") td.append(cc.pill(v));
							else td.append(cc.fmt(v, c.fieldtype, r.currency) || (v === 0 ? "0" : ""));
							return td;
						}),
						hasStatus ? el("td", { "data-label": __("Status") }, cc.pill(r.status)) : null);
					tr.addEventListener("click", (e) => {
						if (e.target.closest("a, button, input")) return;
						if (href.startsWith(cc.base)) cc.go(href);
						else window.location.href = href;
					});
					return tr;
				})));
			tableBox.replaceChildren(table);
		}

		function drawPager() {
			const pages = Math.max(1, Math.ceil(data.total / data.page_size));
			const first = data.total ? (data.page - 1) * data.page_size + 1 : 0;
			const last = Math.min(data.total, data.page * data.page_size);
			pager.replaceChildren(
				el("span", { text: __("{0}–{1} of {2}", [cc.num(first), cc.num(last), cc.num(data.total)]) }),
				el("label", { style: "display:inline-flex;gap:6px;align-items:center" }, __("Rows"),
					el("select", { onchange: (e) => { state.page_size = Number(e.target.value); cc.store.set("pagesize", state.page_size); state.page = 1; load(); } },
						[20, 50, 100].map((n) => el("option", { value: n, text: n, selected: n === data.page_size })))),
				el("div", { class: "cc-actions" },
					cc.btn(__("Previous"), () => { state.page -= 1; load(); }, { sm: true, icon: "chevron-left" }),
					el("span", { text: __("Page {0} of {1}", [data.page, pages]) }),
					cc.btn(__("Next"), () => { state.page += 1; load(); }, { sm: true })));
			const [prev, , next] = pager.querySelectorAll(".cc-actions > *");
			prev.disabled = data.page <= 1;
			next.disabled = data.page >= pages;
		}

		async function exportCsv() {
			const r = await cc.api("export_list", { view: key, search: state.search, tab: state.tab, filters: state.filters, sort: state.sort });
			cc.download(r.filename, r.content);
			cc.toast(__("Exported {0}.", [r.filename]), "ok");
		}

		await load();
	};

	const singular = (data) => data.singular || data.doctype;
})();
