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
	REQUIREMENT_OPEN_ASSIGNMENT,
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
CHECKABLE_TYPES = {
	REQUIREMENT_OPEN_LESSON,
	REQUIREMENT_PASS_QUIZ,
	REQUIREMENT_OPEN_ASSIGNMENT,
}

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
		existing = frappe.db.get_value(
			"LMS Homework Assignment",
			{"assignment_key": idempotency_key},
			["name", "homework", "student", "days"],
			as_dict=True,
		)
		if existing:
			# B05: a key names ONE logical operation. The same key returning with
			# different parameters (student or term changed after an uncertain
			# result) is a stale replay, not a retry: it must fail loudly instead
			# of silently handing back the card issued under the old parameters.
			if not _idempotency_params_match(existing, homework_name, student, days, homework.days):
				frappe.throw(
					_(
						"This request conflicts with an assignment already created from the same dialog. Check the board before issuing again."
					),
					frappe.ValidationError,
				)
			return {"created": False, "name": existing.name, "idempotent": True}

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
	try:
		assignment.insert(ignore_permissions=True)
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		# Two tabs confirming the same logical issue race on the unique key (R19,
		# B05): MariaDB surfaces a secondary unique index as
		# UniqueValidationError, SQLite as DuplicateEntryError -- both land here.
		# The loser returns the winner's card, after re-checking that the key's
		# parameters really are this operation; one logical operation, one card.
		if not idempotency_key:
			raise
		existing = frappe.db.get_value(
			"LMS Homework Assignment",
			{"assignment_key": idempotency_key},
			["name", "homework", "student", "days"],
			as_dict=True,
		)
		if existing and _idempotency_params_match(existing, homework_name, student, days, homework.days):
			frappe.clear_last_message()
			return {"created": False, "name": existing.name, "idempotent": True}
		raise

	_refresh_counts(assignment)
	_add_history(assignment, "assigned", None, STATUS_TO_DO)
	assignment.flags.homework_service = True
	assignment.save(ignore_permissions=True)

	return {"created": True, "name": assignment.name}


def _idempotency_params_match(existing, homework_name: str, student: str, days, template_days) -> bool:
	"""Whether an assignment stored under an idempotency key really is THIS
	operation: same compilation, same student, same term (B05)."""
	return (
		existing.homework == homework_name
		and existing.student == student
		and cint(existing.days) == cint(days if days is not None else template_days)
	)


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
	if row.get("requirement_type") in ("Reference", "Open Assignment") and row.get("reference_assignment"):
		return bool(frappe.db.exists("LMS Assignment", row.reference_assignment))
	return True


# --- Quiz evidence (spec 6.2) ---------------------------------------------------


def passed_quiz_evidence(member: str, quiz: str) -> str | None:
	"""The name of one finally-successful submission, or None.

	Verdicts are read off the saved attempt itself (R07): its own percentage
	against its own snapshotted passing threshold -- raising the live threshold
	later never retroactively un-passes a valid attempt -- and only attempts whose
	manual grading is finished. One final pass is enough; later failed attempts
	never subtract it (A23, B03): the whole history is read in one query, so an
	older valid pass is never evicted by any number of newer failures, however
	long the attempt list has grown.
	"""
	if not quiz or not frappe.db.exists("LMS Quiz", quiz):
		return None
	attempts = frappe.get_all(
		"LMS Quiz Submission",
		filters={"quiz": quiz, "member": member},
		fields=["name", "percentage", "passing_percentage"],
		order_by="creation desc",
	)
	live_threshold = None
	for row in attempts:
		threshold = row.passing_percentage
		if threshold is None:
			# A submission old enough to predate the snapshot column falls back
			# to the quiz's live threshold, exactly one time per call.
			if live_threshold is None:
				live_threshold = frappe.db.get_value("LMS Quiz", quiz, "passing_percentage") or 0
			threshold = live_threshold
		if (row.percentage or 0) < threshold:
			continue
		if _submission_awaiting_grading(row.name):
			continue
		return row.name
	return None


