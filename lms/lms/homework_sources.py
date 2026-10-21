# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""The single server-side resolver for homework sources (task #35 spec, section 3.4).

Everything that turns course structure into selectable, assignable homework items
lives here: the courses a teacher may pick from, the course tree with embedded
quizzes, the expansion of a selection into leaf requirements, and the pre-assignment
access check for one student. No Vue page re-implements the tree.

Tree depth: task #28's sections nest up to 4 structural levels with lessons and
sub-sections mixed in one child table; ``get_course_source_tree`` walks that real
structure, and a legacy flat course comes out of the same walk two levels deep.
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

# Requirement types stored on LMS Homework Requirement. A standalone Assignment
# is a checkable opening condition (R10): the material is real and addressable,
# and spec 6.1 forbids inventing an automatic assessment of the written answer.
# "Reference" remains readable for rows issued before that rule.
REQUIREMENT_OPEN_LESSON = "Open Lesson"
REQUIREMENT_PASS_QUIZ = "Pass Quiz"
REQUIREMENT_OPEN_ASSIGNMENT = "Open Assignment"
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
	"""One course's structure for the material picker, on task #28's real tree.

	Shape: ``{course: {name, title}, nodes: [section|quiz|assignment, ...]}``. Root
	sections come from the course's Chapter Reference rows in order; a section's
	children are its Lesson Reference child rows in idx order -- each row either a
	lesson or a nested section (``section`` set), mixed freely, up to 4 structural
	levels. A lesson node carries its student-visible embedded quizzes; an empty
	section stays visible but is ``assignable: False``: an empty container is not
	homework work (spec 3.4.5). Old flat courses walk the same code and come out
	two levels deep, so one adapter serves both (A09).
	"""
	if not can_source_from(course):
		frappe.throw(_("You cannot pick materials from this course."), frappe.PermissionError)

	from lms.lms.utils import MAX_SECTION_DEPTH

	course_title = frappe.db.get_value("LMS Course", course, "title")
	section_titles = {
		row.name: row.title
		for row in frappe.get_all("Course Chapter", filters={"course": course}, fields=["name", "title"])
	}
	root_rows = frappe.get_all(
		"Chapter Reference",
		filters={"parent": course},
		fields=["chapter", "idx"],
		order_by="idx",
	)
	all_section_names = list(section_titles)
	child_rows = frappe.get_all(
		"Lesson Reference",
		filters={"parent": ("in", all_section_names), "parenttype": "Course Chapter"},
		fields=["parent", "idx", "lesson", "section"],
		order_by="parent, idx",
	)
	children_by_section: dict[str, list] = {}
	for row in child_rows:
		children_by_section.setdefault(row.parent, []).append(row)

	lesson_names = [row.lesson for row in child_rows if row.lesson]
	lesson_titles = _titles("Course Lesson", lesson_names)
	quizzes_by_lesson = _embedded_quizzes_by_lesson(course)
	assignments_by_lesson = _embedded_assignments_by_lesson(course)

	def lesson_node(name: str, parent_section: str) -> dict:
		return {
			"key": f"lesson:{name}",
			"type": "lesson",
			"name": name,
			"title": lesson_titles.get(name, name),
			"chapter": parent_section,
			"quizzes": quizzes_by_lesson.get(name, []),
			"has_assignment": name in assignments_by_lesson,
			"assignable": True,
		}

	def section_node(name: str, seen: set, depth: int) -> dict | None:
		"""Depth-first over the mixed child rows; the depth cap and seen-set only
		bound corrupt data, the same stance get_outline_sections takes."""
		if name in seen or depth > MAX_SECTION_DEPTH:
			return None
		children = []
		for row in children_by_section.get(name, []):
			if row.section:
				child = section_node(row.section, seen | {name}, depth + 1)
				if child:
					children.append(child)
			elif row.lesson and row.lesson in lesson_titles:
				children.append(lesson_node(row.lesson, name))
		return {
			"key": f"chapter:{name}",
			"type": "chapter",
			"name": name,
			"title": section_titles.get(name, name),
			"children": children,
			"assignable": any(child.get("assignable") for child in children),
		}

	nodes = []
	for row in root_rows:
		if row.chapter not in section_titles:
			continue
		node = section_node(row.chapter, set(), 1)
		if node:
			nodes.append(node)

	standalone = _standalone_nodes(course, quizzes_by_lesson, assignments_by_lesson)
	return {
		"course": {"name": course, "title": course_title or course},
		"nodes": nodes + standalone,
	}


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


