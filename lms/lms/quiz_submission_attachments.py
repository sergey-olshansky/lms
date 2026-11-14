# Copyright (c) 2026, tutor LMS contributors
# For license information, please see license.txt

"""Solution files of one quiz submission (card #47).

The owner decision (Telegram #1880, 2026-11-14): a learner may attach ONE
optional bundle of solution files to a quiz submission AS A WHOLE -- never to
individual open questions -- with a total size cap of 100 MiB. Until the
teacher's second pass runs, the bundle is what the teacher scores the
open-answer part against; with no files and no text the teacher may simply
award nothing for the relevant task.

Model (mirrors the homework solution attachments of task #35/E03, which this
module deliberately does NOT reuse -- those rows are owned by an assignment
and carry assignment semantics):

- A row is a DRAFT while the attempt is being sat: ``quiz`` + ``member`` name
  it, ``submission`` is empty. The learner uploads and deletes drafts freely
  (staging, exactly like homework #45): each file lands as a PRIVATE File at
  once, so finishing the quiz only stamps the link.
- ``bind_draft_attachments`` (called by submit_quiz, same transaction) points
  every current draft row of the (quiz, member) at the new submission. From
  that moment the bundle is immutable for the learner -- a new attempt starts
  a fresh draft pool.
- The quota is 100 MiB total over the current DRAFT pool (a bundle was within
  it at the moment it bound, so every bound bundle is within it too).

Trust rules, inherited from the hardened homework module:

- The bytes are posted straight here in ONE request (the classic
  upload-then-register hand-off lost files in production on 2026-10-25).
- Extensions are explicitly allowlisted; known containers are checked against
  their real signatures, so a renamed mismatch is refused.
- Files are stored PRIVATE. Downloads ride the File's own private URL, so the
  member and the quiz's reviewers read them through the platform's
  permission-checked serving, everyone else gets 403.
- Listing/ZIP access is re-checked per call: the submission's member or a
  reviewer of the quiz (``_may_grade_submission``).
"""

from __future__ import annotations

import io
import mimetypes
import os
import re
import zipfile

import frappe
from frappe import _
from frappe.core.doctype.file.utils import get_safe_file_name
from frappe.utils import cint

# E03.3-style single number: 100 MiB total per submission bundle (owner
# decision #1880).
QUIZ_ATTACHMENT_QUOTA_BYTES = 100 * 1024 * 1024


def _lock_key(quiz: str, member: str) -> str:
	return f"quiz_attachment_quota:{quiz}:{member}"


def _may_review(quiz: str) -> bool:
	from lms.lms.doctype.lms_quiz_submission.lms_quiz_submission import _may_grade_submission

	return _may_grade_submission(quiz)


def _submission_for_viewer(submission: str):
	"""The submission the session user may see: its member or a quiz reviewer."""
	doc = frappe.get_doc("LMS Quiz Submission", submission)
	if doc.member != frappe.session.user and not _may_review(doc.quiz):
		frappe.throw(
			_("You are not allowed to view the files of this submission."),
			frappe.PermissionError,
		)
	return doc


def _draft_rows(quiz: str, member: str) -> list[dict]:
	# The member filter is the audience; rows never leave this module's
	# endpoints, which all re-check it.
	# nosemgrep: lms-unjustified-ignore-permissions - the member filter above is the audience
	return frappe.get_all(
		"LMS Quiz Submission Attachment",
		filters={"quiz": quiz, "member": member, "submission": ("is", "not set")},
		fields=["name", "file", "file_name", "file_size", "uploaded_at"],
		order_by="creation asc",
		ignore_permissions=True,
	)


def _quota_state(quiz: str, member: str) -> dict:
	rows = _draft_rows(quiz, member)
	used = sum(cint(row.file_size) for row in rows)
	return {
		"rows": rows,
		"used": used,
		"quota": QUIZ_ATTACHMENT_QUOTA_BYTES,
		"remaining": max(0, QUIZ_ATTACHMENT_QUOTA_BYTES - used),
	}


def _public_rows(rows: list[dict]) -> list[dict]:
	"""Rows as the UI shows them: the File's own private URL, nothing else."""
	if not rows:
		return []
	# nosemgrep: lms-unjustified-ignore-permissions - the caller was authorized on the parent submission/quiz
	files = frappe.get_all(
		"File",
		filters={"name": ("in", [row.file for row in rows] or ["__none__"])},
		fields=["name", "file_url", "is_private"],
		ignore_permissions=True,
	)
	urls = {row.name: row.file_url for row in files}
	out = []
	for row in rows:
		url = urls.get(row.file) or ""
		out.append(
			{
				"name": row.name,
				"file": row.file,
				"file_name": row.file_name,
				"file_size": cint(row.file_size),
				"uploaded_at": row.uploaded_at,
				"file_url": url if url.startswith("/private/files/") else "",
			}
		)
	return out


