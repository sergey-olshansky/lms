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
		self.set_review_status()
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

	def set_review_status(self):
		"""Card #47: the attempt's place in the two-pass review.

		An attempt with any open-answer question is ``pending_review`` the moment
		it is sat -- its automatic score is preliminary until the teacher finishes
		the second pass. An attempt with none (the classic auto-checked quiz, and
		any legacy shape) is ``final`` immediately: the automation has checked
		everything it ever will, which is exactly the owner's decision for quizzes
		without open answers. The status is written by the server on the member's
		own create; afterwards only ``finalize_submission_review`` moves it, so
		neither the member nor the flag serialization can flip it.
		"""
		if self.review_status == "final":
			return
		if self.is_new() or not self.review_status:
			self.review_status = (
				"pending_review"
				if any(row.question_type == "Open Ended" for row in self.result)
				else "final"
			)

	def on_update(self):
		self.notify_member()
		self.save_lesson_progress_after_grading()

	def save_lesson_progress_after_grading(self):
		"""Card #47: a two-part attempt can only clear the passing threshold after
		the teacher's marks land, so a grading save must retry the lesson write
		the submit path already made. Skipped for the member's own create (the
		submit path just made the same call on the same numbers) and for saves
		that changed no score. The helper re-checks the threshold, the course and
		the locked lesson itself."""
		if self.is_new() or not self.has_value_changed("score"):
			return
		if not self.quiz:
			return
		from lms.lms.doctype.lms_quiz.lms_quiz import save_progress_after_quiz

		quiz_details = frappe.db.get_value(
			"LMS Quiz",
			self.quiz,
			["name", "title", "total_marks", "passing_percentage", "lesson", "course"],
			as_dict=True,
		)
		if not quiz_details:
			return
		save_progress_after_quiz(quiz_details, self.percentage or 0)

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

	def notify_member_review_finalized(self):
		"""Card #47: the learner's explicit "your teacher has checked this" signal.

		Fires once, from finalize_submission_review -- unlike the score-change
		note above, which fires on every grading keystroke batch that moved the
		score -- so "the review is finished" never reads as just another mark
		update. The final figures are quoted from the doc the controller just
		recomputed."""
		notification = frappe._dict(
			{
				"subject": _("Your teacher has finished reviewing the quiz {0}").format(
					frappe.bold(self.quiz_title)
				),
				"email_content": _(
					"The review of your submission for the quiz {0} is complete. Your final score is {1} out of {2} ({3}%)."
				).format(
					frappe.bold(self.quiz_title),
					frappe.bold(self.score),
					self.score_out_of,
					self.percentage,
				),
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
	"""The narrow grading action the review page uses (task #35, D01; card #47).

	Plain Course Creators hold no write on this doctype -- the standard
	``frappe.client.set_value`` transport of ``createDocumentResource.save``
	answers them with PermissionError -- so the UI grades through THIS endpoint
	instead. It re-checks the authority itself: the session user must be a
	reviewer of THIS quiz (its author or an instructor of a course/batch that
	places it) and must not be the member. Only ``marks``, ``graded`` and
	``is_correct`` of rows of THIS submission are writable: member, quiz, owner,
	answers and row membership are not. The save still runs the controller's
	validate (marks bounds, flag normalization, attempt limit exempt for
	updates) and the homework recompute rides its on_update hook.

	Card #47 second pass: the teacher may grade ANY row, the auto-checked part
	included -- touching an objective row's marks or verdict stamps it
	``teacher_override`` so "the teacher changed the automation here" stays
	distinguishable from "the preliminary verdict stood". Untouched objective
	rows keep their automatic marks untouched.
	"""
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
	allowed_fields = {"marks", "graded", "is_correct"}
	for grade in grades:
		if not isinstance(grade, dict):
			frappe.throw(_("Invalid grades payload."), frappe.ValidationError)
		row = rows_by_name.get(grade.get("name"))
		if row is None:
			frappe.throw(_("This submission does not have the question being graded."), frappe.ValidationError)
		unknown = set(grade) - allowed_fields - {"name"}
		if unknown:
			frappe.throw(
				_("Fields cannot be changed through grading: {0}").format(
					frappe.bold(", ".join(sorted(unknown)))
				),
				frappe.ValidationError,
			)
		touched = False
		if "marks" in grade:
			row.marks = grade["marks"]
			touched = True
		if "is_correct" in grade:
			row.is_correct = 1 if cint(grade["is_correct"]) else 0
			touched = True
		if "graded" in grade:
			row.graded = 1 if cint(grade["graded"]) else 0
		# A hand-set mark or verdict on a machine-graded row IS the override the
		# owner asked to stay distinguishable (card #47); open answers are graded
		# by hand by design, so their normal grading is not an override.
		if touched and row.question_type != "Open Ended":
			row.teacher_override = 1

	doc.save(ignore_permissions=True)
	return {"saved": True}


@frappe.whitelist()
def finalize_submission_review(submission: str) -> dict:
	"""Finish the teacher's second pass (card #47): the attempt becomes ``final``.

	Only a reviewer of THIS quiz (never the member who sat it) may finish the
	review. Every open-answer row must already carry an explicit verdict -- a
	recorded 0 included -- because a finalized attempt promises the learner that
	nothing is still waiting for a human. Objective rows are not required to be
	touched: the owner's rule is that untouched automation keeps its preliminary
	marks. Idempotent for an already-final attempt. The score/percentage the
	controller recomputes on save already include the open part's marks in both
	numerator and denominator, which is the aggregation the owner chose.
	"""
	if not isinstance(submission, str) or not submission:
		frappe.throw(_("Invalid quiz submission."), frappe.ValidationError)

	doc = frappe.get_doc("LMS Quiz Submission", submission)
	if frappe.session.user in (None, "Guest") or frappe.session.user == doc.member:
		frappe.throw(
			_("You are not authorized to review this submission."), frappe.PermissionError
		)
	if not _may_grade_submission(doc.quiz):
		frappe.throw(
			_("You are not authorized to review this submission."), frappe.PermissionError
		)

	if doc.review_status == "final":
		return {"finalized": True, "review_status": "final"}

	ungraded = [
		row.idx
		for row in doc.result
		if row.question_type == "Open Ended" and not cint(row.graded)
	]
	if ungraded:
		frappe.throw(
			_("Grade every open-answer question before finishing the review (question numbers: {0}). A recorded zero is allowed.").format(
				frappe.bold(", ".join(str(idx) for idx in ungraded))
			),
			frappe.ValidationError,
		)

	doc.review_status = "final"
	doc.reviewed_by = frappe.session.user
	doc.reviewed_on = frappe.utils.now_datetime()
	doc.save(ignore_permissions=True)
	doc.notify_member_review_finalized()
	return {"finalized": True, "review_status": "final"}
