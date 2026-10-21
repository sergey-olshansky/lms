# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Whitelisted homework API (task #35 spec, section 9.4).

Semantic operation names; every entry re-checks authority server-side. Students
only ever read their own board and fire their own events; a ``status``, ``pass``
verdict or ``member`` from the payload is never trusted.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime

from lms.lms import homework_service, homework_sources
from lms.lms.homework_service import (
	STATUS_DONE,
	STATUS_IN_PROGRESS,
	STATUS_REVIEW,
	STATUS_TO_DO,
	compute_due_at,
	source_alive,
)
from lms.lms.schedule_utils import datetime_to_iso
from lms.lms.utils import get_membership

BOARD_PAGE_SIZE = 10
BOARD_STATUSES = [STATUS_TO_DO, STATUS_IN_PROGRESS, STATUS_REVIEW, STATUS_DONE]


# --- Library groups (spec 3.2) --------------------------------------------------


@frappe.whitelist()
def list_homework_groups() -> list[dict]:
	"""The session teacher's groups as a two-level tree, for filters and forms."""
	owner_scope = {"owner": frappe.session.user}
	if _is_privileged():
		owner_scope = {}
	rows = frappe.get_all(
		"LMS Homework Group",
		filters=owner_scope,
		fields=["name", "title", "parent_group"],
		order_by="title",
	)
	by_name = {row.name: row for row in rows}
	for row in rows:
		row["path"] = _group_path(row, by_name)
	return rows


def _group_path(row: dict, by_name: dict) -> str:
	parts = [row.title]
	parent = row.parent_group
	while parent and parent in by_name:
		parts.insert(0, by_name[parent].title)
		parent = by_name[parent].parent_group
	return " / ".join(parts)


@frappe.whitelist()
def save_homework_group(name: str | None = None, title: str = "", parent_group: str | None = None) -> dict:
	"""Create or rename/move a group. Depth, cycles and ownership are enforced by
	the doctype's validate (A02, A03)."""
	if name:
		doc = frappe.get_doc("LMS Homework Group", name)
	else:
		doc = frappe.new_doc("LMS Homework Group")
	doc.title = title
	doc.parent_group = parent_group or None
	doc.save()
	return {"name": doc.name, "title": doc.title, "parent_group": doc.parent_group}


@frappe.whitelist()
def delete_homework_group(name: str) -> dict:
	frappe.delete_doc("LMS Homework Group", name)
	return {"deleted": True}


# --- Library of compilations (spec 3.1, 3.3, 8.1) -------------------------------


@frappe.whitelist()
def get_homework_library(
	search: str = "",
	group: str | None = None,
	archived: bool = False,
	limit: int = 25,
	offset: int = 0,
) -> dict:
	"""The teacher's own table: search, group filter, pagination; server-side
	scoped to the owner (A01). Moderators see everything, as their role grants."""
	filters: dict = {"archived": 1 if archived else 0}
	if _is_teacher_scoped():
		filters["owner"] = frappe.session.user
	if search:
		filters["title"] = ("like", f"%{search}%")
	if group:
		filters["group"] = group

	total = frappe.db.count("LMS Homework", filters)
	rows = frappe.get_all(
		"LMS Homework",
		filters=filters,
		fields=["name", "title", "days", "group", "archived", "modified", "owner"],
		order_by="modified desc",
		limit_page_length=limit,
		limit_start=offset,
	)
	_compose_library_counts(rows)
	_group_titles(rows)
	return {"rows": rows, "total": total}


def _group_titles(rows: list) -> None:
	"""Fill ``group_title`` as the readable "Group / Subgroup" path, in two queries."""
	group_names = {row.group for row in rows if row.group}
	if not group_names:
		for row in rows:
			row["group_title"] = ""
		return
	groups = {
		row.name: row
		for row in frappe.get_all(
			"LMS Homework Group",
			filters={"name": ("in", list(group_names))},
			fields=["name", "title", "parent_group"],
		)
	}
	parent_names = {row.parent_group for row in groups.values() if row.parent_group}
	parents = (
		{
			row.name: row.title
			for row in frappe.get_all(
				"LMS Homework Group", filters={"name": ("in", list(parent_names))}, fields=["name", "title"]
			)
		}
		if parent_names
		else {}
	)
	for row in rows:
		group = groups.get(row.group)
		if not group:
			row["group_title"] = ""
			continue
		if group.parent_group and group.parent_group in parents:
			row["group_title"] = f"{parents[group.parent_group]} / {group.title}"
		else:
			row["group_title"] = group.title


