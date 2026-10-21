# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""The homework assignment lifecycle end to end (task #35 spec 4, 6, 7):
issue with snapshot and idempotency, prior credit, confirmed openings, quiz
evidence and pending grading, automatic Review, teacher decisions, deadlines,
revocation, and the authority checks along the way. Matrix A10-A32 (server)."""

import json
from datetime import datetime

import frappe
from frappe.tests import IntegrationTestCase

from lms.lms import homework_api, homework_service, homework_sources
from lms.lms.doctype.lms_quiz.lms_quiz import submit_quiz
from lms.lms.test_helpers import BaseTestUtils

QUIZ_BLOCK = '{{"blocks": [{{"type": "quiz", "data": {{"quiz": "{0}"}}}}]}}'
# The editorjs block a lesson's written-assignment placement is rebuilt from.
ASSIGNMENT_BLOCK = '{{"blocks": [{{"type": "assignment", "data": {{"assignment": "{0}"}}}}]}}'


class TestHomeworkLifecycle(BaseTestUtils, IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.teacher = self._create_user(
			"hw-teacher@example.com", "Hana", "Teacher", ["Course Creator", "LMS Student"]
		)
		self.student = self._create_user("hw-student@example.com", "Ann", "Student", ["LMS Student"])
		self.student2 = self._create_user("hw-student2@example.com", "Ben", "Second", ["LMS Student"])

		frappe.set_user(self.teacher.email)
		self.course = self._create_course(title="HW Lifecycle Course", instructor=self.teacher.email)
		self.questions = self._create_quiz_questions()
		self.quiz = self._create_quiz(self.questions, title="HW Lifecycle Quiz")
		self.lesson_plain = self._lesson("Plain lesson")
		self.lesson_quiz = self._lesson("Quiz lesson", QUIZ_BLOCK.format(self.quiz.name))

	def _lesson(self, title, content=None):
		chapter = self._create_chapter(f"Chapter {title}", self.course.name)
		self._create_chapter_reference(self.course.name, chapter.name)
		lesson = self._create_lesson(title, chapter.name, self.course.name, content)
		self._create_lesson_reference(chapter.name, lesson.name)
		return lesson

	def _template(self, title, lessons, quizzes=(), assignments=()):
		items = [
			{
				"source_type": "Lesson",
				"name": lesson.name,
				"course": self.course.name,
				"title": lesson.title,
				"chapter": "",
				"path": f"Course / {lesson.title}",
			}
			for lesson in lessons
		]
		items += [
			{
				"source_type": "Quiz",
				"name": quiz,
				"course": self.course.name,
				"title": quiz,
				"chapter": "",
				"path": f"Course / {quiz}",
			}
			for quiz in quizzes
		]
		items += [
			{
				"source_type": "Assignment",
				"name": assignment,
				"course": self.course.name,
				"title": assignment,
				"chapter": "",
				"path": f"Course / {assignment}",
			}
			for assignment in assignments
		]
		result = homework_api.save_homework(title=title, days=3, items=items)
		return result["name"]

	def _enroll(self, student):
		self._create_enrollment(student.email, self.course.name)

	def _assign(self, template, student, key, days=None, force=False):
		frappe.set_user(self.teacher.email)
		return homework_api.assign_homework(
			homework=template,
			student=student.email,
			days=days,
			idempotency_key=key,
			force=force,
		)

	def _requirements(self, name):
		doc = frappe.get_doc("LMS Homework Assignment", name)
		return doc.requirements

	def _statuses(self, name):
		return {
			# An embedded quiz row carries BOTH its lesson and its quiz; the quiz is
			# the material the row is about, so it wins the key.
			(row.requirement_type, row.quiz or row.lesson or row.reference_assignment): row.status
			for row in self._requirements(name)
		}

	def _delete_lesson(self, lesson):
		"""Delete a lesson on a stack that refuses deleting a linked document:
		the chapter's Lesson Reference row goes first, then the lesson itself.
		An administrator act -- the deletion is the fixture, not the subject."""
		frappe.set_user("Administrator")
		for ref in frappe.get_all("Lesson Reference", filters={"lesson": lesson.name}, pluck="name"):
			frappe.delete_doc("Lesson Reference", ref)
		for progress in frappe.get_all("LMS Course Progress", filters={"lesson": lesson.name}, pluck="name"):
			frappe.delete_doc("LMS Course Progress", progress)
		frappe.delete_doc("Course Lesson", lesson.name)

	def _submit(self, student, correct=True):
		frappe.set_user(student.email)
		results = []
		for question in self.questions:
			answer = [question.option_1] if correct else [question.option_2]
			results.append({"question_name": question.name, "answer": answer})
		submit_quiz(self.quiz.name, json.dumps(results))
		frappe.set_user(self.teacher.email)

	# --- Issue: validation, idempotency, snapshot (A05, A10, A11, A12, A13) ---

	def test_empty_composition_refused(self):
		self._enroll(self.student)
		template = self._template("Empty", [])
		with self.assertRaises(frappe.ValidationError):
			self._assign(template, self.student, "key-empty")

	def test_unenrolled_student_blocked_with_reason(self):
		template = self._template("Blocked", [self.lesson_plain])
		frappe.set_user(self.teacher.email)
		precheck = homework_api.precheck_assignment(template, self.student.email, 3)
		self.assertFalse(precheck["ok"])
		self.assertTrue(any("not enrolled" in reason for reason in precheck["reasons"]))
		# The dialog turns these into links to the app's own access management.
		self.assertEqual(precheck["missing_courses"], [self.course.name])
		with self.assertRaises(frappe.ValidationError):
			self._assign(template, self.student, "key-blocked")

	def test_accept_refused_when_source_deleted(self):
		"""Spec 7: acceptance requires the requirements to still be valid."""
		name = self._drive_to_review("key-accept-dead")
		self._delete_lesson(self.lesson_quiz)
		frappe.set_user(self.teacher.email)
		with self.assertRaises(frappe.ValidationError):
			homework_service.accept(name)
		self.assertEqual(frappe.get_value("LMS Homework Assignment", name, "status"), "Review")

	def test_idempotent_same_key_returns_same_assignment(self):
		self._enroll(self.student)
		template = self._template("Idempotent", [self.lesson_plain])
		first = self._assign(template, self.student, "key-same")
		second = self._assign(template, self.student, "key-same")
		self.assertTrue(first["created"])
		self.assertFalse(second["created"])
		self.assertTrue(second["idempotent"])
		self.assertEqual(first["name"], second["name"])
		self.assertEqual(frappe.db.count("LMS Homework Assignment", {"homework": template}), 1)

	def test_active_assignment_reported_then_force_creates_second(self):
		self._enroll(self.student)
		template = self._template("Active", [self.lesson_plain])
		first = self._assign(template, self.student, "key-first")
		without_force = self._assign(template, self.student, "key-second")
		self.assertFalse(without_force["created"])
		self.assertTrue(without_force["already_active"])
		self.assertEqual(without_force["name"], first["name"])

		deliberate = self._assign(template, self.student, "key-third", force=True)
		self.assertTrue(deliberate["created"])
		self.assertNotEqual(first["name"], deliberate["name"])
		self.assertEqual(frappe.db.count("LMS Homework Assignment", {"homework": template}), 2)

	def test_two_students_isolated(self):
		self._enroll(self.student)
		self._enroll(self.student2)
		template = self._template("Isolated", [self.lesson_plain, self.lesson_quiz])
		first = self._assign(template, self.student, "key-a")["name"]
		second = self._assign(template, self.student2, "key-b")["name"]
		self.assertNotEqual(first, second)

		frappe.set_user(self.student.email)
		homework_service.record_lesson_opened(self.lesson_plain.name)
		self.assertEqual(frappe.get_value("LMS Homework Assignment", first, "status"), "In Progress")
		self.assertEqual(frappe.get_value("LMS Homework Assignment", second, "status"), "To Do")

	def test_template_edit_never_rewrites_snapshot(self):
		self._enroll(self.student)
		template = self._template("Snapshot", [self.lesson_plain])
		name = self._assign(template, self.student, "key-snap")["name"]

		homework_api.save_homework(
			name=template,
			title="Renamed",
			days=9,
			details="new details",
			items=[
				{
					"source_type": "Lesson",
					"name": self.lesson_quiz.name,
					"course": self.course.name,
					"title": self.lesson_quiz.title,
					"chapter": "",
					"path": self.lesson_quiz.title,
				}
			],
		)

		doc = frappe.get_doc("LMS Homework Assignment", name)
		self.assertEqual(doc.title, "Snapshot")
		self.assertEqual(doc.days, 3)
		self.assertEqual(doc.details, None)
		self.assertEqual(len(doc.requirements), 1)
		self.assertEqual(doc.requirements[0].lesson, self.lesson_plain.name)

	def test_due_at_is_end_of_day_n_days_later(self):
		assigned = datetime(2026, 10, 21, 10, 30, 0)
		due = homework_service.compute_due_at(assigned, 3)
		self.assertEqual(due, datetime(2026, 10, 24, 23, 59, 59))

	def test_snapshot_embeds_quiz_requirements(self):
		self._enroll(self.student)
		template = self._template("With quiz", [self.lesson_quiz])
		name = self._assign(template, self.student, "key-quiz")["name"]
		statuses = self._statuses(name)
		self.assertIn(("Open Lesson", self.lesson_quiz.name), statuses)
		self.assertIn(("Pass Quiz", self.quiz.name), statuses)
		self.assertEqual(len(self._requirements(name)), 2)

	# --- Prior credit and start (A15, A21) ---

	def test_prior_credit_and_straight_to_review(self):
		self._enroll(self.student)
		# The student already completed the plain lesson and passed the quiz
		# before the homework existed.
		self._create_lesson_progress(self.student.email, self.course.name, self.lesson_plain.name)
		self._submit(self.student, correct=True)

		template = self._template("Pre-credited", [self.lesson_plain, self.lesson_quiz])
		name = self._assign(template, self.student, "key-prior")["name"]
		doc = frappe.get_doc("LMS Homework Assignment", name)
		# Not started yet: stays To Do even with everything credited (spec 4).
		self.assertEqual(doc.status, "To Do")
		for row in doc.requirements:
			if row.requirement_type == "Open Lesson":
				self.assertEqual(row.status, "Completed Earlier")
			else:
				self.assertEqual(row.status, "Completed Earlier")

		frappe.set_user(self.student.email)
		homework_service.mark_started(name)
		doc = frappe.get_doc("LMS Homework Assignment", name)
		self.assertEqual(doc.status, "Review")
		events = [row.event for row in doc.history]
		self.assertEqual(events, ["assigned", "started", "submitted_for_review"])

	def test_teacher_opening_never_starts(self):
		self._enroll(self.student)
		template = self._template("Teacher view", [self.lesson_plain])
		name = self._assign(template, self.student, "key-teacher-view")["name"]

		frappe.set_user(self.teacher.email)
		board = homework_api.get_homework_board(student=self.student.email)
		self.assertEqual(board["columns"][0]["status"], "To Do")
		with self.assertRaises(frappe.PermissionError):
			homework_service.mark_started(name)
		self.assertEqual(frappe.get_value("LMS Homework Assignment", name, "status"), "To Do")

	def test_student_first_open_starts_once(self):
		self._enroll(self.student)
		template = self._template("Start", [self.lesson_plain])
		name = self._assign(template, self.student, "key-start")["name"]

		frappe.set_user(self.student.email)
		self.assertTrue(homework_service.mark_started(name)["started"])
		self.assertFalse(homework_service.mark_started(name)["started"])
		doc = frappe.get_doc("LMS Homework Assignment", name)
		self.assertEqual(doc.status, "In Progress")
		self.assertEqual(len([row for row in doc.history if row.event == "started"]), 1)

	# --- Openings and quiz evidence (A16, A17, A18, A19, A22, A23) ---

	def test_open_lesson_updates_all_active_assignments(self):
		self._enroll(self.student)
		template_a = self._template("Board A", [self.lesson_plain])
		template_b = self._template("Board B", [self.lesson_plain])
		assignment_a = self._assign(template_a, self.student, "key-open-a")["name"]
		assignment_b = self._assign(template_b, self.student, "key-open-b")["name"]

		# Straight from the course, no homework link: both cards move (spec 6.3).
		frappe.set_user(self.student.email)
		result = homework_service.record_lesson_opened(self.lesson_plain.name)
		self.assertEqual(result["updated"], 2)

		for name in (assignment_a, assignment_b):
			doc = frappe.get_doc("LMS Homework Assignment", name)
			self.assertEqual(doc.status, "Review")  # all requirements done + started

	def test_quiz_below_threshold_blocks_review(self):
		self._enroll(self.student)
		template = self._template("Threshold", [self.lesson_quiz])
		name = self._assign(template, self.student, "key-threshold")["name"]

		frappe.set_user(self.student.email)
		homework_service.record_lesson_opened(self.lesson_quiz.name)  # opening counted
		self._submit(self.student, correct=False)  # failing attempt

		doc = frappe.get_doc("LMS Homework Assignment", name)
		self.assertEqual(doc.status, "In Progress")
		statuses = self._statuses(name)
		self.assertEqual(statuses[("Open Lesson", self.lesson_quiz.name)], "Completed")
		self.assertEqual(statuses[("Pass Quiz", self.quiz.name)], "Pending")

	def test_final_pass_moves_to_review(self):
		self._enroll(self.student)
		template = self._template("Final pass", [self.lesson_quiz])
		name = self._assign(template, self.student, "key-final")["name"]

		frappe.set_user(self.student.email)
		homework_service.record_lesson_opened(self.lesson_quiz.name)
		self._submit(self.student, correct=False)
		self.assertEqual(frappe.get_value("LMS Homework Assignment", name, "status"), "In Progress")

		self._submit(self.student, correct=True)
		doc = frappe.get_doc("LMS Homework Assignment", name)
		self.assertEqual(doc.status, "Review")
		row = next(row for row in doc.requirements if row.requirement_type == "Pass Quiz")
		self.assertEqual(row.status, "Completed")
		self.assertEqual(row.proof_type, "LMS Quiz Submission")
		self.assertTrue(frappe.db.exists("LMS Quiz Submission", row.proof_name))

	def test_later_failure_keeps_earlier_pass(self):
		self._enroll(self.student)
		template = self._template("Keep pass", [self.lesson_quiz])
		name = self._assign(template, self.student, "key-keep")["name"]

		frappe.set_user(self.student.email)
		homework_service.record_lesson_opened(self.lesson_quiz.name)
		self._submit(self.student, correct=True)
		self.assertEqual(frappe.get_value("LMS Homework Assignment", name, "status"), "Review")

		# A later failed retake must not revoke the confirmed pass (A23). With the
		# #34 retake-credit rule a repeated attempt may still carry the credited
		# rows; either way the requirement stays confirmed.
		self._submit(self.student, correct=False)
		statuses = self._statuses(name)
		self.assertEqual(statuses[("Pass Quiz", self.quiz.name)], "Completed")
		self.assertEqual(frappe.get_value("LMS Homework Assignment", name, "status"), "Review")

	# --- Teacher decisions (A25, A26, A27, A28, A31) ---

	def _drive_to_review(self, template_key):
		self._enroll(self.student)
		template = self._template("Flow", [self.lesson_quiz])
		name = self._assign(template, self.student, template_key)["name"]
		frappe.set_user(self.student.email)
		homework_service.record_lesson_opened(self.lesson_quiz.name)
		self._submit(self.student, correct=True)
		frappe.set_user(self.teacher.email)
		return name

	def test_accept_records_actor_and_ignores_repeat(self):
		name = self._drive_to_review("key-accept")
		homework_service.accept(name)
		doc = frappe.get_doc("LMS Homework Assignment", name)
		self.assertEqual(doc.status, "Done")
		self.assertEqual(doc.reviewed_by, self.teacher.email)
		accepted_rows = [row for row in doc.history if row.event == "accepted"]
		self.assertEqual(len(accepted_rows), 1)

		homework_service.accept(name)  # repeat confirmation: no duplicate audit
		doc = frappe.get_doc("LMS Homework Assignment", name)
		self.assertEqual(len([row for row in doc.history if row.event == "accepted"]), 1)

	def test_return_comment_required_and_review_suppressed(self):
		name = self._drive_to_review("key-return")

		with self.assertRaises(frappe.ValidationError):
			homework_service.return_for_revision(name, "   ")

		homework_service.return_for_revision(name, "Redo the last task")
		doc = frappe.get_doc("LMS Homework Assignment", name)
		self.assertEqual(doc.status, "In Progress")
		self.assertEqual(doc.needs_revision, 1)
		self.assertEqual(doc.last_revision_comment, "Redo the last task")

		# Refreshes and recomputes must not bounce it back to Review (A26).
		homework_service.recompute_quiz_requirements(self.student.email, self.quiz.name)
		self.assertEqual(frappe.get_value("LMS Homework Assignment", name, "status"), "In Progress")

	def test_resubmit_requires_full_completion(self):
		name = self._drive_to_review("key-resubmit")
		homework_service.return_for_revision(name, "Fix")
		doc = frappe.get_doc("LMS Homework Assignment", name)

		# Nothing incomplete here, so the resubmission goes through; make one
		# requirement incomplete to prove refusal first.
		row = next(row for row in doc.requirements if row.requirement_type == "Pass Quiz")
		frappe.db.set_value(
			"LMS Homework Requirement",
			row.name,
			{"status": "Pending", "completed_at": None},
			update_modified=False,
		)
		frappe.set_user(self.student.email)
		with self.assertRaises(frappe.ValidationError):
			homework_service.resubmit(name)

		# Complete it again through the evidence path, then resubmit.
		self._submit(self.student, correct=True)
		frappe.set_user(self.student.email)
		homework_service.resubmit(name)
		self.assertEqual(frappe.get_value("LMS Homework Assignment", name, "status"), "Review")

	def test_reopen_done_with_comment(self):
		name = self._drive_to_review("key-reopen")
		homework_service.accept(name)
		with self.assertRaises(frappe.ValidationError):
			homework_service.reopen(name, "")
		homework_service.reopen(name, "The proof was annulled")
		doc = frappe.get_doc("LMS Homework Assignment", name)
		self.assertEqual(doc.status, "In Progress")
		self.assertEqual(doc.needs_revision, 1)

	def test_revoke_hides_and_freezes(self):
		self._enroll(self.student)
		template = self._template("Revoke", [self.lesson_quiz])
		name = self._assign(template, self.student, "key-revoke")["name"]

		with self.assertRaises(frappe.ValidationError):
			homework_service.revoke(name, " ")
		homework_service.revoke(name, "Issued by mistake")

		frappe.set_user(self.student.email)
		board = homework_api.get_homework_board(student=self.student.email)
		counts = sum(column["count"] for column in board["columns"])
		self.assertEqual(counts, 0)

		# Later course events no longer touch the recalled card (spec 8.1).
		result = homework_service.record_lesson_opened(self.lesson_quiz.name)
		self.assertEqual(result["updated"], 0)

	def test_deadline_change_recorded_in_history(self):
		self._enroll(self.student)
		template = self._template("Deadline", [self.lesson_plain])
		name = self._assign(template, self.student, "key-deadline")["name"]
		old_due = frappe.get_value("LMS Homework Assignment", name, "due_at")

		homework_service.change_deadline(name, 10)
		doc = frappe.get_doc("LMS Homework Assignment", name)
		self.assertNotEqual(doc.due_at, old_due)
		self.assertEqual(len([row for row in doc.history if row.event == "deadline_changed"]), 1)

	# --- Authority (A24) ---

	def test_student_cannot_accept_or_edit_status(self):
		name = self._drive_to_review("key-auth")
		frappe.set_user(self.student.email)
		with self.assertRaises(frappe.PermissionError):
			homework_service.accept(name)

		frappe.set_user(self.teacher.email)
		doc = frappe.get_doc("LMS Homework Assignment", name)
		doc.status = "Done"
		with self.assertRaises(frappe.PermissionError):
			doc.save()

	def test_student_cannot_view_another_board(self):
		self._enroll(self.student)
		template = self._template("Board auth", [self.lesson_plain])
		self._assign(template, self.student, "key-board")
		frappe.set_user(self.student2.email)
		with self.assertRaises(frappe.PermissionError):
			homework_api.get_homework_board(student=self.student.email)

	# --- Proof invalidation (spec 7, last row) ---

	def test_annulled_submission_reopens_review(self):
		name = self._drive_to_review("key-annul")
		self.assertEqual(frappe.get_value("LMS Homework Assignment", name, "status"), "Review")

		# The teacher annuls the only passing attempt.
		submission = frappe.get_all(
			"LMS Quiz Submission",
			filters={"quiz": self.quiz.name, "member": self.student.email},
			pluck="name",
		)[0]
		frappe.set_user("Administrator")
		frappe.delete_doc("LMS Quiz Submission", submission)
		frappe.set_user(self.teacher.email)

		doc = frappe.get_doc("LMS Homework Assignment", name)
		self.assertEqual(doc.status, "In Progress")
		self.assertTrue(any(row.event == "requirement_invalidated" for row in doc.history))

	def test_open_ended_grading_flow(self):
		"""A20: an ungraded open answer is not a success; the teacher's grade
		recomputes the requirement through the submission's own on_update."""
		self._enroll(self.student)

		question = frappe.new_doc("LMS Question")
		question.update({"question": "Explain the atom", "type": "Open Ended"})
		question.save()
		quiz = frappe.new_doc("LMS Quiz")
		quiz.update({"title": "HW Open Ended Quiz", "passing_percentage": 70, "total_marks": 5})
		quiz.append("questions", {"question": question.name, "marks": 5, "type": "Open Ended"})
		quiz.save()

		lesson = self._lesson("Open ended lesson", QUIZ_BLOCK.format(quiz.name))
		template = self._template("Open ended", [lesson])
		name = self._assign(template, self.student, "key-open-ended")["name"]

		frappe.set_user(self.student.email)
		homework_service.record_lesson_opened(lesson.name)
		submit_quiz(quiz.name, json.dumps([{"question_name": question.name, "answer": ["My essay"]}]))

		doc = frappe.get_doc("LMS Homework Assignment", name)
		row = next(row for row in doc.requirements if row.requirement_type == "Pass Quiz")
		self.assertEqual(row.status, "Awaiting Grading")
		self.assertEqual(doc.status, "In Progress")  # no false success yet

		# The teacher grades; the submission's save recomputes the homework.
		# C01: a verdict is marks AND the explicit graded flag together -- the
		# grading page writes both; the controller accepts the flag only from a
		# permitted grader.
		frappe.set_user(self.teacher.email)
		submission = frappe.get_all(
			"LMS Quiz Submission",
			filters={"quiz": quiz.name, "member": self.student.email},
			pluck="name",
		)[0]
		submission_doc = frappe.get_doc("LMS Quiz Submission", submission)
		for result_row in submission_doc.result:
			result_row.marks = result_row.marks_out_of
			result_row.graded = 1
		# DocPerms grant no submission write to plain teachers on this stack;
		# the controller remains the authority on who may record a verdict (C01).
		submission_doc.save(ignore_permissions=True)

		doc = frappe.get_doc("LMS Homework Assignment", name)
		row = next(row for row in doc.requirements if row.requirement_type == "Pass Quiz")
		self.assertEqual(row.status, "Completed")
		self.assertEqual(doc.status, "Review")

	def test_deleted_source_reads_unavailable(self):
		"""A30: deleting the lesson after issuing leaves the frozen row but the
		detail reads it as Unavailable instead of counting it."""
		self._enroll(self.student)
		template = self._template("Vanishing", [self.lesson_plain])
		name = self._assign(template, self.student, "key-vanish")["name"]

		self._delete_lesson(self.lesson_plain)

		frappe.set_user(self.student.email)
		detail = homework_api.get_homework_assignment(name)
		lesson_rows = [row for row in detail["requirements"] if row["requirement_type"] == "Open Lesson"]
		self.assertEqual(lesson_rows[0]["status"], "Unavailable")
		self.assertEqual(lesson_rows[0]["state_label"], "Unavailable")

	def test_open_answer_pending_even_with_passing_auto_part(self):
		"""R07 on this stack's quiz rule (a quiz is either all-objective or
		all-open-ended): the lesson carries BOTH -- an objective quiz the machine
		passes at once and an open-ended one awaiting a human. The auto success
		completes its own row, but the work is not done while the open answer is
		unjudged; the percentage alone must not issue a final verdict."""
		self._enroll(self.student)

		auto_question = frappe.new_doc("LMS Question")
		auto_question.update(
			{"question": "2+2?", "type": "Choices", "option_1": "4", "is_correct_1": 1, "option_2": "5"}
		)
		auto_question.save()
		auto_quiz = frappe.new_doc("LMS Quiz")
		auto_quiz.update({"title": "HW Auto Quiz", "passing_percentage": 50, "total_marks": 5})
		auto_quiz.append("questions", {"question": auto_question.name, "marks": 5, "type": "Choices"})
		auto_quiz.save()

		open_question = frappe.new_doc("LMS Question")
		open_question.update({"question": "Explain", "type": "Open Ended"})
		open_question.save()
		open_quiz = frappe.new_doc("LMS Quiz")
		open_quiz.update({"title": "HW Open Quiz", "passing_percentage": 50, "total_marks": 5})
		open_quiz.append("questions", {"question": open_question.name, "marks": 5, "type": "Open Ended"})
		open_quiz.save()

		two_quizzes = json.dumps(
			{
				"blocks": [
					{"type": "quiz", "data": {"quiz": auto_quiz.name}},
					{"type": "quiz", "data": {"quiz": open_quiz.name}},
				]
			}
		)
		lesson = self._lesson("Mixed lesson", two_quizzes)
		template = self._template("Mixed", [lesson])
		name = self._assign(template, self.student, "key-mixed")["name"]

		frappe.set_user(self.student.email)
		homework_service.record_lesson_opened(lesson.name)
		submit_quiz(
			auto_quiz.name,
			json.dumps([{"question_name": auto_question.name, "answer": ["4"]}]),
		)

		doc = frappe.get_doc("LMS Homework Assignment", name)
		auto_row = next(row for row in doc.requirements if row.quiz == auto_quiz.name)
		open_row = next(row for row in doc.requirements if row.quiz == open_quiz.name)
		self.assertEqual(auto_row.status, "Completed")
		self.assertEqual(open_row.status, "Pending")
		self.assertEqual(doc.status, "In Progress")

		submit_quiz(
			open_quiz.name,
			json.dumps([{"question_name": open_question.name, "answer": ["My essay"]}]),
		)

		doc = frappe.get_doc("LMS Homework Assignment", name)
		open_row = next(row for row in doc.requirements if row.quiz == open_quiz.name)
		self.assertEqual(open_row.status, "Awaiting Grading")
		self.assertEqual(doc.status, "In Progress")

		# A partial FINAL grade (3 of 5) is a verdict, not a pending state:
		# marks plus the explicit graded flag (C01), as the grading page sends.
		frappe.set_user(self.teacher.email)
		submission = frappe.get_all(
			"LMS Quiz Submission",
			filters={"quiz": open_quiz.name, "member": self.student.email},
			pluck="name",
		)[0]
		submission_doc = frappe.get_doc("LMS Quiz Submission", submission)
		for result_row in submission_doc.result:
			if result_row.question_type == "Open Ended":
				result_row.marks = 3
				result_row.graded = 1
		# DocPerms grant no submission write to plain teachers on this stack;
		# the controller remains the authority on who may record a verdict.
		submission_doc.save(ignore_permissions=True)

		doc = frappe.get_doc("LMS Homework Assignment", name)
		open_row = next(row for row in doc.requirements if row.quiz == open_quiz.name)
		self.assertEqual(open_row.status, "Completed")
		self.assertEqual(doc.status, "Review")

	def test_threshold_raise_keeps_earlier_pass(self):
		"""R07: the verdict is read off the attempt's own snapshotted threshold;
		raising the live threshold later never un-passes a valid attempt."""
		self._enroll(self.student)
		template = self._template("Threshold snapshot", [self.lesson_quiz])
		name = self._assign(template, self.student, "key-threshold-snapshot")["name"]

		frappe.set_user(self.student.email)
		homework_service.record_lesson_opened(self.lesson_quiz.name)
		self._submit(self.student, correct=True)
		self.assertEqual(frappe.get_value("LMS Homework Assignment", name, "status"), "Review")

		frappe.set_user(self.teacher.email)
		frappe.db.set_value("LMS Quiz", self.quiz.name, "passing_percentage", 100)
		homework_service.recompute_quiz_requirements(self.student.email, self.quiz.name)
		statuses = self._statuses(name)
		self.assertEqual(statuses[("Pass Quiz", self.quiz.name)], "Completed")
		self.assertEqual(frappe.get_value("LMS Homework Assignment", name, "status"), "Review")

	def test_locked_unselected_lesson_does_not_block(self):
		"""R05: only the SELECTED materials gate the issue -- a sequentially
		locked lesson the composition does not name must not block it."""
		self._enroll(self.student)
		frappe.set_user(self.teacher.email)
		frappe.db.set_value("LMS Course", self.course.name, "enforce_lesson_completion", 1)

		template = self._template("First lesson only", [self.lesson_plain])
		frappe.set_user(self.teacher.email)
		precheck = homework_api.precheck_assignment(template, self.student.email, 3)
		self.assertEqual(precheck["reasons"], [])
		created = self._assign(template, self.student, "key-first-lesson")
		self.assertTrue(created["created"])

	def test_written_assignment_composition(self):
		"""R10/A34 as the platform actually grants it: a member reaches a written
		assignment through its student-visible lesson placement -- the course
		stamp alone is an author reach. The openable requirement therefore rides
		the placing lesson, and a stamp-only assignment is refused at issue time
		with the reason, instead of silently issuing unreadable material."""
		self._enroll(self.student)
		written = self._create_assignment(title="HW Written Task")
		frappe.db.set_value("LMS Assignment", written.name, "course", self.course.name)
		lesson = self._lesson("Written task lesson", ASSIGNMENT_BLOCK.format(written.name))

		template = self._template("Written", [lesson])
		name = self._assign(template, self.student, "key-written")["name"]

		doc = frappe.get_doc("LMS Homework Assignment", name)
		self.assertEqual(
			{row.requirement_type for row in doc.requirements}, {"Open Lesson", "Open Assignment"}
		)
		self.assertEqual(doc.status, "To Do")

		frappe.set_user(self.student.email)
		homework_service.record_assignment_opened(written.name)
		doc = frappe.get_doc("LMS Homework Assignment", name)
		assignment_row = next(r for r in doc.requirements if r.requirement_type == "Open Assignment")
		self.assertEqual(assignment_row.status, "Completed")
		self.assertEqual(doc.status, "In Progress")  # the lesson itself still waits

		homework_service.record_lesson_opened(lesson.name)
		doc = frappe.get_doc("LMS Homework Assignment", name)
		self.assertEqual(doc.status, "Review")

		# A stamp-only assignment has no student reach on this stack: issuing it
		# is refused with the availability reason, never silently.
		frappe.set_user("Administrator")
		lonely = self._create_assignment(title="HW Lonely Task")
		frappe.db.set_value("LMS Assignment", lonely.name, "course", self.course.name)
		frappe.set_user(self.teacher.email)
		lonely_template = self._template("Lonely only", [], assignments=[lonely.name])
		with self.assertRaises(frappe.ValidationError):
			self._assign(lonely_template, self.student, "key-lonely")

	def test_actions_blocked_after_revoke(self):
		"""R06: a recalled assignment is frozen history for every action."""
		name = self._drive_to_review("key-frozen")
		homework_service.revoke(name, "Issued by mistake")

		frappe.set_user(self.teacher.email)
		for action in (
			lambda: homework_service.accept(name),
			lambda: homework_service.return_for_revision(name, "x"),
			lambda: homework_service.reopen(name, "x"),
			lambda: homework_service.change_deadline(name, 9),
		):
			with self.assertRaises(frappe.PermissionError):
				action()

		frappe.set_user(self.student.email)
		with self.assertRaises(frappe.PermissionError):
			homework_service.resubmit(name)

	def test_client_cannot_edit_assignment_through_rest(self):
		"""R02: the managed fields move only through the named actions; a direct
		document write by the teacher himself is refused."""
		self._enroll(self.student)
		template = self._template("REST guard", [self.lesson_plain])
		name = self._assign(template, self.student, "key-rest-guard")["name"]

		frappe.set_user(self.teacher.email)
		doc = frappe.get_doc("LMS Homework Assignment", name)
		doc.status = "Done"
		with self.assertRaises(frappe.PermissionError):
			doc.save()

		doc = frappe.get_doc("LMS Homework Assignment", name)
		doc.needs_revision = 1
		with self.assertRaises(frappe.PermissionError):
			doc.save()

		frappe.set_user(self.teacher.email)
		fresh = frappe.get_doc({"doctype": "LMS Homework Assignment", "student": self.student.email})
		with self.assertRaises(frappe.PermissionError):
			fresh.insert()

	def test_foreign_template_access_refused(self):
		"""R03: the library door is checked per endpoint, not by the list query."""
		self._enroll(self.student)
		template = self._template("Private", [self.lesson_plain])
		frappe.set_user(self.teacher.email)

		frappe.set_user("Administrator")
		if not frappe.db.exists("User", "hw-other-teacher@example.com"):
			self._create_user(
				"hw-other-teacher@example.com", "Oleg", "Other", ["Course Creator", "LMS Student"]
			)
		frappe.set_user("hw-other-teacher@example.com")
		with self.assertRaises(frappe.PermissionError):
			homework_api.get_homework(template)
		with self.assertRaises(frappe.PermissionError):
			homework_api.copy_homework(template)
		with self.assertRaises(frappe.PermissionError):
			homework_api.archive_homework(template)
		frappe.set_user(self.student.email)
		with self.assertRaises(frappe.PermissionError):
			homework_api.get_homework(template)

	def test_board_counts_and_course_filter(self):
		self._enroll(self.student)
		template = self._template("Board counts", [self.lesson_plain])
		self._assign(template, self.student, "key-counts")
		frappe.set_user(self.student.email)
		board = homework_api.get_homework_board(student=self.student.email)
		self.assertEqual(board["columns"][0]["count"], 1)
		board_filtered = homework_api.get_homework_board(student=self.student.email, course=self.course.name)
		self.assertEqual(board_filtered["columns"][0]["count"], 1)
		board_other = homework_api.get_homework_board(student=self.student.email, course="no-such-course")
		self.assertEqual(sum(c["count"] for c in board_other["columns"]), 0)


