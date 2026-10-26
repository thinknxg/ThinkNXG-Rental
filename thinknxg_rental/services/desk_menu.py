"""Menu bar on the thinkNXG Rental desk workspace (/app/thinknxg-rental).

The bar has the same documents, in the same order, as the admin portal (/rental/admin): the
document flow Lead -> Quotation -> Rental Site -> Hire Order / Hire Order Contract -> Rental Contract
-> Reservation / Cross Hire Order -> Delivery Order -> JCR / Off-Hire Note -> Return Inspection ->
Damage Settlement -> Sales Invoice, then the portal boards. Each item opens the desk list, with a
"+" for a new document and a link to the same entry in the admin portal.

Labels come from the portal's ENTRY_TYPES (portal/entry.py), so a document renamed there is renamed
here. A portal entry that is not placed in MENU below is added to the last document group, so a new
portal entry still shows up on the desk. The bar itself is a Custom HTML Block that sync() writes on
every migrate; its script calls get_menu(), which leaves out what the user may not read.
"""
from urllib.parse import quote

import frappe
from frappe import _

BLOCK = "thinkNXG Rental Menu"

# Item: entry (key in ENTRY_TYPES) and/or doctype, report or url; label (else from ENTRY_TYPES or
# the DocType); filters for the desk list.
MENU = [
	dict(label="Sales", items=[
		dict(entry="lead", doctype="Lead"),
		dict(entry="quotation", doctype="Quotation"),
		dict(entry="rental-site", doctype="Rental Site"),
		dict(entry="request", doctype="Rental Portal Request", label="Customer Request"),
	]),
	dict(label="Hire Orders", items=[
		dict(entry="hire-order", doctype="Hire Order"),
		dict(entry="hire-order-contract", doctype="Hire Order Contract"),
		dict(entry="jcr", doctype="Job Completion Report"),
		dict(doctype="JCR Billing Schedule"),
	]),
	dict(label="Contracts", items=[
		dict(entry="rental-contract", doctype="Rental Contract"),
		dict(entry="material-reservation", doctype="Rental Material Reservation", label="Material Reservation"),
		dict(entry="delivery-order", doctype="Hire Delivery Order", label="Delivery Order"),
		dict(entry="off-hire-note", doctype="Hire Off-Hire Note", label="Off-Hire Note"),
	]),
	dict(label="Cross Hire", items=[
		dict(entry="cross-hire-order", doctype="Cross Hire Order"),
		dict(doctype="Purchase Order"),
		dict(entry="cross-hire-receipt", doctype="Purchase Receipt", label="Cross Hire Receipt",
			filters={"nxg_is_cross_hire_receipt": 1}),
		dict(entry="cross-hire-off-hire", doctype="Cross Hire Off-Hire Note"),
		dict(doctype="Purchase Invoice"),
	]),
	dict(label="Returns & Billing", items=[
		dict(entry="return-inspection", doctype="Rental Return Inspection", label="Return Inspection"),
		dict(entry="damage-settlement", doctype="Rental Damage Settlement", label="Damage Settlement"),
		dict(entry="sales-invoice", doctype="Sales Invoice"),
		dict(doctype="Rental Billing Schedule"),
		dict(entry="sales-order", doctype="Sales Order"),
		dict(entry="delivery-note", doctype="Delivery Note", label="Sales Delivery Note"),
	]),
	dict(label="Reports", items=[
		dict(report="Material at Site"),
		dict(report="Rental Stock Position"),
		dict(report="Cross Hire Position"),
		dict(report="Unbilled Rental"),
		dict(report="Damage and Loss Register"),
		dict(report="Hire Contract Profitability"),
	]),
	# The portal's boards, in its menu order (portal/admin.py MORE_NAV).
	dict(label="Admin Portal", portal=1, items=[
		dict(url="/rental/admin", label="Board"),
		dict(url="/rental/admin/requests", label="Customer requests"),
		dict(url="/rental/admin/contracts", label="Contract status"),
		dict(url="/rental/admin/sites", label="Material at site"),
		dict(url="/rental/admin/yard", label="Yard"),
		dict(url="/rental/admin/billing", label="Billing"),
		dict(url="/rental/admin/suppliers", label="Cross hire suppliers"),
		dict(url="/rental/admin/entries", label="Entries"),
	]),
	dict(label="Setup", items=[
		dict(doctype="Rental Settings"),
		dict(doctype="Rental Item Profile"),
		dict(doctype="Job Type"),
		dict(doctype="Rental Rate Card"),
		dict(doctype="Rental Ownership Ledger"),
	]),
]

