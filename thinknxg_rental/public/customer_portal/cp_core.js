/* thinkNXG Rental customer Command Center: core helpers and components.
   No framework: small DOM helpers, a fetch wrapper for the whitelisted API (portal/customer.py),
   formatting, and the reusable pieces every page is built from. */
(function () {
	"use strict";
	const cp = (window.cp = window.cp || {});
	const B = (cp.boot = window.cp_boot || {});
	cp.base = "/rental";
	cp.pages = {};
	const API = "thinknxg_rental.portal.customer.";

	// Page code passes optional parts as `cond ? node : null`. The native replaceChildren / append would
	// print "null"; on this page they skip empty values instead.
	for (const m of ["replaceChildren", "append", "prepend"]) {
		const native = Element.prototype[m];
		Element.prototype[m] = function (...nodes) {
			return native.apply(this, nodes.flat(Infinity).filter((n) => n != null && n !== false && n !== ""));
		};
	}

	// ------------------------------------------------------------------ translation (server strings are already translated)
	window.__ = window.__ || function (s, args) {
		return String(s).replace(/\{(\d+)\}/g, (m, i) => (args && args[i] != null ? args[i] : m));
	};

	// ------------------------------------------------------------------ DOM
	function el(tag, attrs, ...kids) {
		const n = document.createElement(tag);
		for (const [k, v] of Object.entries(attrs || {})) {
			if (v == null || v === false) continue;
			if (k === "class") n.className = v;
			else if (k === "text") n.textContent = v;
			else if (k === "html") n.innerHTML = v;
			else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
			else if (k === "style" && typeof v === "object") Object.assign(n.style, v);
			else n.setAttribute(k, v === true ? "" : v);
		}
		append(n, kids);
		return n;
	}
	function append(n, kids) {
		for (const k of kids.flat(Infinity)) {
			if (k == null || k === false || k === "") continue;
			n.appendChild(k instanceof Node ? k : document.createTextNode(String(k)));
		}
		return n;
	}
	function clear(n, ...kids) {
		n.replaceChildren();
		return append(n, kids);
	}
	const SVGNS = "http://www.w3.org/2000/svg";
	function svg(tag, attrs, ...kids) {
		const n = document.createElementNS(SVGNS, tag);
		for (const [k, v] of Object.entries(attrs || {})) if (v != null) n.setAttribute(k, v);
		for (const k of kids.flat()) if (k) n.appendChild(k instanceof Node ? k : document.createTextNode(k));
		return n;
	}
	function icon(name, cls) {
		const s = svg("svg", { class: "cp-i " + (cls || ""), "aria-hidden": "true" });
		s.appendChild(svg("use", { href: "/assets/frappe/icons/lucide.svg#icon-" + name }));
		return s;
	}
	Object.assign(cp, { el, append, clear, svg, icon });

	// ------------------------------------------------------------------ API
	cp.customer = function () {
		return cp.state && cp.state.customer ? cp.state.customer : null;
	};
	cp.api = async function (method, args, opts) {
		opts = opts || {};
		const params = Object.assign({}, args || {});
		const c = cp.customer();
		if (c && !("customer" in params)) params.customer = c;
		for (const k of Object.keys(params)) if (params[k] == null || params[k] === "") delete params[k];
		const url = "/api/method/" + API + method;
		let res;
		try {
			if (opts.post) {
				const body = new URLSearchParams();
				for (const [k, v] of Object.entries(params)) body.append(k, typeof v === "object" ? JSON.stringify(v) : v);
				res = await fetch(url, { method: "POST", headers: { "X-Frappe-CSRF-Token": window.csrf_token, Accept: "application/json",
					"Content-Type": "application/x-www-form-urlencoded" }, body, credentials: "same-origin" });
			} else {
				const qs = new URLSearchParams();
				for (const [k, v] of Object.entries(params)) qs.append(k, typeof v === "object" ? JSON.stringify(v) : v);
				res = await fetch(url + (qs.toString() ? "?" + qs : ""), { headers: { Accept: "application/json" }, credentials: "same-origin" });
			}
		} catch (e) {
			throw Object.assign(new Error(__("We could not reach the server. Check your connection and try again.")), { network: true });
		}
		let data = {};
		try {
			data = await res.json();
		} catch (e) {
			/* non-JSON */
		}
		if (!res.ok || data.exc_type) {
			if (res.status === 401 || res.status === 403 && data.exc_type === "SessionExpired") {
				window.location.href = "/login?redirect-to=" + encodeURIComponent(location.pathname + location.search);
			}
			throw Object.assign(new Error(serverMessage(data) || __("Something went wrong. Please try again.")), { status: res.status, type: data.exc_type });
		}
		return data.message;
	};
	function serverMessage(data) {
		try {
			if (data._server_messages) {
				const msgs = JSON.parse(data._server_messages).map((m) => {
					try {
						return JSON.parse(m).message;
					} catch (e) {
						return m;
					}
				});
				const div = document.createElement("div");
				div.innerHTML = msgs.join(" ");
				return div.textContent.trim();
			}
		} catch (e) {
			/* ignore */
		}
		if (data.exception) return String(data.exception).split(":").slice(1).join(":").trim();
		return null;
	}
	cp.fileUrl = function (method, args) {
		const params = new URLSearchParams();
		const all = Object.assign({}, args);
		if (cp.customer()) all.customer = cp.customer();
		for (const [k, v] of Object.entries(all)) if (v != null) params.append(k, v);
		return "/api/method/" + API + method + "?" + params;
	};
	cp.pdf = function (doctype, name) {
		return cp.fileUrl("download_pdf", { doctype, name });
	};

	// ------------------------------------------------------------------ formatting
	const lang = document.documentElement.lang || "en";
	const currency = () => (B.settings && B.settings.currency) || "OMR";
	const nf = {};
	cp.money = function (v, cur) {
		cur = cur || currency();
		const key = cur;
		try {
			nf[key] = nf[key] || new Intl.NumberFormat(lang, { style: "currency", currency: cur, minimumFractionDigits: cur === "OMR" || cur === "KWD" || cur === "BHD" ? 3 : 2 });
			return nf[key].format(Number(v) || 0);
		} catch (e) {
			return (Number(v) || 0).toFixed(2) + " " + cur;
		}
	};
	cp.qty = function (v) {
		const n = Number(v) || 0;
		return new Intl.NumberFormat(lang, { maximumFractionDigits: 3 }).format(n);
	};
	cp.compact = function (v) {
		const n = Number(v) || 0;
		return new Intl.NumberFormat(lang, { notation: Math.abs(n) >= 100000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(n);
	};
	function toDate(v) {
		if (!v) return null;
		if (v instanceof Date) return v;
		const s = String(v);
		return new Date(s.length <= 10 ? s + "T00:00:00" : s.replace(" ", "T"));
	}
	cp.toDate = toDate;
	cp.date = function (v, opts) {
		const d = toDate(v);
		if (!d || isNaN(d)) return "";
		return d.toLocaleDateString(lang, opts || { day: "numeric", month: "short", year: "numeric" });
	};
	cp.datetime = function (v) {
		const d = toDate(v);
		if (!d || isNaN(d)) return "";
		return d.toLocaleString(lang, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
	};
	cp.ago = function (v) {
		const d = toDate(v);
		if (!d) return "";
		const s = (Date.now() - d.getTime()) / 1000;
		if (s < 60) return __("just now");
		if (s < 3600) return __("{0} min ago", [Math.floor(s / 60)]);
		if (s < 86400) return __("{0} h ago", [Math.floor(s / 3600)]);
		if (s < 86400 * 7) return __("{0} d ago", [Math.floor(s / 86400)]);
		return cp.date(d);
	};
	cp.today = function () {
		const d = new Date();
		return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
	};
	cp.daysFrom = function (v) {
		const d = toDate(v);
		if (!d) return null;
		const t = toDate(cp.today());
		return Math.round((d - t) / 86400000);
	};

	// ------------------------------------------------------------------ status badges
	const TONES = {
		blue: ["Active", "Open", "Scheduled", "Submitted", "To Deliver and Bill", "To Bill", "To Deliver", "Awaiting Contract", "Ordered", "Pickup requested", "New"],
		teal: ["On Hire", "In Progress", "Delivered", "Received", "Pickup being arranged", "Partly Delivered", "In Review"],
		good: ["Completed", "Paid", "Returned", "Closed", "Approved", "Quoted"],
		warn: ["Off Hired", "Unpaid", "Partly Paid", "Inspection Pending", "Returned, inspection pending", "Ending soon", "Partially Returned", "Pending"],
		bad: ["Overdue", "Rejected", "Cancelled", "Expired", "Lost"],
		violet: ["Credit note", "Refund", "Return"],
	};
	const TONE = {};
	for (const [t, list] of Object.entries(TONES)) for (const s of list) TONE[s] = t;
	cp.badge = function (text, tone) {
		return el("span", { class: "cp-badge is-" + (tone || TONE[text] || "plain"), text: __(text) });
	};

	// ------------------------------------------------------------------ links and buttons
	cp.href = (route) => cp.base + "/" + String(route || "").replace(/^\/+/, "");
	cp.link = function (route, text, attrs) {
		return el("a", Object.assign({ href: cp.href(route), "data-nav": "1" }, attrs || {}), text);
	};
	cp.btn = function (text, onclick, opts) {
		opts = opts || {};
		const b = el(opts.href ? "a" : "button", { class: "cp-btn" + (opts.primary ? " cp-btn--primary" : "") + (opts.danger ? " cp-btn--danger" : "") + (opts.ghost ? " cp-btn--ghost" : "") + (opts.sm ? " cp-btn--sm" : ""),
			type: opts.href ? null : "button", href: opts.href || null, "data-nav": opts.href && !opts.external ? "1" : null, target: opts.target || null,
			"aria-label": opts.label || null, title: opts.title || null },
			opts.icon ? icon(opts.icon, "cp-i--sm") : null, text);
		if (onclick) {
			b.addEventListener("click", async (e) => {
				if (b.disabled) return;
				if (opts.href) return;
				b.disabled = true;
				try {
					await onclick(e);
				} catch (err) {
					cp.toast(err.message, "bad");
				} finally {
					b.disabled = false;
				}
			});
		}
		return b;
	};
	cp.pdfBtn = function (doctype, name, label) {
		return el("a", { class: "cp-btn cp-btn--sm", href: cp.pdf(doctype, name), target: "_blank", rel: "noopener" }, icon("download", "cp-i--sm"), label || __("PDF"));
	};

	// ------------------------------------------------------------------ toasts
	cp.toast = function (msg, kind) {
		let box = document.querySelector(".cp-toasts");
		if (!box) document.body.appendChild((box = el("div", { class: "cp-toasts", role: "status", "aria-live": "polite" })));
		const t = el("div", { class: "cp-toast is-" + (kind || "ok") }, icon(kind === "bad" ? "circle-alert" : "circle-check"), el("span", { text: msg }));
		box.appendChild(t);
		setTimeout(() => t.remove(), kind === "bad" ? 7000 : 4000);
	};

	// ------------------------------------------------------------------ modal and confirm
	cp.modal = function (title, body, actions, opts) {
		opts = opts || {};
		const prev = document.activeElement;
		const close = () => {
			ov.remove();
			document.removeEventListener("keydown", onKey);
			if (prev && prev.focus) prev.focus();
		};
		const onKey = (e) => e.key === "Escape" && close();
		const foot = actions && actions.length ? el("div", { class: "cp-modal__foot" }, actions.map((a) => cp.btn(a.label, async () => {
			const r = await a.action(close);
			if (r !== false && !a.keep) close();
		}, { primary: a.primary, danger: a.danger }))) : null;
		const box = el("div", { class: "cp-modal " + (opts.cls || ""), role: "dialog", "aria-modal": "true", "aria-label": title },
			title ? el("div", { class: "cp-modal__head" }, el("h2", { text: title }), el("button", { class: "cp-iconbtn", type: "button", "aria-label": __("Close"), onclick: close }, icon("x"))) : null,
			el("div", { class: "cp-modal__body" }, body), foot);
		const ov = el("div", { class: "cp-overlay", onclick: (e) => e.target === ov && close() }, box);
		document.body.appendChild(ov);
		document.addEventListener("keydown", onKey);
		setTimeout(() => {
			const f = box.querySelector("input, textarea, select, button:not(.cp-iconbtn)");
			if (f) f.focus();
		}, 20);
		return { close, box };
	};
	cp.confirm = function (title, text, label, danger) {
		return new Promise((resolve) => {
			const m = cp.modal(title, el("p", { text, style: { margin: 0 } }), [
				{ label: __("Keep it"), action: () => resolve(false) },
				{ label, primary: !danger, danger, action: () => resolve(true) },
			]);
			m.box.parentNode.addEventListener("click", (e) => e.target === m.box.parentNode && resolve(false));
		});
	};

	// ------------------------------------------------------------------ popover menus
	cp.popover = function (anchor, content, opts) {
		opts = opts || {};
		document.querySelectorAll(".cp-pop").forEach((p) => p._close && p._close());
		const pop = el("div", { class: "cp-pop " + (opts.cls || ""), role: opts.role || "menu" }, content);
		document.body.appendChild(pop);
		const r = anchor.getBoundingClientRect();
		const w = pop.offsetWidth;
		pop.style.top = r.bottom + 6 + "px";
		pop.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.right - w)) + "px";
		const close = () => {
			pop.remove();
			document.removeEventListener("mousedown", out, true);
			document.removeEventListener("keydown", key);
			anchor.setAttribute("aria-expanded", "false");
		};
		const out = (e) => !pop.contains(e.target) && !anchor.contains(e.target) && close();
		const key = (e) => e.key === "Escape" && (close(), anchor.focus());
		setTimeout(() => {
			document.addEventListener("mousedown", out, true);
			document.addEventListener("keydown", key);
		});
		pop.addEventListener("click", (e) => e.target.closest("a, .cp-pop__item") && close());
		anchor.setAttribute("aria-expanded", "true");
		pop._close = close;
		return pop;
	};

	// ------------------------------------------------------------------ page pieces
	cp.pageHead = function (title, sub, actions) {
		return el("div", { class: "cp-pagehead" }, el("div", {}, el("h1", { text: title }), sub ? el("p", { text: sub }) : null),
			actions && actions.length ? el("div", { class: "cp-pagehead__actions" }, actions) : null);
	};
	cp.card = function (title, body, opts) {
		opts = opts || {};
		return el("section", { class: "cp-card " + (opts.cls || "") },
			title ? el("div", { class: "cp-card__head" }, el("div", {}, el("h2", { text: title }), opts.sub ? el("p", { text: opts.sub }) : null), opts.action || null) : null,
			el("div", { class: "cp-card__body" + (opts.flush ? " cp-card__body--flush" : "") }, body));
	};
	cp.empty = function (title, text, action, iconName) {
		return el("div", { class: "cp-empty" }, el("div", { class: "cp-empty__icon" }, icon(iconName || "inbox")), el("h3", { text: title }), text ? el("p", { text }) : null, action || null);
	};
	cp.errorBox = function (err, retry) {
		const forbidden = err && (err.status === 403 || err.type === "PermissionError" || err.type === "DoesNotExistError" || err.status === 404);
		return el("div", { class: "cp-error" }, el("div", { class: "cp-empty__icon" }, icon(forbidden ? "lock" : "cloud-off")),
			el("h2", { text: forbidden ? __("Not available") : __("This page could not load") }),
			el("p", { text: (err && err.message) || __("Something went wrong.") }),
			forbidden ? cp.btn(__("Back to dashboard"), null, { href: cp.href("") }) : cp.btn(__("Try again"), retry, { primary: true, icon: "refresh-cw" }));
	};
	cp.skeleton = function (rows) {
		return el("div", { class: "cp-card", style: { padding: "18px" }, "aria-busy": "true", "aria-label": __("Loading") },
			Array.from({ length: rows || 6 }, (_, i) => el("div", { class: "cp-skel", style: { height: i ? "14px" : "22px", width: i ? 60 + ((i * 37) % 40) + "%" : "30%", margin: "12px 0" } })));
	};
	cp.dashSkeleton = function () {
		return el("div", { "aria-busy": "true" }, el("div", { class: "cp-skel", style: { height: "150px", borderRadius: "12px", marginBottom: "18px" } }),
			el("div", { class: "cp-kpis" }, Array.from({ length: 8 }, () => el("div", { class: "cp-skel", style: { height: "104px", borderRadius: "10px" } }))),
			el("div", { class: "cp-skel", style: { height: "300px", borderRadius: "10px" } }));
	};
	cp.facts = function (pairs) {
		return el("dl", { class: "cp-facts cp-dl" }, pairs.filter((p) => p && p[1] != null && p[1] !== "").map(([k, v]) => el("div", { class: "cp-fact" }, el("dt", { text: k }), el("dd", {}, v))));
	};
	cp.tabs = function (options, value, onChange, label) {
		return el("div", { class: "cp-tabs", role: "tablist", "aria-label": label || null }, options.map(([v, t]) => el("button", { type: "button", role: "tab",
			"aria-selected": String(v === value), class: v === value ? "is-on" : "", text: t, onclick: () => v !== value && onChange(v) })));
	};
	cp.progress = function (parts, total) {
		const t = total || parts.reduce((s, p) => s + (p.value || 0), 0) || 1;
		return el("div", { class: "cp-progress", role: "img", "aria-label": parts.map((p) => p.label + " " + cp.qty(p.value)).join(", ") },
			parts.filter((p) => p.value > 0).map((p) => el("i", { style: { width: (100 * p.value) / t + "%", background: p.color }, title: p.label + ": " + cp.qty(p.value) })));
	};
	cp.timeline = function (events) {
		if (!events.length) return cp.empty(__("No activity yet"), null, null, "history");
		return el("ol", { class: "cp-timeline" }, events.map((e) => el("li", {}, el("span", { class: "cp-timeline__dot" }, icon(e.icon || "circle")),
			el("div", {}, el("b", {}, e.route ? cp.link(e.route, e.title) : e.title), el("span", { text: [cp.date(e.date), e.detail].filter(Boolean).join(", ") })))));
	};
	cp.dateChip = function (v, late) {
		const d = toDate(v);
		return el("span", { class: "cp-date" + (late ? " is-bad" : "") }, el("small", { text: d ? d.toLocaleDateString(lang, { month: "short" }) : "" }),
			el("b", { text: d ? d.getDate() : "" }));
	};

	// ------------------------------------------------------------------ data table: server-paged, searchable, filterable
	/**
	 * cp.dataTable({
	 *   method, args, columns: [{label, render(row), num, sort}], href(row), mobile(row) -> {title, badge, meta:[[k,v]]},
	 *   search: placeholder, filters: [{name, label, options:[[v,t]]} | {name, type:"date", label}], tabs: {name, options},
	 *   empty: {title, text, action}, page_length, onData(data), footer(data)
	 * })
	 * State lives in the URL query so back / forward and shared links keep filters.
	 */
	cp.dataTable = function (spec) {
		const q = new URLSearchParams(location.search);
		const state = { page: Number(q.get("page")) || 1, search: q.get("q") || "", sort: q.get("sort") || spec.defaultSort || "" };
		for (const f of spec.filters || []) state[f.name] = q.get(f.name) || f.default || "";
		if (spec.tabs) state[spec.tabs.name] = q.get(spec.tabs.name) || spec.tabs.default || spec.tabs.options[0][0];
		const wrap = el("section", { class: "cp-card cp-has-mlist" });
		const body = el("div", {});
		const syncUrl = () => {
			const u = new URLSearchParams(location.search);
			const set = (k, v, d) => (v && v !== d ? u.set(k, v) : u.delete(k));
			set("page", state.page > 1 ? String(state.page) : "");
			set("q", state.search);
			set("sort", state.sort, spec.defaultSort);
			for (const f of spec.filters || []) set(f.name, state[f.name], f.default);
			if (spec.tabs) set(spec.tabs.name, state[spec.tabs.name], spec.tabs.default || spec.tabs.options[0][0]);
			history.replaceState(history.state, "", location.pathname + (u.toString() ? "?" + u : ""));
		};
		const toolbar = el("div", { class: "cp-toolbar" });
		if (spec.tabs) {
			const renderTabs = () => cp.tabs(spec.tabs.options, state[spec.tabs.name], (v) => {
				state[spec.tabs.name] = v;
				state.page = 1;
				tabsBox.replaceChildren(renderTabs());
				load();
			}, spec.tabs.label);
			const tabsBox = el("div", {}, renderTabs());
			toolbar.appendChild(tabsBox);
		}
		if (spec.search) {
			const input = el("input", { type: "search", value: state.search, placeholder: spec.search, "aria-label": spec.search });
			let t;
			input.addEventListener("input", () => {
				clearTimeout(t);
				t = setTimeout(() => {
					state.search = input.value.trim();
					state.page = 1;
					load();
				}, 300);
			});
			toolbar.appendChild(el("label", { class: "cp-field-search" }, icon("search", "cp-i--sm"), input));
		}
		for (const f of spec.filters || []) {
			let ctl;
			if (f.type === "date") {
				ctl = el("input", { type: "date", class: "cp-input", value: state[f.name], "aria-label": f.label, title: f.label });
			} else {
				ctl = el("select", { class: "cp-select", "aria-label": f.label }, el("option", { value: "", text: f.label }),
					(f.options || []).map(([v, t]) => el("option", { value: v, text: t, selected: v === state[f.name] })));
			}
			ctl.addEventListener("change", () => {
				state[f.name] = ctl.value;
				state.page = 1;
				load();
			});
			toolbar.appendChild(ctl);
		}
		if (toolbar.childNodes.length) wrap.appendChild(toolbar);
		wrap.appendChild(body);
		let seq = 0;
		async function load() {
			syncUrl();
			const my = ++seq;
			body.replaceChildren(el("div", { style: { padding: "6px 18px" } }, Array.from({ length: 5 }, () => el("div", { class: "cp-skel", style: { height: "16px", margin: "16px 0" } }))));
			const args = Object.assign({}, spec.args || {}, { page: state.page, page_length: spec.page_length || 20, search: state.search, sort: state.sort });
			for (const f of spec.filters || []) args[f.param || f.name] = state[f.name];
			if (spec.tabs) args[spec.tabs.param || spec.tabs.name] = state[spec.tabs.name];
			let data;
			try {
				data = await cp.api(spec.method, args);
			} catch (e) {
				if (my === seq) body.replaceChildren(cp.errorBox(e, load));
				return;
			}
			if (my !== seq) return;
			if (spec.onData) spec.onData(data);
			render(data);
		}
		function render(data) {
			const rows = data.rows || [];
			if (!rows.length) {
				const filtered = state.search || (spec.filters || []).some((f) => state[f.name] && state[f.name] !== f.default);
				body.replaceChildren(filtered ? cp.empty(__("Nothing matches"), __("Try another search or clear the filters."), cp.btn(__("Clear filters"), () => {
					state.search = "";
					for (const f of spec.filters || []) state[f.name] = f.default || "";
					state.page = 1;
					const s = wrap.querySelector(".cp-field-search input");
					if (s) s.value = "";
					wrap.querySelectorAll(".cp-toolbar select, .cp-toolbar input[type=date]").forEach((x) => (x.value = ""));
					load();
				}), "search-x") : cp.empty(spec.empty.title, spec.empty.text, spec.empty.action, spec.empty.icon));
				return;
			}
			const head = el("tr", {}, spec.columns.map((c) => {
				if (!c.sort) return el("th", { class: c.num ? "cp-num" : null, scope: "col", text: c.label });
				const on = state.sort === c.sort || state.sort === c.sort + "_desc";
				return el("th", { class: c.num ? "cp-num" : null, scope: "col", "aria-sort": on ? "ascending" : "none" }, el("button", { type: "button", onclick: () => {
					state.sort = state.sort === c.sort ? "" : c.sort;
					load();
				} }, c.label, icon(on ? "arrow-up" : "arrow-up-down", "cp-i--sm")));
			}));
			const tbody = el("tbody", {}, rows.map((r) => {
				const href = spec.href ? spec.href(r) : null;
				const tr = el("tr", { class: href ? "is-link" : null }, spec.columns.map((c) => el("td", { class: c.num ? "cp-num" : null }, c.render(r))));
				if (href) {
					tr.addEventListener("click", (e) => {
						if (e.target.closest("a, button")) return;
						cp.go(href);
					});
				}
				return tr;
			}));
			const foot = spec.footer ? spec.footer(data) : null;
			const table = el("div", { class: "cp-tablewrap" }, el("table", { class: "cp-table" }, el("thead", {}, head), tbody, foot));
			const mobile = el("div", { class: "cp-mlist" }, rows.map((r) => {
				const m = spec.mobile ? spec.mobile(r) : { title: spec.columns[0].render(r) };
				const href = spec.href ? spec.href(r) : null;
				return el(href ? "a" : "div", { class: "cp-mcard", href: href ? cp.href(href) : null, "data-nav": href ? "1" : null },
					el("div", { class: "cp-mcard__top" }, el("b", {}, m.title), m.badge || null),
					m.meta && m.meta.length ? el("dl", { class: "cp-mcard__meta" }, m.meta.filter((x) => x && x[1] != null && x[1] !== "").map(([k, v]) => el("div", {}, el("dt", { text: k }), el("dd", {}, v)))) : null);
			}));
			const pages = data.pages || 1;
			const from = (data.page - 1) * data.page_length + 1;
			const pager = el("div", { class: "cp-pager" }, el("span", { text: __("{0}–{1} of {2}", [from, from + rows.length - 1, data.total]) }),
				pages > 1 ? el("div", { class: "cp-pager__btns" },
					cp.btn(__("Previous"), () => { state.page--; load(); window.scrollTo({ top: 0 }); }, { sm: true, icon: "chevron-left" }),
					el("span", { text: __("Page {0} of {1}", [data.page, pages]) }),
					cp.btn(__("Next"), () => { state.page++; load(); window.scrollTo({ top: 0 }); }, { sm: true, icon: "chevron-right" })) : null);
			const prev = pager.querySelector("button");
			if (prev && data.page <= 1) prev.disabled = true;
			const btns = pager.querySelectorAll("button");
			if (btns.length > 1 && data.page >= pages) btns[btns.length - 1].disabled = true;
			body.replaceChildren(table, mobile, pager);
		}
		load();
		wrap.reload = load;
		return wrap;
	};

	// ------------------------------------------------------------------ charts (SVG, no library)
	cp.tip = function (evt, text) {
		let t = document.querySelector(".cp-tip");
		if (!text) return t && t.remove();
		if (!t) document.body.appendChild((t = el("div", { class: "cp-tip", role: "tooltip" })));
		t.textContent = text;
		t.style.left = Math.min(window.innerWidth - t.offsetWidth - 8, evt.clientX + 12) + "px";
		t.style.top = evt.clientY - 36 + "px";
	};
	/** Grouped bars over categories: series [{label, color, values[]}], one axis. */
	cp.barChart = function (labels, series, opts) {
		opts = opts || {};
		const W = 640, H = opts.height || 220, L = 40, R = 8, T = 10, Bm = 26;
		const max = Math.max(1, ...series.flatMap((s) => s.values));
		const step = niceStep(max);
		const top = Math.ceil(max / step) * step;
		const g = svg("svg", { class: "cp-chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.label || "" });
		for (let v = 0; v <= top + 1e-9; v += step) {
			const y = T + (H - T - Bm) * (1 - v / top);
			g.appendChild(svg("line", { x1: L, x2: W - R, y1: y, y2: y, stroke: v ? "#edf0f4" : "#cfd7e2", "stroke-width": 1 }));
			g.appendChild(svg("text", { x: L - 8, y: y + 4, "text-anchor": "end" }, cp.compact(v)));
		}
		const band = (W - L - R) / labels.length;
		const bw = Math.min(26, (band * 0.62) / series.length);
		labels.forEach((lab, i) => {
			const x0 = L + band * i + (band - bw * series.length - 2 * (series.length - 1)) / 2;
			series.forEach((s, j) => {
				const v = s.values[i] || 0;
				const h = ((H - T - Bm) * v) / top;
				const x = x0 + j * (bw + 2);
				const bar = svg("path", { d: roundTop(x, H - Bm - h, bw, h), fill: s.color, tabindex: "0", "aria-label": `${lab}, ${s.label}: ${cp.qty(v)}` });
				bar.addEventListener("mousemove", (e) => cp.tip(e, `${lab}  ${s.label}: ${cp.qty(v)}`));
				bar.addEventListener("mouseleave", () => cp.tip());
				g.appendChild(bar);
			});
			g.appendChild(svg("text", { x: L + band * i + band / 2, y: H - 8, "text-anchor": "middle" }, lab));
		});
		return g;
	};
	function roundTop(x, y, w, h) {
		if (h <= 0) return "";
		const r = Math.min(4, w / 2, h);
		return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
	}
	function niceStep(max) {
		const raw = max / 4;
		const p = Math.pow(10, Math.floor(Math.log10(raw)));
		const n = raw / p;
		return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
	}
	cp.legend = function (items) {
		return el("div", { class: "cp-legend" }, items.map((i) => el("span", {}, el("i", { style: { background: i.color } }), i.label)));
	};
	cp.hbars = function (rows, opts) {
		opts = opts || {};
		const max = Math.max(1, ...rows.map((r) => r.value));
		return el("div", {}, rows.map((r) => el(r.route ? "a" : "div", { class: "cp-hbar", href: r.route ? cp.href(r.route) : null, "data-nav": r.route ? "1" : null, style: { color: "inherit" } },
			el("span", { class: "cp-hbar__name", text: r.label, title: r.label }),
			el("span", { class: "cp-hbar__track" }, el("i", { style: { width: (100 * r.value) / max + "%", background: opts.color || null } })),
			el("span", { class: "cp-num", style: { textAlign: "right", fontWeight: 600 }, text: cp.qty(r.value) }))));
	};

	cp.COLORS = { blue: "#1f5fd6", teal: "#0b8f8a", amber: "#c98a1d", slate: "#8a99ad", violet: "#5b4bc4", red: "#c2410c" };
})();
