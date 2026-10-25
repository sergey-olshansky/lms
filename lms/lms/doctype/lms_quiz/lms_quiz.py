# Copyright (c) 2021, FOSS United and contributors
# For license information, please see license.txt

import json
import os
import re
from binascii import Error as BinasciiError
from functools import partial

import frappe
from frappe import _, safe_decode
from frappe.core.doctype.file.utils import get_random_filename
from frappe.model.document import Document
from frappe.utils import (
	cint,
	comma_and,
	convert_utc_to_system_timezone,
	escape_html,
	get_datetime,
	now_datetime,
)
from frappe.utils.file_manager import safe_b64decode
from frappe.utils.html_utils import sanitize_html
from fuzzywuzzy import fuzz

from lms.lms.doctype.course_lesson.course_lesson import get_lesson_course, save_progress
from lms.lms.doctype.lms_content_author.lms_content_author import AuthoredDocument
from lms.lms.doctype.lms_question.lms_question import (
	QUESTION_CORRECTNESS_FIELDS,
	QUESTION_OPTION_FIELDS,
	QUESTION_POSSIBILITY_FIELDS,
)
from lms.lms.schedule_utils import assert_within_schedule, validate_schedule_fields
from lms.lms.utils import (
	can_modify_batch,
	can_modify_course,
	generate_slug,
	has_course_instructor_role,
	has_moderator_role,
)

# Quiz answers may embed inline images as data: URIs. Only raster image types are
# permitted. A data: URI with an active-document extension (.xhtml, .xsl, .html,
# .js, …) would otherwise be written to the public /files/ dir and served inline,
# enabling stored XSS on the LMS origin. SVG is excluded (script-bearing).
ALLOWED_DATAURL_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp"}

VIOLATION_EVENT_TYPES = {"tab_switch", "no_face", "multiple_faces", "focus_loss", "camera_disconnect"}
SUBMISSION_REASONS = {"manual", "timer_expired", "max_violations", "browser_closed"}
# One attempt cannot plausibly produce more proctoring events than this; the rest is a flood.
MAX_VIOLATION_EVENTS = 500
# Proctoring frames are ~320px JPEGs, so a frame past this is not a frame. Held as a
# data: URI length because that is the form it arrives in, and rejecting it before the
# base64 is decoded is what keeps a hostile payload cheap.
MAX_VIOLATION_FRAME_CHARS = 400_000
MAX_VIOLATION_FRAME_BYTES = 250 * 1024
# Per attempt, not per event: an attempt that trips two hundred times does not need two
# hundred stills to show what happened.
MAX_VIOLATION_FRAMES = 40


class LMSQuiz(AuthoredDocument, Document):
	def validate(self):
		self.validate_duplicate_questions()
		self.validate_limit()
		self.calculate_total_marks()
		self.validate_open_ended_questions()
		validate_schedule_fields(self)

	def validate_duplicate_questions(self):
		questions = [row.question for row in self.questions]
		rows = [i + 1 for i, x in enumerate(questions) if questions.count(x) > 1]
		if len(rows):
			frappe.throw(_("Rows {0} have the duplicate questions.").format(frappe.bold(comma_and(rows))))

	def validate_limit(self):
		if not self.shuffle_questions and self.limit_questions_to:
			self.limit_questions_to = 0

		if self.limit_questions_to and cint(self.limit_questions_to) >= len(self.questions):
			frappe.throw(_("Limit cannot be greater than or equal to the number of questions in the quiz."))

		if self.limit_questions_to and cint(self.limit_questions_to) < len(self.questions):
			marks = [question.marks for question in self.questions]
			if len(set(marks)) > 1:
				frappe.throw(_("All questions should have the same marks if the limit is set."))

	def calculate_total_marks(self):
		if len(self.questions) == 0:
			self.total_marks = 0
			self.passing_percentage = 100
			return

		if self.limit_questions_to:
			self.total_marks = sum(
				question.marks for question in self.questions[: cint(self.limit_questions_to)]
			)
		else:
			self.total_marks = sum(cint(question.marks) for question in self.questions)

	def validate_open_ended_questions(self):
		types = [question.type for question in self.questions]
		types = set(types)

		if "Open Ended" in types:
			if len(types) > 1:
				frappe.throw(
					_(
						"If you want open ended questions then make sure each question in the quiz is of open ended type."
					)
				)
			else:
				self.show_answers = 0

	def autoname(self):
		if not self.name:
			self.name = generate_slug(self.title, "LMS Quiz")

	def get_last_submission_details(self):
		"""Returns the latest submission for this user."""
		user = frappe.session.user
		if not user or user == "Guest":
			return

		result = frappe.get_all(
			"LMS Quiz Submission",
			fields="*",
			filters={"owner": user, "quiz": self.name},
			order_by="creation desc",
			page_length=1,
		)

		if result:
			return result[0]


def set_total_marks(questions: list) -> int:
	marks = 0
	for question in questions:
		marks += question.get("marks")
	return marks


def _parse_json_arg(raw, label):
	"""Parse a client-supplied JSON-string argument, raising a clean error (not a 500)."""
	try:
		return json.loads(raw)
	except (TypeError, ValueError):
		frappe.throw(_("Invalid {0} submitted.").format(label), frappe.ValidationError)


def _validate_quiz_results(results):
	"""Coarse shape check before process_results reads result["question_name"] / ["answer"].
	Rejects genuinely malformed items (non-dict, no question_name, or an answer that isn't a
	list) with a clean validation error. A blank/null answer element is NOT rejected here: the
	UI legitimately emits answer=[null] for a skipped open-ended question; process_results
	normalises those to "" so a student can still submit a partially-answered quiz.

	One question, one row. Duplicate question_name rows would each be graded and
	each carry marks while the attempt's denominator counts the question once,
	so the attempt could read past 100% — including duplicates of an
	already-credited question, which the retake merge would stamp at full
	marks twice. They are rejected here, before anything scores.
	"""
	seen: set[str] = set()
	for result in results:
		if not (
			isinstance(result, dict)
			and isinstance(result.get("question_name"), str)
			and result["question_name"]
		):
			frappe.throw(_("Invalid quiz results submitted."), frappe.ValidationError)
		answer = result.get("answer")
		if answer is not None and not isinstance(answer, list):
			frappe.throw(_("Invalid quiz results submitted."), frappe.ValidationError)
		if result["question_name"] in seen:
			frappe.throw(
				_("Duplicate answers for the same question cannot be submitted."),
				frappe.ValidationError,
			)
		seen.add(result["question_name"])


