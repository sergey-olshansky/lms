# Copyright (c) 2026, tutor LMS contributors
# For license information, please see license.txt

"""The server rendering of one quiz attempt's report (#33, #34).

The report's content contract is the one the learner-facing per-attempt report
(#27, ``QuizAttemptReportModal``) established: every answered question with its
full body (the live question text first, the submission's stored snapshot as
fallback), the learner's own answer, the strict verdict of the attempt's
grading, the marks, and — for viewers the server authorises — the correct
answers. The verdicts here mirror ``attemptRowStatus`` in
``frontend/src/utils/quizSummary.ts``; the two must not drift, and the unit
tests pin the shared cases.

Rendering happens server-side because a PDF cannot reuse the SPA component:
``render_attempt_report_html`` produces the same rows as HTML, and
``frappe.utils.pdf.get_pdf`` turns it into the PDF both the teacher's download
(#33) and the completion email (#34) reuse.
"""

import re

import frappe
from frappe import _

# Matches the modal's numbering: the position within the whole attempt,
# skipped questions included, so a filtered report still names rows as the
# learner saw them.
_RELATIVE_SRC = re.compile(r"""(src|href)=["'](?!https?://|data:|#)(/[^"']+)["']""")

_STATUS_LABELS = {
	"correct": "Correct",
	"incorrect": "Incorrect",
	"skipped": "Skipped",
	"pending": "Pending review",
}


def attempt_row_status(row) -> str:
	"""The strict verdict of one graded row, mirroring the report's statuses.

	Same order of questions as the frontend's ``attemptRowStatus``:

	- An open-ended answer that carries content has no verdict until an
	  instructor grades it — read as pending review, never as incorrect — unless
	  the grade already sits at full marks, which is what "credited" means (#32)
	  and reads as correct.
	- An empty answer is a skipped question whatever its type.
	- Only then does the stored binary verdict decide correct vs incorrect.
	"""
	from frappe.utils import cint

	answer = row.get("answer") if hasattr(row, "get") else None
	answered = bool((answer or "").strip())
	if row.get("question_type") == "Open Ended" and answered:
		marks_out_of = cint(row.get("marks_out_of"))
		if marks_out_of > 0 and cint(row.get("marks")) >= marks_out_of:
			return "correct"
		return "pending"
	if not answered:
		return "skipped"
	return "correct" if cint(row.get("is_correct")) else "incorrect"


def _question_live_texts(question_names: list[str]) -> dict[str, str]:
	"""The live question bodies, sanitized, for the report's live-first resolver."""
	from lms.lms.html_sanitizer import sanitize_rich_text

	if not question_names:
		return {}
	# The caller has cleared the audience for this report (a reviewing teacher,
	# or the job that emails one); the question rows carry no permission surface
	# of their own.
	# nosemgrep: lms-unjustified-ignore-permissions - read behind the report's own authorization
	rows = frappe.get_all(
		"LMS Question", filters={"name": ("in", question_names)}, fields=["name", "question"]
	)
	return {row.name: sanitize_rich_text(row.question or "") for row in rows}


def _absolute_asset_urls(html: str) -> str:
	"""Rewrite root-relative asset URLs to absolute ones for the PDF renderer.

	wkhtmltopdf fetches images over HTTP with no page origin to inherit, so a
	``/files/...`` answer image would render as a blank box without this.
	"""
	site = frappe.utils.get_url()
	if not site:
		return html
	return _RELATIVE_SRC.sub(lambda match: f'{match.group(1)}="{site}{match.group(2)}"', html)


