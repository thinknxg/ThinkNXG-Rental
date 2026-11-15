/* thinkNXG Rental customer Command Center: quotations, sales orders, invoices, payments, statement. */
(function () {
	"use strict";
	const { el, icon } = cp;
	const P = cp.pages;

	cp.per = function (basis) {
		return { Daily: __("per day"), Weekly: __("per week"), Monthly: __("per month") }[basis] || (basis ? __(basis) : "");
	};

	function linesCard(doc, extraCol) {
		return cp.card(__("Items"), el("div", { class: "cp-tablewrap" }, el("table", { class: "cp-table" },
			el("thead", {}, el("tr", {}, [__("Item"), __("Qty"), __("Rate"), extraCol ? extraCol.label : null, __("Amount")].filter(Boolean).map((h, i) => el("th", { class: i ? "cp-num" : null, text: h })))),
			el("tbody", {}, doc.items.map((i) => el("tr", {}, el("td", {}, el("b", { text: i.item_name }), el("span", { class: "cp-sub", text: [i.item_code, i.description].filter(Boolean).join(", ") })),
				el("td", { class: "cp-num", text: cp.qty(i.qty) + " " + (i.uom || "") }),
				el("td", { class: "cp-num" }, cp.money(i.rate, doc.currency), i.nxg_rate_basis ? el("span", { class: "cp-sub", text: cp.per(i.nxg_rate_basis) }) : null),
				extraCol ? el("td", { class: "cp-num", text: extraCol.render(i) }) : null,
				el("td", { class: "cp-num", text: cp.money(i.amount, doc.currency) })))),
			el("tfoot", {}, totalsRows(doc, extraCol ? 4 : 3)))), { flush: true });
	}
	function totalsRows(doc, span) {
		const row = (label, value, strong) => el("tr", {}, el("td", { colspan: span, class: "cp-num", style: { fontWeight: strong ? 700 : 500 }, text: label }), el("td", { class: "cp-num", style: { fontWeight: strong ? 700 : 500 }, text: cp.money(value, doc.currency) }));
		return [row(__("Net total"), doc.net_total), ...doc.taxes.map((t) => row(t.description, t.amount)), row(__("Grand total"), doc.grand_total, true)];
	}
	function terms(doc) {
		if (!doc.terms) return null;
		const div = el("div", { style: { fontSize: "14px", color: "var(--ink-2)" } });
		div.textContent = new DOMParser().parseFromString(doc.terms, "text/html").body.textContent;
		return cp.card(__("Terms and conditions"), div);
	}

	// ================================================================== quotations
	P.quotations = async function (ctx) {
		ctx.setTitle(__("Quotations"));
		ctx.main.replaceChildren(cp.pageHead(__("Quotations"), __("Offers we have sent you, with their validity.")),
			cp.dataTable({
				method: "quotations",
				search: __("Quotation number or title"),
				filters: [{ name: "status", label: __("All statuses"), options: [["Open", __("Open")], ["Ordered", __("Ordered")], ["Partially Ordered", __("Partially ordered")], ["Expired", __("Expired")], ["Lost", __("Lost")]] }],
				columns: [
					{ label: __("Quotation"), render: (r) => el("div", {}, cp.link(r.route, r.name, { class: "cp-strong" }), el("span", { class: "cp-sub", text: r.title || "" })) },
					{ label: __("Date"), render: (r) => cp.date(r.transaction_date) },
					{ label: __("Valid until"), render: (r) => el("div", {}, cp.date(r.valid_till), r.status === "Open" && cp.daysFrom(r.valid_till) >= 0 && cp.daysFrom(r.valid_till) <= 7 ? el("span", { class: "cp-sub", style: { color: "var(--warn)" }, text: __("expires in {0} days", [cp.daysFrom(r.valid_till)]) }) : null) },
					{ label: __("Site"), render: (r) => r.rental_site || "" },
					{ label: __("Amount"), num: 1, render: (r) => cp.money(r.grand_total, r.currency) },
					{ label: __("Status"), render: (r) => cp.badge(r.status) },
					{ label: "", render: (r) => cp.pdfBtn("Quotation", r.name) },
				],
				href: (r) => r.route,
				mobile: (r) => ({ title: r.name, badge: cp.badge(r.status), meta: [[__("Date"), cp.date(r.transaction_date)], [__("Valid until"), cp.date(r.valid_till)], [__("Amount"), cp.money(r.grand_total, r.currency)]] }),
				empty: { title: __("No quotations"), text: __("Quotations we send you will be listed here."), icon: "file-text" },
			}));
	};
	P.quotation = async function (ctx) {
		const q = await cp.api("quotation", { name: ctx.params[0] });
		if (!ctx.isCurrent()) return;
		ctx.setTitle(q.name, [[__("Quotations"), "quotations"]]);
		const accept = q.can_accept ? cp.btn(__("Accept quotation"), async () => {
			if (!(await cp.confirm(__("Accept quotation {0}?", [q.name]), __("The rental team is told straight away and prepares your order. Delivery is arranged with you."), __("Accept quotation")))) return;
			await cp.api("accept_quotation", { name: q.name }, { post: true });
			cp.toast(__("Quotation accepted. The rental team will be in touch to confirm the order."));
			P.quotation(ctx);
		}, { primary: true, icon: "check" }) : null;
		ctx.main.replaceChildren(cp.pageHead(q.name, q.title, [accept, cp.pdfBtn("Quotation", q.name, __("Download PDF"))].filter(Boolean)),
			el("div", { style: { margin: "-10px 0 18px", display: "flex", gap: "8px", flexWrap: "wrap", alignItems: "center" } }, cp.badge(q.status),
				q.accepted_on ? cp.badge(__("Accepted online {0}", [cp.date(q.accepted_on)]), "good") : null),
			el("div", { class: "cp-stack" }, cp.card(__("Quotation"), cp.facts([[__("Quotation number"), q.name], [__("Date"), cp.date(q.transaction_date)], [__("Valid until"), cp.date(q.valid_till)],
				[__("Site"), q.rental_site], [__("Grand total"), cp.money(q.grand_total, q.currency)]])), linesCard(q), terms(q)));
	};

	// ================================================================== website enquiries
	P.enquiries = async function (ctx) {
		ctx.setTitle(__("Enquiries"));
		ctx.main.replaceChildren(cp.pageHead(__("Enquiries"), __("Requests you sent from the website, and the quotations we prepared for them."),
			[cp.btn(__("New enquiry"), null, { href: "/hire/equipment", external: true, icon: "plus" })]),
			cp.dataTable({
				method: "enquiries",
				search: __("Enquiry reference"),
				columns: [
					{ label: __("Enquiry"), render: (r) => el("div", {}, el("b", { text: r.name }), el("span", { class: "cp-sub", text: [__(r.enquiry_type), r.subject].filter(Boolean).join(", ") })) },
					{ label: __("Sent"), render: (r) => cp.date(r.enquiry_date) },
					{ label: __("Items"), render: (r) => r.items.length ? el("div", {}, r.items.slice(0, 3).map((i) => el("div", { text: cp.qty(i.qty) + " × " + i.item_name + (i.line_type === "Purchase" ? " (" + __("buy") + ")" : "") })),
						r.items.length > 3 ? el("span", { class: "cp-sub", text: __("and {0} more", [r.items.length - 3]) }) : null) : el("span", { class: "cp-sub", text: __("Message only") }) },
					{ label: __("Period"), render: (r) => r.required_from ? cp.date(r.required_from) + " – " + cp.date(r.expected_return) : "" },
					{ label: __("Quotation"), render: (r) => r.quotations.length ? el("div", {}, r.quotations.map((q) => el("div", {}, cp.link("quotations/" + q, q)))) : el("span", { class: "cp-sub", text: __("Being prepared") }) },
					{ label: __("Status"), render: (r) => cp.badge(r.status) },
				],
				mobile: (r) => ({ title: r.name, badge: cp.badge(r.status), meta: [[__("Sent"), cp.date(r.enquiry_date)], [__("Items"), String(r.items.length)], [__("Quotation"), r.quotations.join(", ") || __("Being prepared")]] }),
				empty: { title: __("No enquiries yet"), text: __("Choose equipment on the website and send an enquiry; it is listed here."), icon: "inbox" },
			}));
	};

	// ================================================================== sales orders
	P.sales_orders = async function (ctx) {
		ctx.setTitle(__("Sales Orders"));
		ctx.main.replaceChildren(cp.pageHead(__("Sales Orders"), __("Orders for goods and services outside rental contracts.")),
			cp.dataTable({
				method: "sales_orders",
				search: __("Order number, PO or project"),
				filters: [{ name: "status", label: __("All statuses"), options: [["To Deliver and Bill", __("To deliver and bill")], ["To Bill", __("To bill")], ["To Deliver", __("To deliver")], ["Completed", __("Completed")], ["Closed", __("Closed")]] }],
				columns: [
					{ label: __("Sales order"), render: (r) => el("div", {}, cp.link(r.route, r.name, { class: "cp-strong" }), r.po_no ? el("span", { class: "cp-sub", text: __("Your PO {0}", [r.po_no]) }) : null) },
					{ label: __("Date"), render: (r) => cp.date(r.transaction_date) },
					{ label: __("Delivery date"), render: (r) => cp.date(r.delivery_date) },
					{ label: __("Project"), render: (r) => r.project || "" },
					{ label: __("Delivered"), render: (r) => el("div", { style: { minWidth: "90px" } }, cp.progress([{ label: __("Delivered"), value: r.per_delivered, color: cp.COLORS.teal }], 100), el("span", { class: "cp-sub", text: Math.round(r.per_delivered) + "%" })) },
					{ label: __("Value"), num: 1, render: (r) => cp.money(r.grand_total, r.currency) },
					{ label: __("Status"), render: (r) => cp.badge(r.status) },
				],
				href: (r) => r.route,
				mobile: (r) => ({ title: r.name, badge: cp.badge(r.status), meta: [[__("Date"), cp.date(r.transaction_date)], [__("Value"), cp.money(r.grand_total, r.currency)]] }),
				empty: { title: __("No sales orders"), text: "", icon: "shopping-cart" },
			}));
	};
	P.sales_order = async function (ctx) {
		const s = await cp.api("sales_order", { name: ctx.params[0] });
		if (!ctx.isCurrent()) return;
		ctx.setTitle(s.name, [[__("Sales Orders"), "sales-orders"]]);
		ctx.main.replaceChildren(cp.pageHead(s.name, null, [cp.pdfBtn("Sales Order", s.name, __("Download PDF"))]),
			el("div", { style: { margin: "-10px 0 18px" } }, cp.badge(s.status)),
			el("div", { class: "cp-stack" }, cp.card(__("Sales order"), cp.facts([[__("Order number"), s.name], [__("Date"), cp.date(s.transaction_date)], [__("Delivery date"), cp.date(s.delivery_date)],
				[__("Your PO"), s.po_no], [__("Project"), s.project], [__("Delivered"), Math.round(s.per_delivered) + "%"], [__("Billed"), Math.round(s.per_billed) + "%"]])),
			linesCard(s, { label: __("Delivered"), render: (i) => cp.qty(i.delivered_qty) }), terms(s)));
	};

	// ================================================================== invoices
	function payBadge(r) {
		return cp.badge(r.payment_status);
	}
	P.invoices = async function (ctx) {
		ctx.setTitle(__("Invoices"));
		const summary = el("div", { class: "cp-kpis", style: { gridTemplateColumns: "repeat(2, minmax(0, 1fr))", maxWidth: "640px" } });
		ctx.main.replaceChildren(cp.pageHead(__("Invoices"), __("Rental, job and damage invoices, and credit notes.")), summary,
			cp.dataTable({
				method: "invoices",
				search: __("Invoice, contract or PO"),
				filters: [{ name: "status", label: __("All invoices"), options: [["unpaid", __("Unpaid")], ["overdue", __("Overdue")], ["paid", __("Paid")], ["credit", __("Credit notes")]] },
					{ name: "from_date", type: "date", label: __("From") }, { name: "to_date", type: "date", label: __("To") }],
				onData: (d) => summary.replaceChildren(cp.kpiMini(__("Outstanding"), cp.money(d.outstanding, d.currency), "wallet", d.outstanding ? "warn" : "teal"),
					cp.kpiMini(__("Overdue"), cp.money(d.overdue, d.currency), "alarm-clock", d.overdue ? "bad" : "")),
				columns: [
					{ label: __("Invoice"), render: (r) => el("div", {}, cp.link(r.route, r.name, { class: "cp-strong" }), el("span", { class: "cp-sub", text: r.kind + (r.period_from ? ", " + cp.date(r.period_from) + " to " + cp.date(r.period_to) : "") })) },
					{ label: __("Date"), render: (r) => cp.date(r.posting_date) },
					{ label: __("Due"), render: (r) => el("span", { style: r.overdue ? { color: "var(--bad)", fontWeight: 600 } : null, text: cp.date(r.due_date) }) },
					{ label: __("Contract"), render: (r) => (r.rental_contract ? cp.link("orders/" + r.rental_contract, r.rental_contract) : "") },
					{ label: __("Grand total"), num: 1, render: (r) => cp.money(r.grand_total, r.currency) },
					{ label: __("Outstanding"), num: 1, render: (r) => el("b", { text: cp.money(r.outstanding_amount, r.currency) }) },
					{ label: __("Status"), render: payBadge },
					{ label: "", render: (r) => cp.pdfBtn("Sales Invoice", r.name) },
				],
				href: (r) => r.route,
				mobile: (r) => ({ title: r.name, badge: payBadge(r), meta: [[__("Date"), cp.date(r.posting_date)], [__("Due"), cp.date(r.due_date)], [__("Total"), cp.money(r.grand_total, r.currency)], [__("Outstanding"), cp.money(r.outstanding_amount, r.currency)]] }),
				empty: { title: __("No invoices yet"), text: __("Invoices appear here once they are issued."), icon: "receipt" },
			}));
	};
	P.invoice = async function (ctx) {
		const v = await cp.api("invoice", { name: ctx.params[0] });
		if (!ctx.isCurrent()) return;
		ctx.setTitle(v.name, [[__("Invoices"), "invoices"]]);
		const s = cp.boot.settings || {};
		const payCard = cp.card(__("Payments"), v.payments.length ? el("div", { class: "cp-tablewrap" }, el("table", { class: "cp-table" },
			el("thead", {}, el("tr", {}, [__("Payment"), __("Date"), __("Mode"), __("Reference"), __("Allocated")].map((h, i) => el("th", { class: i === 4 ? "cp-num" : null, text: h })))),
			el("tbody", {}, v.payments.map((p) => el("tr", {}, el("td", { text: p.name }), el("td", { text: cp.date(p.posting_date) }), el("td", { text: p.mode_of_payment || "" }),
				el("td", { text: p.reference_no || "" }), el("td", { class: "cp-num", text: cp.money(p.allocated_amount, v.currency) }))))))
			: el("p", { class: "cp-sub", style: { margin: "16px 18px" }, text: v.is_return ? __("Credit notes are applied to your account.") : __("No payments recorded against this invoice yet.") }), { flush: true });
		const due = v.outstanding_amount > 0 && !v.is_return ? el("div", { class: "cp-callout " + (v.overdue ? "is-bad" : "is-warn"), style: { marginBottom: "18px" } }, icon("wallet"),
			el("span", {}, v.overdue ? __("{0} was due on {1}.", [cp.money(v.outstanding_amount, v.currency), cp.date(v.due_date)]) : __("{0} is due on {1}.", [cp.money(v.outstanding_amount, v.currency), cp.date(v.due_date)]),
				s.contact_email ? [" ", __("Questions about this invoice?"), " ", el("a", { href: "mailto:" + s.contact_email + "?subject=" + encodeURIComponent(v.name), text: s.contact_email })] : null)) : null;
		ctx.main.replaceChildren(cp.pageHead(v.name, v.kind, [cp.pdfBtn("Sales Invoice", v.name, __("Download PDF"))]),
			el("div", { style: { margin: "-10px 0 18px" } }, cp.badge(v.payment_status)), due,
			el("div", { class: "cp-stack" }, cp.card(__("Invoice"), cp.facts([[__("Invoice number"), v.name], [__("Invoice date"), cp.date(v.posting_date)], [__("Due date"), cp.date(v.due_date)],
				[__("Rental contract"), v.rental_contract ? cp.link("orders/" + v.rental_contract, v.rental_contract) : null],
				[__("Billing period"), v.period ? cp.date(v.period.from_date) + " to " + cp.date(v.period.to_date) : null], [__("Your PO"), v.po_no],
				[__("Credit note for"), v.return_against ? cp.link("invoices/" + v.return_against, v.return_against) : null],
				[__("Grand total"), cp.money(v.grand_total, v.currency)], [__("Outstanding"), cp.money(v.outstanding_amount, v.currency)]])),
			linesCard(v), payCard, terms(v)));
	};

	// ================================================================== payments
	P.payments = async function (ctx) {
		ctx.setTitle(__("Payments"));
		ctx.main.replaceChildren(cp.pageHead(__("Payments"), __("Payments we have received from you and how they were applied.")),
			cp.dataTable({
				method: "payments",
				search: __("Payment or your reference"),
				filters: [{ name: "from_date", type: "date", label: __("From") }, { name: "to_date", type: "date", label: __("To") }],
				columns: [
					{ label: __("Payment"), render: (r) => el("div", {}, el("b", { text: r.name }), r.reference_no ? el("span", { class: "cp-sub", text: __("Ref. {0}", [r.reference_no]) }) : null) },
					{ label: __("Date"), render: (r) => cp.date(r.posting_date) },
					{ label: __("Mode"), render: (r) => r.mode_of_payment || "" },
					{ label: __("Applied to"), render: (r) => el("div", {}, r.allocations.length ? r.allocations.map((a) => el("div", {}, a.route ? cp.link(a.route, a.name) : a.name, " ", el("span", { class: "cp-sub", style: { display: "inline" }, text: cp.money(a.amount, r.currency) })))
						: el("span", { class: "cp-sub", text: __("On account") })) },
					{ label: __("Amount"), num: 1, render: (r) => el("b", { text: (r.is_refund ? "−" : "") + cp.money(r.paid_amount, r.currency) }) },
					{ label: __("Status"), render: (r) => cp.badge(r.status) },
					{ label: "", render: (r) => cp.pdfBtn("Payment Entry", r.name, __("Receipt")) },
				],
				mobile: (r) => ({ title: [r.name, " ", cp.pdfBtn("Payment Entry", r.name, __("Receipt"))], badge: cp.badge(r.status), meta: [[__("Date"), cp.date(r.posting_date)], [__("Amount"), cp.money(r.paid_amount, r.currency)], [__("Mode"), r.mode_of_payment]] }),
				empty: { title: __("No payments yet"), text: __("Payments are listed here once we have recorded them."), icon: "wallet" },
			}));
	};

	// ================================================================== account statement
	P.statement = async function (ctx) {
		ctx.setTitle(__("Account Statement"));
		const q = ctx.query;
		const s = await cp.api("statement", { from_date: q.get("from"), to_date: q.get("to"), company: q.get("company") });
		if (!ctx.isCurrent()) return;
		const from = el("input", { type: "date", class: "cp-input", value: s.from_date, "aria-label": __("From") });
		const to = el("input", { type: "date", class: "cp-input", value: s.to_date, "aria-label": __("To") });
		const comp = s.companies.length > 1 ? el("select", { class: "cp-select", "aria-label": __("Company") }, s.companies.map((c) => el("option", { value: c, text: c, selected: c === s.company }))) : null;
		const apply = () => cp.go("statement?from=" + from.value + "&to=" + to.value + (comp ? "&company=" + encodeURIComponent(comp.value) : ""));
		[from, to, comp].forEach((x) => x && x.addEventListener("change", apply));
		const cur = s.currency;
		const csv = () => {
			const rows = [[__("Date"), __("Type"), __("Document"), __("Reference"), __("Debit"), __("Credit"), __("Balance")],
				["", __("Opening balance"), "", "", "", "", s.opening], ...s.rows.map((r) => [r.date, r.type, r.voucher_no, r.reference || "", r.debit, r.credit, r.balance]),
				["", __("Closing balance"), "", "", s.total_debit, s.total_credit, s.closing]];
			const text = rows.map((r) => r.map((v) => '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"').join(",")).join("\n");
			const a = el("a", { href: URL.createObjectURL(new Blob([text], { type: "text/csv" })), download: "statement-" + s.from_date + "-" + s.to_date + ".csv" });
			document.body.appendChild(a);
			a.click();
			a.remove();
		};
		const table = s.rows.length || s.opening ? el("div", { class: "cp-tablewrap" }, el("table", { class: "cp-table" },
			el("thead", {}, el("tr", {}, [__("Date"), __("Transaction"), __("Reference"), __("Debit"), __("Credit"), __("Balance")].map((h, i) => el("th", { class: i > 2 ? "cp-num" : null, text: h })))),
			el("tbody", {}, el("tr", {}, el("td", { text: cp.date(s.from_date) }), el("td", { colspan: 4 }, el("b", { text: __("Opening balance") })), el("td", { class: "cp-num cp-strong", text: cp.money(s.opening, cur) })),
				s.rows.map((r) => el("tr", {}, el("td", { text: cp.date(r.date) }), el("td", {}, el("span", { class: "cp-sub", style: { marginTop: 0 }, text: r.type }), r.route ? cp.link(r.route, r.voucher_no) : el("span", { text: r.voucher_no })),
					el("td", {}, r.reference ? (r.voucher_type === "Payment Entry" ? cp.link("invoices/" + r.reference, r.reference) : r.reference) : ""),
					el("td", { class: "cp-num", text: r.debit ? cp.money(r.debit, cur) : "" }), el("td", { class: "cp-num", text: r.credit ? cp.money(r.credit, cur) : "" }),
					el("td", { class: "cp-num cp-strong", text: cp.money(r.balance, cur) })))),
			el("tfoot", {}, el("tr", {}, el("td", { colspan: 3, text: __("Closing balance") }), el("td", { class: "cp-num", text: cp.money(s.total_debit, cur) }),
				el("td", { class: "cp-num", text: cp.money(s.total_credit, cur) }), el("td", { class: "cp-num", text: cp.money(s.closing, cur) })))))
			: cp.empty(__("No transactions in this period"), __("Choose an earlier start date to see older activity."), null, "scroll-text");
		ctx.main.replaceChildren(cp.pageHead(__("Account Statement"), s.company ? __("Your account with {0}.", [s.company]) : null,
			[cp.btn(__("Download CSV"), csv, { icon: "download" }), cp.btn(__("Print"), () => window.print(), { icon: "printer" })]),
		el("div", { class: "cp-kpis" }, cp.kpiMini(__("Opening balance"), cp.money(s.opening, cur), "flag"), cp.kpiMini(__("Invoiced (debit)"), cp.money(s.total_debit, cur), "receipt"),
			cp.kpiMini(__("Paid and credited"), cp.money(s.total_credit, cur), "wallet", "teal"), cp.kpiMini(__("Closing balance"), cp.money(s.closing, cur), "scale", s.closing > 0 ? "warn" : "teal")),
		el("section", { class: "cp-card" }, el("div", { class: "cp-toolbar" }, el("label", { class: "cp-label", style: { flexDirection: "row", alignItems: "center" } }, __("From"), from),
			el("label", { class: "cp-label", style: { flexDirection: "row", alignItems: "center" } }, __("To"), to), comp),
		s.truncated ? el("div", { class: "cp-callout is-warn", style: { margin: "12px 14px" } }, icon("info"), __("Only the first 2,000 transactions are shown. Choose a shorter period.")) : null, table));
	};
})();
