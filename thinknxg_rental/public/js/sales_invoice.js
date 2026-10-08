// Job (JCR) billing rows on the Sales Invoice item grid.
// Each JCR line is a block: a title row ("JCR-no item @ location"), then a contract row and,
// when there are excess days, one excess row per billing period.
const NXG_STYLE_ID = "nxg-jcr-grid-style";

function nxg_inject_style() {
    if (document.getElementById(NXG_STYLE_ID)) return;
    const css = `
        .nxg-jcr-title .grid-static-col:not([data-fieldname="description"]):not([data-fieldname="item_code"]) .static-area { visibility: hidden; }
        .nxg-jcr-title .grid-static-col[data-fieldname="description"] .static-area,
        .nxg-jcr-title .grid-static-col[data-fieldname="item_code"] .static-area { font-weight: 700; }
        .nxg-jcr-title { background: var(--bg-light-gray, #f5f7fa); }
    `;
    $("<style>").attr("id", NXG_STYLE_ID).text(css).appendTo(document.head);
}

function nxg_style_grid(frm) {
    const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
    if (!grid || !(grid.grid_rows || []).length) return;
    nxg_inject_style();
    let n = 0;
    grid.grid_rows.forEach((gr) => {
        const d = gr.doc;
        if (!d) return;
        const $row = $(gr.wrapper);
        const is_title = d.nxg_row_type === "Title";
        $row.toggleClass("nxg-jcr-title", is_title);
        if (is_title) {
            // Heading rows show "*" in place of the item code and are not numbered.
            $row.find('.grid-static-col[data-fieldname="item_code"] .static-area').text("*");
            $row.find(".row-index span").text("");
        } else {
            n += 1;
            $row.find(".row-index span").text(n);
        }
    });
}

frappe.ui.form.on("Sales Invoice", {
    refresh(frm) {
        if ((frm.doc.items || []).some((r) => r.nxg_row_type)) {
            nxg_style_grid(frm);
            // the grid renders its rows after refresh; style once more when it is ready
            setTimeout(() => nxg_style_grid(frm), 300);
        }
    },
    items_on_form_rendered(frm) {
        nxg_style_grid(frm);
    },
});
