"""Permission and persistence boundaries of the lesson archive importer."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe

from lms.lms.lesson_archive import import_lesson_archive
from lms.lms.test_lesson_archive_format import archive_bytes


class TestLessonArchiveImport(unittest.TestCase):
	def test_non_author_cannot_read_zip_or_write_frames(self):
		with (
			patch("lms.lms.permissions.can_author_course", return_value=False),
			patch("frappe.get_doc") as get_doc,
			patch("lms.lms.lesson_archive.save_file") as save,
		):
			with self.assertRaises(frappe.PermissionError):
				import_lesson_archive("https://vkvideo.ru/video_ext.php", "/private/files/a.zip", "other")
			get_doc.assert_not_called()
			save.assert_not_called()

	def _file(self, content):
		return SimpleNamespace(
			owner=frappe.session.user,
			file_size=len(content),
			file_name="lesson.zip",
			check_permission=Mock(),
			get_content=Mock(return_value=content),
		)

	def test_import_attaches_private_frames_and_returns_one_article(self):
		file = self._file(archive_bytes())
		lesson = SimpleNamespace(course="chemistry", check_permission=Mock())
		with (
			patch("lms.lms.permissions.can_author_course", return_value=True),
			patch("frappe.get_all", return_value=[SimpleNamespace(name="zip-1")]),
			patch("frappe.get_doc", side_effect=lambda dt, name: lesson if dt == "Course Lesson" else file),
			patch(
				"lms.lms.lesson_archive.save_file",
				return_value=SimpleNamespace(file_url="/private/files/frame.png"),
			) as save,
		):
			data = import_lesson_archive(
				"https://vkvideo.ru/video_ext.php?oid=-1&id=2",
				"/private/files/lesson.zip",
				"chemistry",
				"lesson-1",
			)
			self.assertEqual(
				data["manifest"]["sections"][0]["frames"][0]["image_url"], "/private/files/frame.png"
			)
			self.assertEqual(data["archive"]["file_url"], "/private/files/lesson.zip")
			self.assertEqual(save.call_args.kwargs, {"is_private": 1, "df": "content"})
			self.assertEqual(save.call_args.args[2:], ("Course Lesson", "lesson-1"))
			lesson.check_permission.assert_called_once_with("write")
			file.check_permission.assert_called_once_with("read")

	def test_corrupt_archive_writes_no_frames(self):
		with (
			patch("lms.lms.permissions.can_author_course", return_value=True),
			patch("frappe.get_all", return_value=[SimpleNamespace(name="zip-1")]),
			patch("frappe.get_doc", return_value=self._file(b"invalid zip")),
			patch("lms.lms.lesson_archive.save_file") as save,
		):
			with self.assertRaises(frappe.ValidationError):
				import_lesson_archive(
					"https://vkvideo.ru/video_ext.php?oid=-1&id=2", "/private/files/lesson.zip", "chemistry"
				)
			save.assert_not_called()
