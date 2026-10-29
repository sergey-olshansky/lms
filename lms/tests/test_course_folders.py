# Copyright (c) 2026, FOSS United and Contributors
# See license.txt

"""Course image folders: the third child kind of a section.

Covers: several named folders in one section (repeated titles allowed), the
mixed single order of lessons/sections/folders, deterministic private image
order, idempotent retry of a partially failed batch, per-file limit errors,
editor-only writes through can_modify_course, member-scoped outline
visibility, and cleanup on folder/chapter delete.
"""

import base64
import io
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from werkzeug.datastructures import FileStorage

from lms.lms import api
from lms.lms.test_helpers import BaseTestUtils
from lms.lms.utils import get_course_outline

INSTRUCTOR = "frappe@example.com"
STUDENT = "folders-student@example.com"
OUTSIDER = "folders-outsider@example.com"

PNG_1PX = base64.b64decode(
	"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@contextmanager
def multipart(filename: str, content: bytes):
	"""Fake the multipart transport the browser posts: request.files['file']."""
	real = getattr(frappe.local, "request", None)
	frappe.local.request = frappe._dict(
		files={"file": FileStorage(stream=io.BytesIO(content), filename=filename)},
		headers={},
		host="foldertest.local",
		method="POST",
	)
	try:
		yield
	finally:
		frappe.local.request = real


class TestCourseFolders(BaseTestUtils):
	def setUp(self):
		super().setUp()
		self._create_user(INSTRUCTOR, "Frappe", "Teacher", ["Course Creator"])
		self.course = self._create_course("Image Folder Course")
		frappe.set_user(INSTRUCTOR)
		self.chapter = self.make_chapter("Materials")

	def make_chapter(self, title, parent_section=None):
		chapter = frappe.new_doc("Course Chapter")
		chapter.update(
			{
				"course": self.course.name,
				"title": title,
				"parent_section": parent_section,
			}
		)
		chapter.insert()
		self._create_chapter_reference(self.course.name, chapter.name, idx=1)
		return chapter

	# -- folders as section children --------------------------------------

	def test_multiple_named_folders_keep_mixed_order(self):
		first = api.create_folder(title="Тема 1", chapter=self.chapter.name)
		api.create_lesson(self.chapter.name)
		second = api.create_folder(title="Тема 1", chapter=self.chapter.name)

		# Repeated titles are legal: the docname numbers them apart.
		self.assertNotEqual(first, second)

		node = get_course_outline(self.course.name)[0]
		self.assertEqual([f.title for f in node.folders], ["Тема 1", "Тема 1"])
		self.assertEqual(node.folder_count, 2)
		# Positions are the child-table rows: folder, lesson, folder.
		self.assertEqual([f.position for f in node.folders], [1, 3])
		# Numbering ignores folders entirely: the lesson is still 1-1.
		self.assertEqual([l.number for l in node.lessons], ["1-1"])

		# Titles survive a fresh read (they live on the folder doc).
		titles = frappe.get_all(
			"Course Folder",
			{"chapter": self.chapter.name},
			pluck="title",
			order_by="creation",
		)
		self.assertEqual(titles, ["Тема 1", "Тема 1"])

	def test_folder_rename_persists(self):
		folder = api.create_folder(title="Draft", chapter=self.chapter.name)
		api.rename_folder(folder=folder, title="Финальная папка")
		node = get_course_outline(self.course.name)[0]
		self.assertEqual(node.folders[0].title, "Финальная папка")

		with self.assertRaises(frappe.ValidationError):
			api.rename_folder(folder=folder, title="   ")

	def test_folder_writes_require_course_access(self):
		folder = api.create_folder(title="Guarded", chapter=self.chapter.name)
		self._create_user(STUDENT, "Folder", "Student", ["LMS Student"])

		frappe.set_user(STUDENT)
		with self.assertRaises(frappe.PermissionError):
			api.create_folder(title="Nope", chapter=self.chapter.name)
		with self.assertRaises(frappe.PermissionError):
			api.rename_folder(folder=folder, title="Nope")
		with self.assertRaises(frappe.PermissionError):
			api.delete_folder(folder=folder)
		with self.assertRaises(frappe.PermissionError):
			api.update_folder_index(folder=folder, parent=self.chapter.name, idx=0)
		with multipart("a.png", PNG_1PX):
			with self.assertRaises(frappe.PermissionError):
				api.upload_folder_image(folder=folder)
		with self.assertRaises(frappe.PermissionError):
			api.delete_folder_image(folder=folder, image="whatever.png")

		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			api.create_folder(title="Nope", chapter=self.chapter.name)

	# -- images: upload, order, privacy -----------------------------------

	def test_upload_orders_images_and_keeps_them_private(self):
		folder = api.create_folder(title="Images", chapter=self.chapter.name)
		with multipart("first.png", PNG_1PX):
			uploaded = api.upload_folder_image(folder=folder)
		with multipart("second.png", PNG_1PX):
			api.upload_folder_image(folder=folder)

		self.assertEqual(uploaded["status"], "uploaded")
		stored = frappe.get_doc("File", uploaded["file"]["name"])
		self.assertEqual(stored.attached_to_doctype, "Course Folder")
		self.assertEqual(stored.attached_to_name, folder)
		self.assertEqual(stored.is_private, 1)
		self.assertTrue(stored.file_url.startswith("/private/files/"))

		node = get_course_outline(self.course.name)[0]
		images = node.folders[0].images
		self.assertEqual([i.file_name for i in images], ["first.png", "second.png"])
		self.assertEqual(node.folders[0].image_count, 2)
		for image in images:
			self.assertTrue(image.file_url.startswith("/private/files/"))

	def test_duplicate_upload_is_skipped_not_duplicated(self):
		folder = api.create_folder(title="Retry", chapter=self.chapter.name)
		with multipart("same.png", PNG_1PX):
			first = api.upload_folder_image(folder=folder)
		with multipart("same.png", PNG_1PX):
			second = api.upload_folder_image(folder=folder)

		# Same name + same size: the retry lands on the stored file, not a copy.
		self.assertEqual(first["status"], "uploaded")
		self.assertEqual(second["status"], "skipped")
		self.assertEqual(first["file"]["name"], second["file"]["name"])
		self.assertEqual(
			frappe.db.count("Folder Image Reference", {"parent": folder}), 1
		)

		# Same name, different size: a genuinely different file, so it is kept.
		with multipart("same.png", PNG_1PX + b"different"):
			third = api.upload_folder_image(folder=folder)
		self.assertEqual(third["status"], "uploaded")
		self.assertNotEqual(third["file"]["name"], first["file"]["name"])
		self.assertEqual(
			frappe.db.count("Folder Image Reference", {"parent": folder}), 2
		)

	def test_upload_rejects_bad_format_size_and_missing_file(self):
		folder = api.create_folder(title="Limits", chapter=self.chapter.name)

		with multipart("notes.txt", b"plain text"):
			with self.assertRaises(frappe.ValidationError):
				api.upload_folder_image(folder=folder)

		with multipart("big.png", b"\0" * (api.FOLDER_IMAGE_MAX_SIZE + 1)):
			with self.assertRaises(frappe.ValidationError):
				api.upload_folder_image(folder=folder)

		with multipart("empty.png", b""):
			with self.assertRaises(frappe.ValidationError):
				api.upload_folder_image(folder=folder)

		# No multipart body at all: a clear error, not a traceback.
		saved = getattr(frappe.local, "request", None)
		frappe.local.request = frappe._dict(headers={}, host="foldertest.local")
		try:
			with self.assertRaises(frappe.ValidationError):
				api.upload_folder_image(folder=folder)
		finally:
			frappe.local.request = saved

		self.assertEqual(
			frappe.db.count("Folder Image Reference", {"parent": folder}), 0
		)

	def test_folder_image_limit_is_enforced(self):
		folder = api.create_folder(title="Full", chapter=self.chapter.name)
		with patch("lms.lms.api.FOLDER_MAX_IMAGES", 2):
			with multipart("a.png", PNG_1PX):
				api.upload_folder_image(folder=folder)
			with multipart("b.png", PNG_1PX):
				api.upload_folder_image(folder=folder)
			with multipart("c.png", PNG_1PX):
				with self.assertRaises(frappe.ValidationError):
					api.upload_folder_image(folder=folder)
		self.assertEqual(
			frappe.db.count("Folder Image Reference", {"parent": folder}), 2
		)

	# -- ordering and cleanup ---------------------------------------------

	def test_reorder_folder_among_mixed_children(self):
		first = api.create_folder(title="A", chapter=self.chapter.name)
		api.create_lesson(self.chapter.name)
		second = api.create_folder(title="B", chapter=self.chapter.name)

		# Child rows are [A, lesson, B]; move B to the front.
		api.update_folder_index(folder=second, parent=self.chapter.name, idx=0)

		node = get_course_outline(self.course.name)[0]
		self.assertEqual([f.title for f in node.folders], ["B", "A"])
		self.assertEqual([f.position for f in node.folders], [1, 3])
		self.assertEqual([l.number for l in node.lessons], ["1-1"])

		with self.assertRaises(frappe.DoesNotExistError):
			api.update_folder_index(folder=first, parent="missing-section", idx=0)

	def test_delete_folder_removes_files_and_renumbers(self):
		folder = api.create_folder(title="Bye", chapter=self.chapter.name)
		api.create_folder(title="Stay", chapter=self.chapter.name)
		with multipart("a.png", PNG_1PX):
			uploaded = api.upload_folder_image(folder=folder)
		with multipart("b.png", PNG_1PX):
			api.upload_folder_image(folder=folder)

		api.delete_folder(folder=folder)

		self.assertFalse(frappe.db.exists("Course Folder", folder))
		self.assertFalse(frappe.db.exists("File", uploaded["file"]["name"]))
		self.assertEqual(frappe.db.count("Folder Image Reference", {"parent": folder}), 0)
		self.assertEqual(
			frappe.db.count("Lesson Reference", {"parent": self.chapter.name, "folder": folder}),
			0,
		)
		# The surviving folder's row is renumbered back to 1.
		stayed = frappe.db.get_value("Course Folder", {"chapter": self.chapter.name}, "name")
		row = frappe.db.get_value(
			"Lesson Reference", {"parent": self.chapter.name, "folder": stayed}, "idx"
		)
		self.assertEqual(row, 1)

	def test_delete_folder_image_renumbers_and_deletes_file(self):
		folder = api.create_folder(title="Trim", chapter=self.chapter.name)
		with multipart("a.png", PNG_1PX):
			first = api.upload_folder_image(folder=folder)
		with multipart("b.png", PNG_1PX):
			second = api.upload_folder_image(folder=folder)

		api.delete_folder_image(folder=folder, image=first["file"]["name"])

		self.assertFalse(frappe.db.exists("File", first["file"]["name"]))
		rows = frappe.get_all(
			"Folder Image Reference", {"parent": folder}, ["image", "idx"], order_by="idx"
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].image, second["file"]["name"])
		self.assertEqual(rows[0].idx, 1)

		with self.assertRaises(frappe.DoesNotExistError):
			api.delete_folder_image(folder=folder, image=first["file"]["name"])

	def test_delete_chapter_purges_folders_and_files(self):
		folder = api.create_folder(title="Purge", chapter=self.chapter.name)
		with multipart("a.png", PNG_1PX):
			uploaded = api.upload_folder_image(folder=folder)

		api.delete_chapter(self.chapter.name)

		self.assertFalse(frappe.db.exists("Course Folder", folder))
		self.assertFalse(frappe.db.exists("File", uploaded["file"]["name"]))
		self.assertEqual(
			frappe.db.count("Lesson Reference", {"parent": self.chapter.name}), 0
		)

	def test_scorm_sections_reject_folders(self):
		frappe.db.set_value("Course Chapter", self.chapter.name, "is_scorm_package", 1)
		with self.assertRaises(frappe.ValidationError):
			api.create_folder(title="Nope", chapter=self.chapter.name)

	# -- visibility --------------------------------------------------------

	def test_draft_course_folders_follow_course_visibility(self):
		folder = api.create_folder(title="Members only", chapter=self.chapter.name)
		with multipart("a.png", PNG_1PX):
			api.upload_folder_image(folder=folder)
		frappe.db.set_value("LMS Course", self.course.name, "published", 0)

		self._create_user(STUDENT, "Folder", "Student", ["LMS Student"])
		self._create_user(OUTSIDER, "Folder", "Outsider", ["LMS Student"])
		self._create_enrollment(STUDENT, self.course.name)

		# An enrolled member reads the outline with the folder and its images.
		frappe.set_user(STUDENT)
		node = get_course_outline(self.course.name)[0]
		self.assertEqual(node.folders[0].title, "Members only")
		self.assertEqual(node.folders[0].image_count, 1)
		self.assertTrue(node.folders[0].images[0].file_url.startswith("/private/files/"))

		# A logged-in non-member of a draft course gets nothing.
		frappe.set_user(OUTSIDER)
		self.assertEqual(get_course_outline(self.course.name), [])

		# Neither does a guest.
		frappe.set_user("Guest")
		self.assertEqual(get_course_outline(self.course.name), [])
