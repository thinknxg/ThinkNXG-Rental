// Subcontracting block of the Hire Order Contract: balance, cost and the actions that lead to the work orders.
frappe.ui.form.on("Hire Order Contract", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || !frappe.model.can_read("Subcontract Work Order")) return;
		const API = "thinknxg_rental.subcontracting.api.";
		frm.add_custom_button(__("Subcontract Work Order"), () => frappe.call({
			method: API + "make_subcontract_work_order", args: { hire_order_contract: frm.doc.name },
			callback: (r) => { const doc = frappe.model.sync(r.message)[0]; frappe.set_route("Form", doc.doctype, doc.name); },
		}), __("Create"));
		const open = (doctype, label) => frm.add_custom_button(__(label), () =>
			frappe.set_route("List", doctype, { hire_order_contract: frm.doc.name }), __("Subcontracting"));
		open("Subcontract Work Order", "Work Orders");
		open("Subcontract Material Allocation", "Material Allocation");
		open("Subcontract Work Progress", "Work Progress");
		open("Subcontract Completion Report", "Completion Reports");
		frm.add_custom_button(__("Cost Summary"), () => frappe.call({
			method: API + "get_subcontract_summary", args: { hire_order_contract: frm.doc.name },
			callback: (r) => {
				const s = r.message, p = s.profitability, c = (v) => format_currency(v, s.currency);
				frappe.msgprint({ title: __("Subcontract Cost Summary"), wide: true, message: `<table class="table table-bordered"><tbody>
					<tr><td>${__("Subcontract work orders")}</td><td>${s.work_orders} (${s.subcontractors} ${__("subcontractors")})</td></tr>
					<tr><td>${__("Quantity: contract / subcontracted / balance")}</td><td>${s.total_contract_qty} / ${s.subcontracted_qty} / ${s.balance_qty}</td></tr>
					<tr><td>${__("Completion")}</td><td>${s.completion_pct}%</td></tr>
					<tr><td>${__("Labour / Equipment (ordered)")}</td><td>${c(s.labour_cost)} / ${c(s.equipment_cost)}</td></tr>
					<tr><td>${__("Estimated / certified subcontract cost")}</td><td>${c(s.estimated_cost)} / ${c(s.actual_cost)}</td></tr>
					<tr><td>${__("Customer revenue")}</td><td>${c(p.customer_revenue)}</td></tr>
					<tr><td>${__("Subcontract cost (net of recoveries)")}</td><td>${c(p.subcontract_cost)}</td></tr>
					<tr><td>${__("Other direct costs (cross hire)")}</td><td>${c(p.other_direct_costs)}</td></tr>
					<tr><td><b>${__("Net profit")}</b></td><td><b>${c(p.net_profit)}</b> (${flt(p.margin, 1)}%)</td></tr></tbody></table>` });
			},
		}), __("Subcontracting"));
		frappe.call({
			method: API + "get_subcontract_summary", args: { hire_order_contract: frm.doc.name }, callback: (r) => {
				const s = r.message; if (!s || !s.work_orders) return;
				frm.dashboard.add_indicator(__("Subcontracted {0} of {1}", [s.subcontracted_qty, s.total_contract_qty]), s.balance_qty ? "orange" : "green");
				frm.dashboard.add_indicator(__("{0} work orders, {1} subcontractors", [s.work_orders, s.subcontractors]), "blue");
				frm.dashboard.add_indicator(__("Subcontract completion {0}%", [s.completion_pct]), s.completion_pct >= 100 ? "green" : "orange");
			},
		});
	},
});
