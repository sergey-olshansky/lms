# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""The homework assignment lifecycle: issuing, progress, and the state machine.

Everything here runs server-side with the session user's authority re-checked on
every step (task #35 spec, sections 4, 6 and 7). The client never supplies a
status, a pass verdict or a member: it names an action, and this module decides
whether that action is legal from the row's current state.

Statuses: To Do -> In Progress -> Review -> Done. The first move is the student's
own opening, the middle move is the server's alone, the last is the teacher's.
``needs_revision`` suppresses the automatic return to Review after a teacher has
sent the work back, until the student explicitly resubmits.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from lms.lms.homework_sources import (
	REQUIREMENT_OPEN_LESSON,
	REQUIREMENT_PASS_QUIZ,
	REQUIREMENT_REFERENCE,
	expand_requirements,
	validate_sources_for_student,
)

STATUS_TO_DO = "To Do"
STATUS_IN_PROGRESS = "In Progress"
STATUS_REVIEW = "Review"
STATUS_DONE = "Done"

COMPLETED_STATUSES = {"Completed", "Completed Earlier"}
# Reference rows are links, not checkable work: never counted, never gating.
CHECKABLE_TYPES = {REQUIREMENT_OPEN_LESSON, REQUIREMENT_PASS_QUIZ}

MAX_HOMEWORK_DAYS = 3650


# --- Deadline (spec 4.1) --------------------------------------------------------


def compute_due_at(assigned_at: datetime, days: int) -> datetime:
	"""The deadline is the end of the calendar day `days` after the local date of
	assignment: assigned 21.10 for 3 days -> 24.10 23:59:59 in the site timezone.

	Frappe stores naive datetimes in the system (site) timezone, so end-of-day is
	date arithmetic on the stored value; ``schedule_utils.datetime_to_iso`` attaches
	the offset for display.
	"""
	base = assigned_at if isinstance(assigned_at, datetime) else now_datetime()
	return datetime.combine((base + timedelta(days=days)).date(), time(23, 59, 59))


def validate_days_raw(days) -> int:
	"""The strict whole-number gate. Frappe casts Int fields before a controller's
	validate() sees them, so the raw value must be checked where it enters -- here,
	at the API boundary -- or "7.5" would silently become "7"."""
	if isinstance(days, bool) or not isinstance(days, int):
		frappe.throw(_("Number of days must be a whole number."))
	if days < 1:
		frappe.throw(_("Number of days must be at least 1."))
	if days > MAX_HOMEWORK_DAYS:
		frappe.throw(_("Number of days cannot exceed {0}.").format(MAX_HOMEWORK_DAYS))
	return days


# --- Issuing (spec 4, 8.2) ------------------------------------------------------


def create_assignment(
	homework_name: str,
	student: str,
	days: int | None = None,
	idempotency_key: str | None = None,
	force: bool = False,
) -> dict:
	"""Issue one compilation to one student, transactionally, with a frozen snapshot.

	Idempotency: the same ``assignment_key`` returns the existing assignment instead
	of creating a second card (A11). A deliberate re-issue passes ``force`` with a
	NEW key, after the caller has confirmed against the active assignment's link.
	"""
	teacher = frappe.session.user
	homework = frappe.get_doc("LMS Homework", homework_name)

	if homework.owner != teacher and not _is_privileged():
		frappe.throw(_("You can only assign your own homework."), frappe.PermissionError)
	if homework.archived:
		frappe.throw(_("This homework is archived and cannot be assigned."))
	if not student or not frappe.db.exists("User", student):
		frappe.throw(_("Please choose a valid student."))

	if idempotency_key:
		existing = frappe.db.get_value("LMS Homework Assignment", {"assignment_key": idempotency_key})
		if existing:
			return {"created": False, "name": existing, "idempotent": True}

	if not force:
		active = frappe.db.get_value(
			"LMS Homework Assignment",
			{"homework": homework_name, "student": student, "cancelled": 0},
		)
		if active:
			# The UI shows this link and asks before issuing an additional copy.
			return {"created": False, "name": active, "already_active": True}

	days = validate_days_raw(days if days is not None else homework.days)

	if not homework.items:
		frappe.throw(_("This homework has no materials. Add materials before assigning."))

	reasons = validate_sources_for_student(homework.items, student)
	if reasons:
		frappe.throw("<br>".join(reasons), frappe.ValidationError, title=_("Cannot assign this homework"))

	requirements = expand_requirements(homework.items)
	if not [row for row in requirements if row["requirement_type"] in CHECKABLE_TYPES]:
		frappe.throw(_("A homework must contain at least one lesson or quiz."))

	requirements = _apply_prior_credit(requirements, student)

	assigned_at = now_datetime()
	assignment = frappe.new_doc("LMS Homework Assignment")
	assignment.update(
		{
			"homework": homework_name,
			"teacher": teacher,
			"student": student,
			"title": homework.title,
			"details": homework.details,
			"days": days,
			"assigned_at": assigned_at,
			"due_at": compute_due_at(assigned_at, days),
			"status": STATUS_TO_DO,
			"assignment_key": idempotency_key,
		}
	)
	for row in requirements:
		assignment.append("requirements", row)
	assignment.flags.homework_service = True
	assignment.insert()

	_refresh_counts(assignment)
	_add_history(assignment, "assigned", None, STATUS_TO_DO)
	assignment.flags.homework_service = True
	assignment.save()

	return {"created": True, "name": assignment.name}


def _apply_prior_credit(requirements: list[dict], student: str) -> list[dict]:
	"""Credit evidence that already exists at issue time as "Completed Earlier"
	(spec 6.3). Without reliable stored history the row stays Pending -- no fact
	of viewing is invented."""
	for row in requirements:
		if row["requirement_type"] == REQUIREMENT_OPEN_LESSON:
			if frappe.db.exists(
				"LMS Course Progress",
				{"member": student, "lesson": row["lesson"], "status": "Complete"},
			):
				row["status"] = "Completed Earlier"
				row["completed_at"] = now_datetime()
				row["proof_type"] = "LMS Course Progress"
				row["proof_name"] = frappe.db.get_value(
					"LMS Course Progress",
					{"member": student, "lesson": row["lesson"], "status": "Complete"},
					"name",
				)
		elif row["requirement_type"] == REQUIREMENT_PASS_QUIZ:
			proof = passed_quiz_evidence(student, row["quiz"])
			if proof:
				row["status"] = "Completed Earlier"
				row["completed_at"] = now_datetime()
				row["proof_type"] = "LMS Quiz Submission"
				row["proof_name"] = proof
	return requirements


def source_alive(row) -> bool:
	"""Whether a requirement's underlying material still resolves by its stable id
	(spec 8.2: a deleted source reads Unavailable, never silently counts)."""
	if row.get("requirement_type") == "Open Lesson" and row.get("lesson"):
		return bool(frappe.db.exists("Course Lesson", row.lesson))
	if row.get("requirement_type") == "Pass Quiz" and row.get("quiz"):
		return bool(frappe.db.exists("LMS Quiz", row.quiz))
	if row.get("requirement_type") == "Reference" and row.get("reference_assignment"):
		return bool(frappe.db.exists("LMS Assignment", row.reference_assignment))
	return True


# --- Quiz evidence (spec 6.2) ---------------------------------------------------


def passed_quiz_evidence(member: str, quiz: str) -> str | None:
	"""The name of one passing submission, or None.

	The rule is the one the app already uses for lesson completion
	(get_quiz_progress): a saved submission whose percentage meets the quiz's
	passing threshold. One valid pass is enough; later failed attempts never
	subtract it (A23) -- the query simply keeps looking for any passing row.
	"""
	if not quiz or not frappe.db.exists("LMS Quiz", quiz):
		return None
	passing = frappe.db.get_value("LMS Quiz", quiz, "passing_percentage") or 0
	return (
		frappe.get_all(
			"LMS Quiz Submission",
			filters={"quiz": quiz, "member": member, "percentage": (">=", passing)},
			order_by="creation desc",
			pluck="name",
			limit=1,
		)
		or [None]
	)[0]


def quiz_awaiting_grading(member: str, quiz: str) -> bool:
	"""Whether the newest submission has an answered open-ended answer still awaiting
	marks (spec 6.2): the attempt is not a failure, it is unjudged -- "Ожидает
	проверки". Mirrors the #34 report's row status without depending on its UI."""
	latest = frappe.get_all(
		"LMS Quiz Submission",
		filters={"quiz": quiz, "member": member},
		order_by="creation desc",
		pluck="name",
		limit=1,
	)
	if not latest:
		return False
	rows = frappe.get_all(
		"LMS Quiz Result",
		filters={"parent": latest[0], "parenttype": "LMS Quiz Submission"},
		fields=["question_type", "answer", "marks", "marks_out_of"],
	)
	for row in rows:
		if (
			row.question_type == "Open Ended"
			and (row.answer or "").strip()
			and cint(row.marks) < cint(row.marks_out_of)
		):
			return True
	return False


# --- Student events (spec 6.1, 6.3, 7) ------------------------------------------


def mark_started(assignment_name: str) -> dict:
	"""The student's first open of their own card: To Do -> In Progress, once.

	A teacher previewing the board never reaches this (the session user must be the
	student), and loading the board is not an opening (A14, A15).
	"""
	assignment = _get_owned_assignment(assignment_name)
	if assignment.cancelled:
		return {"started": False}

	if assignment.first_opened_at:
		return {"started": False}

	assignment.first_opened_at = now_datetime()
	from_status = assignment.status
	if assignment.status == STATUS_TO_DO:
		assignment.status = STATUS_IN_PROGRESS
	_add_history(assignment, "started", from_status, assignment.status)
	assignment.flags.homework_service = True
	assignment.save()

	# A fully pre-credited composition goes straight through to Review on the same
	# first opening (A21): both events are recorded, no intermediate screen needed.
	_maybe_auto_review(assignment)
	return {"started": True}


def record_lesson_opened(lesson: str) -> dict:
	"""A confirmed opening of a lesson by the session student, from the lesson page
	after it loaded (spec 6.1). Updates every non-cancelled assignment of this
	student that includes the lesson -- working the course directly counts just as
	much as working through the homework link (spec 6.3, A22).

	Two tabs can race on the same row; Frappe's modified-check turns that into a
	TimestampMismatchError, and each assignment is then re-read and applied once
	more from its current state -- no rollback, the losing write never landed.
	"""
	user = frappe.session.user
	if not lesson or not frappe.db.exists("Course Lesson", lesson):
		return {"updated": 0}

	assignment_names = frappe.get_all(
		"LMS Homework Assignment",
		filters={"student": user, "cancelled": 0, "status": ("in", [STATUS_TO_DO, STATUS_IN_PROGRESS])},
		pluck="name",
	)
	updated = 0
	for name in assignment_names:
		assignment = frappe.get_doc("LMS Homework Assignment", name)
		if not _apply_lesson_opening(assignment, lesson):
			continue
		try:
			assignment.flags.homework_service = True
			assignment.save()
		except frappe.TimestampMismatchError:
			assignment = frappe.get_doc("LMS Homework Assignment", name)
			if not _apply_lesson_opening(assignment, lesson):
				continue
			assignment.flags.homework_service = True
			assignment.save()
		updated += 1
		_maybe_auto_review(assignment)
	return {"updated": updated}


def _apply_lesson_opening(assignment, lesson: str) -> bool:
	"""Idempotently credit the opening on one assignment. Returns False when the
	row has nothing left to do here (also the dedupe across concurrent events)."""
	touched = False
	for row in assignment.requirements:
		if (
			row.requirement_type == REQUIREMENT_OPEN_LESSON
			and row.lesson == lesson
			and row.status not in COMPLETED_STATUSES
			and row.status != "Unavailable"
		):
			row.status = "Completed"
			row.completed_at = now_datetime()
			row.proof_type = "Lesson View"
			row.proof_name = lesson
			touched = True
	if not touched:
		return False
	if not assignment.first_opened_at:
		# Working a material directly also starts the card (spec 7).
		assignment.first_opened_at = now_datetime()
		from_status = assignment.status
		if assignment.status == STATUS_TO_DO:
			assignment.status = STATUS_IN_PROGRESS
		_add_history(assignment, "started", from_status, assignment.status)
	_refresh_counts(assignment)
	return True


def resubmit(assignment_name: str) -> dict:
	"""After a teacher's return: the student sends the finished work for review
	again. Unfinished work is refused with the reason (A27)."""
	assignment = _get_owned_assignment(assignment_name)
	if assignment.status != STATUS_IN_PROGRESS or not assignment.needs_revision:
		frappe.throw(_("This homework is not waiting for your rework."))
	if not _all_requirements_confirmed(assignment):
		frappe.throw(_("Some requirements are still incomplete. Finish them before resubmitting."))

	assignment.needs_revision = 0
	assignment.status = STATUS_REVIEW
	assignment.submitted_for_review_at = now_datetime()
	_add_history(assignment, "resubmitted", STATUS_IN_PROGRESS, STATUS_REVIEW)
	assignment.flags.homework_service = True
	assignment.save()
	return {"status": STATUS_REVIEW}


# --- Teacher actions (spec 7, 4.1, 8.1) -----------------------------------------


def accept(assignment_name: str, comment: str | None = None) -> dict:
	assignment = _get_teachable_assignment(assignment_name)
	if assignment.status == STATUS_DONE:
		# A repeated confirmation is not a second audit row (A25).
		return {"status": STATUS_DONE}
	if assignment.status != STATUS_REVIEW:
		frappe.throw(_("Only homework in Review can be accepted."))
	# "Требования по-прежнему валидны" (spec 7): a source deleted while the card
	# sat in Review must be fixed or recalled, not accepted as done.
	dead = [
		row.label
		for row in assignment.requirements
		if row.requirement_type in CHECKABLE_TYPES and not source_alive(row)
	]
	if dead:
		frappe.throw(
			_("Some materials are no longer available: {0}.").format(frappe.bold(", ".join(dead))),
			frappe.ValidationError,
		)

	assignment.status = STATUS_DONE
	assignment.reviewed_by = frappe.session.user
	assignment.reviewed_at = now_datetime()
	assignment.needs_revision = 0
	_add_history(assignment, "accepted", STATUS_REVIEW, STATUS_DONE, comment)
	assignment.flags.homework_service = True
	assignment.save()
	return {"status": STATUS_DONE}


def return_for_revision(assignment_name: str, comment: str) -> dict:
	comment = (comment or "").strip()
	if not comment:
		frappe.throw(_("A comment is required when returning homework for rework."))

	assignment = _get_teachable_assignment(assignment_name)
	if assignment.status != STATUS_REVIEW:
		frappe.throw(_("Only homework in Review can be returned for rework."))

	assignment.status = STATUS_IN_PROGRESS
	assignment.needs_revision = 1
	assignment.last_revision_comment = comment
	assignment.reviewed_by = frappe.session.user
	assignment.reviewed_at = now_datetime()
	_add_history(assignment, "returned_for_revision", STATUS_REVIEW, STATUS_IN_PROGRESS, comment)
	assignment.flags.homework_service = True
	assignment.save()
	return {"status": STATUS_IN_PROGRESS}


def reopen(assignment_name: str, comment: str) -> dict:
	comment = (comment or "").strip()
	if not comment:
		frappe.throw(_("A comment is required when reopening accepted homework."))

	assignment = _get_teachable_assignment(assignment_name)
	if assignment.status != STATUS_DONE:
		frappe.throw(_("Only accepted homework can be reopened."))

	assignment.status = STATUS_IN_PROGRESS
	assignment.needs_revision = 1
	assignment.last_revision_comment = comment
	assignment.reviewed_by = frappe.session.user
	assignment.reviewed_at = now_datetime()
	_add_history(assignment, "reopened", STATUS_DONE, STATUS_IN_PROGRESS, comment)
	assignment.flags.homework_service = True
	assignment.save()
	return {"status": STATUS_IN_PROGRESS}


def change_deadline(assignment_name: str, days) -> dict:
	days = validate_days_raw(days)
	assignment = _get_teachable_assignment(assignment_name)

	old_due = assignment.due_at
	assignment.days = days
	assignment.due_at = compute_due_at(assignment.assigned_at or now_datetime(), days)
	_add_history(
		assignment,
		"deadline_changed",
		assignment.status,
		assignment.status,
		_("Due {0} -> due {1}").format(
			frappe.format(old_due, {"fieldtype": "Datetime"}) if old_due else "-",
			frappe.format(assignment.due_at, {"fieldtype": "Datetime"}),
		),
	)
	assignment.flags.homework_service = True
	assignment.save()
	return {"due_at": assignment.due_at}


def revoke(assignment_name: str, reason: str) -> dict:
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("A reason is required to recall a homework."))

	assignment = _get_teachable_assignment(assignment_name)
	if assignment.cancelled:
		return {"cancelled": True}

	assignment.cancelled = 1
	assignment.cancelled_by = frappe.session.user
	assignment.cancelled_at = now_datetime()
	assignment.cancellation_reason = reason
	# Cancellation is a technical flag, not a fifth column: progress and audit
	# stay, and later course events stop updating the card (spec 8.1).
	_add_history(assignment, "revoked", assignment.status, assignment.status, reason)
	assignment.flags.homework_service = True
	assignment.save()
	return {"cancelled": True}


