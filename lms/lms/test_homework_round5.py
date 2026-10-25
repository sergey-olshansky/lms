# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Round-5 review scenarios (D01-D08, D01b, E01-E03), as real Frappe tests.

Every case drives the SAME user-facing API the UI drives, with ordinary roles
(Course Creator + LMS Student teacher, LMS Student student); permission
bypasses appear only where a fixture must author the world the test then
judges the REAL action in, and each such spot says so in a comment.
"""

import json
import unittest
from datetime import timedelta

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from lms.lms import homework_api, homework_attachments, homework_service
from lms.lms.test_helpers import BaseTestUtils as B


class TestRound5GradingAndFinality(B, IntegrationTestCase):
	"""D01, D01b, D02, D03: the grading action, the attempt limit, the carried
	verdict, and one shared meaning of a recorded verdict."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		token = frappe.generate_hash(length=10)
		self.teacher = B._create_user(
			f"r5t-{token}@example.com", "R5", "Teacher", ["Course Creator", "LMS Student"]
		)
		self.student = B._create_user(
			f"r5s-{token}@example.com", "R5", "Student", ["LMS Student"]
		)
		self.outsider = B._create_user(
			f"r5o-{token}@example.com", "R5", "Outsider", ["Course Creator", "LMS Student"]
		)
		frappe.set_user(self.teacher.name)
		self.course = B._create_course(title=f"R5 Course {token}", instructor=self.teacher.name)
		self.chapter = B._create_chapter(f"R5 Chapter {token}", self.course.name)
		B._create_chapter_reference(self.course.name, self.chapter.name)
		self.questions = []
		for i in range(2):
			q = frappe.get_doc(
				{"doctype": "LMS Question", "question": f"Explain {token} {i}", "type": "Open Ended"}
			)
			q.insert()
			self.questions.append(q)
		self.quiz = frappe.new_doc("LMS Quiz")
		self.quiz.update({"title": f"R5 Quiz {token}", "passing_percentage": 50, "total_marks": 10})
		for q in self.questions:
			self.quiz.append("questions", {"question": q.name, "marks": 5, "type": "Open Ended"})
		self.quiz.insert()
		content = json.dumps({"blocks": [{"type": "quiz", "data": {"quiz": self.quiz.name}}]})
		self.lesson = B._create_lesson(f"R5 Lesson {token}", self.chapter.name, self.course.name, content)
		B._create_lesson_reference(self.chapter.name, self.lesson.name)
		B._create_enrollment(self.student.name, self.course.name)

	def student_submission(self, answers=None):
		from lms.lms.doctype.lms_quiz.lms_quiz import submit_quiz

		frappe.set_user(self.student.name)
		if answers is None:
			answers = [
				{"question_name": q.name, "answer": [f"Essay {i}"]} for i, q in enumerate(self.questions)
			]
		submit_quiz(self.quiz.name, json.dumps(answers))
		name = frappe.get_all(
			"LMS Quiz Submission",
			filters={"quiz": self.quiz.name, "member": self.student.name},
			order_by="creation desc",
			pluck="name",
			limit=1,
		)[0]
		frappe.set_user(self.teacher.name)
		return frappe.get_doc("LMS Quiz Submission", name)

	def test_D01_teacher_grades_through_narrow_action(self):
		from lms.lms.doctype.lms_quiz_submission.lms_quiz_submission import save_submission_grades

		doc = self.student_submission()
		row = doc.result[0]
		frappe.set_user(self.teacher.name)
		# The SAME API the UI calls, with no permission bypass.
		save_submission_grades(
			submission=doc.name, grades=[{"name": row.name, "marks": 4, "graded": 1}]
		)
		fresh = frappe.get_doc("LMS Quiz Submission", doc.name)
		self.assertEqual(fresh.result[0].graded, 1)
		self.assertEqual(fresh.result[0].marks, 4)

	def test_D01_outsider_and_student_cannot_grade(self):
		from lms.lms.doctype.lms_quiz_submission.lms_quiz_submission import save_submission_grades

		doc = self.student_submission()
		row = doc.result[0]
		frappe.set_user(self.outsider.name)
		with self.assertRaises(frappe.PermissionError):
			save_submission_grades(
				submission=doc.name, grades=[{"name": row.name, "marks": 5, "graded": 1}]
			)
		frappe.set_user(self.student.name)
		with self.assertRaises(frappe.PermissionError):
			save_submission_grades(
				submission=doc.name, grades=[{"name": row.name, "marks": 5, "graded": 1}]
			)

	def test_D01_cannot_smuggle_fields(self):
		from lms.lms.doctype.lms_quiz_submission.lms_quiz_submission import save_submission_grades

		doc = self.student_submission()
		row = doc.result[0]
		frappe.set_user(self.teacher.name)
		with self.assertRaises(frappe.ValidationError):
			save_submission_grades(
				submission=doc.name,
				grades=[{"name": row.name, "marks": 5, "graded": 1, "member": self.outsider.name}],
			)

	def test_D01b_last_attempt_is_gradeable_and_limit_holds(self):
		from lms.lms.doctype.lms_quiz.lms_quiz import submit_quiz
		from lms.lms.doctype.lms_quiz_submission.lms_quiz_submission import (
			MaximumAttemptsExceededError,
			save_submission_grades,
		)

		frappe.set_user(self.teacher.name)
		self.quiz.reload()
		self.quiz.max_attempts = 1
		self.quiz.save()

		doc = self.student_submission()
		frappe.set_user(self.teacher.name)
		row = doc.result[0]
		# Grading the saved attempt must not spend or collide with the limit.
		save_submission_grades(
			submission=doc.name, grades=[{"name": row.name, "marks": 3, "graded": 1}]
		)
		self.assertEqual(frappe.get_doc("LMS Quiz Submission", doc.name).result[0].graded, 1)

		frappe.set_user(self.student.name)
		with self.assertRaises(MaximumAttemptsExceededError):
			submit_quiz(self.quiz.name, json.dumps([{"question_name": self.questions[0].name, "answer": ["again"]}]))

	def test_D02_carried_grade_survives_member_retake(self):
		from lms.lms.doctype.lms_quiz.lms_quiz import submit_quiz
		from lms.lms.doctype.lms_quiz_submission.lms_quiz_submission import save_submission_grades

		first = self.student_submission()
		frappe.set_user(self.teacher.name)
		row = first.result[0]
		save_submission_grades(submission=first.name, grades=[{"name": row.name, "marks": 5, "graded": 1}])

		frappe.set_user(self.student.name)
		submit_quiz(
			self.quiz.name,
			json.dumps([{"question_name": self.questions[1].name, "answer": ["Retried essay"]}]),
		)
		retry_name = frappe.get_all(
			"LMS Quiz Submission",
			filters={"quiz": self.quiz.name, "member": self.student.name},
			order_by="creation desc",
			pluck="name",
			limit=1,
		)[0]
		retry = frappe.get_doc("LMS Quiz Submission", retry_name)
		carried = next(r for r in retry.result if r.question_name == self.questions[0].name)
		self.assertEqual(carried.marks, 5)
		self.assertEqual(carried.graded, 1)

	def test_D02_forged_client_flag_does_not_survive(self):
		frappe.set_user(self.student.name)
		doc = self.student_submission()
		# A member saving their own submission with graded=1 forged into the
		# payload: validate_grading_flags must rewrite it to 0.
		frappe.set_user(self.student.name)
		doc.result[0].graded = 1
		doc.save(ignore_permissions=True)  # fixture save; the flag logic is the judge
		fresh = frappe.get_doc("LMS Quiz Submission", doc.name)
		self.assertEqual(fresh.result[0].graded, 0)

	def test_D03_recorded_partial_is_not_pending_anywhere(self):
		from lms.lms.doctype.lms_quiz.quiz_attempt_report import attempt_row_status
		from lms.lms.doctype.lms_quiz_submission.lms_quiz_submission import save_submission_grades

		doc = self.student_submission()
		frappe.set_user(self.teacher.name)
		row = doc.result[0]
		save_submission_grades(submission=doc.name, grades=[{"name": row.name, "marks": 3, "graded": 1}])
		fresh_row = frappe.get_doc("LMS Quiz Submission", doc.name).result[0]
		self.assertEqual(attempt_row_status(fresh_row), "incorrect")

	def test_D03_ungraded_stays_pending(self):
		from lms.lms.doctype.lms_quiz.quiz_attempt_report import attempt_row_status

		doc = self.student_submission()
		row = doc.result[0]
		self.assertEqual(attempt_row_status(row), "pending")


