# Copyright (c) 2021, FOSS United and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class LessonReference(Document):
	"""One child row of a section's content table.

	A row references exactly one of a lesson, a nested section or an image
	folder, never more than one and never none: the shared table is what keeps
	mixed children in one manual order, so a row that points at nothing would
	silently disturb that order, and a row pointing at several kinds at once
	would be rendered as each of them.
	"""

	def validate(self):
		if sum(1 for value in (self.lesson, self.section, self.folder) if value) != 1:
			frappe.throw(
				_("A course child row must reference exactly one of a lesson, a section or a folder."),
				frappe.ValidationError,
			)
