// thinkNXG Rental customer portal: the request form on /rental/requests.
(function () {
	const form = document.getElementById("rp-form");
	if (!form) return;
	const boot = window.rp_boot || {};
	const $ = (id) => document.getElementById(id);
	const lines = $("rp-lines");
	const msg = $("rp-form-msg");
	const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
	const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
	const API = "thinknxg_rental.portal.api.";
	let catalogue = null;

	function call(method, args) {
		if (boot.customer) args = Object.assign({ customer: boot.customer }, args);
		return new Promise((resolve, reject) => {
			frappe.call({
				method: API + method,
				args,
				type: method === "create_request" || method === "cancel_request" ? "POST" : "GET",
				callback: (r) => resolve(r.message),
				error: (r) => reject(r),
			});
		});
	}

	function fail(text) {
		msg.textContent = text;
		msg.hidden = false;
		msg.scrollIntoView({ block: "nearest" });
	}

	function type() {
		const checked = form.querySelector('input[name="request_type"]:checked');
		return checked ? checked.value : "";
	}

	function show_fields() {
		const t = type();
		form.querySelectorAll("[data-for]").forEach((el) => {
			el.hidden = !el.dataset.for.split(",").includes(t);
		});
		msg.hidden = true;
		lines.innerHTML = "";
		$("rp-add-line").hidden = t !== "Hire Enquiry";
		$("rp-all").hidden = t !== "Off-Hire Request";
		$("rp-col-site").hidden = t !== "Off-Hire Request";
		$("rp-lines-hint").textContent = "";
		if (t === "Hire Enquiry") load_catalogue().then(add_enquiry_line);
		if (t === "Off-Hire Request") load_contract_items();
		if (t === "Extension Request") show_end_hint();
	}

	function load_catalogue() {
		if (catalogue) return Promise.resolve(catalogue);
		return call("get_catalogue", {}).then((rows) => (catalogue = rows || []));
	}

	function add_enquiry_line() {
		if (!catalogue.length) {
			$("rp-lines-hint").textContent = __("The hire catalogue is empty. Describe what you need in the box below.");
			return;
		}
		let options = `<option value="">${esc(__("Choose an item"))}</option>`;
		let group = null;
		catalogue.forEach((i) => {
			if (i.category !== group) {
				if (group !== null) options += "</optgroup>";
				options += `<optgroup label="${esc(__(i.category || "Other"))}">`;
				group = i.category;
			}
			const rate = i.monthly_rate ? ` (${fmt(i.monthly_rate)} / ${__("month")})` : "";
			options += `<option value="${esc(i.item_code)}">${esc(i.item_name)}${esc(rate)}</option>`;
		});
		if (group !== null) options += "</optgroup>";
		const tr = document.createElement("tr");
		tr.innerHTML = `<td><select data-item aria-label="${esc(__("Item"))}">${options}</select></td>
			<td hidden></td>
			<td><input type="number" data-qty min="0" step="any" inputmode="decimal" aria-label="${esc(__("Quantity"))}"></td>
			<td><button type="button" class="rp-btn rp-btn--plain" data-remove>${esc(__("Remove"))}</button></td>`;
		lines.appendChild(tr);
	}

	function load_contract_items() {
		const contract = $("rp-contract").value;
		lines.innerHTML = "";
		if (!contract) {
			$("rp-lines-hint").textContent = __("Choose a contract to see what is at site.");
			return;
		}
		$("rp-lines-hint").textContent = "";
		call("get_contract_items", { hire_contract: contract }).then((data) => {
			if (!data || !data.items.length) {
				$("rp-lines-hint").textContent = __("Nothing is at site on this contract.");
				return;
			}
			data.items.forEach((i) => {
				const tr = document.createElement("tr");
				tr.dataset.item = i.item_code;
				tr.dataset.max = i.at_site_qty;
				tr.innerHTML = `<td>${esc(i.item_name)}</td>
					<td>${fmt(i.at_site_qty)} ${esc(i.uom)}</td>
					<td><input type="number" data-qty min="0" max="${Number(i.at_site_qty)}" step="any" inputmode="decimal" aria-label="${esc(__("Quantity to collect"))} ${esc(i.item_name)}"></td>
					<td></td>`;
				lines.appendChild(tr);
			});
		});
	}

	function show_end_hint() {
		const option = $("rp-contract").selectedOptions[0];
		const end = option && option.dataset.end;
		$("rp-end-hint").textContent = end ? __("Currently ends {0}", [end]) : "";
		if (end) $("rp-newend").min = end;
	}

	function collect_items() {
		const items = [];
		lines.querySelectorAll("tr").forEach((tr) => {
			const select = tr.querySelector("[data-item]");
			const item_code = select ? select.value : tr.dataset.item;
			const qty = parseFloat(tr.querySelector("[data-qty]").value);
			if (item_code && qty > 0) items.push({ item_code, qty });
		});
		return items;
	}

	function open_form(preset, contract) {
		form.hidden = false;
		$("rp-done").hidden = true;
		const map = { "off-hire": "Off-Hire Request", enquiry: "Hire Enquiry", extension: "Extension Request" };
		const value = map[preset] || (boot.has_material ? "Off-Hire Request" : "Hire Enquiry");
		form.querySelector(`input[name="request_type"][value="${value}"]`).checked = true;
		if (contract) $("rp-contract").value = contract;
		show_fields();
		form.scrollIntoView({ block: "start", behavior: "smooth" });
	}

	$("rp-new").addEventListener("click", () => open_form());
	$("rp-cancel-form").addEventListener("click", () => {
		form.hidden = true;
		form.reset();
	});
	form.querySelectorAll('input[name="request_type"]').forEach((el) => el.addEventListener("change", show_fields));
	$("rp-contract").addEventListener("change", () => {
		if (type() === "Off-Hire Request") load_contract_items();
		if (type() === "Extension Request") show_end_hint();
	});
	$("rp-add-line").addEventListener("click", add_enquiry_line);
	$("rp-all").addEventListener("click", () => {
		lines.querySelectorAll("tr").forEach((tr) => {
			if (tr.dataset.max) tr.querySelector("[data-qty]").value = tr.dataset.max;
		});
	});
	lines.addEventListener("click", (e) => {
		if (e.target.matches("[data-remove]")) e.target.closest("tr").remove();
	});

	form.addEventListener("submit", (e) => {
		e.preventDefault();
		msg.hidden = true;
		const t = type();
		const data = new FormData(form);
		const args = { request_type: t, remarks: data.get("remarks") || "" };
		if (t === "Hire Enquiry") {
			Object.assign(args, {
				required_date: data.get("required_date"),
				expected_return_date: data.get("expected_return_date"),
				site_location: data.get("site_location"),
				items: collect_items(),
			});
			if (!args.required_date) return fail(__("Tell us when you need the material."));
			if (!args.items.length) return fail(__("Add at least one item and a quantity."));
		} else {
			args.hire_contract = data.get("hire_contract");
			if (!args.hire_contract) return fail(__("Choose a contract."));
			if (t === "Off-Hire Request") {
				args.required_date = data.get("collection_date");
				args.items = collect_items();
				if (!args.items.length) return fail(__("Enter the quantity to collect for at least one item."));
				const over = [...lines.querySelectorAll("tr")].find((tr) => parseFloat(tr.querySelector("[data-qty]").value) > parseFloat(tr.dataset.max));
				if (over) return fail(__("You cannot return more than is at site."));
			} else {
				args.new_end_date = data.get("new_end_date");
				if (!args.new_end_date) return fail(__("Choose the new end date."));
			}
		}
		const button = $("rp-submit");
		button.disabled = true;
		call("create_request", args)
			.then((r) => {
				if (!r || !r.name) return;
				const url = new URL(window.location.href);
				url.searchParams.delete("new");
				url.searchParams.delete("contract");
				url.searchParams.set("sent", r.name);
				window.location.href = url.toString();
			})
			.catch(() => {})
			.finally(() => (button.disabled = false));
	});

	document.querySelectorAll("[data-cancel]").forEach((el) =>
		el.addEventListener("click", () => {
			if (!window.confirm(__("Withdraw request {0}?", [el.dataset.cancel]))) return;
			call("cancel_request", { name: el.dataset.cancel }).then(() => window.location.reload());
		})
	);

	const sent = new URLSearchParams(window.location.search).get("sent");
	if (sent) {
		$("rp-done").textContent = __("Request {0} sent. We will confirm it shortly.", [sent]);
		$("rp-done").hidden = false;
	}
	if (boot.new) open_form(boot.new, boot.contract);
})();