# --- Recalculation (spec 6.2, 6.4, 9.4) -----------------------------------------


def on_quiz_submission_update(doc, method: str | None = None) -> None:
	"""doc_events hook: a submission saved (first attempt or a re-graded open
	answer) recomputes every affected quiz requirement -- targeted by member and
	quiz, never a scan of all assignments."""
	if not doc.get("member") or not doc.get("quiz"):
		return
	recompute_quiz_requirements(doc.member, doc.quiz)


def on_quiz_submission_trash(doc, method: str | None = None) -> None:
	"""A deleted (annulled) submission can also take the last proof with it."""
	if not doc.get("member") or not doc.get("quiz"):
		return
	recompute_quiz_requirements(doc.member, doc.quiz)


def recompute_quiz_requirements(member: str, quiz: str) -> None:
	assignments = frappe.get_all(
		"LMS Homework Assignment",
		filters={"student": member, "cancelled": 0},
		pluck="name",
	)
	for name in assignments:
		assignment = frappe.get_doc("LMS Homework Assignment", name)
		touched = False
		for row in assignment.requirements:
			if row.requirement_type != REQUIREMENT_PASS_QUIZ or row.quiz != quiz:
				continue
			if row.status == "Unavailable":
				continue
			touched |= _refresh_quiz_requirement(assignment, row, member, quiz)
		if not touched:
			continue
		_refresh_counts(assignment)
		assignment.flags.homework_service = True
		try:
			assignment.save()
		except frappe.TimestampMismatchError:
			# This runs inside the quiz submission's own save; a concurrent homework
			# write must never fail the submission. The next event (or this one
			# re-fired by the other writer) catches the requirement up.
			frappe.clear_last_message()
			continue
		_maybe_auto_review(assignment)


