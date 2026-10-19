"""Import a video and its lesson.zip as one persistent EditorJS article block."""

import uuid

import frappe
from frappe import _
from frappe.utils.file_manager import save_file

from lms.lms.lesson_archive_format import MAX_ARCHIVE_BYTES, LessonArchiveError, parse_archive, video_url


@frappe.whitelist(methods=["POST"])
def import_lesson_archive(video_src, archive_url, course, lesson=None, fieldname="content"):
	"""Prepare a video + article block; the lesson's normal autosave persists it."""
	from lms.lms.permissions import can_access_lesson, can_author_course, is_site_administrator

	if not can_author_course(course):
		raise frappe.PermissionError
	if fieldname not in {"content", "instructor_content"}:
		frappe.throw(_("Invalid lesson field."))
	if lesson:
		lesson_doc = frappe.get_doc("Course Lesson", lesson)
		if lesson_doc.course != course:
			raise frappe.PermissionError
		lesson_doc.check_permission("write")
	if not isinstance(archive_url, str) or not archive_url.startswith("/private/files/"):
		frappe.throw(_("Upload a private ZIP archive first."))
	# The first File row owns the bytes. A later forged row naming the same URL
	# cannot grant read access to somebody else's upload.
	rows = frappe.get_all(
		"File",
		filters={"file_url": archive_url, "is_private": 1},
		fields=["name"],
		order_by="creation asc, name asc",
		limit_page_length=1,
	)
	if not rows:
		raise frappe.PermissionError
	file_doc = frappe.get_doc("File", rows[0].name)
	file_doc.check_permission("read")
	if file_doc.owner != frappe.session.user and not is_site_administrator():
		if (
			file_doc.attached_to_doctype != "Course Lesson"
			or not file_doc.attached_to_name
			or not can_access_lesson(file_doc.attached_to_name, instructor_only=True)
		):
			raise frappe.PermissionError
	if (file_doc.file_size or 0) > MAX_ARCHIVE_BYTES:
		frappe.throw("Размер ZIP не должен превышать 100 МБ.")
	try:
		src = video_url(video_src)
		manifest, frames = parse_archive(file_doc.get_content())
	except LessonArchiveError as error:
		frappe.throw(str(error))
	prefix = uuid.uuid4().hex[:12]
	frame_urls = {}
	for index, (path, content) in enumerate(frames.items(), 1):
		file = save_file(
			f"lesson-{prefix}-{index:02d}.png",
			content,
			"Course Lesson" if lesson else None,
			lesson,
			is_private=1,
			df=fieldname if lesson else None,
		)
		frame_urls[path] = file.file_url
	for section in manifest["sections"]:
		for frame in section["frames"]:
			frame["image_url"] = frame_urls[frame["file"]]
	return {
		"video_src": src,
		"archive": {"file_url": archive_url, "file_name": file_doc.file_name},
		"manifest": manifest,
	}
