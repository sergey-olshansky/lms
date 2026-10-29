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
import json
import os
import zipfile
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from werkzeug.datastructures import FileStorage

from lms.lms import api
from lms.lms import course_import_export
from lms.lms.course_import_export import export_course_zip, import_course_zip
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


class TestFolderArchiveRoundTrip(BaseTestUtils):
	"""The course archive carries folders and their images without silent loss.

	Export packs every folder doc with its images' bytes and order; import
	rebuilds the folders on the right sections with their File links, privacy and
	attachment intact -- or refuses, never drops.
	"""

	def setUp(self):
		super().setUp()
		self._create_user(INSTRUCTOR, "Frappe", "Teacher", ["Course Creator"])
		self.course = self._create_course("Folder Archive Course")
		frappe.set_user(INSTRUCTOR)
		self.chapter = self.make_chapter("Materials")
		self.hash = frappe.generate_hash(length=6).lower()

	def make_chapter(self, title, parent_section=None):
		chapter = frappe.new_doc("Course Chapter")
		chapter.update(
			{"course": self.course.name, "title": title, "parent_section": parent_section}
		)
		chapter.insert()
		if not parent_section:
			self._create_chapter_reference(self.course.name, chapter.name, idx=1)
		return chapter

	def attach_section_row(self, parent, child, idx):
		row = frappe.new_doc("Lesson Reference")
		row.update(
			{
				"section": child.name,
				"idx": idx,
				"parent": parent.name,
				"parenttype": "Course Chapter",
				"parentfield": "lessons",
			}
		)
		row.insert()

	def upload(self, folder, filename, payload):
		with multipart(filename, payload):
			return api.upload_folder_image(folder=folder)["file"]

	def export(self, course_name):
		"""Run the real export; keep (and clean up) the ZIP it produces."""
		with patch.object(course_import_export, "serve_zip") as serve, patch.object(
			course_import_export, "schedule_file_deletion"
		):
			export_course_zip(course_name)
		path = serve.call_args[0][0]
		self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
		return path

	def import_(self, path):
		original = frappe.session.user
		frappe.set_user(INSTRUCTOR)
		try:
			return import_course_zip(f"/private/files/{os.path.basename(path)}")
		finally:
			frappe.set_user(original)

	def trim_members(self, path, prefixes):
		"""The same archive minus the given member trees (a damaged copy)."""
		trimmed = path.replace(".zip", "-trimmed.zip")
		with zipfile.ZipFile(path) as src, zipfile.ZipFile(trimmed, "w") as dst:
			for member in src.namelist():
				if not member.startswith(tuple(prefixes)):
					dst.writestr(member, src.read(member))
		self.addCleanup(lambda: os.path.exists(trimmed) and os.remove(trimmed))
		return trimmed

	def test_round_trip_keeps_folder_names_order_and_image_bytes(self):
		# Root section: folder, lesson, folder -- the mixed order; a nested
		# section carries a folder of its own.
		first = api.create_folder(title="Тема 1", chapter=self.chapter.name)
		first_payloads = [PNG_1PX + b"-one", PNG_1PX + b"-two"]
		first_images = [
			self.upload(first, f"rt-a-{self.hash}-{n}.png", payload)
			for n, payload in zip((1, 2), first_payloads)
		]
		api.create_lesson(self.chapter.name)
		second = api.create_folder(title="Extras", chapter=self.chapter.name)
		second_images = [self.upload(second, f"rt-b-{self.hash}.png", PNG_1PX + b"-extras")]
		nested = self.make_chapter("Nested Materials", parent_section=self.chapter.name)
		self.attach_section_row(self.chapter, nested, idx=4)
		third = api.create_folder(title="Nested folder", chapter=nested.name)
		third_images = [self.upload(third, f"rt-c-{self.hash}.png", PNG_1PX + b"-nested")]

		path = self.export(self.course.name)

		# What the archive carries: one doc per folder, each image's bytes under
		# the private root, and the folder's own image order in its JSON.
		with zipfile.ZipFile(path) as archive:
			members = archive.namelist()
			self.assertEqual(len([m for m in members if m.startswith("folders/")]), 3)
			first_json = json.loads(
				archive.read(f"folders/{course_import_export.sanitize_string(first)}.json")
			)
			self.assertEqual(
				[row["file_url"] for row in first_json["images"]],
				[image["file_url"] for image in first_images],
			)
			for image in first_images + second_images + third_images:
				self.assertIn(f"assets/private/files/{image['file_name']}", members)

		# Removing the source folders takes their private files with them, so
		# every byte below must come out of the archive itself.
		for folder in (first, second, third):
			api.delete_folder(folder)

		imported = self.import_(path)
		self.assertNotEqual(imported, self.course.name)

		node = get_course_outline(imported)[0]
		self.assertEqual([f.title for f in node.folders], ["Тема 1", "Extras"])
		self.assertEqual([f.position for f in node.folders], [1, 3])
		self.assertEqual([l.number for l in node.lessons], ["1-1"])
		self.assertEqual([f.title for f in node.sections[0].folders], ["Nested folder"])

		# Names and order per folder, then bytes, privacy and links per image.
		restored = node.folders[0].images
		self.assertEqual([i.file_name for i in restored], [i["file_name"] for i in first_images])
		for image, payload in zip(restored, first_payloads):
			file_doc = frappe.get_doc("File", {"file_url": image.file_url})
			self.assertEqual(file_doc.is_private, 1)
			self.assertEqual(file_doc.attached_to_doctype, "Course Folder")
			self.assertEqual(file_doc.attached_to_name, node.folders[0].name)
			with open(file_doc.get_full_path(), "rb") as stored:
				self.assertEqual(stored.read(), payload)
		self.assertEqual(node.folders[0].image_count, 2)

		# Importing the same archive again reuses the restored files rather than
		# duplicating them: one File per URL, both courses point at it.
		again = self.import_(path)
		self.assertNotEqual(again, imported)
		for image in restored:
			self.assertEqual(frappe.db.count("File", {"file_url": image.file_url}), 1)

	def test_export_fails_clearly_when_two_images_would_share_one_archive_entry(self):
		folder = api.create_folder(title="Clash", chapter=self.chapter.name)
		# The names differ on disk, but the archive's name sanitizer keeps only
		# [a-z0-9 -.]: both reduce to the same member name and one would overwrite
		# the other -- a loss the export must refuse instead of hiding.
		self.upload(folder, f"img_one_{self.hash}.png", PNG_1PX + b"-one")
		self.upload(folder, f"imgone{self.hash}.png", PNG_1PX + b"-two")

		with self.assertRaises(frappe.ValidationError) as ctx:
			self.export(self.course.name)
		message = str(ctx.exception)
		self.assertIn(f"img_one_{self.hash}.png", message)
		self.assertIn(f"imgone{self.hash}.png", message)

	def test_import_fails_clearly_when_folder_image_bytes_are_missing(self):
		folder = api.create_folder(title="Bytes", chapter=self.chapter.name)
		self.upload(folder, f"miss-{self.hash}.png", PNG_1PX + b"-bytes")

		path = self.export(self.course.name)
		trimmed = self.trim_members(path, ("assets/",))

		with self.assertRaises(frappe.ValidationError) as ctx:
			self.import_(trimmed)
		message = str(ctx.exception)
		self.assertIn(f"miss-{self.hash}.png", message)
		self.assertIn("Bytes", message)

	def test_import_fails_clearly_when_a_folder_doc_is_missing_from_the_archive(self):
		folder = api.create_folder(title="Ghost", chapter=self.chapter.name)
		self.upload(folder, f"ghost-{self.hash}.png", PNG_1PX)

		path = self.export(self.course.name)
		trimmed = self.trim_members(path, ("folders/",))

		with self.assertRaises(frappe.ValidationError) as ctx:
			self.import_(trimmed)
		self.assertIn("Ghost", str(ctx.exception))


