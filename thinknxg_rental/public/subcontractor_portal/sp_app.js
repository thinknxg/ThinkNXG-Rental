// thinkNXG Rental subcontractor portal: shell, navigation and router. Pages change without reloading; the address
// always says where you are, so Back, bookmarks and "open in new tab" work.
(function () {
	"use strict";
	const sp = window.sp;
	const { el, fill } = sp;
	const app = document.getElementById("sp-app");
	if (!app) return;

	const ROUTES = [
		["dashboard", "Dashboard", "layout-dashboard", "dashboard"],
		["work-orders", "Work orders", "clipboard-list", "workOrders"],
		["progress", "Progress reports", "trending-up", "progress"],
		["inspections", "Inspections", "search-check", "inspections"],
		["materials", "Materials", "package", "materials"],
		["variations", "Variations and claims", "git-pull-request", "variations"],
		["invoices", "Invoices", "receipt", "invoices", true],
		["payments", "Payments", "wallet", "payments", true],
		["messages", "Messages", "message-square", "messages"],
		["profile", "Company and documents", "building-2", "profile"],
	];

	const main = el("main", { id: "sp-main", class: "sp-main", tabindex: "-1" });
	const title = el("h1");
	const nav = el("nav", { class: "sp-nav", "aria-label": __("Portal") });
	const bellDot = el("span", { class: "sp-dot", hidden: true });
	const crumbs = el("div", { class: "sp-sub" });

	function drawNav() {
		fill(nav, ROUTES.filter((r) => !r[4] || sp.state.commercial).map(([key, label, ic]) => {
			const href = sp.base + "/" + key;
			return el("a", { href, "data-key": key, onclick: (e) => { sp.linkClick(e, href); app.dataset.drawer = "0"; } }, sp.icon(ic), el("span", { text: __(label) }));
		}));
	}
	function markActive(path) {
		nav.querySelectorAll("a").forEach((a) => {
			const k = a.getAttribute("data-key");
			if (path === k || path.startsWith(k + "/")) a.setAttribute("aria-current", "page");
			else a.removeAttribute("aria-current");
		});
	}

	async function bell(btn) {
		const pop = el("div", { class: "sp-pop", role: "dialog", "aria-label": __("Notifications") }, el("div", { class: "sp-loading", text: __("Loading…") }));
		const close = (e) => { if (!pop.contains(e.target) && e.target !== btn) { pop.remove(); document.removeEventListener("click", close); } };
		document.querySelector(".sp-body").append(pop);
		setTimeout(() => document.addEventListener("click", close), 0);
		const d = await sp.api("notifications", {});
		fill(pop, d.rows.length ? el("ul", { class: "sp-list" }, d.rows.map((n) => el("li", {}, el("div", { class: "sp-grow" }, el("div", { style: n.read ? "" : "font-weight:600", text: n.subject.replace(/<[^>]+>/g, "") }),
			el("div", { class: "sp-sub", text: sp.date(n.creation) }))))) : sp.empty(__("No notifications"), null));
		if (d.unread) {
			await sp.post("mark_notifications_read", {});
			bellDot.hidden = true;
		}
	}
	async function refreshBell() {
		try {
			const d = await sp.api("notifications", {}, { silent: true });
			bellDot.hidden = !d.unread;
			bellDot.textContent = d.unread > 9 ? "9+" : d.unread;
		} catch (e) { /* offline */ }
	}

	function shell() {
		const s = sp.state;
		const accounts = s.accounts && s.accounts.length > 1 ? el("select", { "aria-label": __("Subcontractor account"), onchange: (e) => { s.supplier = e.target.value; start(); } },
			s.accounts.map((a) => el("option", { value: a.supplier, text: a.name, selected: a.supplier === s.supplier }))) : null;
		const bellBtn = el("button", { type: "button", class: "sp-iconbtn", "aria-label": __("Notifications"), onclick: (e) => bell(e.currentTarget) }, sp.icon("bell"), bellDot);
		fill(app,
			el("aside", { class: "sp-side" },
				el("div", { class: "sp-brand" }, el("b", { text: __("Subcontractor Portal") }), el("span", { text: (window.sp_boot && window.sp_boot.company) || "thinkNXG Rental" })),
				el("div", { class: "sp-account" }, el("strong", { text: s.supplier_name || s.supplier }), el("span", { text: s.full_name + " · " + __(s.access_level) }), accounts),
				nav,
				el("div", { class: "sp-side-foot" }, s.contact_email ? el("div", {}, __("Help: "), el("span", { text: s.contact_email })) : null,
					s.contact_phone ? el("div", { text: s.contact_phone }) : null, el("a", { href: "/update-password" }, __("Change password")), " · ",
					el("a", { href: "/?cmd=web_logout", onclick: (e) => { e.preventDefault(); fetch("/api/method/logout", { credentials: "same-origin" }).finally(() => (location.href = "/login")); } }, __("Log out")))),
			el("div", { class: "sp-body" },
				el("header", { class: "sp-top" },
					el("button", { type: "button", class: "sp-iconbtn sp-menu-btn", "aria-label": __("Menu"), onclick: () => (app.dataset.drawer = app.dataset.drawer === "1" ? "0" : "1") }, sp.icon("menu")),
					el("div", { style: "flex:1;min-width:0" }, crumbs, title), bellBtn),
				main));
		drawNav();
	}

	function resolve(path) {
		if (!path) return { page: "dashboard" };
		if (path.startsWith("work-orders/")) return { page: "workOrder", name: decodeURIComponent(path.slice(12)) };
		const r = ROUTES.find((x) => x[0] === path && (!x[4] || sp.state.commercial));
		return r ? { page: r[3] } : null;
	}

	let seq = 0;
	async function show() {
		const my = ++seq;
		const path = location.pathname.slice(sp.base.length).replace(/^\/+|\/+$/g, "");
		const r = resolve(path);
		markActive(path || "dashboard");
		const ctx = {
			root: main, name: r && r.name, query: location.search.slice(1),
			title(t, trail) {
				if (my !== seq) return;
				title.textContent = t;
				document.title = t + " · " + __("Subcontractor Portal");
				fill(crumbs, (trail || []).map((x) => [sp.link(x.route, x.label), " / "]));
			},
			reload: () => show(),
		};
		fill(main, el("div", { class: "sp-loading", text: __("Loading…") }));
		main.setAttribute("aria-busy", "true");
		try {
			if (!r || !sp.pages[r.page]) {
				ctx.title(__("Not found"));
				fill(main, sp.panel(null, sp.empty(__("There is no page at this address"), null, sp.link("dashboard", __("Go to the dashboard")))));
			} else await sp.pages[r.page](ctx);
		} catch (e) {
			if (my !== seq) return;
			ctx.title(__("Not available"));
			fill(main, sp.panel(null, sp.empty(e.status === 403 ? __("You cannot open this page") : __("This page could not be loaded"), e.message, sp.btn(__("Try again"), () => show()))));
		} finally {
			main.removeAttribute("aria-busy");
		}
	}
	sp.go = function (href) {
		history.pushState(null, "", href);
		show();
		window.scrollTo(0, 0);
	};
	sp.reload = () => show();
	window.addEventListener("popstate", show);

	async function start() {
		try {
			const b = await sp.api("boot", {});
			Object.assign(sp.state, b);
		} catch (e) {
			fill(app, el("div", { class: "sp-main" }, sp.panel(null, sp.empty(__("The portal could not be opened"), e.message, el("a", { class: "sp-btn", href: "/login" }, __("Log in again"))))));
			return;
		}
		app.removeAttribute("data-loading");
		shell();
		await show();
		refreshBell();
		setInterval(refreshBell, 120000);
	}
	start();
})();
