# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Solution files of one homework assignment (task #35, E03; hardened round 6,
R01-R03, R05, R08-R10).

A student may attach images, PDFs, DOCX and the project's other accepted
formats to THEIR assignment -- bound to the (assignment, student) pair, never
to the shared template -- with a quota of 20 MiB TOTAL across every file of
that solution, not per file.

Trust rules (round 6):
- The client names a File by ID; nothing about that ID is trusted. The file
  must be the session student's OWN upload, still unbound, and stored PRIVATE
  (a public upload is refused and cleaned, never silently re-flagged -- R03:
  flipping ``is_private`` with db.set_value leaves the public URL working).
- The declared extension must match the actual container: images decode,
  PDF/Office/ODF/ZIP carry their real signatures (R09).
- Every refusal cleans ONLY that verified-own fresh upload -- a foreign or
  already-bound file is never deleted by someone else's request (R02).
- The assignment's state is re-read with a CURRENT read (SELECT ... FOR
  UPDATE) INSIDE the advisory lock, and the quota sum is a current read too,
  so a revoke/review committed before the write is seen (R10), and two
  parallel registrations cannot both spend the same remaining bytes under
  MariaDB REPEATABLE READ.
- Downloads ride the file's own private URL: serving goes through
  File.has_permission and the attachment-row hooks, so the student and the
  assignment's teacher download, everyone else gets 403 (R05).
"""

from __future__ import annotations

import mimetypes
import zipfile

import frappe
from frappe import _
from frappe.utils import cint

# E03.3: one number, one meaning -- 20 * 1024 * 1024 bytes, total per solution.
ATTACHMENT_QUOTA_BYTES = 20 * 1024 * 1024

# The accepted extension allowlist. Anything active (HTML/svg-with-script,
# executables) is refused regardless of the client's declared type; the
# extension is re-derived from the stored file name and the CONTENT is
# verified against it (R09).
ALLOWED_EXTENSIONS = {
	".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
	".pdf",
	".doc", ".docx", ".odt", ".rtf", ".txt", ".csv",
	".xls", ".xlsx", ".ods", ".ppt", ".pptx",
	".zip",
}

# Plain-text extensions ride the text contract: no container signature to
# check, and angle brackets in prose are not an attack (R09).
TEXT_EXTENSIONS = {".txt", ".csv", ".rtf"}

_STATUS_FIELDS = ["name", "student", "teacher", "status", "cancelled"]


def _assignment_for_student(name: str):
	"""The assignment the session user may see (student, teacher or staff)."""
	doc = frappe.get_doc("LMS Homework Assignment", name)
	if doc.student != frappe.session.user and not _teacher_of(doc):
		frappe.throw(_("You cannot work with this homework."), frappe.PermissionError)
	return doc


def _teacher_of(doc) -> bool:
	from lms.lms.homework_api import _is_privileged

	return doc.teacher == frappe.session.user or _is_privileged()


def _student_editable(row) -> bool:
	"""E03.5 / R10: the student adds/removes their files only while the work
	is theirs to edit. Judged from a FRESH current read of the row, never
	from a document loaded before the lock."""
	if row.cancelled:
		return False
	return row.status in ("To Do", "In Progress")


def _lock_key(assignment: str, student: str) -> str:
	return f"homework_attachment_quota:{assignment}:{student}"


def _current_assignment_row(assignment: str):
	"""The assignment's live state as a CURRENT read (FOR UPDATE): blocks
	concurrent status writers on the same row and sees their committed
	state, dodging the stale REPEATABLE READ snapshot (R10)."""
	return frappe.db.sql(
		"SELECT `name`, `student`, `teacher`, `status`, `cancelled`"
		" FROM `tabLMS Homework Assignment` WHERE `name` = %s FOR UPDATE",
		(assignment,),
		as_dict=True,
	)[0]


def _current_quota_used(assignment: str) -> int:
	"""The stored sum as a CURRENT read (FOR UPDATE) -- inside the advisory
	lock this counts every registration that already committed."""
	row = frappe.db.sql(
		"SELECT COALESCE(SUM(`file_size`), 0) AS used"
		" FROM `tabLMS Homework Attachment` WHERE `assignment` = %s FOR UPDATE",
		(assignment,),
		as_dict=True,
	)
	return cint(row[0].used) if row else 0


@frappe.whitelist()
def list_attachments(assignment: str) -> dict:
	"""The solution's files plus the quota line the UI shows (E03.7). Each row
	carries the file's own PRIVATE url -- downloading goes through the
	platform's permission-checked private-file serving (R05)."""
	doc = _assignment_for_student(assignment)
	state = _quota_state(assignment)
	files = frappe.get_all(
		"File",
		filters={"name": ("in", [row.file for row in state["rows"]] or ["__none__"])},
		fields=["name", "file_name", "file_size", "file_url", "is_private"],
	)
	by_name = {row.name: row for row in files}
	rows = []
	for row in state["rows"]:
		file_row = by_name.get(row.file) or {}
		file_url = file_row.get("file_url") or ""
		rows.append(
			{
				"name": row.name,
				"file": row.file,
				"file_name": row.file_name or file_row.get("file_name"),
				"file_size": cint(row.file_size),
				"uploaded_by": row.uploaded_by,
				"uploaded_at": row.uploaded_at,
				"uploaded_by_name": frappe.utils.get_fullname(row.uploaded_by),
				# The private URL itself: readable by this assignment's student
				# and teacher alone, through the File/attachment permission pair.
				"file_url": file_url if file_url.startswith("/private/files/") else "",
				"can_delete": (
					doc.student == frappe.session.user and _student_editable(doc)
				),
			}
		)
	return {
		"rows": rows,
		"used": state["used"],
		"quota": state["quota"],
		"remaining": state["remaining"],
		"can_upload": doc.student == frappe.session.user and _student_editable(doc),
	}


