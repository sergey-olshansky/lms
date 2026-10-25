# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Hotfix 2026-10-25 (first production release of task #35): on the released
site every solution upload succeeded (HTTP 200, File stored) yet the
follow-up registration request never left the browser, so nothing attached;
homework solutions accept common image, document, PDF, and text formats.

Covers the new contract:
- upload_solution_file: the ONE-request transport (multipart bytes straight
  to the homework endpoint) -- supported image/document formats, private storage + quota/state
  verdict + binding in a single transaction, no orphan upload on a refusal,
  no dependency on the generic upload endpoint's response or mime allowlist;
- attach_file accepts the platform's own PRIVATE file url as the reference;
- list_attachments serves a forced-download URL (?download=1).
"""

import io
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from werkzeug.datastructures import FileStorage

from lms.lms import homework_api, homework_attachments, homework_service
from lms.lms.test_helpers import BaseTestUtils as B
from lms.lms.test_homework_round6 import _file

HEIC_BYTES = b"\x00\x00\x00\x18ftypheic" + b"heic-payload"


@contextmanager
def _multipart(filename: str, content: bytes):
	"""Fake the multipart transport the browser posts: request.files['file']."""
	real = getattr(frappe.local, "request", None)
	frappe.local.request = frappe._dict(
		files={"file": FileStorage(stream=io.BytesIO(content), filename=filename)},
		headers={},
		host="hwtest.local",
		method="POST",
	)
	try:
		yield
	finally:
		frappe.local.request = real


class HotfixBase(B, IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		token = frappe.generate_hash(length=10)
		self.teacher = B._create_user(
			f"hx1-{token}@example.com", "Hx", "Teach", ["Course Creator", "LMS Student"]
		)
		self.student = B._create_user(
			f"hx2-{token}@example.com", "Hx", "Stud", ["LMS Student"]
		)
		frappe.set_user(self.teacher.name)
		self.course = B._create_course(title=f"HX Course {token}", instructor=self.teacher.name)
		self.chapter = B._create_chapter(f"HX ch {token}", self.course.name)
		B._create_chapter_reference(self.course.name, self.chapter.name)
		self.lesson = B._create_lesson(f"HX lesson {token}", self.chapter.name, self.course.name)
		B._create_lesson_reference(self.chapter.name, self.lesson.name)
		B._create_enrollment(self.student.name, self.course.name)
		self.template = homework_api.save_homework(
			title=f"HX hw {token}", days=3, items=[{"source_type": "Lesson", "name": self.lesson.name}]
		)["name"]
		self.assignment = homework_api.assign_homework(
			homework=self.template,
			student=self.student.name,
			idempotency_key=frappe.generate_hash(length=24),
		)["name"]


class TestUploadSolutionFile(HotfixBase):
	def test_heic_image_registers_in_one_request(self):
		frappe.set_user(self.student.name)
		with _multipart("scan.heic", HEIC_BYTES) as _:
			result = homework_attachments.upload_solution_file(
				doctype="LMS Homework Assignment", docname=self.assignment
			)
		self.assertTrue(result["name"])
		self.assertEqual(result["state"]["used"], len(HEIC_BYTES))
		row = frappe.get_doc("LMS Homework Attachment", result["name"])
		self.assertEqual(row.student, self.student.name)
		self.assertEqual(row.file_size, len(HEIC_BYTES))
		# HEIC may be unknown to Python's mimetypes table, but is an explicitly
		# supported image format.
		self.assertIn(
			row.content_type,
			("image/heic", "application/octet-stream", ""),
		)
		file_row = frappe.db.get_value(
			"File",
			row.file,
			["is_private", "attached_to_doctype", "attached_to_name", "file_url"],
			as_dict=True,
		)
		self.assertEqual(file_row.is_private, 1)
		self.assertEqual(file_row.attached_to_doctype, "LMS Homework Attachment")
		self.assertEqual(file_row.attached_to_name, row.name)
		self.assertTrue(file_row.file_url.startswith("/private/files/"))

	def test_unsupported_executable_extension_refused(self):
		frappe.set_user(self.student.name)
		files_before = frappe.db.count("File")
		with _multipart("payload.exe", b"MZ" + b"x" * 40):
			with self.assertRaises(frappe.ValidationError):
				homework_attachments.upload_solution_file(assignment=self.assignment)
		self.assertEqual(frappe.db.count("File"), files_before)

	def test_mislabeled_known_container_refused_without_orphan(self):
		frappe.set_user(self.student.name)
		files_before = frappe.db.count("File")
		with _multipart("photo.jpg", b"<html><script>alert(1)</script></html>"):
			with self.assertRaises(frappe.ValidationError):
				homework_attachments.upload_solution_file(assignment=self.assignment)
		# Nothing was stored and nothing was registered: a refusal in the
		# single-request transport leaves no orphan behind.
		self.assertEqual(frappe.db.count("File"), files_before)
		self.assertEqual(
			frappe.db.count("LMS Homework Attachment", {"assignment": self.assignment}), 0
		)

	def test_oversize_file_refused_before_storing(self):
		frappe.set_user(self.student.name)
		files_before = frappe.db.count("File")
		with _multipart("big.zip", b"\x00" * (homework_attachments.ATTACHMENT_QUOTA_BYTES + 1)):
			with self.assertRaises(frappe.ValidationError):
				homework_attachments.upload_solution_file(assignment=self.assignment)
		self.assertEqual(frappe.db.count("File"), files_before)

	def test_quota_sum_refusal_leaves_no_rows_or_files(self):
		# Fixture rows: tiny real files whose stored sizes eat the quota.
		frappe.set_user("Administrator")
		spent = 0
		fixture_rows = []
		while spent < homework_attachments.ATTACHMENT_QUOTA_BYTES - 100:
			file_doc = _file(self.student.name)
			row = frappe.new_doc("LMS Homework Attachment")
			row.update(
				{
					"assignment": self.assignment,
					"student": self.student.name,
					"file": file_doc.name,
					"file_name": file_doc.file_name,
					"file_size": 10 * 1024 * 1024,
					"content_type": "text/plain",
				}
			)
			row.insert(ignore_permissions=True)
			fixture_rows.append(row.name)
			spent += 10 * 1024 * 1024
		frappe.set_user(self.student.name)
		files_before = frappe.db.count("File")
		with _multipart("note.txt", b"n" * 200):
			with self.assertRaises(frappe.ValidationError):
				homework_attachments.upload_solution_file(assignment=self.assignment)
		self.assertEqual(frappe.db.count("File"), files_before)
		self.assertEqual(
			frappe.db.count("LMS Homework Attachment", {"assignment": self.assignment}),
			len(fixture_rows),
		)

	def test_only_the_student_uses_the_transport(self):
		frappe.set_user(self.teacher.name)
		with _multipart("t.txt", b"teacher bytes"):
			with self.assertRaises(frappe.PermissionError):
				homework_attachments.upload_solution_file(assignment=self.assignment)

	def test_review_state_refuses_upload(self):
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
		with _multipart("late.pdf", b"%PDF-1.7 late"):
			with self.assertRaises(frappe.PermissionError):
				homework_attachments.upload_solution_file(assignment=self.assignment)
		self.assertEqual(
			frappe.db.count("LMS Homework Attachment", {"assignment": self.assignment}), 0
		)


class TestAttachByUrlAndDto(HotfixBase):
	def test_transient_deadlock_does_not_delete_student_upload(self):
		file_doc = _file(self.student.name)
		frappe.set_user(self.student.name)
		with patch.object(
			homework_attachments,
			"_assert_registration_allowed",
			side_effect=frappe.QueryDeadlockError("transient deadlock"),
		):
			with self.assertRaises(frappe.QueryDeadlockError):
				homework_attachments.attach_file(self.assignment, file_doc.name)
		self.assertTrue(
			frappe.db.exists("File", file_doc.name),
			"transient database failures must leave the student's upload available for retry",
		)

	def test_attach_by_private_url_reference(self):
		file_doc = _file(self.student.name)
		url = frappe.db.get_value("File", file_doc.name, "file_url")
		self.assertTrue(url.startswith("/private/files/"))
		frappe.set_user(self.student.name)
		result = homework_attachments.attach_file(self.assignment, file_name=url)
		self.assertEqual(
			frappe.db.get_value("LMS Homework Attachment", result["name"], "file"), file_doc.name
		)

	def test_dto_serves_forced_download_url(self):
		file_doc = _file(self.student.name)
		frappe.set_user(self.student.name)
		homework_attachments.attach_file(self.assignment, file_doc.name)
		dto = homework_attachments.list_attachments(self.assignment)
		self.assertEqual(len(dto["rows"]), 1)
		row = dto["rows"][0]
		self.assertTrue(row["file_url"].startswith("/private/files/"))
		self.assertEqual(row["download_url"], row["file_url"] + "?download=1")


if __name__ == "__main__":
	unittest.main()
