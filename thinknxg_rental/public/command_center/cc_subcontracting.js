// Command Center, Subcontracting section: overview with action centre, work orders (list and 360), subcontractors
// (list and 360 with account statement), and comparison. Data from command_center/subcontracting.py; every action
// runs the document's own role-checked workflow method on the server.
(function () {
	const cc = window.cc;
	const { el, __ } = cc;
	const C = cc.colors;
	const P = (cc.pages = cc.pages || {});
	const API = "thinknxg_rental.command_center.subcontracting.";
	const call = (m, a, o) => cc.call(API + m, a, o);
	const post = (m, a) => cc.call(API + m, a, { post: true });

	const load = async (ctx, fn) => {
		ctx.root.replaceChildren(cc.skeleton(8));
		try {
			return await fn();
		} catch (e) {
			ctx.setTitle(__("No access"));
			ctx.root.replaceChildren(cc.failure(e));
			e.shown = true;
			throw e;
		}
	};
	const table = (head, rows, empty) => rows.length ? el("div", { class: "cc-tablewrap" }, el("table", { class: "cc-table cc-table--cards" },
		el("thead", {}, el("tr", {}, head.map((h) => el("th", { scope: "col", class: h.num ? "cc-num" : null, text: h.label ?? h })))),
		el("tbody", {}, rows.map((r) => el("tr", r.href ? { "data-href": r.href, style: "cursor:pointer", onclick: (e) => { if (!e.target.closest("a,button,input")) cc.go(r.href); } } : {},
			r.cells.map((c, i) => el("td", { class: head[i] && head[i].num ? "cc-num" : null, "data-label": head[i] && (head[i].label ?? head[i]) }, c))))))) : cc.empty(empty || __("Nothing here"));
	const num = (label) => ({ label, num: true });
	const desk = (href, label) => el("a", { href, target: "_blank", rel: "noopener" }, label);
	const sc = (path) => "subcontracting/" + path;
	const tabsEl = (items, current, onpick) => el("div", { class: "cc-tabs", role: "tablist" }, items.map(([v, l]) => el("button", { type: "button", role: "tab", "aria-selected": v === current ? "true" : "false", text: l, onclick: () => onpick(v) })));
	const LABELS = { approve: __("Approve"), reject: __("Reject"), send: __("Send to subcontractor"), hold: __("Put on hold"), resume: __("Resume"), start: __("Start work"),
		return: __("Return for correction"), start_inspection: __("Schedule inspection"), verify: __("Verify and invoice"), issue: __("Issue material"),
		submit_for_approval: __("Send for approval") };
	const NEEDS_REMARK = { reject: __("Reason"), return: __("What needs correcting"), hold: __("Reason for the hold") };

	async function runAction(doctype, name, action, after, item) {
		if (action === "issue") {
			window.open("/app/subcontract-material-request/" + encodeURIComponent(name), "_blank", "noopener");
			return;
		}
		let remarks = null, amount = null;
		if (NEEDS_REMARK[action]) {
			const v = await cc.prompt(LABELS[action] + " · " + name, [{ fieldname: "remarks", label: NEEDS_REMARK[action], fieldtype: "Small Text", reqd: 1 }], LABELS[action]);
			if (!v) return;
			remarks = v.remarks;
		} else if (doctype === "Subcontract Variation" && action === "approve") {
			const v = await cc.prompt(__("Approve {0}", [name]), [{ fieldname: "amount", label: __("Approved amount (claims only)"), fieldtype: "Data" },
				{ fieldname: "remarks", label: __("Remarks to the subcontractor"), fieldtype: "Small Text" }], __("Approve"));
			if (!v) return;
			remarks = v.remarks;
			amount = v.amount;
		} else if (["approve", "verify", "send"].includes(action)) {
			const ok = await cc.confirm(LABELS[action], __("{0} {1}?", [LABELS[action], name]), LABELS[action]);
			if (!ok) return;
		}
		try {
			if (doctype === "Subcontract Work Order" && (action === "submit_for_approval" || !item)) await post("wo_action", { name, action, remarks });
			else await post("act", { doctype, name, action, remarks, amount });
			cc.toast(__("Done"), "good");
			if (cc.refreshBadges) cc.refreshBadges();
			after();
		} catch (e) {
			/* the server message is already shown */
		}
	}

	// ================================================================== overview
	P.scOverview = async function (ctx) {
		ctx.setTitle(__("Overview"));
		const d = await load(ctx, () => call("dashboard"));
		const cur = cc.boot.currency;
		const kpis = el("dl", { class: "cc-kpis" }, d.kpis.map((k) => {
			const a = el("a", { class: "cc-kpi" + (k.tone === "bad" && k.value ? " cc-kpi--alert" : ""), href: cc.base + "/" + k.route },
				el("dt", { text: k.label }), el("dd", { text: k.money ? cc.money(k.value, cur, true) : cc.qty(k.value) }));
			a.addEventListener("click", (e) => cc.linkClick(e, a.getAttribute("href")));
			return a;
		}));
		const ch = d.charts;
		const groups = {};
		d.actions.forEach((a) => (groups[a.group] = groups[a.group] || []).push(a));
		const actionCentre = Object.keys(groups).length ? el("div", {}, Object.entries(groups).map(([g, rows]) => el("div", { style: "margin-bottom:14px" },
			el("h3", { style: "font-size:13px;margin:0 0 6px;color:var(--cc-mute,#66768c)", text: g + " (" + rows.length + ")" }),
			table([__("Item"), __("Detail"), ""], rows.slice(0, 8).map((a) => ({ cells: [a.route ? cc.link(a.route, a.title) : desk(a.desk, a.title), a.sub || "",
				el("div", { class: "cc-actions" }, a.actions.map((act) => cc.btn(LABELS[act] || act, () => runAction(a.doctype, a.name, act, () => ctx.reload(), true),
					{ sm: true, kind: act === "reject" || act === "return" ? "ghost" : "primary" })), cc.btn(__("Open"), null, { sm: true, kind: "ghost", href: a.desk, target: "_blank", icon: "external-link" }))] }))))))
			: cc.empty(__("Nothing is waiting"), __("Approvals, reviews and requests from subcontractors appear here."));
		const fin = ch.finance;
		const finRows = [[__("Contract value"), fin.contract, C.s1], [__("Certified"), fin.certified, C.s3], [__("Invoiced"), fin.invoiced, C.s4], [__("Paid"), fin.paid, C.s6],
			[__("Outstanding"), fin.outstanding, C.s8], [__("Retention held"), fin.retention, C.s7], [__("Advances paid"), fin.advance_paid, C.s2], [__("Advances recovered"), fin.advance_recovered, C.s5]];
		const reports = [["sc-register", __("Subcontractor Register")], ["sc-performance", __("Performance")], ["sc-work-orders", __("Work orders by subcontractor")],
			["sc-hoc", __("By Hire Order Contract")], ["sc-progress", __("Work progress")], ["sc-delayed", __("Delayed work orders")], ["sc-material", __("Material issue and return")],
			["sc-pending-completion", __("Pending completion approval")], ["sc-invoices", __("Invoice register")], ["sc-outstanding", __("Outstanding payments")],
			["sc-payments", __("Payments")], ["subcontract-retention", __("Retention and advances")], ["sc-variations", __("Variations")], ["sc-cost", __("Cost analysis")],
			["sc-cost-monitor", __("Cost monitor and forecast")], ["sc-profitability", __("Profitability")], ["sc-labour", __("Labour cost")], ["sc-equipment", __("Equipment cost")],
			["sc-statement", __("Account statement")]];
		ctx.root.replaceChildren(
			cc.pagehead(__("Subcontracting"), __("Work orders, progress, inspections, materials and payments of your subcontractors."),
				[cc.btn(__("New work order"), null, { href: "/app/subcontract-work-order/new", target: "_blank", kind: "primary", icon: "plus" }),
					cc.btn(__("Settings"), null, { href: d.settings_url, target: "_blank", kind: "ghost", icon: "settings" })]),
			kpis,
			cc.panel(__("Action centre"), actionCentre),
			el("div", { class: "cc-grid cc-grid--2" },
				cc.chart.panel(__("Work orders by status"), null, () => cc.chart.hbars(ch.status.map((r) => ({ label: __(r.status), route: sc("work-orders?status=" + encodeURIComponent(r.status)),
					segments: [{ name: __("Work orders"), value: r.n, color: C.s1 }], text: cc.qty(r.n) }))),
					() => cc.chart.table([__("Status"), __("Work orders"), __("Value")], ch.status.map((r) => [__(r.status), cc.qty(r.n), cc.money(r.value, cur)]))),
				cc.chart.panel(__("Financial position"), __("Certified = accepted work at work-order rates; invoiced, paid and outstanding come from the Purchase Invoices."),
					() => cc.chart.hbars(finRows.map(([l, v, c]) => ({ label: l, segments: [{ name: l, value: v, color: c }], text: cc.money(v, cur, true) })), { fmt: (v) => cc.money(v, cur) }),
					() => cc.chart.table([__("Measure"), __("Amount")], finRows.map(([l, v]) => [l, cc.money(v, cur)]))),
				cc.chart.panel(__("Monthly work order value"), __("Last 12 months, by order date"), () => cc.chart.xy({ labels: ch.monthly.map((m) => m.label),
					series: [{ name: __("Value"), values: ch.monthly.map((m) => m.value), color: C.s1 }], kind: "bars", fmt: (v) => cc.money(v, cur) }),
					() => cc.chart.table([__("Month"), __("Work orders"), __("Value")], ch.monthly.map((m) => [m.label, cc.qty(m.n), cc.money(m.value, cur)]))),
				cc.chart.panel(__("Planned vs actual completion"), __("Work orders due and completed per month"), () => cc.chart.xy({ labels: ch.completion.map((m) => m.label),
					series: [{ name: __("Planned"), values: ch.completion.map((m) => m.planned), color: C.s4 }, { name: __("Completed"), values: ch.completion.map((m) => m.actual), color: C.s3 }], kind: "bars" }),
					() => cc.chart.table([__("Month"), __("Planned"), __("Completed")], ch.completion.map((m) => [m.label, m.planned, m.actual]))),
				cc.chart.panel(__("Work progress by project"), __("Value accepted and reported against value ordered"), () => ch.progress.length ? cc.chart.hbars(ch.progress.map((r) => ({ label: r.label,
					segments: [{ name: __("Accepted"), value: r.accepted, color: C.s3 }, { name: __("Reported, not yet accepted"), value: Math.max(r.reported - r.accepted, 0), color: C.s4 },
						{ name: __("Not started"), value: Math.max(r.ordered - Math.max(r.reported, r.accepted), 0), color: "#d5dce6" }], text: (r.ordered ? Math.round((100 * r.accepted) / r.ordered) : 0) + "%" })), { fmt: (v) => cc.money(v, cur) }) : cc.empty(__("No work in progress")),
					() => cc.chart.table([__("Project"), __("Ordered"), __("Reported"), __("Accepted")], ch.progress.map((r) => [r.label, cc.money(r.ordered, cur), cc.money(r.reported, cur), cc.money(r.accepted, cur)]))),
				cc.chart.panel(__("Top subcontractors"), __("By work order value"), () => ch.subcontractor.length ? cc.chart.hbars(ch.subcontractor.map((r) => ({ label: r.label, route: sc("subcontractors/" + encodeURIComponent(r.key)),
					segments: [{ name: __("Value"), value: r.value, color: C.s7 }], text: cc.money(r.value, cur, true) })), { fmt: (v) => cc.money(v, cur) }) : cc.empty(__("No work orders yet")),
					() => cc.chart.table([__("Subcontractor"), __("Work orders"), __("Value")], ch.subcontractor.map((r) => [r.label, r.n, cc.money(r.value, cur)]))),
				cc.chart.panel(__("Work orders by project"), null, () => ch.project.length ? cc.chart.hbars(ch.project.map((r) => ({ label: r.label, segments: [{ name: __("Value"), value: r.value, color: C.s2 }],
					text: cc.money(r.value, cur, true) })), { fmt: (v) => cc.money(v, cur) }) : cc.empty(__("No work orders yet")),
					() => cc.chart.table([__("Project"), __("Work orders"), __("Value")], ch.project.map((r) => [r.label, r.n, cc.money(r.value, cur)]))),
				cc.panel(__("Delayed and rejected work"), el("div", {}, table([__("Work order"), __("Subcontractor"), __("Due")], d.delayed.map((r) => ({ href: cc.base + "/" + sc("work-orders/" + encodeURIComponent(r.name)),
					cells: [r.name, r.supplier_name, cc.date(r.expected_completion_date)] })), __("No delayed work orders")),
					d.rejected.length ? table([__("Inspection"), __("Work order"), __("Result")], d.rejected.map((r) => ({ href: cc.base + "/" + sc("work-orders/" + encodeURIComponent(r.subcontract_work_order)),
						cells: [r.name, r.subcontract_work_order, cc.pill(r.inspection_status)] }))) : null))),
			cc.panel(__("Reports"), el("div", { class: "cc-actions", style: "flex-wrap:wrap" }, reports.map(([k, l]) => cc.btn(l, null, { href: cc.base + "/reports/" + k, sm: true, kind: "ghost", icon: "file-chart-column" })))));
	};

	// ================================================================== work orders
	const WO_TABS = [["", __("All")], ["approval", __("Awaiting approval")], ["Sent to Subcontractor", __("Awaiting acceptance")], ["progress", __("In progress")],
		["delayed", __("Delayed")], ["on-schedule", __("On schedule")], ["Completed", __("Completed")], ["On Hold", __("On hold")], ["Closed", __("Closed")]];
	P.scWorkOrders = async function (ctx) {
		ctx.setTitle(__("Work Orders"));
		const q = new URLSearchParams(ctx.query || "");
		const f = { status: q.get("status") || "", search: q.get("search") || "", project: q.get("project") || "", supplier: q.get("supplier") || "", site: q.get("site") || "",
			manager: q.get("manager") || "", from_date: q.get("from") || "", to_date: q.get("to") || "" };
		const d = await load(ctx, () => call("work_orders", f));
		const go = (patch) => {
			const p = new URLSearchParams(ctx.query || "");
			Object.entries(patch).forEach(([k, v]) => (v ? p.set(k, v) : p.delete(k)));
			cc.go(cc.base + "/" + ctx.path + (p.toString() ? "?" + p : ""), { replace: true });
		};
		const input = (k, ph, type) => el("input", { type: type || "search", value: f[k === "from" ? "from_date" : k === "to" ? "to_date" : k], placeholder: ph, "aria-label": ph, onchange: (e) => go({ [k]: e.target.value }) });
		const cur = cc.boot.currency;
		ctx.root.replaceChildren(
			cc.pagehead(__("Work Orders"), __("Every subcontract work order with its value, progress and dates."), d.can_create ? [cc.btn(__("New work order"), null, { href: "/app/subcontract-work-order/new", target: "_blank", kind: "primary", icon: "plus" })] : []),
			tabsEl(WO_TABS, f.status, (v) => go({ status: v })),
			el("div", { class: "cc-filters", style: "display:flex;gap:8px;flex-wrap:wrap;margin:10px 0" }, input("search", __("Search")), input("project", __("Project")), input("supplier", __("Subcontractor ID")),
				input("site", __("Site")), input("manager", __("Manager (user)")), input("from", __("From"), "date"), input("to", __("To"), "date")),
			cc.panel(null, table([__("Work order"), __("Subcontractor"), __("Project / site"), __("Work"), num(__("Value")), num(__("Completed")), num(__("Progress")), __("Start"), __("Due"), __("Status"), __("Approval")],
				d.rows.map((r) => ({ href: cc.base + "/" + sc("work-orders/" + encodeURIComponent(r.name)), cells: [el("b", { text: r.name }), r.supplier_name, [r.project, r.rental_site].filter(Boolean).join(" · "),
					r.work_description || r.subcontract_type, cc.money(r.final_contract_value, r.currency || cur), cc.money(r.completed_value, r.currency || cur), r.progress + "%", cc.date(r.start_date),
					el("span", { style: r.delayed ? "color:var(--cc-bad,#b42318);font-weight:600" : null, text: cc.date(r.expected_completion_date) }), cc.pill(r.status), cc.pill(r.approval)] })),
				__("No work orders match"))));
	};

	P.scWorkOrder = async function (ctx) {
		const d = await load(ctx, () => call("work_order", { name: ctx.name }));
		const w = d.doc;
		const cur = w.currency || cc.boot.currency;
		ctx.setTitle(w.name, [{ route: sc("work-orders"), label: __("Work Orders") }]);
		const q = new URLSearchParams(ctx.query || "");
		const tab = q.get("tab") || "overview";
		const x = d.cost;
		const docRow = (dt, cols) => (r) => ({ cells: [desk("/app/" + dt + "/" + encodeURIComponent(r.name), r.name)].concat(cols.map((c) => c(r))) });
		const newBtn = (dt, label) => cc.btn(label, null, { href: d.new[dt], target: "_blank", sm: true, icon: "plus" });
		const TABS = {
			overview: () => el("div", { class: "cc-grid cc-grid--2" },
				cc.panel(__("Work order"), el("dl", { class: "cc-dl" }, [[__("Subcontractor"), cc.link(sc("subcontractors/" + encodeURIComponent(w.supplier)), w.supplier_name)],
					[__("Agreement"), w.agreement], [__("Hire Order Contract"), w.hire_order_contract], [__("Project"), w.project], [__("Customer"), w.customer], [__("Site"), w.rental_site],
					[__("Priority"), w.priority], [__("Type"), w.subcontract_type], [__("Order date"), cc.date(w.contract_date)], [__("Planned start"), cc.date(w.start_date)],
					[__("Planned completion"), cc.date(w.expected_completion_date)], [__("Actual start"), cc.date(w.actual_start_date)], [__("Actual completion"), cc.date(w.actual_completion_date)],
					[__("Project manager"), w.project_manager], [__("Site engineer"), w.site_engineer], [__("Coordinator"), w.coordinator], [__("Sent to subcontractor"), w.sent_on ? cc.datetime(w.sent_on) : null],
					[__("Subcontractor response"), w.subcontractor_response], [__("Confirmed start"), cc.date(w.confirmed_start_date)], [__("Hold reason"), w.hold_reason]]
					.filter((p) => p[1]).flatMap((p) => [el("dt", { text: p[0] }), el("dd", {}, p[1])]))),
				cc.panel(__("Contract cost"), el("div", {}, cc.chart.hbars([[__("Revised value"), x.revised, C.s1], [__("Certified"), x.certified, C.s3], [__("Invoiced"), x.invoiced, C.s4],
					[__("Paid"), x.paid, C.s6]].map(([l, v, c]) => ({ label: l, segments: [{ name: l, value: v, color: c }], text: cc.money(v, cur, true) })), { fmt: (v) => cc.money(v, cur) }),
				el("dl", { class: "cc-dl" }, [[__("Original value"), x.original], [__("Approved variations"), x.approved_variations], [__("Revised value"), x.revised], [__("Completed (reported)"), x.completed],
					[__("Certified"), x.certified], [__("Invoiced"), x.invoiced], [__("Paid"), x.paid], [__("Retention held"), x.retention], [__("Advance paid"), x.advance_paid],
					[__("Advance recovered"), x.advance_recovered], [__("Outstanding"), x.outstanding], [__("Forecast final cost"), x.forecast]].flatMap((p) => [el("dt", { text: p[0] }), el("dd", { text: cc.money(p[1], cur) })])
					.concat([el("dt", { text: __("Budget used (certified / revised)") }), el("dd", { text: x.utilization + "%" })]))))),
			scope: () => cc.panel(__("Scope and items"), table([__("Work"), __("Category"), num(__("Ordered")), num(__("Rate")), num(__("Amount")), num(__("Reported")), num(__("Accepted")), num(__("Rejected")), num(__("Invoiced")), __("Progress")],
				d.items.map((r) => ({ cells: [el("div", {}, el("b", { text: r.job_type }), el("div", { class: "cc-sub", text: (r.description || "") + (r.is_additional ? " · " + __("Additional") + (r.variation ? " (" + r.variation + ")" : "") : "") })),
					r.work_category, cc.qty(r.qty), cc.money(r.rate, cur), cc.money(r.amount, cur), cc.qty(r.reported_qty), cc.qty(r.accepted_qty), cc.qty(r.rejected_qty), cc.qty(r.invoiced_qty),
					cc.chart.tube([{ name: __("Accepted"), value: r.accepted_qty, color: C.s3 }, { name: __("Reported"), value: Math.max(r.reported_qty - r.accepted_qty, 0), color: C.s4 },
						{ name: __("Open"), value: Math.max(r.qty - Math.max(r.reported_qty, r.accepted_qty), 0), color: "#d5dce6" }])] })))),
			progress: () => cc.panel(__("Progress reports"), table([__("Report"), __("Date"), num(__("Labour")), __("Delay"), __("From"), __("Status")],
				d.docs.progress.map(docRow("subcontract-daily-progress", [(r) => cc.date(r.report_date), (r) => r.labour_deployed || "", (r) => (r.delay_reported ? __("Yes") : ""), (r) => r.source, (r) => cc.pill(r.status)])),
				__("No progress reported yet")), { actions: [newBtn("Subcontract Daily Progress", __("New report"))] }),
			materials: () => el("div", { class: "cc-grid" },
				cc.panel(__("With the subcontractor"), table([__("Item"), num(__("Issued")), num(__("Installed")), num(__("Returned")), num(__("Damaged")), num(__("Missing")), num(__("Outstanding"))],
					d.materials.map((m) => ({ cells: [m.item_code, cc.qty(m.issued), cc.qty(m.installed), cc.qty(m.returned), cc.qty(m.damaged), cc.qty(m.missing), cc.qty(m.outstanding)] })), __("No company material issued"))),
				cc.panel(__("Material requests"), table([__("Request"), __("Requested"), __("Needed by"), __("From"), __("Status")], d.docs.material_requests.map(docRow("subcontract-material-request",
					[(r) => cc.date(r.request_date), (r) => cc.date(r.required_by), (r) => r.source, (r) => cc.pill(r.status)])), __("No requests")), { actions: [newBtn("Subcontract Material Request", __("New request"))] }),
				cc.panel(__("Issues"), table([__("Issue"), __("Date"), __("Stock Entry"), __("Receipt")], d.docs.issues.map(docRow("subcontract-material-allocation", [(r) => cc.date(r.posting_date),
					(r) => (r.stock_entry ? desk("/app/stock-entry/" + r.stock_entry, r.stock_entry) : ""), (r) => (r.received_by_subcontractor ? cc.pill(r.shortage_reported ? __("Shortage reported") : __("Confirmed"), r.shortage_reported ? "warn" : "good") : cc.pill(__("Not confirmed"), "warn"))])),
					__("No issues")), { actions: [newBtn("Subcontract Material Allocation", __("Issue material"))] }),
				cc.panel(__("Returns"), table([__("Return"), __("Date"), num(__("Recovery"))], d.docs.returns.map(docRow("subcontract-material-return", [(r) => cc.date(r.posting_date), (r) => cc.money(r.total_recovery, cur)])),
					__("No returns")), { actions: [newBtn("Subcontract Material Return", __("Record a return"))] })),
			inspections: () => el("div", { class: "cc-grid" },
				cc.panel(__("Inspections"), table([__("Inspection"), __("Date"), __("Proposed"), __("From"), __("Result")], d.docs.inspections.map(docRow("subcontract-work-progress",
					[(r) => cc.date(r.progress_date), (r) => cc.date(r.proposed_inspection_date), (r) => r.source, (r) => cc.pill(r.inspection_status)])), __("No inspections")),
					{ actions: [newBtn("Subcontract Work Progress", __("New inspection"))] }),
				cc.panel(__("Completion certificates"), table([__("Certificate"), __("Date"), num(__("Certified value"))], d.docs.completion.map(docRow("subcontract-completion-report",
					[(r) => cc.date(r.completion_date), (r) => cc.money(r.certified_value, cur)])), __("Not certified yet")), { actions: [newBtn("Subcontract Completion Report", __("Certify completion"))] })),
			variations: () => cc.panel(__("Variations and claims"), table([__("Request"), __("Type"), __("Requested"), num(__("Value change")), __("From"), __("Status")],
				d.docs.variations.map(docRow("subcontract-variation", [(r) => __(r.variation_type), (r) => cc.date(r.request_date), (r) => cc.money(r.value_change || r.claimed_amount, cur), (r) => r.source, (r) => cc.pill(r.status)])),
				__("No variations")), { actions: [newBtn("Subcontract Variation", __("New variation"))] }),
			invoices: () => el("div", { class: "cc-grid" },
				cc.panel(__("Supplier invoices"), table([__("Submission"), __("Invoice no."), __("Date"), num(__("Claimed")), __("Purchase Invoice"), __("Status")], d.docs.submissions.map(docRow("subcontractor-invoice-submission",
					[(r) => r.supplier_invoice_no, (r) => cc.date(r.supplier_invoice_date), (r) => cc.money(r.total_claimed, cur), (r) => (r.purchase_invoice ? desk("/app/purchase-invoice/" + r.purchase_invoice, r.purchase_invoice) : ""), (r) => cc.pill(r.status)])),
					__("No invoices submitted")), { actions: [newBtn("Subcontractor Invoice Submission", __("Record an invoice"))] }),
				cc.panel(__("Settlements (progress certificates)"), table([__("Settlement"), __("Date"), __("Type"), num(__("Certified")), num(__("Payable")), __("Purchase Invoice")], d.docs.settlements.map(docRow("subcontract-settlement",
					[(r) => cc.date(r.posting_date), (r) => r.settlement_type, (r) => cc.money(r.certified_value, cur), (r) => cc.money(r.final_payable, cur), (r) => (r.purchase_invoice ? desk("/app/purchase-invoice/" + r.purchase_invoice, r.purchase_invoice) : "")])), __("No settlements"))),
				cc.panel(__("Purchase invoices"), table([__("Invoice"), __("Supplier bill"), __("Date"), num(__("Total")), num(__("Outstanding")), __("Status")], d.docs.purchase_invoices.map(docRow("purchase-invoice",
					[(r) => r.bill_no || "", (r) => cc.date(r.posting_date), (r) => cc.money(r.grand_total, cur), (r) => cc.money(r.outstanding_amount, cur), (r) => cc.pill(r.status)])), __("No purchase invoices")))),
			payments: () => cc.panel(__("Payments"), table([__("Payment"), __("Date"), __("Mode"), __("Reference"), num(__("Amount")), num(__("Unallocated (advance)"))], d.docs.payments.map(docRow("payment-entry",
				[(r) => cc.date(r.posting_date), (r) => r.mode_of_payment || "", (r) => r.reference_no || "", (r) => cc.money(r.paid_amount, cur), (r) => cc.money(r.unallocated_amount, cur)])), __("No payments"))),
			communication: () => {
				const box = el("textarea", { "aria-label": __("Message"), placeholder: __("Write to the subcontractor (shown in their portal)"), style: "width:100%;min-height:70px" });
				return el("div", { class: "cc-grid cc-grid--2" },
					cc.panel(__("Messages with the subcontractor"), el("div", {}, d.messages.length ? d.messages.map((m) => el("div", { style: "padding:8px 0;border-bottom:1px solid var(--cc-line,#e2e7ee)" },
						el("div", { class: "cc-sub", text: (m.direction === "From Subcontractor" ? "← " : "→ ") + (m.sender_name || "") + " · " + cc.datetime(m.creation) }), m.subject ? el("b", { text: m.subject }) : null,
						el("div", { style: "white-space:pre-wrap", text: m.message }))) : cc.empty(__("No messages yet")),
					el("div", { style: "margin-top:10px;display:grid;gap:8px" }, box, el("div", {}, cc.btn(__("Send"), async () => {
						if (!box.value.trim()) return;
						await post("send_message", { supplier: w.supplier, work_order: w.name, message: box.value });
						cc.toast(__("Sent"), "good");
						ctx.reload();
					}, { kind: "primary" }))))),
					cc.panel(__("Internal notes (not shown to the subcontractor)"), d.comments.length ? el("div", {}, d.comments.map((c) => el("div", { style: "padding:6px 0;border-bottom:1px solid var(--cc-line,#e2e7ee)" },
						el("div", { class: "cc-sub", text: c.owner + " · " + cc.datetime(c.creation) }), el("div", { text: cc.strip ? cc.strip(c.content) : c.content })))) : cc.empty(__("No notes"))));
			},
			timeline: () => cc.panel(__("Document timeline"), table([__("Date"), __("Document"), __("Reference"), __("Status")], d.timeline.map((t) => ({ cells: [cc.date(t.date), __(t.doctype), desk(t.desk, t.name), t.status ? cc.pill(t.status) : ""] })), __("No documents yet"))),
		};
		const NAMES = [["overview", __("Overview")], ["scope", __("Scope & items")], ["progress", __("Progress")], ["materials", __("Materials")], ["inspections", __("Inspections")],
			["variations", __("Variations")], ["invoices", __("Invoices")], ["payments", __("Payments")], ["communication", __("Communication")], ["timeline", __("Activity timeline")]];
		const body = (TABS[tab] || TABS.overview)();
		ctx.root.replaceChildren(
			cc.pagehead(w.work_description || w.name, w.name + " · " + (w.supplier_name || "") + (w.project ? " · " + w.project : ""),
				d.actions.map((a) => cc.btn(LABELS[a] || a, () => runAction("Subcontract Work Order", w.name, a, () => ctx.reload()), { kind: ["reject", "hold"].includes(a) ? "ghost" : "primary" }))
					.concat([cc.btn(__("Open in desk"), null, { href: d.desk, target: "_blank", kind: "ghost", icon: "external-link" })]), cc.pill(w.status)),
			tabsEl(NAMES, tab, (v) => {
				const p = new URLSearchParams(ctx.query || "");
				p.set("tab", v);
				cc.go(cc.base + "/" + ctx.path + "?" + p, { replace: true });
			}), el("div", { style: "margin-top:14px" }, body));
	};

	// ================================================================== subcontractors
	P.scSubcontractors = async function (ctx) {
		ctx.setTitle(__("Subcontractors"));
		const q = new URLSearchParams(ctx.query || "");
		const approval = q.get("approval") || "";
		const d = await load(ctx, () => call("subcontractors", { approval, search: q.get("search") || "" }));
		const cur = cc.boot.currency;
		ctx.root.replaceChildren(
			cc.pagehead(__("Subcontractors"), __("Suppliers set up as subcontractors, with their work, compliance and performance score."),
				[cc.btn(__("Compare"), null, { href: cc.base + "/" + sc("compare"), kind: "ghost", icon: "chart-bar" }), cc.btn(__("New subcontractor"), null, { href: "/app/supplier/new?is_subcontractor=1", target: "_blank", kind: "primary", icon: "plus" })]),
			tabsEl([["", __("All")], ["Approved", __("Approved")], ["Pending", __("Awaiting approval")], ["Suspended", __("Suspended")], ["Blacklisted", __("Blacklisted")]], approval, (v) => cc.go(cc.base + "/" + ctx.path + (v ? "?approval=" + v : ""), { replace: true })),
			cc.panel(null, table([__("Subcontractor"), __("Classification"), __("Approval"), __("Compliance"), num(__("Work orders")), num(__("Ongoing")), num(__("Delayed")), num(__("Value")), num(__("Score"))],
				d.rows.map((r) => ({ href: cc.base + "/" + sc("subcontractors/" + encodeURIComponent(r.name)), cells: [el("div", {}, el("b", { text: r.supplier_name }), el("div", { class: "cc-sub", text: r.name })),
					r.business_classification || r.subcontractor_type || "", cc.pill(r.subcontractor_approval_status), cc.pill(r.compliance === "None" ? __("No documents") : r.compliance, r.compliance === "Valid" ? "good" : r.compliance === "None" ? null : "warn"),
					cc.qty(r.work_orders), cc.qty(r.ongoing), r.delayed ? el("b", { style: "color:var(--cc-bad,#b42318)", text: r.delayed }) : "0", cc.money(r.value, cur), r.score == null ? "–" : cc.num(r.score, 0)] })),
				__("No subcontractors yet"))));
	};

	P.scSubcontractor = async function (ctx) {
		const q = new URLSearchParams(ctx.query || "");
		const d = await load(ctx, () => call("subcontractor", { name: ctx.name, from_date: q.get("from") || "", to_date: q.get("to") || "" }));
		const s = d.supplier;
		const cur = s.default_currency || cc.boot.currency;
		ctx.setTitle(s.supplier_name, [{ route: sc("subcontractors"), label: __("Subcontractors") }]);
		const st = d.statement;
		const card = d.scorecard;
		const actions = [];
		if (d.can_approve && s.subcontractor_approval_status !== "Approved") actions.push(cc.btn(__("Approve subcontractor"), () => runAction("Supplier", s.name, "approve", () => ctx.reload()), { kind: "primary" }));
		actions.push(cc.btn(__("Invite portal user"), null, { href: "/app/subcontractor-portal-access/new?supplier=" + encodeURIComponent(s.name), target: "_blank", kind: "ghost", icon: "key-round" }),
			cc.btn(__("Open in desk"), null, { href: d.desk, target: "_blank", kind: "ghost", icon: "external-link" }));
		const box = el("textarea", { "aria-label": __("Message"), placeholder: __("Write to this subcontractor (shown in their portal)"), style: "width:100%;min-height:60px" });
		ctx.root.replaceChildren(
			cc.pagehead(s.supplier_name, [s.name, s.business_classification, s.subcontractor_type].filter(Boolean).join(" · "), actions, cc.pill(s.subcontractor_approval_status)),
			el("dl", { class: "cc-kpis" }, [[__("Performance score"), card.score == null ? "–" : cc.num(card.score, 0)], [__("Work orders"), card.work_orders.total], [__("Ongoing"), card.work_orders.ongoing],
				[__("Completed"), card.work_orders.completed], [__("Delayed"), card.work_orders.delayed], [__("Payable balance"), cc.money(st.closing, cur, true)]].map(([l, v]) => el("div", { class: "cc-kpi" }, el("dt", { text: l }), el("dd", { text: String(v) })))),
			el("div", { class: "cc-grid cc-grid--2" },
				cc.panel(__("Business information"), el("dl", { class: "cc-dl" }, [[__("Tax number"), s.tax_id], [__("Email"), s.email_id], [__("Phone"), s.mobile_no], [__("Website"), s.website],
					[__("Contact person"), s.subcontractor_contact_person], [__("Relationship manager"), s.relationship_manager], [__("Category"), s.subcontractor_category], [__("Specializations"), s.specializations],
					[__("Approved work categories"), s.approved_work_categories], [__("Service areas"), s.service_areas], [__("Operating locations"), s.operating_locations],
					[__("Default retention"), s.default_retention_percentage ? s.default_retention_percentage + "%" : null], [__("Current projects"), d.projects.join(", ")]].filter((p) => p[1]).flatMap((p) => [el("dt", { text: p[0] }), el("dd", { text: p[1] })]))),
				cc.panel(__("Performance scorecard"), el("div", {}, table([__("Indicator"), num(__("Score")), num(__("Weight")), __("Basis")], card.indicators.map((i) => ({ cells: [i.label, i.score == null ? "–" : cc.num(i.score, 0), cc.num(i.weight, 0), i.basis] }))),
					el("p", { class: "cc-sub", text: __("The score is the weighted average of the indicators that have data. Weights are set in Subcontracting Settings.") }))),
				cc.panel(__("Compliance documents"), table([__("Document"), __("Number"), __("Expires"), __("Status"), __("Verified")], d.compliance.map((r) => ({ cells: [__(r.document_type), r.document_no || "",
					cc.date(r.expiry_date), cc.pill(r.compliance_status), r.verified ? __("Yes") : __("No")] })), __("No documents on file"))),
				cc.panel(__("Agreements"), table([__("Agreement"), __("Type"), __("From"), __("To"), num(__("Value")), __("Status")], d.agreements.map((r) => ({ cells: [desk("/app/subcontract-agreement/" + r.name, r.name),
					__(r.agreement_type), cc.date(r.start_date), cc.date(r.end_date), cc.money(r.contract_value, cur), cc.pill(r.status)] })), __("No agreements")),
					{ actions: [cc.btn(__("New agreement"), null, { href: "/app/subcontract-agreement/new?supplier=" + encodeURIComponent(s.name), target: "_blank", sm: true, icon: "plus" })] }),
				cc.panel(__("Work orders"), table([__("Work order"), __("Project"), num(__("Value")), __("Due"), __("Status")], d.work_orders.map((r) => ({ href: cc.base + "/" + sc("work-orders/" + encodeURIComponent(r.name)),
					cells: [r.name, r.project || "", cc.money(r.final_contract_value, cur), cc.date(r.expected_completion_date), cc.pill(r.status)] })), __("No work orders"))),
				cc.panel(__("Inspections"), table([__("Result"), num(__("Count"))], d.inspections.map((r) => ({ cells: [cc.pill(r.status), r.n] })), __("No inspections yet"))),
				cc.panel(__("Variations and claims"), table([__("Request"), __("Type"), num(__("Value change")), __("Status")], d.variations.map((r) => ({ cells: [desk("/app/subcontract-variation/" + r.name, r.name),
					__(r.variation_type), cc.money(r.value_change, cur), cc.pill(r.status)] })), __("No variations"))),
				cc.panel(__("Material issued"), table([__("Issue"), __("Date"), __("Work order")], d.material.map((r) => ({ cells: [desk("/app/subcontract-material-allocation/" + r.name, r.name), cc.date(r.posting_date), r.subcontract_work_order] })), __("No material issued"))),
				cc.panel(__("Invoices"), table([__("Invoice"), __("Bill no."), __("Date"), num(__("Total")), num(__("Outstanding")), __("Status")], d.invoices.map((r) => ({ cells: [desk("/app/purchase-invoice/" + r.name, r.name),
					r.bill_no || "", cc.date(r.posting_date), cc.money(r.grand_total, cur), cc.money(r.outstanding_amount, cur), cc.pill(r.status)] })), __("No invoices"))),
				cc.panel(__("Portal users"), table([__("Name"), __("Email"), __("Access"), __("Last access"), __("Status")], d.portal_users.map((r) => ({ cells: [desk("/app/subcontractor-portal-access/" + r.name, r.full_name),
					r.email, __(r.access_level), r.last_access ? cc.ago(r.last_access) : __("Never"), cc.pill(r.enabled ? __("Enabled") : __("Suspended"), r.enabled ? "good" : "warn")] })), __("No portal users"))),
				cc.panel(__("Communication"), el("div", {}, d.messages.slice(0, 8).map((m) => el("div", { style: "padding:6px 0;border-bottom:1px solid var(--cc-line,#e2e7ee)" },
					el("div", { class: "cc-sub", text: (m.direction === "From Subcontractor" ? "← " : "→ ") + (m.sender_name || "") + " · " + cc.datetime(m.creation) + (m.subcontract_work_order ? " · " + m.subcontract_work_order : "") }),
					el("div", { style: "white-space:pre-wrap", text: m.message }))),
				el("div", { style: "margin-top:8px;display:grid;gap:8px" }, box, el("div", {}, cc.btn(__("Send"), async () => {
					if (!box.value.trim()) return;
					await post("send_message", { supplier: s.name, message: box.value });
					cc.toast(__("Sent"), "good");
					ctx.reload();
				}, { kind: "primary" })))))),
			cc.panel(__("Account statement"), el("div", {},
				el("div", { style: "display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;align-items:center" }, __("From"), el("input", { type: "date", value: st.from_date, onchange: (e) => go({ from: e.target.value }) }),
					__("to"), el("input", { type: "date", value: st.to_date, onchange: (e) => go({ to: e.target.value }) }), el("span", { class: "cc-sub", text: __("Company {0}. From the general ledger, so it agrees with the accounts.", [st.company]) })),
				table([__("Date"), __("Voucher"), num(__("Debit (paid / deducted)")), num(__("Credit (invoiced)")), num(__("Balance payable"))],
					[{ cells: [cc.date(st.from_date), el("i", { text: __("Opening balance") }), "", "", cc.money(st.opening, cur)] }].concat(st.entries.map((e) => ({ cells: [cc.date(e.posting_date),
						desk(e.desk, __(e.voucher_type) + " " + e.voucher_no), e.debit ? cc.money(e.debit, cur) : "", e.credit ? cc.money(e.credit, cur) : "", cc.money(e.balance, cur)] }))),
					__("No entries")))));
		function go(patch) {
			const p = new URLSearchParams(ctx.query || "");
			Object.entries(patch).forEach(([k, v]) => (v ? p.set(k, v) : p.delete(k)));
			cc.go(cc.base + "/" + ctx.path + "?" + p, { replace: true });
		}
	};

	P.scCompare = async function (ctx) {
		ctx.setTitle(__("Performance & Comparison"));
		const q = new URLSearchParams(ctx.query || "");
		const d = await load(ctx, () => call("compare", { classification: q.get("classification") || "" }));
		const keys = [["on_time", __("On time")], ["quality", __("Quality")], ["rework", __("Rework")], ["safety", __("Compliance")], ["material", __("Material")], ["response", __("Response")], ["commercial", __("Commercial")]];
		const score = (v) => (v == null ? "–" : cc.num(v, 0));
		ctx.root.replaceChildren(
			cc.pagehead(__("Performance & Comparison"), __("Scores 0–100 per indicator, the weighted score, workload and approved rates side by side.")),
			el("div", { class: "cc-filters", style: "margin:8px 0" }, el("select", { "aria-label": __("Classification"), onchange: (e) => cc.go(cc.base + "/" + ctx.path + (e.target.value ? "?classification=" + encodeURIComponent(e.target.value) : ""), { replace: true }) },
				["", "Labour Contractor", "Equipment Contractor", "Material Supplier", "Installation Contractor", "Fabrication Contractor", "Maintenance Contractor", "Transportation Contractor", "Specialist Service Provider", "Other"]
					.map((v) => el("option", { value: v, selected: v === (q.get("classification") || ""), text: v ? __(v) : __("All classifications") })))),
			cc.panel(__("Scorecards"), table([__("Subcontractor"), num(__("Score"))].concat(keys.map((k) => num(k[1]))).concat([num(__("Projects")), num(__("Work orders")), num(__("Ongoing")), __("Available")]),
				d.rows.map((r) => ({ href: cc.base + "/" + sc("subcontractors/" + encodeURIComponent(r.supplier)), cells: [el("b", { text: r.supplier_name }), el("b", { text: score(r.score) })]
					.concat(keys.map((k) => score(r.indicators[k[0]]))).concat([r.projects, r.work_orders.total, r.work_orders.ongoing, r.available ? __("Yes") : __("Busy")]) })), __("No subcontractors"))),
			cc.panel(__("Approved and historical rates"), table([__("Subcontractor"), __("Item / job"), num(__("Approved rate (active agreement)")), num(__("Average rate on work orders")), num(__("Quantity ordered"))],
				d.rows.flatMap((r) => {
					const items = new Set(r.rates.map((x) => x.item_code).concat(r.history.map((x) => x.job_type)));
					return [...items].map((it) => {
						const a = r.rates.find((x) => x.item_code === it), h = r.history.find((x) => x.job_type === it);
						return { cells: [r.supplier_name, it, a ? cc.money(a.rate) : "–", h ? cc.money(h.avg_rate) : "–", h ? cc.qty(h.qty) : "–"] };
					});
				}), __("No rates yet"))));
	};
})();