@frappe.whitelist()
def submit_quiz(
	quiz: str,
	results: str | None = None,
	violation_count: int = 0,
	submission_reason: str = "manual",
	violation_events: str | None = None,
	question_pool: str | list | None = None,
):
	if not isinstance(quiz, str):
		frappe.throw(_("Invalid quiz."), frappe.ValidationError)

	results = _parse_json_arg(results, _("quiz results")) if results else []
	if not isinstance(results, list):
		frappe.throw(_("Invalid quiz results submitted."), frappe.ValidationError)
	_validate_quiz_results(results)

	quiz_details = frappe.db.get_value(
		"LMS Quiz",
		quiz,
		[
			"name",
			"title",
			"total_marks",
			"passing_percentage",
			"lesson",
			"course",
			"enable_negative_marking",
			"marks_to_cut",
			"enable_proctoring",
			"max_violations",
			"enable_scheduling",
			"schedule_start",
			"schedule_end",
			"limit_questions_to",
		],
		as_dict=1,
	)
	if not quiz_details:
		frappe.throw(_("Invalid quiz."), frappe.ValidationError)

	from lms.lms.permissions import can_access_quiz

	if not can_access_quiz(quiz):
		frappe.throw(_("You are not authorized to submit this quiz."), frappe.PermissionError)

	assert_within_schedule(
		quiz_details.enable_scheduling,
		quiz_details.schedule_start,
		quiz_details.schedule_end,
		label=quiz_details.title or _("This quiz"),
	)

	data = process_results(results, quiz_details)
	is_open_ended = data["is_open_ended"]

	# A retake only asks the never-credited questions; the credited answers of
	# earlier attempts ride along so this attempt's score accounts for them
	# (#32). The denominator follows the same coverage — unique credited
	# questions plus this attempt's offered pool at current marks — so a
	# limited shuffled quiz can no longer score past 100% across retakes.
	quiz_questions = _quiz_question_rows(quiz)
	credited = _credited_question_rows(quiz, frappe.session.user)
	carried_graded = merge_credited_results(quiz_questions, credited, data["results"])
	attempt_pool = _validated_question_pool(
		quiz_questions, _parse_question_pool(question_pool), credited
	)
	# The SAME validated pool feeds the score denominator and the persisted
	# record (F03/round 9): whatever the client declared, only the
	# resolver-accepted form is ever stored or scored.
	score_out_of = resolve_attempt_score_out_of(
		quiz_details, quiz_questions, credited, data["results"], attempt_pool
	)

	proctoring = _build_proctoring_record(quiz_details, violation_count, submission_reason, violation_events)

	# Score and percentage are the submission's responsibility. Its validate()
	# runs validate_marks() + set_percentage() on save. Read them back rather
	# than recomputing here, so the two paths can't drift.
	submission = create_submission(
		quiz,
		data["results"],
		score_out_of,
		quiz_details.passing_percentage,
		violation_count=proctoring["violation_count"],
		submission_reason=proctoring["submission_reason"],
		carried_graded=carried_graded,
		attempt_pool=attempt_pool,
	)
	percentage = submission.percentage or 0
	save_progress_after_quiz(quiz_details, percentage)

	_save_violation_events(submission.name, proctoring["events"])
	_attach_answer_files(data["answer_files"], submission.name)

	# The attempt report email (#34) is a side effect of completion, never of
	# grading: it rides after commit so the queued job reads a submission that
	# exists, and its failure can never cost the learner their attempt.
	from lms.lms.doctype.lms_quiz.quiz_attempt_report import enqueue_attempt_report_email

	enqueue_attempt_report_email(submission.name)

	return {
		"score": submission.score,
		"score_out_of": submission.score_out_of,
		"submission": submission.name,
		"pass": percentage >= quiz_details.passing_percentage,
		"percentage": percentage,
		"is_open_ended": is_open_ended,
	}


def _attach_answer_files(file_names: list[str], submission: str) -> None:
	"""Bind a learner's inline answer images to the submission that carries them.

	A private File with no attachment is readable by its owner alone, which would hide
	the learner's evidence from the grader. Attaching defers to File.has_permission,
	and so to LMS Quiz Submission's own read rule.
	"""
	if not file_names:
		return

	File = frappe.qb.DocType("File")
	(
		frappe.qb.update(File)
		.set(File.attached_to_doctype, "LMS Quiz Submission")
		.set(File.attached_to_name, submission)
		.where(File.name.isin(file_names))
	).run()


