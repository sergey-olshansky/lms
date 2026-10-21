# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""The single server-side resolver for homework sources (task #35 spec, section 3.4).

Everything that turns course structure into selectable, assignable homework items
lives here: the courses a teacher may pick from, the course tree with embedded
quizzes, the expansion of a selection into leaf requirements, and the pre-assignment
access check for one student. No Vue page re-implements the tree.

Tree depth: the builder is depth-agnostic on purpose. Today's chapters are a flat
list on the course (Course -> Chapter Reference -> Lesson Reference); when task
#28's nested chapters land, ``_chapter_children`` is the one place to extend.
"""

from __future__ import annotations

import frappe
from frappe import _

from lms.lms.permissions import (
	can_access_assessment,
	is_site_administrator,
)
from lms.lms.utils import (
	can_modify_course,
	compute_locked_lessons,
	get_membership,
	get_ordered_lesson_rows,
)

# Requirement types stored on LMS Homework Requirement. "Reference" rows are
# addressable materials without an automatic condition (a standalone Assignment):
# shown in the checklist as links, excluded from totals and auto-review.
REQUIREMENT_OPEN_LESSON = "Open Lesson"
REQUIREMENT_PASS_QUIZ = "Pass Quiz"
REQUIREMENT_REFERENCE = "Reference"


def get_assignable_courses() -> list[dict]:
	"""Courses the current teacher may pick homework materials from.

	Moderators and site administrators reach every course; a Course Creator reaches
	the courses they instruct. Other users get nothing: another teacher's closed
	courses never open here (spec 3.4).
	"""
	user = frappe.session.user
	if is_site_administrator(user) or "Moderator" in frappe.get_roles(user):
		return frappe.get_all("LMS Course", fields=["name", "title"], order_by="title")

	instructor = frappe.qb.DocType("Course Instructor")
	names = (
		frappe.qb.from_(instructor)
		.select(instructor.parent)
		.where((instructor.instructor == user) & (instructor.parenttype == "LMS Course"))
		.distinct()
	).run(pluck=True)
	if not names:
		return []
	return frappe.get_all(
		"LMS Course", filters={"name": ("in", names)}, fields=["name", "title"], order_by="title"
	)


def can_source_from(course: str) -> bool:
	"""Whether the session user may read this course's tree for homework selection."""
	if not isinstance(course, str) or not course:
		return False
	if is_site_administrator() or "Moderator" in frappe.get_roles():
		return True
	return bool(can_modify_course(course))


def get_course_source_tree(course: str) -> dict:
	"""One course's structure for the material picker.

	Shape: ``{course: {name, title}, nodes: [chapter|quiz|assignment, ...]}`` where a
	chapter node carries ``children`` (sub-chapters today: none; lessons) and a lesson
	node carries its student-visible embedded quizzes plus whether an Assignment is
	embedded. Empty chapters stay in the tree so the teacher sees them, but they are
	marked ``assignable: False``: an empty container is not homework work (spec 3.4.5).
	"""
	if not can_source_from(course):
		frappe.throw(_("You cannot pick materials from this course."), frappe.PermissionError)

	course_title = frappe.db.get_value("LMS Course", course, "title")
	chapters = _course_chapters(course)
	lesson_rows = _chapter_lesson_rows([c["name"] for c in chapters])
	quizzes_by_lesson = _embedded_quizzes_by_lesson(course)
	assignments_by_lesson = _embedded_assignments_by_lesson(course)

	lesson_nodes: dict[str, dict] = {}
	for row in lesson_rows:
		lesson_nodes[row.name] = {
			"key": f"lesson:{row.name}",
			"type": "lesson",
			"name": row.name,
			"title": row.title,
			"chapter": row.chapter_name,
			"quizzes": quizzes_by_lesson.get(row.name, []),
			"has_assignment": row.name in assignments_by_lesson,
			"assignable": True,
		}

	for chapter in chapters:
		chapter["key"] = f"chapter:{chapter['name']}"
		chapter["type"] = "chapter"
		chapter["children"] = [
			lesson_nodes[row.name] for row in lesson_rows if row.chapter_name == chapter["name"]
		] + _chapter_children(chapter["name"])
		chapter["assignable"] = any(child.get("assignable") for child in chapter["children"])

	standalone = _standalone_nodes(course, quizzes_by_lesson, assignments_by_lesson)

	return {
		"course": {"name": course, "title": course_title or course},
		"nodes": chapters + standalone,
	}


