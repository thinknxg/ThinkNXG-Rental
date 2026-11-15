/* thinkNXG Rental public website: progressive enhancement on top of server-rendered pages.
   The enquiry basket is kept in this browser (localStorage); every price, estimate and availability
   figure is fetched from the server, never computed here. */
(function () {
	"use strict";
	const B = window.rw_boot || {};
	const API = "/api/method/thinknxg_rental.website.api.";
	const KEY = "rw_enquiry_v1";
	const $ = (s, r) => (r || document).querySelector(s);
	const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
	const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
	const icon = (n, c) => `<svg class="rw-i ${c || ""}" aria-hidden="true"><use href="#icon-${n}"></use></svg>`;
	const MESSAGES = B.messages || {};
	const t = (s) => MESSAGES[s] || s; // translated on the server (www/hire/index.py JS_MESSAGES)

	// ------------------------------------------------------------------ server calls
	async function call(method, args, post) {
		const body = new URLSearchParams();
		for (const [k, v] of Object.entries(args || {})) if (v != null) body.append(k, typeof v === "object" ? JSON.stringify(v) : v);
		const headers = { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" };
		if (window.csrf_token) headers["X-Frappe-CSRF-Token"] = window.csrf_token;
		let res;
		try {
			res = post
				? await fetch(API + method, { method: "POST", headers: Object.assign(headers, { "Content-Type": "application/x-www-form-urlencoded" }), body, credentials: "same-origin" })
				: await fetch(API + method + "?" + body.toString(), { headers, credentials: "same-origin" });
		} catch (e) {
			throw new Error(t("We could not reach the server. Check your connection and try again."));
		}
		let data = {};
		try { data = await res.json(); } catch (e) { /* not json */ }
		if (!res.ok || data.exc_type) {
			if (res.status === 429) throw new Error(t("Too many requests from this connection. Try again in a little while."));
			throw new Error(serverMessage(data) || t("Something went wrong. Try again, or contact us by phone or e-mail."));
		}
		return data.message;
	}
	function serverMessage(data) {
		try {
			const msgs = JSON.parse(data._server_messages || "[]").map((m) => { try { return JSON.parse(m).message; } catch (e) { return m; } });
			if (msgs.length) return msgs.map((m) => String(m).replace(/<[^>]+>/g, "")).join(" ");
		} catch (e) { /* ignore */ }
		return data.exception ? String(data.exception).split(":").slice(1).join(":").trim() : "";
	}

	// ------------------------------------------------------------------ toasts (amounts arrive formatted by the server)
	const PER = { Daily: t("day"), Weekly: t("week"), Monthly: t("month") };
	function toast(html, kind) {
		const box = $(".rw-toasts");
		if (!box) return;
		const el = document.createElement("div");
		el.className = "rw-toast" + (kind ? " rw-toast--" + kind : "");
		el.innerHTML = html;
		box.appendChild(el);
		setTimeout(() => el.remove(), 5000);
	}

	// ------------------------------------------------------------------ basket (this browser only)
	function load() {
		try { const v = JSON.parse(localStorage.getItem(KEY) || "{}"); return Object.assign({ items: [] }, v); }
		catch (e) { return { items: [] }; }
	}
	let memory = null;
	function read() { return memory || (memory = load()); }
	function save(b) {
		memory = b;
		try { localStorage.setItem(KEY, JSON.stringify(b)); } catch (e) { /* private mode: keep it in memory for this page */ }
		badge();
	}
	function badge() {
		const n = read().items.length;
		$$("[data-rw-count]").forEach((el) => { el.textContent = n; el.hidden = !n; });
	}
	function add(item, qty, lineType, extra) {
		const b = read();
		const kind = lineType === "Purchase" ? "Purchase" : "Hire";
		const found = b.items.find((x) => x.item_code === item.item_code && (x.line_type || "Hire") === kind);
		if (found) found.qty = Math.max(1, (Number(found.qty) || 0) + (Number(qty) || 1));
		else b.items.push({ item_code: item.item_code, item_name: item.item_name, url: item.url, image: item.image, uom: item.uom, qty: Number(qty) || 1, line_type: kind });
		Object.assign(b, extra || {});
		save(b);
	}
	function fromData(el) {
		return { item_code: el.dataset.item, item_name: el.dataset.name, url: el.dataset.url, image: el.dataset.image, uom: el.dataset.uom };
	}

	// ------------------------------------------------------------------ header
	function header() {
		const btn = $("[data-rw-menu]"), nav = $("#rw-nav");
		if (!btn || !nav) return;
		const set = (open) => {
			nav.classList.toggle("is-open", open);
			btn.setAttribute("aria-expanded", open ? "true" : "false");
			btn.innerHTML = icon(open ? "x" : "menu") + `<span class="rw-sr">${esc(t("Menu"))}</span>`;
			document.body.classList.toggle("rw-locked", open);
		};
		btn.addEventListener("click", () => set(!nav.classList.contains("is-open")));
		document.addEventListener("keydown", (e) => { if (e.key === "Escape" && nav.classList.contains("is-open")) { set(false); btn.focus(); } });
		window.addEventListener("resize", () => { if (window.innerWidth >= 1024 && nav.classList.contains("is-open")) set(false); });
	}

	// ------------------------------------------------------------------ catalogue
	function catalogue() {
		$$("[data-rw-autosubmit]").forEach((el) => el.addEventListener("change", () => el.form && el.form.submit()));
		const panel = $("[data-rw-filters]"), scrim = $("[data-rw-scrim]");
		if (!panel) return;
		const set = (open) => {
			panel.classList.toggle("is-open", open);
			if (scrim) scrim.hidden = !open;
			document.body.classList.toggle("rw-locked", open);
			if (open) { const f = $("input, select", panel); if (f) f.focus(); }
		};
		$$("[data-rw-filters-open]").forEach((b) => b.addEventListener("click", () => set(true)));
		$$("[data-rw-filters-close]").forEach((b) => b.addEventListener("click", () => set(false)));
		if (scrim) scrim.addEventListener("click", () => set(false));
		document.addEventListener("keydown", (e) => { if (e.key === "Escape" && panel.classList.contains("is-open")) set(false); });
	}
	function addButtons() {
		document.addEventListener("click", (e) => {
			const btn = e.target.closest("[data-rw-add]");
			if (!btn) return;
			e.preventDefault();
			add(fromData(btn), 1, "Hire");
			toast(`${icon("check", "rw-i--sm")}<span>${esc(t("Added to your enquiry"))}: ${esc(btn.dataset.name)}</span><a href="/hire/basket">${esc(t("View"))}</a>`);
		});
	}

	// ------------------------------------------------------------------ product page
	function gallery() {
		const g = $("[data-rw-gallery]");
		if (!g) return;
		const main = $("[data-rw-gallery-main]", g);
		$$(".rw-gallery__thumbs button", g).forEach((b) => b.addEventListener("click", () => {
			if (main) { main.src = b.dataset.src; main.alt = b.dataset.alt || ""; }
			$$(".rw-gallery__thumbs button", g).forEach((x) => x.removeAttribute("aria-current"));
			b.setAttribute("aria-current", "true");
		}));
	}
	const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
	function datesValid(from, to) { return from && to && from >= today() && to >= from; }

	function hireForm() {
		const f = $("[data-rw-hire]");
		if (!f) return;
		const out = $("[data-rw-estimate]", f);
		const b = read();
		const start = f.elements.required_from, end = f.elements.expected_return;
		start.min = today(); end.min = today();
		if (b.required_from && b.required_from >= today()) start.value = b.required_from;
		if (b.expected_return && b.expected_return >= start.value) end.value = b.expected_return;
		const kind = () => (f.elements.line_type ? f.elements.line_type.value : "Hire");
		const toggle = () => $$("[data-hire-only]", f).forEach((el) => { el.hidden = kind() === "Purchase"; });
		let timer, seq = 0;
		async function refresh() {
			const qty = Number(f.elements.qty.value) || 0;
			if (start.value) end.min = start.value;
			if (qty <= 0 || kind() === "Purchase" || (start.value && end.value && !datesValid(start.value, end.value))) { out.hidden = true; return; }
			const my = ++seq;
			try {
				const r = await call("estimate", { item_code: f.dataset.item, qty, required_from: datesValid(start.value, end.value) ? start.value : null, expected_return: datesValid(start.value, end.value) ? end.value : null });
				if (my !== seq) return;
				const parts = [];
				if (r.availability) parts.push(`<span class="rw-avail rw-avail--${esc(r.availability.code)}">${esc(r.availability.label)}</span>`);
				if (r.chargeable_days) {
					let line = esc(t("{0} rental days").replace("{0}", r.days));
					if (r.chargeable_days > r.days) line += " · " + esc(t("charged as the {0}-day minimum").replace("{0}", r.chargeable_days));
					parts.push(`<span>${line}</span>`);
				}
				if (r.amount) parts.push(`<b>${esc(t("Estimate"))} ${esc(r.amount_display)}</b><small>${esc(t("At {0} per {1}, before tax and delivery. Your quotation confirms the price.").replace("{0}", r.rate_display).replace("{1}", PER[r.rate_basis] || r.rate_basis))}</small>`);
				else if (r.chargeable_days && B.show_prices) parts.push(`<small>${esc(t("We quote this item on request."))}</small>`);
				else if (!r.chargeable_days) parts.push(`<small>${esc(t("Choose your dates to see the rental period."))}</small>`);
				out.innerHTML = parts.join("");
				out.hidden = !parts.length;
			} catch (e) { out.hidden = true; }
		}
		const later = () => { clearTimeout(timer); timer = setTimeout(refresh, 250); };
		["input", "change"].forEach((ev) => f.addEventListener(ev, (e) => { if (e.target.name === "line_type") toggle(); later(); }));
		toggle(); refresh();

		function collect(requireDates) {
			const qty = Number(f.elements.qty.value);
			if (!(qty > 0)) { f.elements.qty.focus(); toast(esc(t("Enter a quantity")), "error"); return null; }
			if (kind() === "Hire" && requireDates && !datesValid(start.value, end.value)) {
				(start.value ? end : start).focus();
				toast(esc(t("Choose a start date from today and a return date after it")), "error");
				return null;
			}
			const extra = {};
			if (datesValid(start.value, end.value)) Object.assign(extra, { required_from: start.value, expected_return: end.value });
			for (const k of ["project_location", "delivery_requirements", "message"]) if (f.elements[k] && f.elements[k].value.trim()) extra[k] = f.elements[k].value.trim();
			return { qty, extra };
		}
		f.addEventListener("submit", (e) => {
			e.preventDefault();
			const c = collect(true);
			if (!c) return;
			add(fromData(f), c.qty, kind(), c.extra);
			location.href = "/hire/basket";
		});
		$$("[data-action='add']", f).forEach((b) => b.addEventListener("click", () => {
			const c = collect(false);
			if (!c) return;
			add(fromData(f), c.qty, kind(), c.extra);
			toast(`${icon("check", "rw-i--sm")}<span>${esc(t("Added to your enquiry"))}</span><a href="/hire/basket">${esc(t("View enquiry"))}</a>`);
		}));
		$$("[data-action='quote']", f).forEach((a) => a.addEventListener("click", (e) => {
			e.preventDefault();
			const c = collect(false);
			if (!c) return;
			add(fromData(f), c.qty, kind(), c.extra);
			location.href = "/hire/basket";
		}));
	}

	// ------------------------------------------------------------------ basket page
	function basketPage() {
		const root = $("[data-rw-basket]");
		if (!root) return;
		const linesEl = $("[data-rw-lines]", root), totalEl = $("[data-rw-total]", root), daysEl = $("[data-rw-days]", root);
		const form = $("[data-rw-enquiry]", root), done = $("[data-rw-done]", root);
		const start = $("[name=required_from]", root), end = $("[name=expected_return]", root);
		const b = read();
		start.min = end.min = today();
		if (b.required_from && b.required_from >= today()) start.value = b.required_from;
		if (b.expected_return && b.expected_return >= (start.value || today())) end.value = b.expected_return;
		for (const k of ["project_location", "delivery_requirements", "message"]) if (b[k] && form.elements[k] && !form.elements[k].value) form.elements[k].value = b[k];
		let seq = 0;

		async function render() {
			const bk = read();
			if (start.value) end.min = start.value;
			const dates = datesValid(start.value, end.value);
			bk.required_from = dates ? start.value : null;
			bk.expected_return = dates ? end.value : null;
			save(bk);
			if (!bk.items.length) {
				linesEl.innerHTML = `<div class="rw-empty">${icon("clipboard-list", "rw-i--lg")}<h2>${esc(t("Your enquiry is empty"))}</h2><p>${esc(t("Add equipment from the catalogue, or send us a message with what you need."))}</p><div class="rw-ctas"><a class="rw-btn rw-btn--primary" href="/hire/equipment">${esc(t("Browse equipment"))}</a><a class="rw-btn" href="/hire/contact">${esc(t("Send a message"))}</a></div></div>`;
				totalEl.hidden = true; daysEl.textContent = "";
				return;
			}
			const my = ++seq;
			let r;
			try {
				r = await call("basket", { items: bk.items.map((x) => ({ item_code: x.item_code, qty: x.qty, line_type: x.line_type })), required_from: bk.required_from, expected_return: bk.expected_return }, true);
			} catch (e) {
				if (my === seq) linesEl.innerHTML = `<p class="rw-form__status">${esc(e.message)}</p>`;
				return;
			}
			if (my !== seq) return;
			// drop lines the website no longer offers
			const known = new Set(r.lines.map((l) => l.item_code + "|" + l.line_type));
			const kept = bk.items.filter((x) => known.has(x.item_code + "|" + (x.line_type || "Hire")) || r.lines.some((l) => l.item_code === x.item_code));
			if (kept.length !== bk.items.length) {
				bk.items = kept; save(bk);
				toast(`${icon("info", "rw-i--sm")}<span>${esc(t("Some items are no longer offered and were taken out of your enquiry."))}</span>`);
			}
			daysEl.textContent = r.days ? t("{0} days, from {1} to {2}").replace("{0}", r.days).replace("{1}", fmtDate(start.value)).replace("{2}", fmtDate(end.value)) : t("Choose the dates to see the rental period and estimates.");
			linesEl.innerHTML = r.lines.map((l, i) => {
				const amount = l.line_type === "Purchase" ? `<small>${esc(t("Price in the quotation"))}</small>`
					: l.amount ? `<b>${esc(l.amount_display)}</b><small>${esc(l.rate_display)} / ${esc(PER[l.rate_basis] || "")}${l.chargeable_days ? " · " + esc(t("{0} days").replace("{0}", l.chargeable_days)) : ""}</small>`
					: r.days && r.show_prices ? `<small>${esc(t("Rate on request"))}</small>` : "";
				return `<div class="rw-line" data-i="${i}" data-item="${esc(l.item_code)}" data-type="${esc(l.line_type)}">
					<a class="rw-line__img" href="${esc(l.url)}" tabindex="-1" aria-hidden="true">${l.image ? `<img src="${esc(l.image)}" alt="" loading="lazy">` : icon("boxes")}</a>
					<div><a class="rw-line__name" href="${esc(l.url)}">${esc(l.item_name)}</a>
						<div class="rw-line__meta"><span>${esc(l.item_code)}</span>${l.category ? `<span>${esc(l.category)}</span>` : ""}${l.availability ? `<span class="rw-avail rw-avail--${esc(l.availability.code)}">${esc(l.availability.label)}</span>` : ""}${l.minimum_hire_days && l.line_type === "Hire" ? `<span>${esc(t("Min. hire {0} days").replace("{0}", l.minimum_hire_days))}</span>` : ""}</div></div>
					<div class="rw-line__ctl">
						<label><span class="rw-sr">${esc(t("Quantity"))}</span><input type="number" min="1" step="1" inputmode="numeric" value="${esc(l.qty)}" data-qty aria-label="${esc(t("Quantity"))}"></label>
						<span class="rw-line__uom">${esc(l.uom || "")}</span>
						${l.purchasable ? `<select data-kind aria-label="${esc(t("Hire or buy"))}"><option value="Hire" ${l.line_type === "Hire" ? "selected" : ""}>${esc(t("Hire"))}</option><option value="Purchase" ${l.line_type === "Purchase" ? "selected" : ""}>${esc(t("Buy"))}</option></select>` : ""}
						<span class="rw-line__amount">${amount}</span>
						<button type="button" class="rw-iconbtn" data-remove aria-label="${esc(t("Remove"))} ${esc(l.item_name)}">${icon("trash-2", "rw-i--sm")}</button>
					</div></div>`;
			}).join("");
			if (r.total) {
				totalEl.innerHTML = `<span>${esc(t("Estimated rental"))}<small>${esc(t("Before tax, delivery and any discount"))}</small></span><b>${esc(r.total_display)}</b>`;
				totalEl.hidden = false;
			} else totalEl.hidden = true;
		}
		function fmtDate(d) { try { return new Date(d + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }); } catch (e) { return d; } }
		function lineIndex(el) {
			const row = el.closest(".rw-line"), bk = read();
			return { bk, idx: bk.items.findIndex((x) => x.item_code === row.dataset.item && (x.line_type || "Hire") === row.dataset.type) };
		}
		let timer;
		linesEl.addEventListener("input", (e) => {
			if (!e.target.matches("[data-qty]")) return;
			const { bk, idx } = lineIndex(e.target);
			const q = Number(e.target.value);
			if (idx < 0 || !(q > 0)) return;
			bk.items[idx].qty = q; save(bk);
			clearTimeout(timer); timer = setTimeout(render, 400);
		});
		linesEl.addEventListener("change", (e) => {
			if (!e.target.matches("[data-kind]")) return;
			const { bk, idx } = lineIndex(e.target);
			if (idx < 0) return;
			bk.items[idx].line_type = e.target.value;
			// merge with an existing line of the same kind
			const dup = bk.items.findIndex((x, j) => j !== idx && x.item_code === bk.items[idx].item_code && (x.line_type || "Hire") === e.target.value);
			if (dup >= 0) { bk.items[dup].qty += bk.items[idx].qty; bk.items.splice(idx, 1); }
			save(bk); render();
		});
		linesEl.addEventListener("click", (e) => {
			const btn = e.target.closest("[data-remove]");
			if (!btn) return;
			const { bk, idx } = lineIndex(btn);
			if (idx >= 0) { bk.items.splice(idx, 1); save(bk); render(); }
		});
		[start, end].forEach((el) => el.addEventListener("change", render));
		for (const k of ["project_location", "delivery_requirements", "message"]) {
			const el = form.elements[k];
			if (el) el.addEventListener("change", () => { const bk = read(); bk[k] = el.value.trim(); save(bk); });
		}

		form.addEventListener("submit", async (e) => {
			e.preventDefault();
			const status = $(".rw-form__status", form);
			status.textContent = ""; status.className = "rw-form__status";
			const bk = read();
			if (!bk.items.length) { status.textContent = t("Add at least one item to your enquiry."); return; }
			const hire = bk.items.some((x) => (x.line_type || "Hire") === "Hire");
			if (hire && !datesValid(start.value, end.value)) { status.textContent = t("Choose a start date from today and a return date after it."); (start.value ? end : start).focus(); return; }
			if (!checkForm(form, status)) return;
			const data = formData(form);
			Object.assign(data, { items: bk.items.map((x) => ({ item_code: x.item_code, qty: x.qty, line_type: x.line_type || "Hire" })), required_from: start.value || null,
				expected_return: end.value || null, enquiry_type: hire ? "Rental Hire" : "Purchase", source_page: location.pathname });
			const btn = $("button[type=submit]", form);
			btn.disabled = true;
			try {
				const r = await call("submit_enquiry", { data }, true);
				save({ items: [] });
				root.querySelectorAll(".rw-basket__items, .rw-basket__form").forEach((el) => { el.hidden = true; });
				done.hidden = false;
				done.innerHTML = `${icon("circle-check", "rw-i--xl")}<h2>${esc(t("Thank you. Your enquiry is with the rental team."))}</h2>
					${r.name ? `<div class="rw-ref">${esc(r.name)}</div>` : ""}
					<p>${esc(t("Keep this reference. We check availability for your dates and send you a quotation."))}${r.confirmation ? " " + esc(t("A confirmation is on its way to your e-mail.")) : ""}</p>
					<div class="rw-ctas">${B.logged_in ? `<a class="rw-btn rw-btn--primary" href="/hire/account">${esc(t("See it in your account"))}</a>` : ""}<a class="rw-btn" href="/hire/equipment">${esc(t("Back to the catalogue"))}</a></div>`;
				window.scrollTo({ top: 0 });
				done.setAttribute("tabindex", "-1"); done.focus();
			} catch (err) {
				status.textContent = err.message;
			} finally { btn.disabled = false; }
		});
		render();
	}

	// ------------------------------------------------------------------ forms
	function formData(form) {
		const out = {};
		for (const el of form.elements) if (el.name && el.type !== "submit") out[el.name] = typeof el.value === "string" ? el.value.trim() : el.value;
		return out;
	}
	function checkForm(form, status) {
		let first = null;
		for (const el of form.elements) {
			if (!el.name || el.closest(".rw-hp")) continue;
			el.removeAttribute("aria-invalid");
			const bad = (el.required && !el.value.trim()) || (el.type === "email" && el.value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(el.value.trim()));
			if (bad) { el.setAttribute("aria-invalid", "true"); first = first || el; }
		}
		if (first) { status.textContent = t("Fill in the highlighted fields."); first.focus(); return false; }
		return true;
	}
	function contactForms() {
		$$("[data-rw-contact]").forEach((form) => form.addEventListener("submit", async (e) => {
			e.preventDefault();
			const status = $(".rw-form__status", form);
			status.textContent = ""; status.className = "rw-form__status";
			if (!checkForm(form, status)) return;
			const data = Object.assign(formData(form), { source_page: location.pathname });
			const btn = $("button[type=submit]", form);
			btn.disabled = true;
			try {
				const r = await call("contact", { data }, true);
				form.reset();
				status.className = "rw-form__status is-ok";
				status.textContent = r.name ? t("Thank you. Your message is with the rental team, reference {0}. We reply by e-mail or phone.").replace("{0}", r.name) : t("Thank you. Your message is with the rental team.");
			} catch (err) {
				status.textContent = err.message;
			} finally { btn.disabled = false; }
		}));
	}

	function logout() {
		$$("[data-rw-logout]").forEach((b) => b.addEventListener("click", async () => {
			b.disabled = true;
			try { await fetch("/api/method/logout", { method: "POST", headers: { "X-Frappe-CSRF-Token": window.csrf_token || "", Accept: "application/json" }, credentials: "same-origin" }); }
			catch (e) { /* the redirect below shows the state either way */ }
			location.href = "/hire";
		}));
	}

	function init() {
		logout();
		badge(); header(); catalogue(); addButtons(); gallery(); hireForm(); basketPage(); contactForms();
		window.addEventListener("storage", (e) => { if (e.key === KEY) { memory = null; badge(); } });
	}
	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