def _build_proctoring_record(
	quiz_details: dict,
	violation_count: int,
	submission_reason: str,
	violation_events: str | None,
) -> dict:
	"""Decide what proctoring evidence is actually stored for a submission.

	Every field here is reported by the learner's own browser, so the fields are checked against
	each other rather than believed one at a time. The event log is treated as the record and the
	stored count is derived from it, so a learner cannot log five tab switches and report zero,
	nor inflate a count past the events behind it. A caller that sends no event list at all (the
	pagehide beacon) keeps its reported count — there is nothing to derive from — but still cannot
	claim a reason its count does not support.

	What cross-checking cannot do is catch a client that reports nothing. An empty event list with
	a zero count is indistinguishable from an attempt that had nothing to report, and no rule here
	can separate them while the browser is the only witness — tightening one field only moves
	which field a tampered client has to lie about. So a clean log is the absence of evidence, not
	evidence of absence. Making silence itself suspicious takes a client that checks in on a
	schedule, so that a gap in the trail is the finding.
	"""
	reason = submission_reason if submission_reason in SUBMISSION_REASONS else "manual"

	if not quiz_details.enable_proctoring:
		# Nothing was being watched, so there is no evidence to keep whatever the client sent.
		return {
			"violation_count": 0,
			"submission_reason": "manual" if reason == "max_violations" else reason,
			"events": [],
		}

	events = _normalise_violation_events(violation_events)
	if violation_events:
		count = sum(1 for event in events if event["severity"] == "violation")
	else:
		count = cint(violation_count)

	max_violations = cint(quiz_details.max_violations)
	# The count is the evidence; make the reason agree with it in both directions.
	if max_violations and count >= max_violations:
		reason = "max_violations"
	elif reason == "max_violations":
		reason = "manual"

	return {"violation_count": count, "submission_reason": reason, "events": events}


def _normalise_violation_events(raw_events: str | None) -> list[dict]:
	"""Coerce the client's event list into rows we are willing to store: a known event type, a
	known severity, and a timestamp that cannot be in the future."""
	if not raw_events:
		return []

	events = _parse_json_arg(raw_events, _("violation events"))
	if not isinstance(events, list):
		frappe.throw(_("Invalid violation events submitted."), frappe.ValidationError)

	received_at = now_datetime()
	normalised = []
	for event in events[:MAX_VIOLATION_EVENTS]:
		if not isinstance(event, dict):
			continue
		event_type = event.get("eventType") or event.get("event_type")
		if event_type not in VIOLATION_EVENT_TYPES:
			continue
		severity = event.get("severity")
		normalised.append(
			{
				"event_type": event_type,
				"severity": severity if severity in ("violation", "warning") else "violation",
				"timestamp": _violation_event_timestamp(event.get("timestamp"), received_at),
				"frame": _violation_event_frame(event.get("frame")),
			}
		)
	return normalised


def _violation_event_frame(raw_frame):
	"""Keep the camera still only if it is plausibly one. Anything else is dropped rather than
	thrown for: the frame is supporting evidence, and losing it must not cost the submission."""
	if not isinstance(raw_frame, str):
		return None
	if not raw_frame.startswith("data:image/"):
		return None
	if len(raw_frame) > MAX_VIOLATION_FRAME_CHARS:
		return None
	return raw_frame


def _violation_event_timestamp(raw_timestamp, received_at):
	"""JS sends Date.toISOString(), which is always UTC — store it in the site's timezone so the
	instructor's activity table reads in the same clock as every other date on the page. A stamp
	we cannot parse, or one from a client clock running ahead of ours, becomes the receive time."""
	if not raw_timestamp:
		return received_at
	try:
		timestamp = convert_utc_to_system_timezone(get_datetime(raw_timestamp)).replace(tzinfo=None)
	except Exception:
		return received_at
	return received_at if not timestamp or timestamp > received_at else timestamp


def _save_violation_events(submission_name: str, events: list[dict]):
	"""Best effort. The graded submission is already saved and carries the headline
	violation_count, so losing the detail log must not fail the learner's submission."""
	if not events:
		return

	user = frappe.session.user
	now = now_datetime()
	# Names are ours to choose, so they are kept: the camera stills are attached to these
	# rows afterwards, and bulk_insert hands nothing back to attach them to.
	names = [frappe.generate_hash(length=10) for _ in events]
	rows = [
		(
			name,
			now,  # creation
			now,  # modified
			user,  # modified_by
			user,  # owner
			0,  # docstatus
			0,  # idx
			submission_name,  # quiz_submission
			event["event_type"],
			event["severity"],
			event["timestamp"],
		)
		for name, event in zip(names, events, strict=True)
	]
	try:
		frappe.db.bulk_insert(
			"LMS Quiz Violation Log",
			fields=[
				"name",
				"creation",
				"modified",
				"modified_by",
				"owner",
				"docstatus",
				"idx",
				"quiz_submission",
				"event_type",
				"severity",
				"timestamp",
			],
			values=rows,
		)
	except Exception:
		frappe.log_error(title=f"Could not save quiz violation events for {submission_name}")
		return

	_attach_violation_frames(names, events)


def _attach_violation_frames(names: list[str], events: list[dict]):
	"""Store each camera still as a private File hung off its own log row, so a frame is
	reachable only through the row it belongs to and inherits that row's audience.

	Best effort for the same reason as the log itself: a frame that will not decode is not
	worth failing a graded submission over."""
	saved = 0
	for name, event in zip(names, events, strict=True):
		if saved >= MAX_VIOLATION_FRAMES:
			break
		if not event.get("frame"):
			continue
		try:
			if _save_violation_frame(name, event["frame"]):
				saved += 1
		except Exception:
			frappe.log_error(title=f"Could not save proctoring frame for {name}")


def _save_violation_frame(log_name: str, data_url: str) -> bool:
	"""Decode one data: URI onto a private File attached to log_name. Returns whether it
	was stored."""
	headers, separator, content = data_url.partition(",")
	if not separator or not content:
		return False

	mimetype = headers.split("data:", 1)[1].split(";", 1)[0]
	if not mimetype.lower().startswith("image/"):
		return False

	try:
		decoded = safe_b64decode(content.encode("utf-8"))
	except BinasciiError:
		return False
	if not decoded or len(decoded) > MAX_VIOLATION_FRAME_BYTES:
		return False

	filename = get_random_filename(content_type=mimetype)
	# Same allowlist the answer images use: an active-document extension here would be
	# written under /files/ and served inline.
	if os.path.splitext(filename)[1].lower() not in ALLOWED_DATAURL_IMAGE_EXTENSIONS:
		return False

	# The learner is writing evidence against their own attempt: File checks write on the
	# doctype it is attached to, and a student holds nothing on LMS Quiz Violation Log — only
	# System Manager and Instructor do. Without the bypass the attachment fails for exactly the
	# person it is meant to record. The row it hangs off was created by this same call chain a
	# moment earlier, and the frame reaches nobody the row does not.
	# nosemgrep: lms-unjustified-ignore-permissions - proctoring evidence written by the learner it records
	frappe.get_doc(
		{
			"doctype": "File",
			"file_name": filename,
			"content": decoded,
			"decode": False,
			"is_private": 1,
			"attached_to_doctype": "LMS Quiz Violation Log",
			"attached_to_name": log_name,
		}
	).insert(ignore_permissions=True)
	return True


