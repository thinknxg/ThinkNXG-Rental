// Job (JCR) billing rows on the Sales Invoice item grid.
// Each JCR line is a block: a title row ("JCR-no item @ location"), then a contract row and,
// when there are excess days, one excess row per billing period.
// Display only: the title rows get a CSS class and the numbering is re-applied every time
// the grid redraws, so it survives adding rows, saving, sorting and opening a row.
const NXG_STYLE_ID = "nxg-jcr-grid-style";

function nxg_is_title(d) {
    return !!d && d.nxg_row_type === "Title";
}

function nxg_inject_style() {
    if (document.getElementById(NXG_STYLE_ID)) return;
    const css = `
        .nxg-jcr-title { background: var(--bg-light-gray, #f5f7fa); }
        .nxg-jcr-title .grid-static-col .static-area,
        .nxg-jcr-title .grid-static-col .field-area { visibility: hidden; }
        .nxg-jcr-title .row-index span { visibility: hidden; }
        .nxg-jcr-title .grid-static-col[data-fieldname="description"] .static-area,
        .nxg-jcr-title .grid-static-col[data-fieldname="description"] .field-area { visibility: visible; font-weight: 700; }
        .nxg-jcr-title .grid-static-col[data-fieldname="item_code"] .static-area { visibility: visible; font-size: 0; }
        .nxg-jcr-title .grid-static-col[data-fieldname="item_code"] .static-area::after { content: "*"; font-size: 13px; font-weight: 700; }
    `;
    $("<style>").attr("id", NXG_STYLE_ID).text(css).appendTo(document.head);
}

const NXG_LOCKED_FIELDS = ["description", "item_code", "qty", "uom", "rate"];

function nxg_lock_row(gr) {
    if (!gr || !gr.doc || !gr.doc.nxg_row_type || gr._nxg_locked) return;
    gr._nxg_locked = true;
    NXG_LOCKED_FIELDS.forEach((f) => {
        try { gr.set_field_property(f, "read_only", 1); } catch (e) { /* column not rendered */ }
    });
}

function nxg_style_grid(frm) {
    const field = frm.fields_dict.items;
    const grid = field && field.grid;
    if (!grid || !(grid.grid_rows || []).length) return;
    if (!(frm.doc.items || []).some((r) => r.nxg_row_type)) return;
    nxg_inject_style();

    // Title rows are not numbered; every other row is numbered 1, 2, 3 ...
    let n = 0;
    grid.grid_rows.forEach((gr) => {
        const title = nxg_is_title(gr.doc);
        $(gr.wrapper).toggleClass("nxg-jcr-title", title);
        nxg_lock_row(gr);
        if (!title) {
            n += 1;
            const el = $(gr.wrapper).find(".row-index span").first();
            if (el.length && el.text() !== String(n)) el.text(n);
        }
    });
}

frappe.ui.form.on("Sales Invoice", {
    refresh(frm) {
        nxg_style_grid(frm);
        // the grid renders its rows after refresh; style once more when it is ready
        setTimeout(() => nxg_style_grid(frm), 300);

        const field = frm.fields_dict.items;
        const wrapper = field && field.grid && field.grid.wrapper;
        if (wrapper && wrapper.length && !frm._nxg_grid_observer) {
            frm._nxg_grid_observer = new MutationObserver(() => {
                if (frm._nxg_grid_pending) return;
                frm._nxg_grid_pending = true;
                requestAnimationFrame(() => {
                    frm._nxg_grid_pending = false;
                    nxg_style_grid(frm);
                });
            });
            frm._nxg_grid_observer.observe(wrapper[0], { childList: true, subtree: true });
        }
    },
    items_on_form_rendered(frm) {
        nxg_style_grid(frm);
    },
});

frappe.ui.form.on("Sales Invoice Item", {
    form_render(frm, cdt, cdn) {
        const row = locals[cdt] && locals[cdt][cdn];
        if (!row || !row.nxg_row_type) return;
        const gr = frm.fields_dict.items.grid.grid_rows_by_docname[cdn];
        if (!gr) return;
        NXG_LOCKED_FIELDS.forEach((f) => {
            try { gr.toggle_editable(f, false); } catch (e) { /* ignore */ }
        });
    },
});
