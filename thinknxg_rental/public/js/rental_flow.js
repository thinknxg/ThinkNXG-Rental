// Flow navigation for the rental process, so nobody has to search for the next document:
//
//   Hire Order Contract -> Rental Contract -> Material Reservation -> Cross Hire Order
//   -> Purchase Order -> Purchase Receipt -> Delivery Order (material at site) -> JCR -> Sales Invoice
//
// Adds "next step" buttons and links on Cross Hire Order, Purchase Order, Purchase Receipt,
// Material Reservation, Delivery Order and Rental Contract. Existing buttons are not touched.
(function () {
    const RC = "thinknxg_rental.thinknxg_rental.doctype.rental_contract.rental_contract.";
    const HOC = "thinknxg_rental.thinknxg_rental.doctype.hire_order_contract.hire_order_contract.";
    const OPEN = (label, doctype, filters) => ({ label, route: () => frappe.set_route("List", doctype, filters) });

    function is_live(status) {
        return !["Completed", "Cancelled"].includes(status);
    }

    // Buttons that jump to related documents of one Rental Contract.
    function add_view_buttons(frm, rc, extra) {
        const group = __("Flow");
        const views = [
            { label: __("Rental Contract"), route: () => frappe.set_route("Form", "Rental Contract", rc) },
            ...(extra || []),
            OPEN(__("Material Reservations"), "Rental Material Reservation", { rental_contract: rc }),
            OPEN(__("Cross Hire Orders"), "Cross Hire Order", { rental_contract: rc }),
            OPEN(__("Delivery Orders"), "Hire Delivery Order", { rental_contract: rc }),
            OPEN(__("Job Completion Reports"), "Job Completion Report", { rental_contract: rc }),
            OPEN(__("Sales Invoices"), "Sales Invoice", { nxg_rental_contract: rc }),
        ];
        views.forEach((v) => frm.add_custom_button(v.label, v.route, group));
    }

    // "Create" buttons for the steps after the material is available.
    function add_next_steps(frm, rc, info, opts) {
        opts = opts || {};
        const group = __("Next Step");
        if (opts.delivery !== false && is_live(info.status)) {
            frm.add_custom_button(__("Delivery Order (send to site)"), () => {
                if (opts.reservation) {
                    frappe.route_options = { rental_contract: rc, rental_material_reservation: opts.reservation };
                    frappe.new_doc("Hire Delivery Order");
                } else {
                    frappe.model.open_mapped_doc({ method: RC + "make_delivery_order", source_name: rc });
                }
            }, group);
        }
        if (info.contract_type === "Job Type Contract" && info.hire_order_contract && is_live(info.status)) {
            frm.add_custom_button(__("Job Completion Report (JCR)"), () =>
                frappe.model.open_mapped_doc({ method: HOC + "make_jcr", source_name: info.hire_order_contract }), group);
        }
        frm.page.set_inner_btn_group_as_primary(group);
    }

    // Fetch the Rental Contract once, then add buttons unless the form has refreshed in the meantime.
    function with_contract(frm, rc, callback) {
        if (!rc) return;
        const token = (frm._nxg_flow_token = (frm._nxg_flow_token || 0) + 1);
        frappe.db.get_value("Rental Contract", rc, ["status", "contract_type", "hire_order_contract"]).then((r) => {
            if (token !== frm._nxg_flow_token || !r.message) return;
            callback(r.message);
        });
    }

    function hint(frm, text) {
        frm.dashboard.add_comment(text, "blue", true);
    }

    frappe.ui.form.on("Cross Hire Order", {
        refresh(frm) {
            if (frm.doc.docstatus !== 1) return;
            const rc = frm.doc.rental_contract;
            const received = (frm.doc.items || []).some((d) => flt(d.received_qty) > 0);
            const to_receive = (frm.doc.items || []).some((d) => flt(d.received_qty) < flt(d.qty));
            const extra = [];
            if (frm.doc.purchase_order) extra.push({ label: __("Purchase Order"), route: () => frappe.set_route("Form", "Purchase Order", frm.doc.purchase_order) });
            extra.push(OPEN(__("Purchase Receipts"), "Purchase Receipt", { nxg_cross_hire_order: frm.doc.name }));
            if (frm.doc.material_reservation) extra.push({ label: __("Material Reservation"), route: () => frappe.set_route("Form", "Rental Material Reservation", frm.doc.material_reservation) });
            if (rc) {
                with_contract(frm, rc, (info) => {
                    add_view_buttons(frm, rc, extra);
                    if (received) add_next_steps(frm, rc, info, { reservation: frm.doc.material_reservation });
                });
            }
            if (frm.doc.status !== "Completed") {
                if (to_receive) hint(frm, __("Next step: when the supplier delivers, use Create > Cross Hire Receipt."));
                else if (received && rc) hint(frm, __("Material received. Next steps: Create > Delivery Order to send it to site, then the Job Completion Report (JCR)."));
            }
        },
    });

    frappe.ui.form.on("Purchase Order", {
        refresh(frm) {
            if (!frm.doc.nxg_is_cross_hire || frm.doc.docstatus !== 1 || !frm.doc.nxg_cross_hire_order) return;
            frappe.db.get_value("Cross Hire Order", frm.doc.nxg_cross_hire_order, "status").then((r) => {
                if (!r.message || r.message.status !== "To Receive") return;
                frm.add_custom_button(__("Cross Hire Receipt"), () =>
                    frappe.call({
                        method: "thinknxg_rental.services.cross_hire.make_cross_hire_receipt",
                        args: { cross_hire_order: frm.doc.nxg_cross_hire_order },
                        freeze: true,
                        callback(res) {
                            if (!res.message) return;
                            const doc = frappe.model.sync(res.message)[0];
                            frappe.set_route("Form", doc.doctype, doc.name);
                        },
                    }), __("Create"));
                frm.page.set_inner_btn_group_as_primary(__("Create"));
            });
            if (frm.doc.nxg_rental_contract) {
                frm.add_custom_button(__("Rental Contract"), () => frappe.set_route("Form", "Rental Contract", frm.doc.nxg_rental_contract), __("Flow"));
            }
        },
    });

    frappe.ui.form.on("Purchase Receipt", {
        refresh(frm) {
            if (!frm.doc.nxg_is_cross_hire_receipt || frm.doc.docstatus !== 1 || !frm.doc.nxg_cross_hire_order) return;
            frappe.db.get_value("Cross Hire Order", frm.doc.nxg_cross_hire_order, ["rental_contract", "material_reservation"]).then((r) => {
                const cho = r.message || {};
                const rc = cho.rental_contract;
                if (!rc) return;
                with_contract(frm, rc, (info) => {
                    add_view_buttons(frm, rc, [
                        { label: __("Cross Hire Order"), route: () => frappe.set_route("Form", "Cross Hire Order", frm.doc.nxg_cross_hire_order) },
                    ]);
                    add_next_steps(frm, rc, info, { reservation: cho.material_reservation });
                });
                hint(frm, __("Material received. Next steps: Create > Delivery Order to send it to site, then the Job Completion Report (JCR)."));
            });
        },
    });

    frappe.ui.form.on("Rental Material Reservation", {
        refresh(frm) {
            if (frm.doc.docstatus !== 1 || !frm.doc.rental_contract) return;
            const rc = frm.doc.rental_contract;
            with_contract(frm, rc, (info) => {
                add_view_buttons(frm, rc);
                if (["Reserved", "Partially Reserved"].includes(frm.doc.status)) {
                    add_next_steps(frm, rc, info, { reservation: frm.doc.name });
                }
            });
        },
    });

    frappe.ui.form.on("Hire Delivery Order", {
        refresh(frm) {
            if (frm.doc.docstatus !== 1 || !frm.doc.rental_contract) return;
            const rc = frm.doc.rental_contract;
            with_contract(frm, rc, (info) => {
                add_view_buttons(frm, rc);
                // material is at site: the next step is the JCR
                add_next_steps(frm, rc, info, { delivery: false });
            });
        },
    });

})();