class TestHomeworkDeepTree(BaseTestUtils, IntegrationTestCase):
	"""A09 for real: task #28's four-level mixed section tree through the whole
	homework pipeline -- resolver, snapshot, and the multi-segment lesson routes
	("1-1-1-1": section path 1-1-1, first lesson)."""

	def setUp(self):
		super().setUp()
		self.teacher = self._create_user(
			"hw-deep-teacher@example.com", "Dana", "Deep", ["Course Creator", "LMS Student"]
		)
		self.student = self._create_user("hw-deep-student@example.com", "Eve", "Deep", ["LMS Student"])
		frappe.set_user(self.teacher.email)
		self.course = self._create_course(title="HW Deep Course", instructor=self.teacher.email)

	def _section(self, title, parent_section=None):
		doc = frappe.new_doc("Course Chapter")
		doc.update({"course": self.course.name, "title": title, "parent_section": parent_section})
		doc.insert()
		return doc

	def _child_row(self, parent, idx, lesson=None, section=None):
		row = frappe.new_doc("Lesson Reference")
		row.update(
			{
				"idx": idx,
				"lesson": lesson,
				"section": section,
				"parent": parent.name,
				"parenttype": "Course Chapter",
				"parentfield": "lessons",
			}
		)
		row.insert()

	def _deep_course(self):
		"""Block -> [lesson L1, section Chapter]; Chapter -> [section Part, lesson
		L2]; Part -> [lesson L3 with an embedded quiz]. Four structural levels,
		mixed children on the way down."""
		block = self._section("Block")
		self._create_chapter_reference(self.course.name, block.name, idx=1)
		chapter = self._section("Chapter", parent_section=block.name)
		part = self._section("Part", parent_section=chapter.name)

		questions = self._create_quiz_questions()
		quiz = self._create_quiz(questions, title="HW Deep Quiz")
		quiz_block = QUIZ_BLOCK.format(quiz.name)

		l1 = self._create_lesson("Shallow lesson", block.name, self.course.name)
		l2 = self._create_lesson("Mid lesson", chapter.name, self.course.name)
		l3 = self._create_lesson("Deep lesson", part.name, self.course.name, quiz_block)

		self._child_row(block, 1, lesson=l1.name)
		self._child_row(block, 2, section=chapter.name)
		self._child_row(chapter, 1, section=part.name)
		self._child_row(chapter, 2, lesson=l2.name)
		self._child_row(part, 1, lesson=l3.name)
		return {"block": block, "chapter": chapter, "part": part, "l1": l1, "l2": l2, "l3": l3, "quiz": quiz}

	def test_resolver_walks_four_levels_of_mixed_children(self):
		fixtures = self._deep_course()
		frappe.set_user(self.teacher.email)
		tree = homework_sources.get_course_source_tree(self.course.name)

		self.assertEqual(len(tree["nodes"]), 1)
		block = tree["nodes"][0]
		self.assertEqual(block["type"], "chapter")
		self.assertEqual([child["type"] for child in block["children"]], ["lesson", "chapter"])

		chapter = block["children"][1]
		self.assertEqual([child["type"] for child in chapter["children"]], ["chapter", "lesson"])
		part = chapter["children"][0]
		deep_lesson = part["children"][0]
		self.assertEqual(deep_lesson["name"], fixtures["l3"].name)
		self.assertEqual([quiz["name"] for quiz in deep_lesson["quizzes"]], [fixtures["quiz"].name])

	def test_deep_lesson_assigns_and_routes_with_multisegment_number(self):
		fixtures = self._deep_course()
		self._create_enrollment(self.student.email, self.course.name)
		frappe.set_user(self.teacher.email)
		result = homework_api.save_homework(
			title="Deep work",
			days=5,
			items=[
				{
					"source_type": "Lesson",
					"name": fixtures["l3"].name,
					"course": self.course.name,
					"title": fixtures["l3"].title,
					"chapter": "",
					"path": f"Course / Block / Chapter / Part / {fixtures['l3'].title}",
				}
			],
		)
		assignment = homework_api.assign_homework(
			homework=result["name"],
			student=self.student.email,
			idempotency_key="deep-key",
		)["name"]

		doc = frappe.get_doc("LMS Homework Assignment", assignment)
		self.assertEqual(len(doc.requirements), 2)  # the lesson + its embedded quiz

		frappe.set_user(self.student.email)
		detail = homework_api.get_homework_assignment(assignment)
		lesson_row = next(row for row in detail["requirements"] if row["requirement_type"] == "Open Lesson")
		# Section path 1-1-1 (Block->Chapter->Part), first lesson of Part.
		self.assertEqual(lesson_row["route"]["number"], "1-1-1-1")
		self.assertEqual(detail["continue_target"]["number"], "1-1-1-1")