def quiz_awaiting_grading(member: str, quiz: str) -> bool:
	"""Whether the newest submission still awaits its manual grading (spec 6.2):
	the attempt is not a failure, it is unjudged -- "Ожидает проверки"."""
	latest = frappe.get_all(
		"LMS Quiz Submission",
		filters={"quiz": quiz, "member": member},
		order_by="creation desc",
		pluck="name",
		limit=1,
	)
	if not latest:
		return False
	return _submission_awaiting_grading(latest[0])


def _submission_awaiting_grading(submission_name: str) -> bool:
	"""One submission: does any answered open-ended question still have no
	recorded verdict?

	The signal is the grader's own field, not a save timestamp (B02): the quiz
	client submits only ``{question_name, answer}`` (SavedAnswer) and
	``process_results`` writes ``marks`` for every objective row but none for
	Open Ended, so an unanswered-by-grader row stores NULL. The grading page
	binds that NULL into an empty input and writes a verdict -- any verdict: a
	final zero and a final partial mark are recorded values, indistinguishable
	from full marks by design. Therefore ``marks IS NULL`` on an answered
	open-ended row means precisely "no verdict exists yet": the 1-second
	autosave that graded one answer of two leaves the submission awaiting,
	and ``modified_by`` -- which the old heuristic read -- is not consulted
	at all, because it says nothing about WHICH answers were judged."""
	rows = frappe.get_all(
		"LMS Quiz Result",
		filters={"parent": submission_name, "parenttype": "LMS Quiz Submission"},
		fields=["question_type", "answer", "marks"],
	)
	return any(
		row.question_type == "Open Ended"
		and (row.answer or "").strip()
		and row.marks is None
		for row in rows
	)


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
	assignment.save(ignore_permissions=True)

	# A fully pre-credited composition goes straight through to Review on the same
	# first opening (A21): both events are recorded, no intermediate screen needed.
	_maybe_auto_review(assignment)
	return {"started": True}


def record_lesson_opened(lesson: str) -> dict:
	"""A confirmed opening of a lesson by the session student, from the lesson page
	after it loaded (spec 6.1). Updates every non-cancelled assignment of this
	student that includes the lesson -- working the course directly counts just as
	much as working through the homework link (spec 6.3, A22).

	The student's right to open THIS lesson is re-checked at event time (R04):
	revoked enrollment, a later sequential lock or an unpublished course leaves
	the requirement untouched instead of crediting a visit that was never allowed.
	"""
	from lms.lms.permissions import can_access_lesson

	user = frappe.session.user
	if not lesson or not frappe.db.exists("Course Lesson", lesson):
		return {"updated": 0}
	if not can_access_lesson(lesson, user=user):
		return {"updated": 0}

	return _record_opening_of(user, lesson=lesson)


def record_assignment_opened(assignment_ref: str) -> dict:
	"""A confirmed opening of a standalone written Assignment by the session
	student (R10): the material is real and addressable, so opening it is the
	agreed condition -- its own submission UI and grading are untouched (spec 6.1
	forbids inventing an automatic assessment for the written answer)."""
	user = frappe.session.user
	if not assignment_ref or not frappe.db.exists("LMS Assignment", assignment_ref):
		return {"updated": 0}
	from lms.lms.permissions import can_access_assessment

	if not can_access_assessment("LMS Assignment", assignment_ref, user=user):
		return {"updated": 0}

	return _record_opening_of(user, assignment=assignment_ref)


def _record_opening_of(user: str, lesson: str | None = None, assignment: str | None = None) -> dict:
	"""Credit one confirmed opening across the student's active assignments."""
	assignment_names = frappe.get_all(
		"LMS Homework Assignment",
		filters={"student": user, "cancelled": 0, "status": ("in", [STATUS_TO_DO, STATUS_IN_PROGRESS])},
		pluck="name",
	)
	updated = 0
	for name in assignment_names:
		if _persist_opening(name, user, lesson=lesson, assignment=assignment):
			updated += 1
	return {"updated": updated}