def _refresh_quiz_requirement(assignment, row, member: str, quiz: str) -> bool:
	"""Update one quiz requirement from stored evidence. Returns True when changed."""
	proof = passed_quiz_evidence(member, quiz)

	if proof:
		if row.status in COMPLETED_STATUSES:
			if row.proof_name != proof:
				row.proof_name = proof
				row.proof_type = "LMS Quiz Submission"
				return True
			return False
		row.status = "Completed"
		row.completed_at = now_datetime()
		row.proof_type = "LMS Quiz Submission"
		row.proof_name = proof
		return True

	# No passing submission. An invalidated earlier proof is a real event (spec 7,
	# last row): Review falls back to In Progress with the reason in history; Done
	# only records the discrepancy -- reopening stays the teacher's explicit act.
	invalidated = row.status in COMPLETED_STATUSES
	awaiting = quiz_awaiting_grading(member, quiz)
	if invalidated:
		row.status = "Awaiting Grading" if awaiting else "Pending"
		row.completed_at = None
		row.proof_type = None
		row.proof_name = None
		_add_history(
			assignment,
			"requirement_invalidated",
			assignment.status,
			assignment.status,
			_("The confirmed result of {0} is no longer valid.").format(frappe.bold(row.label)),
		)
		if assignment.status == STATUS_REVIEW:
			assignment.status = STATUS_IN_PROGRESS
		return True
	if awaiting and row.status != "Awaiting Grading":
		row.status = "Awaiting Grading"
		return True
	if not awaiting and row.status == "Awaiting Grading":
		row.status = "Pending"
		return True
	return False