def render_attempt_report_html(doc, correct_answers: dict[str, list[str]] | None = None) -> str:
	"""The attempt report as one standalone HTML document.

	``doc`` is the LMS Quiz Submission; ``correct_answers`` — the key rows from
	``_correct_answers_for_questions`` — is rendered only when the caller passes
	it, which is the caller asserting the viewer may see keys (#1088).
	"""
	from frappe.utils import cint, format_datetime

	rows = list(doc.result or [])
	live_texts = _question_live_texts(
		[row.get("question_name") for row in rows if row.get("question_name")]
	)

	parts = []
	skipped = 0
	for index, row in enumerate(rows, start=1):
		status = attempt_row_status(row)
		if status == "skipped":
			skipped += 1
		question = (live_texts.get(row.get("question_name")) or "").strip() or (
			row.get("question") or ""
		).strip()

		parts.append(f'<div class="qrow {status}">')
		parts.append(
			f'<div class="q"><span class="qnum">Q{index}:</span>'
			+ (_absolute_asset_urls(question) if question else _("Question text is not available"))
			+ "</div>"
		)
		parts.append(
			'<div class="a"><span class="alabel">' + _("Your answer:") + "</span>"
			+ _absolute_asset_urls(row.get("answer") or "") + "</div>"
		)
		marks = f'<span class="marks">{cint(row.get("marks"))} / {cint(row.get("marks_out_of"))}</span>'
		parts.append(
			f'<div class="verdict"><span class="chip {status}">'
			+ _(_STATUS_LABELS[status])
			+ f"</span>{marks}</div>"
		)
		if correct_answers is not None:
			keys = correct_answers.get(row.get("question_name")) or []
			parts.append(
				'<div class="keys"><span class="klabel">'
				+ _("Correct Answer:")
				+ "</span>"
				+ (", ".join(keys) if keys else "—")
				+ "</div>"
			)
		parts.append("</div>")

	meta = [
		_("Member"),
		f"{doc.member_name} ({doc.member})",
		"&middot;",
		_("Submitted On"),
		format_datetime(doc.creation, "dd MMM yyyy HH:mm"),
		"&middot;",
		_("Score"),
		f"{doc.score} / {doc.score_out_of}",
		"&middot;",
		_("Percentage"),
		f"{doc.percentage}%",
	]
	if cint(doc.violation_count):
		meta += ["&middot;", _("Violations"), str(doc.violation_count)]

	if skipped:
		parts.append(
			"<p class='skipped'>"
			+ _("{0} skipped questions are not included in this report.").format(skipped)
			+ "</p>"
		)

	return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
	body {{ font-family: sans-serif; font-size: 12px; color: #202124; margin: 24px; }}
	h1 {{ font-size: 18px; margin: 0 0 6px; }}
	.meta {{ color: #5f6368; font-size: 11px; margin-bottom: 18px; }}
	.qrow {{ border: 1px solid #dadce0; border-radius: 6px; padding: 10px; margin-bottom: 10px; }}
	.qrow.incorrect {{ border-color: #f6c5c1; background: #fdf0ef; }}
	.qrow.pending {{ border-color: #f5d4b3; background: #fdf6ec; }}
	.q {{ font-size: 12px; }}
	.qnum {{ font-weight: 600; margin-right: 6px; }}
	.a {{ margin-top: 6px; color: #3c4043; }}
	.alabel {{ color: #5f6368; font-size: 10px; text-transform: uppercase; margin-right: 6px; }}
	.verdict {{ margin-top: 8px; }}
	.chip {{ border-radius: 10px; font-size: 10px; padding: 2px 8px; }}
	.chip.correct {{ background: #34a853; color: #ffffff; }}
	.chip.incorrect {{ background: #ea4335; color: #ffffff; }}
	.chip.pending {{ background: #fbbc04; color: #202124; }}
	.chip.skipped {{ background: #f1f3f4; color: #5f6368; }}
	.marks {{ float: right; color: #5f6368; }}
	.keys {{ margin-top: 6px; border-left: 2px solid #dadce0; padding-left: 8px; color: #3c4043; }}
	.klabel {{ color: #5f6368; font-size: 10px; text-transform: uppercase; margin-right: 6px; }}
	.skipped {{ color: #5f6368; font-size: 11px; }}
	img {{ max-width: 100%; }}
</style></head>
<body>
<h1>{doc.quiz_title}</h1>
<div class="meta">{" ".join(str(part) for part in meta)}</div>
{''.join(parts) or '<p>' + _("No questions were answered in this attempt.") + '</p>'}
</body></html>"""


def _report_pdf(doc, with_correct_answers: bool) -> bytes:
	"""The attempt report as PDF bytes, from the one renderer (#33)."""
	from frappe.utils.pdf import get_pdf

	from lms.lms.doctype.lms_quiz.lms_quiz import _correct_answers_for_questions

	correct_answers = None
	if with_correct_answers:
		question_names = [row.get("question_name") for row in doc.result or [] if row.get("question_name")]
		correct_answers = _correct_answers_for_questions(question_names) if question_names else {}

	return get_pdf(render_attempt_report_html(doc, correct_answers=correct_answers))


def _attempt_report_filename(doc) -> str:
	from frappe.utils import cint

	# Submission names are ours (hash-style), but a defensive scrub keeps the
	# Content-Disposition header free of anything a filename must not carry.
	scrubbed = re.sub(r"[^A-Za-z0-9._-]+", "-", str(doc.name)).strip("-") or "attempt"
	percentage = cint(doc.percentage)
	return f"attempt-report-{scrubbed}-{percentage}.pdf"


@frappe.whitelist()
def download_attempt_report_pdf(submission: str) -> None:
	"""The teacher's PDF of one attempt's report (#33).

	The same renderer the completion email (#34) attaches; staff review rights
	(``_can_review_submission``) gate both the document and its answer keys.
	"""
	from lms.lms.doctype.lms_quiz.lms_quiz import _can_review_submission

	if not isinstance(submission, str) or not submission:
		frappe.throw(_("Invalid quiz submission."), frappe.ValidationError)

	doc = frappe.get_doc("LMS Quiz Submission", submission)
	if not _can_review_submission(doc.quiz):
		frappe.throw(
			_("You are not authorized to view this attempt report."), frappe.PermissionError
		)
	doc.check_permission("read")

	frappe.local.response["filename"] = _attempt_report_filename(doc)
	frappe.local.response["filecontent"] = _report_pdf(doc, with_correct_answers=True)
	frappe.local.response["type"] = "download"


def _email_transport_configured() -> bool:
	"""The same gate every other outgoing LMS email already answers to.

	Certification mail and mention notifications only go out when an enabled
	default outgoing Email Account exists (or the site carries mail_login
	credentials), so a site without mail never queues bounces. The attempt
	report email answers the same question rather than inventing its own switch.
	"""
	outgoing_email_account = frappe.get_cached_value(
		"Email Account", {"default_outgoing": 1, "enable_outgoing": 1}, "name"
	)
	return bool(outgoing_email_account or frappe.conf.get("mail_login"))


def enqueue_attempt_report_email(submission_name: str) -> None:
	"""Queue the teacher's copy of a finished attempt (#34).

	After commit, on a worker: the learner's submit request pays neither the PDF
	render nor the mail queue, and a job that finds no submission (a rolled-back
	request) simply does nothing.
	"""
	frappe.enqueue(
		send_attempt_report_email,
		queue="default",
		submission=submission_name,
		enqueue_after_commit=True,
	)


def _quiz_teacher_recipients(quiz: str, exclude: str | None = None) -> list[str]:
	"""The emails of the teachers a quiz's review rules already recognise (#34).

	Owner alone answers "who teaches this" only for a standalone quiz. A quiz
	reaches learners three ways — on its own, through a lesson of a course, on a
	batch's assessment plan — and the review rules (``_can_review_submission``,
	``can_modify_course``/``can_modify_batch``) name the same teachers for all
	three: the quiz's author, plus the users the Course Instructor rows assign
	to the placing courses and batches. Those assignments are the real,
	enumerable source of a teacher's address; moderators are a role, not an
	assignment, so they are not mailed here.

	Only enabled users with an email resolve; ``exclude`` drops the attempt's
	own member (their attempt is a preview, not a submission to review).
	"""
	if not quiz:
		return []

	users = set()
	owner = frappe.db.get_value("LMS Quiz", quiz, "owner")
	if owner:
		users.add(owner)

	# The same placements _can_review_submission walks: lessons naming the
	# quiz, and batch assessment plans running it.
	courses = frappe.get_all("Course Lesson", filters={"quiz_id": quiz}, pluck="course")
	batches = frappe.get_all(
		"LMS Assessment",
		filters={"assessment_type": "LMS Quiz", "assessment_name": quiz},
		pluck="parent",
	)
	parents = [course for course in courses if course] + [batch for batch in batches if batch]
	if parents:
		users.update(
			frappe.get_all(
				"Course Instructor",
				filters={"parent": ("in", parents)},
				pluck="instructor",
			)
		)

	users.discard(exclude)
	if not users:
		return []

	rows = frappe.get_all(
		"User", filters={"name": ("in", list(users)), "enabled": 1}, pluck="email"
	)
	recipients = {email for email in rows if email}
	return sorted(recipients)


def send_attempt_report_email(submission_name: str) -> None:
	"""Email the quiz's teachers the PDF report of a finished attempt (#34).

	Recipients resolve from the quiz's own placements — the author and the
	assigned Course Instructors of the courses and batches that run it, the
	same reading the review rules hold — never from a configured address. Best
	effort throughout: the submission is already saved and graded when this
	runs, so nothing here may raise back into the submit path; failures are
	logged and the attempt stands.
	"""
	from frappe.utils import get_url

	from lms.lms.utils import get_lms_route

	try:
		if not _email_transport_configured():
			return

		doc = frappe.get_doc("LMS Quiz Submission", submission_name)
		recipients = _quiz_teacher_recipients(doc.quiz, exclude=doc.member)
		if not recipients:
			# Nobody is left to review: no assignments, or the only teacher is
			# the member who sat the attempt.
			return

		pdf = _report_pdf(doc, with_correct_answers=True)
	except Exception:
		frappe.log_error(title=f"Could not build the attempt report email for {submission_name}")
		return

	subject = _("New attempt report: {0} — {1}").format(doc.quiz_title, doc.member_name)
	# The SPA page the teacher grades on, absolute so it survives any mail client.
	link = get_url() + get_lms_route(f"quiz-submission/{doc.name}")
	content = (
		f"<p>{_('A quiz attempt has been submitted.')}</p>"
		f"<p>{_('Quiz')}: {frappe.bold(doc.quiz_title)}<br>"
		f"{_('Member')}: {frappe.bold(doc.member_name)}<br>"
		f"{_('Score')}: {doc.score} / {doc.score_out_of} ({doc.percentage}%)</p>"
		f"<p><a href='{link}'>{_('Open the attempt report')}</a></p>"
	)
	try:
		frappe.sendmail(
			recipients=recipients,
			subject=subject,
			content=content,
			attachments=[
				{
					"fname": _attempt_report_filename(doc),
					"fcontent": pdf,
					"content-type": "application/pdf",
				}
			],
			header=[subject, "green"],
			retry=3,
		)
	except Exception:
		frappe.log_error(title=f"Could not send the attempt report email for {submission_name}")