def _persist_opening(name: str, user: str, lesson: str | None = None, assignment: str | None = None) -> bool:
	"""Apply and persist one opening on one card, racing other writers safely.

	Repeated write conflicts never lose the credit (B06): after one fresh retry
	the opening is re-applied by a queued job, so a card cannot stay un-credited
	or un-started because somebody else saved first."""
	doc = frappe.get_doc("LMS Homework Assignment", name)
	if not _apply_material_opening(doc, lesson=lesson, assignment=assignment):
		return True
	doc.flags.homework_service = True
	try:
		doc.save(ignore_permissions=True)
		_maybe_auto_review(doc)
		return True
	except frappe.TimestampMismatchError:
		frappe.clear_last_message()

	fresh = frappe.get_doc("LMS Homework Assignment", name)
	if _apply_material_opening(fresh, lesson=lesson, assignment=assignment):
		fresh.flags.homework_service = True
		try:
			fresh.save(ignore_permissions=True)
			_maybe_auto_review(fresh)
			return True
		except frappe.TimestampMismatchError:
			frappe.clear_last_message()
			if not frappe.flags.in_test:
				frappe.enqueue(
					apply_opening_job,
					queue="short",
					enqueue_after_commit=True,
					user=user,
					name=name,
					lesson=lesson,
					assignment=assignment,
				)
	return False


def apply_opening_job(user: str, name: str, lesson: str | None = None, assignment: str | None = None) -> None:
	"""Queued re-application of one confirmed opening after repeated write races
	(B06): the opening is a recorded fact, not a request to be retried by hand."""
	_persist_opening(name, user, lesson=lesson, assignment=assignment)


def _apply_material_opening(assignment_doc, lesson: str | None = None, assignment: str | None = None) -> bool:
	"""Idempotently credit the opening on one assignment. Returns False when the
	row has nothing left to do here (also the dedupe across concurrent events)."""
	touched = False
	for row in assignment_doc.requirements:
		if row.status in COMPLETED_STATUSES or row.status == "Unavailable":
			continue
		opens_lesson = lesson and row.requirement_type == REQUIREMENT_OPEN_LESSON and row.lesson == lesson
		opens_assignment = (
			assignment
			and row.requirement_type == REQUIREMENT_OPEN_ASSIGNMENT
			and row.reference_assignment == assignment
		)
		if not (opens_lesson or opens_assignment):
			continue
		row.status = "Completed"
		row.completed_at = now_datetime()
		row.proof_type = "Assignment View" if opens_assignment else "Lesson View"
		row.proof_name = assignment if opens_assignment else lesson
		touched = True
	if not touched:
		return False
	if not assignment_doc.first_opened_at:
		# Working a material directly also starts the card (spec 7).
		assignment_doc.first_opened_at = now_datetime()
		from_status = assignment_doc.status
		if assignment_doc.status == STATUS_TO_DO:
			assignment_doc.status = STATUS_IN_PROGRESS
		_add_history(assignment_doc, "started", from_status, assignment_doc.status)
	_refresh_counts(assignment_doc)
	return True


def resubmit(assignment_name: str) -> dict:
	"""After a teacher's return: the student sends the finished work for review
	again. Unfinished work is refused with the reason (A27)."""
	assignment = _get_owned_assignment(assignment_name)
	_refuse_cancelled(assignment)
	if assignment.status != STATUS_IN_PROGRESS or not assignment.needs_revision:
		frappe.throw(_("This homework is not waiting for your rework."))
	if _any_requirement_unavailable(assignment):
		frappe.throw(_("Some materials are no longer available. Ask the teacher to fix the homework."))
	if not _all_requirements_confirmed(assignment):
		frappe.throw(_("Some requirements are still incomplete. Finish them before resubmitting."))

	assignment.needs_revision = 0
	assignment.status = STATUS_REVIEW
	assignment.submitted_for_review_at = now_datetime()
	_add_history(assignment, "resubmitted", STATUS_IN_PROGRESS, STATUS_REVIEW)
	assignment.flags.homework_service = True
	assignment.save(ignore_permissions=True)
	return {"status": STATUS_REVIEW}


# --- Teacher actions (spec 7, 4.1, 8.1) -----------------------------------------


def _refuse_cancelled(assignment) -> None:
	"""A recalled assignment is frozen history: no action may move it (R06)."""
	if assignment.cancelled:
		frappe.throw(
			_("This homework was recalled and stays as history only."),
			frappe.PermissionError,
		)


