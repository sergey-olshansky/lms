# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Card #45 (batch + archive): the batch solution upload and the streamed
solution archive.

Batch contract: the uploader posts the picked files sequentially, ONE
request per file, so every per-file verdict stays atomic:
- a batch of several photos registers one by one, the cumulative quota sum
  re-checked under the same advisory lock for EVERY file;
- a mid-batch quota overflow refuses exactly the overflowing file with a
  cause-named verdict -- the files that already fit STAY registered;
- a failed file (renamed container, unsupported extension) refuses without
  an orphan and without touching the files registered before it.

Archive contract (``download_solution_archive``): one streamed zip of the
assignment's solution attachments for the assignment's student, its teacher
and privileged staff; entries are named ``<student_name>-<original
filename>``; the archive is a view over the quota-gated bytes, never a new
budget. The admin/teacher gallery renders from ``list_attachments`` -- the
same gate, so a non-privileged stranger gets PermissionError (HTTP 403).
"""

import io
import unittest
import zipfile

import frappe
from frappe.core.doctype.file.utils import get_safe_file_name
from frappe.tests import IntegrationTestCase

from lms.lms import homework_attachments
from lms.lms.test_helpers import BaseTestUtils as B
from lms.lms.test_homework_attach_hotfix import HotfixBase, _multipart

PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def _png(size: int, seed: bytes = b"t45") -> bytes:
	"""A declared PNG whose signature is real: the container check (R09)
	passes and the payload is deterministic for content comparison."""
	payload = (seed * (size // len(seed) + 1))[: max(0, size - len(PNG_HEADER))]
	return PNG_HEADER + payload


def _drain(response) -> bytes:
	return b"".join(response.response)


class TestBatchUpload(HotfixBase):
	def _upload(self, filename: str, content: bytes):
		with _multipart(filename, content) as _:
			return homework_attachments.upload_solution_file(assignment=self.assignment)

	def test_batch_of_photos_registers_one_by_one(self):
		"""Three photos picked together register as three atomic requests:
		each one re-reads the CURRENT quota sum under the advisory lock."""
		frappe.set_user(self.student.name)
		sizes = [2048, 4096, 1024]
		names = []
		for index, size in enumerate(sizes, start=1):
			result = self._upload(f"photo-{index}.png", _png(size, f"p{index}".encode()))
			names.append(result["name"])
			self.assertEqual(result["state"]["used"], sum(sizes[:index]))
			self.assertEqual(
				result["state"]["remaining"],
				homework_attachments.ATTACHMENT_QUOTA_BYTES - sum(sizes[:index]),
			)
		rows = frappe.get_all(
			"LMS Homework Attachment",
			filters={"assignment": self.assignment},
			fields=["name", "file_name", "file_size"],
			order_by="creation asc",
		)
		self.assertEqual([row.name for row in rows], names)
		self.assertEqual(sum(row.file_size for row in rows), sum(sizes))

	def test_mid_batch_quota_overflow_keeps_the_files_that_fit(self):
		"""The queue's first files fit and STAY; the overflowing file is
		refused with the cause-named cumulative verdict; nothing after it is
		forced through."""
		frappe.set_user("Administrator")
		# Pre-eat the quota until exactly two small photos fit: remaining =
		# f1 + f2 + 10, engineered so f1 and f2 fit and f3 overflows.
		f1, f2, f3 = 2048, 2048, 4096
		from lms.lms.test_homework_round6 import _file

		file_doc = _file(self.student.name)
		row = frappe.new_doc("LMS Homework Attachment")
		row.update(
			{
				"assignment": self.assignment,
				"student": self.student.name,
				"file": file_doc.name,
				"file_name": file_doc.file_name,
				"file_size": homework_attachments.ATTACHMENT_QUOTA_BYTES - (f1 + f2) - 10,
				"content_type": "text/plain",
			}
		)
		row.insert(ignore_permissions=True)

		frappe.set_user(self.student.name)
		files_before = frappe.db.count("File")
		self._upload("batch-1.png", _png(f1, b"a"))
		self._upload("batch-2.png", _png(f2, b"b"))
		with self.assertRaises(frappe.ValidationError) as caught:
			self._upload("batch-3.png", _png(f3, b"c"))
		# The cause-named verdict the UI surfaces for the overflowing file.
		self.assertIn("cannot exceed", str(caught.exception))
		self.assertIn("remaining", str(caught.exception))
		# The files that fit stayed (and stored exactly their own bytes); the
		# overflow stored nothing.
		self.assertEqual(
			frappe.db.count("LMS Homework Attachment", {"assignment": self.assignment}), 3
		)
		self.assertEqual(frappe.db.count("File"), files_before + 2)
		state = homework_attachments._public_state(self.assignment)
		self.assertEqual(state["remaining"], 10)

	def test_failed_file_reports_and_keeps_earlier_uploads(self):
		"""A bad file in the middle of a batch refuses alone: the earlier
		files stay registered, no orphan is stored, and a later good file can
		still be uploaded (the queue stops client-side, the server just
		refused the one file)."""
		frappe.set_user(self.student.name)
		files_before = frappe.db.count("File")
		self._upload("good-1.png", _png(1024, b"g1"))
		with self.assertRaises(frappe.ValidationError):
			self._upload("fake.jpg", b"<html><script>alert(1)</script></html>")
		with self.assertRaises(frappe.ValidationError):
			self._upload("evil.exe", b"MZ" + b"x" * 32)
		self._upload("good-2.png", _png(768, b"g2"))
		self.assertEqual(frappe.db.count("File"), files_before + 2)
		self.assertEqual(
			frappe.db.count("LMS Homework Attachment", {"assignment": self.assignment}), 2
		)
		self.assertEqual(
			homework_attachments._public_state(self.assignment)["used"], 1024 + 768
		)


class TestSolutionArchive(HotfixBase):
	def setUp(self):
		super().setUp()
		frappe.set_user(self.student.name)
		self.photos = {
			"page-1.png": _png(2048, b"one"),
			"page-2.png": _png(4096, b"two"),
		}
		for name, content in self.photos.items():
			with _multipart(name, content) as _:
				homework_attachments.upload_solution_file(assignment=self.assignment)

	def _full_name(self) -> str:
		return frappe.utils.get_fullname(self.student.name)

	def _zip_of(self, response) -> zipfile.ZipFile:
		data = _drain(response)
		self.assertTrue(data[:2] == b"PK")
		return zipfile.ZipFile(io.BytesIO(data))

	def test_archive_streams_for_the_assignment_student(self):
		response = homework_attachments.download_solution_archive(assignment=self.assignment)
		self.assertTrue(response.is_streamed)
		self.assertEqual(response.mimetype, "application/zip")
		self.assertIn("attachment", response.headers.get("Content-Disposition", ""))
		zf = self._zip_of(response)
		prefix = get_safe_file_name(f"{self._full_name()}-")
		self.assertEqual(len(zf.namelist()), 2)
		for name in zf.namelist():
			self.assertTrue(name.startswith(prefix))
		for original, content in self.photos.items():
			self.assertEqual(zf.read(f"{prefix}{original}"), content)

	def test_teacher_and_privileged_staff_download_too(self):
		frappe.set_user(self.teacher.name)
		zf = self._zip_of(
			homework_attachments.download_solution_archive(assignment=self.assignment)
		)
		self.assertEqual(len(zf.namelist()), 2)
		frappe.set_user("Administrator")
		zf = self._zip_of(
			homework_attachments.download_solution_archive(assignment=self.assignment)
		)
		self.assertEqual(len(zf.namelist()), 2)

	def test_non_assignment_user_gets_permission_error(self):
		stranger = B._create_user(
			f"t45s-{frappe.generate_hash(length=8)}@example.com", "T", "Stranger",
			["LMS Student"],
		)
		frappe.set_user(stranger.name)
		with self.assertRaises(frappe.PermissionError):
			homework_attachments.download_solution_archive(assignment=self.assignment)
		# The gallery's data source is gated the same way: the non-privileged
		# viewer of the admin scope gets 403 (PermissionError).
		with self.assertRaises(frappe.PermissionError):
			homework_attachments.list_attachments(assignment=self.assignment)

	def test_duplicate_names_disambiguate_in_the_archive(self):
		"""Defensive: every live transport uniquifies the STORED filename on a
		disk collision, so identical names reach the archive only through
		legacy/pre-existing rows (or a classic two-step registration). The
		entry namer still guarantees an extractor never sees two identical
		entry names."""
		frappe.set_user("Administrator")
		from lms.lms.test_homework_round6 import _file

		file_doc = _file(self.student.name)
		row = frappe.new_doc("LMS Homework Attachment")
		row.update(
			{
				"assignment": self.assignment,
				"student": self.student.name,
				"file": file_doc.name,
				"file_name": "page-1.png",
				"file_size": 512,
				"content_type": "image/png",
			}
		)
		row.insert(ignore_permissions=True)
		frappe.set_user(self.student.name)
		zf = self._zip_of(
				homework_attachments.download_solution_archive(assignment=self.assignment)
		)
		names = zf.namelist()
		self.assertEqual(len(names), 3)
		self.assertEqual(len(set(names)), 3)
		prefix = get_safe_file_name(f"{self._full_name()}-page-1.png")
		self.assertIn(prefix, names)
		self.assertIn(prefix.replace(".png", " (2).png"), names)
		# The uploaded photo keeps the plain name (creation order); the
		# legacy row carries the disambiguated entry with its own bytes.
		self.assertEqual(zf.read(prefix), self.photos["page-1.png"])

	def test_assignment_without_files_refuses_with_a_cause(self):
		assignment = _empty_assignment()
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError) as caught:
			homework_attachments.download_solution_archive(assignment=assignment)
		self.assertIn("no attached files", str(caught.exception))


def _empty_assignment() -> str:
	"""A second assignment with no solution files (the empty-archive case)."""
	from lms.lms import homework_api

	frappe.set_user("Administrator")
	token = frappe.generate_hash(length=8)
	teacher = B._create_user(
		f"t45t-{token}@example.com", "T", "Fourfive", ["Course Creator", "LMS Student"]
	)
	student = B._create_user(f"t45u-{token}@example.com", "U", "Fourfive", ["LMS Student"])
	frappe.set_user(teacher.name)
	course = B._create_course(title=f"T45 Course {token}", instructor=teacher.name)
	chapter = B._create_chapter(f"T45 ch {token}", course.name)
	B._create_chapter_reference(course.name, chapter.name)
	lesson = B._create_lesson(f"T45 lesson {token}", chapter.name, course.name)
	B._create_lesson_reference(chapter.name, lesson.name)
	B._create_enrollment(student.name, course.name)
	template = homework_api.save_homework(
		title=f"T45 hw {token}", days=3, items=[{"source_type": "Lesson", "name": lesson.name}]
	)["name"]
	return homework_api.assign_homework(
		homework=template,
		student=student.name,
		idempotency_key=frappe.generate_hash(length=24),
	)["name"]


if __name__ == "__main__":
	unittest.main()