def canonicalize_selection(selection: list[dict]) -> list[dict]:
	"""A confirmed picker selection -> canonical, deduplicated template items.

	Nothing the client sent about a source is trusted (R04): existence, the real
	course, the real title and the readable path all come from the database, and
	every course must be one the session teacher may source from -- enforced
	right here, not only later at issuance (B01). Unknown source types and
	dangling or unreachable ids are refused with a reason, never dropped -- a
	silently vanishing mandatory material must not look like a valid
	composition. Selecting a parent and its child both resolves to the same
	leaf, and the dedup by (type, name) keeps one instance (A07).
	"""
	if selection is None:
		selection = []
	if not isinstance(selection, list):
		frappe.throw(_("The material selection must be a list."))

	items: dict[tuple, dict] = {}
	for entry in selection:
		source_type = entry.get("source_type") if isinstance(entry, dict) else None
		name = entry.get("name") if isinstance(entry, dict) else None
		if source_type not in ("Lesson", "Quiz", "Assignment") or not name:
			frappe.throw(
				_("Unsupported material in the selection: {0}.").format(
					frappe.bold(str(source_type or name))
				),
				frappe.ValidationError,
			)
		key = (source_type, name)
		if key in items:
			continue
		item = _canonical_item(source_type, name)
		# B01: canonicalizing a material the session teacher cannot source from
		# would hand them a foreign course's title and path -- the access check
		# belongs to the resolution itself, not only to the later issue step.
		if not can_source_from(item["course"]):
			frappe.throw(
				_("You cannot pick materials from the course {0}.").format(
					frappe.bold(item["course"])
				),
				frappe.PermissionError,
			)
		items[key] = item
	return list(items.values())


def _canonical_item(source_type: str, name: str) -> dict:
	"""One source resolved from the database: existence, course, label, path."""
	if source_type == "Lesson":
		row = frappe.db.get_value("Course Lesson", name, ["name", "title", "course", "chapter"], as_dict=True)
		if not row:
			frappe.throw(_("Lesson {0} no longer exists.").format(frappe.bold(name)))
		chapter = (
			frappe.db.get_value("Course Chapter", row.chapter, ["title", "is_scorm_package"], as_dict=True)
			if row.chapter
			else None
		)
		if chapter and chapter.is_scorm_package:
			# SCORM packages are their own playback world; their internal tests never
			# become LMS quizzes (spec 3.4). Not selectable as homework material.
			frappe.throw(
				_("Lesson {0} is part of a SCORM package and cannot be homework material.").format(
					frappe.bold(row.title)
				)
			)
		return {
			"source_type": source_type,
			"lesson": name,
			"quiz": None,
			"assignment": None,
			"course": row.course,
			"label": row.title,
			"path": _display_path(row.course, chapter.title if chapter else None, row.title),
		}

	if source_type == "Quiz":
		row = frappe.db.get_value("LMS Quiz", name, ["name", "title", "course"], as_dict=True)
		if not row:
			frappe.throw(_("Quiz {0} no longer exists.").format(frappe.bold(name)))
		course = row.course or _course_of_placed("LMS Quiz", name)
		if not course:
			frappe.throw(_("Quiz {0} is not reachable from any course.").format(frappe.bold(row.title)))
		return {
			"source_type": source_type,
			"lesson": None,
			"quiz": name,
			"assignment": None,
			"course": course,
			"label": row.title,
			"path": _display_path(course, None, row.title),
		}

	row = frappe.db.get_value("LMS Assignment", name, ["name", "title", "course"], as_dict=True)
	if not row:
		frappe.throw(_("Assignment {0} no longer exists.").format(frappe.bold(name)))
	course = row.course or _course_of_placed("LMS Assignment", name)
	if not course:
		frappe.throw(_("Assignment {0} is not reachable from any course.").format(frappe.bold(row.title)))
	return {
		"source_type": source_type,
		"lesson": None,
		"quiz": None,
		"assignment": name,
		"course": course,
		"label": row.title,
		"path": _display_path(course, None, row.title),
	}


