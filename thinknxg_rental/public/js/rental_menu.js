// thinkNXG Rental menu bar: floats at the bottom of every desk page while the user works in
// thinkNXG Rental (forms, lists, reports, Print), with Home to get back to the workspace.
//
// It also keeps thinkNXG Rental as the app on screen. A v16 desk shows the sidebar of the module a
// page belongs to, so Print (Printing) or a Customer (Selling) used to swap the thinkNXG Rental
// sidebar out. Here, a page opened while thinkNXG Rental is on screen stays in thinkNXG Rental;
// the user leaves it by opening another app or workspace. Forms, permissions, routing and Print
// are the desk's own; only the choice of sidebar changes.
//
// The menu comes from thinknxg_rental.services.desk_menu.get_menu, the same groups as the admin
// portal, with only what the user may read.
(function () {
	const APP = "thinkNXG Rental"; // the workspace, and the module sidebar of the same name
	const HOME = "/app/thinknxg-rental";
	const CONTEXT_KEY = "nxg_rental_context";
	const MIN_KEY = "nxg_rental_menu_min";

	let menu = null;
	let bar = null;
	let rental_doctypes = new Set();

	// Storage can be blocked (private windows); the bar then just forgets.
	const read = (store, key) => {
		try {
			return window[store].getItem(key);
		} catch (e) {
			return null;
		}
	};
	const write = (store, key, value) => {
		try {
			window[store].setItem(key, value);
		} catch (e) {
			// ignore
		}
	};

	const sidebar = () => frappe.app && frappe.app.sidebar;
	// v16 with module sidebars knows which one is on screen.
	const has_shells = () => !!(sidebar() && typeof sidebar().shell_can_show === "function");

	function in_rental() {
		if (has_shells()) return sidebar().current_module === APP;
		return read("sessionStorage", CONTEXT_KEY) === "1";
	}

	// Earlier v16 sidebars follow the workspace: remember that the user came from thinkNXG Rental
	// until they open another workspace.
	function track_context(route) {
		if (has_shells()) return;
		if (route[0] === "Workspaces") {
			write("sessionStorage", CONTEXT_KEY, route[route.length - 1] === APP ? "1" : "0");
		} else if (rental_doctypes.has(route[1])) {
			write("sessionStorage", CONTEXT_KEY, "1");
		}
	}

	// While thinkNXG Rental is on screen it can show any page, so the desk keeps it there. Opening
	// another workspace, or another app from the app switcher, still leaves it. Patched on the class
	// as this file loads, since the desk resolves its first route before app_ready.
	function hold_sidebar() {
		const proto = frappe.ui && frappe.ui.Sidebar && frappe.ui.Sidebar.prototype;
		if (!proto || typeof proto.shell_can_show !== "function" || proto.__nxg_rental_held) return;
		const can_show = proto.shell_can_show;
		proto.shell_can_show = function (shell, route, opts) {
			if (can_show.call(this, shell, route, opts)) return true;
			// On a reload nothing is on screen yet, and the URL (/desk/thinknxg-rental/...) says where it was.
			const here = this.current_module === APP || frappe.router.current_shell === APP;
			return shell === APP && here && !!route && !!route.length && route[0] !== "Workspaces";
		};
		proto.__nxg_rental_held = true;
	}
	hold_sidebar();

	const esc = (s) => frappe.utils.escape_html(s || "");
	const link = (route, label, cls, title) =>
		`<a class="${cls || ""}" href="${esc(route)}"${title ? ` title="${esc(title)}"` : ""}>${esc(label)}</a>`;

	function render() {
		bar = document.createElement("div");
		bar.className = "nxg-fbar";
		bar.setAttribute("role", "navigation");
		bar.setAttribute("aria-label", APP);
		bar.innerHTML = `
			<div class="nxg-fbar-row">
				${link(HOME, __("Home"), "nxg-fbar-home", __("Back to the {0} workspace", [APP]))}
				<button type="button" class="nxg-fbar-toggle" aria-expanded="false">${esc(__("Menu"))}</button>
				<div class="nxg-fbar-groups">${menu.groups
					.map(
						(g) => `
					<div class="nxg-fbar-group${g.portal ? " portal" : ""}">
						<button type="button" aria-expanded="false">${esc(g.label)}</button>
						<ul class="nxg-fbar-drop">${g.items
							.map(
								(i) => `<li data-doctype="${esc(i.doctype)}">
							${link(i.route, i.label, "nxg-open")}
							${i.new ? link(i.new, "+ " + __("New"), "nxg-side", __("New {0}", [__(i.label)])) : ""}
							${i.portal && i.doctype ? link(i.portal, __("Portal"), "nxg-side", __("Open in the admin portal")) : ""}
						</li>`
							)
							.join("")}</ul>
					</div>`
					)
					.join("")}</div>
				<button type="button" class="nxg-fbar-min" title="${esc(__("Hide the menu"))}" aria-label="${esc(
					__("Hide the menu")
				)}">&minus;</button>
			</div>`;
		const show = document.createElement("button");
		show.type = "button";
		show.className = "nxg-fbar-show";
		show.textContent = __("{0} menu", [APP]);

		bar.addEventListener("click", on_click);
		bar.addEventListener("keydown", (e) => e.key === "Escape" && close());
		show.addEventListener("click", () => minimize(false));
		document.addEventListener("click", (e) => {
			if (!bar.contains(e.target)) close();
		});
		window.addEventListener("resize", () => bar.querySelectorAll(".nxg-fbar-group.open").forEach(place));
		document.body.append(bar, show);
	}

	function on_click(e) {
		if (e.target.closest(".nxg-fbar-min")) return minimize(true);
		if (e.target.closest(".nxg-fbar-toggle")) {
			const open = bar.classList.toggle("sheet");
			e.target.closest("button").setAttribute("aria-expanded", open ? "true" : "false");
			return;
		}
		const btn = e.target.closest(".nxg-fbar-group > button");
		if (btn) {
			const g = btn.parentElement;
			close(g);
			const open = g.classList.toggle("open");
			btn.setAttribute("aria-expanded", open ? "true" : "false");
			if (open) place(g);
			return;
		}
		const a = e.target.closest("a");
		if (!a) return;
		close();
		bar.classList.remove("sheet");
		const href = a.getAttribute("href");
		// Desk routes open in place, in thinkNXG Rental; the portal opens as a page of its own.
		if (href.startsWith("/app/") && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
			e.preventDefault();
			e.stopPropagation();
			frappe.set_route(href);
		}
	}

	// An open list stays on the screen: moved left when it would run past the right edge.
	function place(g) {
		const drop = g.querySelector(".nxg-fbar-drop");
		if (bar.classList.contains("sheet")) {
			drop.style.left = "";
			return;
		}
		const margin = 8;
		drop.style.left = "0px";
		drop.style.maxWidth = `${window.innerWidth - 2 * margin}px`;
		const r = drop.getBoundingClientRect();
		const shift = Math.max(margin - r.left, Math.min(0, window.innerWidth - margin - r.right));
		drop.style.left = `${shift}px`;
	}

	function close(except) {
		if (!bar) return;
		bar.querySelectorAll(".nxg-fbar-group.open").forEach((g) => {
			if (g === except) return;
			g.classList.remove("open");
			g.firstElementChild.setAttribute("aria-expanded", "false");
		});
	}

	function minimize(on) {
		write("localStorage", MIN_KEY, on ? "1" : "0");
		refresh();
	}

	function refresh() {
		if (!bar) return;
		const route = frappe.get_route() || [];
		const on = in_rental();
		const min = read("localStorage", MIN_KEY) === "1";
		document.body.classList.toggle("nxg-fbar-on", on && !min);
		document.body.classList.toggle("nxg-fbar-min-on", on && min);
		if (!on) {
			close();
			bar.classList.remove("sheet");
		}
		// The group holding the page on screen is marked.
		bar.querySelectorAll(".nxg-fbar-group").forEach((g) => {
			g.classList.toggle("current", !!route[1] && !!g.querySelector(`li[data-doctype="${CSS.escape(route[1])}"]`));
		});
	}

	function on_route() {
		track_context(frappe.get_route() || []);
		// The sidebar settles on its module after the route change; read it then.
		setTimeout(refresh, 0);
	}

	$(document).on("app_ready", () => {
		if (!frappe.boot || !frappe.boot.setup_complete || frappe.session.user === "Guest") return;
		frappe
			.xcall("thinknxg_rental.services.desk_menu.get_menu")
			.then((m) => {
				if (!m || !m.groups || !m.groups.length) return;
				menu = m;
				m.groups.forEach((g) => g.items.forEach((i) => i.doctype && rental_doctypes.add(i.doctype)));
				render();
				frappe.router.on("change", on_route);
				on_route();
			})
			.catch(() => {});
	});
})();
