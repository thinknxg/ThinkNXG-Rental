// Command Center pages other than lists and document forms: the dashboard, the boards (yard,
// material at site, cross hire, billing, outstanding, utilization), the request inbox, reports,
// customers, notifications, tasks, users and settings. Each one draws what one API call returns.
(function () {
	const cc = window.cc;
	const { el, __ } = cc;
	const C = cc.colors;
	const P = (cc.pages = cc.pages || {});

	const load = async (ctx, fn) => {
		ctx.root.replaceChildren(cc.skeleton(8));
		try {
			return await fn();
		} catch (e) {
			ctx.setTitle(__("No access"));
			ctx.root.replaceChildren(cc.failure(e));
			e.shown = true;
			throw e;
		}
	};
	const table = (head, rows, opts) => {
		opts = opts || {};
		return el("div", { class: "cc-tablewrap" }, el("table", { class: "cc-table" + (opts.cards === false ? "" : " cc-table--cards") },
			el("thead", {}, el("tr", {}, head.map((h) => el("th", { scope: "col", class: h.num ? "cc-num" : null, text: h.label ?? h })))),
			el("tbody", {}, rows.map((r) => el("tr", r.href ? { "data-href": r.href, onclick: (e) => { if (!e.target.closest("a,button,input")) cc.go(r.href); } } : {},
				r.cells.map((c, i) => el("td", { class: [i === 0 ? "cc-first" : null, head[i] && head[i].num ? "cc-num" : null].filter(Boolean).join(" ") || null, "data-label": head[i] && (head[i].label ?? head[i]) }, c))))),
			opts.foot ? el("tfoot", {}, el("tr", {}, opts.foot.map((c, i) => el("td", { class: head[i] && head[i].num ? "cc-num" : null }, c)))) : null));
	};
	const num = (label) => ({ label, num: true });
	const tabsEl = (items, current, onpick) => el("div", { class: "cc-tabs", role: "tablist" }, items.map(([v, l]) => el("button", { type: "button", role: "tab", "aria-selected": v === current ? "true" : "false", text: l, onclick: () => onpick(v) })));
	const setQuery = (ctx, params) => {
		const p = new URLSearchParams(ctx.query || "");
		Object.entries(params).forEach(([k, v]) => (v === null || v === undefined || v === "" ? p.delete(k) : p.set(k, v)));
		const s = p.toString();
		cc.go(cc.base + "/" + ctx.path + (s ? "?" + s : ""), { replace: true });
	};

	// ================================================================== dashboard
	const PERIODS = [["today", __("Today")], ["week", __("This week")], ["month", __("This month")], ["quarter", __("This quarter")], ["year", __("This year")], ["custom", __("Custom")]];
	P.dashboard = async function (ctx) {
		const q = new URLSearchParams(ctx.query || "");
		const period = q.get("period") || cc.store.get("period", "month");
		const from = q.get("from") || "", to = q.get("to") || "";
		ctx.setTitle(__("Dashboard"));
		let d;
		if (period === "custom" && !(from && to)) {
			d = null;
		} else {
			d = await load(ctx, () => cc.api("dashboard", { period, from_date: from, to_date: to }));
		}
		const pick = el("div", { class: "cc-period" }, tabsEl(PERIODS, period, (v) => {
			cc.store.set("period", v);
			setQuery(ctx, { period: v, from: v === "custom" ? from : null, to: v === "custom" ? to : null });
		}));
		if (period === "custom") {
			const f = el("input", { type: "date", value: from, "aria-label": __("From") });
			const t = el("input", { type: "date", value: to, "aria-label": __("To") });
			pick.append(f, t, cc.btn(__("Apply"), () => setQuery(ctx, { period: "custom", from: f.value, to: t.value }), { sm: true, kind: "primary" }));
		}
		const hello = __("Good {0}, {1}", [new Date().getHours() < 12 ? __("morning") : new Date().getHours() < 17 ? __("afternoon") : __("evening"), (cc.boot.user.full_name || "").split(" ")[0]]);
		const head = cc.pagehead(hello, d ? __("{0} to {1}. Stock figures are as of now; changes are measured from the start of the period.", [cc.date(d.period.from_date), cc.date(d.period.to_date)]) : __("Choose the first and last day of the period."), [pick]);
		if (!d) return ctx.root.replaceChildren(head);
		const cur = d.currency;

		// KPI tiles
		const kpis = el("dl", { class: "cc-kpis" }, d.kpis.map((k) => {
			const value = k.currency !== undefined ? cc.money(k.value, k.currency || cur, true) : k.unit === "%" ? cc.num(k.value, 1) : cc.qty(k.value);
			const delta = k.delta && k.delta.value !== null ? el("span", { class: "cc-delta", "data-dir": k.delta.value > 0 ? "up" : k.delta.value < 0 ? "down" : "", "data-good": ["late", "outstanding", "unbilled"].includes(k.key) ? "0" : "1" },
				el("b", { text: (k.delta.value > 0 ? "+" : "") + cc.num(k.delta.value, k.delta.unit === "pts" ? 1 : undefined) + (k.delta.unit === "pts" ? " " + __("pts") : "") }), " " + k.delta.label) : null;
			const tile = el("a", { class: "cc-kpi" + (k.tone === "bad" ? " cc-kpi--alert" : "") + (k.key === "utilization" ? " cc-kpi--hero" : ""), href: cc.base + "/" + k.route, title: k.hint || null },
				el("dt", { text: k.label }),
				el("dd", {}, value, k.unit && k.unit !== "%" && k.currency === undefined ? el("small", { text: k.unit }) : k.unit === "%" ? el("small", { text: "%" }) : null),
				k.sub ? el("span", { class: "cc-delta", text: k.sub }) : null, delta,
				k.key === "utilization" ? cc.chart.tube([{ name: __("On hire"), value: k.value, color: C.s4 }, { name: __("Not on hire"), value: 100 - k.value, color: "#2c4466" }]) : null);
			tile.addEventListener("click", (e) => cc.linkClick(e, tile.getAttribute("href")));
			return tile;
		}));

		// work queue
		const queue = d.queue.length ? table([__("Priority"), __("What needs doing"), __("Reference"), num(__("Waiting")), ""],
			d.queue.map((r) => ({ href: cc.base + "/" + r.route, cells: [
				el("span", { class: "cc-prio", "data-p": r.priority === "high" ? "high" : "low", text: r.priority === "high" ? __("High") : __("Normal") }),
				el("div", { class: "cc-queue-desc" }, el("b", { text: r.title }), el("span", { class: "cc-sub", text: r.party || "" })),
				cc.link(r.route, r.name),
				r.age === null || r.age === undefined ? (r.due ? __("due {0}", [cc.date(r.due)]) : "") : r.age <= 0 ? __("today") : cc.days(r.age),
				cc.btn(r.action, null, { sm: true, href: cc.base + "/" + r.route }),
			] }))) : cc.empty(__("All clear"), __("Nothing is waiting: no open requests, drafts, inspections or billing due."));
		const queuePanel = cc.panel(__("Work queue"), queue, { flush: true, cls: "cc-queue", note: __("{0} items, most urgent first", [d.queue.length]) });

		// today
		const today = d.today;
		const dayList = (rows, kindLabel) => rows.length ? el("ul", { class: "cc-day" }, rows.map((r) => el("li", {},
			el("div", {}, cc.link(r.route, r.name), r.docstatus === 0 ? " " : null, r.docstatus === 0 ? cc.pill(__("Draft")) : null,
				el("small", { text: [r.kind || kindLabel, r.customer_name, r.rental_site, r.vehicle_no].filter(Boolean).join(", ") })),
			r.qty || r.total_qty ? el("span", { class: "cc-strong", text: cc.qty(r.qty || r.total_qty) }) : null))) : el("p", { class: "cc-muted", style: "margin:0", text: __("None today.") });
		const todayPanel = el("div", { class: "cc-stack" },
			cc.panel(__("Deliveries today"), dayList(today.deliveries, __("Delivery order")), { actions: [cc.btn(__("New"), null, { sm: true, icon: "plus", href: cc.base + "/deliveries/new" })] }),
			cc.panel(__("Returns expected today"), dayList(today.returns, "")));

		// charts
		const ch = d.charts;
		const labels = ch.labels;
		const charts = [];
		charts.push(cc.chart.panel(__("Utilization"), __("Share of rental units on hire, at the end of each {0}", [ch.unit]),
			() => cc.chart.xy({ labels, kind: "line", series: [{ name: __("Utilization"), color: C.s1, values: ch.utilization }], fmt: (v) => cc.num(v, 1) + "%", axisFmt: (v) => cc.num(v) + "%", max: 100 }),
			() => cc.chart.table([__("Period"), __("Utilization")], labels.map((l, i) => [l, ch.utilization[i] === null ? "–" : cc.num(ch.utilization[i], 1) + "%"]))));
		charts.push(cc.chart.panel(__("Own and cross-hired at sites"), __("Units at customer sites at the end of each {0}", [ch.unit]),
			() => el("div", {}, cc.chart.xy({ labels, kind: "stacked", series: [{ name: __("Own"), color: C.s1, values: ch.at_site.own }, { name: __("Cross-hired"), color: C.s2, values: ch.at_site.cross }], fmt: cc.qty }),
				cc.chart.legend([{ name: __("Own"), color: C.s1 }, { name: __("Cross-hired"), color: C.s2 }])),
			() => cc.chart.table([__("Period"), __("Own"), __("Cross-hired")], labels.map((l, i) => [l, cc.qty(ch.at_site.own[i]), cc.qty(ch.at_site.cross[i])]))));
		if (ch.revenue) charts.push(cc.chart.panel(__("Rental revenue"), __("Submitted rental and job invoices, net of tax"),
			() => cc.chart.xy({ labels, kind: "bars", series: [{ name: __("Revenue"), color: C.s1, values: ch.revenue }], fmt: (v) => cc.money(v, cur) }),
			() => cc.chart.table([__("Period"), __("Revenue")], labels.map((l, i) => [l, cc.money(ch.revenue[i], cur)]))));
		if (ch.billing) charts.push(cc.chart.panel(__("Billing"), __("Rental billing schedules and JCR periods, by period end"),
			() => cc.chart.xy({ labels, kind: "bars", series: [{ name: __("Billed"), color: C.s3, values: ch.billing }], fmt: (v) => cc.money(v, cur) }),
			() => cc.chart.table([__("Period"), __("Billed")], labels.map((l, i) => [l, cc.money(ch.billing[i], cur)]))));
		if (ch.cross_hire_cost) charts.push(cc.chart.panel(__("Cross-hire expenses"), __("Submitted supplier hire bills"),
			() => cc.chart.xy({ labels, kind: "bars", series: [{ name: __("Supplier bills"), color: C.s2, values: ch.cross_hire_cost }], fmt: (v) => cc.money(v, cur) }),
			() => cc.chart.table([__("Period"), __("Supplier bills")], labels.map((l, i) => [l, cc.money(ch.cross_hire_cost[i], cur)]))));
		const catSeg = (c) => [{ name: __("Own at sites"), value: c.own, color: C.s1 }, { name: __("Cross-hired at sites"), value: c.cross, color: C.s2 },
			{ name: __("Reserved"), value: c.reserved, color: C.s4 }, { name: __("Inspection or repair"), value: c.workshop, color: C.s7 }, { name: __("Free in yard"), value: c.free, color: C.s3 }];
		charts.push(cc.chart.panel(__("Availability by category"), __("Where each category's units are now"),
			() => ch.categories.length ? el("div", {}, cc.chart.hbars(ch.categories.map((c) => ({ label: c.label, route: "inventory?category=" + encodeURIComponent(c.label), segments: catSeg(c), text: __("{0} free", [cc.qty(c.free)]) }))),
				cc.chart.legend(catSeg({}).map((s) => ({ name: s.name, color: s.color })))) : cc.empty(__("No rental items yet")),
			() => cc.chart.table([__("Category"), __("Own at sites"), __("Cross-hired"), __("Reserved"), __("Workshop"), __("Free")], ch.categories.map((c) => [c.label, cc.qty(c.own), cc.qty(c.cross), cc.qty(c.reserved), cc.qty(c.workshop), cc.qty(c.free)]))));
		charts.push(cc.chart.panel(__("Most rented items"), __("Units at customer sites now"),
			() => ch.top_items.length ? el("div", {}, cc.chart.hbars(ch.top_items.map((r) => ({ label: r.label, route: "inventory?item=" + encodeURIComponent(r.key), segments: [{ name: __("Own"), value: r.own, color: C.s1 }, { name: __("Cross-hired"), value: r.cross, color: C.s2 }], text: cc.num(r.utilization, 0) + "%" }))),
				cc.chart.legend([{ name: __("Own"), color: C.s1 }, { name: __("Cross-hired"), color: C.s2 }])) : cc.empty(__("Nothing on hire")),
			() => cc.chart.table([__("Item"), __("Own"), __("Cross-hired"), __("Utilization")], ch.top_items.map((r) => [r.label, cc.qty(r.own), cc.qty(r.cross), cc.num(r.utilization, 1) + "%"]))));
		if (ch.customers) charts.push(cc.chart.panel(__("Revenue by customer"), __("Top customers in the period"),
			() => ch.customers.length ? cc.chart.hbars(ch.customers.map((r) => ({ label: r.label, route: "customers/" + encodeURIComponent(r.key), segments: [{ name: __("Revenue"), value: r.value, color: C.s1 }], text: cc.money(r.value, cur, true) })), { fmt: (v) => cc.money(v, cur) }) : cc.empty(__("No invoices in this period")),
			() => cc.chart.table([__("Customer"), __("Revenue")], ch.customers.map((r) => [r.label, cc.money(r.value, cur)]))));
		if (ch.profitability) charts.push(cc.chart.panel(__("Contract profitability"), __("Invoiced in the period less cross-hire cost (Hire Contract Profitability)"),
			() => ch.profitability.length ? cc.chart.hbars(ch.profitability.map((r) => ({ label: r.label + (r.customer ? ", " + r.customer : ""), route: "contracts/" + encodeURIComponent(r.label),
				segments: [{ name: __("Contribution"), value: Math.max(0, r.value), color: r.value >= 0 ? C.s3 : C.s8 }], text: cc.num(r.margin, 0) + "%" })), { fmt: (v) => cc.money(v, cur) }) : cc.empty(__("No invoiced contracts in this period")),
			() => cc.chart.table([__("Contract"), __("Revenue"), __("Cross-hire cost"), __("Contribution"), __("Margin")], ch.profitability.map((r) => [r.label, cc.money(r.revenue, cur), cc.money(r.cost, cur), cc.money(r.value, cur), cc.num(r.margin, 1) + "%"])),
			{ actions: [cc.btn(__("Report"), null, { sm: true, kind: "ghost", href: cc.base + "/reports/contract-profitability" })] }));

		// recent documents
		const recentTabs = [["hire_orders", __("Hire orders")], ["contracts", __("Contracts")], ["deliveries", __("Deliveries")], ["off_hire", __("Off-hire")]].filter(([k]) => today.recent[k]);
		let recentKey = (recentTabs[0] || [])[0];
		const recentBody = el("div");
		const drawRecent = () => recentBody.replaceChildren(!(today.recent[recentKey] || []).length ? el("p", { class: "cc-muted", text: __("Nothing yet.") }) :
			el("ul", { class: "cc-day" }, today.recent[recentKey].map((r) => el("li", {}, el("div", {}, cc.link(r.route, r.name), el("small", { text: [r.customer_name, cc.date(r.order_date || r.start_date || r.posting_date || r.return_date)].filter(Boolean).join(", ") })), cc.pill(r.status || (r.docstatus === 0 ? "Draft" : ""))))));
		const recentTabsEl = el("div", { class: "cc-tabs", role: "tablist" }, recentTabs.map(([k, l]) => el("button", { type: "button", role: "tab", "aria-selected": k === recentKey ? "true" : "false", text: l, onclick: (e) => {
			recentKey = k;
			recentTabsEl.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", b === e.target ? "true" : "false"));
			drawRecent();
		} })));
		drawRecent();

		ctx.root.replaceChildren(head, kpis,
			el("div", { class: "cc-grid cc-grid--main" }, queuePanel, el("div", { class: "cc-stack" }, todayPanel, recentTabs.length ? cc.panel(__("Recent"), recentBody, { actions: [recentTabsEl] }) : null)),
			el("div", { class: "cc-grid cc-grid--2", style: "margin-top:16px" }, charts),
			el("p", { class: "cc-muted", style: "font-size:12.5px;margin-top:16px", text: __("Figures as of {0}. They refresh at most once a minute.", [cc.datetime(d.generated)]) }));
	};

	// ================================================================== notifications and tasks
	P.notifications = async function (ctx) {
		ctx.setTitle(__("Notifications"));
		const r = await load(ctx, () => cc.api("notifications", { limit: 60 }));
		ctx.root.replaceChildren(
			cc.pagehead(__("Notifications"), __("Mentions, assignments, alerts and shares sent to you."), r.unread ? [cc.btn(__("Mark all as read"), async () => { await cc.api("mark_notifications_read", {}, { post: true }); cc.refreshBadges(); ctx.reload(); }, { icon: "check" })] : []),
			cc.panel(null, r.rows.length ? el("ul", { class: "cc-day", style: "padding:6px 0" }, r.rows.map((n) => el("li", {},
				el("span", { class: "cc-pill", "data-tone": n.read ? "" : "info", text: n.read ? __("Read") : __("New") }),
				el("div", {}, n.target ? cc.link(cc.target(n.target), n.subject) : el("span", { text: n.subject }), el("small", { text: [n.document_type, n.document_name, cc.ago(n.creation)].filter(Boolean).join(", ") })))))
				: cc.empty(__("No notifications"), __("You are up to date."))));
	};
	P.tasks = async function (ctx) {
		ctx.setTitle(__("My Tasks"));
		const status = new URLSearchParams(ctx.query || "").get("status") || "Open";
		const rows = await load(ctx, () => cc.api("my_tasks", { status }));
		ctx.root.replaceChildren(
			cc.pagehead(__("My Tasks"), __("Documents assigned to you. Close a task when the work is done."), [tabsEl([["Open", __("Open")], ["Closed", __("Closed")]], status, (v) => setQuery(ctx, { status: v }))]),
			cc.panel(null, rows.length ? table([__("Task"), __("Document"), __("Due"), __("Assigned by"), ""], rows.map((t) => ({ cells: [
				el("div", {}, el("b", { text: t.description || t.reference_name }), el("span", { class: "cc-sub", text: t.priority ? __("{0} priority", [__(t.priority)]) : "" })),
				t.target ? cc.link(cc.target(t.target), t.reference_name) : t.reference_name || "",
				t.date ? cc.date(t.date) : "",
				t.assigned_by || "",
				status === "Open" ? cc.btn(__("Close"), async () => { await cc.api("close_task", { name: t.name }, { post: true }); cc.toast(__("Task closed."), "ok"); ctx.reload(); }, { sm: true, icon: "check" }) : cc.pill("Closed"),
			] }))) : cc.empty(status === "Open" ? __("No open tasks") : __("No closed tasks"), status === "Open" ? __("Anything assigned to you appears here.") : ""), { flush: true }));
	};

	// ================================================================== customer request inbox
	P.requests = async function (ctx) {
		ctx.setTitle(__("Customer Requests"));
		const q = new URLSearchParams(ctx.query || "");
		const view = q.get("view") || "open";
		const type = q.get("type") || "";
		const search = q.get("q") || "";
		const r = await load(ctx, () => cc.api("requests", { view, search, request_type: type }));
		const searchInput = el("input", { type: "search", value: search, placeholder: __("Customer, contract or site"), "aria-label": __("Search requests") });
		searchInput.addEventListener("change", () => setQuery(ctx, { q: searchInput.value.trim() }));
		const toolbar = el("div", { class: "cc-toolbar" },
			tabsEl([["open", __("Waiting ({0})", [(r.counts.Open || 0) + (r.counts["In Progress"] || 0)])], ["closed", __("Closed")]], view, (v) => setQuery(ctx, { view: v })),
			el("div", { class: "cc-search" }, cc.icon("search", "cc-i--sm"), searchInput),
			el("select", { "aria-label": __("Request type"), onchange: (e) => setQuery(ctx, { type: e.target.value }) }, el("option", { value: "", text: __("All requests") }), r.types.map((t) => el("option", { value: t, text: __(t), selected: t === type }))));
		const rows = r.rows.map((x) => ({ href: cc.base + "/requests/" + encodeURIComponent(x.name), cells: [
			el("div", {}, cc.link("requests/" + encodeURIComponent(x.name), x.name), el("span", { class: "cc-sub", text: __(x.request_type) })),
			el("div", {}, el("b", { text: x.customer_name || x.customer }), el("span", { class: "cc-sub", text: [x.rental_contract, x.rental_site || x.site_location].filter(Boolean).join(", ") }),
				x.lines && x.lines.length ? el("ul", { class: "cc-req-lines" }, x.lines.slice(0, 4).map((l) => el("li", { text: `${cc.qty(l.qty)} ${l.uom || ""} ${l.item_name || l.item_code}` })), x.lines.length > 4 ? el("li", { text: __("and {0} more", [x.lines.length - 4]) }) : null) : null,
				x.new_end_date ? el("span", { class: "cc-sub", text: __("Extend to {0}", [cc.date(x.new_end_date)]) }) : null),
			el("div", {}, cc.date(x.request_date), el("span", { class: "cc-sub", text: x.required_date ? __("needed {0}", [cc.date(x.required_date)]) : "" })),
			x.age_days > 0 ? cc.days(x.age_days) : __("today"),
			el("div", {}, cc.pill(x.status), x.assigned.length ? el("span", { class: "cc-sub", text: x.assigned.join(", ") }) : null),
			view === "open" ? el("div", { class: "cc-actions", style: "justify-content:flex-end" },
				!x.assigned.length ? cc.btn(__("Take"), async () => { await cc.api("assign", { doctype: "Rental Portal Request", name: x.name }, { post: true }); cc.toast(__("{0} assigned to you.", [x.name]), "ok"); ctx.reload(); }, { sm: true, kind: "ghost" }) : null,
				cc.btn(__("Handle"), null, { sm: true, kind: "primary", href: cc.base + "/requests/" + encodeURIComponent(x.name) })) : x.response ? el("span", { class: "cc-sub", text: x.response }) : "",
		] }));
		ctx.root.replaceChildren(
			cc.pagehead(__("Customer Requests"), __("Hire enquiries, collections and extensions raised on the customer portal. The customer sees the status change as you work.")),
			el("section", { class: "cc-panel" }, toolbar, rows.length ? table([__("Request"), __("Customer and items"), __("Raised"), num(__("Waiting")), __("Status"), ""], rows)
				: cc.empty(view === "open" ? __("No requests waiting") : __("No closed requests"), view === "open" ? __("New requests from the customer portal appear here.") : "")));
	};

	// ================================================================== yard / inventory
	const stockSegments = (r) => [
		{ name: __("Own at sites"), value: r.at_site_own, color: C.s1 }, { name: __("Cross-hired at sites"), value: r.at_site_cross_hire, color: C.s2 },
		{ name: __("Reserved"), value: Math.min(r.reserved_qty, Math.max(r.yard_qty, 0)), color: C.s4 },
		{ name: __("Inspection or repair"), value: r.workshop_qty, color: C.s7 }, { name: __("Free in yard"), value: Math.max(r.available_qty, 0), color: C.s3 }];
	P.inventory = async function (ctx) {
		ctx.setTitle(__("Rental Yard"));
		const q = new URLSearchParams(ctx.query || "");
		const category = q.get("category") || "", item = q.get("item") || "";
		const r = await load(ctx, () => cc.api("inventory", { category, item }));
		const rows = r.rows;
		const sum = (k) => rows.reduce((s, x) => s + (Number(x[k]) || 0), 0);
		const totals = { at_site_own: sum("at_site_own"), at_site_cross_hire: sum("at_site_cross_hire"), reserved_qty: sum("reserved_qty"), yard_qty: sum("yard_qty"), workshop_qty: sum("workshop_qty"), available_qty: sum("available_qty") };
		const filterInput = el("input", { type: "search", placeholder: __("Filter items"), "aria-label": __("Filter items") });
		const body = el("div");
		const draw = () => {
			const needle = filterInput.value.trim().toLowerCase();
			const shown = rows.filter((x) => !needle || (x.item_code + " " + x.item_name).toLowerCase().includes(needle));
			body.replaceChildren(shown.length ? table([__("Item"), __("Where the units are"), num(__("Own stock")), num(__("At sites")), num(__("Reserved")), num(__("Workshop")), num(__("Free")), num(__("Utilization"))],
				shown.map((x) => ({ href: cc.base + "/inventory?item=" + encodeURIComponent(x.item_code) + (category ? "&category=" + encodeURIComponent(category) : ""), cells: [
					el("div", {}, cc.link("inventory?item=" + encodeURIComponent(x.item_code), x.item_name), el("span", { class: "cc-sub", text: [x.item_code !== x.item_name ? x.item_code : "", x.category].filter(Boolean).join(", ") })),
					el("div", { style: "min-width:160px" }, cc.chart.tube(stockSegments(x))),
					cc.qty(x.own_total), cc.qty(Number(x.at_site_own) + Number(x.at_site_cross_hire)), cc.qty(x.reserved_qty), cc.qty(x.workshop_qty),
					el("span", { style: x.short ? "color:var(--bad);font-weight:600" : null, text: cc.qty(x.available_qty) }), cc.num(x.utilization, 1) + "%",
				] }))) : cc.empty(__("No rental items"), __("Rental items are items with a Rental Item Profile.")));
		};
		filterInput.addEventListener("input", draw);
		draw();
		const detail = item && r.movements ? itemDetail(rows.find((x) => x.item_code === item), r, ctx) : null;
		ctx.root.replaceChildren(
			cc.pagehead(__("Rental Yard"), __("Every rental item and where its units are now: at customer sites, reserved, in inspection or repair, or free in the yard. From the Rental Stock Position report."),
				[cc.btn(__("Stock position report"), null, { href: cc.base + "/reports/stock-availability", kind: "ghost", icon: "boxes" }), cc.btn(__("New reservation"), null, { href: cc.base + "/reservations/new", icon: "bookmark" })]),
			el("section", { class: "cc-panel", style: "padding:16px 18px;margin-bottom:16px" }, cc.chart.tube(stockSegments(totals), true), cc.chart.legend(stockSegments(totals).map((s) => ({ name: `${s.name} ${cc.qty(s.value)}`, color: s.color })))),
			detail,
			el("section", { class: "cc-panel" }, el("div", { class: "cc-toolbar" },
				el("div", { class: "cc-search" }, cc.icon("search", "cc-i--sm"), filterInput),
				el("select", { "aria-label": __("Category"), onchange: (e) => setQuery(ctx, { category: e.target.value, item: null }) }, el("option", { value: "", text: __("All categories") }), r.categories.map((c) => el("option", { value: c, text: c, selected: c === category })))), body));
	};
	function itemDetail(row, r, ctx) {
		if (!row) return null;
		const moves = r.movements || [];
		return cc.panel(__("{0}: movements", [row.item_name]), el("div", { class: "cc-grid cc-grid--main", style: "padding:0 0 4px" },
			moves.length ? table([__("Date"), __("Warehouse"), num(__("Qty")), num(__("Balance")), __("Document")], moves.map((m) => ({ cells: [
				cc.date(m.posting_date), m.warehouse, el("span", { style: `color:${m.actual_qty < 0 ? "var(--bad)" : "var(--ok)"};font-weight:600`, text: (m.actual_qty > 0 ? "+" : "") + cc.qty(m.actual_qty) }), cc.qty(m.qty_after_transaction),
				m.target ? (cc.target(m.target).startsWith(cc.base) ? cc.link(cc.target(m.target), m.source_name) : el("a", { href: cc.target(m.target), text: m.source_name })) : m.source_name,
			] }))) : cc.empty(__("No stock movements")),
			el("div", {}, el("h3", { style: "margin:0 0 8px;font:600 16px var(--font-cond)", text: __("Stock by warehouse") }),
				(r.warehouses || []).length ? table([__("Warehouse"), num(__("Qty"))], r.warehouses.map((w) => ({ cells: [w.warehouse, cc.qty(w.actual_qty)] })), { cards: false }) : el("p", { class: "cc-muted", text: __("No stock.") }))),
			{ actions: [cc.btn(__("Close"), () => setQuery(ctx, { item: null }), { sm: true, kind: "ghost", icon: "x" })] });
	}

	// ================================================================== material at customer sites
	P.material = async function (ctx) {
		ctx.setTitle(__("Material at Customer Sites"));
		const q = new URLSearchParams(ctx.query || "");
		const search = q.get("q") || "", ownership = q.get("ownership") || "";
		const r = await load(ctx, () => cc.api("material_at_site", { search, ownership }));
		const s = el("input", { type: "search", value: search, placeholder: __("Customer, site, contract or item"), "aria-label": __("Search") });
		s.addEventListener("change", () => setQuery(ctx, { q: s.value.trim() }));
		ctx.root.replaceChildren(
			cc.pagehead(__("Material at Customer Sites"), __("{0} units at {1} sites, {2} of them cross-hired. Replacement value {3}.", [cc.qty(r.totals.total), r.groups.length, cc.qty(r.totals.cross), cc.money(r.totals.value)]),
				[cc.btn(__("New off-hire note"), null, { href: cc.base + "/off-hire/new", icon: "undo-2" })]),
			el("section", { class: "cc-panel", style: "margin-bottom:16px" }, el("div", { class: "cc-toolbar", style: "border:0" },
				el("div", { class: "cc-search" }, cc.icon("search", "cc-i--sm"), s),
				tabsEl([["", __("All")], ["Own", __("Own")], ["Cross Hire", __("Cross-hired")]], ownership, (v) => setQuery(ctx, { ownership: v })))),
			r.groups.length ? el("div", { class: "cc-stack" }, r.groups.map((g) => cc.panel(g.customer_name + (g.site ? ", " + g.site : ""),
				table([__("Item"), __("Ownership"), num(__("Delivered")), num(__("Returned")), num(__("At site")), num(__("Days at site")), num(__("Replacement value"))], g.rows.map((x) => ({ cells: [
					el("div", {}, el("b", { text: x.item_name }), el("span", { class: "cc-sub", text: x.description || x.item_code })),
					x.ownership === "Cross Hire" ? el("span", {}, cc.pill(__("Cross-hired"), "warn"), x.cross_hire_order ? el("span", { class: "cc-sub" }, cc.link("cross-hire/" + encodeURIComponent(x.cross_hire_order), x.cross_hire_order)) : null) : cc.pill(__("Own"), ""),
					cc.qty(x.delivered_qty), cc.qty(x.returned_qty + (x.lost_qty || 0)), el("b", { text: cc.qty(x.qty) }), x.days_at_site ?? "", cc.money(x.replacement_value),
				] })), { foot: [__("Total"), "", "", "", cc.qty(g.total), "", cc.money(g.value)] }),
				{ flush: true, actions: [cc.btn(g.contract, null, { sm: true, kind: "ghost", href: cc.base + "/contracts/" + encodeURIComponent(g.contract) }), cc.btn(__("Off-hire"), null, { sm: true, href: cc.base + "/off-hire/new?rental_contract=" + encodeURIComponent(g.contract) })] })))
				: cc.panel(null, cc.empty(__("No material at customer sites"), search || ownership ? __("Nothing matches these filters.") : "")));
	};

	// ================================================================== cross hire suppliers
	P.suppliers = async function (ctx) {
		ctx.setTitle(__("Supplier Position"));
		const r = await load(ctx, () => cc.api("supplier_position"));
		const t = r.totals;
		ctx.root.replaceChildren(
			cc.pagehead(__("Supplier Position"), __("Equipment hired in from suppliers: what is on hire, where it is, what is overdue for return and what has been billed. From the Cross Hire Position report."),
				[cc.btn(__("New cross hire order"), null, { href: cc.base + "/cross-hire/new", kind: "primary", icon: "plus" })]),
			el("dl", { class: "cc-kpis", style: "grid-template-columns:repeat(4,minmax(0,1fr))" },
				[[__("On hire from suppliers"), cc.qty(t.on_hire)], [__("At customer sites"), cc.qty(t.at_site)], [__("Idle in our yard"), cc.qty(t.idle)], [__("Orders overdue"), t.overdue]].map(([l, v], i) => el("div", { class: "cc-kpi" + (i === 3 && t.overdue ? " cc-kpi--alert" : "") }, el("dt", { text: l }), el("dd", { text: v })))),
			cc.panel(__("By supplier"), r.suppliers.length ? table([__("Supplier"), num(__("Orders")), num(__("On hire")), num(__("At sites")), num(__("Idle")), num(__("Overdue")), num(__("Billed"))],
				r.suppliers.map((s) => ({ cells: [s.supplier, s.orders, cc.qty(s.on_hire), cc.qty(s.at_site), cc.qty(s.idle), s.overdue ? el("b", { style: "color:var(--bad)", text: s.overdue }) : "0", cc.money(s.billed)] }))) : cc.empty(__("No cross hire")), { flush: true }),
			cc.panel(__("Orders"), r.groups.length ? table([__("Order"), __("Supplier"), __("Contract"), num(__("On hire")), __("Due back"), __("Bills")], r.groups.map((g) => ({ href: cc.base + "/" + g.route, cells: [
				el("div", {}, cc.link(g.route, g.order), el("span", { class: "cc-sub" }, cc.pill(g.status))),
				g.supplier, g.contract ? cc.link("contracts/" + encodeURIComponent(g.contract), g.contract) : "",
				cc.qty(g.on_hire),
				el("div", {}, cc.date(g.due), g.overdue_days > 0 ? el("span", { class: "cc-sub", style: "color:var(--bad)", text: __("{0} overdue", [cc.days(g.overdue_days)]) }) : null),
				g.invoices.length ? el("div", {}, g.invoices.map((i) => el("span", { class: "cc-sub" }, el("a", { href: "/app/purchase-invoice/" + encodeURIComponent(i.name), text: i.name }), " ", cc.money(i.grand_total)))) : el("span", { class: "cc-muted", text: __("Not billed") }),
			] }))) : cc.empty(__("No open cross hire orders")), { flush: true }));
	};

	// ================================================================== billing control centre
	P.billing = async function (ctx) {
		ctx.setTitle(__("Rental Billing"));
		const search = new URLSearchParams(ctx.query || "").get("q") || "";
		const b = await load(ctx, () => cc.api("billing_center", { search }));
		const billOne = async (contract, button) => {
			if (button) button.disabled = true;
			try {
				const r = await cc.api("bill_contract", { rental_contract: contract, only_complete: 1 }, { post: true });
				const n = (r.schedules || []).length;
				cc.toast(n ? __("{0}: {1} billing period(s) billed.", [contract, n]) : __("{0}: no complete period to bill yet.", [contract]), n ? "ok" : "");
				return n;
			} catch (e) {
				if (button) button.disabled = false;
				return 0;
			}
		};
		const billAll = async (btn) => {
			if (!b.due.length) return;
			if (!(await cc.confirm(__("Bill all due contracts?"), __("Runs the rental billing engine for {0} contracts whose billing date has passed. Complete periods are billed, as the nightly billing does.", [b.due.length]), __("Bill all due")))) return;
			btn.disabled = true;
			let made = 0;
			for (const r of b.due) made += await billOne(r.rental_contract);
			cc.toast(__("Billing finished: {0} period(s) billed.", [made]), "ok");
			ctx.reload();
		};
		const s = el("input", { type: "search", class: "cc-input", style: "width:240px", value: search, placeholder: __("Contract, customer or site"), "aria-label": __("Search") });
		s.addEventListener("change", () => setQuery(ctx, { q: s.value.trim() }));
		const allBtn = b.can_bill && b.due.length ? cc.btn(__("Bill all due ({0})", [b.due.length]), (e) => billAll(e.currentTarget), { kind: "primary", icon: "receipt" }) : null;
		const tiles = [[__("Accrued, not billed"), cc.money(b.accrued_total, null, true), __("to yesterday, {0} contracts", [b.accrued.length])], [__("Billing due"), b.due.length, __("contracts past their billing date")],
			[__("JCR periods pending"), cc.money(b.jcr_pending_total, null, true), __("{0} periods", [b.jcr_pending.length])], [__("Billed this month"), cc.money(b.billed_this_month, null, true), __("rental and job invoices")],
			[__("Receivable"), cc.money(b.receivable, null, true), __("{0} overdue", [cc.money(b.late_total, null, true)])], [__("Damage and loss recovered"), cc.money(b.recoveries, null, true), __("submitted settlements")]];
		ctx.root.replaceChildren(
			cc.pagehead(__("Rental Billing"), __("Accrued rent per contract, from the Unbilled Rental report. Billing runs the same engine as the nightly job and the desk: complete periods only, never twice."),
				[allBtn, cc.btn(__("Billing schedules"), null, { href: cc.base + "/billing-schedules", kind: "ghost" }), cc.btn(__("JCR periods"), null, { href: cc.base + "/jcr-billing", kind: "ghost" })].filter(Boolean)),
			el("dl", { class: "cc-kpis" }, tiles.map(([l, v, sub]) => el("div", { class: "cc-kpi" }, el("dt", { text: l }), el("dd", { text: v }), el("span", { class: "cc-delta", text: sub })))),
			el("section", { class: "cc-panel" }, el("header", {}, el("h2", { text: __("Accrued rent by contract") }), el("div", { class: "cc-actions" }, el("div", { class: "cc-search", style: "position:relative" }, s))),
				b.accrued.length ? table([__("Contract"), __("Customer"), __("Billed up to"), __("Next billing"), num(__("At site")), num(__("Accrued")), num(__("Billed to date")), ""],
					b.accrued.map((r) => ({ cells: [
						cc.link("contracts/" + encodeURIComponent(r.rental_contract), r.rental_contract),
						el("div", {}, r.customer_name || r.customer, el("span", { class: "cc-sub", text: r.rental_site || "" })),
						cc.date(r.last_billed_upto) || el("span", { class: "cc-muted", text: __("never") }),
						el("div", {}, cc.date(r.next_billing_date), r.overdue ? el("span", { class: "cc-sub", style: "color:var(--warn);font-weight:600", text: __("due") }) : null),
						cc.qty(r.at_site_qty), el("b", { text: cc.money(r.unbilled_amount) }), cc.money(r.billed_amount),
						b.can_bill ? (() => { const btn = cc.btn(__("Bill now"), async () => { if (await billOne(r.rental_contract, btn)) ctx.reload(); }, { sm: true }); return btn; })() : "",
					] })), { foot: [__("Total"), "", "", "", "", cc.money(b.accrued_total), "", ""] }) : cc.empty(__("Nothing accrued"), __("Every contract is billed up to yesterday."))),
			b.jcr_pending.length ? cc.panel(__("JCR periods waiting for an invoice"), table([__("JCR"), __("Customer"), __("Charge"), __("Period"), num(__("Amount"))], b.jcr_pending.map((r) => ({ href: cc.base + "/" + r.route, cells: [
				cc.link(r.route, r.jcr), r.customer, __(r.billing_type), cc.date(r.period_from) + " – " + cc.date(r.period_to), cc.money(r.amount)] }))), { flush: true, note: __("Open the JCR to invoice it, alone or with the customer's other open JCRs.") }) : null,
			cc.panel(__("Unpaid rental invoices"), b.invoices.length ? table([__("Invoice"), __("Customer"), __("Contract"), __("Due"), num(__("Total")), num(__("Outstanding"))], b.invoices.map((i) => ({ href: cc.base + "/invoices/" + encodeURIComponent(i.name), cells: [
				cc.link("invoices/" + encodeURIComponent(i.name), i.name), i.customer_name, i.nxg_rental_contract || "", el("div", {}, cc.date(i.due_date), i.days_late > 0 ? el("span", { class: "cc-sub", style: "color:var(--bad)", text: __("{0} late", [cc.days(i.days_late)]) }) : null),
				cc.money(i.grand_total, i.currency), el("b", { text: cc.money(i.outstanding_amount, i.currency) })] }))) : cc.empty(__("No unpaid rental invoices")), { flush: true, actions: [cc.btn(__("Outstanding by customer"), null, { sm: true, kind: "ghost", href: cc.base + "/outstanding" })] }));
	};

	// ================================================================== outstanding payments
	P.outstanding = async function (ctx) {
		ctx.setTitle(__("Outstanding Payments"));
		const r = await load(ctx, () => cc.api("outstanding"));
		const cust = new URLSearchParams(ctx.query || "").get("customer") || "";
		const invoices = cust ? r.invoices.filter((i) => i.customer === cust) : r.invoices;
		const bucketColor = { current: C.s3, d30: C.s4, d60: C.s2, d90: C.s8, d90p: "#8f1d1d" };
		ctx.root.replaceChildren(
			cc.pagehead(__("Outstanding Payments"), __("Unpaid rental, job and damage invoices, aged by due date. Receive payment against the invoice in the desk (Create, Payment).")),
			el("section", { class: "cc-panel", style: "padding:16px 18px;margin-bottom:16px" },
				el("div", { style: "display:flex;gap:24px;flex-wrap:wrap;margin-bottom:12px" }, el("div", {}, el("div", { class: "cc-muted", style: "font-size:13px;font-weight:600", text: __("Total outstanding") }), el("div", { style: "font:600 30px/1.1 var(--font-cond)", text: cc.money(r.totals.total) })),
					r.buckets.map((bk) => el("div", {}, el("div", { class: "cc-muted", style: "font-size:13px;font-weight:600", text: bk.label }), el("div", { style: "font:600 20px/1.3 var(--font-cond)", text: cc.money(r.totals[bk.key]) })))),
				cc.chart.tube(r.buckets.map((bk) => ({ name: bk.label, value: r.totals[bk.key], color: bucketColor[bk.key] })), true),
				cc.chart.legend(r.buckets.map((bk) => ({ name: bk.label, color: bucketColor[bk.key] })))),
			cc.panel(__("By customer"), r.customers.length ? table([__("Customer"), num(__("Invoices")), ...r.buckets.map((bk) => num(bk.label)), num(__("Total"))], r.customers.map((c) => ({ href: cc.base + "/outstanding?customer=" + encodeURIComponent(c.customer), cells: [
				el("div", {}, cc.link("customers/" + encodeURIComponent(c.customer), c.customer_name || c.customer)), c.count, ...r.buckets.map((bk) => (c[bk.key] ? cc.money(c[bk.key]) : el("span", { class: "cc-muted", text: "–" }))), el("b", { text: cc.money(c.total) })] }))) : cc.empty(__("Nothing outstanding"), __("Every rental invoice is paid.")), { flush: true }),
			cc.panel(cust ? __("Invoices of {0}", [(r.customers.find((c) => c.customer === cust) || {}).customer_name || cust]) : __("Invoices"), invoices.length ? table([__("Invoice"), __("Customer"), __("Due"), num(__("Total")), num(__("Outstanding")), ""], invoices.map((i) => ({ cells: [
				cc.link("invoices/" + encodeURIComponent(i.name), i.name), i.customer_name, el("div", {}, cc.date(i.due_date), i.days_late > 0 ? el("span", { class: "cc-sub", style: "color:var(--bad)", text: __("{0} late", [cc.days(i.days_late)]) }) : null),
				cc.money(i.grand_total), el("b", { text: cc.money(i.outstanding_amount) }), r.can_pay ? cc.btn(__("Receive payment"), null, { sm: true, href: "/app/sales-invoice/" + encodeURIComponent(i.name), title: __("Opens the invoice in the desk: Create, Payment") }) : ""] }))) : cc.empty(__("No invoices")),
				{ flush: true, actions: cust ? [cc.btn(__("Show all"), () => setQuery(ctx, { customer: null }), { sm: true, kind: "ghost" })] : null }));
	};

	// ================================================================== utilization
	P.utilization = async function (ctx) {
		ctx.setTitle(__("Rental Utilization"));
		const period = new URLSearchParams(ctx.query || "").get("period") || "year";
		const r = await load(ctx, () => cc.api("utilization", { period }));
		const pts = r.points;
		ctx.root.replaceChildren(
			cc.pagehead(__("Rental Utilization"), __("Units on hire as a share of all rental units (own stock plus cross-hired stock in custody), from the stock and ownership ledgers."),
				[tabsEl(PERIODS.filter(([k]) => k !== "custom" && k !== "today"), period, (v) => setQuery(ctx, { period: v }))]),
			cc.chart.panel(__("Utilization over time"), __("At the end of each {0}", [r.unit]),
				() => cc.chart.xy({ labels: pts.map((p) => p.label), kind: "line", height: 260, max: 100, series: [{ name: __("Utilization"), color: C.s1, values: pts.map((p) => p.utilization) }], fmt: (v) => cc.num(v, 1) + "%", axisFmt: (v) => cc.num(v) + "%" }),
				() => cc.chart.table([__("Period"), __("Utilization"), __("On hire"), __("Rental units")], pts.map((p) => [p.label, p.utilization === null ? "–" : cc.num(p.utilization, 1) + "%", p.on_hire === undefined ? "–" : cc.qty(p.on_hire), p.rentable === undefined ? "–" : cc.qty(p.rentable)]))),
			cc.panel(__("By item, now"), table([__("Item"), __("Category"), "", num(__("On hire")), num(__("Rental units")), num(__("Utilization"))], r.items.map((x) => ({ href: cc.base + "/inventory?item=" + encodeURIComponent(x.item_code), cells: [
				el("div", {}, cc.link("inventory?item=" + encodeURIComponent(x.item_code), x.item_name)), x.category || "", el("div", { style: "min-width:140px" }, cc.chart.tube([{ name: __("On hire"), value: x.utilization, color: C.s1 }, { name: __("Not on hire"), value: 100 - x.utilization, color: "#dfe5ec" }])),
				cc.qty(Number(x.at_site_own) + Number(x.at_site_cross_hire)), cc.qty(x.rentable), el("b", { text: cc.num(x.utilization, 1) + "%" })] }))), { flush: true }));
	};

	// ================================================================== reports
	P.report = async function (ctx) {
		const meta = await load(ctx, () => cc.api("report_meta", { view: ctx.path }));
		ctx.setTitle(meta.label);
		const q = new URLSearchParams(ctx.query || "");
		const values = {};
		meta.filters.forEach((f) => (values[f.fieldname] = q.has(f.fieldname) ? q.get(f.fieldname) : f.default ?? ""));
		const out = el("div");
		const fields = el("div", { class: "cc-toolbar", style: "align-items:flex-end" }, meta.filters.filter((f) => f.fieldname !== "company").map((f) => {
			let input;
			const change = (v) => { values[f.fieldname] = v; run(); };
			if (f.fieldtype === "Link") {
				const [i, list] = cc.linkInput(f.options, values[f.fieldname], change, { label: f.label });
				input = [i, list];
			} else if (f.fieldtype === "Select") input = [el("select", { onchange: (e) => change(e.target.value) }, f.options.map((o) => el("option", { value: o, text: o ? __(o) : __("Any"), selected: o === values[f.fieldname] })))];
			else if (f.fieldtype === "Check") input = [el("input", { type: "checkbox", checked: !!Number(values[f.fieldname]), onchange: (e) => change(e.target.checked ? 1 : 0) })];
			else input = [el("input", { type: f.fieldtype === "Date" ? "date" : "text", value: values[f.fieldname] || "", onchange: (e) => change(e.target.value) })];
			return el("label", { class: "cc-field", style: f.fieldtype === "Check" ? "display:flex;gap:8px;align-items:center;height:36px" : "min-width:160px" }, el("span", { class: "cc-flabel", text: f.label }), ...input);
		}));
		let last;
		const exportBtn = cc.btn(__("Export"), () => {
			if (!last) return;
			const cols = last.columns;
			const lines = [cols.map((c) => c.label)].concat(last.rows.map((r) => cols.map((c) => r[c.fieldname] ?? "")));
			cc.download(meta.label + ".csv", lines.map((l) => l.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n"));
		}, { icon: "download" });
		async function run() {
			const p = new URLSearchParams();
			Object.entries(values).forEach(([k, v]) => v !== "" && v !== null && v !== undefined && v !== (meta.filters.find((f) => f.fieldname === k) || {}).default && p.set(k, v));
			history.replaceState(history.state, "", cc.base + "/" + ctx.path + (p.toString() ? "?" + p : ""));
			out.replaceChildren(cc.skeleton(6));
			try {
				const filters = {};
				Object.entries(values).forEach(([k, v]) => v !== "" && v !== null && (filters[k] = v));
				const r = await cc.call("frappe.desk.query_report.run", { report_name: meta.name, filters: JSON.stringify(filters), ignore_prepared_report: 1 });
				const cols = (r.columns || []).map((c) => (typeof c === "string" ? parseCol(c) : { label: c.label, fieldname: c.fieldname, fieldtype: c.fieldtype || "Data", options: c.options })).filter((c) => c.fieldname);
				const rows = (r.result || []).filter((x) => x && typeof x === "object").map((x) => (Array.isArray(x) ? Object.fromEntries(cols.map((c, i) => [c.fieldname, x[i]])) : x));
				last = { columns: cols, rows };
				out.replaceChildren(
					(r.report_summary || []).length ? el("dl", { class: "cc-kpis", style: `grid-template-columns:repeat(${Math.min(r.report_summary.length, 6)},minmax(0,1fr));margin:14px` },
						r.report_summary.map((s) => el("div", { class: "cc-kpi", style: "min-height:0" }, el("dt", { text: s.label }), el("dd", { style: "font-size:24px", text: cc.fmt(s.value, s.datatype) })))) : null,
					rows.length ? el("div", { class: "cc-tablewrap" }, el("table", { class: "cc-table cc-table--nowrap" },
						el("thead", {}, el("tr", {}, cols.map((c) => el("th", { class: cc.NUM.includes(c.fieldtype) ? "cc-num" : null, text: c.label })))),
						el("tbody", {}, rows.slice(0, 1000).map((x) => el("tr", {}, cols.map((c) => el("td", { class: cc.NUM.includes(c.fieldtype) ? "cc-num" : null }, reportCell(c, x[c.fieldname])))))))) : cc.empty(__("No rows"), __("Nothing matches these filters.")),
					rows.length > 1000 ? el("p", { class: "cc-muted", style: "padding:0 14px", text: __("Showing the first 1,000 of {0} rows. Export or open the report in the desk for all of them.", [rows.length]) }) : null);
			} catch (e) {
				out.replaceChildren(el("div", { class: "cc-error", style: "margin:14px", text: e.message }));
			}
		}
		ctx.root.replaceChildren(cc.pagehead(meta.label, meta.description || __("Runs the {0} report with your permissions.", [meta.label]), [exportBtn, cc.btn(__("Open in desk"), null, { href: meta.desk_url, kind: "ghost", icon: "external-link" })]),
			el("section", { class: "cc-panel" }, fields, out));
		run();
	};
	function parseCol(s) {
		const [label, type] = s.split(":");
		const [fieldtype, options] = (type || "Data").split("/");
		return { label, fieldname: label.toLowerCase().replace(/[^a-z0-9]+/g, "_"), fieldtype, options };
	}
	function reportCell(c, v) {
		if (v === null || v === undefined || v === "") return "";
		if (c.fieldtype === "Link" && c.options && !/^total$/i.test(String(v))) {
			const routes = { "Rental Contract": "contracts", Customer: "customers", "Cross Hire Order": "cross-hire", "Rental Site": "sites", Item: "inventory?item=" };
			const r = routes[c.options];
			if (r) return cc.link(r.endsWith("=") ? r + encodeURIComponent(v) : r + "/" + encodeURIComponent(v), String(v));
		}
		if (c.fieldtype === "Dynamic Link") return String(v);
		return cc.fmt(v, c.fieldtype);
	}

	// ================================================================== customers
	P.customers = async function (ctx) {
		ctx.setTitle(__("Customers"));
		const q = new URLSearchParams(ctx.query || "");
		const search = q.get("q") || "", page = Number(q.get("page")) || 1;
		const r = await load(ctx, () => cc.api("customers", { search, page }));
		const s = el("input", { type: "search", value: search, placeholder: __("Name, phone or email"), "aria-label": __("Search customers") });
		s.addEventListener("change", () => setQuery(ctx, { q: s.value.trim(), page: null }));
		const pages = Math.max(1, Math.ceil(r.total / r.page_size));
		ctx.root.replaceChildren(
			cc.pagehead(__("Customers"), __("{0} customers. Open one to see its sites, contracts, material at site and unpaid invoices.", [cc.num(r.total)]),
				[r.can_create ? cc.btn(__("New customer"), null, { href: "/app/customer/new", icon: "plus" }) : null].filter(Boolean)),
			el("section", { class: "cc-panel" }, el("div", { class: "cc-toolbar" }, el("div", { class: "cc-search" }, cc.icon("search", "cc-i--sm"), s)),
				r.rows.length ? table([__("Customer"), __("Group"), __("Contact"), num(__("Live contracts")), num(__("At site")), num(__("Outstanding"))], r.rows.map((c) => ({ href: cc.base + "/customers/" + encodeURIComponent(c.name), cells: [
					el("div", {}, cc.link("customers/" + encodeURIComponent(c.name), c.customer_name), c.customer_name !== c.name ? el("span", { class: "cc-sub", text: c.name }) : null), c.customer_group || "",
					el("div", {}, c.mobile_no || "", el("span", { class: "cc-sub", text: c.email_id || "" })), c.live_contracts, cc.qty(c.at_site), c.outstanding ? cc.money(c.outstanding) : el("span", { class: "cc-muted", text: "–" })] }))) : cc.empty(__("No customers found")),
				el("div", { class: "cc-pager" }, el("span", { text: __("Page {0} of {1}", [page, pages]) }), el("div", { class: "cc-actions" },
					Object.assign(cc.btn(__("Previous"), () => setQuery(ctx, { page: page - 1 }), { sm: true }), { disabled: page <= 1 }),
					Object.assign(cc.btn(__("Next"), () => setQuery(ctx, { page: page + 1 }), { sm: true }), { disabled: page >= pages })))));
	};
	P.customer = async function (ctx) {
		const c = await load(ctx, () => cc.api("customer_overview", { customer: ctx.name }));
		ctx.setTitle(c.customer_name, [{ label: __("Customers"), route: "customers" }]);
		cc.remember({ href: location.pathname, title: c.customer_name, label: __("Customer") });
		const tiles = [[__("Live contracts"), (c.contracts || []).filter((x) => ["Active", "On Hire"].includes(x.status)).length], [__("Units at site"), cc.qty(c.at_site || 0)], [__("Sites"), (c.sites || []).length], [__("Outstanding"), cc.money(c.outstanding || 0, null, true)]];
		ctx.root.replaceChildren(
			cc.pagehead(c.customer_name, [c.customer_group, c.territory, c.mobile_no, c.email_id].filter(Boolean).join(", "), [
				cc.btn(__("New hire order"), null, { href: cc.base + "/hire-orders/new?customer=" + encodeURIComponent(c.name), icon: "plus" }),
				cc.btn(__("New quotation"), null, { href: cc.base + "/sales/quotations/new?party_name=" + encodeURIComponent(c.name) }),
				cc.btn(__("View customer portal"), null, { href: "/rental?customer=" + encodeURIComponent(c.name), target: "_blank", kind: "ghost", icon: "external-link" }),
				cc.btn(__("Open in desk"), null, { href: c.desk_url, kind: "ghost" })]),
			el("dl", { class: "cc-kpis", style: "grid-template-columns:repeat(4,minmax(0,1fr))" }, tiles.map(([l, v]) => el("div", { class: "cc-kpi", style: "min-height:0" }, el("dt", { text: l }), el("dd", { text: v })))),
			el("div", { class: "cc-grid cc-grid--main" },
				el("div", { class: "cc-stack" },
					c.contracts ? cc.panel(__("Rental contracts"), c.contracts.length ? table([__("Contract"), __("Site"), __("Period"), num(__("At site")), num(__("Billed")), __("Status")], c.contracts.map((x) => ({ href: cc.base + "/contracts/" + encodeURIComponent(x.name), cells: [
						cc.link("contracts/" + encodeURIComponent(x.name), x.name), x.rental_site || "", cc.date(x.start_date) + " – " + cc.date(x.end_date), cc.qty(x.total_at_site_qty), cc.money(x.total_billed_amount), cc.pill(x.status)] }))) : cc.empty(__("No contracts")), { flush: true }) : null,
					c.invoices ? cc.panel(__("Unpaid invoices"), c.invoices.length ? table([__("Invoice"), __("Due"), num(__("Total")), num(__("Outstanding"))], c.invoices.map((i) => ({ href: cc.base + "/invoices/" + encodeURIComponent(i.name), cells: [cc.link("invoices/" + encodeURIComponent(i.name), i.name), cc.date(i.due_date), cc.money(i.grand_total), el("b", { text: cc.money(i.outstanding_amount) })] }))) : cc.empty(__("Nothing outstanding")), { flush: true }) : null),
				c.sites ? cc.panel(__("Sites"), c.sites.length ? el("ul", { class: "cc-day" }, c.sites.map((s) => el("li", {}, el("div", {}, cc.link("sites/" + encodeURIComponent(s.name), s.name), el("small", { text: [s.site_contact, s.contact_phone].filter(Boolean).join(", ") })), s.disabled ? cc.pill(__("Disabled"), "") : null))) : cc.empty(__("No sites")),
					{ actions: [cc.btn(__("New site"), null, { sm: true, icon: "plus", href: cc.base + "/sites/new?customer=" + encodeURIComponent(c.name) })] }) : null));
	};

	// ================================================================== users and settings
	P.users = async function (ctx) {
		ctx.setTitle(__("Users & Roles"));
		const rows = await load(ctx, () => cc.api("users_roles"));
		ctx.root.replaceChildren(cc.pagehead(__("Users & Roles"), __("Who has a rental role. Rental User enters documents, Rental Manager also cancels and changes settings, System Manager manages users. Change roles on the user in the desk."),
			[cc.btn(__("New user"), null, { href: "/app/user/new", icon: "plus" })]),
			cc.panel(null, table([__("User"), __("Roles"), __("Last active"), __("Status"), ""], rows.map((u) => ({ cells: [
				el("div", {}, el("b", { text: u.full_name || u.name }), el("span", { class: "cc-sub", text: u.name })), el("div", { style: "display:flex;gap:4px;flex-wrap:wrap" }, u.roles.map((r) => cc.pill(r, r === "Customer" ? "" : "info"))),
				u.last_active ? cc.ago(u.last_active) : el("span", { class: "cc-muted", text: __("never") }), u.enabled ? cc.pill(__("Enabled"), "ok") : cc.pill(__("Disabled"), ""),
				cc.btn(__("Edit roles"), null, { sm: true, href: u.desk_url })] }))), { flush: true }));
	};
	P.settings = async function (ctx) {
		ctx.setTitle(__("Rental Settings"));
		const s = await load(ctx, () => cc.api("settings_summary"));
		ctx.root.replaceChildren(cc.pagehead(__("Rental Settings"), __("How billing, warehouses, numbering and the customer portal behave. Settings are changed in the desk, where every field has its help text."),
			[s.can_edit ? cc.btn(__("Edit settings"), null, { href: s.desk_url, kind: "primary", icon: "settings" }) : null, cc.btn(__("Rental item profiles"), null, { href: cc.base + "/item-profiles", kind: "ghost" })].filter(Boolean)),
			el("div", { class: "cc-grid cc-grid--2" }, s.sections.map((sec) => cc.panel(sec.label || __("General"), el("dl", { class: "cc-fields", style: "margin:0" },
				sec.fields.map((f) => el("div", { class: "cc-field" }, el("dt", { class: "cc-flabel", text: f.label }), el("dd", { style: "margin:0", text: cc.fmt(f.value, f.fieldtype) || "–" }))))))));
	};
})();