def _course_chapters(course: str) -> list[dict]:
	reference = frappe.qb.DocType("Chapter Reference")
	chapter_table = frappe.qb.DocType("Course Chapter")
	rows = (
		frappe.qb.from_(reference)
		.join(chapter_table)
		.on(chapter_table.name == reference.chapter)
		.select(chapter_table.name.as_("name"), chapter_table.title.as_("title"))
		.where(reference.parent == course)
		.orderby(reference.idx)
	).run(as_dict=True)
	return [{"name": row.name, "title": row.title} for row in rows]


def _chapter_children(chapter: str) -> list[dict]:
	"""Sub-chapters of a chapter. The current schema has none; task #28's nested
	chapters plug in exactly here, so nothing else in the resolver assumes depth."""
	if not frappe.get_meta("Course Chapter").has_field("parent_chapter"):
		return []
	rows = frappe.get_all(
		"Course Chapter",
		filters={"parent_chapter": chapter},
		fields=["name", "title"],
		order_by="idx",
	)
	return [
		{"key": f"chapter:{row.name}", "type": "chapter", "name": row.name, "title": row.title}
		for row in rows
	]


def _chapter_lesson_rows(chapter_names: list[str]) -> list:
	if not chapter_names:
		return []
	reference = frappe.qb.DocType("Lesson Reference")
	lesson = frappe.qb.DocType("Course Lesson")
	return (
		frappe.qb.from_(reference)
		.join(lesson)
		.on(lesson.name == reference.lesson)
		.select(lesson.name, lesson.title, reference.parent.as_("chapter_name"))
		.where(reference.parenttype == "Course Chapter")
		.where(reference.parent.isin(chapter_names))
		.orderby(reference.parent)
		.orderby(reference.idx)
	).run(as_dict=True)


def _embedded_quizzes_by_lesson(course: str) -> dict[str, list[dict]]:
	"""Student-visible quizzes embedded in each lesson of the course, from the
	queryable placement index (Course Lesson.assessments), not from HTML."""
	lessons = frappe.get_all("Course Lesson", {"course": course}, pluck="name")
	if not lessons:
		return {}
	rows = frappe.get_all(
		"LMS Lesson Assessment",
		filters={
			"parent": ("in", lessons),
			"parenttype": "Course Lesson",
			"assessment_type": "LMS Quiz",
			"instructor_only": 0,
		},
		fields=["parent", "assessment_name"],
		order_by="idx",
	)
	titles = _titles("LMS Quiz", [row.assessment_name for row in rows])
	by_lesson: dict[str, list[dict]] = {}
	for row in rows:
		quizzes = by_lesson.setdefault(row.parent, [])
		if not any(q["name"] == row.assessment_name for q in quizzes):
			# The same quiz embedded twice in one lesson is one requirement
			# (spec 3.4: one pass closes that quiz in that lesson).
			quizzes.append(
				{"name": row.assessment_name, "title": titles.get(row.assessment_name, row.assessment_name)}
			)
	return by_lesson


def _embedded_assignments_by_lesson(course: str) -> dict[str, list[str]]:
	lessons = frappe.get_all("Course Lesson", {"course": course}, pluck="name")
	if not lessons:
		return {}
	rows = frappe.get_all(
		"LMS Lesson Assessment",
		filters={
			"parent": ("in", lessons),
			"parenttype": "Course Lesson",
			"assessment_type": "LMS Assignment",
			"instructor_only": 0,
		},
		fields=["parent", "assessment_name"],
	)
	by_lesson: dict[str, list[str]] = {}
	for row in rows:
		by_lesson.setdefault(row.parent, []).append(row.assessment_name)
	return by_lesson


def _standalone_nodes(course: str, quizzes_by_lesson: dict, assignments_by_lesson: dict) -> list[dict]:
	"""Quizzes and Assignments stamped with this course but not embedded in any of
	its lessons -- addressable on their own (spec 3.4)."""
	embedded_quizzes = {q["name"] for rows in quizzes_by_lesson.values() for q in rows}
	embedded_assignments = {a for rows in assignments_by_lesson.values() for a in rows}

	nodes = []
	for quiz in frappe.get_all(
		"LMS Quiz", filters={"course": course}, fields=["name", "title"], order_by="title"
	):
		if quiz.name not in embedded_quizzes:
			nodes.append(
				{
					"key": f"quiz:{quiz.name}",
					"type": "quiz",
					"name": quiz.name,
					"title": quiz.title,
					"assignable": True,
				}
			)
	for assignment in frappe.get_all(
		"LMS Assignment", filters={"course": course}, fields=["name", "title"], order_by="title"
	):
		if assignment.name not in embedded_assignments:
			nodes.append(
				{
					"key": f"assignment:{assignment.name}",
					"type": "assignment",
					"name": assignment.name,
					"title": assignment.title,
					"assignable": True,
				}
			)
	return nodes


