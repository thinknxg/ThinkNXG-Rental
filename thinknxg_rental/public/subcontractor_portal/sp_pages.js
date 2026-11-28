// thinkNXG Rental subcontractor portal: pages. Every figure comes from portal/subcontractor.py for the logged-in
// subcontractor; money appears only for contacts with commercial access (the server leaves it out otherwise).
(function () {
	"use strict";
	const sp = window.sp;
	const { el, fill } = sp;
	const P = sp.pages;
	const C = () => sp.state.commercial;
	const ro = () => sp.state.suspended;

	function more(state, load) {
		return state.more ? el("div", { class: "sp-pad", style: "text-align:center" }, sp.btn(__("Show more"), () => { state.page += 1; load(true); })) : null;
	}

	// ------------------------------------------------------------------ dashboard
	P.dashboard = async function (ctx) {
		ctx.title(__("Dashboard"));
		const d = await sp.api("dashboard");
		const c = d.cards;
		const kpis = [
			sp.kpi(__("Active work orders"), c.active, "work-orders"),
			sp.kpi(__("Awaiting your acceptance"), c.awaiting_acceptance, "work-orders?status=awaiting", c.awaiting_acceptance > 0),
			sp.kpi(__("Work in progress"), c.in_progress, "work-orders?status=open"),
			sp.kpi(__("Open material requests"), c.pending_material, "materials"),
			sp.kpi(__("Submitted for inspection"), c.inspection_pending, "inspections"),
		];
		if (C()) kpis.push(
			sp.kpi(__("Approved work value"), sp.money(c.approved_value)),
			sp.kpi(__("Invoices being verified"), c.submitted_invoices, "invoices"),
			sp.kpi(__("Outstanding payments"), sp.money(c.outstanding), "payments"),
			sp.kpi(__("Overdue payments"), sp.money(c.overdue), "payments", c.overdue > 0));
		const actions = d.actions.length ? el("ul", { class: "sp-list" }, d.actions.map((a) => el("li", {}, sp.icon({ accept: "signature", progress: "pencil",
			receipt: "package-check", rework: "rotate-ccw" }[a.kind] || "circle-alert"), el("span", { class: "sp-grow" }, sp.link(a.route, a.label)))))
			: sp.empty(__("Nothing is waiting for you"), __("New work orders, returned reports and material to confirm appear here."));
		const schedule = d.schedule.length ? el("ul", { class: "sp-list" }, d.schedule.map((w) => el("li", {}, el("div", { class: "sp-grow" },
			sp.link("work-orders/" + encodeURIComponent(w.name), w.work_description || w.name), el("div", { class: "sp-sub", text: w.name + (w.project ? " · " + w.project : "") })),
			el("div", { style: "text-align:right" }, el("div", { text: sp.date(w.expected_completion_date) }),
				el("div", { class: "sp-sub", style: w.days_left < 0 ? "color:var(--bad)" : "", text: w.days_left < 0 ? __("{0} days late", [-w.days_left]) : __("{0} days left", [w.days_left]) })))))
			: sp.empty(__("No work scheduled"), null);
		const progress = d.progress.length ? el("ul", { class: "sp-list" }, d.progress.map((p) => el("li", {}, el("div", { class: "sp-grow" },
			sp.link("work-orders/" + encodeURIComponent(p.name), p.title), sp.bar(p.ordered, p.accepted, p.reported),
			el("div", { class: "sp-sub", text: __("{0} of {1} accepted", [sp.num(p.accepted), sp.num(p.ordered)]) })))))
			: sp.empty(__("No work in progress"), null);
		const notes = [];
		d.announcements.forEach((a) => notes.push(el("li", {}, el("div", { class: "sp-grow" }, a.subject ? el("b", { text: a.subject }) : null, el("div", { text: a.message }),
			el("div", { class: "sp-sub", text: sp.date(a.date) })))));
		d.expiring.forEach((x) => notes.push(el("li", {}, sp.badge(x.compliance_status), el("span", { class: "sp-grow" }, sp.link("profile", __("{0}: expires {1}", [x.document_type, sp.date(x.expiry_date)]))))));
		fill(ctx.root,
			ro() ? el("div", { class: "sp-banner sp-banner--warn", text: __("Your account is suspended. You can view your records but not submit anything. Contact the company.") }) : null,
			el("div", { class: "sp-kpis" }, kpis),
			el("div", { class: "sp-grid sp-grid--2" },
				sp.panel(__("Waiting for you"), actions),
				sp.panel(__("Upcoming completion dates"), schedule),
				sp.panel(__("Work progress"), el("div", {}, progress, d.progress.length ? el("div", { class: "sp-pad sp-legend" }, el("span", { text: __("Accepted") }), el("span", { class: "rep", text: __("Reported") })) : null)),
				sp.panel(__("Announcements and documents"), notes.length ? el("ul", { class: "sp-list" }, notes) : sp.empty(__("Nothing new"), null)),
				C() ? sp.panel(__("Recent payments"), sp.table([[__("Payment"), (r) => r.name], [__("Date"), (r) => sp.date(r.posting_date)], [__("Reference"), (r) => r.reference_no || ""],
					[__("Amount"), (r) => sp.money(r.paid_amount), { num: true }]], d.payments) || sp.empty(__("No payments yet"), null), sp.link("payments", __("All payments"))) : null,
				sp.panel(__("Messages"), el("div", { class: "sp-pad" }, d.unread_messages ? __("{0} unread messages", [d.unread_messages]) : __("No unread messages"), " ", sp.link("messages", __("Open messages"))))));
	};

	// ------------------------------------------------------------------ work orders
	P.workOrders = async function (ctx) {
		ctx.title(__("Work orders"));
		const q = new URLSearchParams(ctx.query);
		const state = { page: 1, status: q.get("status") || "", search: "" };
		const list = el("div");
		async function load(append) {
			const d = await sp.api("work_orders", { status: state.status, search: state.search, page: state.page });
			state.more = d.more;
			const cols = [[__("Work order"), (r) => el("div", {}, el("b", { text: r.name }), el("div", { class: "sp-sub", text: r.work_description || "" }))],
				[__("Project / site"), (r) => [r.project, r.rental_site].filter(Boolean).join(" · ")],
				[__("Due"), (r) => sp.date(r.expected_completion_date)],
				[__("Progress"), (r) => el("span", { text: r.progress + "%" }), { num: true }],
				[__("Status"), (r) => sp.badge(r.status)]];
			if (C()) cols.splice(3, 0, [__("Value"), (r) => sp.money(r.final_contract_value, r.currency), { num: true }]);
			const t = sp.table(cols, d.rows, (r) => sp.go(sp.base + "/work-orders/" + encodeURIComponent(r.name)));
			if (!append) fill(list);
			list.append(t || (append ? null : sp.empty(__("No work orders here"), __("Work orders appear when the company sends them to you."))), more(state, load));
		}
		const search = el("input", { type: "search", placeholder: __("Search work orders"), "aria-label": __("Search"), oninput: () => {
			clearTimeout(state.t);
			state.t = setTimeout(() => { state.search = search.value; state.page = 1; load(); }, 300);
		} });
		const status = el("select", { "aria-label": __("Status"), onchange: () => { state.status = status.value; state.page = 1; load(); } },
			[["", __("All")], ["awaiting", __("Awaiting acceptance")], ["open", __("Open")], ["closed", __("Closed")]].map(([v, l]) => el("option", { value: v, text: l, selected: v === state.status })));
		fill(ctx.root, el("div", { class: "sp-filters" }, search, status), sp.panel(null, list));
		await load();
	};

	P.workOrder = async function (ctx) {
		const d = await sp.api("work_order", { name: ctx.name });
		const w = d.doc;
		ctx.title(w.name, [{ route: "work-orders", label: __("Work orders") }]);
		const tabsEl = el("div", { class: "sp-tabs", role: "tablist" });
		const pane = el("div");
		const head = el("div", { class: "sp-head" }, el("div", { class: "sp-grow" }, el("h2", { text: w.work_description || w.name }),
			el("div", { class: "sp-sub" }, w.name, " · ", sp.badge(w.status), w.priority && w.priority !== "Medium" ? [" ", sp.badge(w.priority)] : null)),
		el("div", { class: "sp-actions" },
			w.can_respond ? sp.btn(__("Accept"), () => respond(w, "accept"), "primary") : null,
			w.can_respond ? sp.btn(__("Reject"), () => respond(w, "reject"), "danger") : null,
			w.can_report ? sp.btn(__("Report progress"), () => progressForm(w, d.items, ctx)) : null,
			w.can_report ? sp.btn(__("Request inspection"), () => inspectionForm(w, d.items, ctx)) : null,
			C() ? el("a", { class: "sp-btn", href: "/api/method/thinknxg_rental.portal.subcontractor.work_order_pdf?" + new URLSearchParams({ name: w.name, supplier: sp.state.supplier }) }, sp.icon("download"), __("PDF")) : null));
		const overview = () => el("div", { class: "sp-grid" },
			w.status === "Sent to Subcontractor" ? el("div", { class: "sp-banner sp-banner--warn", text: __("Review the scope and accept or reject this work order.") }) : null,
			w.status === "On Hold" ? el("div", { class: "sp-banner sp-banner--warn", text: __("On hold: {0}", [w.hold_reason || ""]) }) : null,
			sp.panel(__("Details"), el("div", { class: "sp-pad" }, sp.dl([[__("Project"), w.project], [__("Site"), w.rental_site], [__("Order date"), sp.date(w.contract_date)],
				[__("Planned start"), sp.date(w.start_date)], [__("Planned completion"), sp.date(w.expected_completion_date)], [__("Actual start"), sp.date(w.actual_start_date)],
				[__("Completed on"), sp.date(w.actual_completion_date)], [__("Site engineer"), w.site_engineer], [__("Project manager"), w.project_manager],
				[__("Confirmed start"), sp.date(w.confirmed_start_date)], [__("Your response"), w.subcontractor_response],
				C() ? [__("Contract value"), sp.money(w.final_contract_value, w.currency)] : null, C() ? [__("Retention"), w.retention_percentage ? w.retention_percentage + "%" : null] : null,
				C() ? [__("Advance"), w.advance_amount ? sp.money(w.advance_amount, w.currency) : null] : null, C() ? [__("Payment terms"), w.payment_terms] : null]))),
			w.work_instructions ? sp.panel(__("Work instructions"), el("div", { class: "sp-pad", style: "white-space:pre-wrap", text: w.work_instructions })) : null);
		const scope = () => sp.panel(__("Scope and quantities"), sp.table([[__("Work"), (r) => el("div", {}, el("b", { text: r.job_type }), el("div", { class: "sp-sub", text: (r.description || "") + (r.is_additional ? " · " + __("Additional") : "") }))],
			[__("Ordered"), (r) => sp.num(r.qty) + " " + (r.uom || ""), { num: true }], C() ? [__("Rate"), (r) => sp.money(r.rate, w.currency), { num: true }] : null,
			[__("Reported"), (r) => sp.num(r.reported_qty), { num: true }], [__("Accepted"), (r) => sp.num(r.accepted_qty), { num: true }],
			[__("Rejected"), (r) => sp.num(r.rejected_qty), { num: true }], C() ? [__("Invoiced"), (r) => sp.num(r.invoiced_qty), { num: true }] : null,
			[__("Progress"), (r) => sp.bar(r.qty, r.accepted_qty, r.reported_qty)]].filter(Boolean), d.items));
		const listPanel = (title, cols, rows, emptyText, act) => sp.panel(title, sp.table(cols, rows) || sp.empty(emptyText, null), act);
		const TABS = [
			[__("Overview"), overview],
			[__("Scope"), scope],
			[__("Progress"), () => listPanel(__("Progress reports"), [[__("Report"), (r) => r.name], [__("Date"), (r) => sp.date(r.report_date)], [__("Labour"), (r) => r.labour_deployed || "", { num: true }],
				[__("Delay"), (r) => (r.delay_reported ? __("Yes") : "")], [__("Status"), (r) => sp.badge(r.status)], [__("Review"), (r) => r.review_remarks || ""]], d.progress, __("No progress reported yet"))],
			[__("Inspections"), () => listPanel(__("Inspections"), [[__("Inspection"), (r) => r.name], [__("Proposed date"), (r) => sp.date(r.proposed_inspection_date)],
				[__("Status"), (r) => sp.badge(r.inspection_status)], [__("Quality remarks"), (r) => r.quality_remarks || ""], [__("Rework instructions"), (r) => r.corrective_action || ""]], d.inspections, __("No inspections yet"))],
			[__("Materials"), () => el("div", { class: "sp-grid" }, listPanel(__("Material requests"), [[__("Request"), (r) => r.name], [__("Requested"), (r) => sp.date(r.request_date)],
				[__("Needed by"), (r) => sp.date(r.required_by)], [__("Status"), (r) => sp.badge(r.status)]], d.materials, __("No material requested"),
				w.can_report ? sp.btn(__("Request material"), () => materialForm(w, ctx), "primary") : null),
				listPanel(__("Material issued to you"), [[__("Issue"), (r) => r.name], [__("Date"), (r) => sp.date(r.posting_date)],
					[__("Receipt"), (r) => (r.received_by_subcontractor ? sp.badge(r.shortage_reported ? "Shortage reported" : "Confirmed") : sp.btn(__("Confirm receipt"), () => receiptForm(r, ctx), "primary", { disabled: ro() }))]],
				d.issues, __("No material issued yet")))],
			[__("Variations"), () => listPanel(__("Variations and claims"), [[__("Request"), (r) => r.name], [__("Type"), (r) => r.variation_type], [__("Date"), (r) => sp.date(r.request_date)],
				C() ? [__("Change"), (r) => (r.value_change ? sp.money(r.value_change, w.currency) : ""), { num: true }] : null, [__("Status"), (r) => sp.badge(r.status)],
				[__("Remarks"), (r) => r.external_remarks || ""]].filter(Boolean), d.variations, __("No variations yet"),
				!ro() && w.can_report ? sp.btn(__("New request"), () => variationForm(w, d.items, ctx), "primary") : null)],
			C() ? [__("Invoices"), () => listPanel(__("Your invoices"), [[__("Invoice"), (r) => r.supplier_invoice_no], [__("Date"), (r) => sp.date(r.supplier_invoice_date)],
				[__("Claimed"), (r) => sp.money(r.total_claimed, w.currency), { num: true }], [__("Status"), (r) => sp.badge(r.status)]], d.invoices, __("No invoices yet"),
				!ro() ? sp.btn(__("Submit invoice"), () => invoiceForm(w.name, ctx), "primary") : null)] : null,
			[__("Files"), () => sp.panel(__("Documents"), d.files.length ? el("ul", { class: "sp-list" }, d.files.map((f) => el("li", {}, sp.icon("paperclip"),
				el("a", { class: "sp-grow", href: sp.fileUrl(f.name), text: f.file_name }), el("span", { class: "sp-sub", text: sp.date(f.creation) })))) : sp.empty(__("No documents attached"), null))],
			[__("Messages"), () => thread(w.name, d.messages, ctx)],
		].filter(Boolean);
		let current = 0;
		function show(i) {
			current = i;
			tabsEl.querySelectorAll("button").forEach((b, k) => b.setAttribute("aria-selected", k === i ? "true" : "false"));
			fill(pane, TABS[i][1]());
		}
		TABS.forEach((t, i) => tabsEl.append(el("button", { type: "button", role: "tab", onclick: () => show(i), text: t[0] })));
		fill(ctx.root, head, tabsEl, pane);
		show(Math.min(+(new URLSearchParams(ctx.query).get("tab") || current), TABS.length - 1));
	};

	function respond(w, action) {
		const form = el("div", { class: "sp-form" },
			action === "accept" ? sp.field({ name: "confirmed_start_date", label: __("Confirmed start date"), type: "date", value: w.start_date || sp.today() }) : null,
			sp.field({ name: "remarks", label: action === "accept" ? __("Remarks") : __("Reason for rejecting"), type: "textarea", required: action === "reject" }));
		sp.drawer(action === "accept" ? __("Accept work order {0}", [w.name]) : __("Reject work order {0}", [w.name]), form, {
			submitLabel: action === "accept" ? __("Accept work order") : __("Reject work order"),
			async submit() {
				const v = sp.values(form);
				await sp.post("respond_work_order", Object.assign({ name: w.name, action }, v));
				sp.toast(action === "accept" ? __("Work order accepted") : __("Work order rejected"));
				sp.reload();
			},
		});
	}

	function qtyLines(items, field, label, maxFn) {
		return el("div", { class: "sp-table-wrap" }, el("table", { class: "sp-table sp-lines" }, el("thead", {}, el("tr", {}, el("th", { text: __("Work") }),
			el("th", { class: "num", text: __("Ordered") }), el("th", { class: "num", text: __("Reported") }), el("th", { class: "num", text: __("Accepted") }), el("th", { class: "num", text: label }))),
		el("tbody", {}, items.map((r) => el("tr", {}, el("td", {}, el("b", { text: r.job_type }), el("div", { class: "sp-sub", text: r.description || "" })),
			el("td", { class: "num", text: sp.num(r.qty) }), el("td", { class: "num", text: sp.num(r.reported_qty) }), el("td", { class: "num", text: sp.num(r.accepted_qty) }),
			el("td", {}, el("input", { type: "number", min: 0, step: "any", max: maxFn ? maxFn(r) : null, "data-item": r.name, "data-field": field, "aria-label": label + " " + r.job_type })))))));
	}
	function linesFrom(root, field) {
		return [...root.querySelectorAll("input[data-item]")].filter((i) => +i.value > 0).map((i) => ({ swo_item: i.dataset.item, [field]: +i.value }));
	}

	function progressForm(w, items, ctx) {
		const form = el("div", { class: "sp-form" },
			sp.field({ name: "report_date", label: __("Report date"), type: "date", value: sp.today(), required: true }),
			el("div", {}, el("label", { class: "sp-sub", text: __("Quantity done on this date") }), qtyLines(items, "qty_done", __("Done today"), (r) => r.qty - r.reported_qty)),
			el("div", { class: "sp-row2" }, sp.field({ name: "labour_deployed", label: __("Labour on site (persons)"), type: "number", min: 0 }),
				sp.field({ name: "expected_completion_date", label: __("Expected completion"), type: "date" })),
			sp.field({ name: "labour_details", label: __("Labour details"), type: "textarea" }),
			sp.field({ name: "equipment_deployed", label: __("Equipment on site"), type: "textarea" }),
			sp.field({ name: "delay_reported", label: __("There is a delay"), type: "check" }),
			sp.field({ name: "delay_reason", label: __("Reason for the delay"), type: "textarea" }),
			sp.field({ name: "blockers", label: __("Blockers"), type: "textarea" }),
			sp.field({ name: "remarks", label: __("Remarks"), type: "textarea" }),
			sp.filePicker(__("Site photographs and documents"), true));
		form.querySelector("input[type=file]").multiple = true;
		sp.drawer(__("Progress report for {0}", [w.name]), form, {
			async submit() {
				const v = sp.values(form);
				const name = await sp.post("submit_progress", Object.assign({ work_order: w.name, items: linesFrom(form, "qty_done") }, v));
				await sp.uploadPicked(form, "Subcontract Daily Progress", name);
				sp.toast(__("Progress report {0} sent for review", [name]));
				ctx.reload();
			},
		});
	}

	function inspectionForm(w, items, ctx) {
		const form = el("div", { class: "sp-form" },
			el("div", {}, el("label", { class: "sp-sub", text: __("Quantity ready for inspection") }), qtyLines(items, "reported_qty", __("To inspect"), (r) => r.qty - r.accepted_qty)),
			el("div", { class: "sp-row2" }, sp.field({ name: "proposed_date", label: __("Proposed inspection date"), type: "date", min: sp.today() }),
				sp.field({ name: "location", label: __("Location on site") })),
			sp.field({ name: "remarks", label: __("Remarks"), type: "textarea" }),
			sp.filePicker(__("Photographs and documents"), true));
		form.querySelector("input[type=file]").multiple = true;
		sp.drawer(__("Request inspection for {0}", [w.name]), form, {
			submitLabel: __("Request inspection"),
			async submit() {
				const v = sp.values(form);
				const name = await sp.post("request_inspection", Object.assign({ work_order: w.name, items: linesFrom(form, "reported_qty") }, v));
				await sp.uploadPicked(form, "Subcontract Work Progress", name);
				sp.toast(__("Inspection {0} requested", [name]));
				ctx.reload();
			},
		});
	}

	async function materialForm(w, ctx) {
		const items = await sp.api("request_options", { work_order: w.name });
		const lines = el("tbody");
		const addLine = () => lines.append(el("tr", {}, el("td", {}, el("select", { "data-k": "item_code", "aria-label": __("Item") }, el("option", { value: "", text: __("Choose an item") }),
			items.map((i) => el("option", { value: i.name, text: i.item_name + " (" + i.name + ")" })))),
			el("td", {}, el("input", { type: "number", min: 0, step: "any", "data-k": "qty", "aria-label": __("Quantity") })),
			el("td", {}, el("input", { type: "text", "data-k": "remarks", "aria-label": __("Remarks"), style: "text-align:left" }))));
		addLine();
		const form = el("div", { class: "sp-form" },
			el("div", { class: "sp-table-wrap" }, el("table", { class: "sp-table sp-lines" }, el("thead", {}, el("tr", {}, el("th", { text: __("Item") }), el("th", { text: __("Quantity") }), el("th", { text: __("Remarks") }))), lines)),
			el("div", {}, sp.btn(__("Add another item"), addLine, "sm")),
			el("div", { class: "sp-row2" }, sp.field({ name: "required_by", label: __("Needed by"), type: "date", required: true, min: sp.today() }),
				sp.field({ name: "delivery_location", label: __("Deliver to") })),
			sp.field({ name: "remarks", label: __("Remarks"), type: "textarea" }),
			sp.filePicker(__("Supporting document")));
		sp.drawer(__("Request material for {0}", [w.name]), form, {
			async submit() {
				const v = sp.values(form);
				const rows = [...lines.querySelectorAll("tr")].map((tr) => ({ item_code: tr.querySelector("[data-k=item_code]").value, qty: +tr.querySelector("[data-k=qty]").value,
					remarks: tr.querySelector("[data-k=remarks]").value })).filter((r) => r.item_code && r.qty > 0);
				const name = await sp.post("create_material_request", { work_order: w.name, items: rows, required_by: v.required_by, delivery_location: v.delivery_location, remarks: v.remarks });
				await sp.uploadPicked(form, "Subcontract Material Request", name);
				sp.toast(__("Material request {0} sent", [name]));
				ctx.reload();
			},
		});
	}

	function receiptForm(issue, ctx) {
		const form = el("div", { class: "sp-form" },
			issue.items ? sp.table([[__("Item"), (r) => r.item_name || r.item_code], [__("Quantity"), (r) => sp.num(r.qty) + " " + (r.uom || ""), { num: true }]], issue.items) : null,
			sp.field({ name: "shortage", label: __("Something is short or damaged"), type: "check" }),
			sp.field({ name: "remarks", label: __("Remarks"), type: "textarea", help: __("Required when you report a shortage.") }),
			sp.filePicker(__("Delivery note or photographs"), true));
		sp.drawer(__("Confirm receipt of {0}", [issue.name]), form, {
			submitLabel: __("Confirm receipt"),
			async submit() {
				await sp.post("confirm_receipt", Object.assign({ allocation: issue.name }, sp.values(form)));
				await sp.uploadPicked(form, "Subcontract Material Allocation", issue.name);
				sp.toast(__("Receipt confirmed"));
				ctx.reload();
			},
		});
	}

	function variationForm(w, items, ctx) {
		const types = C() ? ["Time Extension", "Quantity Variation", "Extra Work", "Rate Revision", "Delay Claim", "Material Shortage Claim", "Additional Material", "Other Claim"]
			: ["Time Extension", "Quantity Variation"];
		const extra = el("div");
		const typeSel = el("select", { name: "variation_type", id: "f-variation_type", onchange: () => drawExtra() }, types.map((t) => el("option", { value: t, text: __(t) })));
		function drawExtra() {
			const t = typeSel.value;
			if (t === "Time Extension") fill(extra, sp.field({ name: "new_completion_date", label: __("New completion date"), type: "date", required: true, value: w.expected_completion_date }));
			else if (t === "Quantity Variation" || t === "Rate Revision") fill(extra, el("div", { class: "sp-table-wrap" }, el("table", { class: "sp-table sp-lines" },
				el("thead", {}, el("tr", {}, el("th", { text: __("Work") }), el("th", { class: "num", text: t === "Rate Revision" ? __("Current rate") : __("Current quantity") }),
					el("th", { class: "num", text: t === "Rate Revision" ? __("New rate") : __("New quantity") }))),
				el("tbody", {}, items.filter((r) => !r.is_additional || t === "Rate Revision").map((r) => el("tr", {}, el("td", { text: r.job_type + (r.description ? " – " + r.description : "") }),
					el("td", { class: "num", text: t === "Rate Revision" ? sp.money(r.rate, w.currency) : sp.num(r.qty) }),
					el("td", {}, el("input", { type: "number", min: 0, step: "any", "data-item": r.name, "data-field": t === "Rate Revision" ? "rate" : "qty" }))))))));
			else if (t === "Extra Work" || t === "Additional Material") fill(extra, el("div", { class: "sp-row2" }, sp.field({ name: "x_job_type", label: __("Work / item code"), required: true,
				help: __("The service or item code agreed with the company") }), sp.field({ name: "x_uom", label: __("Unit") })),
				el("div", { class: "sp-row2" }, sp.field({ name: "x_qty", label: __("Quantity"), type: "number", required: true, min: 0, step: "any" }),
					sp.field({ name: "x_rate", label: __("Proposed rate"), type: "number", min: 0, step: "any" })));
			else fill(extra, sp.field({ name: "claimed_amount", label: __("Amount claimed"), type: "number", required: true, min: 0, step: "any" }));
		}
		const form = el("div", { class: "sp-form" }, el("div", { class: "sp-field" }, el("label", { for: "f-variation_type", text: __("Type of request") + " *" }), typeSel),
			sp.field({ name: "description", label: __("Description and justification"), type: "textarea", required: true }), extra, sp.filePicker(__("Supporting evidence"), true));
		drawExtra();
		sp.drawer(__("Variation or claim on {0}", [w.name]), form, {
			async submit() {
				const v = sp.values(form);
				const t = typeSel.value;
				let rows = [];
				if (t === "Quantity Variation" || t === "Rate Revision") rows = [...form.querySelectorAll("input[data-item]")].filter((i) => i.value !== "").map((i) => ({ swo_item: i.dataset.item, [i.dataset.field]: +i.value }));
				if (t === "Extra Work" || t === "Additional Material") rows = [{ job_type: v.x_job_type, qty: +v.x_qty, rate: +v.x_rate || 0, uom: v.x_uom, description: v.description }];
				const name = await sp.post("submit_variation", { work_order: w.name, variation_type: t, description: v.description, items: rows,
					new_completion_date: v.new_completion_date, claimed_amount: v.claimed_amount });
				await sp.uploadPicked(form, "Subcontract Variation", name);
				sp.toast(__("Request {0} sent for review", [name]));
				ctx.reload();
			},
		});
	}

	async function invoiceForm(workOrder, ctx) {
		const b = await sp.api("billable", { work_order: workOrder });
		const ok = b.rows.filter((r) => r.billable_qty > 0);
		if (!ok.length) return sp.toast(__("Nothing is ready to invoice: only inspected and accepted work can be invoiced"), true);
		const form = el("div", { class: "sp-form" },
			el("div", { class: "sp-row2" }, sp.field({ name: "supplier_invoice_no", label: __("Your invoice number"), required: true }),
				sp.field({ name: "supplier_invoice_date", label: __("Invoice date"), type: "date", required: true, value: sp.today(), maxv: sp.today() })),
			sp.field({ name: "bill_type", label: __("Bill type"), type: "select", options: [{ value: "Running Bill", label: __("Running bill") }].concat(b.final_allowed ? [{ value: "Final Bill", label: __("Final bill") }] : []) }),
			el("div", { class: "sp-table-wrap" }, el("table", { class: "sp-table sp-lines" }, el("thead", {}, el("tr", {}, el("th", { text: __("Work") }), el("th", { class: "num", text: __("Rate") }),
				el("th", { class: "num", text: __("Can invoice") }), el("th", { class: "num", text: __("Invoice qty") }), el("th", { class: "num", text: __("Amount") }))),
			el("tbody", {}, ok.map((r) => {
				const amt = el("td", { class: "num" });
				return el("tr", {}, el("td", { text: r.job_type + (r.description ? " – " + r.description : "") }), el("td", { class: "num", text: sp.money(r.rate) }),
					el("td", { class: "num", text: sp.num(r.billable_qty) }),
					el("td", {}, el("input", { type: "number", min: 0, max: r.billable_qty, step: "any", "data-item": r.swo_item, value: r.billable_qty,
						oninput: (e) => { amt.textContent = sp.money((+e.target.value || 0) * r.rate); } })), (amt.textContent = sp.money(r.billable_qty * r.rate), amt));
			})))),
			el("small", { class: "sp-sub", text: b.retention_percentage ? __("Retention of {0}%, advances and agreed deductions are applied when the invoice is verified.", [b.retention_percentage]) : __("Advances and agreed deductions are applied when the invoice is verified.") }),
			sp.field({ name: "remarks", label: __("Remarks"), type: "textarea" }),
			sp.filePicker(__("Invoice PDF and supporting documents")));
		form.querySelector("input[type=file]").multiple = true;
		sp.drawer(__("Submit invoice for {0}", [workOrder]), form, {
			submitLabel: __("Submit for verification"),
			async submit() {
				const v = sp.values(form);
				const items = [...form.querySelectorAll("input[data-item]")].filter((i) => +i.value > 0).map((i) => ({ swo_item: i.dataset.item, qty: +i.value }));
				const name = await sp.post("submit_invoice", Object.assign({ work_order: workOrder, items }, v));
				await sp.uploadPicked(form, "Subcontractor Invoice Submission", name);
				sp.toast(__("Invoice submitted for verification"));
				ctx.reload();
			},
		});
	}

	function thread(workOrder, rows, ctx) {
		const box = el("div", { class: "sp-pad" }, rows.length ? rows.slice().reverse().map((m) => el("div", { class: "sp-msg" + (m.direction === "From Subcontractor" ? " sp-msg--mine" : "") },
			el("small", { text: (m.sender_name || "") + " · " + sp.date(m.creation) + (m.subcontract_work_order && !workOrder ? " · " + m.subcontract_work_order : "") }),
			m.subject ? el("b", { text: m.subject }) : null, el("div", { style: "white-space:pre-wrap", text: m.message }))) : sp.empty(__("No messages yet"), __("Write to the project team below.")));
		const input = el("textarea", { "aria-label": __("Message"), maxlength: 5000, placeholder: __("Write a message"), style: "width:100%;min-height:70px;padding:9px;border:1px solid var(--line-2);border-radius:8px" });
		const send = sp.btn(__("Send"), async () => {
			if (!input.value.trim()) return;
			send.disabled = true;
			try {
				await sp.post("post_message", { message: input.value, work_order: workOrder });
				sp.toast(__("Message sent"));
				ctx.reload();
			} catch (e) { sp.toast(e.message, true); send.disabled = false; }
		}, "primary", { disabled: ro() });
		sp.post("mark_messages_read", { work_order: workOrder }).catch(() => {});
		return sp.panel(__("Messages"), el("div", {}, box, el("div", { class: "sp-pad", style: "display:grid;gap:8px;border-top:1px solid var(--line)" }, input, el("div", {}, send))));
	}

	// ------------------------------------------------------------------ list pages
	P.progress = async function (ctx) {
		ctx.title(__("Progress reports"));
		const state = { page: 1 };
		const list = el("div");
		async function load(append) {
			const d = await sp.api("progress_reports", { page: state.page });
			state.more = d.more;
			if (!append) fill(list);
			list.append(sp.table([[__("Report"), (r) => r.name], [__("Work order"), (r) => sp.link("work-orders/" + encodeURIComponent(r.subcontract_work_order) + "?tab=2", r.subcontract_work_order)],
				[__("Date"), (r) => sp.date(r.report_date)], [__("Labour"), (r) => r.labour_deployed || "", { num: true }], [__("Delay"), (r) => r.delay_reason || (r.delay_reported ? __("Yes") : "")],
				[__("Status"), (r) => sp.badge(r.status)], [__("Review"), (r) => r.review_remarks || ""]], d.rows) || sp.empty(__("No progress reports yet"), __("Open a work order and choose Report progress.")), more(state, load));
		}
		fill(ctx.root, sp.panel(null, list));
		await load();
	};

	P.inspections = async function (ctx) {
		ctx.title(__("Inspections"));
		const d = await sp.api("inspections", {});
		fill(ctx.root, sp.panel(null, sp.table([[__("Inspection"), (r) => r.name], [__("Work order"), (r) => sp.link("work-orders/" + encodeURIComponent(r.subcontract_work_order), r.subcontract_work_order)],
			[__("Proposed"), (r) => sp.date(r.proposed_inspection_date)], [__("Submitted"), (r) => sp.num(r.items.reduce((a, x) => a + (+x.reported_qty || 0), 0)), { num: true }],
			[__("Accepted"), (r) => sp.num(r.items.reduce((a, x) => a + (+x.accepted_qty || 0), 0)), { num: true }],
			[__("Rejected / rework"), (r) => sp.num(r.items.reduce((a, x) => a + (+x.rejected_qty || 0) + (+x.rework_qty || 0), 0)), { num: true }],
			[__("Status"), (r) => sp.badge(r.inspection_status)], [__("Remarks"), (r) => [r.quality_remarks, r.corrective_action].filter(Boolean).join(" · ")]], d.rows)
			|| sp.empty(__("No inspections yet"), __("Open a work order and choose Request inspection when work is ready."))));
	};

	P.materials = async function (ctx) {
		ctx.title(__("Materials"));
		const d = await sp.api("materials", {});
		fill(ctx.root, el("div", { class: "sp-grid" },
			sp.panel(__("Company material with you"), sp.table([[__("Item"), (r) => r.item_name || r.item_code], [__("Quantity held"), (r) => sp.num(r.qty), { num: true }]], d.held)
				|| sp.empty(__("You hold no company material"), null)),
			sp.panel(__("Material issued to you"), sp.table([[__("Issue"), (r) => r.name], [__("Work order"), (r) => r.subcontract_work_order], [__("Date"), (r) => sp.date(r.posting_date)],
				[__("Items"), (r) => r.items.map((i) => sp.num(i.qty) + " × " + (i.item_name || i.item_code)).join(", ")],
				[__("Receipt"), (r) => (r.received_by_subcontractor ? sp.badge(r.shortage_reported ? "Shortage reported" : "Confirmed") : sp.btn(__("Confirm receipt"), () => receiptForm(r, ctx), "primary", { disabled: ro() }))]], d.issues)
				|| sp.empty(__("No material issued yet"), null)),
			sp.panel(__("Your material requests"), sp.table([[__("Request"), (r) => r.name], [__("Work order"), (r) => sp.link("work-orders/" + encodeURIComponent(r.subcontract_work_order) + "?tab=4", r.subcontract_work_order)],
				[__("Needed by"), (r) => sp.date(r.required_by)], [__("Items"), (r) => r.items.map((i) => sp.num(i.issued_qty) + "/" + sp.num(i.qty) + " " + (i.item_name || i.item_code)).join(", ")],
				[__("Status"), (r) => sp.badge(r.status)], [__("Review"), (r) => r.review_remarks || ""]], d.requests)
				|| sp.empty(__("No material requests"), __("Open a work order and choose Request material."))),
			sp.panel(__("Material and equipment you supply"), sp.table([[__("Work order"), (r) => r.work_order], [__("Item"), (r) => r.job_type], [__("Description"), (r) => r.description || ""],
				[__("Quantity"), (r) => sp.num(r.qty), { num: true }]], d.own_supplied) || sp.empty(__("Nothing listed"), null))));
	};

	P.variations = async function (ctx) {
		ctx.title(__("Variations and claims"));
		const d = await sp.api("variations", {});
		fill(ctx.root, el("div", { class: "sp-banner sp-banner--info", text: __("To raise a new request, open the work order and go to Variations.") }),
			sp.panel(null, sp.table([[__("Request"), (r) => r.name], [__("Work order"), (r) => sp.link("work-orders/" + encodeURIComponent(r.subcontract_work_order), r.subcontract_work_order)],
				[__("Type"), (r) => r.variation_type], [__("Date"), (r) => sp.date(r.request_date)], C() ? [__("Claimed"), (r) => (r.claimed_amount ? sp.money(r.claimed_amount) : ""), { num: true }] : null,
				C() ? [__("Approved change"), (r) => (r.status === "Approved" ? sp.money(r.value_change) : ""), { num: true }] : null, [__("Status"), (r) => sp.badge(r.status)],
				[__("Remarks"), (r) => r.external_remarks || ""]].filter(Boolean), d.rows) || sp.empty(__("No variations or claims yet"), null)));
	};

	P.invoices = async function (ctx) {
		ctx.title(__("Invoices"));
		const d = await sp.api("invoices", {});
		const wos = (await sp.api("work_orders", { status: "open" })).rows;
		const pick = el("select", { "aria-label": __("Work order") }, el("option", { value: "", text: __("Choose the work order to invoice") }), wos.map((w) => el("option", { value: w.name, text: w.name + (w.work_description ? " – " + w.work_description : "") })));
		fill(ctx.root, !ro() ? el("div", { class: "sp-filters" }, pick, sp.btn(__("Submit invoice"), () => (pick.value ? invoiceForm(pick.value, ctx) : sp.toast(__("Choose a work order first"), true)), "primary")) : null,
			sp.panel(null, sp.table([[__("Invoice"), (r) => el("div", {}, el("b", { text: r.supplier_invoice_no }), el("div", { class: "sp-sub", text: r.name }))],
				[__("Work order"), (r) => r.subcontract_work_order], [__("Date"), (r) => sp.date(r.supplier_invoice_date)], [__("Type"), (r) => __(r.bill_type)],
				[__("Claimed"), (r) => sp.money(r.total_claimed), { num: true }], [__("Payable"), (r) => (r.payable != null ? sp.money(r.payable) : ""), { num: true }],
				[__("Outstanding"), (r) => (r.outstanding != null ? sp.money(r.outstanding) : ""), { num: true }], [__("Status"), (r) => sp.badge(r.payment_status || r.status)],
				[__("Remarks"), (r) => r.review_remarks || ""]], d.rows) || sp.empty(__("No invoices yet"), __("Invoice accepted work from here or from the work order."))));
	};

	P.payments = async function (ctx) {
		ctx.title(__("Payments"));
		const d = await sp.api("payments", {});
		const s = d.summary;
		fill(ctx.root, el("div", { class: "sp-kpis" }, sp.kpi(__("Outstanding"), sp.money(s.outstanding)), sp.kpi(__("Paid"), sp.money(s.paid)),
			sp.kpi(__("Retention held"), sp.money(s.retention_held)), sp.kpi(__("Advance not yet adjusted"), sp.money(s.unadjusted_advance))),
		el("div", { class: "sp-grid" },
			sp.panel(__("Invoices"), sp.table([[__("Invoice"), (r) => r.bill_no || r.name], [__("Work order"), (r) => r.subcontract_work_order], [__("Date"), (r) => sp.date(r.posting_date)],
				[__("Due"), (r) => sp.date(r.due_date)], [__("Total"), (r) => sp.money(r.grand_total), { num: true }], [__("Advance adjusted"), (r) => sp.money(r.total_advance), { num: true }],
				[__("Outstanding"), (r) => sp.money(r.outstanding_amount), { num: true }], [__("Status"), (r) => sp.badge(r.status)]], d.invoices) || sp.empty(__("No invoices yet"), null)),
			sp.panel(__("Payments received"), sp.table([[__("Payment"), (r) => r.name], [__("Date"), (r) => sp.date(r.posting_date)], [__("Reference"), (r) => r.reference_no || ""],
				[__("Mode"), (r) => r.mode_of_payment || ""], [__("Amount"), (r) => sp.money(r.paid_amount), { num: true }],
				[__("Advice"), (r) => el("a", { href: "/api/method/thinknxg_rental.portal.subcontractor.payment_advice?" + new URLSearchParams({ name: r.name, supplier: sp.state.supplier }) }, sp.icon("download"), " PDF")]], d.payments)
				|| sp.empty(__("No payments yet"), null))));
	};

	P.messages = async function (ctx) {
		ctx.title(__("Messages"));
		const d = await sp.api("messages", {});
		fill(ctx.root, thread(null, d.rows, ctx));
	};

	P.profile = async function (ctx) {
		ctx.title(__("Company and documents"));
		const d = await sp.api("profile", {});
		const s = d.supplier;
		const add = () => {
			const opts = ["Business Registration", "Tax Registration", "Insurance Certificate", "Safety Certificate", "Licence", "Bank Details", "Contract Document", "Other"];
			const form = el("div", { class: "sp-form" }, sp.field({ name: "document_type", label: __("Document"), type: "select", options: opts.map((o) => ({ value: o, label: __(o) })) }),
				sp.field({ name: "document_no", label: __("Document number") }),
				el("div", { class: "sp-row2" }, sp.field({ name: "issue_date", label: __("Issue date"), type: "date" }), sp.field({ name: "expiry_date", label: __("Expiry date"), type: "date" })),
				sp.filePicker(__("Scan of the document")));
			sp.drawer(__("Upload a document"), form, {
				async submit() {
					const row = await sp.post("add_compliance_document", sp.values(form));
					await sp.uploadPicked(form, "Supplier Compliance", row);
					sp.toast(__("Document uploaded. The company will verify it."));
					ctx.reload();
				},
			});
		};
		fill(ctx.root, el("div", { class: "sp-grid sp-grid--2" },
			sp.panel(__("Company"), el("div", { class: "sp-pad" }, sp.dl([[__("Name"), s.supplier_name], [__("Approval"), sp.badge(s.subcontractor_approval_status)], [__("Tax number"), s.tax_id],
				[__("Email"), s.email_id], [__("Phone"), s.mobile_no], [__("Website"), s.website], [__("Classification"), s.business_classification], [__("Provides"), s.subcontractor_type],
				[__("Specializations"), s.specializations], [__("Service areas"), s.service_areas], [__("Operating locations"), s.operating_locations]]))),
			sp.panel(__("Portal users"), sp.table([[__("Name"), (r) => r.full_name], [__("Email"), (r) => r.email], [__("Access"), (r) => __(r.access_level)],
				[__("Status"), (r) => sp.badge(r.enabled ? "Active" : "Suspended")]], d.contacts)),
			sp.panel(__("Compliance documents"), sp.table([[__("Document"), (r) => r.document_type], [__("Number"), (r) => r.document_no || ""], [__("Expires"), (r) => sp.date(r.expiry_date)],
				[__("Status"), (r) => sp.badge(r.compliance_status === "No Expiry" ? null : r.compliance_status)], [__("Verified"), (r) => (r.verified ? __("Yes") : __("Not yet"))]], d.documents)
				|| sp.empty(__("No documents on file"), null), !ro() ? sp.btn(__("Upload a document"), add, "primary") : null),
			sp.panel(__("Agreements"), sp.table([[__("Agreement"), (r) => r.name], [__("Type"), (r) => __(r.agreement_type)], [__("From"), (r) => sp.date(r.start_date)],
				[__("To"), (r) => sp.date(r.end_date)], [__("Status"), (r) => sp.badge(r.status)]], d.agreements) || sp.empty(__("No agreements"), null))));
	};
})();
