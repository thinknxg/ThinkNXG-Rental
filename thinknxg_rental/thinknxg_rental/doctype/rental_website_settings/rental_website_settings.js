// Rental Website Settings: open the site, and load a template's home page sections.
frappe.ui.form.on("Rental Website Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Open website"), () => window.open("/hire", "_blank"));
		frm.add_custom_button(__("Load template sections"), () => {
			frappe.confirm(
				__("Replace the home page sections with the {0} set? Text you wrote for a section type that is kept stays as it is.", [frm.doc.template || "Industrial Corporate"]),
				() => frm.call("load_template_sections").then((r) => {
					frappe.show_alert({ message: __("{0} sections loaded", [r.message]), indicator: "green" });
					frm.reload_doc();
				})
			);
		}, __("Design"));
		frm.set_intro(frm.doc.enabled ? "" : __("The website is switched off: only website managers can see it, with a preview banner."), "orange");
	},
	template(frm) {
		if (!frm.is_new()) frappe.show_alert({ message: __("Save, then use Design > Load template sections to apply the template's section order."), indicator: "blue" }, 7);
	},
});
