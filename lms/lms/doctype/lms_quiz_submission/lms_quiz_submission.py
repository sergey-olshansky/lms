# Copyright (c) 2021, FOSS United and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import make_notification_logs
from frappe.model.document import Document
from frappe.utils import cint

from lms.lms.html_sanitizer import sanitize_rich_text


class LMSQuizSubmission(Document):
	def validate(self):
		self.validate_if_max_attempts_exceeded()
		self.sanitize_result_html()
		self.validate_marks()
		self.validate_grading_flags()
		self.set_percentage()

	def sanitize_result_html(self):
		"""A child doctype fires no doc_events, so the parent cleans its rows. Both fields
		render outside the SPA (reports, exports, the jinja portal)."""
		for row in self.result:
			row.answer = sanitize_rich_text(row.answer)
			row.question = sanitize_rich_text(row.question)

	def validate_grading_flags(self):
		"""The explicit per-row grading state (task #35, C01).

		``marks`` is an Int field: Frappe's serialization turns a missing value
		into a stored 0, so an answer nobody judged and a final zero are
		NUMERICALLY IDENTICAL in the database. The ``graded`` check is the only
		signal that separates them, so it is normalized server-side on every
		save: objective rows always carry a machine verdict; the member's own
		saves can never finalize an open answer -- except an answer the SERVER
		itself carried in from an earlier graded attempt (D02), which is named
		in doc flags a client can never write, not in the payload; and only a
		user who may review this quiz may record a manual verdict. A grader
		clearing their input un-finalizes the row again (the grading page writes
		graded=1 for every value typed, including 0, and 0 for a cleared one)."""
		actor = frappe.session.user
		grader_save = bool(actor) and actor not in ("Guest",) and actor != self.member
		server_carried = self.flags.get("carried_graded_questions") or frozenset()
		requested_manual_verdict = False
		for row in self.result:
			if row.question_type != "Open Ended":
				row.graded = 1
				continue
			if not grader_save:
				# Only a server-side carry keeps its recorded verdict through the
				# member's own save; a client-sent graded=1 is rewritten to 0.
				row.graded = 1 if row.question_name in server_carried else 0
			elif cint(row.graded):
				requested_manual_verdict = True
		if requested_manual_verdict and not _may_grade_submission(self.quiz):
			frappe.throw(
				_("You are not authorized to grade this submission."),
				frappe.PermissionError,
			)

	def on_update(self):
		self.notify_member()

	def validate_if_max_attempts_exceeded(self):
		# Attempt limits price NEW submissions (D01b): grading an already saved
		# attempt -- the teacher's verdict, an admin correction -- consumes
		# nothing, while a member's next try is always a fresh document, so the
		# count below still gates every extra submission.
		if not self.is_new():
			return
		max_attempts = frappe.db.get_value("LMS Quiz", self.quiz, ["max_attempts"])
		if max_attempts == 0:
			return

		current_user_submission_count = frappe.db.count(
			self.doctype, filters={"quiz": self.quiz, "member": self.member}
		)
		if current_user_submission_count >= max_attempts:
			frappe.throw(
				_("You have exceeded the maximum number of attempts ({0}) for this quiz").format(
					max_attempts
				),
				MaximumAttemptsExceededError,
			)

	def validate_marks(self):
		self.score = 0
		for row in self.result:
			if cint(row.marks) > cint(row.marks_out_of):
				frappe.throw(
					_(
						"Marks for question number {0} cannot be greater than the marks allotted for that question."
					).format(row.idx)
				)
			else:
				self.score += cint(row.marks)

	def set_percentage(self):
		if self.score and self.score_out_of:
			# Floored at zero, or negative marking throws the whole submission away.
			self.percentage = max(0, (self.score / self.score_out_of) * 100)

	def notify_member(self):
		if self.score != 0 and self.has_value_changed("score"):
			notification = frappe._dict(
				{
					"subject": _("You have got a score of {0} for the quiz {1}").format(
						(frappe.bold(self.score)), frappe.bold(self.quiz_title)
					),
					"email_content": _(
						"There has been an update on your submission. You have got a score of {0} for the quiz {1}"
					).format(frappe.bold(self.score), frappe.bold(self.quiz_title)),
					"document_type": self.doctype,
					"document_name": self.name,
					"for_user": self.member,
					"from_user": frappe.session.user,
					"type": "Alert",
					"link": "",
				}
			)

			make_notification_logs(notification, [self.member])


class MaximumAttemptsExceededError(frappe.DuplicateEntryError):
	pass


def _may_grade_submission(quiz: str) -> bool:
	"""Whether the session user may record manual verdicts on this quiz's
	submissions -- the quiz review right, reused from the quiz doctype so the
	grading flag can never be self-awarded or forged by an outsider."""
	from lms.lms.doctype.lms_quiz.lms_quiz import _can_review_submission

	return _can_review_submission(quiz)


@frappe.whitelist()
def save_submission_grades(submission: str, grades: list | None = None) -> dict:
	"""The narrow grading action the review page uses (task #35, D01).

	Plain Course Creators hold no write on this doctype -- the standard
	``frappe.client.set_value`` transport of ``createDocumentResource.save``
	answers them with PermissionError -- so the UI grades through THIS endpoint
	instead. It re-checks the authority itself: the session user must be a
	reviewer of THIS quiz (its author or an instructor of a course/batch that
	places it) and must not be the member. Only ``marks`` and ``graded`` of
	OPEN-ENDED rows of THIS submission are writable: member, quiz, owner,
	objective verdicts, answers and row membership are not. The save still runs
	the controller's validate (marks bounds, flag normalization, attempt limit
	exempt for updates) and the homework recompute rides its on_update hook."""
	if not isinstance(submission, str) or not submission:
		frappe.throw(_("Invalid quiz submission."), frappe.ValidationError)
	if not isinstance(grades, list):
		frappe.throw(_("Invalid grades payload."), frappe.ValidationError)

	doc = frappe.get_doc("LMS Quiz Submission", submission)
	if frappe.session.user in (None, "Guest") or frappe.session.user == doc.member:
		frappe.throw(
			_("You are not authorized to grade this submission."), frappe.PermissionError
		)
	if not _may_grade_submission(doc.quiz):
		frappe.throw(
			_("You are not authorized to grade this submission."), frappe.PermissionError
		)

	rows_by_name = {row.name: row for row in doc.result}
	allowed_fields = {"marks", "graded"}
	for grade in grades:
		if not isinstance(grade, dict):
			frappe.throw(_("Invalid grades payload."), frappe.ValidationError)
		row = rows_by_name.get(grade.get("name"))
		if row is None:
			frappe.throw(_("This submission does not have the question being graded."), frappe.ValidationError)
		if row.question_type != "Open Ended":
			frappe.throw(
				_("Only open-ended answers can be graded by hand."), frappe.ValidationError
			)
		unknown = set(grade) - allowed_fields - {"name"}
		if unknown:
			frappe.throw(
				_("Fields cannot be changed through grading: {0}").format(
					frappe.bold(", ".join(sorted(unknown)))
				),
				frappe.ValidationError,
			)
		if "marks" in grade:
			row.marks = grade["marks"]
		if "graded" in grade:
			row.graded = 1 if cint(grade["graded"]) else 0

	doc.save(ignore_permissions=True)
	return {"saved": True}