@frappe.whitelist()
def is_open_ended_submission(submission: str) -> bool:
	quiz = frappe.db.get_value("LMS Quiz Submission", submission, "quiz")
	if not quiz:
		return False
	question_type = frappe.db.get_value("LMS Quiz Question", {"parent": quiz}, "type")
	return question_type == "Open Ended"


@frappe.whitelist()
def get_quiz_violation_logs(submission: str):
	if not frappe.db.exists("LMS Quiz Submission", submission):
		frappe.throw(_("Invalid submission."), frappe.ValidationError)
	if not (
		frappe.db.get_value("LMS Quiz Submission", submission, "member") == frappe.session.user
		or frappe.has_permission("LMS Quiz Submission", "read", submission)
	):
		frappe.throw(_("Insufficient Permission"), frappe.PermissionError)
	# The caller is already authorised above, against the parent submission: either they
	# own it or they hold read on it. The log rows carry no permissions of their own —
	# they are only ever read through this endpoint — so reading them under the check
	# already made is the access rule, not a bypass of one.
	# nosemgrep: lms-unjustified-ignore-permissions - access is gated on the parent submission above
	logs = frappe.get_all(
		"LMS Quiz Violation Log",
		filters={"quiz_submission": submission},
		fields=["name", "event_type", "severity", "timestamp"],
		order_by="timestamp asc",
		ignore_permissions=True,
	)
	_attach_frame_urls(logs)
	return logs


def _attach_frame_urls(logs: list[dict]):
	"""Fold each row's camera still onto the row. One query for the lot rather than one per
	row, and the caller has already been authorised for every row it is given."""
	if not logs:
		return

	# nosemgrep: lms-unjustified-ignore-permissions - the rows these hang off were authorised above
	frames = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "LMS Quiz Violation Log",
			"attached_to_name": ("in", [log["name"] for log in logs]),
		},
		fields=["attached_to_name", "file_url"],
		ignore_permissions=True,
	)
	by_log = {frame["attached_to_name"]: frame["file_url"] for frame in frames}
	for log in logs:
		log["frame"] = by_log.get(log["name"])


def process_results(results: list, quiz_details: dict):
	is_open_ended = False
	answer_files: list[str] = []

	for result in results:
		question_details = frappe.db.get_value(
			"LMS Quiz Question",
			{"parent": quiz_details.name, "question": result["question_name"]},
			["question", "marks", "question_detail", "type"],
			as_dict=1,
		)
		# The question must belong to this quiz. A stale/forged submission can name a row
		# that no longer resolves for quiz_details; reject cleanly instead of NoneType-500ing.
		if not question_details:
			frappe.throw(_("Invalid quiz results submitted."), frappe.ValidationError)

		# Normalise the answer to a non-empty list of strings so re.sub/join/[0] below can't
		# choke on a null/empty element (the UI sends [null] for a skipped open-ended answer).
		result["answer"] = [a if isinstance(a, str) else "" for a in (result.get("answer") or [])] or [""]

		result["question_name"] = question_details.question
		result["question"] = question_details.question_detail
		result["marks_out_of"] = question_details.marks
		result["question_type"] = question_details.type

		if question_details.type != "Open Ended":
			if question_details.type == "User Input":
				correct = bool(check_input_answers(question_details.question, result["answer"][0]))
			else:
				correct = verify_answer(question_details.question, result["answer"])
			result["answer"] = ", ".join(result["answer"])
			if correct:
				result["marks"] = question_details.marks
			else:
				result["marks"] = -quiz_details.marks_to_cut if quiz_details.enable_negative_marking else 0
			result["is_correct"] = 1 if correct else 0
			# The machine's verdict is a verdict (task #35, C01): objective rows
			# arrive graded, only open-ended answers wait for a human one.
			result["graded"] = 1

		else:
			is_open_ended = True
			result["is_correct"] = 0
			answer = re.sub(
				r'<img[^>]*src\s*=\s*["\'](?=data:)(.*?)["\']',
				partial(_save_file, answer_files),
				result["answer"][0],
			)
			# Defense-in-depth: the answer is later rendered in the instructor's
			# privileged grading view (QuizSubmission.vue). The frontend already
			# wraps it in sanitizeRichHTML, but a student-controlled answer must
			# not be stored as live HTML that other surfaces could render raw.
			result["answer"] = sanitize_html(answer, always_sanitize=True)

	return {
		"results": results,
		"is_open_ended": is_open_ended,
		"answer_files": answer_files,
	}


def verify_answer(question: str, answer: list):
	question_details = get_question_details(question)

	if question_details.multiple:
		for option_field, correctness_field in zip(
			QUESTION_OPTION_FIELDS, QUESTION_CORRECTNESS_FIELDS, strict=True
		):
			option = question_details[option_field]
			is_correct = question_details[correctness_field]
			if option in answer and not is_correct:
				return False
			if is_correct and option not in answer:
				return False
		return True

	correct = False
	for option_field, correctness_field in zip(
		QUESTION_OPTION_FIELDS, QUESTION_CORRECTNESS_FIELDS, strict=True
	):
		if question_details[option_field] in answer:
			correct = question_details[correctness_field]
	return correct


