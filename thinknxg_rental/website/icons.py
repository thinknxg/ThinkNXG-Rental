"""Icons for the public website, inlined as a small SVG sprite.

Frappe's full lucide sprite is about 750 KB; a public page should not download that. The website
inlines only the symbols it uses: every icon("name") written in its templates and in rw.js (found by
scanning those files once), plus the icons chosen on cards in Rental Website Settings."""
import os
import re

import frappe

_SYMBOLS = None
_USED = None
# icons passed to icon() through a variable, which the scan below cannot see
DYNAMIC = {"layout-grid", "list", "x", "menu"}
_ICON_CALL = re.compile(r"""icon\(\s*["']([a-z0-9-]+)["']""")


def _symbols():
	global _SYMBOLS
	if _SYMBOLS is None:
		path = frappe.get_app_path("frappe", "public", "icons", "lucide.svg")
		try:
			with open(path, encoding="utf-8") as f:
				text = f.read()
		except OSError:
			text = ""
		_SYMBOLS = {m.group(1): m.group(0) for m in re.finditer(r'<symbol[^>]*\sid="icon-([a-z0-9-]+)"[^>]*>.*?</symbol>', text, re.S)}
	return _SYMBOLS


def used_in_code():
	"""Icon names written literally in the website templates and script."""
	global _USED
	if _USED is None:
		names = set()
		roots = [frappe.get_app_path("thinknxg_rental", "templates", "rental_website"),
			frappe.get_app_path("thinknxg_rental", "public", "rental_website")]
		for root in roots:
			for folder, _dirs, files in os.walk(root):
				for name in files:
					if name.endswith((".html", ".js")):
						with open(os.path.join(folder, name), encoding="utf-8") as f:
							names.update(_ICON_CALL.findall(f.read()))
		_USED = names | DYNAMIC
	return _USED


def exists(name):
	return bool(name) and name in _symbols()


def sprite(extra=()):
	"""<svg> with the symbols the page can use, hidden."""
	symbols = _symbols()
	names = sorted((used_in_code() | {n for n in extra if n}) & set(symbols))
	body = "".join(re.sub(r'\sxmlns="[^"]*"', "", symbols[n]) for n in names)
	return f'<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">{body}</svg>'
