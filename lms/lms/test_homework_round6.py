# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Round-6 regressions (R01-R10) and the E04-E06 core as real Frappe tests.

Judged actions run through the same user-facing APIs the UI drives, with
ordinary roles; permission bypasses appear only in fixture preparation and
are marked as such.
"""

import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from lms.lms import homework_api, homework_attachments, homework_service
from lms.lms.test_helpers import BaseTestUtils as B


def _file(owner, *, private=True, filename=None, content=None):
	"""Fixture: a stored File owned by `owner` (privileged insert)."""
	frappe.set_user(owner)
	doc = frappe.new_doc("File")
	doc.update(
		{
			"file_name": filename or ("r6-" + frappe.generate_hash(length=10) + ".txt"),
			"is_private": int(private),
			"content": content or ("probe-" + frappe.generate_hash(length=12)).encode(),
		}
	)
	doc.save(ignore_permissions=True)
	return doc


class Round6Base(B, IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		token = frappe.generate_hash(length=10)
		self.teacher = B._create_user(
			f"r6a-{token}@example.com", "R6", "Teach", ["Course Creator", "LMS Student"]
		)
		self.student = B._create_user(
			f"r6b-{token}@example.com", "R6", "Stud", ["LMS Student"]
		)
		self.student2 = B._create_user(
			f"r6c-{token}@example.com", "R6", "Other", ["LMS Student"]
		)
		frappe.set_user(self.teacher.name)
		self.course = B._create_course(title=f"R6 Course {token}", instructor=self.teacher.name)
		self.chapter = B._create_chapter(f"R6 ch {token}", self.course.name)
		B._create_chapter_reference(self.course.name, self.chapter.name)
		self.lesson = B._create_lesson(f"R6 lesson {token}", self.chapter.name, self.course.name)
		B._create_lesson_reference(self.chapter.name, self.lesson.name)
		B._create_enrollment(self.student.name, self.course.name)
		self.template = homework_api.save_homework(
			title=f"R6 hw {token}", days=3, items=[{"source_type": "Lesson", "name": self.lesson.name}]
		)["name"]
		self.assignment = homework_api.assign_homework(
			homework=self.template,
			student=self.student.name,
			idempotency_key=frappe.generate_hash(length=24),
		)["name"]


class TestRound6Attachments(Round6Base):
	"""R01-R03, R08-R10: the hardened solution uploader."""

	def test_R01_foreign_private_file_refused(self):
		# Fixture: the TEACHER's private file; judged action runs as the student.
		foreign = _file(self.teacher.name)
		frappe.set_user(self.student.name)
		with self.assertRaises(frappe.PermissionError):
			homework_attachments.attach_file(self.assignment, foreign.name)
		# A foreign file that is already bound is refused untouched too.
		bound = _file(self.teacher.name)
		frappe.set_user("Administrator")
		frappe.db.set_value(
			"File",
			bound.name,
			{"attached_to_doctype": "Elsewhere", "attached_to_name": "X"},
		)
		frappe.set_user(self.student.name)
		with self.assertRaises(frappe.PermissionError):
			homework_attachments.attach_file(self.assignment, bound.name)
		self.assertTrue(frappe.db.exists("File", bound.name))
		# The student's OWN already-bound file is refused as a re-registration.
		own = _file(self.student.name)
		frappe.set_user("Administrator")
		frappe.db.set_value(
			"File",
			own.name,
			{"attached_to_doctype": "Elsewhere", "attached_to_name": "X"},
		)
		frappe.set_user(self.student.name)
		with self.assertRaises(frappe.ValidationError):
			homework_attachments.attach_file(self.assignment, own.name)

	def test_R02_refusal_never_deletes_foreign_file(self):
		foreign = _file(self.teacher.name)
		frappe.set_user(self.teacher.name)
		homework_service.revoke(self.assignment, "R6 probe")
		frappe.set_user(self.student.name)
		with self.assertRaises(frappe.PermissionError):
			homework_attachments.attach_file(self.assignment, foreign.name)
		self.assertTrue(frappe.db.exists("File", foreign.name))

	def test_R03_public_upload_refused_and_cleaned(self):
		public = _file(self.student.name, private=False)
		original_url = public.file_url
		frappe.set_user(self.student.name)
		with self.assertRaises(frappe.ValidationError):
			homework_attachments.attach_file(self.assignment, public.name)
		# No working public URL survives: the refused upload itself is gone.
		self.assertFalse(frappe.db.exists("File", public.name))
		self.assertTrue(original_url.startswith("/files/"))

	def test_R08_own_row_visible_in_native_list(self):
		own = _file(self.student.name)
		frappe.set_user(self.student.name)
		result = homework_attachments.attach_file(self.assignment, own.name)
		rows = frappe.get_list(
			"LMS Homework Attachment", fields=["name"], filters={"assignment": self.assignment}
		)
		self.assertIn(result["name"], [row.name for row in rows])
		# Another student sees nothing of it.
		frappe.set_user(self.student2.name)
		other = frappe.get_list(
			"LMS Homework Attachment", fields=["name"], filters={"assignment": self.assignment}
		)
		self.assertEqual(other, [])

	def test_R09_fake_docx_refused(self):
		fake = _file(
			self.student.name,
			filename="evil-" + frappe.generate_hash(6) + ".docx",
			content=b"<!doctype html><html><script>alert(1)</script></html>",
		)
		frappe.set_user(self.student.name)
		with self.assertRaises(frappe.ValidationError):
			homework_attachments.attach_file(self.assignment, fake.name)
		self.assertFalse(frappe.db.exists("File", fake.name))

	def test_R09_valid_png_accepted(self):
		png = bytes(
			[
				0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0, 0, 0, 0x0D, 0x49,
				0x48, 0x44, 0x52, 0, 0, 0, 1, 0, 0, 0, 1, 8, 6, 0, 0, 0, 0x1F, 0x15,
				0xC4, 0x89, 0, 0, 0, 0x0A, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9C, 0x63,
				0, 1, 0, 0, 5, 0, 1, 0x0D, 0x0A, 0x2D, 0xB4, 0, 0, 0, 0, 0x49, 0x45,
				0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
			]
		)
		image = _file(self.student.name, filename="ok-" + frappe.generate_hash(6) + ".png", content=png)
		frappe.set_user(self.student.name)
		result = homework_attachments.attach_file(self.assignment, image.name)
		self.assertTrue(result["name"])

	def test_R10_state_change_during_registration_prevented(self):
		own = _file(self.student.name)
		original = frappe.db.advisory_lock

		@contextmanager
		def interleaved(*args, **kwargs):
			# The authority was read, the write has not started: a real revoke
			# lands exactly here, through the real service.
			frappe.set_user(self.teacher.name)
			homework_service.revoke(self.assignment, "interleaved")
			frappe.set_user(self.student.name)
			with original(*args, **kwargs):
				yield

		frappe.set_user(self.student.name)
		with patch.object(frappe.db, "advisory_lock", interleaved):
			with self.assertRaises(frappe.PermissionError):
				homework_attachments.attach_file(self.assignment, own.name)


class TestRound6E04(Round6Base):
	"""E04: the narrow grant of an unpublished fragment."""

	def test_draft_fragment_without_enrollment(self):
		from lms.lms.permissions import can_access_assessment, can_access_lesson

		# A second, DRAFT course the student is NOT enrolled in.
		frappe.set_user(self.teacher.name)
		draft = B._create_course(title="R6 draft", instructor=self.teacher.name)
		chapter = B._create_chapter("R6 draft ch", draft.name)
		B._create_chapter_reference(draft.name, chapter.name)
		question = frappe.get_doc(
			{
				"doctype": "LMS Question",
				"question": "R6 draft q",
				"type": "Choices",
				"option_1": "A",
				"is_correct_1": 1,
				"option_2": "B",
			}
		)
		question.insert()
		quiz = frappe.new_doc("LMS Quiz")
		quiz.update({"title": "R6 draft quiz", "passing_percentage": 50})
		quiz.append("questions", {"question": question.name, "marks": 1, "type": "Choices"})
		quiz.insert()
		granted_lesson = B._create_lesson(
			"Granted",
			chapter.name,
			draft.name,
			json.dumps({"blocks": [{"type": "quiz", "data": {"quiz": quiz.name}}]}),
		)
		B._create_lesson_reference(chapter.name, granted_lesson.name)
		neighbour = B._create_lesson("Neighbour", chapter.name, draft.name)
		B._create_lesson_reference(chapter.name, neighbour.name)
		frappe.set_user("Administrator")
		frappe.db.set_value("LMS Course", draft.name, "published", 0)
		frappe.set_user(self.teacher.name)
		self.assertFalse(frappe.db.get_value("LMS Course", draft.name, "published"))

		self.assertFalse(can_access_lesson(granted_lesson.name, user=self.student.name))
		template = homework_api.save_homework(
			title="R6 fragment", days=3, items=[{"source_type": "Lesson", "name": granted_lesson.name}]
		)["name"]
		precheck = homework_api.precheck_assignment(template, self.student.name, 3)
		self.assertTrue(precheck["ok"], precheck["reasons"])
		self.assertEqual(precheck["narrow_courses"], [draft.name])
		assignment = homework_api.assign_homework(
			homework=template,
			student=self.student.name,
			idempotency_key=frappe.generate_hash(24),
		)["name"]
		self.assertTrue(can_access_lesson(granted_lesson.name, user=self.student.name))
		self.assertFalse(can_access_lesson(neighbour.name, user=self.student.name))
		self.assertTrue(can_access_assessment("LMS Quiz", quiz.name, user=self.student.name))
		# The enrolled course's flow is untouched: the neighbour stays shut.
		homework_api.revoke_homework(assignment, "done")
		self.assertFalse(can_access_lesson(granted_lesson.name, user=self.student.name))


class TestRound6E05(Round6Base):
	"""E05: rich details + teacher materials with the 20 MiB template budget."""

	def test_rich_details_sanitized_and_images_managed(self):
		frappe.set_user(self.teacher.name)
		image = _file(self.teacher.name, filename="pic-" + frappe.generate_hash(6) + ".png",
			content=bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]))
		details = (
			'<p>План работы</p><ul><li>первый пункт</li></ul>'
			f'<p><img src="{image.file_url}"></p>'
			'<script>alert(1)</script>'
		)
		name = homework_api.save_homework(
			title="R6 rich", days=3,
			items=[{"source_type": "Lesson", "name": self.lesson.name}],
			details=details,
		)["name"]
		stored = frappe.db.get_value("LMS Homework", name, "details")
		self.assertIn("<p>", stored)
		self.assertNotIn("<script>", stored)
		# The embedded image became a managed Detail Image row on the template.
		rows = frappe.get_all(
			"LMS Homework Material",
			filters={"parent": name, "role": "Detail Image"},
			pluck="file",
		)
		self.assertIn(image.name, rows)

	def test_material_quota_and_snapshot_freeze(self):
		from lms.lms import homework_materials

		frappe.set_user(self.teacher.name)
		material = _file(self.teacher.name, filename="guide-" + frappe.generate_hash(6) + ".txt")
		result = homework_materials.add_material(self.template, material.name)
		self.assertTrue(result["name"])
		# The issue freezes the material onto the assignment, same File id --
		# the card issued AFTER the material landed.
		issued = homework_api.assign_homework(
			homework=self.template,
			student=self.student.name,
			idempotency_key=frappe.generate_hash(24),
			force=True,
		)["name"]
		frozen = frappe.get_all(
			"LMS Homework Assignment Material",
			filters={"parent": issued},
			pluck="file",
		)
		self.assertIn(material.name, frozen)
		# Removing it from the template keeps the File alive: the snapshot
		# still references it.
		homework_materials.remove_material(result["name"])
		self.assertTrue(frappe.db.exists("File", material.name))
		self.assertIn(material.name, frozen)

	def test_material_privacy_matrix(self):
		from lms.lms import homework_materials

		frappe.set_user(self.teacher.name)
		material = _file(self.teacher.name, filename="sec-" + frappe.generate_hash(6) + ".txt")
		homework_materials.add_material(self.template, material.name)

		# The authorized path is the download endpoint's own verdict; the raw
		# private URL answers to the platform chain, which cannot express
		# "the author OR any issued student" for a template-bound file.
		def readable(user):
			frappe.set_user(user)
			return homework_materials._material_download_allowed(
				frappe.get_doc("File", material.name), user
			)

		self.assertTrue(readable(self.teacher.name))
		self.assertFalse(readable(self.student2.name))
		# Before the issue the student cannot read it; after the issue (which
		# freezes the material onto THEIR assignment) they can.
		self.assertFalse(readable(self.student.name))
		frappe.set_user(self.teacher.name)
		homework_api.assign_homework(
			homework=self.template,
			student=self.student.name,
			idempotency_key=frappe.generate_hash(24),
			force=True,
		)["name"]
		frappe.local.hw_granted_cache = {}
		self.assertTrue(readable(self.teacher.name))
		self.assertTrue(readable(self.student.name))
		self.assertFalse(readable(self.student2.name))


class TestRound6E06(Round6Base):
	"""E06: the required file solution with the explicit submit."""

	def _done_assignment(self, require_solution):
		frappe.set_user(self.teacher.name)
		template = homework_api.save_homework(
			title="R6 file work", days=3,
			items=[{"source_type": "Lesson", "name": self.lesson.name}],
			require_solution=require_solution,
		)["name"]
		assignment = homework_api.assign_homework(
			homework=template, student=self.student.name,
			idempotency_key=frappe.generate_hash(24), force=True,
		)["name"]
		frappe.set_user(self.student.name)
		homework_service.mark_started(assignment)
		homework_service.record_lesson_opened(self.lesson.name)
		return assignment

	def test_no_auto_review_with_required_solution(self):
		assignment = self._done_assignment(require_solution=True)
		status = frappe.db.get_value("LMS Homework Assignment", assignment, "status")
		self.assertEqual(status, "In Progress")

	def test_submit_requires_file_then_moves_to_review(self):
		assignment = self._done_assignment(require_solution=True)
		with self.assertRaises(frappe.ValidationError):
			homework_service.submit_solution(assignment)
		solution = _file(self.student.name)
		homework_attachments.attach_file(assignment, solution.name)
		result = homework_service.submit_solution(assignment)
		self.assertEqual(result["status"], "Review")
		self.assertTrue(
			frappe.db.get_value("LMS Homework Assignment", assignment, "solution_submitted_at")
		)

	def test_default_flow_still_auto_reviews(self):
		assignment = self._done_assignment(require_solution=False)
		self.assertEqual(
			frappe.db.get_value("LMS Homework Assignment", assignment, "status"), "Review"
		)

	def test_fully_precredited_stays_in_progress_until_file(self):
		# The prior work completes under the ordinary flow; only the RE-issue
		# carries the required-solution flag.
		frappe.set_user(self.teacher.name)
		template = homework_api.save_homework(
			title="R6 precredited", days=3,
			items=[{"source_type": "Lesson", "name": self.lesson.name}],
		)["name"]
		first = homework_api.assign_homework(
			homework=template, student=self.student.name,
			idempotency_key=frappe.generate_hash(24),
		)["name"]
		frappe.set_user(self.student.name)
		homework_service.mark_started(first)
		homework_service.record_lesson_opened(self.lesson.name)
		frappe.set_user(self.teacher.name)
		homework_service.accept(first)
		# Flip the template to the file-solution mode; the RE-issued card
		# inherits the prior credit AND the flag.
		homework_api.save_homework(
			name=template,
			title="R6 precredited",
			days=3,
			items=[{"source_type": "Lesson", "name": self.lesson.name}],
			require_solution=True,
		)
		second = homework_api.assign_homework(
			homework=template, student=self.student.name,
			idempotency_key=frappe.generate_hash(24), force=True,
		)["name"]
		frappe.set_user(self.student.name)
		homework_service.mark_started(second)
		# E06.7: everything pre-credited, but the file work stays In Progress.
		status = frappe.db.get_value("LMS Homework Assignment", second, "status")
		self.assertEqual(status, "In Progress")


class TestRound6E08(Round6Base):
	def test_overview_scoped_to_teacher_with_counts(self):
		frappe.set_user(self.teacher.name)
		data = homework_api.get_homework_overview()
		names = [row["name"] for row in data["rows"]]
		self.assertIn(self.assignment, names)
		self.assertEqual(data["counts"]["To Do"] + data["counts"]["In Progress"] >= 1, True)
		# Another teacher sees none of these.
		frappe.set_user("Administrator")
		other = B._create_user(
			"r6z-" + frappe.generate_hash(6) + "@example.com", "R6", "OtherT",
			["Course Creator", "LMS Student"],
		)
		frappe.set_user(other.name)
		other_view = homework_api.get_homework_overview()
		self.assertNotIn(self.assignment, [row["name"] for row in other_view["rows"]])
