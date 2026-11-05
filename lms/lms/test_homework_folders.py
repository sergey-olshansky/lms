# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Task #41 regressions: image-folder homework sources end-to-end.

A folder-only section becomes attachable (the #1445 scenario, Sergey #1527:
folders are selectable leaves and sections recurse), each stored requirement
is ONE folder whose checklist expands to per-image sub-items, and opening each
individual picture in the real gallery completes exactly that image,
idempotently (Sergey #1521), against the folder's CURRENT image set as the
denominator -- later uploads appear unchecked, deletions drop out, an empty
folder is a muted non-blocking note, and a deleted folder goes Unavailable.
"""

import unittest

import frappe
from frappe.tests import IntegrationTestCase

from lms.lms import api as lms_api
from lms.lms import homework_api, homework_service, homework_sources
from lms.lms.test_helpers import BaseTestUtils as B

PNG_HEADER = bytes([137, 80, 78, 71, 13, 10, 26, 10])


def _private_image(filename: str) -> str:
	"""A private File shaped like the folder upload path stores it."""
	doc = frappe.new_doc("File")
	doc.update(
		{
			"file_name": filename,
			"is_private": 1,
			"content": PNG_HEADER + frappe.generate_hash(length=16).encode(),
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _create_folder(title: str, chapter: str, course: str) -> str:
	"""A Course Folder appended to the section's mixed children."""
	folder = frappe.new_doc("Course Folder")
	folder.update({"title": title, "course": course, "chapter": chapter})
	folder.insert(ignore_permissions=True)
	row = frappe.new_doc("Lesson Reference")
	row.update(
		{
			"folder": folder.name,
			"idx": frappe.db.count("Lesson Reference", {"parent": chapter}) + 1,
			"parent": chapter,
			"parenttype": "Course Chapter",
			"parentfield": "lessons",
		}
	)
	row.insert(ignore_permissions=True)
	return folder.name


def _add_folder_image(folder: str, filename: str, *, recompute: bool = True) -> str:
	"""Append one image to the folder the way the upload endpoint does, with
	the homework catch-up the endpoint itself triggers."""
	image = _private_image(filename)
	row = frappe.new_doc("Folder Image Reference")
	row.update(
		{
			"image": image,
			"idx": frappe.db.count("Folder Image Reference", {"parent": folder}) + 1,
			"parent": folder,
			"parenttype": "Course Folder",
			"parentfield": "images",
		}
	)
	row.insert(ignore_permissions=True)
	if recompute:
		homework_service.recompute_folder_requirements(folder)
	return image


class FolderHomeworkBase(B, IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		token = frappe.generate_hash(length=10)
		self.teacher = B._create_user(
			f"f41t-{token}@example.com", "F", "Forty", ["Course Creator", "LMS Student"]
		)
		self.student = B._create_user(
			f"f41s-{token}@example.com", "F", "Stud", ["LMS Student"]
		)
		self.outsider = B._create_user(
			f"f41o-{token}@example.com", "F", "Other", ["Course Creator", "LMS Student"]
		)
		frappe.set_user(self.teacher.name)
		self.course = B._create_course(title=f"F41 Course {token}", instructor=self.teacher.name)
		self.chapter = B._create_chapter(f"F41 ch {token}", self.course.name)
		B._create_chapter_reference(self.course.name, self.chapter.name)
		B._create_enrollment(self.student.name, self.course.name)

	def make_folder(self, title: str, images: int = 0) -> str:
		name = _create_folder(title, self.chapter.name, self.course.name)
		for index in range(images):
			_add_folder_image(name, f"{title}-{index + 1}.png", recompute=False)
		return name

	def save_folder_homework(self, folder: str, title: str = "F41 folder work") -> str:
		frappe.set_user(self.teacher.name)
		return homework_api.save_homework(title=title, days=7, items=[
			{"source_type": "Folder", "name": folder}
		])["name"]

	def issue(self, homework: str, student: str | None = None) -> str:
		frappe.set_user(self.teacher.name)
		return homework_service.create_assignment(
			homework_name=homework, student=student or self.student.name
		)["name"]

	def folder_row(self, assignment: str) -> dict:
		frappe.set_user(self.student.name)
		detail = homework_api.get_homework_assignment(assignment)
		rows = [row for row in detail["requirements"] if row["requirement_type"] == "Open Folder"]
		self.assertEqual(len(rows), 1)
		return rows[0]


class TestFolderSourceTree(FolderHomeworkBase):
	def test_folder_leaf_with_images_and_counts(self):
		folder = self.make_folder("Photos", images=3)
		tree = homework_sources.get_course_source_tree(self.course.name)
		section = next(n for n in tree["nodes"] if n["type"] == "chapter")
		leaf = next(c for c in section["children"] if c.get("type") == "folder")
		self.assertEqual(leaf["key"], f"folder:{folder}")
		self.assertEqual(leaf["image_count"], 3)
		self.assertTrue(leaf["assignable"])

	def test_folder_only_section_is_assignable(self):
		"""The #1445 scenario: a section with ONLY folders is attachable now."""
		chapter = B._create_chapter("F41 media only", self.course.name)
		B._create_chapter_reference(self.course.name, chapter.name, idx=2)
		_create_folder("Slides", chapter.name, self.course.name)
		_add_folder_image(
			_create_folder("Album", chapter.name, self.course.name), "album-1.png"
		)
		tree = homework_sources.get_course_source_tree(self.course.name)
		section = next(n for n in tree["nodes"] if n["name"] == chapter.name)
		self.assertTrue(section["assignable"])
		# The empty folder itself is NOT selectable -- only the one with images.
		states = {c["key"]: c["assignable"] for c in section["children"]}
		self.assertEqual(states, {"folder:Slides": False, "folder:Album": True})

	def test_truly_empty_section_stays_unassignable(self):
		"""Spec 3.4.5 survives: no lessons, no quizzes, no folders with images."""
		# A section holding only an empty folder...
		self.make_folder("Empty", images=0)
		# ...and a section with no children at all.
		chapter = B._create_chapter("F41 nothing here", self.course.name)
		B._create_chapter_reference(self.course.name, chapter.name, idx=3)
		tree = homework_sources.get_course_source_tree(self.course.name)
		by_name = {n["name"]: n for n in tree["nodes"] if n["type"] == "chapter"}
		empty_folder_only = next(
			n
			for n in by_name.values()
			if any(c.get("type") == "folder" and not c.get("image_count") for c in n["children"])
		)
		self.assertFalse(empty_folder_only["assignable"])
		self.assertFalse(by_name[chapter.name]["assignable"])


class TestFolderCompilation(FolderHomeworkBase):
	def test_canonicalize_and_save_folder_item(self):
		folder = self.make_folder("Photos", images=2)
		homework = self.save_folder_homework(folder)
		doc = frappe.get_doc("LMS Homework", homework)
		self.assertEqual(doc.items[0].source_type, "Folder")
		self.assertEqual(doc.items[0].folder, folder)
		self.assertEqual(doc.items[0].course, self.course.name)

	def test_get_homework_stamps_folder_route(self):
		folder = self.make_folder("Photos", images=1)
		homework = self.save_folder_homework(folder)
		frappe.set_user(self.teacher.name)
		payload = homework_api.get_homework(homework)
		item = payload["items"][0]
		self.assertEqual(item["name"], folder)
		self.assertEqual(item["route"]["type"], "folder")
		self.assertEqual(item["route"]["folder"], folder)

	def test_unknown_folder_refused(self):
		frappe.set_user(self.teacher.name)
		with self.assertRaises(frappe.ValidationError):
			homework_sources.canonicalize_selection(
				[{"source_type": "Folder", "name": "no-such-folder"}]
			)

	def test_folder_on_unreachable_course_refused(self):
		"""Another teacher's course never sources through me (B01)."""
		frappe.set_user("Administrator")
		other = B._create_user(
			"f41x-" + frappe.generate_hash(length=8) + "@example.com",
			"F",
			"Other",
			["Course Creator", "LMS Student"],
		)
		frappe.set_user(other.name)
		course = B._create_course(
			title=f"F41 other {frappe.generate_hash(length=6)}", instructor=other.name
		)
		chapter = B._create_chapter("Other ch", course.name)
		folder = _create_folder("Not mine", chapter.name, course.name)
		frappe.set_user(self.teacher.name)
		with self.assertRaises(frappe.PermissionError):
			homework_sources.canonicalize_selection([{"source_type": "Folder", "name": folder}])


class TestFolderValidation(FolderHomeworkBase):
	def test_draft_folder_without_membership_blocks(self):
		folder = self.make_folder("Draft photos", images=1)
		frappe.db.set_value("LMS Course", self.course.name, "published", 0)
		stranger = B._create_user(
			"f41n-" + frappe.generate_hash(length=8) + "@example.com", "F", "Stranger",
			["LMS Student"],
		)
		frappe.set_user(self.teacher.name)
		items = [{"source_type": "Folder", "name": folder, "folder": folder, "course": self.course.name}]
		reasons = homework_sources.validate_sources_for_student(
			[frappe._dict(item) for item in items], stranger.name
		)
		self.assertTrue(any("not available" in reason for reason in reasons))
		# Enrolled students reach the same folder fine.
		reasons_member = homework_sources.validate_sources_for_student(
			[frappe._dict(item) for item in items], self.student.name
		)
		self.assertEqual(reasons_member, [])

	def test_published_folder_without_membership_allowed(self):
		folder = self.make_folder("Public photos", images=1)
		stranger = B._create_user(
			"f41p-" + frappe.generate_hash(length=8) + "@example.com", "F", "Stranger",
			["LMS Student"],
		)
		frappe.set_user(self.teacher.name)
		reasons = homework_sources.validate_sources_for_student(
			[
				frappe._dict(
					{"source_type": "Folder", "name": folder, "folder": folder, "course": self.course.name}
				)
			],
			stranger.name,
		)
		self.assertEqual(reasons, [])


class TestFolderAssignmentCompletion(FolderHomeworkBase):
	def setUp(self):
		super().setUp()
		self.folder = self.make_folder("Album", images=3)
		self.images = [
			row.image
			for row in frappe.get_all(
				"Folder Image Reference", {"parent": self.folder}, ["image"], order_by="idx"
			)
		]
		self.homework = self.save_folder_homework(self.folder)
		self.assignment = self.issue(self.homework)

	def test_requirement_row_and_checklist_payload(self):
		detail_row = self.folder_row(self.assignment)
		self.assertEqual(detail_row["folder"], self.folder)
		self.assertEqual(detail_row["image_count"], 3)
		self.assertEqual(detail_row["opened_count"], 0)
		self.assertEqual([i["opened"] for i in detail_row["images"]], [False, False, False])
		self.assertEqual(detail_row["route"]["type"], "folder")
		doc = frappe.get_doc("LMS Homework Assignment", self.assignment)
		self.assertEqual(doc.total_requirements, 1)

	def test_opening_one_image_completes_only_it(self):
		frappe.set_user(self.student.name)
		result = homework_service.record_folder_image_opened(self.folder, self.images[0])
		self.assertEqual(result["updated"], 1)
		row = self.folder_row(self.assignment)
		self.assertEqual([i["opened"] for i in row["images"]], [True, False, False])
		self.assertEqual(row["status"], "Pending")
		self.assertEqual(row["opened_count"], 1)

	def test_repeated_opening_is_idempotent(self):
		frappe.set_user(self.student.name)
		homework_service.record_folder_image_opened(self.folder, self.images[0])
		homework_service.record_folder_image_opened(self.folder, self.images[0])
		progress = frappe.get_all(
			"LMS Homework Folder Image",
			{"parent": self.assignment, "image": self.images[0]},
		)
		self.assertEqual(len(progress), 1)

	def test_outsider_and_non_member_get_nothing(self):
		frappe.set_user(self.outsider.name)
		self.assertEqual(
			homework_service.record_folder_image_opened(self.folder, self.images[0]),
			{"updated": 0},
		)
		# A member of no course at all, with no assignment: silent no-op.
		self.assertEqual(
			frappe.get_all("LMS Homework Folder Image", {"folder": self.folder}), []
		)

	def test_all_images_opened_completes_and_moves_to_review(self):
		frappe.set_user(self.student.name)
		for image in self.images:
			homework_service.record_folder_image_opened(self.folder, image)
		row = self.folder_row(self.assignment)
		self.assertEqual(row["status"], "Completed")
		self.assertEqual(row["proof_type"], "Folder Images")
		detail = homework_api.get_homework_assignment(self.assignment)
		self.assertEqual(detail["status"], "Review")

	def test_gallery_state_only_for_student_with_active_homework(self):
		frappe.set_user(self.student.name)
		state = homework_api.get_folder_homework_state(self.folder)
		self.assertTrue(state["active"])
		homework_service.record_folder_image_opened(self.folder, self.images[0])
		state = homework_api.get_folder_homework_state(self.folder)
		self.assertEqual(state["opened"], [self.images[0]])
		frappe.set_user(self.teacher.name)
		self.assertEqual(
			homework_api.get_folder_homework_state(self.folder),
			{"active": False, "opened": []},
		)
		frappe.set_user(self.outsider.name)
		self.assertEqual(
			homework_api.get_folder_homework_state(self.folder),
			{"active": False, "opened": []},
		)


class TestFolderDynamics(FolderHomeworkBase):
	def setUp(self):
		super().setUp()
		self.folder = self.make_folder("Dynamic", images=2)
		self.images = [
			row.image
			for row in frappe.get_all(
				"Folder Image Reference", {"parent": self.folder}, ["image"], order_by="idx"
			)
		]
		self.homework = self.save_folder_homework(self.folder)
		self.assignment = self.issue(self.homework)

	def _open_all(self):
		frappe.set_user(self.student.name)
		for image in frappe.get_all(
			"Folder Image Reference", {"parent": self.folder}, pluck="image", order_by="idx"
		):
			homework_service.record_folder_image_opened(self.folder, image)

	def test_upload_after_completion_invalidates_back_to_progress(self):
		self._open_all()
		self.assertEqual(self.folder_row(self.assignment)["status"], "Completed")
		frappe.set_user(self.teacher.name)
		_add_folder_image(self.folder, "added-later.png")
		row = self.folder_row(self.assignment)
		self.assertEqual(row["status"], "Pending")
		self.assertEqual(row["image_count"], 3)
		self.assertEqual(row["opened_count"], 2)
		self.assertFalse(all(i["opened"] for i in row["images"]))
		detail = homework_api.get_homework_assignment(self.assignment)
		self.assertEqual(detail["status"], "In Progress")
		events = [h["event"] for h in detail["history"]]
		self.assertIn("requirement_invalidated", events)

	def test_completing_new_image_returns_to_review(self):
		self._open_all()
		frappe.set_user(self.teacher.name)
		_add_folder_image(self.folder, "added-later.png")
		self._open_all()
		self.assertEqual(self.folder_row(self.assignment)["status"], "Completed")
		self.assertEqual(
			homework_api.get_homework_assignment(self.assignment)["status"], "Review"
		)

	def test_deleted_image_leaves_the_denominator(self):
		self._open_all()
		frappe.set_user(self.teacher.name)
		lms_api.delete_folder_image(folder=self.folder, image=self.images[0])
		row = self.folder_row(self.assignment)
		self.assertEqual(row["image_count"], 1)
		self.assertEqual(row["opened_count"], 1)
		self.assertEqual(row["status"], "Completed")

	def test_emptied_folder_is_neutral_not_blocking(self):
		self._open_all()
		frappe.set_user(self.teacher.name)
		for image in list(self.images):
			lms_api.delete_folder_image(folder=self.folder, image=image)
		row = self.folder_row(self.assignment)
		self.assertTrue(row["folder_empty"])
		self.assertEqual(row["state_label"], "The folder has no images")
		detail = homework_api.get_homework_assignment(self.assignment)
		# Excluded from the denominator (spec: 0 of 0 never happens) and never
		# blocking: the card closed on the strength of the neutral rule.
		self.assertEqual(detail["total_requirements"], 0)
		self.assertEqual(detail["status"], "Review")

	def test_deleted_folder_goes_unavailable(self):
		frappe.set_user("Administrator")
		frappe.delete_doc("Course Folder", self.folder, ignore_permissions=True)
		homework_service.recompute_folder_requirements(self.folder)
		row = self.folder_row(self.assignment)
		self.assertEqual(row["status"], "Unavailable")


class TestFolderPriorCredit(FolderHomeworkBase):
	def test_reissue_after_full_completion_credits_earlier(self):
		folder = self.make_folder("Prior", images=2)
		images = frappe.get_all(
			"Folder Image Reference", {"parent": folder}, pluck="image", order_by="idx"
		)
		first = self.issue(self.save_folder_homework(folder, title="F41 first"))
		frappe.set_user(self.student.name)
		for image in images:
			homework_service.record_folder_image_opened(folder, image)
		frappe.set_user(self.teacher.name)
		homework_service.accept(first)
		second = self.issue(self.save_folder_homework(folder, title="F41 second"))
		doc = frappe.get_doc("LMS Homework Assignment", second)
		row = [r for r in doc.requirements if r.requirement_type == "Open Folder"][0]
		self.assertEqual(row.status, "Completed Earlier")

	def test_reissue_with_new_image_stays_pending(self):
		folder = self.make_folder("Prior new", images=1)
		image = frappe.get_all(
			"Folder Image Reference", {"parent": folder}, pluck="image", order_by="idx"
		)[0]
		self.issue(self.save_folder_homework(folder, title="F41 prior a"))
		frappe.set_user(self.student.name)
		homework_service.record_folder_image_opened(folder, image)
		frappe.set_user(self.teacher.name)
		_add_folder_image(folder, "unseen.png")
		second = self.issue(self.save_folder_homework(folder, title="F41 prior b"))
		doc = frappe.get_doc("LMS Homework Assignment", second)
		row = [r for r in doc.requirements if r.requirement_type == "Open Folder"][0]
		self.assertEqual(row.status, "Pending")


class TestFolderLessonRegression(FolderHomeworkBase):
	"""Folders ride WITH lessons; the lesson flow itself stays untouched."""

	def test_lesson_and_folder_composition_issues_both(self):
		lesson = B._create_lesson("F41 lesson", self.chapter.name, self.course.name)
		B._create_lesson_reference(self.chapter.name, lesson.name)
		folder = self.make_folder("With lesson", images=1)
		frappe.set_user(self.teacher.name)
		homework = homework_api.save_homework(
			title="F41 mixed",
			days=7,
			items=[
				{"source_type": "Lesson", "name": lesson},
				{"source_type": "Folder", "name": folder},
			],
		)["name"]
		assignment = self.issue(homework)
		doc = frappe.get_doc("LMS Homework Assignment", assignment)
		self.assertEqual(doc.total_requirements, 2)
		frappe.set_user(self.student.name)
		homework_service.record_lesson_opened(lesson)
		homework_service.record_folder_image_opened(
			folder,
			frappe.get_all("Folder Image Reference", {"parent": folder}, pluck="image")[0],
		)
		detail = homework_api.get_homework_assignment(assignment)
		self.assertEqual(detail["status"], "Review")


if __name__ == "__main__":
	unittest.main()