# --- Aggregation and the automatic review (spec 6.4) ----------------------------


def _all_requirements_confirmed(assignment) -> bool:
	rows = [row for row in assignment.requirements if row.requirement_type in CHECKABLE_TYPES]
	if not rows:
		return False
	return all(row.status in COMPLETED_STATUSES for row in rows)


def _any_requirement_unavailable(assignment) -> bool:
	return any(row.status == "Unavailable" for row in assignment.requirements)


def _maybe_auto_review(assignment) -> None:
	"""In Progress + everything confirmed + nothing unavailable + no pending
	rework -> Review, recorded once. Reads and refreshes never re-fire it."""
	if not _eligible_for_auto_review(assignment):
		return

	assignment.status = STATUS_REVIEW
	assignment.submitted_for_review_at = now_datetime()
	_add_history(assignment, "submitted_for_review", STATUS_IN_PROGRESS, STATUS_REVIEW)
	assignment.flags.homework_service = True
	try:
		assignment.save()
	except frappe.TimestampMismatchError:
		# Raced with another writer: re-read and apply once from current state, so a
		# finished card can never be stranded in In Progress (A19).
		fresh = frappe.get_doc("LMS Homework Assignment", assignment.name)
		if not _eligible_for_auto_review(fresh):
			return
		fresh.status = STATUS_REVIEW
		fresh.submitted_for_review_at = now_datetime()
		_add_history(fresh, "submitted_for_review", STATUS_IN_PROGRESS, STATUS_REVIEW)
		fresh.flags.homework_service = True
		try:
			fresh.save()
		except frappe.TimestampMismatchError:
			frappe.log_error(
				title="Homework auto-review skipped after write race",
				message=f"assignment={assignment.name}",
			)
			frappe.clear_last_message()