def _quiz_question_rows(quiz: str) -> dict[str, dict]:
	"""The quiz's live question rows, keyed by question name (#32).

	Live means the quiz still carries the row AND its LMS Question still
	exists — the exact set a client can offer — because the retake pool and
	the cumulative denominator are both bounded by what the quiz can ask
	today. Marks are the quiz row's current ones.
	"""
	rows = frappe.get_all(
		"LMS Quiz Question",
		filters={"parent": quiz, "parenttype": "LMS Quiz"},
		fields=["question", "question_detail", "marks", "type"],
	)
	if not rows:
		return {}
	# Question rows whose LMS Question has been deleted are unreachable from
	# any client; a denominator counting them would punish every honest taker.
	# nosemgrep: lms-unjustified-ignore-permissions - read behind submit's own quiz access check
	existing = set(
		frappe.get_all(
			"LMS Question",
			filters={"name": ("in", [row.question for row in rows if row.question])},
			pluck="name",
			ignore_permissions=True,
		)
	)
	return {row.question: row for row in rows if row.question and row.question in existing}


def _credited_question_rows(quiz: str, member: str) -> dict[str, dict]:
	"""The member's already-credited answers on this quiz, across every previous
	attempt (#32).

	A credited answer is one that grading recorded at full marks: objective rows
	land there through the answer check, an open-ended row through an
	instructor's full-mark grade. A partially graded open-ended answer is NOT
	credited — the learner may re-answer it on a retake and have the new answer
	graded, which is the only way to improve a partial mark.

	Keyed by question name; when several attempts credit the same question, any
	of them carries the credit (their verdicts are identical at full marks).
	"""
	if not member or member == "Guest":
		return {}

	previous = frappe.get_all(
		"LMS Quiz Submission",
		filters={"quiz": quiz, "member": member},
		pluck="name",
	)
	if not previous:
		return {}

	# Reading the caller's own submissions back: the member filter above is the
	# audience, so the child rows need no permission pass of their own.
	# nosemgrep: lms-unjustified-ignore-permissions - the member's own attempt rows, gated by the member filter above
	rows = frappe.get_all(
		"LMS Quiz Result",
		filters={"parent": ("in", previous), "parenttype": "LMS Quiz Submission"},
		fields=[
			"question_name",
			"question",
			"answer",
			"marks",
			"marks_out_of",
			"question_type",
			"is_correct",
		],
	)
	credited: dict[str, dict] = {}
	for row in rows:
		if not row.question_name:
			continue
		if cint(row.marks_out_of) <= 0 or cint(row.marks) < cint(row.marks_out_of):
			continue
		credited.setdefault(row.question_name, row)
	return credited


def merge_credited_results(quiz_questions: dict, credited: dict, results: list) -> set:
	"""Fold the member's already-credited answers into a retake's results (#32).

	The retake UI offers only the never-credited questions; the credited ones are
	carried into this attempt's result table at the quiz's CURRENT marks, so the
	attempt's score, percentage and pass verdict account for them and history
	stays whole — every attempt keeps its own submission document.

	A credited question the client re-submits anyway (a stale tab, a hand-built
	request) keeps its credited verdict and the answer that earned it: credit
	already earned cannot be lost to a re-answer. A question that has since left
	the quiz is not carried — its marks no longer exist to be credited.

	In-place on ``results``, before create_submission scores the attempt. Returns
	the set of question names the SERVER carried, so the submission's validate
	can tell a recorded verdict riding along (D02) from a client-forged
	``graded`` flag -- the flag alone is never trusted on a member's save.
	"""
	if not credited:
		return set()

	carried: set = set()
	submitted = set()
	for result in results:
		name = result.get("question_name")
		submitted.add(name)
		if name not in credited:
			continue
		current = quiz_questions.get(name)
		marks = cint(current.marks) if current else cint(result.get("marks_out_of"))
		source = credited[name]
		result["answer"] = source.answer or ""
		result["marks"] = marks
		result["marks_out_of"] = marks
		result["is_correct"] = 1
		# Carried answers carry their verdict with them (task #35, C01).
		result["graded"] = 1
		carried.add(name)

	for question_name, source in credited.items():
		if question_name in submitted:
			continue
		current = quiz_questions.get(question_name)
		if not current:
			continue
		results.append(
			{
				"question_name": question_name,
				"question": current.question_detail,
				"question_type": current.type,
				"answer": source.answer or "",
				"marks": cint(current.marks),
				"marks_out_of": cint(current.marks),
				"is_correct": 1,
				"graded": 1,
			}
		)
		carried.add(question_name)
	return carried


def _parse_question_pool(raw) -> list[str] | None:
	"""The client's declaration of the questions this attempt was offered.

	``None`` means the client declared nothing (an older client, a beacon that
	lost its state); an empty/invalid declaration is returned as-is so the
	denominator resolver can judge it. Names are only strings, deduplicated,
	order-free.
	"""
	if raw is None:
		return None
	if isinstance(raw, str):
		pool = _parse_json_arg(raw, _("question pool"))
	else:
		pool = raw
	if not isinstance(pool, list):
		frappe.throw(_("Invalid question pool submitted."), frappe.ValidationError)
	seen: dict[str, None] = {}
	for name in pool:
		if not isinstance(name, str) or not name:
			frappe.throw(_("Invalid question pool submitted."), frappe.ValidationError)
		seen.setdefault(name)
	return list(seen)


def _validated_question_pool(
	quiz_questions: dict, pool: list[str] | None, credited: dict | None = None
) -> list[str] | None:
	"""The client-declared offered pool, reduced to the form the score
	resolver accepts: unique, uncredited names that are questions of THIS quiz.
	A corrupted/foreign/duplicated/already-credited declaration is narrowed --
	the pool is an optimisation input, never a trust boundary. An empty result
	reads as "client declared nothing" (None), the legacy shape.
	"""
	if pool is None:
		return None
	if not isinstance(pool, list):
		return None
	seen: dict[str, None] = {}
	credited = credited or {}
	for name in pool:
		if isinstance(name, str) and name in quiz_questions and name not in credited:
			seen.setdefault(name)
	return list(seen) or None


