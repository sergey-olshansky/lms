# Copyright (c) 2026, and contributors
# For license information, please see license.txt

"""Task 28 — course section tree, up to 4 structural levels.

Covers the owner-confirmed rules: depth 4 counted from the first section under
the course (the course root and lessons never count), mixed lesson/section
children in one order, lessons legal at every level, no migration of existing
courses, and the depth gate enforced on every write path — Desk-style saves,
the section APIs, and the course archive import.
"""

import json
import tempfile
import zipfile
from pathlib import Path

import frappe
from frappe.tests.utils import IntegrationTestCase

from lms.lms.api import delete_chapter, move_section, upsert_chapter, update_section_index
from lms.lms.course_import_export import import_course_zip
from lms.lms.test_helpers import BaseTestUtils
from lms.lms.utils import (
	get_course_outline,
	get_lesson,
	get_lesson_count,
	get_lesson_index,
	get_neighbour_lesson,
	get_ordered_lesson_rows,
)

STUDENT = "tree-student@example.com"


class TestCourseSectionTree(BaseTestUtils):
	def setUp(self):
		super().setUp()
		self.course = self._create_course("Section Tree Course")
		self.instructor = self.course.instructors[0].instructor

	# -- fixtures ---------------------------------------------------------

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
		return chapter

	def attach_to_course(self, chapter, idx):
		return self._create_chapter_reference(self.course.name, chapter.name, idx=idx)

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

	def attach_lesson_row(self, chapter, lesson, idx):
		row = frappe.new_doc("Lesson Reference")
		row.update(
			{
				"lesson": lesson.name,
				"idx": idx,
				"parent": chapter.name,
				"parenttype": "Course Chapter",
				"parentfield": "lessons",
			}
		)
		row.insert()

	def flat_course(self):
		"""A legacy course exactly as it existed before task 28."""
		ch1 = self._create_chapter("Flat One", self.course.name)
		ch2 = self._create_chapter("Flat Two", self.course.name)
		self.attach_to_course(ch1, 1)
		self.attach_to_course(ch2, 2)
		l1 = self._create_lesson("Flat A", ch1.name, self.course.name)
		l2 = self._create_lesson("Flat B", ch1.name, self.course.name)
		l3 = self._create_lesson("Flat C", ch2.name, self.course.name)
		self.attach_lesson_row(ch1, l1, 1)
		self.attach_lesson_row(ch1, l2, 2)
		self.attach_lesson_row(ch2, l3, 1)
		return ch1, ch2

	# -- depth validation (criterion 1) -----------------------------------

	def test_four_levels_save_and_fifth_is_rejected(self):
		block = self.make_chapter("Block")
		chapter = self.make_chapter("Chapter", parent_section=block.name)
		part = self.make_chapter("Part", parent_section=chapter.name)
		deep = self.make_chapter("Deep", parent_section=part.name)
		self.attach_to_course(block, 1)

		fifth = frappe.new_doc("Course Chapter")
		fifth.update(
			{
				"course": self.course.name,
				"title": "Too Deep",
				"parent_section": deep.name,
			}
		)
		self.assertRaises(frappe.ValidationError, fifth.insert)

	def test_lesson_is_allowed_at_level_four(self):
		"""Lessons are leaves: legal under a level-4 section (criterion 4)."""
		block = self.make_chapter("L4 Block")
		chapter = self.make_chapter("L4 Chapter", parent_section=block.name)
		part = self.make_chapter("L4 Part", parent_section=chapter.name)
		deep = self.make_chapter("L4 Deep", parent_section=part.name)
		self.attach_to_course(block, 1)
		lesson = self._create_lesson("Deep Lesson", deep.name, self.course.name)
		self.attach_lesson_row(deep, lesson, 1)

		outline = get_course_outline(self.course.name)
		deep_node = outline[0]["sections"][0]["sections"][0]["sections"][0]
		self.assertEqual(deep_node["level"], 4)
		self.assertEqual(deep_node["lessons"][0]["name"], lesson.name)

	def test_scorm_sections_stay_leaves(self):
		scorm = self.make_chapter("Scorm Leaf")
		scorm.is_scorm_package = 1
		scorm.save()
		self.attach_to_course(scorm, 1)

		nested = frappe.new_doc("Course Chapter")
		nested.update(
			{
				"course": self.course.name,
				"title": "Nested in SCORM",
				"parent_section": scorm.name,
			}
		)
		self.assertRaises(frappe.ValidationError, nested.insert)

		scorm_chapter = self.make_chapter("Scorm Nested Try")
		self.attach_to_course(scorm_chapter, 2)
		scorm_chapter.parent_section = scorm.name
		self.assertRaises(frappe.ValidationError, scorm_chapter.save)

	def test_parent_must_belong_to_the_same_course(self):
		other_course = self._create_course("Section Tree Other Course")
		other_root = self.make_chapter("Other Course Root")
		other_root.course = other_course.name
		other_root.save()
		self._create_chapter_reference(other_course.name, other_root.name, idx=1)

		mixed = frappe.new_doc("Course Chapter")
		mixed.update(
			{
				"course": self.course.name,
				"title": "Cross course",
				"parent_section": other_root.name,
			}
		)
		self.assertRaises(frappe.ValidationError, mixed.insert)

	# -- mixed children in one order (criterion 2) ------------------------

	def test_mixed_children_keep_one_manual_order(self):
		block = self.make_chapter("Mixed Block")
		self.attach_to_course(block, 1)
		first = self._create_lesson("First", block.name, self.course.name)
		second = self._create_lesson("Second", block.name, self.course.name)
		nested = self.make_chapter("Mixed Nested", parent_section=block.name)
		self.attach_lesson_row(block, first, 1)
		self.attach_section_row(block, nested, 2)
		self.attach_lesson_row(block, second, 3)
		nested_lesson = self._create_lesson("Nested Lesson", nested.name, self.course.name)
		self.attach_lesson_row(nested, nested_lesson, 1)

		outline = get_course_outline(self.course.name)
		node = outline[0]
		self.assertEqual(node["name"], block.name)
		self.assertEqual([l["name"] for l in node["lessons"]], [first.name, second.name])
		self.assertEqual([s["name"] for s in node["sections"]], [nested.name])
		# Positions report the shared child-table order: lesson, section, lesson.
		self.assertEqual([l["position"] for l in node["lessons"]], [1, 3])
		self.assertEqual(node["sections"][0]["position"], 2)
		self.assertEqual(node["lesson_count"], 2)
		self.assertEqual(node["section_count"], 1)
		self.assertEqual(node["total_lesson_count"], 3)

	def test_document_order_walks_the_tree_depth_first(self):
		block = self.make_chapter("Walk Block")
		self.attach_to_course(block, 1)
		first = self._create_lesson("Walk First", block.name, self.course.name)
		second = self._create_lesson("Walk Second", block.name, self.course.name)
		nested = self.make_chapter("Walk Nested", parent_section=block.name)
		self.attach_lesson_row(block, first, 1)
		self.attach_section_row(block, nested, 2)
		self.attach_lesson_row(block, second, 3)
		nested_lesson = self._create_lesson("Walk Nested Lesson", nested.name, self.course.name)
		self.attach_lesson_row(nested, nested_lesson, 1)

		rows = get_ordered_lesson_rows(self.course.name)
		self.assertEqual(
			[r.name for r in rows], [first.name, nested_lesson.name, second.name]
		)

	def test_numbering_is_the_section_path(self):
		block1 = self.make_chapter("Number Block One")
		block2 = self.make_chapter("Number Block Two")
		self.attach_to_course(block1, 1)
		self.attach_to_course(block2, 2)
		nested = self.make_chapter("Number Nested", parent_section=block2.name)
		self.attach_section_row(block2, nested, 1)
		lesson = self._create_lesson("Numbered", nested.name, self.course.name)
		self.attach_lesson_row(nested, lesson, 1)

		self.assertEqual(get_lesson_index(lesson.name), "2-1-1")
		resolved = get_lesson(self.course.name, "2-1", "1")
		self.assertEqual(resolved["name"], lesson.name)

	def test_neighbours_cross_section_boundaries(self):
		block = self.make_chapter("Neighbour Block")
		self.attach_to_course(block, 1)
		first = self._create_lesson("Neighbour First", block.name, self.course.name)
		second = self._create_lesson("Neighbour Second", block.name, self.course.name)
		nested = self.make_chapter("Neighbour Nested", parent_section=block.name)
		self.attach_lesson_row(block, first, 1)
		self.attach_section_row(block, nested, 2)
		self.attach_lesson_row(block, second, 3)
		nested_lesson = self._create_lesson("Neighbour Nested Lesson", nested.name, self.course.name)
		self.attach_lesson_row(nested, nested_lesson, 1)

		self.assertEqual(
			get_neighbour_lesson(self.course.name, "1-1", "1"),
			{"prev": None, "next": "1-1-1"},
		)
		self.assertEqual(
			get_neighbour_lesson(self.course.name, "1-1", "1"),
			{"prev": "1-1", "next": "1-2"},
		)

	def test_lesson_count_includes_nested_lessons(self):
		block = self.make_chapter("Count Block")
		self.attach_to_course(block, 1)
		top = self._create_lesson("Count Top", block.name, self.course.name)
		nested = self.make_chapter("Count Nested", parent_section=block.name)
		self.attach_lesson_row(block, top, 1)
		self.attach_section_row(block, nested, 2)
		deep = self._create_lesson("Count Deep", nested.name, self.course.name)
		self.attach_lesson_row(nested, deep, 1)

		self.assertEqual(get_lesson_count(self.course.name), 2)

	# -- legacy invariance (criterion 3) ----------------------------------

	def test_flat_course_outline_is_unchanged(self):
		ch1, ch2 = self.flat_course()

		outline = get_course_outline(self.course.name)
		self.assertEqual([c["name"] for c in outline], [ch1.name, ch2.name])
		self.assertEqual(outline[0]["level"], 1)
		self.assertEqual(outline[0]["sections"], [])
		self.assertEqual([l["number"] for l in outline[0]["lessons"]], ["1-1", "1-2"])
		self.assertEqual([l["number"] for l in outline[1]["lessons"]], ["2-1"])
		# idx stays the Chapter Reference position for level-1 sections.
		self.assertEqual([c["idx"] for c in outline], [1, 2])

		rows = get_ordered_lesson_rows(self.course.name)
		self.assertEqual([r.number for r in rows], ["1-1", "1-2", "2-1"])

		resolved = get_lesson(self.course.name, "2", "1")
		self.assertEqual(resolved["number"], "2-1")

		self.assertEqual(
			get_neighbour_lesson(self.course.name, "1", "2"),
			{"prev": "1-1", "next": "2-1"},
		)
		self.assertEqual(get_lesson_count(self.course.name), 3)

	def test_no_migration_touches_existing_course_data(self):
		"""The schema grows nullable fields only; legacy rows stay as written."""
		ch1, ch2 = self.flat_course()

		for chapter in (ch1, ch2):
			stored = frappe.db.get_value("Course Chapter", chapter.name, "parent_section")
			self.assertIsNone(stored)

		rows = frappe.get_all(
			"Lesson Reference",
			{"parent": ["in", [ch1.name, ch2.name]]},
			["lesson", "section", "idx"],
			order_by="parent, idx",
		)
		for row in rows:
			self.assertIsNone(row.section)
			self.assertTrue(row.lesson)

	# -- section APIs -----------------------------------------------------

	def test_upsert_chapter_creates_nested_section(self):
		block = self.make_chapter("API Block")
		self.attach_to_course(block, 1)

		created = upsert_chapter(
			title="API Nested",
			course=self.course.name,
			is_scorm_package=False,
			parent_section=block.name,
		)
		self.assertEqual(frappe.db.get_value("Course Chapter", created.name, "parent_section"), block.name)

		rows = frappe.get_all(
			"Lesson Reference",
			{"parent": block.name, "section": ["is", "set"]},
			pluck="section",
			order_by="idx",
		)
		self.assertEqual(rows, [created.name])

	def test_move_section_enforces_the_depth_rule(self):
		block = self.make_chapter("Move Block")
		chapter = self.make_chapter("Move Chapter", parent_section=block.name)
		part = self.make_chapter("Move Part", parent_section=chapter.name)
		self.attach_to_course(block, 1)

		# part (height 1) under a level-3 section would sit at level 4: legal.
		other_root = self.make_chapter("Move Other Root")
		other_mid = self.make_chapter("Move Other Mid", parent_section=other_root.name)
		self.attach_to_course(other_root, 2)

		move_section(part.name, other_mid.name)
		self.assertEqual(
			frappe.db.get_value("Course Chapter", part.name, "parent_section"),
			other_mid.name,
		)

		# Moving the block's whole subtree (height 4) under any section is refused.
		self.assertRaises(frappe.ValidationError, move_section, block.name, other_mid.name)
		self.assertRaises(frappe.ValidationError, move_section, block.name, part.name)

	def test_move_section_to_root_and_back(self):
		block = self.make_chapter("Root Move Block")
		nested = self.make_chapter("Root Move Nested", parent_section=block.name)
		self.attach_to_course(block, 1)

		move_section(nested.name, None)
		self.assertIsNone(frappe.db.get_value("Course Chapter", nested.name, "parent_section"))
		self.assertTrue(
			frappe.db.exists("Chapter Reference", {"chapter": nested.name, "parent": self.course.name})
		)

		move_section(nested.name, block.name)
		self.assertEqual(
			frappe.db.get_value("Course Chapter", nested.name, "parent_section"),
			block.name,
		)
		self.assertFalse(
			frappe.db.exists("Chapter Reference", {"chapter": nested.name, "parent": self.course.name})
		)

	def test_update_section_index_reorders_among_mixed_siblings(self):
		block = self.make_chapter("Reorder Block")
		self.attach_to_course(block, 1)
		first = self._create_lesson("Reorder First", block.name, self.course.name)
		second = self._create_lesson("Reorder Second", block.name, self.course.name)
		nested = self.make_chapter("Reorder Nested", parent_section=block.name)
		self.attach_lesson_row(block, first, 1)
		self.attach_section_row(block, nested, 2)
		self.attach_lesson_row(block, second, 3)

		# "Move down" swaps with the next child row, whatever kind it is.
		update_section_index(nested.name, block.name, 1)
		rows = frappe.get_all(
			"Lesson Reference", {"parent": block.name}, ["lesson", "section", "idx"], order_by="idx"
		)
		self.assertEqual([r.lesson for r in rows], [first.name, second.name])
		self.assertEqual(rows[2].section, nested.name)

	def test_unauthorized_writes_are_refused(self):
		block = self.make_chapter("Guard Block")
		self.attach_to_course(block, 1)
		nested = self.make_chapter("Guard Nested", parent_section=block.name)

		self._create_user(
			STUDENT,
			"Tree",
			"Student",
			[{"role": "LMS Student"}],
		)
		frappe.set_user(STUDENT)

		with self.assertRaises(frappe.PermissionError):
			upsert_chapter(
				title="Nope",
				course=self.course.name,
				is_scorm_package=False,
				parent_section=block.name,
			)

		with self.assertRaises(frappe.PermissionError):
			move_section(nested.name, None)

		with self.assertRaises(frappe.PermissionError):
			update_section_index(nested.name, block.name, 0)

		with self.assertRaises(frappe.PermissionError):
			delete_chapter(nested.name)

	def test_delete_chapter_removes_the_whole_subtree(self):
		block = self.make_chapter("Delete Block")
		nested = self.make_chapter("Delete Nested", parent_section=block.name)
		self.attach_to_course(block, 1)
		top = self._create_lesson("Delete Top", block.name, self.course.name)
		deep = self._create_lesson("Delete Deep", nested.name, self.course.name)
		self.attach_lesson_row(block, top, 1)
		self.attach_section_row(block, nested, 2)
		self.attach_lesson_row(nested, deep, 1)

		delete_chapter(block.name)

		self.assertFalse(frappe.db.exists("Course Chapter", block.name))
		self.assertFalse(frappe.db.exists("Course Chapter", nested.name))
		self.assertFalse(frappe.db.exists("Course Lesson", top.name))
		self.assertFalse(frappe.db.exists("Course Lesson", deep.name))
		self.assertFalse(
			frappe.db.exists("Lesson Reference", {"parent": ["in", [block.name, nested.name]]})
		)
		self.assertFalse(
			frappe.db.exists("Chapter Reference", {"chapter": block.name, "parent": self.course.name})
		)

	# -- import (criterion 1, every write path) ---------------------------

	def _zip_with_depth(self, depth: int) -> Path:
		"""A course archive whose chapter chain claims `depth` section levels."""
		chapters = []
		for level in range(1, depth + 1):
			old_name = f"{level:04d} Level {level}"
			chapters.append(
				{
					"name": old_name,
					"title": f"Import Level {level}",
					"course": "anything",
					"parent_section": None if level == 1 else f"{level - 1:04d} Level {level - 1}",
					"lessons": [],
				}
			)
		# Attach each child to its parent through the parent's child rows, the
		# way a real export serialises the tree.
		for level in range(1, depth):
			chapters[level - 1]["lessons"] = [
				{"section": f"{level + 1:04d} Level {level + 1}"}
			]

		fd, path = tempfile.mkstemp(suffix=".zip")
		with zipfile.ZipFile(path, "w") as archive:
			archive.writestr(
				"course.json",
				json.dumps(
					{
						"title": "Import Depth Course",
						"short_introduction": "Imported",
						"description": "Imported",
						"category": "Business",
						"published": 1,
					}
				),
			)
			for chapter in chapters:
				archive.writestr(
					f"chapters/{chapter['name']}.json",
					json.dumps(chapter),
				)
		return Path(path)

	def test_import_accepts_four_levels(self):
		path = self._zip_with_depth(4)
		course_name = import_course_zip(str(path))
		try:
			chapters = frappe.get_all(
				"Course Chapter", {"course": course_name}, ["name", "parent_section", "title"]
			)
			self.assertEqual(len(chapters), 4)
			roots = [c for c in chapters if not c.parent_section]
			self.assertEqual(len(roots), 1)
			deepest = [c for c in chapters if c.title == "Import Level 4"][0]
			self.assertTrue(deepest.parent_section)
		finally:
			path.unlink(missing_ok=True)

	def test_import_refuses_five_levels(self):
		path = self._zip_with_depth(5)
		try:
			with self.assertRaises(frappe.ValidationError):
				import_course_zip(str(path))
		finally:
			path.unlink(missing_ok=True)
		# Nothing of the refused import survives: the whole request rolls back.
		self.assertFalse(
			frappe.db.exists("LMS Course", {"title": "Import Depth Course"})
		)
