/* thinkNXG Rental customer Command Center: application shell, navigation, router, search, notifications. */
(function () {
	"use strict";
	const { el, icon } = cp;
	const B = cp.boot;
	const P = cp.pages;

	// ------------------------------------------------------------------ state: which customer account is shown
	const KEY = "cp.customer";
	function initialCustomer() {
		const fromUrl = new URLSearchParams(location.search).get("customer");
		if (B.staff) return fromUrl || (B.customers[0] && B.customers[0].name) || null;
		const names = B.customers.map((c) => c.name);
		let saved = null;
		try {
			saved = localStorage.getItem(KEY);
		} catch (e) {
			/* storage blocked */
		}
		return names.includes(saved) ? saved : null; // null = every account the login can see
	}
	cp.state = { customer: initialCustomer() };
	cp.customerName = function () {
		const c = B.customers.find((x) => x.name === cp.state.customer);
		if (c) return c.customer_name;
		return B.customers.length === 1 ? B.customers[0].customer_name : __("All companies");
	};
	cp.features = B.features || {};
	cp.can_request = () => !!(B.settings && B.settings.allow_requests) && !B.staff;

	// ------------------------------------------------------------------ navigation
	const NAV = [
		[__("Overview"), [["", __("Dashboard"), "layout-dashboard"]]],
		[__("Rental operations"), [
			["orders", __("My Rental Orders"), "file-check-2"],
			["active", __("Active Rentals"), "boxes"],
			["deliveries", __("Rental Deliveries"), "truck"],
			["returns", __("Material Returns"), "undo-2"],
			["extensions", __("Extension Requests"), "calendar-plus"],
			["additional", __("Additional Material"), "package-plus"],
		]],
		[__("Commercial"), [
			["enquiries", __("Enquiries"), "inbox"],
			["quotations", __("Quotations"), "file-text", () => cp.features.quotations],
			["sales-orders", __("Sales Orders"), "shopping-cart", () => cp.features.sales_orders],
			["invoices", __("Invoices"), "receipt"],
			["payments", __("Payments"), "wallet"],
			["statement", __("Account Statement"), "scroll-text"],
		]],
		[__("Customer services"), [
			["requests", __("Service Requests"), "life-buoy", null, "open_requests"],
			["complaints", __("Complaints"), "message-square-warning"],
			["support", __("Support Tickets"), "ticket"],
			["communications", __("Communication History"), "messages-square"],
		]],
		[__("Resources"), [
			["documents/rental", __("Rental Documents"), "folder-open"],
			["documents/delivery", __("Delivery Documents"), "package-open"],
			["documents/invoices", __("Invoices & Receipts"), "receipt-text"],
			["history", __("Rental History"), "history"],
		]],
		[__("Account"), [
			["profile", __("Company Profile"), "building-2"],
			["contacts", __("Contacts"), "users"],
			["notifications", __("Notifications"), "bell", null, "unread"],
			["settings", __("Settings"), "settings"],
		]],
	];
	const counters = { unread: B.unread || 0, open_requests: 0 };

	function activeKey(path) {
		let best = "";
		for (const [, items] of NAV) for (const [r] of items) if (r && (path === r || path.startsWith(r + "/")) && r.length > best.length) best = r;
		const alias = { "requests/new": "requests" };
		return alias[path] || best;
	}

	let shell, nav, main, crumbs, bell, previewBar;
	function buildShell() {
		const app = document.getElementById("cp-app");
		let collapsed = false;
		try {
			collapsed = localStorage.getItem("cp.collapsed") === "1";
		} catch (e) {
			/* ignore */
		}
		nav = el("nav", { class: "cp-nav", "aria-label": __("Main") });
		const side = el("aside", { class: "cp-side" },
			el("a", { class: "cp-brand", href: cp.href(""), "data-nav": "1", "aria-label": __("thinkNXG Rental dashboard") },
				el("span", { class: "cp-brand__mark" }, icon("boxes")),
				el("span", { class: "cp-brand__text" }, el("span", { class: "cp-brand__name" }, "thinkNXG ", el("span", { text: "RENTAL" })),
					el("span", { class: "cp-brand__tag", text: __("Intelligent Rental Operations Platform") }))),
			nav,
			el("div", { class: "cp-side__foot" },
				el("button", { type: "button", class: "cp-side__collapse", "aria-label": __("Collapse menu"), onclick: () => {
					shell.classList.toggle("is-collapsed");
					try {
						localStorage.setItem("cp.collapsed", shell.classList.contains("is-collapsed") ? "1" : "0");
					} catch (e) {
						/* ignore */
					}
				} }, icon("panel-left-close"), el("span", { text: __("Collapse menu") }))));
		crumbs = el("div", { class: "cp-crumbs", "aria-label": __("Breadcrumb") });
		bell = el("button", { type: "button", class: "cp-iconbtn", "aria-label": __("Notifications"), "aria-haspopup": "true", onclick: () => openNotifications(bell) }, icon("bell"));
		const companySel = B.customers.length > 1 && !B.staff ? el("select", { class: "cp-company", "aria-label": __("Company"), onchange: (e) => {
			cp.state.customer = e.target.value || null;
			try {
				localStorage.setItem(KEY, cp.state.customer || "");
			} catch (err) {
				/* ignore */
			}
			route();
		} }, el("option", { value: "", text: __("All companies") }), B.customers.map((c) => el("option", { value: c.name, text: c.customer_name, selected: c.name === cp.state.customer }))) : null;
		const userBtn = el("button", { type: "button", class: "cp-user", "aria-haspopup": "true", "aria-label": __("Account menu"), onclick: () => userMenu(userBtn) },
			avatar(), el("span", { class: "cp-user__name", text: B.user.first_name }), icon("chevron-down", "cp-i--sm"));
		const head = el("header", { class: "cp-head" },
			el("button", { type: "button", class: "cp-iconbtn cp-head__menu", "aria-label": __("Open menu"), onclick: () => shell.classList.add("is-drawer") }, icon("menu")),
			crumbs,
			el("button", { type: "button", class: "cp-searchbtn", onclick: openSearch, "aria-label": __("Search") }, icon("search", "cp-i--sm"), el("span", { text: __("Search orders, invoices…") }), el("kbd", { text: navigator.platform.includes("Mac") ? "⌘K" : "Ctrl K" })),
			companySel,
			el("button", { type: "button", class: "cp-iconbtn", "aria-label": __("Help and support"), "aria-haspopup": "true", onclick: (e) => helpMenu(e.currentTarget) }, icon("circle-help")),
			bell, userBtn);
		previewBar = B.staff ? el("div", { class: "cp-preview" }, icon("eye"), el("span", { text: cp.state.customer ? __("Staff preview of {0}. Read-only: requests cannot be raised.", [cp.customerName()]) : __("Staff preview: choose a customer.") }),
			cp.btn(__("Change customer"), null, { href: cp.href("preview"), sm: true })) : null;
		main = el("main", { id: "cp-main", class: "cp-main", tabindex: "-1" });
		shell = el("div", { class: "cp-shell" + (collapsed ? " is-collapsed" : "") }, side, el("div", { class: "cp-scrim", onclick: () => shell.classList.remove("is-drawer") }),
			el("div", { class: "cp-body" }, head, previewBar, main));
		app.replaceChildren(shell);
		app.removeAttribute("data-loading");
		renderNav();
		updateBell();
	}

	function avatar() {
		const initials = (B.user.full_name || "?").split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
		return el("span", { class: "cp-avatar" }, B.user.image ? el("img", { src: B.user.image, alt: "" }) : initials);
	}

	function renderNav(path) {
		const current = activeKey(path == null ? currentPath() : path);
		nav.replaceChildren(...NAV.map(([title, items]) => {
			const shown = items.filter((i) => !i[3] || i[3]());
			if (!shown.length) return null;
			return el("div", { class: "cp-nav__group" }, el("div", { class: "cp-nav__title", text: title }),
				shown.map(([r, label, ic, , counter]) => el("a", { href: cp.href(r), "data-nav": "1", class: r === current ? "is-active" : null, "aria-current": r === current ? "page" : null, title: label },
					icon(ic), el("span", { text: label }), counter && counters[counter] ? el("b", { class: "cp-nav__badge", text: counters[counter] > 99 ? "99+" : counters[counter] }) : null)));
		}).filter(Boolean));
	}
	cp.setCounter = function (k, v) {
		counters[k] = v;
		renderNav();
		if (k === "unread") updateBell();
	};
	function updateBell() {
		const dot = bell.querySelector(".cp-iconbtn__dot");
		if (dot) dot.remove();
		if (counters.unread) bell.appendChild(el("span", { class: "cp-iconbtn__dot", text: counters.unread > 99 ? "99+" : counters.unread }));
		bell.setAttribute("aria-label", counters.unread ? __("Notifications, {0} unread", [counters.unread]) : __("Notifications"));
	}

	// ------------------------------------------------------------------ header menus
	function userMenu(anchor) {
		cp.popover(anchor, [
			el("div", { class: "cp-pop__head" }, el("b", { text: B.user.full_name }), el("span", { text: B.user.email || B.user.name })),
			el("hr"),
			cp.link("profile", [icon("building-2", "cp-i--sm"), __("Company profile")]),
			cp.link("settings", [icon("settings", "cp-i--sm"), __("Settings")]),
			el("a", { href: "/update-password" }, icon("key-round", "cp-i--sm"), __("Change password")),
			el("hr"),
			el("a", { href: "/api/method/logout?redirect-to=/login" }, icon("log-out", "cp-i--sm"), __("Log out")),
		]);
	}
	function helpMenu(anchor) {
		const s = B.settings || {};
		cp.popover(anchor, [
			el("div", { class: "cp-pop__head" }, el("b", { text: __("Rental team") }), el("span", { text: __("We are here to help with orders, deliveries and invoices.") })),
			el("hr"),
			cp.can_request() ? cp.link("requests/new?type=Support Request", [icon("life-buoy", "cp-i--sm"), __("Raise a support request")]) : null,
			s.contact_email ? el("a", { href: "mailto:" + s.contact_email }, icon("mail", "cp-i--sm"), s.contact_email) : null,
			s.contact_phone ? el("a", { href: "tel:" + s.contact_phone.replace(/\s/g, "") }, icon("phone", "cp-i--sm"), s.contact_phone) : null,
			cp.link("communications", [icon("messages-square", "cp-i--sm"), __("Messages with the team")]),
		]);
	}

	async function openNotifications(anchor) {
		const body = el("div", { class: "cp-panel__body" }, el("div", { style: { padding: "14px" } }, el("div", { class: "cp-skel", style: { height: "40px" } })));
		const markAll = el("button", { type: "button", class: "cp-btn cp-btn--ghost cp-btn--sm", text: __("Mark all read") });
		const pop = cp.popover(anchor, [el("div", { class: "cp-panel__head" }, el("h2", { text: __("Notifications") }), markAll), body,
			el("div", { class: "cp-panel__foot" }, cp.link("notifications", __("See all notifications")))], { cls: "cp-panel", role: "dialog" });
		markAll.addEventListener("click", async () => {
			const r = await cp.api("mark_notifications_read", {}, { post: true });
			cp.setCounter("unread", r.unread);
			body.querySelectorAll(".is-unread").forEach((n) => n.classList.remove("is-unread"));
		});
		try {
			const data = await cp.api("notifications", { page_length: 12 });
			cp.setCounter("unread", data.unread);
			body.replaceChildren(...(data.rows.length ? data.rows.map((n) => noteRow(n, () => pop._close())) : [cp.empty(__("You're all caught up"), __("Order, delivery, invoice and request updates appear here."), null, "bell")]));
		} catch (e) {
			body.replaceChildren(cp.errorBox(e, () => openNotifications(anchor)));
		}
	}
	function noteRow(n, after) {
		const row = el(n.route ? "a" : "div", { class: "cp-note" + (n.read ? "" : " is-unread"), href: n.route ? cp.href(n.route) : null },
			el("span", { class: "cp-note__dot", "aria-hidden": "true" }),
			el("span", {}, el("span", { class: "cp-note__text", text: n.subject }), el("span", { class: "cp-note__time", text: cp.ago(n.creation) })));
		row.addEventListener("click", async (e) => {
			if (!n.read) {
				n.read = 1;
				row.classList.remove("is-unread");
				cp.api("mark_notifications_read", { names: [n.name] }, { post: true }).then((r) => cp.setCounter("unread", r.unread)).catch(() => null);
			}
			if (n.route) {
				e.preventDefault();
				if (after) after();
				cp.go(n.route);
			}
		});
		return row;
	}
	cp.noteRow = noteRow;

	// ------------------------------------------------------------------ global search (Ctrl/Cmd K)
	function openSearch() {
		const input = el("input", { type: "search", placeholder: __("Search orders, deliveries, invoices, requests…"), "aria-label": __("Search"), autocomplete: "off" });
		const results = el("div", { class: "cp-palette__body", role: "listbox" }, el("div", { class: "cp-palette__hint", text: __("Type at least two characters. Only your company's records are searched.") }));
		const m = cp.modal(null, el("div", {}, el("div", { class: "cp-palette__input" }, icon("search"), input), results), null, { cls: "cp-palette" });
		m.box.querySelector(".cp-modal__body").style.padding = "0";
		input.focus();
		let t, seq = 0, sel = -1;
		const rows = () => [...results.querySelectorAll(".cp-palette__row")];
		const mark = () => rows().forEach((r, i) => r.classList.toggle("is-sel", i === sel));
		input.addEventListener("keydown", (e) => {
			const list = rows();
			if (e.key === "ArrowDown") { sel = Math.min(list.length - 1, sel + 1); mark(); e.preventDefault(); }
			else if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); mark(); e.preventDefault(); }
			else if (e.key === "Enter" && list[Math.max(sel, 0)]) { list[Math.max(sel, 0)].click(); }
		});
		input.addEventListener("input", () => {
			clearTimeout(t);
			t = setTimeout(async () => {
				const q = input.value.trim();
				if (q.length < 2) return;
				const my = ++seq;
				results.replaceChildren(el("div", { class: "cp-palette__hint", text: __("Searching…") }));
				try {
					const groups = await cp.api("search", { q });
					if (my !== seq) return;
					sel = -1;
					if (!groups.length) return results.replaceChildren(el("div", { class: "cp-palette__hint", text: __("No records match “{0}”.", [q]) }));
					results.replaceChildren(...groups.flatMap((g) => [el("div", { class: "cp-palette__group" }, icon(g.icon, "cp-i--sm"), g.label),
						...g.rows.map((r) => {
							const a = el("a", { class: "cp-palette__row", href: cp.href(r.route), role: "option" }, el("b", { text: r.title }), el("span", { text: r.sub || "" }));
							a.addEventListener("click", (e) => { e.preventDefault(); m.close(); cp.go(r.route); });
							return a;
						})]));
				} catch (e) {
					results.replaceChildren(el("div", { class: "cp-palette__hint", text: e.message }));
				}
			}, 250);
		});
	}
	document.addEventListener("keydown", (e) => {
		if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
			e.preventDefault();
			if (!document.querySelector(".cp-palette")) openSearch();
		}
	});

	// ------------------------------------------------------------------ router
	const LEGACY = { contracts: "orders", material: "active", "": "" };
	const ROUTES = [
		[/^$/, "dashboard"],
		[/^orders$/, "orders"], [/^orders\/(.+)$/, "order"],
		[/^active$/, "active"],
		[/^deliveries$/, "deliveries"], [/^deliveries\/(.+)$/, "delivery"],
		[/^returns$/, "returns"], [/^returns\/(.+)$/, "return_note"],
		[/^extensions$/, "extensions"], [/^additional$/, "additional"],
		[/^enquiries$/, "enquiries"], [/^quotations$/, "quotations"], [/^quotations\/(.+)$/, "quotation"],
		[/^sales-orders$/, "sales_orders"], [/^sales-orders\/(.+)$/, "sales_order"],
		[/^invoices$/, "invoices"], [/^invoices\/(.+)$/, "invoice"],
		[/^payments$/, "payments"], [/^statement$/, "statement"],
		[/^requests$/, "requests"], [/^requests\/new$/, "new_request"], [/^requests\/(.+)$/, "request"],
		[/^complaints$/, "complaints"], [/^support$/, "support"], [/^communications$/, "communications"],
		[/^documents$/, "documents"], [/^documents\/(rental|delivery|invoices)$/, "documents"], [/^history$/, "history"],
		[/^profile$/, "profile"], [/^contacts$/, "contacts"], [/^notifications$/, "notifications"], [/^settings$/, "settings"],
		[/^preview$/, "preview"],
	];
	function currentPath() {
		return decodeURIComponent(location.pathname.replace(/^\/rental\/?/, "").replace(/\/+$/, ""));
	}
	cp.go = function (routeOrUrl, replace) {
		const url = /^\//.test(routeOrUrl) ? routeOrUrl : cp.href(routeOrUrl);
		const withCustomer = B.staff && cp.state.customer && !url.includes("customer=") ? url + (url.includes("?") ? "&" : "?") + "customer=" + encodeURIComponent(cp.state.customer) : url;
		history[replace ? "replaceState" : "pushState"]({}, "", withCustomer);
		route();
	};
	let routeSeq = 0;
	async function route() {
		let path = currentPath();
		const q = new URLSearchParams(location.search);
		if (path === "contract" && q.get("name")) return cp.go("orders/" + q.get("name"), true);
		if (path in LEGACY && LEGACY[path] !== path) return cp.go(LEGACY[path], true);
		if (B.staff && !cp.state.customer && path !== "preview") return cp.go("preview", true);
		let page = null, params = [];
		for (const [re, name] of ROUTES) {
			const m = path.match(re);
			if (m) {
				page = name;
				params = m.slice(1);
				break;
			}
		}
		shell.classList.remove("is-drawer");
		renderNav(path);
		const my = ++routeSeq;
		const ctx = {
			main, params, query: q, path,
			isCurrent: () => my === routeSeq,
			setTitle(title, trail) {
				document.title = title + " · thinkNXG Rental";
				crumbs.replaceChildren(cp.link("", __("Home")), ...(trail || []).flatMap(([t, r]) => [icon("chevron-right", "cp-i--sm"), cp.link(r, t)]),
					icon("chevron-right", "cp-i--sm"), el("b", { text: title }));
				if (path === "") crumbs.replaceChildren(el("b", { text: __("Dashboard") }));
			},
		};
		window.scrollTo(0, 0);
		main.replaceChildren(page === "dashboard" ? cp.dashSkeleton() : cp.skeleton(8));
		if (!page || !P[page]) {
			ctx.setTitle(__("Page not found"));
			main.replaceChildren(cp.errorBox({ status: 404, message: __("This page does not exist. Use the menu to find what you need.") }));
			return;
		}
		try {
			await P[page](ctx);
		} catch (e) {
			if (my !== routeSeq) return;
			console.error(e); // eslint-disable-line no-console
			ctx.setTitle(__("Not available"));
			main.replaceChildren(cp.errorBox(e, route));
		}
		if (my === routeSeq && document.activeElement === document.body) main.focus({ preventScroll: true });
	}
	cp.reload = route;
	document.addEventListener("click", (e) => {
		const a = e.target.closest("a[data-nav]");
		if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || a.target === "_blank") return;
		const href = a.getAttribute("href");
		if (!href || !href.startsWith(cp.base)) return;
		e.preventDefault();
		cp.go(href);
	});
	window.addEventListener("popstate", route);

	// ------------------------------------------------------------------ start
	function start() {
		if (!B.user) return;
		if (!B.staff && !B.customers.length) {
			document.getElementById("cp-app").replaceChildren(el("div", { class: "cp-main", style: { maxWidth: "620px", paddingTop: "12vh" } },
				el("div", { class: "cp-card", style: { padding: "28px" } }, el("h1", { style: { font: "600 28px var(--display)", margin: "0 0 8px" }, text: __("Your login is not linked to a company yet") }),
					el("p", { style: { color: "var(--mute)" }, text: __("Ask the rental team to add you as a portal user of your company. Then sign in again.") }),
					B.settings.contact_email ? el("p", {}, el("a", { href: "mailto:" + B.settings.contact_email, text: B.settings.contact_email })) : null,
					el("a", { class: "cp-btn", href: "/api/method/logout?redirect-to=/login" }, __("Log out")))));
			return;
		}
		buildShell();
		route();
		cp.api("requests", { status: "open", page_length: 1 }).then((r) => cp.setCounter("open_requests", r.total)).catch(() => null);
	}
	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
	else start();
})();