def resolve_attempt_score_out_of(
	quiz_details: dict,
	quiz_questions: dict,
	credited: dict,
	results: list,
	question_pool: list[str] | None,
) -> int:
	"""The cumulative denominator of an attempt (#32): the unique credited
	questions of earlier attempts plus the questions this attempt covers, each
	at the quiz's current marks.

	On a shuffled quiz limited to a few questions, retakes cover new questions
	while the credited ones ride along; against the quiz's fixed total_marks
	that union can outscore 100%. The denominator therefore follows the union:

	- A declared pool (what the client offered, answered or not) bounds the
	  attempt's coverage from below — skipping an offered, never-credited
	  question cannot lift the percentage, because its marks stay in the
	  denominator while its answer earns none.
	- Every submitted question joins the coverage whatever the declaration
	  said, so answers cannot be smuggled in beside a shrunk pool.
	- The declaration is bounded, not proven: the draw is the client's today
	  (the shuffle runs there). It must name live quiz questions, steer clear
	  of the credited set, and match what the quiz could have offered — within
	  the limit, and no shorter than the offered remainder. Anything else
	  widens the coverage to every question the quiz currently asks, the same
	  strict reading an absent declaration gets on a retake.
	- A first attempt with no declaration keeps the quiz's total_marks, which
	  is exactly the coverage such an attempt has always had.
	"""
	total_marks = cint(quiz_details.total_marks)
	if not credited and question_pool is None:
		return total_marks

	if question_pool is None:
		covered = set(quiz_questions)
	else:
		non_credited = {name for name in quiz_questions if name not in credited}
		declared = question_pool
		in_quiz = [name for name in declared if name in quiz_questions]
		pool = [name for name in in_quiz if name not in credited]
		limit = cint(quiz_details.limit_questions_to)
		bound = limit if limit else len(quiz_questions)
		declared_ok = (
			len(in_quiz) == len(declared)
			and len(pool) <= bound
			and len(pool) >= min(len(non_credited), bound)
		)
		covered = set(pool) if declared_ok else set(quiz_questions)

	covered |= {row.get("question_name") for row in results if row.get("question_name")}
	covered |= {name for name in credited if name in quiz_questions}
	return sum(
		cint(row.marks) for name, row in quiz_questions.items() if name in covered
	)


@frappe.whitelist()
def get_quiz_credited_questions(quiz: str) -> list[str]:
	"""Question names the current user has already credited on this quiz (#32).

	The retake UI hides these from the offered pool, so the learner answers only
	what was never credited. Reading one's own credits reveals nothing the
	per-attempt report does not: it lists verdicts of attempts the caller owns.
	"""
	from lms.lms.permissions import can_access_quiz

	if not isinstance(quiz, str) or not quiz:
		frappe.throw(_("Invalid quiz."), frappe.ValidationError)
	if not frappe.db.exists("LMS Quiz", quiz):
		frappe.throw(_("Invalid quiz."), frappe.ValidationError)
	if not can_access_quiz(quiz):
		frappe.throw(
			_("You are not authorized to view this quiz."), frappe.PermissionError
		)
	return sorted(_credited_question_rows(quiz, frappe.session.user))


def _save_file(created: list[str], match: re.Match) -> str:
	data = match.group(1).split("data:")[1]
	headers, content = data.split(",")
	mtype = headers.split(";", 1)[0]

	if not mtype.lower().startswith("image/"):
		frappe.throw(_("Only image data is allowed in quiz answers."))

	if isinstance(content, str):
		content = content.encode("utf-8")
	if b"," in content:
		content = content.split(b",")[1]

	try:
		content = safe_b64decode(content)
	except BinasciiError:
		frappe.flags.has_dataurl = True
		return f'<img src="#broken-image" alt="{get_corrupted_image_msg()}"'

	if "filename=" in headers:
		filename = headers.split("filename=")[-1]
		filename = safe_decode(filename).split(";", 1)[0]

	else:
		filename = get_random_filename(content_type=mtype)

	if os.path.splitext(filename)[1].lower() not in ALLOWED_DATAURL_IMAGE_EXTENSIONS:
		frappe.throw(_("File type of {0} is not allowed in quiz answers.").format(escape_html(filename)))

	# Private, not public: a /files/ answer image is readable by anyone holding the URL,
	# including the other learners sitting the same quiz. submit_quiz then binds it to
	# the submission, which is what lets the grader read it.
	_file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": filename,
			"content": content,
			"decode": False,
			"is_private": True,
		}
	)
	_file.save(ignore_permissions=True)
	created.append(_file.name)
	file_url = _file.unique_url
	frappe.flags.has_dataurl = True

	return f'<img src="{file_url}"'


def get_corrupted_image_msg():
	return _("Image: Corrupted Data Stream")


def create_submission(
	quiz: str,
	results: list,
	score_out_of: int,
	passing_percentage: float,
	violation_count: int = 0,
	submission_reason: str = "manual",
	carried_graded: set | None = None,
	attempt_pool: list | None = None,
):
	submission = frappe.new_doc("LMS Quiz Submission")
	# Which open answers the SERVER carried from earlier graded attempts (D02):
	# doc flags never cross the client boundary, so validate_grading_flags can
	# trust exactly these rows' graded=1 on the member's own save.
	submission.flags.carried_graded_questions = carried_graded or set()
	# F03/round 8: what this attempt was OFFERED, distinct from its saved
	# result rows -- merge_credited_results appends the carried answers, so
	# the rows alone cannot answer "what was the last retake about".
	submission.question_pool = json.dumps(attempt_pool) if attempt_pool else None
	submission.update(
		{
			"doctype": "LMS Quiz Submission",
			"quiz": quiz,
			"result": results,
			"score": 0,
			"score_out_of": score_out_of,
			"member": frappe.session.user,
			"percentage": 0,
			"passing_percentage": passing_percentage,
			"violation_count": violation_count,
			"submission_reason": submission_reason,
		}
	)
	submission.save(ignore_permissions=True)
	return submission