def _titles(doctype: str, names: list[str]) -> dict[str, str]:
	names = list({name for name in names if name})
	if not names:
		return {}
	rows = frappe.get_all(doctype, filters={"name": ("in", names)}, fields=["name", "title"])
	return {row.name: row.title for row in rows}


# --- Selection normalization (spec 3.4, 6.4) ----------------------------------


def normalize_selection(selection: list[dict]) -> list[dict]:
	"""A confirmed picker selection -> deduplicated template item rows.

	The picker sends one row per selected leaf (lesson / standalone quiz / standalone
	assignment) with its course context and readable path. Selecting a parent and
	its child both simply resolves to the same leaf, and the dedup by (type, name)
	keeps one instance (A07). Containers never survive here: only assignable leaves.
	"""
	items: dict[tuple, dict] = {}
	for entry in selection or []:
		source_type = entry.get("source_type")
		name = entry.get("name")
		if source_type not in ("Lesson", "Quiz", "Assignment") or not name:
			continue
		course = entry.get("course")
		title = entry.get("title") or name
		chapter = entry.get("chapter") or ""
		path = entry.get("path") or _display_path(course, chapter, title)
		items[(source_type, name)] = {
			"source_type": source_type,
			"lesson": name if source_type == "Lesson" else None,
			"quiz": name if source_type == "Quiz" else None,
			"assignment": name if source_type == "Assignment" else None,
			"course": course,
			"label": title,
			"path": path,
			"chapter_title": chapter,
		}
	return list(items.values())


def expand_requirements(items: list) -> list[dict]:
	"""Template items -> the frozen requirement rows of one assignment (spec 8.2).

	A lesson becomes one Open Lesson requirement plus one Pass Quiz requirement per
	student-visible quiz embedded in it at issue time. A standalone quiz becomes one
	Pass Quiz requirement. A standalone Assignment becomes a Reference row: its own
	submission UI keeps working, but no automatic condition is invented for it
	(spec 6.1). The same quiz embedded in two selected lessons yields two rows --
	both paths stay for navigation, and one passing submission satisfies both (spec 3.4).

	Chapter titles are snapshotted from the lesson's own chapter at issue time, so the
	checklist grouping stays readable even if the course is restructured later.
	"""
	rows: list[dict] = []
	seen_lessons: set[str] = set()

	for item in items:
		if item.get("source_type") == "Lesson" and item.get("lesson") and item.lesson not in seen_lessons:
			seen_lessons.add(item.lesson)
			lesson_title = item.get("label") or item.lesson
			chapter_title = _chapter_title_of_lesson(item.lesson)
			base_path = item.get("path") or lesson_title
			rows.append(
				{
					"requirement_type": REQUIREMENT_OPEN_LESSON,
					"course": item.get("course"),
					"chapter_title": chapter_title,
					"lesson": item.lesson,
					"quiz": None,
					"reference_assignment": None,
					"label": lesson_title,
					"path": base_path,
				}
			)
			for quiz in _lesson_quizzes(item.lesson):
				rows.append(
					{
						"requirement_type": REQUIREMENT_PASS_QUIZ,
						"course": item.get("course"),
						"chapter_title": chapter_title,
						"lesson": item.lesson,
						"quiz": quiz["name"],
						"reference_assignment": None,
						"label": quiz["title"],
						"path": f"{base_path} / {quiz['title']}",
					}
				)
		elif item.get("source_type") == "Quiz" and item.get("quiz"):
			rows.append(
				{
					"requirement_type": REQUIREMENT_PASS_QUIZ,
					"course": item.get("course"),
					"chapter_title": "",
					"lesson": None,
					"quiz": item.quiz,
					"reference_assignment": None,
					"label": item.get("label") or item.quiz,
					"path": item.get("path") or item.quiz,
				}
			)
		elif item.get("source_type") == "Assignment" and item.get("assignment"):
			rows.append(
				{
					"requirement_type": REQUIREMENT_REFERENCE,
					"course": item.get("course"),
					"chapter_title": "",
					"lesson": None,
					"quiz": None,
					"reference_assignment": item.assignment,
					"label": item.get("label") or item.assignment,
					"path": item.get("path") or item.assignment,
				}
			)
	return rows