def _compose_library_counts(rows: list) -> None:
	"""Materialize the «N lessons · M quizzes» column for one page, batched (R20):
	four queries per page, never one per row. Embedded quizzes are counted through
	the placement index, not per-lesson HTML; standalone assignments count as
	materials too (R10)."""
	template_names = [row.name for row in rows]
	if not template_names:
		return

	lessons_by_template: dict[str, set] = {}
	quizzes_by_template: dict[str, set] = {}
	assignments_by_template: dict[str, set] = {}
	lesson_names: set = set()
	for row in frappe.get_all(
		"LMS Homework Source",
		filters={"parent": ("in", template_names), "parenttype": "LMS Homework"},
		fields=["parent", "source_type", "lesson", "quiz", "assignment"],
	):
		if row.source_type == "Lesson" and row.lesson:
			lessons_by_template.setdefault(row.parent, set()).add(row.lesson)
			lesson_names.add(row.lesson)
		elif row.source_type == "Quiz" and row.quiz:
			quizzes_by_template.setdefault(row.parent, set()).add(row.quiz)
		elif row.source_type == "Assignment" and row.assignment:
			assignments_by_template.setdefault(row.parent, set()).add(row.assignment)

	embedded_by_lesson: dict[str, set] = {}
	if lesson_names:
		for placement in frappe.get_all(
			"LMS Lesson Assessment",
			filters={
				"parent": ("in", list(lesson_names)),
				"parenttype": "Course Lesson",
				"assessment_type": "LMS Quiz",
				"instructor_only": 0,
			},
			fields=["parent", "assessment_name"],
		):
			embedded_by_lesson.setdefault(placement.parent, set()).add(placement.assessment_name)

	issued_templates = set(
		frappe.get_all(
			"LMS Homework Assignment",
			filters={"homework": ("in", template_names)},
			pluck="homework",
		)
	)

	for row in rows:
		lessons = lessons_by_template.get(row.name, set())
		quizzes = quizzes_by_template.get(row.name, set())
		assignments = assignments_by_template.get(row.name, set())
		embedded = set().union(*(embedded_by_lesson.get(lesson, set()) for lesson in lessons))
		row["lessons_count"] = len(lessons)
		row["quizzes_count"] = len(quizzes | embedded)
		row["assignments_count"] = len(assignments)
		row["has_materials"] = bool(lessons or quizzes or assignments)
		row["has_assignments"] = row.name in issued_templates


def _require_homework_access(name: str):
	"""The library door every template operation shares (R03): the owner or
	privileged staff. ``frappe.get_doc`` reads without a permission check, so a
	whitelisted endpoint naming another teacher's -- or a student's -- homework
	must be refused here, not by a hidden button."""
	doc = frappe.get_doc("LMS Homework", name)
	if doc.owner != frappe.session.user and not _is_privileged():
		frappe.throw(_("You can only work with your own homework."), frappe.PermissionError)
	return doc


@frappe.whitelist()
def get_homework(name: str) -> dict:
	"""One compilation with its items, for the edit form. Each item carries its
	own working link (R18), so the teacher can view a source before issuing."""
	doc = _require_homework_access(name)
	items = [
		{
			"source_type": row.source_type,
			"name": row.lesson or row.quiz or row.assignment,
			"course": row.course,
			"label": row.label,
			"path": row.path,
		}
		for row in doc.items
	]
	numbers = _lesson_numbers_by_course({item["course"] for item in items if item["course"]})
	for item in items:
		number = (
			numbers.get(item["course"], {}).get(item["name"])
			if item["source_type"] == "Lesson"
			else None
		)
		if number:
			item["route"] = {"type": "lesson", "course": item["course"], "number": number}
		elif item["source_type"] == "Quiz":
			item["route"] = {"type": "quiz", "quiz": item["name"], "course": item["course"]}
		elif item["source_type"] == "Assignment":
			item["route"] = {"type": "assignment", "assignment": item["name"], "course": item["course"]}
	return {
		"name": doc.name,
		"title": doc.title,
		"days": doc.days,
		"details": doc.details,
		"group": doc.group,
		"archived": doc.archived,
		"items": items,
	}