def _eligible_for_auto_review(assignment) -> bool:
	return (
		assignment.status == STATUS_IN_PROGRESS
		and not assignment.needs_revision
		and bool(assignment.first_opened_at)
		and not _any_requirement_unavailable(assignment)
		and _all_requirements_confirmed(assignment)
	)


def _refresh_counts(assignment) -> None:
	"""Denormalized counters for the board: totals count checkable requirements
	only (spec 6.4 -- no "0 of 0", and a chapter heading is never a done lesson)."""
	rows = [row for row in assignment.requirements if row.requirement_type in CHECKABLE_TYPES]
	assignment.total_requirements = len(rows)
	assignment.completed_requirements = sum(1 for row in rows if row.status in COMPLETED_STATUSES)
	assignment.lessons_total = sum(1 for row in rows if row.requirement_type == REQUIREMENT_OPEN_LESSON)
	assignment.quizzes_total = sum(1 for row in rows if row.requirement_type == REQUIREMENT_PASS_QUIZ)
	assignment.quizzes_completed = sum(
		1
		for row in rows
		if row.requirement_type == REQUIREMENT_PASS_QUIZ and row.status in COMPLETED_STATUSES
	)


# --- Shared helpers -------------------------------------------------------------


def _get_owned_assignment(assignment_name: str):
	"""Load an assignment the session STUDENT owns. Any other reader -- a teacher
	previewing the board included -- is refused: their opens never start work."""
	assignment = frappe.get_doc("LMS Homework Assignment", assignment_name)
	if assignment.student != frappe.session.user and not _is_privileged():
		frappe.throw(_("This homework belongs to another student."), frappe.PermissionError)
	if assignment.student != frappe.session.user:
		frappe.throw(_("Only the student's own opening starts the homework."), frappe.PermissionError)
	return assignment


def _get_teachable_assignment(assignment_name: str):
	"""Load an assignment the session user may act on as a teacher: the issuing
	teacher or privileged staff (spec 7 -- 'назначивший/уполномоченный')."""
	assignment = frappe.get_doc("LMS Homework Assignment", assignment_name)
	user = frappe.session.user
	if assignment.teacher != user and not _is_privileged():
		frappe.throw(_("Only the teacher who assigned this homework can review it."), frappe.PermissionError)
	return assignment


def _add_history(
	assignment, event: str, from_status: str | None, to_status: str | None, comment: str | None = None
) -> None:
	assignment.append(
		"history",
		{
			"actor": frappe.session.user,
			"actor_name": frappe.utils.get_fullname(frappe.session.user),
			"event": event,
			"from_status": from_status,
			"to_status": to_status,
			"comment": comment,
		},
	)


def _is_privileged() -> bool:
	from lms.lms.utils import has_moderator_role

	user = frappe.session.user
	return (
		user == "Administrator"
		or "System Manager" in frappe.get_roles(user)
		or bool(has_moderator_role(user))
	)