def _any_requirement_unavailable(assignment) -> bool:
	"""Whether any checkable row's material is gone RIGHT NOW (B04): the stored
	status alone is not consulted -- a Completed row over a deleted source is
	unavailable, whatever the snapshot still says."""
	return any(
		row.status == "Unavailable" or not source_alive(row)
		for row in assignment.requirements
		if row.requirement_type in CHECKABLE_TYPES
	)


def accept(assignment_name: str, comment: str | None = None) -> dict:
	assignment = _get_teachable_assignment(assignment_name)
	_refuse_cancelled(assignment)
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
	assignment.save(ignore_permissions=True)
	return {"status": STATUS_DONE}


def return_for_revision(assignment_name: str, comment: str) -> dict:
	comment = (comment or "").strip()
	if not comment:
		frappe.throw(_("A comment is required when returning homework for rework."))

	assignment = _get_teachable_assignment(assignment_name)
	_refuse_cancelled(assignment)
	if assignment.status != STATUS_REVIEW:
		frappe.throw(_("Only homework in Review can be returned for rework."))

	assignment.status = STATUS_IN_PROGRESS
	assignment.needs_revision = 1
	assignment.last_revision_comment = comment
	assignment.reviewed_by = frappe.session.user
	assignment.reviewed_at = now_datetime()
	_add_history(assignment, "returned_for_revision", STATUS_REVIEW, STATUS_IN_PROGRESS, comment)
	assignment.flags.homework_service = True
	assignment.save(ignore_permissions=True)
	return {"status": STATUS_IN_PROGRESS}


def reopen(assignment_name: str, comment: str) -> dict:
	comment = (comment or "").strip()
	if not comment:
		frappe.throw(_("A comment is required when reopening accepted homework."))

	assignment = _get_teachable_assignment(assignment_name)
	_refuse_cancelled(assignment)
	if assignment.status != STATUS_DONE:
		frappe.throw(_("Only accepted homework can be reopened."))

	assignment.status = STATUS_IN_PROGRESS
	assignment.needs_revision = 1
	assignment.last_revision_comment = comment
	assignment.reviewed_by = frappe.session.user
	assignment.reviewed_at = now_datetime()
	_add_history(assignment, "reopened", STATUS_DONE, STATUS_IN_PROGRESS, comment)
	assignment.flags.homework_service = True
	assignment.save(ignore_permissions=True)
	return {"status": STATUS_IN_PROGRESS}


def change_deadline(assignment_name: str, days) -> dict:
	days = validate_days_raw(days)
	assignment = _get_teachable_assignment(assignment_name)
	_refuse_cancelled(assignment)

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
	assignment.save(ignore_permissions=True)
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
	assignment.save(ignore_permissions=True)
	return {"cancelled": True}


# --- Recalculation (spec 6.2, 6.4, 9.4) -----------------------------------------


def on_quiz_submission_update(doc, method: str | None = None) -> None:
	"""doc_events hook: a submission saved (first attempt or a re-graded open
	answer) recomputes every affected quiz requirement -- targeted by member and
	quiz, never a scan of all assignments."""
	if not doc.get("member") or not doc.get("quiz"):
		return
	recompute_quiz_requirements(doc.member, doc.quiz)


def on_quiz_submission_delete(doc, method: str | None = None) -> None:
	"""after_delete hook: the annulled submission is gone from the database by
	now -- on_trash fires before the delete, so the recalculation would still
	see the passing row it is supposed to lose (R08)."""
	if not doc.get("member") or not doc.get("quiz"):
		return
	recompute_quiz_requirements(doc.member, doc.quiz)


def recompute_quiz_requirements(member: str, quiz: str) -> None:
	"""Addressed recalculation (R20): only the assignments of this member that
	actually carry a requirement on this quiz, found through the requirement
	rows -- never every card of the student, and never another student's."""
	parents = {
		row
		for row in frappe.get_all(
			"LMS Homework Requirement",
			filters={"parenttype": "LMS Homework Assignment", "quiz": quiz},
			pluck="parent",
		)
	}
	if not parents:
		return
	assignments = frappe.get_all(
		"LMS Homework Assignment",
		filters={"name": ("in", list(parents)), "student": member, "cancelled": 0},
		pluck="name",
	)
	for name in assignments:
		_recompute_one_assignment(name, member=member, quiz=quiz)