@frappe.whitelist()
def save_homework(
	name: str | None = None,
	title: str = "",
	days: int = 7,
	details: str | None = None,
	group: str | None = None,
	items: list | None = None,
) -> dict:
	"""Create or update a compilation. Re-saving updates in place -- no duplicates
	(A04, A05). ``days`` is checked raw here: Frappe would silently truncate a
	fraction before the controller's validate ever sees it. The composition is
	canonicalized from the database (R04): client-sent courses, titles and paths
	are never trusted, and unknown or unreachable sources are refused."""
	days = homework_service.validate_days_raw(days)

	normalized = homework_sources.canonicalize_selection(items or [])
	if name:
		doc = _require_homework_access(name)
	else:
		doc = frappe.new_doc("LMS Homework")
	doc.title = title
	doc.days = days
	doc.details = details
	doc.group = group or None
	doc.set("items", [])
	for item in normalized:
		doc.append(
			"items",
			{
				"source_type": item["source_type"],
				"lesson": item["lesson"],
				"quiz": item["quiz"],
				"assignment": item["assignment"],
				"course": item["course"],
				"label": item["label"],
				"path": item["path"],
			},
		)
	doc.save()
	return {"name": doc.name}


@frappe.whitelist()
def copy_homework(name: str) -> dict:
	"""A fresh template with new ids, same sources, no assignments inherited (8.1)."""
	source = _require_homework_access(name)
	doc = frappe.new_doc("LMS Homework")
	doc.title = f"{source.title} ({_('copy')})"
	doc.days = source.days
	doc.details = source.details
	doc.group = source.group
	for row in source.items:
		doc.append(
			"items",
			{
				"source_type": row.source_type,
				"lesson": row.lesson,
				"quiz": row.quiz,
				"assignment": row.assignment,
				"course": row.course,
				"label": row.label,
				"path": row.path,
			},
		)
	doc.save()
	return {"name": doc.name}


@frappe.whitelist()
def archive_homework(name: str, archived: bool = True) -> dict:
	"""Archiving hides a compilation from the list and blocks new assignments but
	never closes or cancels issued ones (spec 8.1)."""
	doc = _require_homework_access(name)
	doc.archived = 1 if archived else 0
	doc.save()
	return {"name": doc.name, "archived": bool(doc.archived)}


@frappe.whitelist()
def delete_homework(name: str) -> dict:
	"""Only a never-issued compilation can be deleted; the doctype refuses a
	deleted-in-flight history (spec 8.1)."""
	_require_homework_access(name)
	frappe.delete_doc("LMS Homework", name)
	return {"deleted": True}


# --- Source tree (spec 3.4) -----------------------------------------------------


@frappe.whitelist()
def get_homework_courses() -> list[dict]:
	"""Courses the teacher may pick materials from. Closed courses of other
	teachers never appear (A09, A10 side of the picker)."""
	return homework_sources.get_assignable_courses()


@frappe.whitelist()
def get_homework_course_tree(course: str) -> dict:
	return homework_sources.get_course_source_tree(course)


@frappe.whitelist()
def get_homework_students(search: str = "") -> list[dict]:
	"""Students this teacher may assign to: members enrolled in courses the teacher
	instructs (the app's own teacher-student model); privileged staff reach every
	enrolled student."""
	courses = homework_sources.get_assignable_courses()
	names = [course["name"] for course in courses]
	if not names:
		return []
	filters = {"course": ("in", names)}
	if search:
		filters["member_name"] = ("like", f"%{search}%")
	rows = frappe.get_all(
		"LMS Enrollment",
		filters=filters,
		fields=["member as name", "member_name as full_name"],
		order_by="member_name",
	)
	seen = set()
	students = []
	for row in rows:
		if row.name not in seen:
			seen.add(row.name)
			students.append(row)
	return students


# --- Assignment flow (spec 4) ---------------------------------------------------