def _chapter_title_of_lesson(lesson: str) -> str:
	chapter = frappe.db.get_value("Course Lesson", lesson, "chapter")
	if not chapter:
		return ""
	return frappe.db.get_value("Course Chapter", chapter, "title") or ""


def _lesson_quizzes(lesson: str) -> list[dict]:
	rows = frappe.get_all(
		"LMS Lesson Assessment",
		filters={
			"parent": lesson,
			"parenttype": "Course Lesson",
			"assessment_type": "LMS Quiz",
			"instructor_only": 0,
		},
		fields=["assessment_name"],
		order_by="idx",
	)
	names: list[str] = []
	for row in rows:
		if row.assessment_name not in names:
			names.append(row.assessment_name)
	if not names:
		return []
	titles = _titles("LMS Quiz", names)
	return [{"name": name, "title": titles.get(name, name)} for name in names]


def _display_path(course: str, chapter: str, title: str) -> str:
	parts = []
	course_title = frappe.db.get_value("LMS Course", course, "title") if course else None
	if course_title:
		parts.append(course_title)
	if chapter:
		chapter_title = frappe.db.get_value("Course Chapter", chapter, "title")
		if chapter_title:
			parts.append(chapter_title)
	parts.append(title)
	return " / ".join(parts)


# --- Pre-assignment validation (spec section 4) --------------------------------


def validate_sources_for_student(items: list, student: str) -> list[str]:
	"""Why this composition cannot be issued to this student. Empty list = allowed.

	Issuing never grants course access implicitly and never bypasses the sequential
	lesson gate: a missing enrollment or a locked lesson blocks with a reason the
	teacher can act on (A10).
	"""
	reasons: list[str] = []
	courses = {item.course for item in items if item.course}

	for course in courses:
		if not get_membership(course, student):
			course_title = frappe.db.get_value("LMS Course", course, "title") or course
			reasons.append(_("Student is not enrolled in the course {0}.").format(frappe.bold(course_title)))

	locked = _locked_lessons_for_student(courses, student)
	if locked:
		titles = _titles("Course Lesson", list(locked))
		for lesson in sorted(locked, key=lambda name: titles.get(name, name)):
			reasons.append(
				_("Lesson {0} is locked by sequential course access.").format(
					frappe.bold(titles.get(lesson, lesson))
				)
			)

	for item in items:
		if item.source_type == "Lesson":
			if item.lesson and not frappe.db.exists("Course Lesson", item.lesson):
				reasons.append(_("Lesson {0} no longer exists.").format(frappe.bold(item.label)))
		elif item.source_type == "Quiz":
			if item.quiz and not frappe.db.exists("LMS Quiz", item.quiz):
				reasons.append(_("Quiz {0} no longer exists.").format(frappe.bold(item.label)))
			elif item.quiz and not can_access_assessment("LMS Quiz", item.quiz, user=student):
				reasons.append(
					_("Quiz {0} is not available to this student.").format(frappe.bold(item.label))
				)
		elif item.source_type == "Assignment":
			if item.assignment and not frappe.db.exists("LMS Assignment", item.assignment):
				reasons.append(_("Assignment {0} no longer exists.").format(frappe.bold(item.label)))
	return reasons


def _locked_lessons_for_student(courses: set, student: str) -> set:
	"""Lesson names the student may not open yet, across the composition's courses."""
	locked: set = set()
	for course in courses:
		if not frappe.db.get_value("LMS Course", course, "enforce_lesson_completion"):
			continue
		if not get_membership(course, student):
			continue
		rows = get_ordered_lesson_rows(course)
		completed = set(
			frappe.get_all(
				"LMS Course Progress",
				filters={
					"course": course,
					"member": student,
					"status": "Complete",
					"lesson": ("in", [row.name for row in rows]),
				},
				pluck="lesson",
			)
		)
		locked |= compute_locked_lessons([row.name for row in rows], completed)
	return locked