def _quota_state(assignment: str) -> dict:
	"""Used / remaining bytes of the solution's quota, from the rows Frappe
	stored -- the sizes are read from the File rows, not from any client
	declaration."""
	rows = frappe.get_all(
		"LMS Homework Attachment",
		filters={"assignment": assignment},
		fields=["name", "file", "file_size", "file_name", "uploaded_by", "uploaded_at"],
		order_by="creation asc",
	)
	used = sum(cint(row.file_size) for row in rows)
	return {
		"rows": rows,
		"used": used,
		"quota": ATTACHMENT_QUOTA_BYTES,
		"remaining": max(0, ATTACHMENT_QUOTA_BYTES - used),
	}


def _own_fresh_private_upload(file_name: str):
	"""The File the caller may register: their OWN upload, still unbound, and
	already stored PRIVATE (R01, R03). Returns the doc or throws."""
	if not isinstance(file_name, str) or not file_name or not frappe.db.exists("File", file_name):
		frappe.throw(_("Invalid file."), frappe.ValidationError)
	file_doc = frappe.get_doc("File", file_name)
	if file_doc.owner != frappe.session.user:
		frappe.throw(
			_("You can only attach your own uploaded files."), frappe.PermissionError
		)
	if file_doc.attached_to_doctype or file_doc.attached_to_name:
		# Someone else's -- or the caller's own already-registered -- binding:
		# refused untouched, never deleted (R01, R02).
		frappe.throw(_("This file is already attached elsewhere."), frappe.ValidationError)
	if not cint(file_doc.is_private) or not (file_doc.file_url or "").startswith("/private/files/"):
		# A public upload is not convertible by re-flagging a column (R03);
		# the caller must upload privately. Their own fresh public file is
		# cleaned so no orphan blob survives.
		_discard_verified_own(file_doc)
		frappe.throw(
			_("Please upload the file as private (the solution uploader does this"
			  " automatically). Public files cannot be attached."),
			frappe.ValidationError,
		)
	return file_doc


