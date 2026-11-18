/* thinkNXG Rental customer Command Center: dashboard and rental operations pages. */
(function () {
	"use strict";
	const { el, icon } = cp;
	const P = cp.pages;
	const C = cp.COLORS;
	const SITE_COLORS = ["#5aa9ff", "#2cc4bd", "#f2b84b", "#a78bfa", "#ff8a65", "#7fd38a", "#e879a8", "#94a3b8"];

	function greeting() {
		const h = new Date().getHours();
		return h < 12 ? __("Good morning") : h < 17 ? __("Good afternoon") : __("Good evening");
	}
	function orderStatus(r) {
		if (r.overdue) return cp.badge("Overdue");
		if (r.ending_soon) return el("span", {}, cp.badge(r.status), " ", cp.badge("Ending soon", "warn"));
		return cp.badge(r.status);
	}
	const raise = (type, extra) => cp.href("requests/new?type=" + encodeURIComponent(type) + (extra || ""));

	// ================================================================== dashboard
	P.dashboard = async function (ctx) {
		ctx.setTitle(__("Dashboard"));
		const d = await cp.api("dashboard");
		if (!ctx.isCurrent()) return;
		const k = d.kpi, o = d.ops;
		const company = cp.state.customer ? cp.customerName() : d.customer_names.join(", ");
		const onSiteTotal = d.by_site.reduce((s, x) => s + x.qty, 0);

		const band = d.by_site.length ? el("div", { class: "cp-band" },
			el("div", { class: "cp-band__bar", role: "img", "aria-label": __("Material on site by site") },
				d.by_site.map((s, i) => el("i", { style: { width: (100 * s.qty) / (onSiteTotal || 1) + "%", background: SITE_COLORS[i % SITE_COLORS.length] }, title: s.site + ": " + cp.qty(s.qty) }))),
			el("div", { class: "cp-band__legend" }, d.by_site.map((s, i) => el("span", {}, el("i", { style: { background: SITE_COLORS[i % SITE_COLORS.length] } }), s.site, " ", el("b", { text: cp.qty(s.qty) }))))) : null;
		const hello = el("section", { class: "cp-hello" },
			el("div", { style: { position: "relative", zIndex: 1 } },
				el("h1", { text: greeting() + ", " + (cp.boot.user.first_name || "") }),
				el("p", { text: __("Here's an overview of your rental operations and account activity.") }),
				el("span", { class: "cp-hello__company" }, icon("building-2", "cp-i--sm"), company)),
			el("div", { class: "cp-hello__figure" }, el("b", { text: cp.qty(k.on_rent) }), el("span", { text: __("units on site right now") })),
			band);

		const delta = k.on_rent - k.on_rent_30d;
		const kpi = (route, label, value, sub, ic, tone) => el("a", { class: "cp-kpi", href: cp.href(route), "data-nav": "1" },
			el("div", { class: "cp-kpi__top" }, el("span", { text: label }), el("span", { class: "cp-kpi__icon " + (tone ? "is-" + tone : "") }, icon(ic, "cp-i--sm"))),
			el("div", { class: "cp-kpi__value", text: value }), el("div", { class: "cp-kpi__sub" }, sub));
		const kpis = el("div", { class: "cp-kpis" },
			kpi("orders?status=live", __("Active rental orders"), cp.qty(k.active_orders), __("{0} awaiting contract", [k.active_orders - k.active_contracts]), "file-check-2"),
			kpi("orders?status=live", __("Active rental contracts"), cp.qty(k.active_contracts), __("with material or deliveries open"), "file-pen-line", "teal"),
			kpi("active", __("Materials on rent"), cp.qty(k.on_rent), k.on_rent_30d || k.on_rent ? [el("span", { class: "cp-delta " + (delta >= 0 ? "is-up" : "is-down"), text: (delta >= 0 ? "+" : "") + cp.qty(delta) }), __("vs 30 days ago")] : __("No material on site"), "boxes", "teal"),
			kpi("orders?status=live", __("Pending deliveries"), cp.qty(k.pending_delivery_qty), __("units on {0} orders", [k.pending_delivery_orders]), "truck"),
			kpi("returns?status=requested", __("Pending returns"), cp.qty(k.pending_returns), __("{0} units to collect", [cp.qty(k.pending_return_qty)]), "undo-2", k.pending_returns ? "warn" : ""),
			kpi("invoices?status=unpaid", __("Outstanding invoices"), cp.qty(k.unpaid_invoices), k.overdue_invoices ? el("span", { style: { color: "var(--bad)", fontWeight: 600 }, text: __("{0} overdue", [k.overdue_invoices]) }) : __("none overdue"), "receipt", k.overdue_invoices ? "bad" : ""),
			kpi("requests?status=open", __("Pending requests"), cp.qty(k.pending_requests), __("open or in progress"), "life-buoy", "violet"),
			kpi("statement", __("Total outstanding"), cp.money(k.outstanding, d.currency), k.overdue_amount ? el("span", { style: { color: "var(--bad)", fontWeight: 600 }, text: __("{0} overdue", [cp.money(k.overdue_amount, d.currency)]) }) : __("nothing overdue"), "wallet", k.overdue_amount ? "bad" : ""));

		const op = (route, label, value, sub, ic, tone) => el("a", { class: "cp-op " + (tone ? "is-" + tone : ""), href: cp.href(route), "data-nav": "1" },
			el("span", { class: "cp-op__label" }, icon(ic, "cp-i--sm"), label), el("b", { text: cp.qty(value) }), el("span", { text: sub }));
		const ops = cp.card(__("Rental operations"), el("div", { class: "cp-ops" },
			op("active", __("Active rentals"), o.active_rentals, __("item lines on site"), "boxes"),
			op("deliveries?status=scheduled", __("Upcoming deliveries"), o.upcoming_deliveries, __("planned or requested"), "truck"),
			op("returns?status=requested", __("Scheduled pickups"), o.scheduled_pickups, __("return requests open"), "undo-2"),
			op("active?state=overdue", __("Overdue returns"), o.overdue.contracts, o.overdue.qty ? __("{0} units past return date", [cp.qty(o.overdue.qty)]) : __("none past return date"), "alarm-clock", o.overdue.contracts ? "bad" : ""),
			op("extensions", __("Pending extensions"), o.pending_extensions, o.ending_soon ? __("{0} rentals end in 14 days", [o.ending_soon]) : __("awaiting our reply"), "calendar-plus", o.pending_extensions ? "warn" : "")),
			{ flush: true });

		const months = d.movement.map((m) => m.label);
		const moveCard = cp.card(__("Deliveries and returns"), el("div", {},
			cp.legend([{ label: __("Dispatched"), color: C.blue }, { label: __("Returned"), color: C.teal }]),
			cp.barChart(months, [{ label: __("Dispatched"), color: C.blue, values: d.movement.map((m) => m.dispatched) },
				{ label: __("Returned"), color: C.teal, values: d.movement.map((m) => m.returned) }], { label: __("Units dispatched and returned per month") })),
			{ sub: __("Units per month, last 6 months") });
		const siteCard = cp.card(__("On site by location"), d.by_site.length ? cp.hbars(d.by_site.map((s) => ({ label: s.site, value: s.qty, route: "active?site=" + encodeURIComponent(s.site) })))
			: cp.empty(__("Nothing on site"), __("Material you have on hire will show here by site."), null, "map-pin"), { sub: __("Units currently on hire") });

		const ordersTable = d.recent_orders.length ? el("div", { class: "cp-has-mlist" }, el("div", { class: "cp-tablewrap" }, el("table", { class: "cp-table" },
			el("thead", {}, el("tr", {}, [__("Order"), __("Order date"), __("Project / site"), __("Rental start"), __("Expected return"), __("Order value"), __("Status"), ""].map((h, i) => el("th", { class: i === 5 ? "cp-num" : null, text: h })))),
			el("tbody", {}, d.recent_orders.map((r) => el("tr", {}, el("td", {}, cp.link(r.route, r.order_no, { class: "cp-strong" }), r.order_no !== r.name ? el("span", { class: "cp-sub", text: r.name }) : null),
				el("td", { text: cp.date(r.order_date) }), el("td", {}, r.rental_site, r.project ? el("span", { class: "cp-sub", text: r.project }) : null),
				el("td", { text: cp.date(r.start_date) }), el("td", { text: cp.date(r.end_date) }), el("td", { class: "cp-num", text: r.value ? cp.money(r.value) : "" }),
				el("td", {}, orderStatus(r)), el("td", {}, cp.link(r.route, __("View"), { "aria-label": __("View order {0}", [r.order_no]) }))))))),
			el("div", { class: "cp-mlist" }, d.recent_orders.map((r) => el("a", { class: "cp-mcard", href: cp.href(r.route), "data-nav": "1" },
				el("div", { class: "cp-mcard__top" }, el("b", { text: r.order_no }), orderStatus(r)),
				el("dl", { class: "cp-mcard__meta" }, el("div", {}, el("dt", { text: __("Site") }), el("dd", { text: r.rental_site })), el("div", {}, el("dt", { text: __("Return") }), el("dd", { text: cp.date(r.end_date) })))))))
			: cp.empty(__("No rental orders yet"), __("Your hire orders and rental contracts will be listed here."), cp.can_request() ? cp.btn(__("New hire enquiry"), null, { href: raise("Hire Enquiry"), primary: true }) : null, "file-check-2");
		const recent = cp.card(__("Recent rental orders"), ordersTable, { flush: true, action: cp.btn(__("All orders"), null, { href: cp.href("orders"), sm: true }) });

		const kindIcon = { delivery: "truck", pickup: "undo-2", expiry: "calendar-clock", overdue: "alarm-clock", inspection: "search-check", payment: "wallet", "payment-overdue": "wallet" };
		const upcoming = cp.card(__("Upcoming activity"), d.upcoming.length ? el("ul", { class: "cp-agenda" }, d.upcoming.map((u) => {
			const late = cp.daysFrom(u.date) < 0 && u.kind !== "inspection";
			return el("li", {}, el("a", { href: cp.href(u.route), "data-nav": "1" }, cp.dateChip(u.date, late),
				el("span", {}, el("span", { class: "cp-agenda__title", text: u.title }), el("span", { class: "cp-sub", text: u.amount ? cp.money(u.amount, u.currency) : u.detail || "" })),
				icon(kindIcon[u.kind] || "calendar", "cp-i--sm")));
		})) : cp.empty(__("Nothing scheduled"), __("Deliveries, pickups, return dates and payments due in the next 30 days appear here."), null, "calendar"), { flush: true });

		const notes = cp.card(__("Recent notifications"), d.notifications.length ? el("div", {}, d.notifications.map((n) => cp.noteRow(n))) : cp.empty(__("No notifications yet"), null, null, "bell"),
			{ flush: true, action: cp.btn(__("All"), null, { href: cp.href("notifications"), sm: true }) });

		const quick = cp.can_request() ? el("div", { class: "cp-pagehead__actions", style: { marginBottom: "18px" } },
			cp.btn(__("Request more material"), null, { href: raise("Additional Material Request"), primary: true, icon: "package-plus" }),
			cp.btn(__("Request a return"), null, { href: raise("Off-Hire Request"), icon: "undo-2" }),
			cp.btn(__("Extend a rental"), null, { href: raise("Extension Request"), icon: "calendar-plus" }),
			cp.btn(__("Get support"), null, { href: raise("Support Request"), icon: "life-buoy" })) : null;

		ctx.main.replaceChildren(hello, quick, kpis, el("div", { class: "cp-stack" }, ops,
			el("div", { class: "cp-grid cp-grid--main" }, moveCard, siteCard),
			el("div", { class: "cp-grid cp-grid--main" }, recent, el("div", { class: "cp-stack" }, upcoming, notes))));
	};

	// ================================================================== rental orders
	P.orders = async function (ctx) {
		ctx.setTitle(__("My Rental Orders"));
		const opts = await cp.api("request_options").catch(() => ({ sites: [] }));
		if (!ctx.isCurrent()) return;
		ctx.main.replaceChildren(cp.pageHead(__("My Rental Orders"), __("Every hire order and rental contract, with what was delivered, returned and is still on site."),
			cp.can_request() ? [cp.btn(__("New hire enquiry"), null, { href: raise("Hire Enquiry"), primary: true, icon: "plus" })] : []),
		cp.dataTable({
			method: "orders",
			search: __("Order number, site or project"),
			filters: [
				{ name: "status", label: __("All statuses"), options: [["live", __("Live orders")], ["closed", __("Closed")], ["Awaiting Contract", __("Awaiting contract")], ["Active", __("Active")], ["On Hire", __("On hire")], ["Off Hired", __("Off hired")], ["Completed", __("Completed")]] },
				{ name: "site", label: __("All sites"), options: (opts.sites || []).map((s) => [s.name, s.site_name || s.name]) },
				{ name: "from_date", type: "date", label: __("Ordered from") },
				{ name: "to_date", type: "date", label: __("Ordered to") },
			],
			columns: [
				{ label: __("Order"), sort: "", render: (r) => el("div", {}, cp.link(r.route, r.order_no, { class: "cp-strong" }), el("span", { class: "cp-sub", text: r.order_no !== r.name ? __("Contract {0}", [r.name]) : r.contract_type === "Job Type Contract" ? __("Job contract") : "" })) },
				{ label: __("Order date"), sort: "date_asc", render: (r) => cp.date(r.order_date) },
				{ label: __("Project / site"), render: (r) => el("div", {}, r.rental_site, r.project ? el("span", { class: "cp-sub", text: r.project }) : null) },
				{ label: __("Rental start"), render: (r) => cp.date(r.start_date) },
				{ label: __("Expected return"), sort: "end", render: (r) => cp.date(r.end_date) },
				{ label: __("On site"), num: 1, render: (r) => cp.qty(r.at_site_qty) },
				{ label: __("Order value"), num: 1, render: (r) => (r.value ? cp.money(r.value) : "") },
				{ label: __("Status"), render: orderStatus },
				{ label: "", render: (r) => cp.link(r.route, __("View"), { "aria-label": __("View order {0}", [r.order_no]) }) },
			],
			href: (r) => r.route,
			mobile: (r) => ({ title: r.order_no, badge: orderStatus(r), meta: [[__("Site"), r.rental_site], [__("Ordered"), cp.date(r.order_date)], [__("Return"), cp.date(r.end_date)], [__("On site"), cp.qty(r.at_site_qty)]] }),
			empty: { title: __("No rental orders yet"), text: __("Hire orders and rental contracts for your company appear here."), icon: "file-check-2" },
		}));
	};

	P.order = async function (ctx) {
		const name = ctx.params[0];
		const o = await cp.api("order", { name });
		if (!ctx.isCurrent()) return;
		ctx.setTitle(o.order_no, [[__("Rental Orders"), "orders"]]);
		const late = o.end_date && cp.daysFrom(o.end_date) < 0 && o.lines.some((l) => l.at_site > 0) && ["Active", "On Hire"].includes(o.status);
		const actions = [];
		if (o.can_request && cp.can_request()) {
			const c = "&contract=" + encodeURIComponent(o.contract);
			actions.push(cp.btn(__("Extend"), null, { href: raise("Extension Request", c), icon: "calendar-plus" }),
				cp.btn(__("Request return"), null, { href: raise("Off-Hire Request", c), icon: "undo-2" }),
				cp.btn(__("More material"), null, { href: raise("Additional Material Request", c), primary: true, icon: "package-plus" }));
		}
		o.documents.forEach((dd) => actions.push(cp.pdfBtn(dd.doctype, dd.name, dd.label)));
		const totals = o.lines.reduce((t, l) => ({ ordered: t.ordered + l.ordered, delivered: t.delivered + l.delivered, returned: t.returned + l.returned + l.lost, at_site: t.at_site + l.at_site }), { ordered: 0, delivered: 0, returned: 0, at_site: 0 });
		const info = cp.card(__("Order information"), cp.facts([
			[__("Order number"), o.order_no], [__("Rental contract"), o.contract || __("Not yet confirmed")], [__("Order date"), cp.date(o.order_date)],
			[__("Customer"), o.customer_name], [__("Site"), el("span", {}, o.site_name || o.site, o.site_location ? el("span", { class: "cp-sub", text: o.site_location }) : null)],
			[__("Project"), o.project], [__("Your reference"), o.customer_reference],
			[__("Site contact"), o.site_contact ? el("span", {}, o.site_contact, o.site_phone ? el("span", { class: "cp-sub" }, el("a", { href: "tel:" + o.site_phone, text: o.site_phone })) : null) : null],
			[__("Delivery address"), o.address],
			[__("Rental period"), [cp.date(o.start_date), cp.date(o.end_date)].filter(Boolean).join(" to ")],
			[__("Billing"), o.billing_cycle ? __(o.billing_cycle) + (o.last_billed_upto ? ", " + __("billed to {0}", [cp.date(o.last_billed_upto)]) : "") : null],
			[__("Order value"), o.value ? cp.money(o.value, o.currency) : null],
		]));
		const progress = el("div", { style: { marginTop: "14px" } }, cp.progress([
			{ label: __("Returned"), value: totals.returned, color: C.slate }, { label: __("On site"), value: totals.at_site, color: C.teal },
			{ label: __("To deliver"), value: Math.max(totals.ordered - totals.delivered, 0), color: "#cfd7e2" }], Math.max(totals.ordered, totals.delivered)),
			cp.legend([{ label: __("Returned {0}", [cp.qty(totals.returned)]), color: C.slate }, { label: __("On site {0}", [cp.qty(totals.at_site)]), color: C.teal },
				{ label: __("To deliver {0}", [cp.qty(Math.max(totals.ordered - totals.delivered, 0))]), color: "#cfd7e2" }]));
		const lines = cp.card(__("Material"), el("div", {}, el("div", { class: "cp-tablewrap" }, el("table", { class: "cp-table" },
			el("thead", {}, el("tr", {}, [__("Item"), __("Ordered"), __("Delivered"), __("Returned"), __("On site"), __("To deliver"), __("Rate"), __("Amount")].map((h, i) => el("th", { class: i ? "cp-num" : null, text: h })))),
			el("tbody", {}, o.lines.map((l) => el("tr", {}, el("td", {}, el("b", { text: l.item_name }), el("span", { class: "cp-sub", text: [l.item_code, l.description].filter(Boolean).join(", ") })),
				el("td", { class: "cp-num", text: cp.qty(l.ordered) + " " + (l.uom || "") }), el("td", { class: "cp-num", text: cp.qty(l.delivered) }),
				el("td", { class: "cp-num", text: cp.qty(l.returned) + (l.lost ? " + " + cp.qty(l.lost) + " " + __("lost") : "") }),
				el("td", { class: "cp-num cp-strong", text: cp.qty(l.at_site) }), el("td", { class: "cp-num", text: cp.qty(l.to_deliver) }),
				el("td", { class: "cp-num" }, l.rate != null && l.rate !== "" ? [cp.money(l.rate, o.currency), el("span", { class: "cp-sub", text: cp.per(l.rate_basis) })] : ""),
				el("td", { class: "cp-num", text: l.amount != null && l.amount !== "" ? cp.money(l.amount, o.currency) : "" })))))),
			progress), { sub: o.contract_type === "Job Type Contract" ? __("Job type contract: material is supplied for the contracted jobs") : null });
		const jobs = o.jobs.length ? cp.card(__("Contracted jobs"), el("div", { class: "cp-tablewrap" }, el("table", { class: "cp-table" },
			el("thead", {}, el("tr", {}, [__("Job"), __("Location"), __("Qty"), __("Included days"), __("Rate"), __("Amount"), __("Reported")].map((h, i) => el("th", { class: i > 1 ? "cp-num" : null, text: h })))),
			el("tbody", {}, o.jobs.map((j) => el("tr", {}, el("td", { text: j.job_type }), el("td", { text: j.location || "" }), el("td", { class: "cp-num", text: cp.qty(j.qty) }),
				el("td", { class: "cp-num", text: j.included_days || "" }), el("td", { class: "cp-num", text: cp.money(j.rate, o.currency) }), el("td", { class: "cp-num", text: cp.money(j.amount, o.currency) }),
				el("td", { class: "cp-num", text: cp.qty(j.reported) }))))))) : null;
		const list = (title, rows, cols, emptyText) => cp.card(title, rows.length ? el("div", { class: "cp-tablewrap" }, el("table", { class: "cp-table" },
			el("thead", {}, el("tr", {}, cols.map((c) => el("th", { class: c.num ? "cp-num" : null, text: c.label })))),
			el("tbody", {}, rows.map((r) => el("tr", { class: "is-link", onclick: (e) => !e.target.closest("a") && cp.go(r.route) }, cols.map((c) => el("td", { class: c.num ? "cp-num" : null }, c.render(r)))))))) : el("p", { class: "cp-sub", style: { padding: "16px 18px", margin: 0 }, text: emptyText }), { flush: true });
		const movements = el("div", { class: "cp-grid cp-grid--2" },
			list(__("Deliveries"), o.deliveries, [{ label: __("Delivery"), render: (r) => cp.link(r.route, r.name) }, { label: __("Date"), render: (r) => cp.date(r.posting_date) }, { label: __("Units"), num: 1, render: (r) => cp.qty(r.total_qty) }, { label: __("Status"), render: (r) => cp.badge(r.status) }], __("Nothing delivered yet.")),
			list(__("Returns"), o.returns, [{ label: __("Return"), render: (r) => cp.link(r.route, r.name) }, { label: __("Date"), render: (r) => cp.date(r.date) }, { label: __("Units"), num: 1, render: (r) => cp.qty(r.qty) }, { label: __("Status"), render: (r) => cp.badge(r.status) }], __("Nothing returned yet.")));
		const money = el("div", { class: "cp-grid cp-grid--2" },
			list(__("Invoices"), o.invoices, [{ label: __("Invoice"), render: (r) => cp.link(r.route, r.name) }, { label: __("Date"), render: (r) => cp.date(r.posting_date) }, { label: __("Total"), num: 1, render: (r) => cp.money(r.grand_total, r.currency) }, { label: __("Status"), render: (r) => cp.badge(r.payment_status) }], __("No invoices yet.")),
			list(__("Requests"), o.requests, [{ label: __("Request"), render: (r) => cp.link(r.route, r.name) }, { label: __("Type"), render: (r) => r.label }, { label: __("Status"), render: (r) => cp.badge(r.status) }], __("No requests on this order.")));
		const timeline = cp.card(__("Timeline"), cp.timeline(o.timeline));
		const ext = o.extensions.length ? cp.card(__("Extensions"), el("ul", { style: { margin: 0, paddingLeft: "18px" } }, o.extensions.map((x) => el("li", { text: __("{0}: return date moved from {1} to {2}", [cp.date(x.date), cp.date(x.previous), cp.date(x.new)]) })))) : null;
		ctx.main.replaceChildren(
			cp.pageHead(o.order_no, null, actions),
			el("div", { style: { display: "flex", gap: "8px", margin: "-10px 0 18px", flexWrap: "wrap" } }, cp.badge(o.status), late ? cp.badge("Overdue") : null,
				o.contract_type === "Job Type Contract" ? cp.badge(__("Job type contract"), "violet") : null),
			late ? el("div", { class: "cp-callout is-bad", style: { marginBottom: "18px" } }, icon("alarm-clock"), el("span", { text: __("The return date {0} has passed and material is still on site. Request a return or an extension.", [cp.date(o.end_date)]) })) : null,
			el("div", { class: "cp-grid cp-grid--main" }, el("div", { class: "cp-stack" }, info, lines, jobs, movements, money), el("div", { class: "cp-stack" }, timeline, ext)));
	};

	// ================================================================== active rentals
	P.active = async function (ctx) {
		ctx.setTitle(__("Active Rentals"));
		const summary = el("div", { class: "cp-kpis", style: { gridTemplateColumns: "repeat(4, minmax(0, 1fr))" } });
		let sitesLoaded = false;
		const table = cp.dataTable({
			method: "active_rentals",
			page_length: 25,
			search: __("Item, site, contract or order"),
			filters: [
				{ name: "state", label: __("All rentals"), options: [["expiring", __("Ending within 14 days")], ["overdue", __("Overdue")], ["partial", __("Partially returned")]] },
				{ name: "site", label: __("All sites"), options: [] },
			],
			onData: (d) => {
				const s = d.summary || {};
				summary.replaceChildren(
					kpiMini(__("Item lines on site"), cp.qty(s.line_count), "boxes", "teal"), kpiMini(__("Units on rent"), cp.qty(s.qty), "package", "teal"),
					kpiMini(__("Ending within 14 days"), cp.qty(s.expiring), "calendar-clock", s.expiring ? "warn" : ""), kpiMini(__("Overdue"), cp.qty(s.overdue), "alarm-clock", s.overdue ? "bad" : ""));
				if (!sitesLoaded && d.sites) {
					sitesLoaded = true;
					const sel = table.querySelectorAll(".cp-toolbar select")[1];
					const cur = new URLSearchParams(location.search).get("site") || "";
					d.sites.forEach((x) => sel.appendChild(el("option", { value: x.name, text: x.site_name || x.name, selected: x.name === cur })));
				}
			},
			columns: [
				{ label: __("Rental"), render: (r) => el("div", {}, cp.link(r.route, r.order_no || r.rental_contract, { class: "cp-strong" }), el("span", { class: "cp-sub", text: r.order_no ? r.rental_contract : "" })) },
				{ label: __("Site"), render: (r) => r.rental_site },
				{ label: __("Material"), render: (r) => el("div", {}, r.item_name, el("span", { class: "cp-sub", text: r.item_code })) },
				{ label: __("On rent"), num: 1, render: (r) => el("div", {}, el("b", { text: cp.qty(r.qty) + " " + (r.uom || "") }), r.partial ? el("span", { class: "cp-sub", text: __("{0} returned", [cp.qty(r.returned)]) }) : null) },
				{ label: __("Start"), render: (r) => cp.date(r.start_date) },
				{ label: __("Expected return"), render: (r) => el("div", {}, cp.date(r.end_date), el("span", { class: "cp-sub", text: r.days_left == null ? "" : r.days_left < 0 ? __("{0} days overdue", [-r.days_left]) : __("{0} days left", [r.days_left]) })) },
				{ label: __("On hire for"), num: 1, render: (r) => __("{0} days", [r.days_on_hire]) },
				{ label: __("Value per period"), num: 1, render: (r) => (r.rate ? el("div", {}, cp.money(r.period_value), el("span", { class: "cp-sub", text: cp.per(r.rate_basis) })) : "") },
				{ label: __("Status"), render: rentalBadge },
				{ label: "", render: (r) => cp.can_request() ? el("div", { style: { display: "flex", gap: "6px" } },
					cp.btn(__("Extend"), null, { href: raise("Extension Request", "&contract=" + encodeURIComponent(r.rental_contract)), sm: true }),
					cp.btn(__("Return"), null, { href: raise("Off-Hire Request", "&contract=" + encodeURIComponent(r.rental_contract) + "&item=" + encodeURIComponent(r.item_code)), sm: true })) : "" },
			],
			href: (r) => r.route,
			mobile: (r) => ({ title: r.item_name, badge: rentalBadge(r), meta: [[__("Site"), r.rental_site], [__("On rent"), cp.qty(r.qty)], [__("Return by"), cp.date(r.end_date)], [__("Order"), r.order_no || r.rental_contract]] }),
			empty: { title: __("No material on hire"), text: __("Material delivered to your sites shows here until it is returned."), icon: "boxes" },
		});
		ctx.main.replaceChildren(cp.pageHead(__("Active Rentals"), __("Material on your sites now, with its return date. Ask for an extension or a return straight from a line.")), summary, table);
	};
	function rentalBadge(r) {
		if (r.state === "overdue") return cp.badge("Overdue");
		if (r.state === "expiring") return cp.badge("Ending soon");
		if (r.partial) return cp.badge("Partially Returned");
		return cp.badge(__("On hire"), "teal");
	}
	function kpiMini(label, value, ic, tone) {
		return el("div", { class: "cp-kpi" }, el("div", { class: "cp-kpi__top" }, el("span", { text: label }), el("span", { class: "cp-kpi__icon " + (tone ? "is-" + tone : "") }, icon(ic, "cp-i--sm"))), el("div", { class: "cp-kpi__value", text: value }));
	}
	cp.kpiMini = kpiMini;

	// ================================================================== deliveries
	P.deliveries = async function (ctx) {
		ctx.setTitle(__("Rental Deliveries"));
		ctx.main.replaceChildren(cp.pageHead(__("Rental Deliveries"), __("Every delivery to your sites, and deliveries we have planned."),
			cp.can_request() ? [cp.btn(__("Reschedule a delivery"), null, { href: raise("Delivery Reschedule"), icon: "calendar-clock" })] : []),
		cp.dataTable({
			method: "deliveries",
			search: __("Delivery, order, site or vehicle"),
			filters: [{ name: "status", label: __("All deliveries"), options: [["delivered", __("Delivered")], ["scheduled", __("Scheduled")]] },
				{ name: "from_date", type: "date", label: __("From") }, { name: "to_date", type: "date", label: __("To") }],
			columns: [
				{ label: __("Delivery"), render: (r) => cp.link(r.route, r.name, { class: "cp-strong" }) },
				{ label: __("Date"), render: (r) => cp.date(r.posting_date) },
				{ label: __("Order"), render: (r) => cp.link("orders/" + r.rental_contract, r.order_no || r.rental_contract) },
				{ label: __("Site"), render: (r) => el("div", {}, r.rental_site, r.project ? el("span", { class: "cp-sub", text: r.project }) : null) },
				{ label: __("Vehicle"), render: (r) => el("div", {}, r.vehicle_no || "", r.driver_name ? el("span", { class: "cp-sub", text: r.driver_name }) : null) },
				{ label: __("Units"), num: 1, render: (r) => cp.qty(r.total_qty) },
				{ label: __("Status"), render: (r) => cp.badge(r.status) },
				{ label: "", render: (r) => (r.docstatus === 1 ? cp.pdfBtn("Hire Delivery Order", r.name, __("Delivery note")) : "") },
			],
			href: (r) => r.route,
			mobile: (r) => ({ title: r.name, badge: cp.badge(r.status), meta: [[__("Date"), cp.date(r.posting_date)], [__("Site"), r.rental_site], [__("Units"), cp.qty(r.total_qty)], [__("Vehicle"), r.vehicle_no]] }),
			empty: { title: __("No deliveries yet"), text: __("Each delivery to your sites is listed here with its delivery note."), icon: "truck" },
		}));
	};

	P.delivery = async function (ctx) {
		const d = await cp.api("delivery", { name: ctx.params[0] });
		if (!ctx.isCurrent()) return;
		ctx.setTitle(d.name, [[__("Deliveries"), "deliveries"]]);
		const delivered = d.status === __("Delivered");
		const steps = [{ title: __("Delivery planned"), date: d.posting_date, icon: "calendar" }];
		if (delivered) steps.push({ title: __("Dispatched and delivered to {0}", [d.rental_site]), date: d.posting_date, icon: "truck", detail: d.vehicle_no ? __("Vehicle {0}", [d.vehicle_no]) : null });
		ctx.main.replaceChildren(cp.pageHead(d.name, null, delivered ? [cp.pdfBtn("Hire Delivery Order", d.name, __("Delivery note"))] : []),
			el("div", { style: { margin: "-10px 0 18px" } }, cp.badge(d.status)),
			el("div", { class: "cp-grid cp-grid--main" }, el("div", { class: "cp-stack" },
				cp.card(__("Delivery"), cp.facts([[__("Delivery reference"), d.name], [__("Date"), cp.date(d.posting_date)], [__("Rental order"), cp.link("orders/" + d.rental_contract, d.order_no)],
					[__("Site"), d.rental_site], [__("Project"), d.project], [__("Vehicle"), d.vehicle_no], [__("Driver"), d.driver_name ? el("span", {}, d.driver_name, d.driver_phone ? el("span", { class: "cp-sub" }, el("a", { href: "tel:" + d.driver_phone, text: d.driver_phone })) : null) : null],
					[__("Transporter"), d.transporter], [__("Dispatch reference"), d.dispatch_reference], [__("Units"), cp.qty(d.total_qty)]])),
				cp.card(__("Material"), el("div", { class: "cp-tablewrap" }, el("table", { class: "cp-table" },
					el("thead", {}, el("tr", {}, [__("Item"), __("Delivered here"), __("Ordered"), __("Still to deliver on the order")].map((h, i) => el("th", { class: i ? "cp-num" : null, text: h })))),
					el("tbody", {}, d.items.map((i) => el("tr", {}, el("td", {}, el("b", { text: i.item_name }), el("span", { class: "cp-sub", text: i.item_code })),
						el("td", { class: "cp-num cp-strong", text: cp.qty(i.qty) + " " + (i.uom || "") }), el("td", { class: "cp-num", text: cp.qty(i.ordered) }), el("td", { class: "cp-num", text: cp.qty(i.pending) })))))), { flush: true })),
			cp.card(__("Status"), cp.timeline(steps))));
	};

	// ================================================================== returns
	P.returns = async function (ctx) {
		ctx.setTitle(__("Material Returns"));
		ctx.main.replaceChildren(cp.pageHead(__("Material Returns"), __("Material collected from your sites, and returns you have asked for."),
			cp.can_request() ? [cp.btn(__("Request a return"), null, { href: raise("Off-Hire Request"), primary: true, icon: "undo-2" }), cp.btn(__("Book a pickup"), null, { href: raise("Pickup Request"), icon: "truck" })] : []),
		cp.dataTable({
			method: "returns",
			search: __("Return, order or site"),
			filters: [{ name: "status", label: __("All returns"), options: [["returned", __("Returned")], ["requested", __("Requested, not yet collected")]] },
				{ name: "from_date", type: "date", label: __("From") }, { name: "to_date", type: "date", label: __("To") }],
			columns: [
				{ label: __("Return"), render: (r) => el("div", {}, cp.link(r.route, r.name, { class: "cp-strong" }), el("span", { class: "cp-sub", text: r.kind })) },
				{ label: __("Date"), render: (r) => el("div", {}, cp.date(r.date), el("span", { class: "cp-sub", text: r.pending ? __("requested pickup") : __("returned") })) },
				{ label: __("Order"), render: (r) => (r.rental_contract ? cp.link("orders/" + r.rental_contract, r.rental_contract) : "") },
				{ label: __("Site"), render: (r) => r.rental_site || "" },
				{ label: __("Units"), num: 1, render: (r) => el("div", {}, cp.qty(r.qty), r.lost_qty ? el("span", { class: "cp-sub", text: __("{0} lost", [cp.qty(r.lost_qty)]) }) : null) },
				{ label: __("Status"), render: (r) => cp.badge(r.status) },
				{ label: "", render: (r) => (r.pending ? "" : cp.pdfBtn("Hire Off-Hire Note", r.name, __("Return note"))) },
			],
			href: (r) => r.route,
			mobile: (r) => ({ title: r.name, badge: cp.badge(r.status), meta: [[__("Date"), cp.date(r.date)], [__("Site"), r.rental_site], [__("Units"), cp.qty(r.qty)]] }),
			empty: { title: __("No returns yet"), text: __("When material comes back from site, the return note is listed here."), icon: "undo-2" },
		}));
	};

	P.return_note = async function (ctx) {
		const r = await cp.api("return_note", { name: ctx.params[0] });
		if (!ctx.isCurrent()) return;
		ctx.setTitle(r.name, [[__("Returns"), "returns"]]);
		const steps = [];
		if (r.request) steps.push({ title: __("Return requested"), detail: r.request, route: "requests/" + r.request, icon: "undo-2" });
		steps.push({ title: __("Off hire from"), date: r.off_hire_date, icon: "calendar-check", detail: r.last_billable_date ? __("billed up to {0}", [cp.date(r.last_billable_date)]) : null });
		steps.push({ title: __("Material collected"), date: r.return_date, icon: "package-open", detail: __("{0} units", [cp.qty(r.total_returned_qty)]) });
		if (r.inspection) steps.push({ title: __("Inspection completed"), date: r.inspection.inspection_date, icon: "search-check",
			detail: __("{0} good, {1} repairable, {2} beyond repair", [cp.qty(r.inspection.total_good_qty), cp.qty(r.inspection.total_repairable_qty), cp.qty(r.inspection.total_damaged_qty)]) });
		else if (r.inspection_status === "Pending") steps.push({ title: __("Inspection in progress"), icon: "search-check" });
		ctx.main.replaceChildren(cp.pageHead(r.name, null, [cp.pdfBtn("Hire Off-Hire Note", r.name, __("Return note"))]),
			el("div", { style: { margin: "-10px 0 18px", display: "flex", gap: "8px" } }, cp.badge(r.status), cp.badge(__("{0} return", [__(r.off_hire_type)]), "plain")),
			el("div", { class: "cp-grid cp-grid--main" }, el("div", { class: "cp-stack" },
				cp.card(__("Return"), cp.facts([[__("Return reference"), r.name], [__("Rental order"), cp.link("orders/" + r.rental_contract, r.rental_contract)], [__("Site"), r.rental_site],
					[__("Off hire date"), cp.date(r.off_hire_date)], [__("Pickup date"), cp.date(r.return_date)], [__("Vehicle"), r.vehicle_no], [__("Driver"), r.driver_name],
					[__("Units returned"), cp.qty(r.total_returned_qty)], [__("Units lost"), r.total_lost_qty ? cp.qty(r.total_lost_qty) : null]])),
				cp.card(__("Material"), el("div", { class: "cp-tablewrap" }, el("table", { class: "cp-table" },
					el("thead", {}, el("tr", {}, [__("Item"), __("On site before"), __("Returned"), __("Lost"), __("Still on site")].map((h, i) => el("th", { class: i ? "cp-num" : null, text: h })))),
					el("tbody", {}, r.items.map((i) => el("tr", {}, el("td", {}, el("b", { text: i.item_name }), el("span", { class: "cp-sub", text: i.item_code })),
						el("td", { class: "cp-num", text: cp.qty(i.at_site_before) }), el("td", { class: "cp-num cp-strong", text: cp.qty(i.returned) }),
						el("td", { class: "cp-num", text: i.lost ? cp.qty(i.lost) : "" }), el("td", { class: "cp-num", text: cp.qty(i.still_at_site) })))))), { flush: true }),
				// extra material handed over with this return (more than was on site), and what has become of it
				(r.excess || []).length ? cp.card(__("Extra material received"), el("div", { class: "cp-tablewrap" }, el("table", { class: "cp-table" },
					el("thead", {}, el("tr", {}, [__("Item"), __("Received"), __("Held for you"), __("Returned to you"), __("Set against material owed"), __("Left with us")]
						.map((h, n) => el("th", { class: n ? "cp-num" : null, text: h })))),
					el("tbody", {}, r.excess.map((x) => el("tr", {}, el("td", {}, el("b", { text: x.item_name }), el("span", { class: "cp-sub", text: x.item_code })),
						el("td", { class: "cp-num cp-strong", text: cp.qty(x.received) }), el("td", { class: "cp-num", text: x.held ? cp.qty(x.held) : "" }),
						el("td", { class: "cp-num", text: x.returned ? cp.qty(x.returned) : "" }), el("td", { class: "cp-num", text: x.settled ? cp.qty(x.settled) : "" }),
						el("td", { class: "cp-num", text: x.abandoned ? cp.qty(x.abandoned) : "" })))))), { flush: true }) : null),
			cp.card(__("Progress"), cp.timeline(steps))));
	};

	// ================================================================== request lists by group
	function requestList(ctx, title, sub, group, newTypes) {
		ctx.setTitle(title);
		ctx.main.replaceChildren(cp.pageHead(title, sub, cp.can_request() ? newTypes.map(([t, label], i) => cp.btn(label, null, { href: raise(t), primary: i === 0, icon: i === 0 ? "plus" : null })) : []),
			cp.requestTable({ group }));
	}
	P.extensions = (ctx) => requestList(ctx, __("Extension Requests"), __("Requests to keep material beyond the agreed return date."), "extensions", [["Extension Request", __("Request an extension")]]);
	P.additional = (ctx) => requestList(ctx, __("Additional Material"), __("Requests for more material on a current order, and enquiries for new sites."), "additional",
		[["Additional Material Request", __("Request more material")], ["Hire Enquiry", __("New hire enquiry")]]);
	P.complaints = (ctx) => requestList(ctx, __("Complaints"), __("Complaints and reports of damaged or missing material."), "complaints",
		[["Complaint", __("Raise a complaint")], ["Damage Report", __("Report damage")], ["Missing Material Report", __("Report missing material")]]);
	P.support = (ctx) => requestList(ctx, __("Support Tickets"), __("Questions and support requests for the rental team."), "support", [["Support Request", __("New support ticket")]]);

	// ================================================================== history and documents
	P.history = async function (ctx) {
		ctx.setTitle(__("Rental History"));
		ctx.main.replaceChildren(cp.pageHead(__("Rental History"), __("Every delivery and return, newest first. Closed orders are under My Rental Orders.")),
			cp.dataTable({
				method: "history",
				search: __("Delivery, return, order or site"),
				filters: [{ name: "from_date", type: "date", label: __("From") }, { name: "to_date", type: "date", label: __("To") }],
				columns: [
					{ label: __("Date"), render: (r) => cp.date(r.date) },
					{ label: __("Movement"), render: (r) => el("div", { style: { display: "flex", gap: "8px", alignItems: "center" } }, icon(r.kind === "delivery" ? "truck" : "undo-2", "cp-i--sm"), cp.link(r.route, r.name), cp.badge(r.kind === "delivery" ? __("Delivery") : __("Return"), r.kind === "delivery" ? "blue" : "teal")) },
					{ label: __("Order"), render: (r) => cp.link("orders/" + r.rental_contract, r.rental_contract) },
					{ label: __("Site"), render: (r) => r.rental_site },
					{ label: __("Units"), num: 1, render: (r) => (r.kind === "delivery" ? "+" : "−") + cp.qty(r.qty) + (r.lost_qty ? " (" + __("{0} lost", [cp.qty(r.lost_qty)]) + ")" : "") },
				],
				href: (r) => r.route,
				mobile: (r) => ({ title: r.name, badge: cp.badge(r.kind === "delivery" ? __("Delivery") : __("Return"), r.kind === "delivery" ? "blue" : "teal"), meta: [[__("Date"), cp.date(r.date)], [__("Site"), r.rental_site], [__("Units"), cp.qty(r.qty)]] }),
				empty: { title: __("No history yet"), text: __("Deliveries and returns appear here as they happen."), icon: "history" },
			}));
	};

	P.documents = async function (ctx) {
		const tab = ctx.params[0] || "rental";
		const titles = { rental: __("Rental Documents"), delivery: __("Delivery Documents"), invoices: __("Invoices & Receipts") };
		ctx.setTitle(titles[tab]);
		ctx.main.replaceChildren(cp.pageHead(titles[tab], __("Download any of your documents as PDF.")),
			el("div", { style: { marginBottom: "14px" } }, cp.tabs([["rental", titles.rental], ["delivery", titles.delivery], ["invoices", titles.invoices]], tab, (v) => cp.go("documents/" + v), __("Document group"))),
			cp.dataTable({
				method: "documents",
				args: { tab },
				page_length: 25,
				search: __("Document number or reference"),
				columns: [
					{ label: __("Document"), render: (r) => el("div", {}, r.route ? cp.link(r.route, r.name, { class: "cp-strong" }) : el("b", { text: r.name }), el("span", { class: "cp-sub", text: r.label })) },
					{ label: __("Date"), render: (r) => cp.date(r.date) },
					{ label: __("Reference"), render: (r) => r.reference || "" },
					{ label: __("Amount"), num: 1, render: (r) => (r.amount ? cp.money(r.amount) : "") },
					{ label: __("Status"), render: (r) => (r.status ? cp.badge(r.status) : "") },
					{ label: "", render: (r) => cp.pdfBtn(r.doctype, r.name) },
				],
				mobile: (r) => ({ title: [r.name, " ", cp.pdfBtn(r.doctype, r.name)], badge: el("span", { class: "cp-sub", text: r.label }), meta: [[__("Date"), cp.date(r.date)], [__("Reference"), r.reference], [__("Amount"), r.amount ? cp.money(r.amount) : ""]] }),
				empty: { title: __("No documents yet"), text: __("Your documents appear here once they are issued."), icon: "folder-open" },
			}));
	};

	// ================================================================== staff preview chooser
	P.preview = async function (ctx) {
		ctx.setTitle(__("Preview as customer"));
		const input = el("input", { type: "search", placeholder: __("Customer name"), "aria-label": __("Customer name") });
		const list = el("div", {});
		const load = async () => {
			const rows = await cp.api("preview_customers", { search: input.value.trim(), customer: null });
			list.replaceChildren(...(rows.length ? rows.map((r) => el("a", { class: "cp-mcard", href: "/rental?customer=" + encodeURIComponent(r.name) }, el("b", { text: r.customer_name }), el("span", { class: "cp-sub", text: r.name }))) : [cp.empty(__("No customers found"))]));
		};
		let t;
		input.addEventListener("input", () => { clearTimeout(t); t = setTimeout(load, 250); });
		ctx.main.replaceChildren(cp.pageHead(__("Preview as customer"), __("See the portal exactly as a customer sees it. Previews are read-only.")),
			cp.card(null, el("div", {}, el("label", { class: "cp-field-search", style: { maxWidth: "none", marginBottom: "10px" } }, icon("search", "cp-i--sm"), input), list)));
		await load();
	};
})();
