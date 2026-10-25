# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Template rules (task #35 spec 3.3, 8.1): field validation, drafts, dedupe,
copies, archive and delete-of-used. Matrix A04/A05/A07 (template half)."""

import frappe
from frappe.tests import IntegrationTestCase

from lms.lms import homework_api
from lms.lms.test_helpers import BaseTestUtils

LONG_DETAILS = (
	"Строка первая с переносами.\n" + "Вторая строка: " + "длинный текст " * 200 + "\n" + "Последняя строка."
)


class TestHomeworkTemplates(BaseTestUtils, IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.teacher = self._create_user(
			"hw-teacher@example.com", "Hana", "Teacher", ["Course Creator", "LMS Student"]
		)
		frappe.set_user(self.teacher.email)
		self.course = self._create_course(title="HW Template Course", instructor=self.teacher.email)

	def _lesson(self, title):
		chapter = self._create_chapter(f"Chapter for {title}", self.course.name)
		self._create_chapter_reference(self.course.name, chapter.name)
		lesson = self._create_lesson(title, chapter.name, self.course.name)
		self._create_lesson_reference(chapter.name, lesson.name)
		return lesson

	def _save(self, **kwargs):
		return homework_api.save_homework(
			name=kwargs.get("name"),
			title=kwargs.get("title", "Work"),
			days=kwargs.get("days", 7),
			details=kwargs.get("details"),
			group=kwargs.get("group"),
			items=kwargs.get("items", []),
		)

	def test_long_details_round_trip(self):
		lesson = self._lesson("Atomic structure")
		result = self._save(
			title="Week 1",
			days=3,
			details=LONG_DETAILS,
			items=[
				{
					"source_type": "Lesson",
					"name": lesson.name,
					"course": self.course.name,
					"title": lesson.title,
					"chapter": "",
					"path": f"Course / {lesson.title}",
				}
			],
		)
		stored = frappe.get_value("LMS Homework", result["name"], "details")
		self.assertEqual(stored, LONG_DETAILS)
		self.assertIn("\n", stored)

	def test_days_validation(self):
		# Fractional and non-numeric days are refused; on Frappe v17 the typed
		# API boundary raises FrappeTypeError before the handler body runs, on
		# older frameworks the handler's own validate_days_raw raises
		# ValidationError. Either way the raw value never becomes a silent 7.
		from frappe.exceptions import FrappeTypeError

		for bad in (0, -2, 100000):
			with self.subTest(days=bad):
				with self.assertRaises(frappe.ValidationError):
					self._save(days=bad)
		for bad in (2.5, "7.5"):
			with self.subTest(days=bad):
				with self.assertRaises((frappe.ValidationError, FrappeTypeError)):
					self._save(days=bad)

	def test_empty_draft_saved_and_flagged(self):
		result = self._save(title="Draft", items=[])
		row = frappe.get_doc("LMS Homework", result["name"])
		self.assertEqual(len(row.items), 0)

	def test_duplicate_items_deduped(self):
		lesson = self._lesson("Dedup lesson")
		entry = {
			"source_type": "Lesson",
			"name": lesson.name,
			"course": self.course.name,
			"title": lesson.title,
			"chapter": "",
			"path": lesson.title,
		}
		result = self._save(title="Dedup", items=[entry, dict(entry)])
		row = frappe.get_doc("LMS Homework", result["name"])
		self.assertEqual(len(row.items), 1)

	def test_resave_updates_no_duplicates(self):
		lesson = self._lesson("Resave lesson")
		entry = {
			"source_type": "Lesson",
			"name": lesson.name,
			"course": self.course.name,
			"title": lesson.title,
			"chapter": "",
			"path": lesson.title,
		}
		first = self._save(title="Resave", items=[entry])
		second = self._save(name=first["name"], title="Resave 2", days=5, items=[entry])
		self.assertEqual(first["name"], second["name"])
		self.assertEqual(frappe.db.count("LMS Homework Source", {"parent": first["name"]}), 1)

	def test_copy_keeps_sources_without_assignments(self):
		lesson = self._lesson("Copy lesson")
		entry = {
			"source_type": "Lesson",
			"name": lesson.name,
			"course": self.course.name,
			"title": lesson.title,
			"chapter": "",
			"path": lesson.title,
		}
		first = self._save(title="Original", items=[entry])
		copied = homework_api.copy_homework(first["name"])
		self.assertNotEqual(copied["name"], first["name"])
		row = frappe.get_doc("LMS Homework", copied["name"])
		self.assertEqual(len(row.items), 1)
		self.assertEqual(row.items[0].lesson, lesson.name)
		self.assertEqual(row.title, "Original (copy)")

	def test_delete_used_rejected_archive_ok(self):
		frappe.set_user("Administrator")
		student = self._create_user("hw-student-a@example.com", "Ann", "One", ["LMS Student"])
		frappe.set_user(self.teacher.email)
		lesson = self._lesson("Archive lesson")
		self._create_enrollment(student.email, self.course.name)
		entry = {
			"source_type": "Lesson",
			"name": lesson.name,
			"course": self.course.name,
			"title": lesson.title,
			"chapter": "",
			"path": lesson.title,
		}
		created = self._save(title="To archive", items=[entry])
		homework_api.assign_homework(
			homework=created["name"],
			student=student.email,
			idempotency_key="tpl-archive-key",
			force=True,
		)

		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("LMS Homework", created["name"])

		homework_api.archive_homework(created["name"], True)
		self.assertEqual(frappe.get_value("LMS Homework", created["name"], "archived"), 1)
		# The issued assignment survives archiving untouched.
		self.assertTrue(frappe.db.exists("LMS Homework Assignment", {"homework": created["name"]}))
