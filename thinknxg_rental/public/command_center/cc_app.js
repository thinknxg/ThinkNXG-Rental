// Command Center shell: sidebar, top bar, router, global search, Quick Create, notifications.
// Pages change without reloading; the address always says where you are, so Back, bookmarks and
// "open in new tab" work as on any website.
(function () {
	const cc = window.cc;
	const { el, __ } = cc;
	const boot = cc.boot;
	const P = cc.pages;
	const app = document.getElementById("cc-app");
	if (!app || !boot.user) return;

	// ------------------------------------------------------------------ nav lookup
	const navItems = boot.nav.flatMap((g) => g.items.map((i) => Object.assign({ group: g.label }, i)));
	const findNav = (path) => {
		let best = null;
		navItems.forEach((i) => {
			if (i.alias) return;
			const k = i.key;
			const qk = k.split("?")[0];
			if ((path === qk || path.startsWith(qk + "/")) && (!best || qk.length > best.key.length)) best = i;
		});
		return best;
	};

	// ------------------------------------------------------------------ shell
	const main = el("main", { id: "cc-main", class: "cc-main", tabindex: "-1" });
	const crumbs = el("nav", { class: "cc-crumbs", "aria-label": __("Breadcrumb") });
	const navEl = el("nav", { "aria-label": __("Command Center") });
	const counts = {};
	function drawNav() {
		const closed = cc.store.get("groups", {});
		navEl.replaceChildren(...boot.nav.map((g) => {
			const group = el("div", { class: "cc-group", "data-closed": closed[g.key] ? "1" : "0" });
			const toggle = el("button", { type: "button", "aria-expanded": closed[g.key] ? "false" : "true", onclick: () => {
				const c = cc.store.get("groups", {});
				c[g.key] = !c[g.key];
				cc.store.set("groups", c);
				group.dataset.closed = c[g.key] ? "1" : "0";
				toggle.setAttribute("aria-expanded", c[g.key] ? "false" : "true");
			} }, el("span", { text: g.label }), cc.icon("chevron-down", "cc-i--sm"));
			group.append(toggle, el("ul", {}, g.items.map((i) => {
				const href = i.kind === "desk" ? "/app/thinknxg-rental" : cc.base + "/" + i.key;
				const a = el("a", { class: "cc-nav-item", href, "data-key": i.key, title: i.label }, cc.icon(i.icon), el("span", { class: "cc-label", text: i.label }));
				if (counts[i.key]) a.append(el("span", { class: "cc-count" + (["requests"].includes(i.key) ? " cc-count--hot" : ""), text: counts[i.key] > 99 ? "99+" : counts[i.key], "aria-label": __("{0} waiting", [counts[i.key]]) }));
				if (i.kind !== "desk") a.addEventListener("click", (e) => {
					cc.linkClick(e, href);
					app.dataset.drawer = "0";
				});
				return el("li", {}, a);
			})));
			return group;
		}));
		markActive();
	}
	function markActive() {
		const item = findNav(current.path || "dashboard");
		let lit = false;
		navEl.querySelectorAll(".cc-nav-item").forEach((a) => {
			// an item listed twice (Stock Position under Yard and Reports) lights up once
			if (!lit && item && a.getAttribute("data-key") === item.key) {
				a.setAttribute("aria-current", "page");
				lit = true;
			} else a.removeAttribute("aria-current");
		});
	}
	cc.refreshBadges = async function () {
		try {
			const [b, n] = await Promise.all([cc.api("badges", {}, { silent: true }), cc.api("notifications", { limit: 1 }, { silent: true })]);
			Object.keys(counts).forEach((k) => delete counts[k]);
			Object.assign(counts, b);
			bellDot.hidden = !n.unread;
			bellDot.textContent = n.unread > 9 ? "9+" : n.unread;
			drawNav();
		} catch (e) {
			/* offline for a moment: keep the old counts */
		}
	};

	const collapseBtn = el("button", { type: "button", class: "cc-collapse-btn", onclick: () => {
		const v = app.dataset.collapsed === "1" ? "0" : "1";
		app.dataset.collapsed = v;
		cc.store.set("collapsed", v);
		collapseBtn.replaceChildren(cc.icon(v === "1" ? "panel-left-open" : "panel-left-close"), el("span", { class: "cc-label", text: v === "1" ? __("Expand") : __("Collapse sidebar") }));
	} });
	app.dataset.collapsed = cc.store.get("collapsed", "0");
	collapseBtn.append(cc.icon(app.dataset.collapsed === "1" ? "panel-left-open" : "panel-left-close"), el("span", { class: "cc-label", text: app.dataset.collapsed === "1" ? __("Expand") : __("Collapse sidebar") }));

	const brand = el("a", { class: "cc-brand", href: cc.base + "/dashboard" }, el("img", { src: "/assets/thinknxg_rental/images/logo.svg", alt: "" }), el("div", {}, el("b", { text: "thinkNXG Rental" }), el("span", { text: __("Command Center") })));
	brand.addEventListener("click", (e) => cc.linkClick(e, brand.getAttribute("href")));
	const side = el("aside", { class: "cc-side", "aria-label": __("Main menu") }, brand, navEl, el("div", { class: "cc-side-foot" }, collapseBtn));

	// top bar
	const menuBtn = el("button", { type: "button", class: "cc-iconbtn cc-menu-btn", "aria-label": __("Menu"), onclick: () => (app.dataset.drawer = app.dataset.drawer === "1" ? "0" : "1") }, cc.icon("menu"));
	const searchBtn = el("button", { type: "button", class: "cc-searchbox", "aria-label": __("Search (Ctrl+K)"), onclick: () => openSearch() }, cc.icon("search", "cc-i--sm"), el("span", { text: __("Search documents, customers, items") }), el("span", { class: "cc-kbd", text: navigator.platform.includes("Mac") ? "⌘K" : "Ctrl K" }));
	const createBtn = el("button", { type: "button", class: "cc-btn cc-btn--primary", "aria-haspopup": "true" }, cc.icon("plus", "cc-i--sm"), el("span", { class: "cc-label-create", text: __("New") }));
	createBtn.addEventListener("click", () => cc.popover(createBtn, [el("h3", { text: __("Quick create") }), ...boot.quick_create.map((q) => {
		const a = el("a", { href: cc.base + "/" + q.route + "/new" }, cc.icon("plus", "cc-i--sm"), q.label);
		a.addEventListener("click", (e) => cc.linkClick(e, a.getAttribute("href")));
		return a;
	})]));
	if (!boot.quick_create.length) createBtn.hidden = true;
	const bellDot = el("span", { class: "cc-dot", hidden: true });
	const bell = el("button", { type: "button", class: "cc-iconbtn", "aria-label": __("Notifications"), onclick: () => openNotifications() }, cc.icon("bell"), bellDot);
	const helpBtn = el("button", { type: "button", class: "cc-iconbtn", "aria-label": __("Help"), "aria-haspopup": "true" }, cc.icon("circle-help"));
	helpBtn.addEventListener("click", () => cc.popover(helpBtn, [
		el("h3", { text: __("Keyboard") }),
		...[["Ctrl K", __("Search")], ["Ctrl S", __("Save the open form")], ["g d", __("Dashboard")], ["g r", __("Customer requests")], ["n", __("Quick create")], ["Esc", __("Close a dialog")]]
			.map(([k, l]) => el("div", { style: "display:flex;gap:12px;justify-content:space-between;padding:5px 10px" }, el("span", { text: l }), el("span", { class: "cc-kbd", text: k }))),
		el("hr"),
		el("a", { href: "/app/thinknxg-rental" }, cc.icon("external-link", "cc-i--sm"), __("Open the thinkNXG desk")),
		el("a", { href: "/rental", target: "_blank", rel: "noopener" }, cc.icon("external-link", "cc-i--sm"), __("Customer portal")),
	]));
	const u = boot.user;
	const avatar = el("span", { class: "cc-avatar" }, u.image ? el("img", { src: u.image, alt: "" }) : u.initials);
	const profile = el("button", { type: "button", class: "cc-profile", "aria-haspopup": "true", "aria-label": __("Account") }, avatar, el("span", {}, el("b", { text: u.full_name }), el("small", { text: u.roles[0] || "" })));
	profile.addEventListener("click", () => cc.popover(profile, [
		el("div", { style: "padding:8px 10px" }, el("b", { style: "display:block", text: u.full_name }), el("small", { class: "cc-muted", text: u.name }), el("div", { style: "display:flex;gap:4px;flex-wrap:wrap;margin-top:6px" }, u.roles.map((r) => cc.pill(r, "info")))),
		el("hr"),
		el("a", { href: "/app/user/" + encodeURIComponent(u.name) }, cc.icon("settings", "cc-i--sm"), __("My settings")),
		el("a", { href: "/app/thinknxg-rental" }, cc.icon("layout-grid", "cc-i--sm"), __("Open the thinkNXG desk")),
		el("hr"),
		el("button", { type: "button", class: "cc-menuitem", onclick: async () => {
			try { await cc.call("logout", {}, { post: true, silent: true }); } catch (e) { /* already out */ }
			window.location.href = "/login";
		} }, cc.icon("log-out", "cc-i--sm"), __("Log out")),
	]));
	const top = el("header", { class: "cc-top" }, menuBtn, crumbs, searchBtn, el("div", { class: "cc-top-actions" }, createBtn, bell, helpBtn, profile));
	app.replaceChildren(side, el("div", { class: "cc-body" }, top, main));
	app.removeAttribute("data-loading");
	const scrimMobile = el("div", { class: "cc-scrim", style: "z-index:25", hidden: true, onclick: () => (app.dataset.drawer = "0") });
	document.body.append(scrimMobile);
	new MutationObserver(() => (scrimMobile.hidden = app.dataset.drawer !== "1")).observe(app, { attributes: true, attributeFilter: ["data-drawer"] });

	// ------------------------------------------------------------------ router
	const routes = boot.routes;
	const SIMPLE = { "": "dashboard", dashboard: "dashboard", notifications: "notifications", tasks: "tasks", requests: "requests", inventory: "inventory",
		"material-at-site": "material", "supplier-position": "suppliers", billing: "billing", outstanding: "outstanding", utilization: "utilization",
		settings: "settings", users: "users", customers: "customers" };
	function resolve(path) {
		path = path.replace(/^\/+|\/+$/g, "");
		if (path in SIMPLE) return { page: SIMPLE[path] };
		if (routes.reports[path]) return { page: "report" };
		if (path.startsWith("requests/")) return { page: "form", entry: "request", name: decodeURIComponent(path.slice(9)) };
		if (path.startsWith("customers/")) return { page: "customer", name: decodeURIComponent(path.slice(10)) };
		if (path.startsWith("doc/")) {
			const [, entry, ...rest] = path.split("/");
			const name = decodeURIComponent(rest.join("/"));
			return { page: "form", entry, name: name === "new" ? null : name };
		}
		const keys = Object.keys(routes.views).sort((a, b) => b.length - a.length);
		for (const key of keys) {
			const v = routes.views[key];
			if (path === key && (v.kind === "entry" || v.kind === "doctype")) return { page: "list", key };
			if (path.startsWith(key + "/") && v.kind === "entry") {
				const name = decodeURIComponent(path.slice(key.length + 1));
				return { page: "form", key, entry: v.entry, name: name === "new" ? null : name };
			}
		}
		return null;
	}

	const current = { path: "", leave: [], keys: [] };
	let navSeq = 0;
	async function show(push) {
		const seq = ++navSeq;
		let path = location.pathname.slice(cc.base.length).replace(/^\/+|\/+$/g, "");
		let query = location.search.slice(1);
		// old portal addresses and the plain /rental/admin
		const legacy = cc.fromPortalUrl(location.pathname + location.search);
		if (legacy && legacy !== location.pathname + location.search && legacy.startsWith(cc.base)) {
			history.replaceState(null, "", legacy);
			return show();
		}
		if (path === "") {
			history.replaceState(null, "", cc.base + "/dashboard" + (query ? "?" + query : ""));
			path = "dashboard";
		}
		if (path === "desk") {
			window.location.href = "/app/thinknxg-rental";
			return;
		}
		current.path = path;
		current.leave = [];
		current.keys = [];
		cc.closeLayer();
		cc.chart.hide();
		markActive();
		const r = resolve(path);
		const nav = findNav(path);
		const ctx = {
			root: main, path, query, key: r && r.key, entry: r && r.entry, name: r && r.name,
			setTitle(title, extra) {
				if (seq !== navSeq) return;
				document.title = title + " · thinkNXG Rental";
				const parts = [];
				if (nav && nav.group) parts.push(el("span", { text: nav.group }));
				if (extra && extra.length) extra.forEach((x) => parts.push(cc.link(x.route, x.label)));
				else if (nav && nav.label !== title) parts.push(cc.link(nav.key, nav.label));
				parts.push(el("span", { text: title }));
				crumbs.replaceChildren(...parts.flatMap((p, i) => (i ? [cc.icon("chevron-right", "cc-i--sm"), p] : [p])));
			},
			onLeave(fn) { current.leave.push(fn); },
			onKey(fn) { current.keys.push(fn); },
			reload() { show(); },
		};
		main.setAttribute("aria-busy", "true");
		try {
			if (!r || !P[r.page]) {
				ctx.setTitle(__("Not found"));
				main.replaceChildren(cc.pagehead(__("Page not found")), cc.panel(null, cc.empty(__("There is no page at this address"), __("It may have moved. Use the menu or search to find what you need."), cc.btn(__("Go to the dashboard"), null, { href: cc.base + "/dashboard", kind: "primary" }))));
			} else {
				await P[r.page](ctx);
			}
		} catch (e) {
			if (seq === navSeq && !e.shown) main.replaceChildren(cc.failure(e));
		} finally {
			if (seq === navSeq) {
				main.removeAttribute("aria-busy");
				if (push) {
					window.scrollTo(0, 0);
					main.focus({ preventScroll: true });
				}
			}
		}
	}
	async function mayLeave() {
		for (const fn of current.leave) {
			const msg = fn();
			if (msg && !(await cc.confirm(__("Leave this page?"), msg, __("Leave without saving"), true))) return false;
		}
		return true;
	}
	cc.go = async function (href, opts) {
		opts = opts || {};
		if (!href.startsWith(cc.base)) {
			window.location.href = href;
			return;
		}
		const same = href === location.pathname + location.search;
		if (!opts.replace && !same && !(await mayLeave())) return;
		if (opts.replace || same) history.replaceState(null, "", href);
		else history.pushState(null, "", href);
		show(!opts.replace);
	};
	window.addEventListener("popstate", () => show(true));
	window.addEventListener("beforeunload", (e) => {
		if (current.leave.some((fn) => fn())) {
			e.preventDefault();
			e.returnValue = "";
		}
	});

	// ------------------------------------------------------------------ global search
	function openSearch() {
		const input = el("input", { type: "search", placeholder: __("Search by number, customer, site or item"), "aria-label": __("Search"), autocomplete: "off" });
		const list = el("div", { class: "cc-palette-list", role: "listbox" });
		const box = el("div", { class: "cc-dialog cc-palette", role: "dialog", "aria-modal": "true", "aria-label": __("Search") },
			el("div", { class: "cc-palette-input" }, cc.icon("search"), input, el("span", { class: "cc-kbd", text: "Esc" })), list);
		let hits = [];
		let sel = 0;
		const draw = (sections) => {
			hits = [];
			list.replaceChildren(...sections.filter((s) => s.items.length).flatMap((s) => [el("h3", { text: s.label }), ...s.items.map((h) => {
				const i = hits.length;
				hits.push(h);
				const b = el("button", { type: "button", class: "cc-hit", role: "option", "aria-selected": i === sel ? "true" : "false", onclick: () => pick(h) },
					cc.icon(h.icon || "file-text", "cc-i--sm"), el("b", { text: h.title }), h.sub ? el("span", { class: "cc-hit-sub", text: h.sub }) : null, h.tag ? el("small", { text: h.tag }) : null);
				b.addEventListener("mousemove", () => { sel = i; paint(); });
				return b;
			})]));
			if (!hits.length) list.replaceChildren(el("p", { class: "cc-muted", style: "padding:14px", text: input.value.trim().length < 2 ? __("Type at least two characters.") : __("Nothing found for “{0}”.", [input.value.trim()]) }));
		};
		const paint = () => list.querySelectorAll(".cc-hit").forEach((b, i) => {
			b.setAttribute("aria-selected", i === sel ? "true" : "false");
			if (i === sel) b.scrollIntoView({ block: "nearest" });
		});
		const pick = (h) => {
			cc.closeLayer();
			if (h.href.startsWith(cc.base)) cc.go(h.href);
			else window.location.href = h.href;
		};
		const pages = (needle) => navItems.filter((i) => !i.alias && i.label.toLowerCase().includes(needle)).slice(0, 6)
			.map((i) => ({ title: i.label, sub: i.group, icon: i.icon, href: i.kind === "desk" ? "/app/thinknxg-rental" : cc.base + "/" + i.key, tag: __("Page") }));
		const idle = () => {
			sel = 0;
			draw([
				{ label: __("Favourites"), items: cc.favorites().slice(0, 5).map((d) => ({ title: d.title, sub: d.label, icon: "star", href: d.href })) },
				{ label: __("Recent"), items: cc.store.get("recent", []).slice(0, 6).map((d) => ({ title: d.title, sub: [d.label, d.sub].filter(Boolean).join(", "), icon: "clock", href: d.href })) },
				{ label: __("Create"), items: boot.quick_create.slice(0, 5).map((q) => ({ title: q.label, icon: "plus", href: cc.base + "/" + q.route + "/new" })) },
			]);
			if (!hits.length) list.replaceChildren(el("p", { class: "cc-muted", style: "padding:14px", text: __("Search hire orders, contracts, deliveries, invoices, customers and items by number or name.") }));
		};
		let seq = 0;
		const run = cc.debounce(async () => {
			const needle = input.value.trim();
			if (needle.length < 2) return idle();
			const mine = ++seq;
			const local = pages(needle.toLowerCase());
			draw([{ label: __("Pages"), items: local }, { label: __("Searching…"), items: [] }]);
			try {
				const res = await cc.api("search", { q: needle }, { silent: true });
				if (mine !== seq) return;
				sel = 0;
				const groups = {};
				res.forEach((r) => (groups[r.doctype] = groups[r.doctype] || []).push({ title: r.name, sub: [r.title, r.status].filter(Boolean).join(", "), icon: "file-text", href: cc.target(r), tag: r.doctype }));
				draw([{ label: __("Pages"), items: local }, ...Object.entries(groups).map(([label, items]) => ({ label, items }))]);
			} catch (e) {
				/* shown as nothing found */
			}
		}, 180);
		input.addEventListener("input", run);
		input.addEventListener("keydown", (e) => {
			if (e.key === "ArrowDown" || e.key === "ArrowUp") {
				e.preventDefault();
				if (!hits.length) return;
				sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + hits.length) % hits.length;
				paint();
			} else if (e.key === "Enter" && hits[sel]) {
				e.preventDefault();
				pick(hits[sel]);
			}
		});
		cc.layer([box]);
		idle();
		input.focus();
	}

	// ------------------------------------------------------------------ notifications drawer
	async function openNotifications() {
		const body = el("div", { class: "cc-drawer-body" }, cc.skeleton(5));
		const drawer = el("aside", { class: "cc-drawer", role: "dialog", "aria-modal": "true", "aria-label": __("Notifications") },
			el("header", {}, el("h2", { text: __("Notifications") }), cc.btn(__("See all"), () => { cc.closeLayer(); cc.go(cc.base + "/notifications"); }, { sm: true, kind: "ghost" }),
				el("button", { type: "button", class: "cc-iconbtn", "aria-label": __("Close"), onclick: () => cc.closeLayer() }, cc.icon("x"))), body);
		cc.layer([drawer]);
		try {
			const r = await cc.api("notifications", { limit: 25 });
			body.replaceChildren(r.rows.length ? el("ul", { class: "cc-day", style: "padding:4px 20px" }, r.rows.map((n) => el("li", {},
				el("span", { class: "cc-pill", "data-tone": n.read ? "" : "info", text: n.read ? __("Read") : __("New") }),
				el("div", {}, n.target ? el("a", { href: cc.target(n.target), text: n.subject, onclick: (e) => { cc.closeLayer(); cc.linkClick(e, cc.target(n.target)); } }) : el("span", { text: n.subject }),
					el("small", { text: cc.ago(n.creation) }))))) : cc.empty(__("No notifications"), __("You are up to date.")),
				r.unread ? el("div", { style: "padding:12px 20px" }, cc.btn(__("Mark all as read"), async () => { await cc.api("mark_notifications_read", {}, { post: true }); cc.refreshBadges(); cc.closeLayer(); }, { sm: true, icon: "check" })) : null);
		} catch (e) {
			body.replaceChildren(el("div", { class: "cc-error", style: "margin:16px", text: e.message }));
		}
	}

	// ------------------------------------------------------------------ keyboard
	let pendingG = 0;
	document.addEventListener("keydown", (e) => {
		current.keys.forEach((fn) => fn(e));
		if (e.defaultPrevented) return;
		const typing = e.target.closest && e.target.closest("input, textarea, select, [contenteditable]");
		if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
			e.preventDefault();
			openSearch();
			return;
		}
		if (typing || e.ctrlKey || e.metaKey || e.altKey || document.querySelector(".cc-scrim:not([hidden])")) return;
		if (e.key === "/") {
			e.preventDefault();
			openSearch();
		} else if (e.key === "n" && !createBtn.hidden) {
			e.preventDefault();
			createBtn.click();
		} else if (e.key === "g") pendingG = Date.now();
		else if (Date.now() - pendingG < 900) {
			const to = { d: "dashboard", r: "requests", c: "contracts", b: "billing", i: "inventory", t: "tasks" }[e.key];
			if (to) cc.go(cc.base + "/" + to);
			pendingG = 0;
		}
	});

	// ------------------------------------------------------------------ start
	Object.assign(counts, boot.badges || {});
	drawNav();
	show();
	cc.refreshBadges();
	setInterval(() => document.visibilityState === "visible" && cc.refreshBadges(), 60000);
})();