@frappe.whitelist()
def precheck_assignment(homework: str, student: str, days: int | None = None) -> dict:
	"""Everything the confirm dialog needs before issuing: blocking reasons with
	course-access pointers, the computed deadline, and an already-active card."""
	doc = frappe.get_doc("LMS Homework", homework)
	if doc.owner != frappe.session.user and not _is_privileged():
		frappe.throw(_("You can only assign your own homework."), frappe.PermissionError)

	check_days = homework_service.validate_days_raw(days if days is not None else doc.days)
	reasons = (
		homework_sources.validate_sources_for_student(doc.items, student)
		if doc.items
		else [_("This homework has no materials.")]
	)
	# Which courses the student cannot reach yet, so the dialog can link straight
	# to the app's own enrollment management instead of naming it in prose.
	missing_courses = [
		course
		for course in {item.course for item in (doc.items or []) if item.course}
		if not get_membership(course, student)
	]
	active = frappe.db.get_value(
		"LMS Homework Assignment", {"homework": homework, "student": student, "cancelled": 0}
	)
	return {
		"ok": not reasons and not doc.archived,
		"reasons": reasons,
		"missing_courses": missing_courses,
		"archived": bool(doc.archived),
		"due_at": datetime_to_iso(compute_due_at(now_datetime(), check_days)),
		"days": check_days,
		"already_active": active,
	}


@frappe.whitelist()
def assign_homework(
	homework: str,
	student: str,
	days: int | None = None,
	idempotency_key: str | None = None,
	force: bool = False,
) -> dict:
	"""Idempotent issuing (A11). ``force`` is the confirmed deliberate re-issue and
	must come with a fresh key."""
	return homework_service.create_assignment(
		homework_name=homework,
		student=student,
		days=days,
		idempotency_key=idempotency_key,
		force=force,
	)


# --- Board and detail (spec 5) --------------------------------------------------


@frappe.whitelist()
def get_homework_board(
	student: str | None = None,
	search: str = "",
	status: str | None = None,
	overdue: bool = False,
	course: str | None = None,
	offsets: str | None = None,
	include_cancelled: bool = False,
) -> dict:
	"""The board of an allowed student, four columns with full counts and per-column
	paging. ``student`` from the URL is never the authority: the server decides whose
	board the session user may read (students: their own; teachers: their own
	assignments to that student via the permission conditions; staff: everything).

	``include_cancelled`` flips the board into the history of recalled assignments
	(spec 8.1): a technical flag with its own view, never a fifth column."""
	target = student or frappe.session.user
	authorize_board(target)

	filters: dict = {"student": target, "cancelled": 1 if include_cancelled else 0}
	# frappe.get_all reads without the scripted permission conditions, so a teacher's
	# view of a student's board is narrowed here, explicitly, to their own issued
	# assignments (spec 5.1: the teacher sees the board "within their own rights").
	if target != frappe.session.user and not _is_privileged():
		filters["teacher"] = frappe.session.user
	if search:
		filters["title"] = ("like", f"%{search}%")
	if status:
		filters["status"] = status
	if course:
		filters["name"] = ("in", _assignments_with_course(target, course, include_cancelled) or ["__none__"])
	# R16: overdue is an ACTIVE-work flag -- To Do / In Progress past the deadline.
	# Work submitted on time is judged late-by-review at most; Done is never
	# overdue. The filter survives the per-column construction below.
	if overdue:
		filters["due_at"] = ("<", now_datetime())
		filters["status"] = ("in", [STATUS_TO_DO, STATUS_IN_PROGRESS])

	column_offsets = frappe.parse_json(offsets) if offsets else {}
	now = now_datetime()
	columns = []
	for column_status in BOARD_STATUSES:
		if status and status != column_status:
			columns.append({"status": column_status, "count": 0, "cards": [], "has_more": False})
			continue
		column_filters = dict(filters)
		column_filters["status"] = column_status
		if overdue and column_status not in (STATUS_TO_DO, STATUS_IN_PROGRESS):
			columns.append({"status": column_status, "count": 0, "cards": [], "has_more": False})
			continue
		count = frappe.db.count("LMS Homework Assignment", column_filters)
		offset = int(column_offsets.get(column_status, 0))
		rows = frappe.get_all(
			"LMS Homework Assignment",
			filters=column_filters,
			fields=[
				"name",
				"title",
				"teacher",
				"status",
				"due_at",
				"assigned_at",
				"needs_revision",
				"submitted_for_review_at",
				"reviewed_at",
				"total_requirements",
				"completed_requirements",
				"lessons_total",
				"quizzes_total",
				"quizzes_completed",
			],
			order_by="due_at asc, assigned_at asc" if column_status != STATUS_DONE else "reviewed_at desc",
			limit_page_length=BOARD_PAGE_SIZE,
			limit_start=offset,
		)
		for row in rows:
			_decorate_card(row, now)
		columns.append(
			{
				"status": column_status,
				"count": count,
				"cards": rows,
				"has_more": offset + len(rows) < count,
			}
		)
	_attach_continue_targets([row for column in columns for row in column["cards"]])
	return {"student": target, "columns": columns}