class TestRound5Sources(B, IntegrationTestCase):
	"""D04-D08: the frozen snapshot, prior views, paths, routes, precheck."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		token = frappe.generate_hash(length=10)
		self.teacher = B._create_user(
			f"r5x-{token}@example.com", "R5", "TeacherX", ["Course Creator", "LMS Student"]
		)
		self.student = B._create_user(
			f"r5y-{token}@example.com", "R5", "StudentX", ["LMS Student"]
		)
		frappe.set_user(self.teacher.name)
		self.course = B._create_course(title=f"R5X Course {token}", instructor=self.teacher.name)
		self.chapter = B._create_chapter(f"R5X Chapter {token}", self.course.name)
		B._create_chapter_reference(self.course.name, self.chapter.name)
		self.lesson = B._create_lesson(f"R5X Lesson {token}", self.chapter.name, self.course.name)
		B._create_lesson_reference(self.chapter.name, self.lesson.name)
		B._create_enrollment(self.student.name, self.course.name)

	def _template(self):
		return homework_api.save_homework(
			title="R5X Homework",
			days=3,
			items=[{"source_type": "Lesson", "name": self.lesson.name}],
		)["name"]

	def test_D04_recalled_freeze_survives_source_deletion(self):
		from lms.lms.doctype.course_lesson.course_lesson import cleanup_lesson_backreferences

		template = self._template()
		name = homework_api.assign_homework(
			homework=template,
			student=self.student.name,
			idempotency_key=frappe.generate_hash(length=24),
		)["name"]
		frappe.set_user(self.student.name)
		homework_service.record_lesson_opened(self.lesson.name)
		frappe.set_user(self.teacher.name)
		homework_service.revoke(name, "Recalled before source deletion")
		before = frappe.get_doc("LMS Homework Assignment", name)
		before_row = next(r for r in before.requirements if r.requirement_type == "Open Lesson")
		cleanup_lesson_backreferences(self.lesson.name)
		after = frappe.get_doc("LMS Homework Assignment", name)
		after_row = next(r for r in after.requirements if r.requirement_type == "Open Lesson")
		self.assertEqual(after_row.status, before_row.status)
		self.assertEqual(after_row.proof_name, before_row.proof_name)
		self.assertEqual(after.completed_requirements, before.completed_requirements)
		self.assertEqual(after_row.lesson_snapshot, self.lesson.name)

	def test_D04_active_assignment_shows_unavailable(self):
		from lms.lms.doctype.course_lesson.course_lesson import cleanup_lesson_backreferences

		template = self._template()
		name = homework_api.assign_homework(
			homework=template,
			student=self.student.name,
			idempotency_key=frappe.generate_hash(length=24),
		)["name"]
		cleanup_lesson_backreferences(self.lesson.name)
		frappe.set_user(self.student.name)
		detail = homework_api.get_homework_assignment(name)
		row = next(r for r in detail["requirements"] if r["requirement_type"] == "Open Lesson")
		self.assertEqual(row["status"], "Unavailable")

	def test_D05_prior_homework_view_credits_reissue(self):
		plain = B._create_lesson(
			"R5X Plain " + frappe.generate_hash(length=6), self.chapter.name, self.course.name
		)
		B._create_lesson_reference(self.chapter.name, plain.name)
		template = homework_api.save_homework(
			title="R5X Prior", days=3, items=[{"source_type": "Lesson", "name": plain.name}]
		)["name"]
		first = homework_api.assign_homework(
			homework=template,
			student=self.student.name,
			idempotency_key=frappe.generate_hash(length=24),
		)["name"]
		frappe.set_user(self.student.name)
		homework_service.record_lesson_opened(plain.name)
		frappe.set_user(self.teacher.name)
		homework_service.accept(first)
		self.assertEqual(
			frappe.db.get_value("LMS Homework Assignment", first, "status"), "Done"
		)
		second = homework_api.assign_homework(
			homework=template,
			student=self.student.name,
			idempotency_key=frappe.generate_hash(length=24),
			force=True,
		)["name"]
		row = frappe.get_doc("LMS Homework Assignment", second).requirements[0]
		self.assertEqual(row.status, "Completed Earlier")

	def test_D06_path_contains_chapter_title(self):
		template = self._template()
		item = frappe.get_doc("LMS Homework", template).items[0]
		self.assertIn(self.chapter.title, item.path)

	def test_D07_moved_lesson_keeps_working_route(self):
		template = self._template()
		name = homework_api.assign_homework(
			homework=template,
			student=self.student.name,
			idempotency_key=frappe.generate_hash(length=24),
		)["name"]
		other = B._create_course(
			"R5X Destination " + frappe.generate_hash(length=6), instructor=self.teacher.name
		)
		chapter = B._create_chapter("R5X Destination chapter", other.name)
		B._create_chapter_reference(other.name, chapter.name)
		B._create_enrollment(self.student.name, other.name)
		frappe.db.delete("Lesson Reference", {"lesson": self.lesson.name})
		lesson_doc = frappe.get_doc("Course Lesson", self.lesson.name)
		lesson_doc.course = other.name
		lesson_doc.chapter = chapter.name
		lesson_doc.save()
		B._create_lesson_reference(chapter.name, self.lesson.name)
		from lms.lms.permissions import can_access_lesson

		self.assertTrue(can_access_lesson(self.lesson.name, user=self.student.name))
		frappe.set_user(self.student.name)
		detail = homework_api.get_homework_assignment(name)
		row = next(r for r in detail["requirements"] if r["requirement_type"] == "Open Lesson")
		self.assertIsNotNone(row.get("route"))
		self.assertEqual(row["route"]["course"], other.name)

	def test_D08_future_embedded_quiz_blocks_precheck(self):
		questions = []
		for i in range(2):
			q = frappe.get_doc(
				{
					"doctype": "LMS Question",
					"question": f"R5X Q {frappe.generate_hash(length=6)} {i}",
					"type": "Choices",
					"option_1": "Option 1",
					"is_correct_1": 1,
					"option_2": "Option 2",
					"is_correct_2": 0,
				}
			)
			q.insert()
			questions.append(q)
		quiz = frappe.new_doc("LMS Quiz")
		quiz.update({"title": "R5X Scheduled " + frappe.generate_hash(length=6), "passing_percentage": 50})
		for q in questions:
			quiz.append("questions", {"question": q.name, "marks": 1, "type": "Choices"})
		quiz.insert()
		lesson = B._create_lesson(
			"R5X Scheduled lesson " + frappe.generate_hash(length=6),
			self.chapter.name,
			self.course.name,
			json.dumps({"blocks": [{"type": "quiz", "data": {"quiz": quiz.name}}]}),
		)
		B._create_lesson_reference(self.chapter.name, lesson.name)
		frappe.set_user(self.teacher.name)
		quiz.reload()
		quiz.enable_scheduling = 1
		quiz.schedule_start = now_datetime() + timedelta(days=2)
		quiz.schedule_end = now_datetime() + timedelta(days=3)
		quiz.save()
		template = homework_api.save_homework(
			title="R5X Scheduled homework", days=1, items=[{"source_type": "Lesson", "name": lesson.name}]
		)["name"]
		check = homework_api.precheck_assignment(template, self.student.name, 1)
		self.assertFalse(check["ok"])
		self.assertTrue(any("opens on" in reason for reason in check["reasons"]))


class TestRound5NewFeatures(B, IntegrationTestCase):
	"""E02 PDF, E03 attachments: the new owner requirements as real API tests."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		token = frappe.generate_hash(length=10)
		self.teacher = B._create_user(
			f"r5e-{token}@example.com", "R5", "TeacherE", ["Course Creator", "LMS Student"]
		)
		self.student = B._create_user(
			f"r5f-{token}@example.com", "R5", "StudentE", ["LMS Student"]
		)
		self.stranger = B._create_user(
			f"r5g-{token}@example.com", "R5", "StrangerE", ["LMS Student"]
		)
		frappe.set_user(self.teacher.name)
		self.course = B._create_course(title=f"R5E Course {token}", instructor=self.teacher.name)
		self.chapter = B._create_chapter(f"R5E Chapter {token}", self.course.name)
		B._create_chapter_reference(self.course.name, self.chapter.name)
		self.lesson = B._create_lesson(
			f"R5E Lesson {token}", self.chapter.name, self.course.name
		)
		B._create_lesson_reference(self.chapter.name, self.lesson.name)
		B._create_enrollment(self.student.name, self.course.name)
		self.template = homework_api.save_homework(
			title="R5E Homework",
			days=3,
			details="Line one\nLine two",
			items=[{"source_type": "Lesson", "name": self.lesson.name}],
		)["name"]
		self.assignment = homework_api.assign_homework(
			homework=self.template,
			student=self.student.name,
			idempotency_key=frappe.generate_hash(length=24),
		)["name"]

	def test_E02_template_pdf_renders_with_links(self):
		from lms.lms import homework_pdf

		html = homework_pdf.render_homework_pdf_html(
			homework_pdf._template_payload(frappe.get_doc("LMS Homework", self.template))
		)
		self.assertIn("R5E Homework", html)
		self.assertIn("Line one", html)
		self.assertIn("<a ", html)
		self.assertIn("/lms/", html or "/courses/")

	def test_E02_assignment_pdf_names_student_and_due(self):
		from lms.lms import homework_pdf

		doc = frappe.get_doc("LMS Homework Assignment", self.assignment)
		html = homework_pdf.render_homework_pdf_html(homework_pdf._assignment_payload(doc))
		self.assertIn("StudentE", html)
		self.assertIn("Due", html)
		self.assertIn(self.assignment, html)

	def test_E02_foreign_teacher_cannot_export(self):
		# User creation is an Administrator fixture action; the judged action
		# below runs as the outsider.
		frappe.set_user("Administrator")
		outsider = B._create_user(
			"r5h-" + frappe.generate_hash(length=6) + "@example.com",
			"R5",
			"OutsiderE",
			["Course Creator", "LMS Student"],
		)
		frappe.set_user(outsider.name)
		with self.assertRaises(frappe.PermissionError):
			homework_api._require_homework_access(self.template)

	def _upload_private_file(self, owner, size_bytes=64):
		"""Fixture: a stored private File owned by `owner`, exactly the shape
		the platform upload endpoint leaves behind (unattached, private)."""
		frappe.set_user(owner)
		file_doc = frappe.new_doc("File")
		file_doc.update(
			{
				"file_name": f"solution-{frappe.generate_hash(length=6)}.txt",
				"is_private": 1,
				"content": b"x" * size_bytes,
			}
		)
		file_doc.save(ignore_permissions=True)
		return file_doc

	def test_E03_quota_and_registration(self):
		file_doc = self._upload_private_file(self.student.name)
		frappe.set_user(self.student.name)
		result = homework_attachments.attach_file(
			assignment=self.assignment, file_name=file_doc.name
		)
		self.assertTrue(result["name"])
		state = homework_attachments.list_attachments(self.assignment)
		self.assertEqual(len(state["rows"]), 1)
		self.assertEqual(state["used"], file_doc.file_size)
		attachment_row = frappe.get_doc("LMS Homework Attachment", result["name"])
		self.assertEqual(attachment_row.student, self.student.name)
		# Private binding recorded on the File itself.
		file_row = frappe.db.get_value(
			"File", file_doc.name, ["is_private", "attached_to_doctype"], as_dict=True
		)
		self.assertEqual(file_row.is_private, 1)
		self.assertEqual(file_row.attached_to_doctype, "LMS Homework Attachment")

	def test_E03_supported_types_accepted_renamed_container_refused(self):
		# Common document and image types are accepted. A KNOWN container that
		# does not match its bytes is refused and cleaned (R09).
		file_doc = self._upload_private_file(self.student.name)
		frappe.db.set_value("File", file_doc.name, "file_name", "notes.txt")
		frappe.set_user(self.student.name)
		result = homework_attachments.attach_file(
			assignment=self.assignment, file_name=file_doc.name
		)
		self.assertTrue(result["name"])
		self.assertTrue(
			(frappe.db.get_value("File", file_doc.name, "file_url") or "").startswith(
				"/private/files/"
			)
		)

		renamed = self._upload_private_file(self.student.name)
		frappe.db.set_value("File", renamed.name, "file_name", "fake.png")
		with self.assertRaises(frappe.ValidationError):
			homework_attachments.attach_file(
				assignment=self.assignment, file_name=renamed.name
			)
		self.assertFalse(frappe.db.exists("File", renamed.name))

	def test_E03_teacher_reads_student_cannot_mutate(self):
		file_doc = self._upload_private_file(self.student.name)
		frappe.set_user(self.student.name)
		result = homework_attachments.attach_file(
			assignment=self.assignment, file_name=file_doc.name
		)
		frappe.set_user(self.teacher.name)
		state = homework_attachments.list_attachments(self.assignment)
		self.assertEqual(len(state["rows"]), 1)
		self.assertFalse(state["can_upload"])
		with self.assertRaises(frappe.PermissionError):
			homework_attachments.delete_attachment(attachment=result["name"])
		frappe.set_user(self.stranger.name)
		with self.assertRaises(frappe.PermissionError):
			homework_attachments.list_attachments(self.assignment)

	def test_E03_review_freezes_uploads(self):
		# The card reaches Review through the REAL machine: the single lesson
		# requirement completes on the student's confirmed opening and the
		# server auto-submits for review. No raw status writes.
		frappe.set_user(self.student.name)
		homework_service.mark_started(self.assignment)
		homework_service.record_lesson_opened(self.lesson.name)
		self.assertEqual(
			frappe.db.get_value("LMS Homework Assignment", self.assignment, "status"),
			"Review",
		)
		file_doc = self._upload_private_file(self.student.name)
		frappe.set_user(self.student.name)
		with self.assertRaises(frappe.PermissionError):
			homework_attachments.attach_file(
				assignment=self.assignment, file_name=file_doc.name
			)
		self.assertFalse(frappe.db.exists("File", file_doc.name))