# The flow line under the bar: one step per stage, "/" between documents of the same stage.
FLOW = [
	["Lead"], ["Quotation"], ["Rental Site"], ["Hire Order", "Hire Order Contract"], ["Rental Contract"],
	["Rental Material Reservation", "Cross Hire Order"], ["Hire Delivery Order"],
	["Job Completion Report", "Hire Off-Hire Note"], ["Rental Return Inspection"], ["Rental Damage Settlement"],
	["Sales Invoice"],
]


def _slug(name):
	return name.lower().replace(" ", "-")


def _desk_route(doctype, filters=None):
	route = f"/app/{_slug(doctype)}"
	if filters:
		route += "?" + "&".join(f"{k}={quote(str(v))}" for k, v in filters.items())
	return route


def _entries():
	from thinknxg_rental.portal.entry import ENTRY_TYPES

	return ENTRY_TYPES


def _item(spec, entries):
	cfg = entries.get(spec.get("entry")) or {}
	if spec.get("report"):
		name = spec["report"]
		if not frappe.db.exists("Report", name) or not frappe.has_permission("Report", "read", name):
			return None
		return {"label": _(spec.get("label") or name), "route": f"/app/query-report/{quote(name)}"}
	if spec.get("url"):
		return {"label": _(spec["label"]), "route": spec["url"], "portal": 1}
	doctype = spec.get("doctype") or cfg.get("doctype")
	if not frappe.db.exists("DocType", doctype) or not frappe.has_permission(doctype, "read"):
		return None
	item = {
		"label": _(spec.get("label") or cfg.get("label") or doctype),
		"doctype": doctype,
		"route": _desk_route(doctype, spec.get("filters")),
	}
	# A filtered list (cross hire receipts) is made from its source document, not from a blank form.
	if frappe.has_permission(doctype, "create") and not frappe.get_meta(doctype).issingle and not spec.get("filters"):
		item["new"] = f"/app/{_slug(doctype)}/new"
	if cfg and cfg.get("menu") != "none":
		item["portal"] = f"/rental/admin/entries?type={spec['entry']}"
	return item


@frappe.whitelist()
def get_menu():
	"""The menu bar groups and the flow line, with only what the user may read."""
	entries = _entries()
	menu = [dict(g, items=list(g["items"])) for g in MENU]
	placed = {i.get("entry") for g in MENU for i in g["items"]}
	last_docs = [g for g in menu if not g.get("portal") and g["label"] not in ("Reports", "Setup")][-1]
	last_docs["items"] += [dict(entry=k) for k, cfg in entries.items() if k not in placed and cfg.get("menu") != "none"]

	groups, routes = [], {}
	for g in menu:
		items = [i for i in (_item(s, entries) for s in g["items"]) if i]
		for i in items:
			routes.setdefault(i.get("doctype"), i)
		if items:
			groups.append({"label": _(g["label"]), "portal": g.get("portal", 0), "items": items})

	flow = []
	for step in FLOW:
		docs = [{"label": routes[d]["label"], "route": routes[d]["route"]} for d in step if d in routes]
		if docs:
			flow.append(docs)
	return {"groups": groups, "flow": flow}


# ----------------------------------------------------------------------------- the block
HTML = """<nav class="nxg-menu" aria-label="thinkNXG Rental"></nav><ol class="nxg-flow"></ol>"""

