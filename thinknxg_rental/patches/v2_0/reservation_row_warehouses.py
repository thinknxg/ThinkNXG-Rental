"""v2.0.2: each reservation row now has its own source warehouse. Rows written by earlier versions
take the warehouse of their reservation, which is where they were reserved."""
import frappe


def execute():
	frappe.db.sql(
		"""update `tabRental Material Reservation Item` ri
		inner join `tabRental Material Reservation` r on r.name = ri.parent
		set ri.source_warehouse = r.source_warehouse
		where ifnull(ri.source_warehouse, '') = ''"""
	)