@frappe.whitelist()
def get_draft_attachments(quiz: str) -> dict:
	"""The member's staged bundle for the attempt being sat, plus the quota line."""
	from lms.lms.permissions import can_access_quiz

	if not isinstance(quiz, str) or not quiz or not frappe.db.exists("LMS Quiz", quiz):
		frappe.throw(_("Invalid quiz."), frappe.ValidationError)
	if not can_access_quiz(quiz):
		frappe.throw(_("You are not authorized to view this quiz."), frappe.PermissionError)

	state = _quota_state(quiz, frappe.session.user)
	return {
		"rows": _public_rows(state["rows"]),
		"used": state["used"],
		"quota": state["quota"],
		"remaining": state["remaining"],
	}


def _verify_bytes(extension: str, content: bytes) -> None:
	"""Supported format + real-container check, reusing the homework module's
	verdict so the two attachment flows can never disagree about a file type."""
	from lms.lms.homework_attachments import _verify_bytes as verify

	verify(extension, content)


def _extension_of(file_name: str) -> str:
	"""Local twin of the homework helper: same rule, no private cross-import
	wider than the one above."""
	from lms.lms.homework_attachments import _extension_of as extension_of

	return extension_of(file_name)


@frappe.whitelist()
def upload_quiz_attachment(
	quiz: str | None = None,
	doctype: str | None = None,
	docname: str | None = None,
) -> dict:
	"""Single-request staged upload: the multipart ``file`` is posted straight
	here and registered as a DRAFT bundle row in ONE transaction. The uploader's
	own doctype/docname form fields may carry the target quiz, exactly like the
	homework uploader."""
	from lms.lms.permissions import can_access_quiz

	if not quiz and doctype == "LMS Quiz" and docname:
		quiz = docname
	if not isinstance(quiz, str) or not quiz or not frappe.db.exists("LMS Quiz", quiz):
		frappe.throw(_("Invalid quiz."), frappe.ValidationError)
	if not can_access_quiz(quiz):
		frappe.throw(_("You are not authorized to view this quiz."), frappe.PermissionError)

	member = frappe.session.user
	upload = (getattr(frappe.request, "files", None) or {}).get("file")
	if upload is None:
		frappe.throw(_("No file received."), frappe.ValidationError)
	content = upload.stream.read()
	file_name = get_safe_file_name(os.path.basename(upload.filename or "")) or "file"
	size = len(content)
	if size <= 0:
		frappe.throw(_("The file is empty."), frappe.ValidationError)
	if size > QUIZ_ATTACHMENT_QUOTA_BYTES:
		frappe.throw(
			_("The file alone exceeds the {0} MB solution files limit.").format(
				QUIZ_ATTACHMENT_QUOTA_BYTES // (1024 * 1024)
			),
			frappe.ValidationError,
		)
	_verify_bytes(_extension_of(file_name), content)

	with frappe.db.advisory_lock(_lock_key(quiz, member)):
		used = _current_draft_bytes(quiz, member)
		if used + size > QUIZ_ATTACHMENT_QUOTA_BYTES:
			frappe.throw(
				_(
					"The solution files together cannot exceed {0} MB. Used: {1:.1f} MB,"
					" remaining: {2:.1f} MB."
				).format(
					QUIZ_ATTACHMENT_QUOTA_BYTES // (1024 * 1024),
					used / (1024 * 1024),
					max(0, QUIZ_ATTACHMENT_QUOTA_BYTES - used) / (1024 * 1024),
				),
				frappe.ValidationError,
			)
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_name,
				"folder": "Home",
				"is_private": 1,
				"content": content,
			}
		).insert(ignore_permissions=True)
		if not cint(file_doc.is_private) or not (file_doc.file_url or "").startswith(
			"/private/files/"
		):
			frappe.throw(
				_("The file could not be stored privately."), frappe.ValidationError
			)
		row = frappe.new_doc("LMS Quiz Submission Attachment")
		row.update(
			{
				"quiz": quiz,
				"member": member,
				"file": file_doc.name,
				"file_name": file_doc.file_name,
				"file_size": size,
				"content_type": mimetypes.guess_type(file_doc.file_name or "")[0]
				or "application/octet-stream",
				"uploaded_by": member,
				"uploaded_at": frappe.utils.now_datetime(),
			}
		)
		row.insert(ignore_permissions=True)
		frappe.db.set_value(
			"File",
			file_doc.name,
			{
				"attached_to_doctype": "LMS Quiz Submission Attachment",
				"attached_to_name": row.name,
			},
		)
		if not frappe.flags.in_test:
			frappe.db.commit()

	state = _quota_state(quiz, member)
	return {
		"name": row.name,
		"file_name": row.file_name,
		"state": {
			"used": state["used"],
			"quota": state["quota"],
			"remaining": state["remaining"],
		},
	}


