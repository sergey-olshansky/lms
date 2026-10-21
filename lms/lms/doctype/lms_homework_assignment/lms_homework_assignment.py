# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""One homework assignment issued to one student (task #35 spec, section 9.3).

The template and the assignment are deliberately separate records: re-issuing a
compilation and independent progress would both break if a template row carried a
shared status or student. The requirement rows here are a frozen snapshot -- later
template edits must not rewrite an issued composition.
"""

import frappe
from frappe import _
from frappe.model.document import Document

# Statuses as stored in the Select field, in board order.
HOMEWORK_STATUSES = ["To Do", "In Progress", "Review", "Done"]

# Requirement statuses that count as confirmed completion.
COMPLETED_REQUIREMENT_STATUSES = {"Completed", "Completed Earlier"}


class LMSHomeworkAssignment(Document):
	def validate(self):
		self.validate_status_write()
		self.validate_no_empty_requirements()

	def validate_status_write(self):
		"""Status moves only through the homework service's named actions, which
		re-read the row and check the transition. Any other writer -- a desk save,
		a raw REST write -- is refused (spec section 7: an arbitrary status write
		must not bypass transition checks)."""
		if self.flags.homework_service:
			return
		if self.is_new() and self.status == "To Do":
			return
		if self.has_value_changed("status"):
			frappe.throw(
				_("Status can only change through homework actions, not by editing the document."),
				frappe.PermissionError,
			)

	def validate_no_empty_requirements(self):
		"""An empty assignment is forbidden: no "0 of 0 = done" (spec section 6.4).
		The service guarantees this at creation; this is the belt-and-braces gate."""
		if not self.is_new():
			return
		assignable = [
			row
			for row in self.requirements
			if row.status in COMPLETED_REQUIREMENT_STATUSES
			or row.status in {"Pending", "Awaiting Grading"}
		]
		if not assignable:
			frappe.throw(_("A homework assignment must contain at least one requirement."))

	def on_doctype_update(self):
		frappe.db.add_index(
			self.doctype, ["student", "status", "cancelled"], "homework_student_status_idx"
		)
		frappe.db.add_index(self.doctype, ["homework", "student"], "homework_template_student_idx")
		frappe.db.add_index(self.doctype, ["teacher", "cancelled"], "homework_teacher_idx")