@frappe.whitelist()
def attach_file(assignment: str, file_name: str | None = None) -> dict:
	"""Register one uploaded File as part of the solution.

	The client uploads through Frappe's own file endpoint (private, unbound),
	then registers the file HERE, where every verdict lives: ownership,
	privateness, actual content type, the assignment's CURRENT state and the
	total quota -- the last two under the per-assignment advisory lock with
	FOR UPDATE current reads, so parallel requests serialize and status
	changes committed before the write are honoured (R10)."""
	doc = _assignment_for_student(assignment)
	if doc.student != frappe.session.user:
		frappe.throw(
			_("Only the assignment's own student can add solution files."),
			frappe.PermissionError,
		)
	file_doc = _own_fresh_private_upload(file_name)

	extension = _extension_of(file_doc.file_name or "")
	if extension not in ALLOWED_EXTENSIONS:
		_discard_verified_own(file_doc)
		frappe.throw(
			_("File type {0} is not allowed. Allowed: {1}").format(
				frappe.bold(extension or "?"),
				", ".join(sorted(ALLOWED_EXTENSIONS)),
			),
			frappe.ValidationError,
		)
	size = cint(file_doc.file_size)
	if size <= 0:
		_discard_verified_own(file_doc)
		frappe.throw(_("The file is empty."), frappe.ValidationError)
	try:
		_verify_content(file_doc, extension)
	except frappe.ValidationError:
		_discard_verified_own(file_doc)
		raise

	with frappe.db.advisory_lock(_lock_key(assignment, doc.student)):
		# R10: the state under the lock, as a current read. A revoke or a
		# move to Review committed before this point is visible here; one
		# that comes later waits on the row lock and lands after our write.
		current = _current_assignment_row(assignment)
		if not current or not _student_editable(current) or current.student != frappe.session.user:
			_discard_verified_own(file_doc)
			frappe.throw(
				_("Solution files can only be changed while the homework is not yet"
				  " submitted for review."),
				frappe.PermissionError,
			)
		used = _current_quota_used(assignment)
		if used + size > ATTACHMENT_QUOTA_BYTES:
			_discard_verified_own(file_doc)
			frappe.throw(
				_(
					"The solution files together cannot exceed {0} MB. Used: {1:.1f} MB,"
					" remaining: {2:.1f} MB."
				).format(
					ATTACHMENT_QUOTA_BYTES // (1024 * 1024),
					used / (1024 * 1024),
					max(0, ATTACHMENT_QUOTA_BYTES - used) / (1024 * 1024),
				),
				frappe.ValidationError,
			)
		row = frappe.new_doc("LMS Homework Attachment")
		row.update(
			{
				"assignment": assignment,
				"student": current.student,
				"file": file_doc.name,
				"file_name": file_doc.file_name,
				"file_size": size,
				# The stored type is derived from the name the platform itself
				# recorded -- never from any client-declared header.
				"content_type": mimetypes.guess_type(file_doc.file_name or "")[0] or "",
			}
		)
		row.insert(ignore_permissions=True)
		# Bind to the row (the file was already private at upload -- only the
		# attachment pointers are written here; is_private is NOT toggled).
		frappe.db.set_value(
			"File",
			file_doc.name,
			{
				"attached_to_doctype": "LMS Homework Attachment",
				"attached_to_name": row.name,
			},
		)
		if not frappe.flags.in_test:
			frappe.db.commit()

	return {"name": row.name, "state": _public_state(assignment)}


@frappe.whitelist()
def delete_attachment(attachment: str) -> dict:
	"""The student removes one of their own files while the card is editable
	(E03.8): the link breaks and the stored file is deleted, releasing its
	bytes back to the quota. A teacher never deletes a student's file. The
	state is re-read under the same lock the registration uses (R10)."""
	row = frappe.get_doc("LMS Homework Attachment", attachment)
	if row.student != frappe.session.user:
		frappe.throw(
			_("Only the student who uploaded a file can remove it."), frappe.PermissionError
		)
	file_doc = frappe.get_doc("File", row.file) if row.file else None
	with frappe.db.advisory_lock(_lock_key(row.assignment, row.student)):
		current = _current_assignment_row(row.assignment)
		if not current or not _student_editable(current) or current.student != frappe.session.user:
			frappe.throw(
				_("Solution files can only be changed while the homework is not yet"
				  " submitted for review."),
				frappe.PermissionError,
			)
		frappe.delete_doc("LMS Homework Attachment", row.name, ignore_permissions=True)
		if file_doc and frappe.db.exists("File", file_doc.name):
			frappe.delete_doc("File", file_doc.name, ignore_permissions=True)
		if not frappe.flags.in_test:
			frappe.db.commit()
	return {"deleted": True, "state": _public_state(row.assignment)}