def _attach_continue_targets(rows: list) -> None:
	"""The card's «Продолжить» target (spec 5.2): the first unfinished material,
	computed for a whole page of cards in batched queries, never one per row.
	"""
	names = [row.name for row in rows]
	if not names:
		return
	reqs = frappe.get_all(
		"LMS Homework Requirement",
		filters={"parent": ("in", names), "parenttype": "LMS Homework Assignment"},
		fields=["parent", "requirement_type", "lesson", "quiz", "status", "course"],
		order_by="parent asc, idx asc",
	)
	courses = {row.course for row in reqs if row.course}
	numbers = _lesson_numbers_by_course(courses)

	targets: dict[str, dict] = {}
	for row in reqs:
		if row.status in {"Completed", "Completed Earlier", "Unavailable"}:
			continue
		if row.parent in targets:
			continue
		number = numbers.get(row.course, {}).get(row.lesson) if row.lesson else None
		if row.requirement_type == "Open Lesson" and number:
			targets[row.parent] = {"type": "lesson", "course": row.course, "number": number}
		elif row.requirement_type == "Pass Quiz" and row.quiz:
			if number:
				targets[row.parent] = {"type": "lesson", "course": row.course, "number": number}
			else:
				targets[row.parent] = {"type": "quiz", "quiz": row.quiz, "course": row.course}
		elif row.requirement_type == "Open Assignment" and row.reference_assignment:
			targets[row.parent] = {
				"type": "assignment",
				"assignment": row.reference_assignment,
				"course": row.course,
			}
	for row in rows:
		row["continue_target"] = targets.get(row.name)


def _lesson_numbers_by_course(courses: set) -> dict[str, dict[str, str]]:
	"""course -> {lesson name -> route number} with the outline's own numbering
	rules, including task #28's multi-segment numbers ("2-1-3": section path 2-1,
	third lesson) -- but through the NARROW identity queries (R20), never
	get_course_outline, which would drag every lesson's body/content along just
	to label a link."""
	from lms.lms.utils import get_outline_sections

	maps: dict[str, dict[str, str]] = {}
	for course in courses:
		roots = frappe.get_all(
			"Chapter Reference",
			filters={"parent": course},
			fields=["chapter", "idx"],
			order_by="idx",
		)
		root_names = [row.chapter for row in roots]
		section_rows = get_outline_sections(root_names) if root_names else []
		all_sections = root_names + [row.name for row in section_rows]
		lesson_rows = (
			frappe.get_all(
				"Lesson Reference",
				filters={"parent": ("in", all_sections), "parenttype": "Course Chapter"},
				fields=["parent", "idx", "lesson"],
				order_by="parent, idx",
			)
			if all_sections
			else []
		)

		lessons_by_section: dict[str, list] = {}
		sections_by_parent: dict[str, list] = {}
		for row in lesson_rows:
			if row.lesson:
				lessons_by_section.setdefault(row.parent, []).append(row)
		for row in section_rows:
			sections_by_parent.setdefault(row.chapter_name, []).append(row)

		numbers: dict[str, str] = {}

		def walk(section: str, path: str) -> None:
			lesson_position = 0
			section_position = 0
			for child in sorted(
				lessons_by_section.get(section, []),
				key=lambda row: row.idx,
			):
				lesson_position += 1
				numbers[child.lesson] = f"{path}-{lesson_position}"
			for child in sections_by_parent.get(section, []):
				section_position += 1
				walk(child.name, f"{path}-{section_position}")

		for root in roots:
			walk(root.chapter, str(root.idx))
		maps[course] = numbers
	return maps


def authorize_board(target: str) -> None:
	if target == frappe.session.user:
		return
	if _is_privileged():
		return
	# A Course Creator sees a student's board only through their own assignments:
	# the permission query condition narrows every list read to student/teacher.
	teacher_side = frappe.db.exists(
		"LMS Homework Assignment", {"student": target, "teacher": frappe.session.user}
	)
	if not teacher_side:
		frappe.throw(_("You cannot view this student's homework board."), frappe.PermissionError)


