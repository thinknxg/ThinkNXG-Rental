/* thinkNXG Rental customer Command Center: requests, messages, notifications and account pages. */
(function () {
	"use strict";
	const { el, icon } = cp;
	const P = cp.pages;
	const FORMS = () => cp.boot.request_forms || {};
	const ORDER = ["Additional Material Request", "Extension Request", "Off-Hire Request", "Pickup Request", "Delivery Reschedule", "Replacement Request",
		"Damage Report", "Missing Material Report", "Hire Enquiry", "Complaint", "Support Request"];

	// ================================================================== request table (shared by the request lists)
	cp.requestTable = function (args) {
		return cp.dataTable({
			method: "requests",
			args,
			search: __("Request, subject, order or site"),
			filters: [{ name: "status", label: __("All statuses"), options: [["open", __("Open and in progress")], ["closed", __("Closed")], ["Completed", __("Completed")], ["Rejected", __("Declined")], ["Cancelled", __("Cancelled")]] }],
			columns: [
				{ label: __("Request"), render: (r) => el("div", {}, cp.link(r.route, r.subject || r.name, { class: "cp-strong" }), el("span", { class: "cp-sub", text: r.subject ? r.name + ", " + r.label : r.label })) },
				{ label: __("Raised"), render: (r) => cp.date(r.request_date) },
				{ label: __("Order"), render: (r) => el("div", {}, r.rental_contract ? cp.link("orders/" + r.rental_contract, r.rental_contract) : "", el("span", { class: "cp-sub", text: r.rental_site || r.site_location || "" })) },
				{ label: __("For"), render: (r) => (r.new_end_date ? __("Return by {0}", [cp.date(r.new_end_date)]) : r.required_date ? cp.date(r.required_date) : "") },
				{ label: __("Units"), num: 1, render: (r) => (r.qty ? cp.qty(r.qty) : "") },
				{ label: __("Status"), render: (r) => cp.badge(r.status === "Rejected" ? "Rejected" : r.status) },
			],
			href: (r) => r.route,
			mobile: (r) => ({ title: r.subject || r.name, badge: cp.badge(r.status), meta: [[__("Type"), r.label], [__("Raised"), cp.date(r.request_date)], [__("Order"), r.rental_contract]] }),
			empty: { title: __("No requests yet"), text: __("Requests you raise are tracked here until they are completed."), icon: "life-buoy",
				action: cp.can_request() ? cp.btn(__("New request"), null, { href: cp.href("requests/new"), primary: true }) : null },
		});
	};

	P.requests = async function (ctx) {
		ctx.setTitle(__("Service Requests"));
		const groups = [["", __("All")], ["additional", __("Material")], ["extensions", __("Extensions")], ["returns", __("Returns and pickups")], ["deliveries", __("Deliveries")], ["service", __("Replacement, damage, missing")], ["support", __("Support")]];
		const g = ctx.query.get("group") || "";
		ctx.main.replaceChildren(cp.pageHead(__("Service Requests"), __("Everything you have asked the rental team for, and where it stands."),
			cp.can_request() ? [cp.btn(__("New request"), null, { href: cp.href("requests/new"), primary: true, icon: "plus" })] : []),
		el("div", { style: { marginBottom: "14px", overflowX: "auto" } }, cp.tabs(groups, g, (v) => cp.go("requests" + (v ? "?group=" + v : "")), __("Request group"))),
		cp.requestTable({ group: g }));
	};

	// ================================================================== new request
	P.new_request = async function (ctx) {
		ctx.setTitle(__("New request"), [[__("Service Requests"), "requests"]]);
		if (!cp.can_request()) {
			ctx.main.replaceChildren(cp.pageHead(__("New request")), cp.card(null, cp.empty(__("Online requests are not available"),
				cp.boot.staff ? __("Staff previews are read-only.") : __("Please contact the rental team directly."), null, "lock")));
			return;
		}
		const q = ctx.query;
		const forms = FORMS();
		let type = forms[q.get("type")] ? q.get("type") : null;
		const opts = await cp.api("request_options");
		if (!ctx.isCurrent()) return;
		const host = el("div", {});
		const chooser = el("div", { class: "cp-types", role: "radiogroup", "aria-label": __("Request type") });
		const draw = () => {
			chooser.replaceChildren(...ORDER.filter((t) => forms[t]).map((t) => {
				const f = forms[t];
				return el("button", { type: "button", class: "cp-type" + (t === type ? " is-on" : ""), role: "radio", "aria-checked": String(t === type), onclick: () => {
					type = t;
					history.replaceState(null, "", cp.href("requests/new?type=" + encodeURIComponent(t) + (q.get("contract") ? "&contract=" + encodeURIComponent(q.get("contract")) : "")));
					draw();
				} }, el("span", { class: "cp-kpi__icon" }, icon(f.icon, "cp-i--sm")), el("span", {}, el("b", { text: f.label }), el("span", { text: f.help })));
			}));
			host.replaceChildren(type ? buildForm(type, opts, q) : el("p", { class: "cp-sub", text: __("Choose what you need above.") }));
		};
		draw();
		ctx.main.replaceChildren(cp.pageHead(__("New request"), __("Tell us what you need. You can follow its progress and message the team on the request.")),
			cp.card(__("What do you need?"), chooser), el("div", { style: { height: "18px" } }), host);
	};

	function buildForm(type, opts, q) {
		const f = FORMS()[type];
		const data = { request_type: type, items: [] };
		const form = el("div", { class: "cp-form" });
		const errors = el("div", { role: "alert" });
		let contract = null;
		const contracts = opts.contracts || [];

		// contract
		const itemsHost = el("div", { class: "is-wide" });
		const contractInfo = el("small", {});
		let contractSel = null;
		if (f.contract || f.contract_optional) {
			contractSel = el("select", { class: "cp-select", id: "cp-f-contract" }, el("option", { value: "", text: f.contract ? __("Choose a rental order") : __("Not about a particular order") }),
				contracts.map((c) => el("option", { value: c.name, text: (c.source_document || c.name) + ", " + c.rental_site, selected: c.name === q.get("contract") })));
			form.appendChild(el("label", { class: "cp-label is-wide", for: "cp-f-contract" }, el("span", { class: f.contract ? "cp-req" : null, text: __("Rental order") }), contractSel, contractInfo));
			if (f.contract && !contracts.length) {
				return cp.card(null, cp.empty(__("No open rental orders"), __("This request needs a live rental order. Raise a support request if you need help."), cp.btn(__("Support request"), null, { href: cp.href("requests/new?type=Support Request") }), "file-check-2"));
			}
		}
		// fields by type
		const field = (label, input, opt) => el("label", { class: "cp-label" + (opt && opt.wide ? " is-wide" : "") }, el("span", { class: opt && opt.reqd ? "cp-req" : null, text: label }), input, opt && opt.help ? el("small", { text: opt.help }) : null);
		const inputs = {};
		if (f.subject) form.appendChild(field(__("Subject"), (inputs.subject = el("input", { class: "cp-input", maxlength: 140 })), { wide: 1, reqd: 1 }));
		if (f.new_end_date) form.appendChild(field(__("Requested new return date"), (inputs.new_end_date = el("input", { type: "date", class: "cp-input", min: cp.today() })), { reqd: 1, help: __("Must be after the current return date.") }));
		if (f.date) form.appendChild(field(__(f.date), (inputs.required_date = el("input", { type: "date", class: "cp-input", min: cp.today() })), { reqd: f.date_reqd }));
		if (f.return_date) form.appendChild(field(__("Expected return date"), (inputs.expected_return_date = el("input", { type: "date", class: "cp-input", min: cp.today() }))));
		if (f.location) form.appendChild(field(__(f.location), (inputs.site_location = el("input", { class: "cp-input", maxlength: 140 }))));
		if (f.items) form.appendChild(itemsHost);
		const remarksLabel = type === "Extension Request" ? __("Reason for the extension") : f.remarks_reqd ? __("Describe the request") : __("Remarks");
		form.appendChild(field(remarksLabel, (inputs.remarks = el("textarea", { class: "cp-textarea", maxlength: 2000 })), { wide: 1, reqd: f.remarks_reqd }));
		// attachments
		const files = [];
		const fileList = el("ul", { class: "cp-files" });
		const picker = el("input", { type: "file", multiple: true, accept: ".pdf,.jpg,.jpeg,.png,.webp,.heic,.gif,.doc,.docx,.xls,.xlsx,.csv,.txt", class: "cp-sr", id: "cp-f-files" });
		const addFiles = (list) => {
			for (const file of list) {
				if (file.size > 10 * 1024 * 1024) { cp.toast(__("{0} is larger than 10 MB", [file.name]), "bad"); continue; }
				if (files.length >= 10) break;
				files.push(file);
			}
			fileList.replaceChildren(...files.map((file, i) => el("li", {}, icon("paperclip", "cp-i--sm"), file.name, el("span", { text: Math.ceil(file.size / 1024) + " KB" }),
				el("button", { type: "button", class: "cp-iconbtn", "aria-label": __("Remove {0}", [file.name]), onclick: () => { files.splice(i, 1); addFiles([]); } }, icon("x", "cp-i--sm")))));
		};
		picker.addEventListener("change", () => { addFiles(picker.files); picker.value = ""; });
		const drop = el("label", { class: "cp-dropzone", for: "cp-f-files" }, icon("upload"), " ", __("Add photos or documents"), el("small", { style: { display: "block" }, text: __("PDF, images or Office files, up to 10 MB each") }));
		drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("is-over"); });
		drop.addEventListener("dragleave", () => drop.classList.remove("is-over"));
		drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("is-over"); addFiles(e.dataTransfer.files); });
		form.appendChild(el("div", { class: "is-wide" }, el("div", { class: "cp-label", text: f.attachments ? __("Photos and documents") : __("Supporting attachments (optional)") }), picker, drop, fileList));

		// items editors
		async function loadContract() {
			contract = contractSel && contractSel.value ? contracts.find((c) => c.name === contractSel.value) : null;
			contractInfo.textContent = contract ? __("Site {0}, return date {1}, {2} units on site", [contract.rental_site, cp.date(contract.end_date), cp.qty(contract.total_at_site_qty)]) : "";
			if (inputs.new_end_date && contract) inputs.new_end_date.min = contract.end_date;
			if (!f.items) return;
			if (f.items === "catalogue") return drawCatalogue();
			if (!contract) return itemsHost.replaceChildren(el("p", { class: "cp-sub", text: __("Choose the rental order to see the material on site.") }));
			itemsHost.replaceChildren(cp.skeleton(3));
			const o = await cp.api("request_options", { contract: contract.name });
			drawSiteItems(o.site_items || []);
		}
		function drawSiteItems(rows) {
			data.items = rows.map((r) => ({ item_code: r.item_code, qty: q.get("item") === r.item_code ? r.at_site_qty : 0, max: r.at_site_qty }));
			if (!rows.length) return itemsHost.replaceChildren(el("div", { class: "cp-callout is-warn" }, icon("info"), __("There is no material on site for this order.")));
			const all = el("input", { type: "checkbox", "aria-label": __("All of it") });
			const qtyInputs = [];
			all.addEventListener("change", () => qtyInputs.forEach((inp, i) => { inp.value = all.checked ? rows[i].at_site_qty : 0; data.items[i].qty = Number(inp.value); }));
			const label = type === "Extension Request" ? __("Units to keep (optional)") : type === "Replacement Request" ? __("Units to replace") : ["Damage Report", "Missing Material Report"].includes(type) ? __("Units affected") : __("Units to return");
			itemsHost.replaceChildren(el("span", { class: "cp-label " + (f.items_optional ? "" : "cp-req"), text: __("Material on site") }), el("div", { class: "cp-tablewrap cp-card", style: { marginTop: "6px" } }, el("table", { class: "cp-table cp-items" },
				el("thead", {}, el("tr", {}, el("th", { text: __("Item") }), el("th", { class: "cp-num", text: __("On site") }), el("th", { class: "cp-num" }, el("label", { style: { display: "inline-flex", gap: "6px", alignItems: "center" } }, all, label)))),
				el("tbody", {}, rows.map((r, i) => {
					const inp = el("input", { type: "number", class: "cp-input", min: 0, max: r.at_site_qty, step: "any", value: data.items[i].qty, "aria-label": __("{0} quantity", [r.item_name]) });
					inp.addEventListener("input", () => (data.items[i].qty = Number(inp.value) || 0));
					qtyInputs.push(inp);
					return el("tr", {}, el("td", {}, el("b", { text: r.item_name }), el("span", { class: "cp-sub", text: r.item_code })), el("td", { class: "cp-num", text: cp.qty(r.at_site_qty) + " " + (r.uom || "") }), el("td", { class: "cp-num" }, inp));
				})))));
		}
		function drawCatalogue() {
			const cat = opts.catalogue || [];
			const body = el("tbody", {});
			const add = (code, qty) => {
				const sel = el("select", { class: "cp-select", style: { width: "100%" }, "aria-label": __("Item") }, el("option", { value: "", text: __("Choose an item") }),
					groupBy(cat).map(([g, list]) => el("optgroup", { label: g || __("Other") }, list.map((c) => el("option", { value: c.item_code, text: c.item_name + " (" + c.item_code + ")", selected: c.item_code === code })))));
				const inp = el("input", { type: "number", class: "cp-input", min: 0, step: "any", value: qty || "", "aria-label": __("Quantity") });
				const row = { get item_code() { return sel.value; }, get qty() { return Number(inp.value) || 0; } };
				data.items.push(row);
				const tr = el("tr", {}, el("td", {}, sel), el("td", { class: "cp-num" }, inp),
					el("td", {}, el("button", { type: "button", class: "cp-iconbtn", "aria-label": __("Remove line"), onclick: () => { data.items.splice(data.items.indexOf(row), 1); tr.remove(); } }, icon("trash-2", "cp-i--sm"))));
				body.appendChild(tr);
			};
			data.items = [];
			add(q.get("item"), null);
			itemsHost.replaceChildren(el("span", { class: "cp-label cp-req", text: __("Material needed") }), el("div", { class: "cp-tablewrap cp-card", style: { marginTop: "6px" } }, el("table", { class: "cp-table cp-items" },
				el("thead", {}, el("tr", {}, el("th", { text: __("Item") }), el("th", { class: "cp-num", text: __("Quantity") }), el("th", {}))), body)),
			cp.btn(__("Add item"), () => add(), { sm: true, icon: "plus", ghost: true }));
		}
		if (contractSel) contractSel.addEventListener("change", loadContract);
		loadContract();

		const submit = cp.btn(__("Submit request"), async () => {
			errors.replaceChildren();
			const payload = { request_type: type, rental_contract: contractSel ? contractSel.value : null };
			for (const [k, inp] of Object.entries(inputs)) payload[k] = inp.value.trim();
			payload.items = data.items.map((i) => ({ item_code: i.item_code, qty: i.qty })).filter((i) => i.item_code && i.qty > 0);
			const bad = data.items.find((i) => i.max != null && i.qty > i.max);
			if (bad) return errors.replaceChildren(el("div", { class: "cp-callout is-bad" }, icon("triangle-alert"), __("A quantity is more than what is on site.")));
			let res;
			try {
				res = await cp.api("submit_request", { data: payload }, { post: true });
			} catch (e) {
				errors.replaceChildren(el("div", { class: "cp-callout is-bad" }, icon("triangle-alert"), e.message));
				return;
			}
			let failed = 0;
			for (const file of files) {
				try {
					const content = await readFile(file);
					await cp.api("upload_attachment", { name: res.name, filename: file.name, content }, { post: true });
				} catch (e) {
					failed++;
				}
			}
			cp.toast(failed ? __("Request {0} sent, but {1} attachment(s) could not be uploaded.", [res.name, failed]) : __("Request {0} sent. We will be in touch.", [res.name]), failed ? "bad" : "ok");
			cp.go(res.route);
		}, { primary: true, icon: "send" });
		return cp.card(FORMS()[type].label, el("div", {}, form, errors, el("div", { style: { display: "flex", gap: "8px", justifyContent: "flex-end", marginTop: "18px" } },
			cp.btn(__("Cancel"), null, { href: cp.href("requests") }), submit)));
	}
	function groupBy(cat) {
		const m = new Map();
		for (const c of cat) {
			if (!m.has(c.category)) m.set(c.category, []);
			m.get(c.category).push(c);
		}
		return [...m.entries()];
	}
	function readFile(file) {
		return new Promise((resolve, reject) => {
			const r = new FileReader();
			r.onload = () => resolve(String(r.result));
			r.onerror = () => reject(r.error);
			r.readAsDataURL(file);
		});
	}

	// ================================================================== request detail
	P.request = async function (ctx) {
		const r = await cp.api("request", { name: ctx.params[0] });
		if (!ctx.isCurrent()) return;
		ctx.setTitle(r.subject || r.name, [[__("Service Requests"), "requests"]]);
		const actions = [];
		if (r.can_cancel && cp.can_request()) actions.push(cp.btn(__("Cancel request"), async () => {
			if (!(await cp.confirm(__("Cancel this request?"), __("The rental team will stop working on {0}.", [r.name]), __("Cancel request"), true))) return;
			await cp.api("cancel_request", { name: r.name }, { post: true });
			cp.toast(__("Request cancelled."));
			cp.reload();
		}, { danger: true, icon: "x" }));
		const steps = [{ title: __("Request raised"), date: r.request_date, detail: r.raised_by ? __("by {0}", [r.raised_by]) : null, icon: "send" }];
		if (["In Progress", "Completed", "Rejected"].includes(r.status)) steps.push({ title: __("Being handled by the rental team"), icon: "loader" });
		if (r.status === "Completed") steps.push({ title: __("Completed"), icon: "circle-check", detail: r.reference ? r.reference.doctype + " " + r.reference.name : null, route: r.reference && r.reference.route });
		if (r.status === "Rejected") steps.push({ title: __("Declined"), icon: "circle-x" });
		if (r.status === "Cancelled") steps.push({ title: __("Cancelled"), icon: "circle-x" });
		const response = r.response ? el("div", { class: "cp-callout " + (r.status === "Rejected" ? "is-bad" : "is-good"), style: { marginBottom: "18px" } }, icon("message-square"),
			el("div", {}, el("b", { text: __("Reply from the rental team") }), el("div", { style: { whiteSpace: "pre-wrap" }, text: r.response }))) : null;
		const details = cp.card(__("Details"), cp.facts([[__("Reference"), r.name], [__("Type"), r.label], [__("Raised"), cp.date(r.request_date)], [__("Raised by"), r.raised_by],
			[__("Rental order"), r.rental_contract ? cp.link("orders/" + r.rental_contract, r.rental_contract) : null], [__("Site"), r.rental_site], [__("Location"), r.site_location],
			[__("Requested date"), cp.date(r.required_date)], [__("Expected return"), cp.date(r.expected_return_date)], [__("New return date"), cp.date(r.new_end_date)],
			[__("Result"), r.reference ? (r.reference.route ? cp.link(r.reference.route, r.reference.doctype + " " + r.reference.name) : r.reference.doctype + " " + r.reference.name) : null]]));
		const remarks = r.remarks ? cp.card(__("Description"), el("p", { style: { margin: 0, whiteSpace: "pre-wrap" }, text: r.remarks })) : null;
		const items = r.items.length ? cp.card(__("Material"), el("div", { class: "cp-tablewrap" }, el("table", { class: "cp-table" },
			el("thead", {}, el("tr", {}, el("th", { text: __("Item") }), el("th", { class: "cp-num", text: __("Quantity") }))),
			el("tbody", {}, r.items.map((i) => el("tr", {}, el("td", {}, el("b", { text: i.item_name }), el("span", { class: "cp-sub", text: i.item_code })), el("td", { class: "cp-num", text: cp.qty(i.qty) + " " + (i.uom || "") })))))), { flush: true }) : null;

		// attachments
		const fileList = el("ul", { class: "cp-files" }, r.files.map((x) => el("li", {}, icon("paperclip", "cp-i--sm"),
			el("a", { href: cp.fileUrl("download_attachment", { request: r.name, file: x.name }), target: "_blank", rel: "noopener", text: x.file_name }), el("span", { text: cp.date(x.creation) }))));
		let upload = null;
		if (r.can_attach && cp.can_request()) {
			const picker = el("input", { type: "file", class: "cp-sr", id: "cp-r-file", accept: ".pdf,.jpg,.jpeg,.png,.webp,.heic,.gif,.doc,.docx,.xls,.xlsx,.csv,.txt" });
			picker.addEventListener("change", async () => {
				const file = picker.files[0];
				if (!file) return;
				try {
					await cp.api("upload_attachment", { name: r.name, filename: file.name, content: await readFile(file) }, { post: true });
					cp.toast(__("{0} attached.", [file.name]));
					cp.reload();
				} catch (e) {
					cp.toast(e.message, "bad");
				}
			});
			upload = el("label", { class: "cp-btn cp-btn--sm", for: "cp-r-file", style: { marginTop: "10px" } }, icon("paperclip", "cp-i--sm"), __("Attach a file"), picker);
		}
		const attachments = r.files.length || upload ? cp.card(__("Attachments"), el("div", {}, r.files.length ? fileList : el("p", { class: "cp-sub", style: { margin: 0 }, text: __("No files yet.") }), upload)) : null;

		// conversation
		const msgs = el("div", { class: "cp-msgs" }, r.messages.length ? r.messages.map((m) => el("div", { class: "cp-msg" + (m.mine ? " is-mine" : "") },
			el("small", { text: (m.mine ? m.sender_full_name || __("You") : m.sender_full_name || __("Rental team")) + ", " + cp.datetime(m.communication_date) }), m.content))
			: [el("p", { class: "cp-sub", style: { margin: 0 }, text: __("No messages yet. Write to the rental team below.") })]);
		let reply = null;
		if (r.can_message && cp.can_request()) {
			const box = el("textarea", { class: "cp-textarea", placeholder: __("Write a message to the rental team"), "aria-label": __("Message"), maxlength: 4000 });
			reply = el("div", { class: "cp-reply" }, box, cp.btn(__("Send"), async () => {
				if (!box.value.trim()) return;
				await cp.api("add_request_message", { name: r.name, message: box.value }, { post: true });
				cp.toast(__("Message sent."));
				cp.reload();
			}, { primary: true, icon: "send" }));
		}
		const conversation = cp.card(__("Messages"), el("div", {}, msgs, reply));
		ctx.main.replaceChildren(cp.pageHead(r.subject || r.label, r.subject ? r.label + ", " + r.name : r.name, actions),
			el("div", { style: { margin: "-10px 0 18px" } }, cp.badge(r.status)), response,
			el("div", { class: "cp-grid cp-grid--main" }, el("div", { class: "cp-stack" }, details, remarks, items, conversation), el("div", { class: "cp-stack" }, cp.card(__("Progress"), cp.timeline(steps)), attachments)));
	};

	// ================================================================== communications
	P.communications = async function (ctx) {
		ctx.setTitle(__("Communication History"));
		ctx.main.replaceChildren(cp.pageHead(__("Communication History"), __("E-mails and messages between your team and ours.")),
			cp.dataTable({
				method: "communications",
				search: __("Subject or document"),
				columns: [
					{ label: __("When"), render: (r) => cp.datetime(r.communication_date) },
					{ label: __("Message"), render: (r) => el("div", { style: { maxWidth: "70ch" } }, el("b", { text: r.subject || __("(no subject)") }), el("span", { class: "cp-sub", text: r.content.slice(0, 220) + (r.content.length > 220 ? "…" : "") })) },
					{ label: __("From"), render: (r) => el("div", {}, cp.badge(r.direction === "from_you" ? __("From you") : __("From the rental team"), r.direction === "from_you" ? "blue" : "teal"), el("span", { class: "cp-sub", text: r.sender_full_name || "" })) },
					{ label: __("About"), render: (r) => (r.route ? cp.link(r.route, r.reference_name) : r.reference_name || "") },
				],
				mobile: (r) => ({ title: r.subject || __("(no subject)"), badge: el("span", { class: "cp-sub", text: cp.ago(r.communication_date) }), meta: [[__("From"), r.sender_full_name], [__("About"), r.reference_name]] }),
				href: (r) => r.route,
				empty: { title: __("No messages yet"), text: __("Messages on your requests and e-mails about your account appear here."), icon: "messages-square" },
			}));
	};

	// ================================================================== notifications
	P.notifications = async function (ctx) {
		ctx.setTitle(__("Notifications"));
		const unread = ctx.query.get("unread") === "1";
		const list = el("div", {});
		let page = 1;
		const more = cp.btn(__("Load more"), () => load(page + 1), { sm: true });
		async function load(p) {
			const d = await cp.api("notifications", { page: p, page_length: 25, unread: unread ? 1 : 0 });
			page = p;
			cp.setCounter("unread", d.unread);
			if (p === 1) list.replaceChildren();
			if (!d.rows.length && p === 1) list.appendChild(cp.empty(unread ? __("No unread notifications") : __("No notifications yet"), __("Order confirmations, deliveries, returns, invoices, payments and request updates appear here."), null, "bell"));
			d.rows.forEach((n) => list.appendChild(cp.noteRow(n)));
			more.style.display = d.page < d.pages ? "" : "none";
		}
		ctx.main.replaceChildren(cp.pageHead(__("Notifications"), __("Updates about your orders, deliveries, invoices and requests."), [
			cp.btn(__("Mark all read"), async () => {
				const r = await cp.api("mark_notifications_read", {}, { post: true });
				cp.setCounter("unread", r.unread);
				load(1);
			}, { icon: "check-check" })]),
		el("div", { style: { marginBottom: "14px" } }, cp.tabs([["all", __("All")], ["unread", __("Unread")]], unread ? "unread" : "all", (v) => cp.go("notifications" + (v === "unread" ? "?unread=1" : "")))),
		el("section", { class: "cp-card" }, list, el("div", { class: "cp-pager", style: { justifyContent: "center" } }, more)));
		await load(1);
	};

	// ================================================================== profile and contacts
	async function loadProfile() {
		return cp.api("profile");
	}
	function address(a) {
		return el("div", { class: "cp-card", style: { padding: "14px 16px" } }, el("div", { style: { display: "flex", gap: "8px", alignItems: "center", marginBottom: "6px" } },
			el("b", { text: a.address_title || __(a.address_type) }), cp.badge(__(a.address_type), "plain"), a.is_primary_address ? cp.badge(__("Primary"), "blue") : null, a.is_shipping_address ? cp.badge(__("Shipping"), "teal") : null),
			el("div", { style: { fontSize: "14px", color: "var(--ink-2)" } }, [a.address_line1, a.address_line2, [a.city, a.state, a.pincode].filter(Boolean).join(", "), a.country].filter(Boolean).map((x) => el("div", { text: x }))),
			a.phone || a.email_id ? el("div", { class: "cp-sub", text: [a.phone, a.email_id].filter(Boolean).join(", ") }) : null);
	}
	P.profile = async function (ctx) {
		ctx.setTitle(__("Company Profile"));
		const p = await loadProfile();
		if (!ctx.isCurrent()) return;
		const blocks = p.customers.map((c) => el("div", { class: "cp-stack" },
			cp.card(c.customer_name, cp.facts([[__("Company name"), c.customer_name], [__("Customer ID"), c.name], [__("Customer type"), c.customer_type ? __(c.customer_type) : null],
				[__("Customer group"), c.customer_group], [__("Tax ID / VAT number"), c.tax_id], [__("Primary contact"), c.primary_contact],
				[__("Email"), c.email ? el("a", { href: "mailto:" + c.email, text: c.email }) : null], [__("Phone"), c.mobile ? el("a", { href: "tel:" + c.mobile, text: c.mobile }) : null], [__("Website"), c.website]])),
			cp.card(__("Addresses"), c.addresses.length ? el("div", { class: "cp-grid cp-grid--2" }, c.addresses.map(address)) : el("p", { class: "cp-sub", style: { margin: 0 }, text: __("No address on file. Ask the rental team to add your billing address.") })),
			cp.card(__("Authorised sites and projects"), c.sites.length ? el("div", { class: "cp-tablewrap" }, el("table", { class: "cp-table" },
				el("thead", {}, el("tr", {}, [__("Site"), __("Location"), __("Project"), __("Site contact")].map((h) => el("th", { text: h })))),
				el("tbody", {}, c.sites.map((s) => el("tr", {}, el("td", {}, el("b", { text: s.site_name || s.name })), el("td", { text: s.location || "" }), el("td", { text: s.project || "" }),
					el("td", {}, s.site_contact || "", s.contact_phone ? el("span", { class: "cp-sub" }, el("a", { href: "tel:" + s.contact_phone, text: s.contact_phone })) : null))))))
				: el("p", { class: "cp-sub", style: { margin: "16px 18px" }, text: __("No sites yet.") }), { flush: true })));
		ctx.main.replaceChildren(cp.pageHead(__("Company Profile"), __("Your company details as we hold them. Contact the rental team to change company, tax or address details."),
			[cp.btn(__("Edit my contact details"), null, { href: cp.href("contacts"), icon: "pencil" })]), el("div", { class: "cp-stack" }, blocks));
	};

	P.contacts = async function (ctx) {
		ctx.setTitle(__("Contacts"));
		const p = await loadProfile();
		if (!ctx.isCurrent()) return;
		const me = p.me;
		let mine = null;
		if (me) {
			const inp = (k, label, type) => el("label", { class: "cp-label" }, label, el("input", { class: "cp-input", name: k, type: type || "text", value: me[k] || "", disabled: !p.can_edit_contact }));
			const form = el("div", { class: "cp-form" }, inp("first_name", __("First name")), inp("last_name", __("Last name")), inp("designation", __("Job title")),
				el("label", { class: "cp-label" }, __("Email"), el("input", { class: "cp-input", value: me.email || "", disabled: true }), el("small", { text: __("Your login. The rental team can change it.") })),
				inp("phone", __("Phone"), "tel"), inp("mobile_no", __("Mobile"), "tel"));
			mine = cp.card(__("My contact details"), el("div", {}, form, p.can_edit_contact ? el("div", { style: { display: "flex", justifyContent: "flex-end", marginTop: "16px" } }, cp.btn(__("Save changes"), async () => {
				const vals = {};
				form.querySelectorAll("input[name]").forEach((i) => (vals[i.name] = i.value));
				await cp.api("update_my_contact", vals, { post: true });
				cp.toast(__("Your contact details are saved."));
			}, { primary: true, icon: "check" })) : null));
		}
		const all = p.customers.flatMap((c) => c.contacts.map((k) => Object.assign({ company: c.customer_name }, k)));
		const list = cp.card(__("Company contacts"), all.length ? el("div", { class: "cp-tablewrap" }, el("table", { class: "cp-table" },
			el("thead", {}, el("tr", {}, [__("Name"), __("Job title"), __("Email"), __("Phone"), __("Portal access")].map((h) => el("th", { text: h })))),
			el("tbody", {}, all.map((k) => el("tr", {}, el("td", {}, el("b", { text: k.full_name || k.name }), k.is_primary_contact ? " " : null, k.is_primary_contact ? cp.badge(__("Primary"), "blue") : null,
				p.customers.length > 1 ? el("span", { class: "cp-sub", text: k.company }) : null),
				el("td", { text: k.designation || "" }), el("td", {}, k.email_id ? el("a", { href: "mailto:" + k.email_id, text: k.email_id }) : ""),
				el("td", { text: [k.phone, k.mobile_no].filter(Boolean).join(", ") }), el("td", {}, k.portal_user ? cp.badge(__("Yes"), "good") : cp.badge(__("No"), "plain")))))))
			: el("p", { class: "cp-sub", style: { margin: "16px 18px" }, text: __("No contacts on file.") }), { flush: true, sub: __("To add or remove people with portal access, contact the rental team.") });
		ctx.main.replaceChildren(cp.pageHead(__("Contacts"), __("The people at your company we deal with.")), el("div", { class: "cp-stack" }, mine, list));
	};

	// ================================================================== settings
	P.settings = async function (ctx) {
		ctx.setTitle(__("Settings"));
		const s = await cp.api("get_settings", { customer: null });
		if (!ctx.isCurrent()) return;
		const toggle = el("input", { type: "checkbox", checked: !!s.email_notifications, "aria-describedby": "cp-set-mail" });
		toggle.addEventListener("change", async () => {
			try {
				await cp.api("save_settings", { email_notifications: toggle.checked ? 1 : 0, customer: null }, { post: true });
				cp.toast(toggle.checked ? __("You will get notifications by e-mail too.") : __("Notifications will only show here."));
			} catch (e) {
				toggle.checked = !toggle.checked;
				cp.toast(e.message, "bad");
			}
		});
		ctx.main.replaceChildren(cp.pageHead(__("Settings"), __("Your login and how we notify you.")), el("div", { class: "cp-stack", style: { maxWidth: "760px" } },
			cp.card(__("Notifications"), el("label", { class: "cp-switch" }, toggle, el("span", {}, el("b", { text: __("E-mail me my notifications") }),
				el("span", { class: "cp-sub", id: "cp-set-mail", text: __("Order, delivery, invoice and request updates are always shown in the portal. Switch on to receive them at {0} too.", [s.email]) })))),
			cp.card(__("Login and security"), el("div", {}, cp.facts([[__("Login e-mail"), s.email]]), el("div", { style: { marginTop: "14px", display: "flex", gap: "8px", flexWrap: "wrap" } },
				el("a", { class: "cp-btn", href: "/update-password" }, icon("key-round", "cp-i--sm"), __("Change password")),
				el("a", { class: "cp-btn cp-btn--danger", href: "/api/method/logout?redirect-to=/login" }, icon("log-out", "cp-i--sm"), __("Log out")))))));
	};
})();
