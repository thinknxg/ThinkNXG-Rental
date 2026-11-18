// Excess material, returns and adjustments: dialogs shared by the off-hire note, the rental contract,
// the excess register and the dismantling entry. Loaded with each of those forms (hooks.doctype_js).
frappe.provide("thinknxg_rental");

(() => {
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const qty = (v) => esc(format_number(flt(v), null, 3).replace(/\.?0+$/, "") || "0");
	const link = (doctype, name) => (name ? `<a href="${frappe.utils.get_form_link(doctype, name)}">${esc(name)}</a>` : "");
	const table = (heads, rows) =>
		`<table class="table table-bordered table-condensed" style="font-size: var(--text-sm)"><thead><tr>${heads
			.map((h) => `<th${h.num ? ' class="text-right"' : ""}>${esc(h.label)}</th>`)
			.join("")}</tr></thead><tbody>${
			rows.length
				? rows.map((r) => `<tr>${r.map((c, i) => `<td${heads[i].num ? ' class="text-right"' : ""}>${c}</td>`).join("")}</tr>`).join("")
				: `<tr><td colspan="${heads.length}" class="text-muted">${esc(__("Nothing yet"))}</td></tr>`
		}</tbody></table>`;

	// every return and adjustment of a register, an off-hire note's excess or a contract's excess
	thinknxg_rental.excess_history = (args) => {
		frappe.call({
			method: "thinknxg_rental.thinknxg_rental.doctype.excess_material_return_note.excess_material_return_note.get_history",
			args,
			callback(r) {
				const m = r.message || { registers: [], history: [] };
				const regs = table(
					[{ label: __("Excess Register") }, { label: __("Item") }, { label: __("Received"), num: 1 }, { label: __("Available"), num: 1 }, { label: __("Status") }],
					m.registers.map((g) => [link("Excess Material Register", g.name), esc(g.item_code), qty(g.excess_qty), qty(g.available_qty), esc(__(g.status))])
				);
				const hist = table(
					[{ label: __("Date") }, { label: __("Document") }, { label: __("Excess Register") }, { label: __("Excess Item") }, { label: __("Qty"), num: 1 },
						{ label: __("Settled Against") }, { label: __("State") }],
					m.history.map((h) => [
						esc(frappe.datetime.str_to_user(h.posting_date)),
						`${esc(__(h.doctype))}<br>${link(h.doctype, h.name)}`,
						link("Excess Material Register", h.excess_register),
						esc(h.item_code),
						qty(h.qty),
						h.outstanding_item ? `${qty(h.settled_qty)} ${esc(h.outstanding_item)}` : esc(__("Returned to customer")),
						h.docstatus === 2 ? `<span class="text-danger">${esc(__("Cancelled"))}</span>` : esc(__("Submitted")),
					])
				);
				const d = new frappe.ui.Dialog({ title: __("Adjustment History"), size: "extra-large" });
				d.$body.html(`<h6>${esc(__("Excess Material"))}</h6>${regs}<h6 class="mt-4">${esc(__("Returns and Adjustments"))}</h6>${hist}`);
				d.show();
			},
		});
	};

	// the reconciliation of a contract: delivered = returned + lost + adjusted + outstanding, and the excess
	thinknxg_rental.reconciliation_dialog = (frm) => {
		frm.call("get_reconciliation").then((r) => {
			const m = r.message;
			const items = table(
				[{ label: __("Item") }, { label: __("Delivered"), num: 1 }, { label: __("Returned"), num: 1 }, { label: __("Lost"), num: 1 },
					{ label: __("Adjusted"), num: 1 }, { label: __("Outstanding"), num: 1 }],
				m.items.map((i) => [`${esc(i.item_code)}<br><span class="text-muted">${esc(i.item_name)}</span>`, qty(i.delivered), qty(i.returned),
					qty(i.lost), qty(i.adjusted), flt(i.outstanding) > 0 ? `<b class="text-danger">${qty(i.outstanding)}</b>` : qty(i.outstanding)])
			);
			const ex = table(
				[{ label: __("Excess Register") }, { label: __("Item") }, { label: __("Received"), num: 1 }, { label: __("Returned to Customer"), num: 1 },
					{ label: __("Adjusted"), num: 1 }, { label: __("Available"), num: 1 }],
				m.excess.map((e) => [link("Excess Material Register", e.register), esc(e.item_code), qty(e.excess_qty), qty(e.returned_qty), qty(e.adjusted_qty),
					qty(e.available_qty)])
			);
			const state = m.reconciled
				? `<div class="alert alert-success">${esc(__("Reconciled: everything delivered is accounted for and no excess is left."))}</div>`
				: `<div class="alert alert-warning"><b>${esc(__("Not reconciled"))}</b><ul class="mb-0">${m.issues.map((i) => `<li>${esc(i)}</li>`).join("")}</ul></div>`;
			const exc = m.exception
				? `<div class="alert alert-info">${esc(__("Exception approved by {0} on {1}: {2}", [m.exception.reconciliation_exception_by,
					frappe.datetime.str_to_user(m.exception.reconciliation_exception_on), m.exception.reconciliation_exception_reason]))}</div>`
				: "";
			const d = new frappe.ui.Dialog({ title: __("Material Reconciliation - {0}", [frm.doc.name]), size: "extra-large" });
			d.$body.html(`${state}${exc}<h6>${esc(__("Delivered Material"))}</h6>${items}<h6 class="mt-4">${esc(__("Excess Material"))}</h6>${ex}`);
			if (!m.reconciled && !m.exception && frappe.user.has_role(["Rental Manager", "System Manager"])) {
				d.set_primary_action(__("Approve Exception"), () => {
					d.hide();
					thinknxg_rental.approve_exception(frm);
				});
			}
			d.show();
			frm.reload_doc();
		});
	};

	thinknxg_rental.approve_exception = (frm) => {
		frappe.prompt(
			[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1,
				description: __("Recorded on the contract and in its timeline. The contract and its project can then be closed with the open issues.") }],
			(v) => frm.call("approve_reconciliation_exception", { reason: v.reason }).then(() => {
				frappe.show_alert({ message: __("Reconciliation exception approved"), indicator: "green" });
				frm.reload_doc();
			}),
			__("Approve Reconciliation Exception"),
			__("Approve")
		);
	};
})();
