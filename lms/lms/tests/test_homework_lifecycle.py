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

from lms.lms import homework_api, homework_service
from lms.lms.doctype.lms_quiz.lms_quiz import submit_quiz
from lms.lms.test_helpers import BaseTestUtils

QUIZ_BLOCK = '{{"blocks": [{{"type": "quiz", "data": {{"quiz": "{0}"}}}}]}}'


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

	def _template(self, title, lessons, quizzes=()):
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
			(row.requirement_type, row.lesson or row.quiz): row.status for row in self._requirements(name)
		}

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
		with self.assertRaises(frappe.ValidationError):
			self._assign(template, self.student, "key-blocked")

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
		self.assertEqual(without_force["already_active"], first["name"])

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
		self.assertEqual(len(statuses), 2)

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
		frappe.delete_doc("LMS Quiz Submission", submission)

		doc = frappe.get_doc("LMS Homework Assignment", name)
		self.assertEqual(doc.status, "In Progress")
		self.assertTrue(any(row.event == "requirement_invalidated" for row in doc.history))

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
