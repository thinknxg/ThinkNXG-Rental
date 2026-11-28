// thinkNXG Rental subcontractor portal: core helpers. No framework: DOM helpers, a fetch wrapper for the whitelisted
// API (portal/subcontractor.py), formatting, and the components every page is built from.
(function () {
	"use strict";
	const sp = (window.sp = window.sp || {});
	sp.base = "/subcontractor";
	sp.pages = {};
	sp.state = {};
	const API = "thinknxg_rental.portal.subcontractor.";

	// Page code passes optional parts as `cond ? node : null`; the native append would print "null".
	for (const m of ["replaceChildren", "append", "prepend"]) {
		const native = Element.prototype[m];
		Element.prototype[m] = function (...nodes) {
			return native.apply(this, nodes.flat(Infinity).filter((n) => n != null && n !== false && n !== ""));
		};
	}

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
			else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
			else n.setAttribute(k, v === true ? "" : v);
		}
		add(n, kids);
		return n;
	}
	function add(n, kids) {
		for (const k of [kids].flat(Infinity)) {
			if (k == null || k === false || k === "") continue;
			n.appendChild(k instanceof Node ? k : document.createTextNode(String(k)));
		}
		return n;
	}
	function fill(n, ...kids) {
		n.replaceChildren();
		return add(n, kids);
	}
	function icon(name) {
		const ns = "http://www.w3.org/2000/svg";
		const s = document.createElementNS(ns, "svg");
		s.setAttribute("class", "sp-i");
		s.setAttribute("aria-hidden", "true");
		const u = document.createElementNS(ns, "use");
		u.setAttribute("href", "/assets/frappe/icons/lucide.svg#icon-" + name);
		s.appendChild(u);
		return s;
	}
	Object.assign(sp, { el, add, fill, icon });

	// ------------------------------------------------------------------ API
	function message(e) {
		try {
			const m = JSON.parse(e._server_messages || "[]").map((x) => JSON.parse(x).message);
			if (m.length) return m.join("\n").replace(/<[^>]+>/g, " ");
		} catch (err) { /* fall through */ }
		return e.exception ? String(e.exception).split(":").slice(1).join(":").trim() : __("Something went wrong. Try again.");
	}
	sp.api = async function (method, args, opts) {
		opts = opts || {};
		const params = Object.assign({}, args || {});
		if (sp.state.supplier && !("supplier" in params)) params.supplier = sp.state.supplier;
		for (const k of Object.keys(params)) {
			if (params[k] == null || params[k] === "") delete params[k];
			else if (typeof params[k] === "object") params[k] = JSON.stringify(params[k]);
		}
		const url = "/api/method/" + API + method;
		const init = { credentials: "same-origin", headers: { Accept: "application/json", "X-Frappe-CSRF-Token": window.csrf_token } };
		let res;
		if (opts.post) {
			init.method = "POST";
			init.body = new URLSearchParams(params);
			res = await fetch(url, init);
		} else {
			res = await fetch(url + "?" + new URLSearchParams(params), init);
		}
		let data = {};
		try { data = await res.json(); } catch (e) { /* empty */ }
		if (!res.ok) {
			if (res.status === 403 && !opts.silent && /login|Log in/i.test(message(data))) window.location.href = "/login?redirect-to=" + encodeURIComponent(location.pathname);
			const err = new Error(message(data));
			err.status = res.status;
			throw err;
		}
		return data.message;
	};
	sp.post = (method, args) => sp.api(method, args, { post: true });
	sp.upload = async function (doctype, name, file) {
		const body = new FormData();
		body.append("doctype", doctype);
		body.append("name", name);
		body.append("file", file, file.name);
		if (sp.state.supplier) body.append("supplier", sp.state.supplier);
		const res = await fetch("/api/method/" + API + "upload", { method: "POST", body, credentials: "same-origin",
			headers: { "X-Frappe-CSRF-Token": window.csrf_token } });
		const data = await res.json().catch(() => ({}));
		if (!res.ok) throw new Error(message(data));
		return data.message;
	};
	sp.fileUrl = (name) => "/api/method/" + API + "download?" + new URLSearchParams({ file: name, supplier: sp.state.supplier || "" });

	// ------------------------------------------------------------------ format
	const lang = document.documentElement.lang || "en";
	sp.money = function (v, cur) {
		if (v == null || v === "") return "";
		cur = cur || sp.state.currency || "OMR";
		try {
			return new Intl.NumberFormat(lang, { style: "currency", currency: cur, minimumFractionDigits: cur === "OMR" ? 3 : 2 }).format(+v || 0);
		} catch (e) {
			return (+v || 0).toFixed(2) + " " + cur;
		}
	};
	sp.num = (v) => (v == null || v === "" ? "" : new Intl.NumberFormat(lang, { maximumFractionDigits: 3 }).format(+v || 0));
	sp.date = function (v) {
		if (!v) return "";
		const d = new Date(String(v).length <= 10 ? v + "T00:00:00" : String(v).replace(" ", "T"));
		return isNaN(d) ? v : d.toLocaleDateString(lang, { day: "2-digit", month: "short", year: "numeric" });
	};
	sp.today = () => new Date().toISOString().slice(0, 10);
	const TONES = {
		"Sent to Subcontractor": "amber", "Accepted by Subcontractor": "blue", "Work In Progress": "teal", "Partially Completed": "teal",
		Completed: "good", Verified: "good", Closed: "", "On Hold": "amber", "Rejected by Subcontractor": "bad", "Pending Final Verification": "blue",
		Draft: "", Submitted: "blue", Approved: "good", Returned: "amber", Rejected: "bad", Cancelled: "", Issued: "good", "Partially Issued": "teal",
		"Under Review": "blue", "Inspection Requested": "amber", "Under Inspection": "blue", Accepted: "good", "Partially Accepted": "teal",
		"Rework Required": "amber", Paid: "good", Unpaid: "amber", Overdue: "bad", "Partly Paid": "teal", Expired: "bad", Expiring: "amber", Valid: "good",
		Active: "good", Terminated: "bad",
	};
	sp.badge = (s) => (s ? el("span", { class: "sp-badge" + (TONES[s] ? " sp-badge--" + TONES[s] : ""), text: __(s) }) : null);

	// ------------------------------------------------------------------ components
	sp.panel = (title, body, actions) => el("section", { class: "sp-panel" }, title ? el("header", {}, el("h2", { text: title }), actions) : null, body);
	sp.empty = (title, text, action) => el("div", { class: "sp-empty" }, el("b", { text: title }), text ? el("span", { text }) : null, action ? el("div", { style: "margin-top:10px" }, action) : null);
	sp.btn = (label, onclick, kind, attrs) => el("button", Object.assign({ type: "button", class: "sp-btn" + (kind ? " sp-btn--" + kind : ""), onclick }, attrs || {}), label);
	sp.link = (route, label) => el("a", { href: sp.base + "/" + route, onclick: (e) => sp.linkClick(e, sp.base + "/" + route) }, label);
	sp.linkClick = function (e, href) {
		if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
		e.preventDefault();
		sp.go(href);
	};
	sp.kpi = (label, value, route, due) => {
		const body = [el("span", { text: label }), el("b", { text: value })];
		return route ? el("a", { class: "sp-kpi" + (due ? " sp-kpi--due" : ""), href: sp.base + "/" + route, onclick: (e) => sp.linkClick(e, sp.base + "/" + route) }, body)
			: el("div", { class: "sp-kpi" + (due ? " sp-kpi--due" : "") }, body);
	};
	// cols: [label, fn(row) -> node|text, {num}]
	sp.table = function (cols, rows, onrow) {
		if (!rows || !rows.length) return null;
		return el("div", { class: "sp-table-wrap" }, el("table", { class: "sp-table sp-cards" },
			el("thead", {}, el("tr", {}, cols.map((c) => el("th", { class: c[2] && c[2].num ? "num" : null, text: c[0] })))),
			el("tbody", {}, rows.map((r) => el("tr", { class: onrow ? "sp-click" : null, onclick: onrow ? () => onrow(r) : null },
				cols.map((c) => el("td", { class: c[2] && c[2].num ? "num" : null, "data-label": c[0] }, c[1](r))))))));
	};
	sp.bar = (ordered, accepted, reported) => {
		const pct = (v) => Math.max(0, Math.min(100, ordered ? (100 * v) / ordered : 0)) + "%";
		return el("div", { class: "sp-bar", title: __("{0} accepted, {1} reported of {2}", [sp.num(accepted), sp.num(reported), sp.num(ordered)]) },
			el("i", { style: "width:" + pct(Math.max(reported || 0, accepted)) }), el("b", { style: "width:" + pct(accepted) }));
	};
	sp.dl = (pairs) => el("dl", { class: "sp-dl" }, pairs.filter((p) => p && p[1] != null && p[1] !== "").map((p) => el("div", {}, el("dt", { text: p[0] }), el("dd", {}, p[1]))));

	sp.toast = function (text, bad) {
		let box = document.querySelector(".sp-toasts");
		if (!box) document.body.append((box = el("div", { class: "sp-toasts", role: "status", "aria-live": "polite" })));
		const t = el("div", { class: "sp-toast" + (bad ? " sp-toast--bad" : ""), text });
		box.append(t);
		setTimeout(() => t.remove(), 4200);
	};

	// A drawer form. fields: [{name, label, type, options, required, value, help, min}], or nodes. submit(values) -> promise.
	sp.drawer = function (title, content, opts) {
		opts = opts || {};
		const err = el("div", { class: "sp-error", hidden: true, role: "alert" });
		const body = el("div", { class: "sp-drawer-body" }, err, content);
		const close = () => { layer.remove(); document.removeEventListener("keydown", esc); };
		const esc = (e) => e.key === "Escape" && close();
		const save = opts.submit ? sp.btn(opts.submitLabel || __("Submit"), async () => {
			err.hidden = true;
			save.disabled = true;
			try {
				await opts.submit();
				close();
			} catch (e) {
				err.textContent = e.message;
				err.hidden = false;
				body.scrollTop = 0;
			} finally {
				save.disabled = false;
			}
		}, "primary") : null;
		const drawer = el("div", { class: "sp-drawer", role: "dialog", "aria-modal": "true", "aria-label": title },
			el("header", {}, el("h2", { text: title }), el("button", { type: "button", class: "sp-iconbtn", "aria-label": __("Close"), onclick: close }, icon("x"))),
			body, el("footer", {}, sp.btn(__("Cancel"), close), save));
		const layer = el("div", { class: "sp-layer", onclick: (e) => e.target === layer && close() }, drawer);
		document.body.append(layer);
		document.addEventListener("keydown", esc);
		const first = drawer.querySelector("input, select, textarea");
		if (first) first.focus();
		return { close, body };
	};
	sp.field = function (f) {
		const id = "f-" + f.name;
		let input;
		if (f.type === "select") input = el("select", { id, name: f.name, required: f.required }, (f.options || []).map((o) => el("option", { value: o.value != null ? o.value : o, text: o.label || o, selected: (o.value != null ? o.value : o) === f.value })));
		else if (f.type === "textarea") input = el("textarea", { id, name: f.name, required: f.required, maxlength: f.max || 2000 }, f.value || "");
		else if (f.type === "check") return el("div", { class: "sp-field" }, el("label", {}, el("input", { type: "checkbox", id, name: f.name, checked: !!f.value }), f.label));
		else input = el("input", { id, name: f.name, type: f.type || "text", required: f.required, value: f.value != null ? f.value : null, min: f.min, max: f.maxv, step: f.step, accept: f.accept, capture: f.capture });
		return el("div", { class: "sp-field" }, el("label", { for: id, text: f.label + (f.required ? " *" : "") }), input, f.help ? el("small", { text: f.help }) : null);
	};
	sp.values = function (root) {
		const out = {};
		root.querySelectorAll("[name]").forEach((n) => {
			if (n.type === "file") return;
			out[n.name] = n.type === "checkbox" ? (n.checked ? 1 : 0) : n.value;
		});
		return out;
	};
	// Attach the picked files (input[type=file][data-upload]) to a record after it is created.
	sp.uploadPicked = async function (root, doctype, name) {
		const inputs = root.querySelectorAll("input[type=file]");
		for (const inp of inputs) for (const f of inp.files) await sp.upload(doctype, name, f);
	};
	sp.filePicker = (label, camera) => sp.field({ name: "files", label, type: "file", accept: camera ? "image/*,application/pdf" : ".pdf,.jpg,.jpeg,.png,.webp,.heic,.doc,.docx,.xls,.xlsx,.csv,.txt",
		help: __("Photos or documents, up to 10 MB each. They are attached when you submit.") });
})();