def _can_review_submission(quiz: str) -> bool:
	"""Return whether the current user may view answer keys for a quiz."""
	if not frappe.session.user or frappe.session.user == "Guest":
		return False
	quiz_details = frappe.db.get_value("LMS Quiz", quiz, ["owner", "course"], as_dict=True)
	if not quiz_details:
		return False

	if {"System Manager", "Moderator"}.intersection(frappe.get_roles()):
		return True
	if quiz_details.owner == frappe.session.user:
		return True
	if quiz_details.course and can_modify_course(quiz_details.course):
		return True
	for course in frappe.get_all("Course Lesson", filters={"quiz_id": quiz}, pluck="course"):
		if course and can_modify_course(course):
			return True

	assessment_batches = frappe.get_all(
		"LMS Assessment",
		filters={"assessment_type": "LMS Quiz", "assessment_name": quiz},
		pluck="parent",
	)
	return any(can_modify_batch(batch) for batch in assessment_batches)


def _submission_owner_may_view_answers(submission_doc) -> bool:
	"""Whether the submission's own owner may read its answer keys.

	The quiz's "Show Answers" checkbox is the one switch the owner chose
	(#1088): a learner sees the correct answers of a finished attempt exactly
	when the quiz already shows live answer verdicts, and never otherwise.
	Ownership is checked against the submission's member, so the flag can never
	unlock someone else's attempt.
	"""
	if not frappe.session.user or frappe.session.user == "Guest":
		return False
	if submission_doc.member != frappe.session.user:
		return False
	return bool(frappe.db.get_value("LMS Quiz", submission_doc.quiz, "show_answers"))


@frappe.whitelist()
def get_submission_correct_answers(submission: str) -> dict[str, list[str]]:
	"""Answer keys for one submission's review.

	Staff pass _can_review_submission as before; the submission's owner is
	additionally authorised when the quiz's show_answers is on (#1088). Nobody
	else — including other learners — receives keys.
	"""
	if not isinstance(submission, str) or not submission:
		frappe.throw(_("Invalid quiz submission."), frappe.ValidationError)

	submission_doc = frappe.get_doc("LMS Quiz Submission", submission)
	if not _can_review_submission(submission_doc.quiz) and not _submission_owner_may_view_answers(
		submission_doc
	):
		frappe.throw(
			_("You are not authorized to view correct quiz answers."),
			frappe.PermissionError,
		)
	submission_doc.check_permission("read")

	question_names = [row.question_name for row in submission_doc.result if row.question_name]
	if not question_names:
		return {}

	return _correct_answers_for_questions(question_names)


def _correct_answers_for_questions(question_names: list[str]) -> dict[str, list[str]]:
	"""The answer key rows for a set of questions.

	Split out of get_submission_correct_answers so the attempt-report PDF (#33)
	and its email (#34) render keys from the one existing key source, under the
	authorization their callers have already established.
	"""
	fields = [
		"name",
		"type",
		*QUESTION_OPTION_FIELDS,
		*QUESTION_CORRECTNESS_FIELDS,
		*QUESTION_POSSIBILITY_FIELDS,
	]
	questions = frappe.get_all(
		"LMS Question",
		filters=[["name", "in", question_names]],
		fields=fields,
		ignore_permissions=True,
	)
	correct_answers: dict[str, list[str]] = {}
	for question in questions:
		if question.type == "Choices":
			correct_answers[question.name] = [
				question[option]
				for option, is_correct in zip(
					QUESTION_OPTION_FIELDS, QUESTION_CORRECTNESS_FIELDS, strict=True
				)
				if question.get(is_correct) and question.get(option)
			]
		elif question.type == "User Input":
			correct_answers[question.name] = [
				question[possibility]
				for possibility in QUESTION_POSSIBILITY_FIELDS
				if question.get(possibility)
			]
		else:
			correct_answers[question.name] = []

	return correct_answers


def save_progress_after_quiz(quiz_details: dict, percentage: float):
	if not quiz_details.lesson or not quiz_details.course:
		return

	if quiz_details.passing_percentage and percentage < quiz_details.passing_percentage:
		return

	# save_progress refuses a locked lesson by raising, which would roll back the
	# submission create_submission() has already written. A quiz can be reached
	# without its lesson being open — can_access_quiz also grants through an
	# LMS Assessment on a batch — so skip the progress write instead of failing the
	# submit. The throw stays in _save_progress, which is the boundary for the
	# direct-call bypass.
	from lms.lms.permissions import get_locked_lessons

	course = get_lesson_course(quiz_details.lesson)
	if not course or quiz_details.lesson in get_locked_lessons(course):
		return

	save_progress(quiz_details.lesson, course)


@frappe.whitelist()
def check_answer(quiz: str, question: str, question_type: str, answers: str):
	from lms.lms.permissions import can_access_quiz

	if not can_access_quiz(quiz):
		frappe.logger("lms.security").warning(
			"Quiz answer check denied: user=%s quiz=%s", frappe.session.user, quiz
		)
		frappe.throw(_("You are not authorized to view this quiz."), frappe.PermissionError)

	ADMIN_ROLES = ("System Manager", "Moderator", "Course Creator", "Batch Evaluator")
	is_admin = any(role in ADMIN_ROLES for role in frappe.get_roles())

	if not frappe.db.exists("LMS Quiz Question", {"parent": quiz, "question": question}):
		frappe.throw(_("Question not found in this quiz."), frappe.PermissionError)

	if not is_admin and not frappe.db.get_value("LMS Quiz", quiz, "show_answers"):
		frappe.throw(
			_("Live answer checking is not enabled for this quiz."),
			frappe.PermissionError,
		)

	answers = _parse_json_arg(answers, _("answers")) if answers else []
	if not isinstance(answers, list):
		frappe.throw(_("Invalid answers submitted."), frappe.ValidationError)

	if question_type == "Choices":
		return check_choice_answers(question, answers)

	# A blank input answer (empty list, or the [null] the UI emits for an untouched field)
	# scores as incorrect; coerce to "" so answers[0] can't IndexError / feed None onward.
	answer = answers[0] if answers else ""
	return check_input_answers(question, answer if isinstance(answer, str) else "")


