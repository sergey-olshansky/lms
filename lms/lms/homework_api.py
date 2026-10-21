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
)
from lms.lms.schedule_utils import datetime_to_iso

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
	"""Materialize the «N lessons · M quizzes» column for one page, batched:
	embedded quizzes are counted through the placement index, not per-lesson HTML."""
	lesson_names: list[str] = []
	by_template: dict[str, list[str]] = {}
	template_names = [row.name for row in rows]
	if not template_names:
		return
	for row in frappe.get_all(
		"LMS Homework Source",
		filters={"parent": ("in", template_names), "parenttype": "LMS Homework"},
		fields=["parent", "source_type", "lesson", "quiz"],
	):
		if row.source_type == "Lesson" and row.lesson:
			by_template.setdefault(row.parent, []).append(row.lesson)
			lesson_names.append(row.lesson)
	by_template = {k: list(set(v)) for k, v in by_template.items()}

	quiz_count_by_lesson: dict[str, int] = {}
	if lesson_names:
		for placement in frappe.get_all(
			"LMS Lesson Assessment",
			filters={
				"parent": ("in", lesson_names),
				"parenttype": "Course Lesson",
				"assessment_type": "LMS Quiz",
				"instructor_only": 0,
			},
			fields=["parent", "assessment_name"],
		):
			quiz_count_by_lesson.setdefault(placement.parent, set()).add(placement.assessment_name)

	for row in rows:
		lessons = by_template.get(row.name, [])
		quizzes = sum(len(quiz_count_by_lesson.get(lesson, set())) for lesson in lessons)
		# Standalone quiz rows are their own quiz count.
		standalone = frappe.db.count(
			"LMS Homework Source",
			filters={"parent": row.name, "parenttype": "LMS Homework", "source_type": "Quiz"},
		)
		row["lessons_count"] = len(lessons)
		row["quizzes_count"] = quizzes + standalone
		row["has_materials"] = bool(lessons or standalone)
		row["has_assignments"] = bool(frappe.db.exists("LMS Homework Assignment", {"homework": row.name}))


@frappe.whitelist()
def get_homework(name: str) -> dict:
	"""One compilation with its items, for the edit form."""
	doc = frappe.get_doc("LMS Homework", name)
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
	fraction before the controller's validate ever sees it."""
	days = homework_service.validate_days_raw(days)

	normalized = homework_sources.normalize_selection(items or [])
	if name:
		doc = frappe.get_doc("LMS Homework", name)
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
	source = frappe.get_doc("LMS Homework", name)
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
	doc = frappe.get_doc("LMS Homework", name)
	doc.archived = 1 if archived else 0
	doc.save()
	return {"name": doc.name, "archived": bool(doc.archived)}


@frappe.whitelist()
def delete_homework(name: str) -> dict:
	"""Only a never-issued compilation can be deleted; the doctype refuses a
	deleted-in-flight history (spec 8.1)."""
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
	active = frappe.db.get_value(
		"LMS Homework Assignment", {"homework": homework, "student": student, "cancelled": 0}
	)
	return {
		"ok": not reasons and not doc.archived,
		"reasons": reasons,
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
) -> dict:
	"""The board of an allowed student, four columns with full counts and per-column
	paging. ``student`` from the URL is never the authority: the server decides whose
	board the session user may read (students: their own; teachers: their own
	assignments to that student via the permission conditions; staff: everything)."""
	target = student or frappe.session.user
	authorize_board(target)

	filters: dict = {"student": target, "cancelled": 0}
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
		filters["name"] = ("in", _assignments_with_course(target, course) or ["__none__"])
	if overdue:
		filters["due_at"] = ("<", now_datetime())
		filters["status"] = ("!=", STATUS_DONE)

	column_offsets = frappe.parse_json(offsets) if offsets else {}
	now = now_datetime()
	columns = []
	for column_status in BOARD_STATUSES:
		if status and status != column_status:
			columns.append({"status": column_status, "count": 0, "cards": [], "has_more": False})
			continue
		column_filters = {k: v for k, v in filters.items() if k != "status"}
		column_filters["status"] = column_status
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
	computed for a whole page of cards in three batched queries, never one per row.
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
	lessons = {row.lesson for row in reqs if row.lesson}
	positions = _lesson_positions(lessons) if lessons else {}

	targets: dict[str, dict] = {}
	for row in reqs:
		if row.status in {"Completed", "Completed Earlier", "Unavailable"}:
			continue
		if row.parent in targets:
			continue
		if row.requirement_type == "Open Lesson" and row.lesson and row.lesson in positions:
			targets[row.parent] = {"type": "lesson", **positions[row.lesson]}
		elif row.requirement_type == "Pass Quiz" and row.quiz:
			if row.lesson and row.lesson in positions:
				targets[row.parent] = {"type": "lesson", **positions[row.lesson]}
			else:
				targets[row.parent] = {"type": "quiz", "quiz": row.quiz, "course": row.course}
	for row in rows:
		row["continue_target"] = targets.get(row.name)


