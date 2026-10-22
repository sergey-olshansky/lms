# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Round-10 regressions: the five post-round-9 fixes -- an opening of an
already-credited material starts the card, the PDF embeds private detail
images from the authorized sets, the teacher overview filters/blocks/counts
server-side, and detail-image cleanup keeps bytes another row still needs.
"""

import json
import unittest

import frappe
from frappe.tests import IntegrationTestCase

from lms.lms import homework_api, homework_attachments, homework_materials, homework_service
from lms.lms.test_helpers import BaseTestUtils as B


def _file(owner, *, private=True, filename=None, content=None):
	frappe.set_user(owner)
	doc = frappe.new_doc("File")
	doc.update(
		{
			"file_name": filename or ("r10-" + frappe.generate_hash(length=8) + ".png"),
			"is_private": int(private),
			"content": content
			or (bytes([137, 80, 78, 71, 13, 10, 26, 10]) + frappe.generate_hash(length=16).encode()),
		}
	)
	doc.save(ignore_permissions=True)
	return doc


class Round10Base(B, IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		token = frappe.generate_hash(length=10)
		self.teacher = B._create_user(
			f"rtent-{token}@example.com", "R", "Ten", ["Course Creator", "LMS Student"]
		)
		self.student = B._create_user(
			f"rten-{token}@example.com", "R", "Stud", ["LMS Student"]
		)
		self.outsider = B._create_user(
			f"rteno-{token}@example.com", "R", "Other", ["Course Creator", "LMS Student"]
		)
		frappe.set_user(self.teacher.name)
		self.course = B._create_course(title=f"R10 Course {token}", instructor=self.teacher.name)
		self.chapter = B._create_chapter(f"R10 ch {token}", self.course.name)
		B._create_chapter_reference(self.course.name, self.chapter.name)
		self.lesson = B._create_lesson(f"R10 lesson {token}", self.chapter.name, self.course.name)
		B._create_lesson_reference(self.chapter.name, self.lesson.name)
		B._create_enrollment(self.student.name, self.course.name)


class TestRound10CreditedOpeningStarts(Round10Base):
	"""Fix 1: opening a material the card already credits still STARTS a
	never-opened card (a fully pre-credited To Do work used to ignore the
	student's real first visit because every row was already Completed)."""

	def test_opening_credited_material_starts_todo_card(self):
		template = homework_api.save_homework(
			title="R10 prior", days=3, items=[{"source_type": "Lesson", "name": self.lesson.name}]
		)["name"]
		assignment = homework_api.assign_homework(
			homework=template, student=self.student.name,
			idempotency_key=frappe.generate_hash(24),
		)["name"]
		# Credit the row out-of-band ("Completed Earlier"): prior credit that
		# arrives with the issue itself.
		frappe.db.set_value(
			"LMS Homework Requirement",
			{"parent": assignment, "lesson": self.lesson.name},
			{"status": "Completed Earlier"},
		)
		frappe.set_user(self.student.name)
		# The student really opens the lesson. Before the fix this opening was
		# ignored (every row already credited) and the card sat in To Do
		# forever; now the start is RECORDED and, per A21, the fully
		# pre-credited card continues straight through to Review.
		homework_service.record_lesson_opened(self.lesson.name)
		doc = frappe.get_doc("LMS Homework Assignment", assignment)
		self.assertEqual(doc.status, "Review")
		self.assertTrue(doc.first_opened_at)
		events = [row.event for row in doc.history]
		self.assertEqual(events.count("started"), 1)
		self.assertIn("submitted_for_review", events)
		# A repeat opening neither re-credits nor duplicates the audit rows.
		homework_service.record_lesson_opened(self.lesson.name)
		fresh = frappe.get_doc("LMS Homework Assignment", assignment)
		self.assertEqual([row.event for row in fresh.history].count("started"), 1)
		self.assertEqual(fresh.status, "Review")

	def test_opening_irrelevant_material_still_ignored(self):
		template = homework_api.save_homework(
			title="R10 other", days=3, items=[{"source_type": "Lesson", "name": self.lesson.name}]
		)["name"]
		assignment = homework_api.assign_homework(
			homework=template, student=self.student.name,
			idempotency_key=frappe.generate_hash(24),
		)["name"]
		frappe.set_user(self.teacher.name)
		stranger = B._create_lesson("R10 stranger", self.chapter.name, self.course.name)
		B._create_lesson_reference(self.chapter.name, stranger.name)
		frappe.set_user(self.student.name)
		homework_service.record_lesson_opened(stranger.name)
		doc = frappe.get_doc("LMS Homework Assignment", assignment)
		# The unrelated opening never starts or moves the card.
		self.assertEqual(doc.status, "To Do")
		self.assertFalse(doc.first_opened_at)
		self.assertFalse([row for row in doc.history if row.event == "started"])


class TestRound10PdfPrivateDetailImages(Round10Base):
	"""Fix 2: private detail images are INLINED into the PDF from the files in
	the authorized template/assignment set -- the PDF reader has no session,
	/private/files URLs would render broken."""

	def _template_with_image(self):
		image = _file(self.teacher.name)
		details = f'<p>Состав работы</p><p><img src="{image.file_url}"></p>'
		frappe.set_user(self.teacher.name)
		template = homework_api.save_homework(
			title="R10 picture work", days=3,
			items=[{"source_type": "Lesson", "name": self.lesson.name}],
			details=details,
		)["name"]
		return template, image

	def test_template_pdf_inlines_the_private_image(self):
		from lms.lms import homework_pdf

		template, image = self._template_with_image()
		doc = frappe.get_doc("LMS Homework", template)
		html = homework_pdf.render_homework_pdf_html(homework_pdf._template_payload(doc))
		self.assertIn("data:image/png;base64,", html)
		self.assertNotIn(image.file_url, html)

	def test_assignment_pdf_inlines_from_the_frozen_snapshot(self):
		from lms.lms import homework_pdf

		template, image = self._template_with_image()
		assignment = homework_api.assign_homework(
			homework=template, student=self.student.name,
			idempotency_key=frappe.generate_hash(24),
		)["name"]
		doc = frappe.get_doc("LMS Homework Assignment", assignment)
		html = homework_pdf.render_homework_pdf_html(homework_pdf._assignment_payload(doc))
		self.assertIn("data:image/png;base64,", html)
		self.assertNotIn(image.file_url, html)


class TestRound10Overview(Round10Base):
	"""Fix 4: server-side student/course filters, filter-respecting counts,
	and a human blocking reason per row; the teacher scope never widens."""

	def _issue(self, student, title):
		template = homework_api.save_homework(
			title=title, days=3, items=[{"source_type": "Lesson", "name": self.lesson.name}]
		)["name"]
		return homework_api.assign_homework(
			homework=template, student=student,
			idempotency_key=frappe.generate_hash(24),
		)["name"]

	def test_filters_counts_and_reasons(self):
		# User creation is an Administrator fixture action.
		frappe.set_user("Administrator")
		other_student = B._create_user(
			"rten-x@example.com", "R", "Second", ["LMS Student"]
		)
		frappe.set_user(self.teacher.name)
		B._create_enrollment(other_student.name, self.course.name)
		first = self._issue(self.student.name, "R10 one")
		second = self._issue(other_student.name, "R10 two")

		frappe.set_user(self.teacher.name)
		by_student = homework_api.get_homework_overview(student=self.student.name)
		names = {row["name"] for row in by_student["rows"]}
		self.assertEqual(names, {first})
		self.assertEqual(by_student["total"], 1)
		# Counts respect the SAME filter: one card, in To Do.
		self.assertEqual(by_student["counts"]["To Do"], 1)
		self.assertEqual(by_student["counts"]["In Progress"], 0)

		by_course = homework_api.get_homework_overview(course=self.course.name)
		self.assertEqual({row["name"] for row in by_course["rows"]}, {first, second})
		self.assertEqual(by_course["total"], 2)

		# Blocking reasons: an untouched To Do card names its unfinished
		# requirement -- more useful than the bare "not opened" state.
		reasons = {row["name"]: row["blocking_reason"] for row in by_course["rows"]}
		self.assertIn("Not done", reasons[first])
		self.assertIn("R10 lesson", reasons[first])

		# After the student opens the (quiz-less) lesson everything completes
		# and auto-submits; the reason becomes the review wait.
		frappe.set_user(self.student.name)
		homework_service.record_lesson_opened(self.lesson.name)
		frappe.set_user(self.teacher.name)
		refreshed = homework_api.get_homework_overview(student=self.student.name)
		row = refreshed["rows"][0]
		self.assertEqual(row["status"], "Review")
		self.assertEqual(row["blocking_reason"], "Waiting for teacher review")

	def test_teacher_scope_never_widens(self):
		frappe.set_user(self.teacher.name)
		mine = self._issue(self.student.name, "R10 mine")
		frappe.set_user("Administrator")
		foreign = B._create_user(
			"rten-f@example.com", "F", "Teacher", ["Course Creator", "LMS Student"]
		)
		frappe.set_user(foreign.name)
		foreign_course = B._create_course(title="R10 foreign", instructor=foreign.name)
		foreign_chapter = B._create_chapter("F ch", foreign_course.name)
		B._create_chapter_reference(foreign_course.name, foreign_chapter.name)
		foreign_lesson = B._create_lesson("F lesson", foreign_chapter.name, foreign_course.name)
		B._create_lesson_reference(foreign_chapter.name, foreign_lesson.name)
		B._create_enrollment(self.student.name, foreign_course.name)
		foreign_template = homework_api.save_homework(
			title="R10 foreign work", days=3,
			items=[{"source_type": "Lesson", "name": foreign_lesson.name}],
		)["name"]
		foreign_assignment = homework_api.assign_homework(
			homework=foreign_template, student=self.student.name,
			idempotency_key=frappe.generate_hash(24),
		)["name"]

		# The outsider teacher sees only their OWN card, never mine.
		frappe.set_user(foreign.name)
		view = homework_api.get_homework_overview(student=self.student.name)
		self.assertEqual({row["name"] for row in view["rows"]}, {foreign_assignment})
		self.assertNotIn(mine, {row["name"] for row in view["rows"]})
		# A plain student never sees the overview at all.
		frappe.set_user(self.student.name)
		with self.assertRaises(frappe.PermissionError):
			homework_api.get_homework_overview()


class TestRound10DetailImageCleanup(Round10Base):
	"""Fix 5: dropping an image reference from the details removes the row but
	keeps the bytes while an issued snapshot still needs them; the bytes go
	only when nothing references them anymore."""

	def test_bytes_survive_while_snapshot_references(self):
		frappe.set_user(self.teacher.name)
		image = _file(self.teacher.name)
		details = f'<p><img src="{image.file_url}"></p>'
		template = homework_api.save_homework(
			title="R10 cleanup", days=3,
			items=[{"source_type": "Lesson", "name": self.lesson.name}],
			details=details,
		)["name"]
		assignment = homework_api.assign_homework(
			homework=template, student=self.student.name,
			idempotency_key=frappe.generate_hash(24),
		)["name"]
		self.assertTrue(
			frappe.db.exists(
				"LMS Homework Assignment Material", {"parent": assignment, "file": image.name}
			)
		)
		# The teacher drops the image from the description.
		homework_api.save_homework(
			name=template, title="R10 cleanup", days=3,
			items=[{"source_type": "Lesson", "name": self.lesson.name}],
			details="<p>Без картинки</p>",
		)
		self.assertFalse(
			frappe.db.exists("LMS Homework Material", {"parent": template, "file": image.name})
		)
		# The snapshot still references the file: the bytes stay.
		self.assertTrue(frappe.db.exists("File", image.name))
		self.assertTrue(
			frappe.db.exists(
				"LMS Homework Assignment Material", {"parent": assignment, "file": image.name}
			)
		)

	def test_bytes_deleted_when_nothing_references(self):
		frappe.set_user(self.teacher.name)
		image = _file(self.teacher.name)
		template = homework_api.save_homework(
			title="R10 gone", days=3,
			items=[{"source_type": "Lesson", "name": self.lesson.name}],
			details=f'<p><img src="{image.file_url}"></p>',
		)["name"]
		self.assertTrue(frappe.db.exists("File", image.name))
		homework_api.save_homework(
			name=template, title="R10 gone", days=3,
			items=[{"source_type": "Lesson", "name": self.lesson.name}],
			details="<p>Без картинки</p>",
		)
		self.assertFalse(frappe.db.exists("File", image.name))