class TestHomeworkRound2(BaseTestUtils, IntegrationTestCase):
	"""Round-2 review scenarios (B01-B11), as real Frappe tests: the grading
	signal, unbounded attempt history, dead sources at resubmit, idempotency
	parameter checks, stuck-card recovery, whole-snapshot guarding, source
	rights on every write path, and the standalone-assignment board link."""

	def setUp(self):
		super().setUp()
		self.teacher = self._create_user(
			"hw2-teacher@example.com", "Ivy", "Round2", ["Course Creator", "LMS Student"]
		)
		self.student = self._create_user("hw2-student@example.com", "Kim", "Round2", ["LMS Student"])
		self.student2 = self._create_user("hw2-student2@example.com", "Lia", "Round2", ["LMS Student"])
		frappe.set_user(self.teacher.email)
		self.course = self._create_course(title="HW Round2 Course", instructor=self.teacher.email)
		self.questions = self._create_quiz_questions()
		self.quiz = self._create_quiz(self.questions, title="HW Round2 Quiz")
		self.lesson_quiz = self._lesson("Round2 quiz lesson", QUIZ_BLOCK.format(self.quiz.name))

	def _lesson(self, title, content=None):
		chapter = self._create_chapter(f"Chapter {title}", self.course.name)
		self._create_chapter_reference(self.course.name, chapter.name)
		lesson = self._create_lesson(title, chapter.name, self.course.name, content)
		self._create_lesson_reference(chapter.name, lesson.name)
		return lesson

	def _template(self, title, lessons=(), assignments=()):
		items = [
			{
				"source_type": "Lesson",
				"name": lesson.name,
				"course": self.course.name,
				"title": lesson.title,
				"chapter": "",
				"path": f"Course / {lesson.title}",
			}
			for lesson in lessons
		]
		items += [
			{
				"source_type": "Assignment",
				"name": assignment,
				"course": self.course.name,
				"title": assignment,
				"chapter": "",
				"path": f"Course / {assignment}",
			}
			for assignment in assignments
		]
		return homework_api.save_homework(title=title, days=3, items=items)["name"]

	def _enroll(self, student):
		self._create_enrollment(student.email, self.course.name)

	def _assign(self, template, student, key, days=None, force=False):
		frappe.set_user(self.teacher.email)
		return homework_api.assign_homework(
			homework=template, student=student.email, days=days, idempotency_key=key, force=force
		)

	def _delete_lesson(self, lesson):
		"""Delete a lesson on a stack that refuses deleting a linked document:
		the chapter's Lesson Reference row goes first, then the lesson itself.
		An administrator act -- the deletion is the fixture, not the subject."""
		frappe.set_user("Administrator")
		for ref in frappe.get_all("Lesson Reference", filters={"lesson": lesson.name}, pluck="name"):
			frappe.delete_doc("Lesson Reference", ref)
		for progress in frappe.get_all("LMS Course Progress", filters={"lesson": lesson.name}, pluck="name"):
			frappe.delete_doc("LMS Course Progress", progress)
		frappe.delete_doc("Course Lesson", lesson.name)

	def _submit(self, student, correct=True):
		frappe.set_user(student.email)
		results = []
		for question in self.questions:
			answer = [question.option_1] if correct else [question.option_2]
			results.append({"question_name": question.name, "answer": answer})
		submit_quiz(self.quiz.name, json.dumps(results))
		frappe.set_user(self.teacher.email)

	def _submission_of(self, quiz, member):
		return frappe.get_all(
			"LMS Quiz Submission",
			filters={"quiz": quiz, "member": member},
			order_by="creation desc",
			pluck="name",
			limit=1,
		)[0]

	# --- C01: the grading signal survives Int serialization -------------------

	def test_partial_autosave_of_two_open_answers_still_awaits(self):
		"""The grading page autosaves one typed mark at a time: one graded answer
		of two leaves the attempt unjudged; a FINAL ZERO on the second is the
		completing verdict, and only then may the card reach Review.

		Also pins the storage contract this rests on (C01): ``marks`` is Int, so
		an ungraded open answer reloads from the database as 0 -- the explicit
		``graded`` flag is what separates it from a deliberate zero."""
		self._enroll(self.student)
		questions = []
		for prompt in ("Explain gravity", "Explain entropy"):
			question = frappe.new_doc("LMS Question")
			question.update({"question": prompt, "type": "Open Ended"})
			question.save()
			questions.append(question)
		quiz = frappe.new_doc("LMS Quiz")
		quiz.update({"title": "HW2 Two Open Quiz", "passing_percentage": 50, "total_marks": 10})
		for question in questions:
			quiz.append("questions", {"question": question.name, "marks": 5, "type": "Open Ended"})
		quiz.save()

		# A fresh lesson carrying the two-answer quiz block: the composition's
		# Pass Quiz requirement is the two-answer quiz, not self.quiz.
		lesson = self._lesson("Two open lesson", QUIZ_BLOCK.format(quiz.name))
		template = self._template("Two open answers", lessons=[lesson])
		name = self._assign(template, self.student, "key-c01")["name"]

		frappe.set_user(self.student.email)
		homework_service.record_lesson_opened(lesson.name)
		# The quiz client sends answers as LISTS (SavedAnswer); a bare string is
		# rejected by _validate_quiz_results before anything is stored.
		submit_quiz(
			quiz.name,
			json.dumps(
				[
					{"question_name": questions[0].name, "answer": ["First essay"]},
					{"question_name": questions[1].name, "answer": ["Second essay"]},
				]
			),
		)

		doc = frappe.get_doc("LMS Homework Assignment", name)
		self.assertEqual(doc.status, "In Progress")
		row = next(row for row in doc.requirements if row.requirement_type == "Pass Quiz")
		self.assertEqual(row.status, "Awaiting Grading")

		# The storage round-trip the reviewer asked to pin down: reloaded from
		# the DB, the ungraded answer's marks READ AS 0 (Int serialization of a
		# missing value) and graded is 0 -- exactly why the flag, not the
		# number, decides.
		submission = frappe.get_doc("LMS Quiz Submission", self._submission_of(quiz.name, self.student.email))
		open_rows = [r for r in submission.result if r.question_type == "Open Ended"]
		self.assertEqual(open_rows[0].marks, 0)
		self.assertEqual(open_rows[1].marks, 0)
		self.assertFalse(open_rows[0].graded)
		self.assertFalse(open_rows[1].graded)

		# Autosave after grading ONLY the first answer (marks plus the flag the
		# grading page writes with it): the second row stays unflagged, so the
		# attempt is still unjudged -- its numeric 0 says nothing.
		frappe.set_user(self.teacher.email)
		submission = frappe.get_doc("LMS Quiz Submission", self._submission_of(quiz.name, self.student.email))
		open_rows = [r for r in submission.result if r.question_type == "Open Ended"]
		open_rows[0].marks = 5
		open_rows[0].graded = 1
		# DocPerms grant no submission write to plain teachers on this stack;
		# the controller still decides who may record a verdict (C01).
		submission.save(ignore_permissions=True)

		doc = frappe.get_doc("LMS Homework Assignment", name)
		row = next(row for row in doc.requirements if row.requirement_type == "Pass Quiz")
		self.assertEqual(row.status, "Awaiting Grading")
		self.assertEqual(doc.status, "In Progress")
		self.assertIsNone(homework_service.passed_quiz_evidence(self.student.email, quiz.name))

		# The final zero on the second answer completes the grading: the same
		# numeric value it already stored, but now with a verdict behind it.
		submission = frappe.get_doc("LMS Quiz Submission", self._submission_of(quiz.name, self.student.email))
		open_rows = [r for r in submission.result if r.question_type == "Open Ended"]
		open_rows[1].marks = 0
		open_rows[1].graded = 1
		submission.save(ignore_permissions=True)

		doc = frappe.get_doc("LMS Homework Assignment", name)
		row = next(row for row in doc.requirements if row.requirement_type == "Pass Quiz")
		self.assertEqual(row.status, "Completed")
		self.assertEqual(row.proof_name, submission.name)
		self.assertEqual(doc.status, "Review")

	def test_open_answer_flag_cannot_be_self_awarded(self):
		"""The grading flag is a grader's act (C01): the member's own save can
		never finalize an answer, and an outsider recording a verdict is
		refused by the submission controller."""
		self._enroll(self.student)
		question = frappe.new_doc("LMS Question")
		question.update({"question": "Explain something", "type": "Open Ended"})
		question.save()
		quiz = frappe.new_doc("LMS Quiz")
		quiz.update({"title": "HW2 Flag Quiz", "passing_percentage": 50, "total_marks": 5})
		quiz.append("questions", {"question": question.name, "marks": 5, "type": "Open Ended"})
		quiz.save()
		# The student must be able to reach the quiz to submit it: place it in a
		# student-visible lesson of the enrolled course.
		self._lesson("Flag quiz lesson", QUIZ_BLOCK.format(quiz.name))

		frappe.set_user(self.student.email)
		submit_quiz(quiz.name, json.dumps([{"question_name": question.name, "answer": ["My essay"]}]))
		submission = frappe.get_doc(
			"LMS Quiz Submission", self._submission_of(quiz.name, self.student.email)
		)
		# The author tries to finalize their own answer. The controller is the
		# authority here; the DocPerm layer (owner holds read only) is bypassed
		# the way the app's own server methods do.
		submission.result[0].graded = 1
		submission.save(ignore_permissions=True)
		submission = frappe.get_doc("LMS Quiz Submission", submission.name)
		self.assertFalse(submission.result[0].graded)
		self.assertTrue(homework_service._submission_awaiting_grading(submission.name))

		# A teacher with no review right on this quiz cannot record a verdict.
		outsider = self.student2
		frappe.set_user(outsider.email)
		submission.result[0].graded = 1
		# The controller refuses the outsider's verdict record (C01).
		with self.assertRaises(frappe.PermissionError):
			submission.save(ignore_permissions=True)

	# --- B03: the whole attempt history is consulted --------------------------

	def test_older_valid_pass_survives_fifty_new_failures(self):
		"""An old pass is never evicted by later failures, however many; deleting
		the only passing attempt removes the credit."""
		self._enroll(self.student)
		frappe.set_user(self.student.email)

		def insert_attempt(percentage, prefix):
			doc = frappe.new_doc("LMS Quiz Submission")
			doc.update(
				{
					"quiz": self.quiz.name,
					"member": self.student.email,
					"score": round(percentage / 10),
					"score_out_of": 10,
					"percentage": percentage,
					"passing_percentage": 70,
					"result": [],
				}
			)
			doc.insert(ignore_permissions=True)
			return doc.name

		old_pass = insert_attempt(80, "old")
		for index in range(50):
			insert_attempt(0, f"fail-{index}")

		evidence = homework_service.passed_quiz_evidence(self.student.email, self.quiz.name)
		self.assertEqual(evidence, old_pass)

		# C07: annulment is a staff act, not a student one -- LMS Student holds
		# no delete on quiz submissions. The teacher's delete fires the
		# after_delete hook, and the credit goes with the attempt.
		frappe.set_user("Administrator")
		frappe.delete_doc("LMS Quiz Submission", old_pass)
		self.assertIsNone(homework_service.passed_quiz_evidence(self.student.email, self.quiz.name))

	# --- B04: dead sources block resubmit; counters follow availability -------

	def test_dead_source_refuses_resubmit_and_refreshes_counters(self):
		self._enroll(self.student)
		template = self._template("Round2 flow", lessons=[self.lesson_quiz])
		name = self._assign(template, self.student, "key-b04")["name"]

		frappe.set_user(self.student.email)
		homework_service.record_lesson_opened(self.lesson_quiz.name)
		self._submit(self.student, correct=True)
		frappe.set_user(self.teacher.email)
		self.assertEqual(frappe.get_value("LMS Homework Assignment", name, "status"), "Review")
		homework_service.return_for_revision(name, "Tighten the essay")

		self._delete_lesson(self.lesson_quiz)
		frappe.set_user(self.student.email)

		frappe.set_user(self.student.email)
		with self.assertRaises(frappe.ValidationError):
			homework_service.resubmit(name)

		# Any later course event re-derives availability AND the counters with
		# it: the dead lesson reads Unavailable with 1 of 2 done, never 2 of 2.
		# (The quiz's only placement died with the lesson, so the student can no
		# longer sit it -- the recompute is triggered directly, exactly as the
		# submission hook would have.)
		frappe.set_user(self.teacher.email)
		homework_service.recompute_quiz_requirements(self.student.email, self.quiz.name)
		doc = frappe.get_doc("LMS Homework Assignment", name)
		lesson_row = next(row for row in doc.requirements if row.requirement_type == "Open Lesson")
		self.assertEqual(lesson_row.status, "Unavailable")
		self.assertEqual(doc.total_requirements, 2)
		self.assertEqual(doc.completed_requirements, 1)
		self.assertEqual(doc.status, "In Progress")

	# --- B05: one key, one logical operation ----------------------------------

	def test_idempotency_key_with_other_params_refused(self):
		self._enroll(self.student)
		self._enroll(self.student2)
		template = self._template("Idempotency params", lessons=[self.lesson_quiz])
		created = self._assign(template, self.student, "key-b05", days=3)
		self.assertTrue(created["created"])

		# Same key, different student: a stale replay, not a retry.
		with self.assertRaises(frappe.ValidationError):
			self._assign(template, self.student2, "key-b05", days=3)
		# Same key, different term: same verdict.
		with self.assertRaises(frappe.ValidationError):
			self._assign(template, self.student, "key-b05", days=5)
		# The true retry of the same operation returns the same card.
		again = self._assign(template, self.student, "key-b05", days=3)
		self.assertFalse(again["created"])
		self.assertEqual(again["name"], created["name"])

	# --- B06: a stuck card heals without a new student action -----------------

	def test_recompute_repairs_eligible_card_even_if_proof_did_not_change(self):
		self._enroll(self.student)
		template = self._template("Stuck card", lessons=[self.lesson_quiz])
		name = self._assign(template, self.student, "key-b06")["name"]
		frappe.set_user(self.student.email)
		homework_service.record_lesson_opened(self.lesson_quiz.name)
		self._submit(self.student, correct=True)
		frappe.set_user(self.teacher.email)
		self.assertEqual(frappe.get_value("LMS Homework Assignment", name, "status"), "Review")

		# Simulate the lost write: the rework flag is cleared server-side but
		# the card stays In Progress with every proof already stored.
		homework_service.return_for_revision(name, "One more look")
		frappe.db.set_value("LMS Homework Assignment", name, "needs_revision", 0, update_modified=False)

		homework_service.recompute_quiz_requirements(self.student.email, self.quiz.name)
		doc = frappe.get_doc("LMS Homework Assignment", name)
		self.assertEqual(doc.status, "Review")
		# C07: two review CYCLES legitimately record two submitted_for_review
		# events -- dedupe means a recompute must not add a third, not that the
		# first cycle's event disappears. Count the increment, then the no-op.
		events = [row for row in doc.history if row.event == "submitted_for_review"]
		self.assertEqual(len(events), 2)
		homework_service.recompute_quiz_requirements(self.student.email, self.quiz.name)
		doc = frappe.get_doc("LMS Homework Assignment", name)
		self.assertEqual(
			len([row for row in doc.history if row.event == "submitted_for_review"]), 2
		)

	# --- B07: the whole snapshot is guarded, evidence and history included ----

	def test_rest_guard_refuses_proof_dates_course_and_history(self):
		self._enroll(self.student)
		template = self._template("Snapshot guard", lessons=[self.lesson_quiz])
		name = self._assign(template, self.student, "key-b07")["name"]

		frappe.set_user(self.teacher.email)
		# Control: an identical save passes (the guard is not a blanket refusal).
		frappe.get_doc("LMS Homework Assignment", name).save(ignore_permissions=True)

		doc = frappe.get_doc("LMS Homework Assignment", name)
		row = next(row for row in doc.requirements if row.requirement_type == "Pass Quiz")
		row.proof_name = "another-students-pass"
		with self.assertRaises(frappe.PermissionError):
			doc.save(ignore_permissions=True)

		doc = frappe.get_doc("LMS Homework Assignment", name)
		row = next(row for row in doc.requirements if row.requirement_type == "Open Lesson")
		row.completed_at = datetime(2020, 1, 1, 0, 0, 0)
		with self.assertRaises(frappe.PermissionError):
			doc.save(ignore_permissions=True)

		doc = frappe.get_doc("LMS Homework Assignment", name)
		row = next(row for row in doc.requirements if row.requirement_type == "Open Lesson")
		# A Link field is validated before the managed-write guard, so the
		# tampered course must be a real one for the guard branch to fire.
		guard_course = self._create_course(title="Guard other course", instructor=self.teacher.email)
		row.course = guard_course.name
		with self.assertRaises(frappe.PermissionError):
			doc.save(ignore_permissions=True)

		doc = frappe.get_doc("LMS Homework Assignment", name)
		doc.append(
			"history",
			{"actor": self.teacher.email, "event": "accepted", "comment": "forged audit"},
		)
		with self.assertRaises(frappe.PermissionError):
			doc.save(ignore_permissions=True)

		stored = frappe.get_doc("LMS Homework Assignment", name)
		self.assertTrue(all(row.event != "accepted" for row in stored.history))

	# --- B01: source rights on every write path -------------------------------

	def test_foreign_course_sources_refused_on_every_path(self):
		frappe.set_user("Administrator")
		other = self._create_user(
			"hw2-other-teacher@example.com", "Oda", "Other", ["Course Creator", "LMS Student"]
		)
		frappe.set_user(other.email)
		other_course = self._create_course(title="HW2 Other Course", instructor=other.email)
		chapter = self._create_chapter("Other chapter", other_course.name)
		self._create_chapter_reference(other_course.name, chapter.name)
		foreign_lesson = self._create_lesson("Foreign lesson", chapter.name, other_course.name, None)
		self._create_lesson_reference(chapter.name, foreign_lesson.name)

		# Named API: canonicalization checks the resolved course's rights (B01).
		frappe.set_user(self.teacher.email)
		with self.assertRaises(frappe.PermissionError):
			homework_api.save_homework(
				title="Smuggled",
				days=3,
				items=[{"source_type": "Lesson", "name": foreign_lesson.name}],
			)

		# Direct document writes land on two distinct refusals (C07):
		# a MALFORMED row claims the lesson lives in this teacher's course --
		# that is a data lie and raises ValidationError; an HONEST row names the
		# foreign course and is refused for lack of sourcing rights
		# (PermissionError). Both blocked, by the branch that fits the case.
		forged = frappe.new_doc("LMS Homework")
		forged.update(
			{
				"title": "Forged row",
				"days": 2,
				"items": [
					{
						"source_type": "Lesson",
						"lesson": foreign_lesson.name,
						"quiz": None,
						"assignment": None,
						"course": self.course.name,
						"label": "Looks mine",
						"path": "Looks mine",
					}
				],
			}
		)
		with self.assertRaises(frappe.ValidationError):
			forged.insert()

		honest = frappe.new_doc("LMS Homework")
		honest.update(
			{
				"title": "Honest foreign row",
				"days": 2,
				"items": [
					{
						"source_type": "Lesson",
						"lesson": foreign_lesson.name,
						"quiz": None,
						"assignment": None,
						"course": other_course.name,
						"label": "Someone else's lesson",
						"path": "Someone else's lesson",
					}
				],
			}
		)
		with self.assertRaises(frappe.PermissionError):
			honest.insert()

		# And issuance re-resolves anyway: a forged stored course cannot borrow
		# this teacher's rights (defense in depth).
		reasons = homework_sources.validate_sources_for_student(
			[frappe._dict(source_type="Lesson", lesson=foreign_lesson.name, course=self.course.name, label="Forged")],
			self.student.email,
		)
		self.assertTrue(reasons)

	# --- B10: a standalone assignment carries its board link ------------------

	def test_written_assignment_card_has_continue_target(self):
		"""B10: the card's Continue first offers the placing lesson, and the
		written assignment itself once the lesson is done."""
		self._enroll(self.student)
		written = self._create_assignment(title="HW2 Written Task")
		frappe.db.set_value("LMS Assignment", written.name, "course", self.course.name)
		lesson = self._lesson("Round2 written lesson", ASSIGNMENT_BLOCK.format(written.name))
		template = self._template("Written round2", [lesson])
		created = self._assign(template, self.student, "key-b10")

		def card_of():
			frappe.set_user(self.teacher.email)
			board = homework_api.get_homework_board(student=self.student.email)
			for column in board["columns"]:
				for card in column["cards"]:
					if card["name"] == created["name"]:
						return card
			raise AssertionError("the card left the active board")

		first_target = card_of()["continue_target"]
		self.assertEqual(first_target["type"], "lesson")
		self.assertEqual(first_target["course"], self.course.name)

		frappe.set_user(self.student.email)
		homework_service.record_lesson_opened(lesson.name)
		self.assertEqual(
			card_of()["continue_target"],
			{"type": "assignment", "assignment": written.name, "course": self.course.name},
		)

	# --- C06: deferred events freeze on recalled cards; workers keep counts ---

	def test_cancelled_card_frozen_for_deferred_events(self):
		"""A recalled card is history: even the recovery paths that re-apply
		events after write races -- the queued opening job and the quiz-retry
		recompute -- must leave its rows, counters, status and audit alone."""
		self._enroll(self.student)
		template = self._template("Frozen deferred", lessons=[self.lesson_quiz])
		name = self._assign(template, self.student, "key-c06-frozen")["name"]

		frappe.set_user(self.student.email)
		homework_service.mark_started(name)
		frappe.set_user(self.teacher.email)
		homework_service.revoke(name, "Not this semester")

		before = frappe.get_doc("LMS Homework Assignment", name)
		before_rows = {row.name: row.status for row in before.requirements}
		before_events = [row.event for row in before.history]

		# The queued opening job fires after the recall.
		frappe.set_user(self.student.email)
		homework_service.apply_opening_job(
			self.student.email, name, lesson=self.lesson_quiz.name, attempt=1
		)
		# And the quiz-retry recompute path with a fresh pass on record.
		frappe.set_user(self.teacher.email)
		homework_service._recompute_with_retry_or_enqueue(
			name, member=self.student.email, quiz=self.quiz.name
		)

		after = frappe.get_doc("LMS Homework Assignment", name)
		self.assertEqual({row.name: row.status for row in after.requirements}, before_rows)
		self.assertEqual([row.event for row in after.history], before_events)
		self.assertEqual(after.status, before.status)
		self.assertEqual(after.first_opened_at, before.first_opened_at)
		self.assertEqual(after.completed_requirements, before.completed_requirements)

	def test_worker_recompute_refreshes_counters_with_availability(self):
		"""The queued catch-up worker saves row transitions together with their
		aggregates: a Completed row turning Unavailable drops the counter in the
		same write, never leaving a stale '1 of 1 done' over a dead source."""
		self._enroll(self.student)
		template = self._template("Worker counters", lessons=[self.lesson_quiz])
		name = self._assign(template, self.student, "key-c06-counters")["name"]

		frappe.set_user(self.student.email)
		homework_service.record_lesson_opened(self.lesson_quiz.name)
		self._submit(self.student, correct=True)

		self._delete_lesson(self.lesson_quiz)

		homework_service.recompute_assignment(name)
		doc = frappe.get_doc("LMS Homework Assignment", name)
		lesson_row = next(row for row in doc.requirements if row.requirement_type == "Open Lesson")
		self.assertEqual(lesson_row.status, "Unavailable")
		self.assertEqual(doc.total_requirements, 2)
		self.assertEqual(doc.completed_requirements, 1)