def _recompute_one_assignment(name: str, *, member: str | None = None, quiz: str | None = None) -> None:
	assignment = frappe.get_doc("LMS Homework Assignment", name)
	if assignment.cancelled:
		return
	touched = _refresh_availability(assignment)
	for row in assignment.requirements:
		if quiz and row.requirement_type == REQUIREMENT_PASS_QUIZ and row.quiz == quiz:
			if row.status == "Unavailable":
				continue
			touched |= _refresh_quiz_requirement(assignment, row, member, quiz)
	if touched:
		_refresh_counts(assignment)
		assignment.flags.homework_service = True
		try:
			assignment.save(ignore_permissions=True)
		except frappe.TimestampMismatchError:
			# This runs inside the quiz submission's own save; a concurrent homework
			# write must never fail the submission. Recover deterministically (R19):
			# one immediate retry from the fresh row, and if the conflict persists,
			# an after-commit job that cannot be lost -- never a shrug that leaves
			# the last quiz result off the card.
			frappe.clear_last_message()
			_recompute_with_retry_or_enqueue(name, member=member, quiz=quiz)
			return
	# B06: the transition itself is retried even when no requirement row changed.
	# A card whose proofs are all stored but whose Review save was lost to two
	# consecutive write races must heal on the next recompute, not sit In Progress
	# forever -- `touched` says the rows moved, nothing about the aggregation.
	_maybe_auto_review(assignment)


def _recompute_with_retry_or_enqueue(name: str, *, member: str, quiz: str) -> None:
	"""The conflict-recovery half of R19: exactly one fresh retry, then a queued
	after-commit recompute. The student's quiz save has already succeeded; the
	requirement must catch up without anyone having to re-submit."""
	fresh = frappe.get_doc("LMS Homework Assignment", name)
	fresh.flags.homework_service = True
	for row in fresh.requirements:
		if row.requirement_type == REQUIREMENT_PASS_QUIZ and row.quiz == quiz:
			if row.status != "Unavailable":
				_refresh_quiz_requirement(fresh, row, member, quiz)
	_refresh_availability(fresh)
	_refresh_counts(fresh)
	try:
		fresh.save(ignore_permissions=True)
		_maybe_auto_review(fresh)
		return
	except frappe.TimestampMismatchError:
		frappe.clear_last_message()
	if not frappe.flags.in_test:
		frappe.enqueue(
			recompute_quiz_requirements,
			queue="short",
			enqueue_after_commit=True,
			member=member,
			quiz=quiz,
		)


def _refresh_availability(assignment) -> bool:
	"""Persist the truth about deleted sources (R06): a checkable row whose
	material is gone reads Unavailable in the database itself, so counts and
	transitions agree with what the detail page shows -- no stale "100% done"
	over a dead source."""
	changed = False
	for row in assignment.requirements:
		alive = source_alive(row)
		if not alive and row.status != "Unavailable":
			row.status = "Unavailable"
			row.completed_at = None
			row.proof_type = None
			row.proof_name = None
			changed = True
		elif alive and row.status == "Unavailable":
			row.status = "Pending"
			changed = True
	return changed


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
		if not row.lesson and not assignment.first_opened_at and assignment.status == STATUS_TO_DO:
			# A standalone quiz passed straight from the course: the student is
			# working the material, which starts the card (spec 7, R10).
			assignment.first_opened_at = now_datetime()
			assignment.status = STATUS_IN_PROGRESS
			_add_history(assignment, "started", STATUS_TO_DO, STATUS_IN_PROGRESS)
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


