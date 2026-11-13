// Command Center charts: small SVG line and bar charts with a hover tooltip, a legend for two or more
// series, and a table view of the same numbers. One y-axis per chart. Colours follow the series,
// never their rank (own = slot 1, cross-hired = slot 2, ...).
(function () {
	const cc = window.cc;
	const { el, __ } = cc;
	const C = (cc.colors = {
		s1: "#2a78d6", s2: "#eb6834", s3: "#1baf7a", s4: "#eda100", s5: "#e87ba4", s6: "#008300", s7: "#6250d6", s8: "#e34948",
	});
	const chart = (cc.chart = {});

	// ------------------------------------------------------------------ tooltip
	let tip;
	chart.tip = function (x, y, title, rows) {
		if (!tip) document.body.append((tip = el("div", { class: "cc-tip", role: "presentation" })));
		tip.replaceChildren(el("b", { text: title }), ...rows.map((r) => el("div", {}, el("span", {}, r.color ? el("i", { style: "background:" + r.color }) : null, r.name), el("span", { text: r.value }))));
		tip.hidden = false;
		const w = tip.offsetWidth, h = tip.offsetHeight;
		let left = x + 14, top = y - h - 10;
		if (left + w > window.innerWidth - 8) left = x - w - 14;
		if (top < 8) top = y + 16;
		tip.style.left = left + "px";
		tip.style.top = top + "px";
	};
	chart.hide = () => tip && (tip.hidden = true);

	// ------------------------------------------------------------------ scale
	function niceMax(v) {
		if (!v || v <= 0) return 1;
		const p = Math.pow(10, Math.floor(Math.log10(v)));
		const f = v / p;
		return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
	}
	function ticks(max, n) {
		const out = [];
		for (let i = 0; i <= n; i++) out.push((max / n) * i);
		return out;
	}
	function every(labels, width) {
		const room = Math.max(1, Math.floor(width / 64));
		return Math.max(1, Math.ceil(labels.length / room));
	}

	// Redraw when the box changes width (sidebar collapsed, phone turned).
	function responsive(box, draw) {
		let last = 0;
		const run = () => {
			const w = Math.round(box.clientWidth);
			if (!w || w === last) return;
			last = w;
			draw(w);
		};
		if (window.ResizeObserver) new ResizeObserver(run).observe(box);
		requestAnimationFrame(run);
	}

	// ------------------------------------------------------------------ line / column chart
	// spec: {labels, series: [{name, color, values}], kind: "line"|"bars"|"stacked", fmt(v), height, max}
	chart.xy = function (spec) {
		const box = el("div", { class: "cc-chart" });
		const height = spec.height || 220;
		const fmt = spec.fmt || ((v) => cc.num(v));
		const axisFmt = spec.axisFmt || ((v) => cc.compact(v));
		responsive(box, (W) => {
			const L = 46, R = 8, T = 10, B = 26;
			const w = W - L - R, h = height - T - B;
			const n = spec.labels.length;
			const totals = spec.labels.map((_, i) => spec.series.reduce((s, se) => s + (Number(se.values[i]) || 0), 0));
			const peak = spec.kind === "stacked" ? Math.max(0, ...totals) : Math.max(0, ...spec.series.flatMap((s) => s.values.map((v) => Number(v) || 0)));
			const max = spec.max || niceMax(peak * 1.05);
			const y = (v) => T + h - (Math.max(0, v) / max) * h;
			const band = w / Math.max(n, 1);
			const x = (i) => L + band * i + band / 2;
			const svg = el("svg", { viewBox: `0 0 ${W} ${height}`, role: "img", "aria-label": spec.title || "" });
			ticks(max, 4).forEach((t, i) => {
				svg.append(el("line", { class: i ? "cc-gridline" : "cc-axis", x1: L, x2: W - R, y1: y(t), y2: y(t) }));
				svg.append(el("text", { x: L - 6, y: y(t) + 4, "text-anchor": "end", text: axisFmt(t) }));
			});
			const step = every(spec.labels, w);
			spec.labels.forEach((lab, i) => {
				if (i % step) return;
				svg.append(el("text", { x: x(i), y: height - 8, "text-anchor": "middle", text: lab }));
			});
			if (spec.kind === "line") {
				spec.series.forEach((s) => {
					let d = "";
					let pen = false;
					s.values.forEach((v, i) => {
						if (v === null || v === undefined) {
							pen = false;
							return;
						}
						d += (pen ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1);
						pen = true;
					});
					svg.append(el("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
					// markers only when there are few points
					if (n <= 16) s.values.forEach((v, i) => v !== null && v !== undefined && svg.append(el("circle", { cx: x(i), cy: y(v), r: 3.5, fill: s.color, stroke: "#fff", "stroke-width": 2 })));
				});
			} else {
				const gap = 2;
				const bw = Math.max(3, Math.min(34, band * 0.62));
				spec.labels.forEach((_, i) => {
					if (spec.kind === "stacked") {
						let base = 0;
						spec.series.forEach((s, k) => {
							const v = Number(s.values[i]) || 0;
							if (v <= 0) return;
							const top = y(base + v), bottom = y(base);
							const hh = Math.max(1, bottom - top - (base ? gap : 0));
							const last = spec.series.slice(k + 1).every((o) => !(Number(o.values[i]) > 0));
							svg.append(barPath(x(i) - bw / 2, top, bw, hh, last ? 4 : 0, s.color));
							base += v;
						});
					} else {
						const m = spec.series.length;
						const sub = (bw - gap * (m - 1)) / m;
						spec.series.forEach((s, k) => {
							const v = Number(s.values[i]) || 0;
							if (v <= 0) return;
							svg.append(barPath(x(i) - bw / 2 + k * (sub + gap), y(v), sub, T + h - y(v), 4, s.color));
						});
					}
				});
			}
			// hover: a band per label, crosshair on lines
			const cross = el("line", { class: "cc-cross", y1: T, y2: T + h, visibility: "hidden" });
			svg.append(cross);
			spec.labels.forEach((lab, i) => {
				const r = el("rect", { class: "cc-hit-rect", x: L + band * i, y: T, width: band, height: h });
				const show = (e) => {
					cross.setAttribute("x1", x(i));
					cross.setAttribute("x2", x(i));
					cross.setAttribute("visibility", spec.kind === "line" ? "visible" : "hidden");
					const rows = spec.series.map((s) => ({ name: s.name, color: s.color, value: s.values[i] === null || s.values[i] === undefined ? "–" : fmt(s.values[i]) }));
					if (spec.kind === "stacked" && spec.series.length > 1) rows.push({ name: __("Total"), value: fmt(totals[i]) });
					chart.tip(e.clientX, e.clientY, (spec.tipLabel || ((l) => l))(lab, i), rows);
				};
				r.addEventListener("mousemove", show);
				r.addEventListener("mouseleave", () => {
					cross.setAttribute("visibility", "hidden");
					chart.hide();
				});
				if (spec.onclick) r.addEventListener("click", () => spec.onclick(i));
				svg.append(r);
			});
			box.replaceChildren(svg);
		});
		return box;
	};
	// a bar with its data end rounded and its base square
	function barPath(x0, top, w, h, r, color) {
		r = Math.min(r, w / 2, h);
		const d = `M${x0},${top + h}V${top + r}Q${x0},${top} ${x0 + r},${top}H${x0 + w - r}Q${x0 + w},${top} ${x0 + w},${top + r}V${top + h}Z`;
		return el("path", { d, fill: color });
	}

	// ------------------------------------------------------------------ horizontal bars (ranked lists)
	// rows: [{label, href|route, segments: [{name, value, color}], text}]
	chart.hbars = function (rows, opts) {
		opts = opts || {};
		const max = Math.max(1, ...rows.map((r) => r.segments.reduce((s, x) => s + Math.max(0, x.value), 0)));
		return el("div", { class: "cc-hbar" }, rows.flatMap((r) => {
			const label = r.route ? cc.link(r.route, r.label) : el("span", { text: r.label });
			const track = el("div", { class: "cc-hbar-track" }, r.segments.filter((s) => s.value > 0).map((s, i, a) =>
				el("span", { style: `width:${(s.value / max) * 100}%;background:${s.color};border-radius:${i === a.length - 1 ? "0 4px 4px 0" : "0"}` })));
			track.addEventListener("mousemove", (e) => chart.tip(e.clientX, e.clientY, r.label, r.segments.map((s) => ({ name: s.name, color: s.color, value: (opts.fmt || cc.qty)(s.value) }))));
			track.addEventListener("mouseleave", chart.hide);
			return [el("div", { class: "cc-hbar-label", title: r.label }, label), track, el("div", { class: "cc-hbar-val", text: r.text })];
		}));
	};

	// ------------------------------------------------------------------ the yard tube
	chart.tube = function (segments, lg) {
		const total = segments.reduce((s, x) => s + Math.max(0, x.value), 0);
		const t = el("div", { class: "cc-tube" + (lg ? " cc-tube--lg" : ""), role: "img",
			"aria-label": segments.map((s) => s.name + " " + cc.qty(s.value)).join(", ") },
			total ? segments.filter((s) => s.value > 0).map((s) => el("span", { style: `flex:${s.value} 1 0;background:${s.color}`, title: `${s.name}: ${cc.qty(s.value)}` })) : null);
		return t;
	};
	chart.legend = (items) => el("ul", { class: "cc-legend" }, items.map((i) => el("li", {}, el("i", { style: "background:" + i.color }), i.name)));

	// a chart panel with a Chart / Table switch
	chart.panel = function (title, note, draw, table, opts) {
		opts = opts || {};
		const body = el("div");
		let mode = "chart";
		const toggle = el("div", { class: "cc-tabs cc-viewtoggle", role: "tablist" },
			["chart", "table"].map((m) => el("button", { type: "button", role: "tab", "aria-selected": m === mode ? "true" : "false", text: m === "chart" ? __("Chart") : __("Table"), onclick: (e) => {
				mode = m;
				toggle.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", b === e.target ? "true" : "false"));
				render();
			} })));
		const render = () => body.replaceChildren(mode === "chart" ? draw() : table());
		render();
		return cc.panel(title, body, { actions: table ? [toggle].concat(opts.actions || []) : opts.actions, note });
	};
	chart.table = function (head, rows, numeric) {
		return el("div", { class: "cc-tablewrap" }, el("table", { class: "cc-table cc-chart-table" },
			el("thead", {}, el("tr", {}, head.map((h, i) => el("th", { class: i && numeric !== false ? "cc-num" : null, text: h })))),
			el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c, i) => el("td", { class: i && numeric !== false ? "cc-num" : null }, c)))))));
	};
})();
