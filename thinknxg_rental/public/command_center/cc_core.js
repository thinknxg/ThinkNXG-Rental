// thinkNXG Rental Command Center: shared helpers (DOM, server calls, formatting, dialogs, toasts).
// Every number on screen comes from a server call; nothing is computed or stored here except what
// one viewer's browser remembers for convenience (sidebar state, recent and favourite documents).
(function () {
	const cc = (window.cc = window.cc || {});
	const boot = (cc.boot = window.cc_boot || {});
	cc.base = "/rental/admin";

	// ------------------------------------------------------------------ translation
	// Labels from the server arrive translated; this formats the few strings written here.
	cc.__ = window.__ = function (text, args) {
		let s = String(text ?? "");
		(args || []).forEach((a, i) => (s = s.split("{" + i + "}").join(a)));
		return s;
	};
	const __ = cc.__;

	// ------------------------------------------------------------------ DOM
	// Pages hand over optional parts (a panel only some roles see, a row with no extra line): this page
	// is the Command Center alone, so empty parts are skipped everywhere instead of showing "null".
	const replace = Element.prototype.replaceChildren;
	Element.prototype.replaceChildren = function (...nodes) {
		return replace.apply(this, nodes.flat().filter((n) => n !== null && n !== undefined && n !== false && n !== ""));
	};
	cc.el = function el(tag, attrs, ...children) {
		const svgTags = ["svg", "path", "line", "rect", "circle", "g", "text", "polyline", "polygon", "use", "title"];
		const node = svgTags.includes(tag) ? document.createElementNS("http://www.w3.org/2000/svg", tag) : document.createElement(tag);
		Object.entries(attrs || {}).forEach(([k, v]) => {
			if (v === null || v === undefined || v === false) return;
			if (k === "text") node.textContent = v;
			else if (k === "html") node.innerHTML = v;
			else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
			else if (k === "dataset") Object.assign(node.dataset, v);
			else node.setAttribute(k, v === true ? "" : v);
		});
		children.flat(Infinity).forEach((c) => {
			if (c === null || c === undefined || c === false) return;
			node.append(c instanceof Node ? c : document.createTextNode(String(c)));
		});
		return node;
	};
	const el = cc.el;
	cc.icon = function (name, cls) {
		const svg = el("svg", { class: "cc-i" + (cls ? " " + cls : ""), "aria-hidden": "true" });
		svg.append(el("use", { href: "/assets/frappe/icons/lucide.svg#icon-" + name }));
		return svg;
	};
	cc.debounce = (fn, ms) => {
		let t;
		return (...a) => {
			clearTimeout(t);
			t = setTimeout(() => fn(...a), ms);
		};
	};
	cc.esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

	// ------------------------------------------------------------------ per-viewer storage
	cc.store = {
		get(key, fallback) {
			try {
				const v = localStorage.getItem("cc:" + (boot.user || {}).name + ":" + key);
				return v === null ? fallback : JSON.parse(v);
			} catch (e) {
				return fallback;
			}
		},
		set(key, value) {
			try {
				localStorage.setItem("cc:" + (boot.user || {}).name + ":" + key, JSON.stringify(value));
			} catch (e) {
				/* private mode: the setting lasts for this page only */
			}
		},
	};

	// ------------------------------------------------------------------ server
	function serverMessages(data) {
		const out = [];
		try {
			JSON.parse(data._server_messages || "[]").forEach((m) => {
				const o = typeof m === "string" ? JSON.parse(m) : m;
				if (o && o.message) out.push({ text: String(o.message), indicator: o.indicator, title: o.title });
			});
		} catch (e) {
			/* not JSON */
		}
		return out;
	}
	const strip = (html) => {
		const d = document.createElement("div");
		d.innerHTML = html;
		return (d.textContent || "").trim();
	};
	cc.strip = strip;

	cc.call = async function (method, args, opts) {
		opts = opts || {};
		const post = !!opts.post;
		let url = "/api/method/" + method;
		const init = { method: post ? "POST" : "GET", credentials: "same-origin", headers: { Accept: "application/json", "X-Frappe-CSRF-Token": window.csrf_token || "" } };
		const clean = {};
		Object.entries(args || {}).forEach(([k, v]) => {
			if (v === undefined || v === null) return;
			clean[k] = typeof v === "object" ? JSON.stringify(v) : v;
		});
		if (post) {
			init.headers["Content-Type"] = "application/json";
			init.body = JSON.stringify(clean);
		} else {
			const q = new URLSearchParams(clean).toString();
			if (q) url += "?" + q;
		}
		let res, data;
		try {
			res = await fetch(url, init);
		} catch (e) {
			cc.toast(__("Could not reach the server. Check your connection and try again."), "bad");
			throw e;
		}
		try {
			data = await res.json();
		} catch (e) {
			data = {};
		}
		const messages = serverMessages(data);
		if (!res.ok || data.exc) {
			if (res.status === 403 && /Guest|session|Login/i.test(JSON.stringify(data).slice(0, 2000)) && (data.session_expired || data.exc_type === "PermissionError" && !boot.user)) {
				window.location.href = "/login?redirect-to=" + encodeURIComponent(location.pathname + location.search);
			}
			const text = messages.map((m) => strip(m.text)).filter(Boolean);
			if (!text.length) {
				if (res.status === 403) text.push(__("You are not permitted to do this."));
				else if (res.status === 404) text.push(__("Not found. It may have been deleted or renamed."));
				else if (data.exc_type) text.push(data.exc_type.replace(/Error$/, " error"));
				else text.push(__("Something went wrong on the server ({0}).", [res.status]));
			}
			// a refused read shows as the page itself; a refused action as a toast
			if (!opts.silent && !(res.status === 403 && !post)) cc.toast(text, "bad");
			const err = new Error(text.join(" "));
			err.status = res.status;
			err.exc_type = data.exc_type;
			throw err;
		}
		// msgprint on success (a validation note, "Created ..."): show it
		if (messages.length && !opts.silent) cc.toast(messages.map((m) => strip(m.text)), messages.some((m) => m.indicator === "red") ? "bad" : "");
		return data.message;
	};
	cc.api = (name, args, opts) => cc.call("thinknxg_rental.command_center.api." + name, args, opts);

	// ------------------------------------------------------------------ formatting
	const lang = document.documentElement.lang || undefined;
	const currency = () => boot.currency || "";
	cc.num = (v, digits) => {
		if (v === null || v === undefined || v === "") return "";
		const n = Number(v);
		if (!isFinite(n)) return String(v);
		const d = digits ?? (Number.isInteger(n) ? 0 : 2);
		return n.toLocaleString(lang, { minimumFractionDigits: d, maximumFractionDigits: d });
	};
	cc.qty = (v) => cc.num(Math.round(Number(v || 0) * 100) / 100);
	cc.money = (v, cur, compact) => {
		if (v === null || v === undefined || v === "") return "";
		const n = Number(v) || 0;
		const c = cur || currency();
		if (compact && Math.abs(n) >= 10000) {
			const s = n.toLocaleString(lang, { notation: "compact", maximumFractionDigits: 1 });
			return c ? c + " " + s : s;
		}
		const s = n.toLocaleString(lang, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
		return c ? c + " " + s : s;
	};
	cc.compact = (v) => Number(v || 0).toLocaleString(lang, { notation: "compact", maximumFractionDigits: 1 });
	const fmtPattern = (boot.date_format || "dd-mm-yyyy").toLowerCase();
	cc.date = (v) => {
		if (!v) return "";
		const m = String(v).match(/^(\d{4})-(\d{2})-(\d{2})/);
		if (!m) return String(v);
		return fmtPattern.replace("yyyy", m[1]).replace("mm", m[2]).replace("dd", m[3]);
	};
	cc.datetime = (v) => {
		if (!v) return "";
		const d = new Date(String(v).replace(" ", "T"));
		if (isNaN(d)) return String(v);
		return cc.date(String(v).slice(0, 10)) + " " + d.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" });
	};
	cc.ago = (v) => {
		if (!v) return "";
		const d = new Date(String(v).replace(" ", "T"));
		const s = (Date.now() - d.getTime()) / 1000;
		if (isNaN(s)) return "";
		if (s < 60) return __("just now");
		if (s < 3600) return __("{0} min ago", [Math.floor(s / 60)]);
		if (s < 86400) return __("{0} h ago", [Math.floor(s / 3600)]);
		if (s < 86400 * 30) return __("{0} d ago", [Math.floor(s / 86400)]);
		return cc.date(String(v).slice(0, 10));
	};
	cc.days = (n) => (n === 1 ? __("1 day") : __("{0} days", [cc.num(n)]));
	const NUM = (cc.NUM = ["Int", "Float", "Currency", "Percent"]);
	cc.fmt = (value, fieldtype, cur) => {
		if (value === null || value === undefined || value === "") return "";
		if (fieldtype === "Currency") return cc.money(value, cur);
		if (fieldtype === "Percent") return cc.num(value, 1) + "%";
		if (NUM.includes(fieldtype)) return cc.num(value);
		if (fieldtype === "Date") return cc.date(value);
		if (fieldtype === "Datetime") return cc.datetime(value);
		if (fieldtype === "Check") return Number(value) ? __("Yes") : __("No");
		return String(value);
	};

	// ------------------------------------------------------------------ status
	const TONES = {
		ok: ["Completed", "Paid", "Billed", "Converted", "Within Contract", "Approved", "Closed", "Invoiced", "Received", "Returned", "Settled", "Available", "Delivered", "Submitted"],
		info: ["On Hire", "Active", "In Progress", "Open", "Ordered", "To Deliver", "To Deliver and Bill", "To Bill", "Replied", "Quotation", "Opportunity", "Interested", "Lead", "Partly Delivered"],
		warn: ["Draft", "Pending", "To Invoice", "Unpaid", "In Excess", "Off Hired", "Reserved", "Partly Paid", "Partly Billed", "Due", "Hold", "Partly Returned", "Under Inspection", "Inspection Pending", "Partially Reserved", "Not Reserved", "Partially Received"],
		bad: ["Overdue", "Rejected", "Lost", "Do Not Contact", "Expired", "Short", "Lost Quotation", "Damaged", "Beyond Repair"],
	};
	cc.tone = (status) => {
		for (const [tone, list] of Object.entries(TONES)) if (list.includes(status)) return tone;
		return "";
	};
	cc.pill = (status, tone) => (status ? el("span", { class: "cc-pill", "data-tone": tone ?? cc.tone(status), text: __(status) }) : null);

	// ------------------------------------------------------------------ toasts
	let toasts;
	cc.toast = function (text, tone, ms) {
		const lines = (Array.isArray(text) ? text : [text]).filter(Boolean);
		if (!lines.length) return;
		if (!toasts) document.body.append((toasts = el("div", { class: "cc-toasts", role: "status", "aria-live": "polite" })));
		const node = el("div", { class: "cc-toast", "data-tone": tone || "" },
			cc.icon(tone === "bad" ? "circle-x" : tone === "ok" ? "circle-check" : "info"),
			el("div", {}, lines.map((l) => el("p", { text: l }))),
			el("button", { type: "button", "aria-label": __("Dismiss"), onclick: () => node.remove() }, cc.icon("x", "cc-i--sm")));
		toasts.append(node);
		setTimeout(() => node.remove(), ms || (tone === "bad" ? 9000 : 4500));
	};

	// ------------------------------------------------------------------ dialogs
	let openLayer = null;
	cc.closeLayer = () => {
		if (openLayer) openLayer();
		openLayer = null;
	};
	cc.layer = function (nodes, onclose) {
		cc.closeLayer();
		const prev = document.activeElement;
		const scrim = el("div", { class: "cc-scrim" });
		const close = () => {
			scrim.remove();
			nodes.forEach((n) => n.remove());
			document.removeEventListener("keydown", key);
			onclose && onclose();
			if (prev && prev.focus) prev.focus();
		};
		const key = (e) => {
			if (e.key === "Escape") {
				e.preventDefault();
				cc.closeLayer();
			}
		};
		scrim.addEventListener("click", () => cc.closeLayer());
		document.addEventListener("keydown", key);
		document.body.append(scrim, ...nodes);
		openLayer = close;
		return close;
	};
	cc.dialog = function ({ title, body, actions, wide }) {
		const box = el("div", { class: "cc-dialog", role: "dialog", "aria-modal": "true", "aria-label": title, style: wide ? "width:min(760px,calc(100vw - 24px))" : null },
			el("header", {}, el("h2", { text: title }), el("button", { type: "button", class: "cc-iconbtn", "aria-label": __("Close"), onclick: () => cc.closeLayer() }, cc.icon("x"))),
			el("div", { class: "cc-dialog-body" }, body),
			actions && actions.length ? el("footer", {}, actions) : null);
		cc.layer([box]);
		const first = box.querySelector("input, select, textarea, .cc-btn--primary");
		if (first) first.focus();
		return box;
	};
	cc.confirm = (title, message, okLabel, danger) =>
		new Promise((resolve) => {
			let ok = false;
			const yes = el("button", { type: "button", class: "cc-btn " + (danger ? "cc-btn--danger" : "cc-btn--primary"), text: okLabel || __("Continue"), onclick: () => { ok = true; cc.closeLayer(); } });
			const no = el("button", { type: "button", class: "cc-btn cc-btn--ghost", text: __("Cancel"), onclick: () => cc.closeLayer() });
			cc.dialog({ title, body: el("p", { text: message }), actions: [no, yes] });
			const prevClose = openLayer;
			openLayer = () => {
				prevClose();
				resolve(ok);
			};
			yes.focus();
		});
	cc.prompt = (title, fields, okLabel) =>
		new Promise((resolve) => {
			const values = {};
			let ok = false;
			const body = el("div", { class: "cc-fields" }, fields.map((f) => {
				values[f.fieldname] = f.default ?? "";
				const id = "cc-p-" + f.fieldname;
				const input = f.fieldtype === "Small Text"
					? el("textarea", { id, oninput: (e) => (values[f.fieldname] = e.target.value) })
					: f.fieldtype === "Select"
						? el("select", { id, onchange: (e) => (values[f.fieldname] = e.target.value) }, (f.options || []).map((o) => el("option", { value: o.value ?? o, text: o.label ?? o })))
						: el("input", { id, type: f.fieldtype === "Date" ? "date" : "text", value: values[f.fieldname], oninput: (e) => (values[f.fieldname] = e.target.value) });
				if (f.fieldtype === "Small Text") input.value = values[f.fieldname];
				return el("div", { class: "cc-field cc-field--wide" }, el("label", { for: id, text: f.label }, f.reqd ? el("span", { class: "cc-req", text: " *" }) : null), input);
			}));
			const yes = el("button", { type: "button", class: "cc-btn cc-btn--primary", text: okLabel || __("Save"), onclick: () => {
				const missing = fields.find((f) => f.reqd && !String(values[f.fieldname] || "").trim());
				if (missing) return cc.toast(__("Fill in {0} first.", [missing.label]), "bad");
				ok = true;
				cc.closeLayer();
			} });
			cc.dialog({ title, body, actions: [el("button", { type: "button", class: "cc-btn cc-btn--ghost", text: __("Cancel"), onclick: () => cc.closeLayer() }), yes] });
			const prevClose = openLayer;
			openLayer = () => {
				prevClose();
				resolve(ok ? values : null);
			};
		});
	cc.popover = function (anchor, content, align) {
		const pop = el("div", { class: "cc-pop", role: "menu" }, content);
		const scrim = el("div", { style: "position:fixed;inset:0;z-index:55" });
		let closed = false;
		const close = () => {
			if (closed) return;
			closed = true;
			pop.remove();
			scrim.remove();
			document.removeEventListener("keydown", key);
			anchor.setAttribute("aria-expanded", "false");
		};
		const key = (e) => {
			if (e.key === "Escape") {
				close();
				anchor.focus();
			}
			if (["ArrowDown", "ArrowUp"].includes(e.key)) {
				const items = [...pop.querySelectorAll("a, button")];
				const i = items.indexOf(document.activeElement);
				const n = items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length];
				if (n) n.focus();
				e.preventDefault();
			}
		};
		scrim.addEventListener("click", close);
		pop.addEventListener("click", (e) => {
			if (e.target.closest("a, button.cc-menuitem")) close();
		});
		document.addEventListener("keydown", key);
		document.body.append(scrim, pop);
		const r = anchor.getBoundingClientRect();
		const w = pop.offsetWidth;
		const left = align === "left" ? r.left : r.right - w;
		pop.style.left = Math.max(12, Math.min(left, window.innerWidth - w - 12)) + "px";
		pop.style.top = Math.min(r.bottom + 6, window.innerHeight - pop.offsetHeight - 12) + "px";
		anchor.setAttribute("aria-expanded", "true");
		const first = pop.querySelector("a, button");
		if (first) first.focus();
		return close;
	};

	// ------------------------------------------------------------------ page parts
	cc.pagehead = function (title, description, actions, extra) {
		return el("div", { class: "cc-pagehead" },
			el("div", {}, el("h1", {}, title, extra || null), description ? el("p", { text: description }) : null),
			actions && actions.length ? el("div", { class: "cc-actions" }, actions) : null);
	};
	cc.panel = function (title, body, opts) {
		opts = opts || {};
		return el("section", { class: "cc-panel" + (opts.cls ? " " + opts.cls : ""), id: opts.id || null },
			title || opts.actions ? el("header", {}, title ? el("h2", { text: title }) : null, opts.actions ? el("div", { class: "cc-actions" }, opts.actions) : null, opts.note ? el("p", { text: opts.note }) : null) : null,
			el("div", { class: opts.flush ? "cc-panel-body cc-panel-body--flush" : "cc-panel-body" }, body));
	};
	// a page the server refused: say so plainly, with the server's reason
	cc.failure = (e) => e && e.status === 403
		? el("section", { class: "cc-panel" }, el("div", { class: "cc-empty" }, cc.icon("shield-alert"), el("b", { text: __("You do not have access to this") }),
			el("span", { text: e.message }), el("span", { text: __("Ask your System Manager for the role that gives access.") })))
		: el("div", { class: "cc-error", text: (e && e.message) || String(e) });
	cc.empty = (title, text, action) => el("div", { class: "cc-empty" }, cc.icon("inbox"), el("b", { text: title }), text ? el("span", { text }) : null, action || null);
	cc.skeleton = (rows) => el("div", { class: "cc-panel", style: "padding:18px" },
		Array.from({ length: rows || 6 }, (_, i) => el("span", { class: "cc-skel", style: `width:${[92, 76, 84, 64, 88, 70][i % 6]}%;margin:${i ? 14 : 0}px 0 0` })));
	cc.btn = (label, onclick, opts) => {
		opts = opts || {};
		const b = el(opts.href ? "a" : "button", { type: opts.href ? null : "button", href: opts.href || null, class: "cc-btn" + (opts.kind ? " cc-btn--" + opts.kind : "") + (opts.sm ? " cc-btn--sm" : ""), onclick: onclick || null, target: opts.target || null, rel: opts.target ? "noopener" : null, title: opts.title || null },
			opts.icon ? cc.icon(opts.icon, "cc-i--sm") : null, label);
		if (opts.href && !opts.target && opts.href.startsWith(cc.base)) b.addEventListener("click", (e) => cc.linkClick(e, opts.href));
		return b;
	};
	// a link inside the app: navigate without reloading
	cc.link = (route, text, cls) => {
		const href = route.startsWith("/") ? route : cc.base + "/" + route;
		const a = el("a", { href, class: cls || null }, text);
		if (href.startsWith(cc.base)) a.addEventListener("click", (e) => cc.linkClick(e, href));
		return a;
	};
	cc.linkClick = (e, href) => {
		if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		e.preventDefault();
		cc.go(href);
	};
	cc.target = (t) => (t && t.route ? cc.base + "/" + t.route : t && t.url ? t.url : null);
	cc.openTarget = (t, newTab) => {
		const href = cc.target(t);
		if (!href) return;
		if (newTab) window.open(href, "_blank", "noopener");
		else if (href.startsWith(cc.base)) cc.go(href);
		else window.location.href = href;
	};

	// ------------------------------------------------------------------ old portal addresses
	// The admin portal's engine (portal/entry.py) answers with /rental/admin/entry?type=...; open those here.
	cc.fromPortalUrl = function (url) {
		if (!url) return null;
		const u = new URL(url, location.origin);
		if (!u.pathname.startsWith(cc.base)) return u.pathname + u.search;
		const path = u.pathname.slice(cc.base.length).replace(/^\/+|\/+$/g, "");
		const q = new URLSearchParams(u.search);
		const routes = boot.routes || {};
		if (path === "entry" && q.get("type")) {
			const type = q.get("type");
			q.delete("type");
			const route = (routes.entries || {})[type] || "doc/" + type;
			const name = q.get("name");
			q.delete("name");
			q.delete("done");
			const rest = q.toString();
			return cc.base + "/" + route + "/" + (name ? encodeURIComponent(name) : "new") + (rest ? "?" + rest : "");
		}
		if (path === "entries" && q.get("type")) return cc.base + "/" + ((routes.entries || {})[q.get("type")] || "dashboard");
		if ((routes.legacy || {})[path]) return cc.base + "/" + routes.legacy[path];
		if (path === "contracts" && q.get("view") === "overdue") return cc.base + "/contracts?tab=1";
		return u.pathname + u.search;
	};

	// ------------------------------------------------------------------ recent and favourite documents (this browser only)
	cc.remember = function (doc) {
		const list = cc.store.get("recent", []).filter((d) => d.href !== doc.href);
		list.unshift(doc);
		cc.store.set("recent", list.slice(0, 12));
	};
	cc.favorites = () => cc.store.get("favorites", []);
	cc.toggleFavorite = function (doc) {
		let list = cc.favorites();
		const on = list.some((d) => d.href === doc.href);
		list = on ? list.filter((d) => d.href !== doc.href) : [doc, ...list].slice(0, 30);
		cc.store.set("favorites", list);
		return !on;
	};

	// ------------------------------------------------------------------ download a text file
	cc.download = function (filename, content, type) {
		const blob = new Blob(["﻿" + content], { type: type || "text/csv;charset=utf-8" });
		const a = el("a", { href: URL.createObjectURL(blob), download: filename });
		document.body.append(a);
		a.click();
		setTimeout(() => {
			URL.revokeObjectURL(a.href);
			a.remove();
		}, 500);
	};
})();