def _assignments_with_course(student: str, course: str, include_cancelled: bool = False) -> list[str]:
	# get_all with pluck returns plain strings, not documents (R09).
	names = set(
		frappe.get_all(
			"LMS Homework Requirement",
			filters={"parenttype": "LMS Homework Assignment", "course": course},
			pluck="parent",
		)
	)
	if not names:
		return []
	return list(
		set(
			frappe.get_all(
				"LMS Homework Assignment",
				filters={
					"student": student,
					"cancelled": 1 if include_cancelled else 0,
					"name": ("in", list(names)),
				},
				pluck="name",
			)
		)
	)


def _decorate_card(row: dict, now) -> None:
	row["due_at_iso"] = datetime_to_iso(row.due_at)
	# R16: only unfinished active work is overdue; Review/Done are judged by the
	# submission moment instead (submitted_late), never by the review's length.
	row["overdue"] = bool(
		row.due_at and row.due_at < now and row.status in (STATUS_TO_DO, STATUS_IN_PROGRESS)
	)
	row["submitted_late"] = bool(
		row.due_at and row.submitted_for_review_at and row.submitted_for_review_at > row.due_at
	)
	row["teacher_name"] = frappe.utils.get_fullname(row.teacher)


@frappe.whitelist()
def get_homework_assignment(name: str) -> dict:
	"""The full detail: snapshot header, checklist with proofs, history, and the
	first unfinished material for «Продолжить»."""
	doc = frappe.get_doc("LMS Homework Assignment", name)
	if doc.student != frappe.session.user and doc.teacher != frappe.session.user and not _is_privileged():
		frappe.throw(_("You cannot view this homework."), frappe.PermissionError)

	now = now_datetime()
	payload = {
		"name": doc.name,
		"homework": doc.homework,
		"title": doc.title,
		"details": doc.details,
		"days": doc.days,
		"teacher": doc.teacher,
		"teacher_name": frappe.utils.get_fullname(doc.teacher),
		"student": doc.student,
		"student_name": frappe.utils.get_fullname(doc.student),
		"status": doc.status,
		"assigned_at": doc.assigned_at,
		"assigned_at_iso": datetime_to_iso(doc.assigned_at),
		"due_at": doc.due_at,
		"due_at_iso": datetime_to_iso(doc.due_at),
		"overdue": bool(doc.due_at and doc.due_at < now and doc.status in (STATUS_TO_DO, STATUS_IN_PROGRESS)),
		"submitted_late": bool(
			doc.due_at and doc.submitted_for_review_at and doc.submitted_for_review_at > doc.due_at
		),
		"needs_revision": doc.needs_revision,
		"last_revision_comment": doc.last_revision_comment,
		"cancelled": doc.cancelled,
		"cancellation_reason": doc.cancellation_reason,
		"total_requirements": doc.total_requirements,
		"completed_requirements": doc.completed_requirements,
		"lessons_total": doc.lessons_total,
		"quizzes_total": doc.quizzes_total,
		"quizzes_completed": doc.quizzes_completed,
		"first_opened_at": doc.first_opened_at,
		"submitted_for_review_at": doc.submitted_for_review_at,
		"reviewed_by": doc.reviewed_by,
		"reviewed_at": doc.reviewed_at,
		"requirements": [format_requirement(row) for row in doc.requirements],
		"history": [
			{
				"actor": row.actor,
				"actor_name": row.actor_name,
				"event": row.event,
				"from_status": row.from_status,
				"to_status": row.to_status,
				"comment": row.comment,
				"creation": row.creation,
			}
			for row in reversed(doc.history)
		],
		"continue_target": continue_target(doc),
		"viewer_is_student": doc.student == frappe.session.user,
		"viewer_can_teach": doc.teacher == frappe.session.user or _is_privileged(),
	}
	# Spec 5.3.3: every material row carries its own working link to the real
	# course page, not only the first unfinished one. Numbers come from the
	# outline builder, multi-segment under task #28 ("2-1-3"). Course titles ship
	# with the assignment itself (R18): a student must not need the teacher's
	# course list to read their own checklist.
	course_names = {row.course for row in doc.requirements if row.course}
	numbers = _lesson_numbers_by_course(course_names)
	payload["course_titles"] = (
		{
			row.name: row.title
			for row in frappe.get_all(
				"LMS Course", filters={"name": ("in", list(course_names))}, fields=["name", "title"]
			)
		}
		if course_names
		else {}
	)
	for formatted, row in zip(payload["requirements"], doc.requirements, strict=True):
		number = numbers.get(row.course, {}).get(row.lesson) if row.lesson else None
		if number:
			formatted["route"] = {"type": "lesson", "course": row.course, "number": number}
		elif row.quiz:
			formatted["route"] = {"type": "quiz", "quiz": row.quiz, "course": row.course}
		elif row.reference_assignment:
			formatted["route"] = {
				"type": "assignment",
				"assignment": row.reference_assignment,
				"course": row.course,
			}
	return payload