def _lesson_positions(lessons: set) -> dict:
	"""lesson -> {course, chapter_number, lesson_number} matching the SPA route
	/courses/:courseName/learn/:chapterNumber-:lessonNumber, batched."""
	lesson_rows = frappe.get_all(
		"Course Lesson", filters={"name": ("in", list(lessons))}, fields=["name", "chapter"]
	)
	chapters = {row.chapter for row in lesson_rows if row.chapter}
	if not chapters:
		return {}
	chapter_rows = frappe.get_all(
		"Course Chapter", filters={"name": ("in", list(chapters))}, fields=["name", "course"]
	)
	courses = {row.course for row in chapter_rows if row.course}
	chapter_refs = (
		frappe.get_all(
			"Chapter Reference",
			filters={"parent": ("in", list(courses)), "chapter": ("in", list(chapters))},
			fields=["chapter", "parent", "idx"],
		)
		if courses
		else []
	)
	lesson_refs = frappe.get_all(
		"Lesson Reference",
		filters={"parent": ("in", list(chapters)), "lesson": ("in", list(lessons))},
		fields=["parent", "lesson", "idx"],
	)
	chapter_number = {row.chapter: row.idx for row in chapter_refs}
	chapter_course = {row.name: row.course for row in chapter_rows}
	positions = {}
	for row in lesson_refs:
		positions[row.lesson] = {
			"course": chapter_course.get(row.parent),
			"chapter_number": chapter_number.get(row.parent),
			"lesson_number": row.idx,
		}
	return positions


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


def _assignments_with_course(student: str, course: str) -> list[str]:
	rows = frappe.get_all(
		"LMS Homework Requirement",
		filters={"parenttype": "LMS Homework Assignment", "course": course},
		fields=["parent"],
	)
	names = {row.parent for row in rows}
	if not names:
		return []
	return list(
		{
			row.name
			for row in frappe.get_all(
				"LMS Homework Assignment",
				filters={"student": student, "cancelled": 0, "name": ("in", list(names))},
				pluck="name",
			)
		}
	)


def _decorate_card(row: dict, now) -> None:
	row["due_at_iso"] = datetime_to_iso(row.due_at)
	row["overdue"] = bool(row.due_at and row.due_at < now and row.status != STATUS_DONE)
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
		"overdue": bool(doc.due_at and doc.due_at < now and doc.status != STATUS_DONE),
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
	return payload


def format_requirement(row) -> dict:
	"""One checklist row for the client: identity, path, state with a text label
	(color never the only carrier, spec 5.3), and the proof link when one exists."""
	state_labels = {
		"Pending": _("Not done"),
		"Awaiting Grading": _("Awaiting grading"),
		"Completed": _("Done"),
		"Completed Earlier": _("Done earlier"),
		"Unavailable": _("Unavailable"),
	}
	return {
		"requirement_type": row.requirement_type,
		"course": row.course,
		"chapter_title": row.chapter_title,
		"lesson": row.lesson,
		"quiz": row.quiz,
		"reference_assignment": row.reference_assignment,
		"label": row.label,
		"path": row.path,
		"status": row.status,
		"state_label": state_labels.get(row.status, row.status),
		"completed_at": row.completed_at,
		"proof_type": row.proof_type,
		"proof_name": row.proof_name,
	}


def continue_target(doc) -> dict | None:
	"""The first unfinished material: a lesson link with homework context, falling
	back to a standalone quiz. Lesson routes use chapter/lesson order numbers."""
	positions = _lesson_positions({row.lesson for row in doc.requirements if row.lesson})
	for row in doc.requirements:
		if row.status in {"Completed", "Completed Earlier", "Unavailable"}:
			continue
		if row.requirement_type == "Open Lesson" and row.lesson and row.lesson in positions:
			return {"type": "lesson", "lesson": row.lesson, **positions[row.lesson]}
		if row.requirement_type == "Pass Quiz" and row.quiz:
			if row.lesson and row.lesson in positions:
				return {"type": "lesson", "lesson": row.lesson, **positions[row.lesson]}
			return {"type": "quiz", "quiz": row.quiz, "course": row.course}
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
