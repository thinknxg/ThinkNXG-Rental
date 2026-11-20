// Rental rates: when one of Daily / Weekly / Monthly is entered, the other two are filled if they are empty.
// An entered rate is never overwritten. Factors: Weekly = Daily x 7, Monthly = Daily x 30 (as billing counts a month).
const NXG_WEEK_DAYS = 7;
const NXG_MONTH_DAYS = 30;

function nxg_fill_rates(frm, source) {
    if (frm._nxg_filling) return;
    const value = flt(frm.doc[source]);
    if (value <= 0) return;
    const daily = source === "daily_rate" ? value
        : source === "weekly_rate" ? value / NXG_WEEK_DAYS
        : value / NXG_MONTH_DAYS;
    const fill = {
        daily_rate: daily,
        weekly_rate: daily * NXG_WEEK_DAYS,
        monthly_rate: daily * NXG_MONTH_DAYS,
    };
    frm._nxg_filling = true;
    try {
        Object.keys(fill).forEach((field) => {
            if (field !== source && !flt(frm.doc[field])) {
                frm.set_value(field, flt(fill[field], 2));
            }
        });
    } finally {
        frm._nxg_filling = false;
    }
}

frappe.ui.form.on("Rental Item Profile", {
    daily_rate(frm) { nxg_fill_rates(frm, "daily_rate"); },
    weekly_rate(frm) { nxg_fill_rates(frm, "weekly_rate"); },
    monthly_rate(frm) { nxg_fill_rates(frm, "monthly_rate"); },
});