def _maybe_auto_review(assignment) -> None:
	"""In Progress + everything confirmed + nothing unavailable + no pending
	rework -> Review, recorded once. Reads and refreshes never re-fire it.

	Availability is re-derived from the database first (R06): a deleted source
	must turn its row Unavailable before this decision, not after it on some
	later page view, so a card can never ride a stale Completed into Review.
	Counters move in the SAME write (B04): a row that just turned Unavailable
	must not leave a stale "1 of 1 done" on the card. A write race is recovered
	once from fresh state with every guard re-checked, then handed to the real
	queue (B06) -- never shrugged off with the card stranded in In Progress."""
	availability_changed = _refresh_availability(assignment)
	if availability_changed:
		_refresh_counts(assignment)

	eligible = _eligible_for_auto_review(assignment)
	if not (eligible or availability_changed):
		return
	if eligible:
		assignment.status = STATUS_REVIEW
		assignment.submitted_for_review_at = now_datetime()
		_add_history(assignment, "submitted_for_review", STATUS_IN_PROGRESS, STATUS_REVIEW)
	assignment.flags.homework_service = True
	try:
		assignment.save(ignore_permissions=True)
	except frappe.TimestampMismatchError:
		frappe.clear_last_message()
		_recover_auto_review_after_race(assignment)


def _apply_auto_review(doc) -> bool:
	"""The transition itself, guarded: only In Progress without pending rework,
	never a recalled card (its status column keeps the last live state, so
	``cancelled`` is checked explicitly). Returns False when inapplicable."""
	if not _eligible_for_auto_review(doc):
		return False
	doc.status = STATUS_REVIEW
	doc.submitted_for_review_at = now_datetime()
	_add_history(doc, "submitted_for_review", STATUS_IN_PROGRESS, STATUS_REVIEW)
	return True


def _recover_auto_review_after_race(assignment) -> None:
	"""The write-race half of B06: re-read the card, re-check every guard on
	CURRENT state (cancelled, status, pending rework) and re-apply once. A
	second conflict goes to the bounded queue instead of a log-and-give-up."""
	fresh = frappe.get_doc("LMS Homework Assignment", assignment.name)
	if fresh.cancelled:
		return
	changed = _refresh_availability(fresh)
	if changed:
		_refresh_counts(fresh)
	if _apply_auto_review(fresh):
		changed = True
	if not changed:
		return
	fresh.flags.homework_service = True
	try:
		fresh.save(ignore_permissions=True)
	except frappe.TimestampMismatchError:
		frappe.clear_last_message()
		_enqueue_assignment_recompute(fresh.name)


def _enqueue_assignment_recompute(name: str, attempt: int = 1) -> None:
	"""The finite, observable recovery path (B06): the real short queue re-runs
	the full catch-up for one card. Under tests no worker exists, so the deferral
	is logged instead -- visible in the Error Log, never silent."""
	if frappe.flags.in_test:
		frappe.log_error(
			title="Homework recompute deferred after repeated write races",
			message=f"assignment={name} attempt={attempt}",
		)
		return
	frappe.enqueue(
		recompute_assignment,
		queue="short",
		enqueue_after_commit=True,
		name=name,
		attempt=attempt,
	)


def recompute_assignment(name: str, attempt: int = 1) -> None:
	"""Queued catch-up for one card (B06): refresh availability and counters,
	then retry the auto-review transition. The proofs are already stored, so no
	student action is needed to un-stick a finished card. Re-enqueues itself a
	bounded number of times should writers keep racing it; past that bound the
	deferral is logged, and any later event re-triggers this same path."""
	assignment = frappe.get_doc("LMS Homework Assignment", name)
	if assignment.cancelled:
		return
	changed = _refresh_availability(assignment)
	if _apply_auto_review(assignment):
		changed = True
	if not changed:
		return
	assignment.flags.homework_service = True
	try:
		assignment.save(ignore_permissions=True)
	except frappe.TimestampMismatchError:
		frappe.clear_last_message()
		if attempt < 3:
			_enqueue_assignment_recompute(name, attempt + 1)
		else:
			frappe.log_error(
				title="Homework recompute kept losing write races",
				message=f"assignment={name} attempts={attempt}",
			)


def _eligible_for_auto_review(assignment) -> bool:
	return (
		assignment.status == STATUS_IN_PROGRESS
		and not assignment.cancelled
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
