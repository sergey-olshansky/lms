# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class LMSHomeworkAttachment(Document):
	def validate(self):
		# The row is the student's own claim on one assignment; the API layer
		# (homework_attachments) owns the authority checks and the quota -- the
		# controller only guards the invariant nobody may violate directly.
		if self.is_new() and not self.uploaded_by:
			self.uploaded_by = frappe.session.user
		if not self.uploaded_at:
			self.uploaded_at = frappe.utils.now_datetime()
		assignment = frappe.db.get_value(
			"LMS Homework Assignment", self.assignment, ["student"], as_dict=True
		)
		if assignment and self.student != assignment.student:
			frappe.throw(
				_("The attachment must belong to the assignment's own student."),
				frappe.ValidationError,
			)

	def on_trash(self):
		# Deleting the row detaches the file's link but never touches another
		# student's file: the File document itself is removed by the API layer
		# that owns the delete action, not here.
		pass