def _current_draft_bytes(quiz: str, member: str) -> int:
	"""CURRENT read (FOR UPDATE) inside the advisory lock, so two parallel
	uploads cannot both spend the same remaining bytes."""
	row = frappe.db.sql(
		"SELECT COALESCE(SUM(`file_size`), 0) AS used"
		" FROM `tabLMS Quiz Submission Attachment`"
		" WHERE `quiz` = %s AND `member` = %s AND (`submission` IS NULL OR `submission` = '')"
		" FOR UPDATE",
		(quiz, member),
		as_dict=True,
	)
	return cint(row[0].used) if row else 0


@frappe.whitelist()
def delete_quiz_attachment(attachment: str) -> dict:
	"""The member removes one of their own still-draft files: the row goes, the
	stored File goes, its bytes return to the quota. A bound file is immutable."""
	row = frappe.get_doc("LMS Quiz Submission Attachment", attachment)
	if row.member != frappe.session.user:
		frappe.throw(
			_("Only the member who uploaded a file can remove it."), frappe.PermissionError
		)
	if row.submission:
		frappe.throw(
			_(
				"The quiz has already been finished. Files of a finished submission"
				" cannot be changed."
			),
			frappe.PermissionError,
		)
	with frappe.db.advisory_lock(_lock_key(row.quiz, row.member)):
		frappe.delete_doc("LMS Quiz Submission Attachment", row.name, ignore_permissions=True)
		if row.file and frappe.db.exists("File", row.file):
			frappe.delete_doc("File", row.file, ignore_permissions=True)
		if not frappe.flags.in_test:
			frappe.db.commit()
	state = _quota_state(row.quiz, row.member)
	return {
		"deleted": True,
		"state": {
			"used": state["used"],
			"quota": state["quota"],
			"remaining": state["remaining"],
		},
	}


def bind_draft_attachments(quiz: str, member: str, submission: str) -> int:
	"""Point every current draft row of the (quiz, member) at the submission
	that consumed them (card #47: finishing the quiz fixes the bundle)."""
	if not submission or not frappe.db.exists("LMS Quiz Submission", submission):
		return 0
	rows = _draft_rows(quiz, member)
	for row in rows:
		frappe.db.set_value("LMS Quiz Submission Attachment", row.name, "submission", submission)
	return len(rows)


def _bound_rows(submission: str) -> list[dict]:
	# nosemgrep: lms-unjustified-ignore-permissions - the viewer was authorized on the parent submission
	return frappe.get_all(
		"LMS Quiz Submission Attachment",
		filters={"submission": submission},
		fields=["name", "file", "file_name", "file_size", "uploaded_at"],
		order_by="creation asc",
		ignore_permissions=True,
	)


@frappe.whitelist()
def get_submission_attachments(submission: str) -> dict:
	"""The bound bundle, for the learner's read-only result view and the
	teacher's grading pane alike. Access: the submission's member or a quiz
	reviewer."""
	if not isinstance(submission, str) or not submission:
		frappe.throw(_("Invalid quiz submission."), frappe.ValidationError)
	_submission_for_viewer(submission)
	rows = _bound_rows(submission)
	return {"rows": _public_rows(rows), "count": len(rows)}


@frappe.whitelist()
def download_submission_archive(submission: str) -> None:
	"""One ZIP of the whole bundle for the reviewing teacher (card #47; the
	homework ZIP pattern of #46 applied to quiz submissions). Reviewer-only:
	the member keeps per-file access through their own private URLs."""
	if not isinstance(submission, str) or not submission:
		frappe.throw(_("Invalid quiz submission."), frappe.ValidationError)
	doc = frappe.get_doc("LMS Quiz Submission", submission)
	if doc.member == frappe.session.user or not _may_review(doc.quiz):
		frappe.throw(
			_("You are not authorized to download this archive."), frappe.PermissionError
		)

	rows = _bound_rows(submission)
	buffer = io.BytesIO()
	seen_names: set[str] = set()
	with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
		for index, row in enumerate(rows, start=1):
			try:
				file_doc = frappe.get_doc("File", row.file)
				content = file_doc.get_content()
				if isinstance(content, str):
					content = content.encode("utf-8", "surrogateescape")
			except Exception:
				frappe.log_error(
					title=f"Could not read quiz submission file {row.file} for {submission}"
				)
				continue
			name = row.file_name or f"file-{index}"
			if name in seen_names:
				root, ext = os.path.splitext(name)
				name = f"{root}-{index}{ext}"
			seen_names.add(name)
			archive.writestr(name, content)

	safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(submission)).strip("-") or "submission"
	frappe.local.response["filename"] = f"quiz-submission-files-{safe}.zip"
	frappe.local.response["filecontent"] = buffer.getvalue()
	frappe.local.response["type"] = "download"