def get_question_details(question: str):
	fields = ["multiple"] + QUESTION_OPTION_FIELDS + QUESTION_CORRECTNESS_FIELDS
	return frappe.db.get_value("LMS Question", question, fields, as_dict=1)


def check_choice_answers(question: str, answers: list):
	question_details = get_question_details(question)
	is_correct = []

	for option_field, correctness_field in zip(
		QUESTION_OPTION_FIELDS, QUESTION_CORRECTNESS_FIELDS, strict=True
	):
		if question_details[option_field] in answers:
			is_correct.append(question_details[correctness_field])
		elif question_details[correctness_field]:
			is_correct.append(2)
		else:
			is_correct.append(0)

	return is_correct


def check_input_answers(question: str, answer: str):
	question_details = frappe.db.get_value("LMS Question", question, QUESTION_POSSIBILITY_FIELDS, as_dict=1)
	for field in QUESTION_POSSIBILITY_FIELDS:
		possibility = question_details[field]
		if possibility and re.fullmatch(r"[0-9]+", str(possibility).strip()):
			# A near match can accept a transposed digit in a required sequence.
			if str(possibility).strip() == re.sub(r"\s+", "", str(answer)):
				return 1
			continue
		if possibility and fuzz.token_sort_ratio(possibility, answer) > 85:
			return 1
	return 0


@frappe.whitelist()
def get_question_meta(questions: str | list):
	"""Return {question_name: {quizzes, type, multiple}} for the authoring UI.

	`multiple` comes from LMS Question because the quiz's own child row has no such
	column, so a collapsed card reading the row alone badges every multiple choice
	question as single until it is opened.
	"""
	if not (has_moderator_role() or has_course_instructor_role()):
		frappe.throw(_("You are not permitted to read question details."), frappe.PermissionError)

	if isinstance(questions, str):
		try:
			questions = json.loads(questions)
		except (ValueError, TypeError):
			frappe.throw(_("questions must be a JSON list of question names."))
	if not isinstance(questions, list):
		frappe.throw(_("questions must be a list."))
	questions = [q for q in questions if isinstance(q, str) and q]
	if not questions:
		return {}

	QQ = frappe.qb.DocType("LMS Quiz Question")
	rows = (
		frappe.qb.from_(QQ)
		.select(QQ.question, QQ.parent)
		.where(QQ.question.isin(questions))
		.where(QQ.parenttype == "LMS Quiz")
	).run(as_dict=True)

	seen = {}
	for row in rows:
		seen.setdefault(row.question, set()).add(row.parent)

	meta = {}
	for question in frappe.get_all(
		"LMS Question", filters={"name": ["in", questions]}, fields=["name", "type", "multiple"]
	):
		meta[question["name"]] = {
			"quizzes": len(seen.get(question["name"], ())),
			"type": question["type"],
			"multiple": cint(question["multiple"]),
		}
	return meta


QUESTION_BANK_TYPES = ("Choices", "User Input", "Open Ended")


def _name_list(value):
	"""Coerce a whitelisted list argument, which may arrive as a JSON string."""
	if isinstance(value, str):
		# parse_json raises on anything that is not JSON, and a filter narrowing the
		# bank is not worth a 500: an unreadable one narrows nothing.
		try:
			value = frappe.parse_json(value)
		except Exception:
			return []
	if not isinstance(value, list):
		return []
	return [item for item in value if isinstance(item, str) and item]


@frappe.whitelist()
def get_question_bank(
	quiz: str | None = None,
	search: str | None = None,
	question_type: str | None = None,
	exclude: list | str | None = None,
	allowed_types: list | str | None = None,
):
	"""List reusable LMS Questions for the bank picker, flagged for `quiz`."""
	if not (has_moderator_role() or has_course_instructor_role()):
		frappe.throw(_("You are not permitted to access the question bank."), frappe.PermissionError)

	filters = {}
	# The types this quiz can still take. Applied here rather than after the fact: one
	# page is all the picker gets, so a quiz holding the 100 most recently modified
	# questions drew an empty bank with hundreds left to choose from.
	offered = [t for t in _name_list(allowed_types) if t in QUESTION_BANK_TYPES]
	if question_type in QUESTION_BANK_TYPES:
		# Intersected, never replaced. A type the quiz cannot take has nothing to
		# offer, and answering with rows the picker then drops reads as a bug.
		if offered and question_type not in offered:
			return []
		filters["type"] = question_type
	elif offered:
		filters["type"] = ["in", offered]

	# Same reason. The caller knows which questions the quiz holds, including the rows
	# staged this session that no saved quiz row accounts for yet.
	excluded = _name_list(exclude)
	if excluded:
		filters["name"] = ["not in", excluded]

	or_filters = None
	if search and isinstance(search, str):
		like = f"%{search.strip()}%"
		or_filters = {"question": ["like", like], "name": ["like", like]}

	questions = frappe.get_all(
		"LMS Question",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "question", "type", "multiple", "marks"],
		order_by="modified desc",
		limit_page_length=100,
	)
	if not questions:
		return []

	in_quiz = set()
	if quiz and isinstance(quiz, str):
		in_quiz = set(
			frappe.get_all(
				"LMS Quiz Question",
				filters={"parent": quiz, "parenttype": "LMS Quiz"},
				pluck="question",
			)
		)

	# Marks belong to the question now. A quiz's own row can still carry a different
	# number, but the bank offers the question's, which is what a new row starts on.
	for q in questions:
		q["already_in_quiz"] = q["name"] in in_quiz
		# cint, not `or 1`: a question deliberately worth 0 marks (the field is
		# non_negative, not > 0) would otherwise be offered to the quiz as worth 1.
		q["default_marks"] = cint(q["marks"]) if q.get("marks") is not None else 1
	return questions