class TestLessonReferenceChildKinds(BaseTestUtils):
	"""The child-row validator accepts exactly one of lesson/section/folder.

	Regressions for the folder stage: a folder row sets neither lesson nor
	section and must insert, while a row pointing at nothing or at several
	kinds at once is refused with one clear validation error.
	"""

	def setUp(self):
		super().setUp()
		self._create_user(INSTRUCTOR, "Frappe", "Teacher", ["Course Creator"])
		self.course = self._create_course("Child Kind Course")
		frappe.set_user(INSTRUCTOR)
		self.chapter = self.make_chapter("Materials")
		self.lesson = api.create_lesson(self.chapter.name)
		self.nested = self.make_chapter("Nested", parent_section=self.chapter.name)
		self.folder = api.create_folder(title="Folder", chapter=self.chapter.name)

	def make_chapter(self, title, parent_section=None):
		chapter = frappe.new_doc("Course Chapter")
		chapter.update(
			{"course": self.course.name, "title": title, "parent_section": parent_section}
		)
		chapter.insert()
		if not parent_section:
			self._create_chapter_reference(self.course.name, chapter.name, idx=1)
		return chapter

	def insert_row(self, **kwargs):
		row = frappe.new_doc("Lesson Reference")
		row.update(
			{
				"idx": frappe.db.count("Lesson Reference", {"parent": self.chapter.name}) + 1,
				"parent": self.chapter.name,
				"parenttype": "Course Chapter",
				"parentfield": "lessons",
				**kwargs,
			}
		)
		row.insert()
		return row.name

	# -- exactly one kind is valid ---------------------------------------

	def test_lesson_only_row_is_valid(self):
		self.assertTrue(self.insert_row(lesson=self.lesson))

	def test_section_only_row_is_valid(self):
		self.assertTrue(self.insert_row(section=self.nested.name))

	def test_folder_only_row_is_valid(self):
		self.assertTrue(self.insert_row(folder=self.folder))

	# -- zero or several kinds are rejected ------------------------------

	def test_row_with_no_reference_is_rejected(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.insert_row()
		self.assertIn("exactly one of a lesson, a section or a folder", str(ctx.exception))

	def test_row_with_lesson_and_section_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.insert_row(lesson=self.lesson, section=self.nested.name)

	def test_row_with_lesson_and_folder_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.insert_row(lesson=self.lesson, folder=self.folder)

	def test_row_with_section_and_folder_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.insert_row(section=self.nested.name, folder=self.folder)

	def test_row_with_all_three_kinds_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.insert_row(
				lesson=self.lesson, section=self.nested.name, folder=self.folder
		)
