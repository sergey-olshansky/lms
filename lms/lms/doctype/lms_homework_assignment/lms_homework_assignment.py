# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""One homework assignment issued to one student (task #35 spec, section 9.3).

The template and the assignment are deliberately separate records: re-issuing a
compilation and independent progress would both break if a template row carried a
shared status or student. The requirement rows here are a frozen snapshot -- later
template edits must not rewrite an issued composition.

Everything a student or teacher does to this document goes through the homework
service's named actions, which verify the actor and the transition themselves and
then save with ``ignore_permissions`` (LMS Student holds no write DocPerm by
design). Any other writer -- Desk, raw REST -- is refused: an arbitrary status
write must not bypass transition checks, and the managed snapshot/progress fields
must not move outside the audited actions (spec 7, 9.1).
"""

import frappe
from frappe import _
from frappe.model.document import Document

# Statuses as stored in the Select field, in board order.
HOMEWORK_STATUSES = ["To Do", "In Progress", "Review", "Done"]

# Requirement statuses that count as confirmed completion.
COMPLETED_REQUIREMENT_STATUSES = {"Completed", "Completed Earlier"}

# Fields that only the homework service's audited actions may move. The snapshot
# triple included: issued cards keep the composition they were issued with.
MANAGED_FIELDS = (
	"title",
	"days",
	"details",
	"status",
	"due_at",
	"first_opened_at",
	"submitted_for_review_at",
	"reviewed_by",
	"reviewed_at",
	"needs_revision",
	"last_revision_comment",
	"cancelled",
	"cancelled_by",
	"cancelled_at",
	"cancellation_reason",
	"total_requirements",
	"completed_requirements",
	"lessons_total",
	"quizzes_total",
	"quizzes_completed",
)


class LMSHomeworkAssignment(Document):
	def validate(self):
		# The creation gate first: a Desk/REST insert is refused as such before
		# any field rule turns the refusal into a confusing shape.
		self.validate_managed_write()
		self.validate_status_write()
		self.validate_no_empty_requirements()

	def validate_status_write(self):
		"""Status moves only through the homework service's named actions, which
		re-read the row and check the transition."""
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
		"""An empty assignment is forbidden: no "0 of 0 = done" (spec section 6.4)."""
		if not self.is_new():
			return
		assignable = [row for row in self.requirements if row.status != "Unavailable"]
		if not assignable:
			frappe.throw(_("A homework assignment must contain at least one requirement."))

	def validate_managed_write(self):
		"""The non-service door stays closed: creation, and every managed field
		and requirement row, only move through the validated actions (R02)."""
		if self.flags.homework_service:
			return
		if self.is_new():
			frappe.throw(
				_("Homework assignments are created by assigning a homework, not directly."),
				frappe.PermissionError,
			)
		before = self.get_doc_before_save()
		if not before:
			return
		for field in MANAGED_FIELDS:
			if (self.get(field) or None) != (before.get(field) or None):
				frappe.throw(
					_("{0} changes only through homework actions.").format(_(frappe.unscrub(field))),
					frappe.PermissionError,
				)
		if self._requirements_differ(before):
			frappe.throw(
				_("The requirement rows change only through homework actions."),
				frappe.PermissionError,
			)

	def _requirements_differ(self, before) -> bool:
		def fingerprint(rows):
			return sorted(
				(
					row.requirement_type,
					row.lesson or "",
					row.quiz or "",
					row.reference_assignment or "",
					row.status,
				)
				for row in rows
			)

		return fingerprint(self.requirements) != fingerprint(before.requirements or [])

	def on_doctype_update(self):
		frappe.db.add_index(self.doctype, ["student", "status", "cancelled"], "homework_student_status_idx")
		frappe.db.add_index(self.doctype, ["homework", "student"], "homework_template_student_idx")
		frappe.db.add_index(self.doctype, ["teacher", "cancelled"], "homework_teacher_idx")
