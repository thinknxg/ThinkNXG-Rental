frappe.ui.form.on("Job Type", {
    setup(frm) {
        frm.set_query("item_code", () => ({ filters: { is_stock_item: 0, disabled: 0 } }));
        frm.set_query("item_code", "rental_items", () => ({ filters: { is_stock_item: 1, disabled: 0 } }));
    },
    refresh(frm) {
        if (frm.is_new()) return;
        frm.add_custom_button(__("Duplicate"), () => {
            frappe.prompt(
                [
                    { fieldname: "new_item_code", label: __("New Job Type Item Code"), fieldtype: "Data", reqd: 1 },
                    { fieldname: "new_item_name", label: __("New Job Type Name"), fieldtype: "Data" },
                ],
                (values) => {
                    frappe
                        .call({
                            method: "thinknxg_rental.events.job_type.duplicate_job_type",
                            args: { source: frm.doc.name, new_item_code: values.new_item_code, new_item_name: values.new_item_name },
                            freeze: true,
                        })
                        .then((r) => {
                            if (r.message) frappe.set_route("Form", "Job Type", r.message);
                        });
                },
                __("Duplicate Job Type"),
                __("Create")
            );
        });
    },
});
