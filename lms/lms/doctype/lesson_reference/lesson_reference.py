# Copyright (c) 2021, FOSS United and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class LessonReference(Document):
	"""One child row of a section's content table.

	A row references either a lesson or a nested section, never both and never
	neither: the shared table is what keeps mixed children in one manual order,
	so a row that points at nothing would silently disturb that order.
	"""

	def validate(self):
		if bool(self.lesson) == bool(self.section):
			frappe.throw(
				_("A course child row must reference either a lesson or a section."),
				frappe.ValidationError,
			)