STYLE = """
:host { display: block; }
.nxg-menu { display: flex; flex-wrap: wrap; gap: 2px; padding: 4px; border: 1px solid var(--border-color, #e2e2e2);
	border-radius: var(--border-radius-md, 8px); background: var(--card-bg, #fff); }
.nxg-group { position: relative; }
.nxg-group > button { font: inherit; font-size: var(--text-md, 13px); font-weight: 500; color: var(--text-color, #1f272e);
	background: none; border: 0; border-radius: var(--border-radius, 6px); padding: 6px 12px; cursor: pointer; }
.nxg-group > button:hover, .nxg-group.open > button { background: var(--subtle-fg, #f3f3f3); }
.nxg-group > button::after { content: ""; display: inline-block; margin-left: 6px; vertical-align: 2px;
	border: 4px solid transparent; border-top-color: currentColor; border-bottom: 0; opacity: .6; }
.nxg-group.portal > button { color: var(--primary, #2490ef); }
.nxg-drop { display: none; position: absolute; z-index: 20; top: calc(100% + 4px); left: 0; min-width: min(300px, calc(100vw - 48px)); margin: 0;
	padding: 4px; list-style: none; background: var(--card-bg, #fff); border: 1px solid var(--border-color, #e2e2e2);
	border-radius: var(--border-radius-md, 8px); box-shadow: var(--shadow-md, 0 4px 16px rgba(0,0,0,.12)); }
.nxg-group.open .nxg-drop { display: block; }
.nxg-drop li { display: flex; align-items: center; gap: 4px; border-radius: var(--border-radius, 6px); }
.nxg-drop li:hover { background: var(--subtle-fg, #f3f3f3); }
.nxg-drop a { color: var(--text-color, #1f272e); text-decoration: none; font-size: var(--text-md, 13px); }
.nxg-drop a.nxg-open { flex: 1; padding: 6px 8px; white-space: nowrap; }
.nxg-drop a.nxg-side { padding: 2px 6px; font-size: var(--text-sm, 12px); color: var(--text-muted, #6c7680);
	border-radius: var(--border-radius-sm, 4px); }
.nxg-drop a.nxg-side:hover { color: var(--text-color, #1f272e); background: var(--card-bg, #fff); }
.nxg-flow { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 0; margin: 10px 0 0; padding: 0; list-style: none;
	font-size: var(--text-sm, 12px); color: var(--text-muted, #6c7680); }
.nxg-flow li { display: flex; align-items: center; }
.nxg-flow li + li::before { content: "\\2192"; margin: 0 6px; }
.nxg-flow a { color: var(--text-color, #1f272e); text-decoration: none; padding: 2px 6px; border-radius: var(--border-radius-sm, 4px);
	background: var(--subtle-fg, #f3f3f3); }
.nxg-flow a:hover { background: var(--subtle-accent, #e9ecef); }
.nxg-flow .nxg-or { margin: 0 3px; }
"""

SCRIPT = """
const nav = root_element.querySelector(".nxg-menu");
const flow = root_element.querySelector(".nxg-flow");
const esc = (s) => frappe.utils.escape_html(s || "");
const link = (route, label, cls, title) =>
	`<a class="${cls || ""}" href="${esc(route)}" ${title ? `title="${esc(title)}"` : ""}>${esc(label)}</a>`;

frappe.xcall("thinknxg_rental.services.desk_menu.get_menu").then((m) => {
	nav.innerHTML = m.groups.map((g) => `
		<div class="nxg-group ${g.portal ? "portal" : ""}">
			<button type="button" aria-expanded="false">${esc(g.label)}</button>
			<ul class="nxg-drop">${g.items.map((i) => `<li>
				${link(i.route, i.label, "nxg-open")}
				${i.new ? link(i.new, "+ " + __("New"), "nxg-side", __("New {0}", [__(i.label)])) : ""}
				${i.portal && i.doctype ? link(i.portal, __("Portal"), "nxg-side", __("Open in the admin portal")) : ""}
			</li>`).join("")}</ul>
		</div>`).join("");
	flow.innerHTML = m.flow.map((step) =>
		`<li>${step.map((d) => link(d.route, d.label)).join('<span class="nxg-or">/</span>')}</li>`).join("");
});

const close = (except) => nav.querySelectorAll(".nxg-group.open").forEach((g) => {
	if (g !== except) { g.classList.remove("open"); g.firstElementChild.setAttribute("aria-expanded", "false"); }
});
root_element.addEventListener("click", (e) => {
	const btn = e.target.closest(".nxg-group > button");
	if (btn) {
		const g = btn.parentElement;
		close(g);
		btn.setAttribute("aria-expanded", g.classList.toggle("open") ? "true" : "false");
		return;
	}
	const a = e.target.closest("a");
	if (!a) return;
	close();
	// Desk routes open in place; the shadow root hides the link from the desk router, so route here.
	const href = a.getAttribute("href");
	if (href.startsWith("/app/") && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
		e.preventDefault();
		frappe.set_route(href);
	}
});
document.addEventListener("click", (e) => { if (!e.composedPath().includes(root_element)) close(); });
root_element.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
"""


def sync():
	"""Write the menu bar block (after_migrate). The workspace JSON places it at the top."""
	values = {"html": HTML, "style": STYLE, "script": SCRIPT, "private": 0}
	if frappe.db.exists("Custom HTML Block", BLOCK):
		doc = frappe.get_doc("Custom HTML Block", BLOCK)
		if any(doc.get(k) != v for k, v in values.items()):
			doc.update(values)
			doc.save(ignore_permissions=True)
	else:
		doc = frappe.new_doc("Custom HTML Block")
		doc.update(values)
		doc.insert(ignore_permissions=True, set_name=BLOCK)