def format_requirement(row) -> dict:
	"""One checklist row for the client: identity, path, state with a text label
	(color never the only carrier, spec 5.3), and the proof link when one exists.

	A source deleted after issuing (spec 8.2) reads as Unavailable right here,
	without rewriting the frozen snapshot: the row stays, the work does not
	silently count, and the teacher sees what to fix or recall."""
	state_labels = {
		"Pending": _("Not done"),
		"Awaiting Grading": _("Awaiting grading"),
		"Completed": _("Done"),
		"Completed Earlier": _("Done earlier"),
		"Unavailable": _("Unavailable"),
	}
	status = row.status if source_alive(row) else "Unavailable"
	return {
		"id": row.name,
		"requirement_type": row.requirement_type,
		"course": row.course,
		"chapter_title": row.chapter_title,
		"lesson": row.lesson,
		"quiz": row.quiz,
		"reference_assignment": row.reference_assignment,
		"label": row.label,
		"path": row.path,
		"status": status,
		"state_label": state_labels.get(status, status),
		"completed_at": row.completed_at,
		"proof_type": row.proof_type,
		"proof_name": row.proof_name,
	}


def continue_target(doc) -> dict | None:
	"""The first unfinished material: a lesson link with homework context, falling
	back to a standalone quiz. The lesson link carries the outline's route number,
	multi-segment under task #28."""
	numbers = _lesson_numbers_by_course({row.course for row in doc.requirements if row.course})
	for row in doc.requirements:
		if row.status in {"Completed", "Completed Earlier", "Unavailable"}:
			continue
		number = numbers.get(row.course, {}).get(row.lesson) if row.lesson else None
		if row.requirement_type == "Open Lesson" and number:
			return {"type": "lesson", "lesson": row.lesson, "course": row.course, "number": number}
		if row.requirement_type == "Pass Quiz" and row.quiz:
			if number:
				return {"type": "lesson", "lesson": row.lesson, "course": row.course, "number": number}
			return {"type": "quiz", "quiz": row.quiz, "course": row.course}
		if row.requirement_type == "Open Assignment" and row.reference_assignment:
			return {
				"type": "assignment",
				"assignment": row.reference_assignment,
				"course": row.course,
			}
	return None


# --- Events and actions (spec 7) ------------------------------------------------


@frappe.whitelist()
def open_homework(assignment: str) -> dict:
	"""The student opened their card: the one event that starts execution."""
	return homework_service.mark_started(assignment)


@frappe.whitelist()
def record_material_opened(lesson: str) -> dict:
	"""Called from a successfully loaded lesson page: a confirmed opening."""
	return homework_service.record_lesson_opened(lesson)


@frappe.whitelist()
def record_assignment_material_opened(assignment: str) -> dict:
	"""Called from the assignment's own page once the student has it open (R10):
	a confirmed opening of a standalone written assignment."""
	return homework_service.record_assignment_opened(assignment)


@frappe.whitelist()
def accept_homework(assignment: str, comment: str | None = None) -> dict:
	return homework_service.accept(assignment, comment)


@frappe.whitelist()
def return_homework(assignment: str, comment: str) -> dict:
	return homework_service.return_for_revision(assignment, comment)


@frappe.whitelist()
def reopen_homework(assignment: str, comment: str) -> dict:
	return homework_service.reopen(assignment, comment)


@frappe.whitelist()
def resubmit_homework(assignment: str) -> dict:
	return homework_service.resubmit(assignment)


@frappe.whitelist()
def change_homework_deadline(assignment: str, days: int = 7) -> dict:
	return homework_service.change_deadline(assignment, days)


@frappe.whitelist()
def revoke_homework(assignment: str, reason: str) -> dict:
	return homework_service.revoke(assignment, reason)


def _is_privileged() -> bool:
	from lms.lms.utils import has_moderator_role

	user = frappe.session.user
	return (
		user == "Administrator"
		or "System Manager" in frappe.get_roles(user)
		or bool(has_moderator_role(user))
	)


def _is_teacher_scoped() -> bool:
	"""Whether the library list narrows to the owner: everyone but staff."""
	return not _is_privileged()
