// thinkNXG Rental admin portal: the few actions that run without leaving the page.
(function () {
	const box = document.getElementById("ra-msg");
	const say = (text, tone) => {
		if (!box) return;
		box.textContent = text;
		box.dataset.tone = tone || "";
		box.hidden = false;
	};
	const post = (method, args) =>
		new Promise((resolve, reject) =>
			frappe.call({ method, args, type: "POST", callback: (r) => resolve(r.message), error: reject })
		);
	const bill = (contract) =>
		post("thinknxg_rental.services.billing.generate_billing", { rental_contract: contract, only_complete: 1 }).then((made) => (made || []).length);

	document.querySelectorAll("[data-bill]").forEach((button) =>
		button.addEventListener("click", () => {
			button.disabled = true;
			bill(button.dataset.bill)
				.then((n) => {
					say(n ? __("{0}: {1} billing schedule(s) created.", [button.dataset.bill, n]) : __("{0}: nothing to bill yet.", [button.dataset.bill]));
					setTimeout(() => window.location.reload(), 1200);
				})
				.catch(() => (button.disabled = false));
		})
	);

	const all = document.getElementById("ra-bill-all");
	if (all) {
		all.addEventListener("click", async () => {
			const contracts = [...document.querySelectorAll("[data-bill]")].map((b) => b.dataset.bill);
			if (!window.confirm(__("Create billing schedules and invoices for {0} contracts?", [contracts.length]))) return;
			all.disabled = true;
			let done = 0, failed = [];
			for (const contract of contracts) {
				say(__("Billing {0} of {1}", [done + failed.length + 1, contracts.length]));
				try {
					await bill(contract);
					done += 1;
				} catch (e) {
					failed.push(contract);
				}
			}
			say(
				failed.length ? __("Billed {0}. Could not bill: {1}", [done, failed.join(", ")]) : __("Billed {0} contracts.", [done]),
				failed.length ? "stop" : ""
			);
			setTimeout(() => window.location.reload(), failed.length ? 4000 : 1200);
		});
	}

	document.querySelectorAll("[data-start]").forEach((button) =>
		button.addEventListener("click", () => {
			button.disabled = true;
			post("thinknxg_rental.portal.admin.start_request", { name: button.dataset.start })
				.then(() => window.location.reload())
				.catch(() => (button.disabled = false));
		})
	);
})();
