// Security deposit and advance payment of a rental contract (services/deposits.py): the financial summary,
// collection / refund / deduction dialogs on the Rental Contract, and the advance panel on a rental invoice.
frappe.provide("thinknxg_rental.payments");

(() => {
	const M = "thinknxg_rental.thinknxg_rental.doctype.rental_contract_payment.rental_contract_payment.";
	const PF = "thinknxg_rental.thinknxg_rental.doctype.rental_pro_forma_invoice.rental_pro_forma_invoice.";
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const money = (v, currency) => format_currency(flt(v), currency);
	const request_id = () => `${frappe.session.user}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
	const P = thinknxg_rental.payments;

	P.summary_html = (b, currency) => {
		const row = (label, value, strong) =>
			`<tr><td>${esc(label)}</td><td class="text-right">${strong ? "<b>" : ""}${esc(money(value, currency))}${strong ? "</b>" : ""}</td></tr>`;
		const badge = (status) => `<span class="indicator-pill ${{"Not Collected": "red", "Not Received": "red", "Partially Collected": "orange",
			"Partially Received": "orange", "Fully Collected": "green", "Fully Received": "green", "Partially Utilized": "blue",
			"Fully Utilized": "gray", "Partially Refunded": "blue", Settled: "gray"}[status] || "gray"}">${esc(__(status))}</span>`;
		return `<div class="row">
			<div class="col-sm-6"><h6>${esc(__("Security Deposit"))} ${badge(b.deposit_status)}</h6><table class="table table-condensed table-bordered small">
				${row(__("Security Deposit Required"), b.deposit_required)}${row(__("Security Deposit Collected"), b.deposit_collected)}
				${row(__("Security Deposit Outstanding"), b.deposit_outstanding)}${row(__("Security Deposit Refunded"), b.deposit_refunded)}
				${row(__("Security Deposit Adjusted"), b.deposit_adjusted)}${row(__("Security Deposit Balance"), b.deposit_balance, 1)}</table></div>
			<div class="col-sm-6"><h6>${esc(__("Advance Payment"))} ${badge(b.advance_status)}</h6><table class="table table-condensed table-bordered small">
				${row(__("Advance Required"), b.advance_required)}${row(__("Advance Received"), b.advance_received)}
				${row(__("Advance Utilized"), b.advance_utilized)}${row(__("Advance Refunded"), b.advance_refunded)}
				${row(__("Advance Available"), b.advance_available, 1)}</table></div></div>`;
	};

	// one dialog for every transaction type
	P.dialog = (frm, type, b) => {
		const doc = frm.doc;
		const currency = doc.currency || frappe.defaults.get_default("currency");
		const cash = ["Deposit Collection", "Deposit Refund", "Advance Collection", "Advance Refund"].includes(type);
		const against = ["Deposit Deduction", "Advance Adjustment"].includes(type);
		const rem = b.remaining || {};
		const limit = {
			"Deposit Collection": rem.deposit, "Advance Collection": rem.advance,
			"Deposit Refund": b.deposit_balance, "Deposit Deduction": b.deposit_balance, "Advance Refund": b.advance_available, "Advance Adjustment": b.advance_available,
		}[type];
		const info = {
			"Deposit Collection": [[__("Required"), b.deposit_required], [__("Collected"), b.deposit_collected],
				[__("Remaining to collect"), rem.deposit == null ? b.deposit_outstanding : rem.deposit]],
			"Advance Collection": [[__("Required"), b.advance_required], [__("Received"), b.advance_received],
				[__("Remaining to collect"), rem.advance == null ? b.advance_outstanding : rem.advance]],
			"Deposit Refund": [[__("Collected"), b.deposit_collected], [__("Refunded"), b.deposit_refunded], [__("Approved Deductions"), b.deposit_adjusted], [__("Refundable Balance"), b.deposit_balance]],
			"Deposit Deduction": [[__("Deposit Held"), b.deposit_balance]],
			"Advance Refund": [[__("Advance Available"), b.advance_available]],
			"Advance Adjustment": [[__("Advance Available"), b.advance_available]],
		}[type];
		const fields = [
			{ fieldtype: "HTML", fieldname: "info", options: `<table class="table table-condensed small">${info.map(([l, v]) =>
				`<tr><td>${esc(l)}</td><td class="text-right">${esc(money(v, currency))}</td></tr>`).join("")}</table>` },
			{ fieldname: "amount", fieldtype: "Currency", label: __("Amount"), options: "currency", reqd: 1, default: limit > 0 ? limit : null },
			{ fieldname: "posting_date", fieldtype: "Date", label: __("Date"), reqd: 1, default: frappe.datetime.get_today() },
		];
		if (cash) {
			fields.push(
				{ fieldname: "mode_of_payment", fieldtype: "Link", label: __("Mode of Payment"), options: "Mode of Payment", reqd: 1,
					onchange() {
						const v = d.get_value("mode_of_payment");
						if (v) frappe.call({ method: M + "get_payment_account", args: { mode_of_payment: v, company: doc.company } })
							.then((r) => r.message && d.set_value("account", r.message));
					} },
				{ fieldname: "account", fieldtype: "Link", label: __("Bank / Cash Account"), options: "Account", reqd: 1,
					get_query: () => ({ filters: { company: doc.company, is_group: 0, account_type: ["in", ["Bank", "Cash"]] } }) },
				{ fieldname: "reference_no", fieldtype: "Data", label: __("Transaction / Cheque Reference") },
				{ fieldname: "reference_date", fieldtype: "Date", label: __("Reference Date") }
			);
		}
		if (against) {
			fields.push({ fieldname: "sales_invoice", fieldtype: "Link", label: __("Sales Invoice"), options: "Sales Invoice", reqd: 1,
				get_query: () => ({ filters: { customer: doc.customer, company: doc.company, docstatus: 1, outstanding_amount: [">", 0], is_return: 0 } }) });
		}
		if (type === "Deposit Deduction") {
			fields.push({ fieldname: "deduction_reason", fieldtype: "Select", label: __("Deduction Reason"), reqd: 1,
					options: ["", "Damage", "Missing Material", "Unpaid Rental", "Other"] },
				{ fieldname: "damage_settlement", fieldtype: "Link", label: __("Damage Settlement"), options: "Rental Damage Settlement",
					get_query: () => ({ filters: { rental_contract: doc.name, docstatus: 1 } }) });
		}
		fields.push({ fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") });
		const rid = request_id();
		const d = new frappe.ui.Dialog({
			title: __(type), fields,
			primary_action_label: __("Post"),
			primary_action(v) {
				d.get_primary_btn().prop("disabled", true);
				frappe.call({ method: M + "create", args: { values: Object.assign({ transaction_type: type, rental_contract: doc.doctype === "Rental Contract" ? doc.name : null,
					hire_order: doc.doctype === "Hire Order" ? doc.name : null, pro_forma_invoice: doc.doctype === "Rental Pro Forma Invoice" ? doc.name : null,
					request_id: rid }, v) }, freeze: true })
					.then((r) => {
						d.hide();
						const m = r.message;
						frappe.show_alert({ indicator: m.docstatus === 1 ? "green" : "orange", message: m.docstatus === 1
							? __("{0} posted: {1}", [__(type), m.name]) : __("{0} saved as {1}: waiting for approval", [m.name, __(m.status)]) });
						frm.reload_doc();
					})
					.always(() => d.get_primary_btn().prop("disabled", false));
			},
		});
		d.show();
	};

	P.history = (frm, fund) => {
		frappe.call({ method: M + "get_history", args: { rental_contract: frm.doc.name, fund } }).then((r) => {
			const rows = r.message || [];
			const html = `<table class="table table-bordered table-condensed small"><thead><tr><th>${__("Date")}</th><th>${__("Transaction")}</th>
				<th>${__("Receipt")}</th><th class="text-right">${__("Amount")}</th><th>${__("Payment / Invoice")}</th><th>${__("Journal Entry")}</th><th>${__("Status")}</th></tr></thead><tbody>${
				rows.length ? rows.map((x) => `<tr><td>${esc(frappe.datetime.str_to_user(x.posting_date))}</td><td>${esc(__(x.transaction_type))}</td>
					<td><a href="/app/rental-contract-payment/${encodeURIComponent(x.name)}">${esc(x.name)}</a></td><td class="text-right">${esc(money(x.amount, x.currency))}</td>
					<td>${esc(x.sales_invoice || [x.mode_of_payment, x.reference_no].filter(Boolean).join(" "))}</td><td>${esc(x.journal_entry || "")}</td><td>${esc(__(x.status))}</td></tr>`).join("")
				: `<tr><td colspan="7" class="text-muted">${__("Nothing yet")}</td></tr>`}</tbody></table>`;
			const d = new frappe.ui.Dialog({ title: fund === "Deposit" ? __("Security Deposit History") : __("Advance Payment History"), size: "extra-large" });
			d.$body.html(html);
			d.show();
		});
	};

	P.ledger = (frm, account_field) => {
		frappe.db.get_value("Rental Company Profile", { company: frm.doc.company }, account_field).then((r) => {
			frappe.route_options = { company: frm.doc.company, party_type: "Customer", party: [frm.doc.customer], account: r.message && r.message[account_field] ? [r.message[account_field]] : undefined,
				from_date: frm.doc.contract_date || frm.doc.start_date, to_date: frappe.datetime.get_today(), group_by: "Group by Voucher (Consolidated)" };
			frappe.set_route("query-report", "General Ledger");
		});
	};

	frappe.ui.form.on("Rental Contract", {
		refresh(frm) {
			if (frm.doc.docstatus !== 1) return;
			frappe.call({ method: M + "get_balances", args: { rental_contract: frm.doc.name } }).then((r) => {
				const b = r.message;
				if (!b) return;
				const currency = frm.doc.currency;
				const html = P.summary_html(b, currency);
				const wrap = frm.dashboard.add_section(html, __("Security Deposit and Advance"));
				wrap && wrap.addClass("nxg-contract-finance");
				const dep = __("Security Deposit"), adv = __("Advance Payment");
				// collect only while something is still to collect (null: nothing asked, no limit)
				const can = (v) => v == null || v > 0;
				if (can((b.remaining || {}).deposit)) frm.add_custom_button(__("Collect Deposit"), () => P.dialog(frm, "Deposit Collection", b), dep);
				frm.add_custom_button(__("View Collection History"), () => P.history(frm, "Deposit"), dep);
				if (b.deposit_balance > 0) {
					frm.add_custom_button(__("Refund Deposit"), () => P.dialog(frm, "Deposit Refund", b), dep);
					frm.add_custom_button(__("Adjust Deposit"), () => P.dialog(frm, "Deposit Deduction", b), dep);
				}
				frm.add_custom_button(__("View Ledger"), () => P.ledger(frm, "security_deposit_account"), dep);
				if (can((b.remaining || {}).advance)) frm.add_custom_button(__("Collect Advance"), () => P.dialog(frm, "Advance Collection", b), adv);
				frm.add_custom_button(__("View Payment History"), () => P.history(frm, "Advance"), adv);
				if (b.advance_available > 0) {
					frm.add_custom_button(__("Adjust Against Invoice"), () => P.dialog(frm, "Advance Adjustment", b), adv);
					frm.add_custom_button(__("Refund Advance"), () => P.dialog(frm, "Advance Refund", b), adv);
				}
				frm.add_custom_button(__("View Ledger"), () => P.ledger(frm, "customer_advance_account"), adv);
			});
			frm.add_custom_button(__("Pro Forma Invoice"), () => frappe.model.open_mapped_doc({ method: PF + "make_from_rental_contract", frm }), __("Create"));
		},
	});

	// rental or tax invoice: what advance the contract has, and adjust it against this invoice
	frappe.ui.form.on("Sales Invoice", {
		refresh(frm) {
			if (!frm.doc.nxg_rental_contract || frm.doc.is_return || frm.is_new()) return;
			frappe.call({ method: M + "get_invoice_advance", args: { sales_invoice: frm.doc.name } }).then((r) => {
				const a = r.message;
				if (!a || (a.advance_available <= 0 && a.already_adjusted <= 0)) return;
				const c = a.currency;
				frm.dashboard.add_comment(__("Invoice {0}: advance available on {1} {2}, already adjusted here {3}, adjustable now {4}, remaining payable {5}",
					[money(a.invoice_amount, c), a.rental_contract, money(a.advance_available, c), money(a.already_adjusted, c), money(a.suggested, c),
						money(a.remaining, c)]), "blue", true);
				if (frm.doc.docstatus === 1 && a.suggested > 0) {
					frm.add_custom_button(__("Adjust Advance"), () => {
						const rid = request_id();
						const d = new frappe.ui.Dialog({
							title: __("Adjust Advance"),
							fields: [
								{ fieldtype: "HTML", options: `<table class="table table-condensed small">
									<tr><td>${__("Invoice Gross Amount")}</td><td class="text-right">${esc(money(a.invoice_amount, c))}</td></tr>
									<tr><td>${__("Advance Available for Adjustment")}</td><td class="text-right">${esc(money(a.advance_available, c))}</td></tr>
									<tr><td>${__("Invoice Outstanding")}</td><td class="text-right">${esc(money(a.outstanding, c))}</td></tr></table>` },
								{ fieldname: "amount", fieldtype: "Currency", options: "currency", label: __("Advance Adjustment Amount"), reqd: 1, default: a.suggested,
									onchange() { d.set_df_property("remaining", "options", `<p class="small">${__("Remaining Customer Payable")}: <b>${esc(money(a.outstanding - flt(d.get_value("amount")), c))}</b></p>`); } },
								{ fieldname: "remaining", fieldtype: "HTML", options: `<p class="small">${__("Remaining Customer Payable")}: <b>${esc(money(a.remaining, c))}</b></p>` },
							],
							primary_action_label: __("Adjust"),
							primary_action(v) {
								frappe.call({ method: M + "create", freeze: true, args: { values: { transaction_type: "Advance Adjustment", rental_contract: a.rental_contract,
									sales_invoice: frm.doc.name, amount: v.amount, request_id: rid } } }).then(() => { d.hide(); frm.reload_doc(); });
							},
						});
						d.show();
					});
				}
			});
		},
	});
})();