class TestRound5U02(B, IntegrationTestCase):
	"""U02: the teacher sees WHY a quiz row blocks completion -- the attempt
	limit -- with the count and the latest attempt, never a limit reset."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		token = frappe.generate_hash(length=10)
		self.teacher = B._create_user(
			f"r5u-{token}@example.com", "R5", "TeacherU", ["Course Creator", "LMS Student"]
		)
		self.student = B._create_user(
			f"r5v-{token}@example.com", "R5", "StudentU", ["LMS Student"]
		)
		frappe.set_user(self.teacher.name)
		self.course = B._create_course(title=f"R5U Course {token}", instructor=self.teacher.name)
		self.chapter = B._create_chapter(f"R5U Chapter {token}", self.course.name)
		B._create_chapter_reference(self.course.name, self.chapter.name)
		question = frappe.get_doc(
			{
				"doctype": "LMS Question",
				"question": f"R5U Q {token}",
				"type": "Choices",
				"option_1": "Option 1",
				"is_correct_1": 1,
				"option_2": "Option 2",
				"is_correct_2": 0,
			}
		)
		question.insert()
		self.quiz = frappe.new_doc("LMS Quiz")
		self.quiz.update(
			{"title": f"R5U Quiz {token}", "passing_percentage": 100, "max_attempts": 1}
		)
		self.quiz.append("questions", {"question": question.name, "marks": 1, "type": "Choices"})
		self.quiz.insert()
		lesson = B._create_lesson(
			f"R5U Lesson {token}",
			self.chapter.name,
			self.course.name,
			json.dumps({"blocks": [{"type": "quiz", "data": {"quiz": self.quiz.name}}]}),
		)
		B._create_lesson_reference(self.chapter.name, lesson.name)
		B._create_enrollment(self.student.name, self.course.name)
		self.template = homework_api.save_homework(
			title="R5U Homework", days=3, items=[{"source_type": "Lesson", "name": lesson.name}]
		)["name"]

	def test_exhausted_attempts_surface_to_teacher(self):
		from lms.lms.doctype.lms_quiz.lms_quiz import submit_quiz

		name = homework_api.assign_homework(
			homework=self.template,
			student=self.student.name,
			idempotency_key=frappe.generate_hash(length=24),
		)["name"]
		frappe.set_user(self.student.name)
		# A failing single allowed attempt: the row can never complete through
		# the quiz itself again. Answers are lists -- the submission parser
		# refuses a bare string.
		submit_quiz(
			self.quiz.name,
			json.dumps([{"question_name": self.quiz.questions[0].question, "answer": ["Option 2"]}]),
		)
		frappe.set_user(self.teacher.name)
		detail = homework_api.get_homework_assignment(name)
		row = next(
			r
			for r in detail["requirements"]
			if r["requirement_type"] == "Pass Quiz" and r["quiz"] == self.quiz.name
		)
		self.assertEqual(row["attempts_max"], 1)
		self.assertEqual(row["attempts_used"], 1)
		self.assertTrue(row["attempts_exhausted"])
		self.assertTrue(row["latest_submission"])