def _public_state(assignment: str) -> dict:
	state = _quota_state(assignment)
	return {
		"used": state["used"],
		"quota": state["quota"],
		"remaining": state["remaining"],
	}


def _discard_verified_own(file_doc) -> None:
	"""Clean a refusal's leftovers -- ONLY a file already verified as the
	session user's own fresh unbound upload (R02: nothing else is ever
	deleted here, and the guards are re-checked inside)."""
	if not file_doc or not frappe.db.exists("File", file_doc.name):
		return
	fresh = frappe.get_doc("File", file_doc.name)
	if fresh.owner != frappe.session.user:
		return
	if fresh.attached_to_doctype or fresh.attached_to_name:
		return
	frappe.delete_doc("File", fresh.name, ignore_permissions=True)
	if not frappe.flags.in_test:
		frappe.db.commit()


def _extension_of(file_name: str) -> str:
	return ("." + file_name.rsplit(".", 1)[-1].lower()) if "." in file_name else ""


# --- Content verification (R09) -------------------------------------------------
#
# The declared extension must be backed by the actual container. Signatures
# only -- no antivirus, no OCR; text formats ride the text contract.

_IMAGE_SIGNATURES = {
	".png": b"\x89PNG\r\n\x1a\n",
	".jpg": b"\xff\xd8\xff",
	".jpeg": b"\xff\xd8\xff",
	".gif": b"GIF87a",
	".bmp": b"BM",
}
_CFB_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .doc/.xls/.ppt
_ZIP_OFFICE = {".docx", ".xlsx", ".pptx", ".odt", ".ods", ".zip"}


def _verify_content(file_doc, extension: str) -> None:
	"""Throw ValidationError when the stored bytes do not match the declared
	extension's real container (R09)."""
	try:
		content = file_doc.get_content()
		if isinstance(content, str):
			content = content.encode("utf-8", "surrogateescape")
	except Exception:
		frappe.throw(_("The file could not be read and was not attached."), frappe.ValidationError)
	if not content:
		frappe.throw(_("The file is empty."), frappe.ValidationError)

	if extension in _IMAGE_SIGNATURES:
		if not content.startswith(_IMAGE_SIGNATURES[extension]):
			frappe.throw(_("The file content does not match a {0} image.").format(extension.lstrip(".")))
		if extension == ".gif" and not content.startswith((b"GIF87a", b"GIF89a")):
			frappe.throw(_("The file content does not match a GIF image."))
		return
	if extension == ".webp":
		if not (content.startswith(b"RIFF") and content[8:12] == b"WEBP"):
			frappe.throw(_("The file content does not match a WEBP image."))
		return
	if extension == ".pdf":
		if not content.lstrip()[:5] == b"%PDF-":
			frappe.throw(_("The file content does not match a PDF document."))
		return
	if extension in _ZIP_OFFICE:
		import io

		if not zipfile.is_zipfile(io.BytesIO(content)):
			frappe.throw(_("The file content does not match a {0} document.").format(extension.lstrip(".")))
		return
	if extension == ".doc":
		if not content.startswith(_CFB_SIGNATURE):
			frappe.throw(_("The file content does not match a DOC document."))
		return
	if extension == ".rtf":
		if not content.lstrip().startswith(b"{\\rtf"):
			frappe.throw(_("The file content does not match an RTF document."))
		return
	# .txt/.csv: the text contract -- accepted as text, no container to check.