def _course_of_placed(assessment_type: str, name: str) -> str | None:
	"""The course of a lesson this assessment is embedded in, for items without
	their own course stamp."""
	lesson = frappe.db.get_value(
		"LMS Lesson Assessment",
		{"assessment_type": assessment_type, "assessment_name": name, "parenttype": "Course Lesson"},
		"parent",
	)
	if not lesson:
		return None
	return frappe.db.get_value("Course Lesson", lesson, "course")


def expand_requirements(items: list) -> list[dict]:
	"""Template items -> the frozen requirement rows of one assignment (spec 8.2).

	A lesson becomes one Open Lesson requirement plus one Pass Quiz requirement per
	student-visible quiz embedded in it at issue time, plus one Open Assignment
	per student-visible written assignment embedded in it (integration finding,
	round 3: on this stack members reach an assessment only through a
	student-visible lesson placement or a batch -- the course stamp alone grants
	authors only -- so an openable written-assignment requirement must ride the
	lesson that places it). A standalone quiz becomes one Pass Quiz requirement.
	A standalone stamped Assignment stays pickable for the author, but issuing it
	to a student is refused with a reason by ``validate_sources_for_student``
	until the student can actually reach it. The same quiz embedded in two
	selected lessons yields two rows -- both paths stay for navigation, and one
	passing submission satisfies both (spec 3.4).

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
			for assignment in _lesson_assignments(item.lesson):
				rows.append(
					{
						"requirement_type": REQUIREMENT_OPEN_ASSIGNMENT,
						"course": item.get("course"),
						"chapter_title": chapter_title,
						"lesson": item.lesson,
						"quiz": None,
						"reference_assignment": assignment["name"],
						"label": assignment["title"],
						"path": f"{base_path} / {assignment['title']}",
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
					"requirement_type": REQUIREMENT_OPEN_ASSIGNMENT,
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


def _lesson_assignments(lesson: str) -> list[dict]:
	"""Student-visible written assignments placed in this lesson: the openable
	requirement for them rides the lesson, since on this stack a member reaches
	an assessment through its placement (or a batch), never the course stamp."""
	rows = frappe.get_all(
		"LMS Lesson Assessment",
		filters={
			"parent": lesson,
			"parenttype": "Course Lesson",
			"assessment_type": "LMS Assignment",
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
	titles = _titles("LMS Assignment", names)
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
	teacher can act on (A10). Only the SELECTED materials gate the issue -- a
	locked lesson the composition does not name is not this homework's business
	(R05). Each course is re-resolved from the materials themselves (B01): the
	stored ``course`` column is display data and is never trusted here, so even a
	template row that somehow carries a forged course cannot widen access. Quizzes
	AND standalone assignments are checked through the app's real assessment
	access resolver.
	"""
	reasons: list[str] = []
	courses: set[str] = set()
	selected_lessons = {item.lesson for item in items if item.source_type == "Lesson" and item.lesson}

	for item in items:
		# B01: the real course of each item, read from the material row itself.
		if item.source_type == "Lesson" and item.lesson:
			course = frappe.db.get_value("Course Lesson", item.lesson, "course")
		elif item.source_type == "Quiz" and item.quiz:
			course = frappe.db.get_value("LMS Quiz", item.quiz, "course") or _course_of_placed(
				"LMS Quiz", item.quiz
			)
		elif item.source_type == "Assignment" and item.assignment:
			course = frappe.db.get_value("LMS Assignment", item.assignment, "course") or _course_of_placed(
				"LMS Assignment", item.assignment
			)
		else:
			course = None
		if course:
			courses.add(course)

	for course in courses:
		if not can_source_from(course):
			course_title = frappe.db.get_value("LMS Course", course, "title") or course
			reasons.append(
				_("You cannot assign materials from the course {0}.").format(frappe.bold(course_title))
			)
		if not get_membership(course, student):
			course_title = frappe.db.get_value("LMS Course", course, "title") or course
			reasons.append(_("Student is not enrolled in the course {0}.").format(frappe.bold(course_title)))

	locked = _locked_lessons_for_student(courses, student) & selected_lessons
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
			elif item.assignment and not can_access_assessment(
				"LMS Assignment", item.assignment, user=student
			):
				reasons.append(
					_("Assignment {0} is not available to this student.").format(
						frappe.bold(item.label)
					)
				)
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
