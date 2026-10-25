# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Solution files of one homework assignment (task #35, E03; hardened round 6,
R01-R03, R05, R08-R10; hotfix 2026-10-25 after the first production release).

A student may attach common image, document, PDF, and text formats to THEIR
assignment -- bound to the (assignment, student) pair, never to the shared
template, with a quota of 20 MiB TOTAL across every file of that solution.
Supported extensions are explicitly listed; known containers are checked
against their real signatures, so a renamed mismatch is refused.

Trust rules (round 6, unchanged):
- The client names a File by ID; nothing about that ID is trusted. The file
  must be the session student's OWN upload, still unbound, and stored PRIVATE
  (a public upload is refused and cleaned, never silently re-flagged -- R03:
  flipping ``is_private`` with db.set_value leaves the public URL working).
- The assignment's state is re-read with a CURRENT read (SELECT ... FOR
  UPDATE) INSIDE the advisory lock, and the quota sum is a current read too,
  so a revoke/review committed before the write is seen (R10), and two
  parallel registrations cannot both spend the same remaining bytes under
  MariaDB REPEATABLE READ.
- Downloads ride the file's own private URL: serving goes through
  File.has_permission and the attachment-row hooks, so the student and the
  assignment's teacher download, everyone else gets 403 (R05).

Production incident 2026-10-25: on the released site every upload succeeded
(HTTP 200, the File row stored) yet the browser never issued the follow-up
``attach_file`` registration -- the hand-off depended on the client parsing
the generic ``upload_file`` response. The transport now posts the bytes
straight to ``upload_solution_file`` (single request: private storage,
verification and quota registration commit together, and frappe's
website-user mime allowlist on the generic endpoint stops gating homework
solutions).
"""

from __future__ import annotations

import mimetypes
import os
import zipfile

import frappe
from frappe import _
from frappe.core.doctype.file.utils import get_safe_file_name
from frappe.utils import cint

# E03.3: one number, one meaning -- 20 * 1024 * 1024 bytes, total per solution.
ATTACHMENT_QUOTA_BYTES = 20 * 1024 * 1024

# Homework solutions accept common image, document, and text formats. Unknown
# extensions (especially executable formats) are refused. Known containers
# are also checked against their real signatures (R09).

_ALLOWED_EXTENSIONS = {
	# Images
	".bmp", ".gif", ".heic", ".heif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp",
	# Documents and spreadsheets / presentations
	".doc", ".docx", ".odt", ".ods", ".odp", ".pdf", ".ppt", ".pptx", ".rtf",
	".xls", ".xlsx", ".zip",
	# Common plain-text exports
	".csv", ".md", ".txt",
}

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
				# Forced-download disposition ("a download is never less safe
				# than inline") -- what the UI links to, since attachments
				# can be a solution now.
				"download_url": (
					file_url + "?download=1"
					if file_url.startswith("/private/files/")
					else ""
				),
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


def _resolve_upload(ref: str):
	"""Locate the File the caller named -- by document name, or by the
	platform's own PRIVATE file url -- then hand it to the ownership /
	freshness / privateness verdict (R01-R03)."""
	if isinstance(ref, str) and ref and not frappe.db.exists("File", ref):
		if ref.startswith("/private/files/"):
			found = frappe.db.get_value("File", {"file_url": ref}, "name")
			if found:
				ref = found
	return _own_fresh_private_upload(ref)


def _assert_registration_allowed(assignment: str, student: str, extra_size: int) -> None:
	"""Inside the advisory lock: the CURRENT editable state (R10) and the
	CURRENT quota sum -- one verdict shared by every registration entry
	point."""
	current = _current_assignment_row(assignment)
	if not current or not _student_editable(current) or current.student != student:
		frappe.throw(
			_("Solution files can only be changed while the homework is not yet"
			  " submitted for review."),
			frappe.PermissionError,
		)
	used = _current_quota_used(assignment)
	if used + extra_size > ATTACHMENT_QUOTA_BYTES:
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


def _insert_attachment_row(assignment: str, student: str, file_doc, size: int):
	"""The solution row plus the File's private binding (the file is already
	private at upload -- only the attachment pointers are written here;
	is_private is NOT toggled)."""
	row = frappe.new_doc("LMS Homework Attachment")
	row.update(
		{
			"assignment": assignment,
			"student": student,
			"file": file_doc.name,
			"file_name": file_doc.file_name,
			"file_size": size,
			# The stored type is derived from the name the platform itself
			# recorded -- never from any client-declared header.
			"content_type": mimetypes.guess_type(file_doc.file_name or "")[0]
			or "application/octet-stream",
		}
	)
	row.insert(ignore_permissions=True)
	frappe.db.set_value(
		"File",
		file_doc.name,
		{
			"attached_to_doctype": "LMS Homework Attachment",
			"attached_to_name": row.name,
		},
	)
	return row


def _register_with_upload(assignment: str, file_doc) -> dict:
	"""Register an EXISTING verified-own upload: the locked verdict, then the
	row and the private binding. A refusal cleans only that upload (R02) --
	and ONLY a verdict refusal: a transient DB error (deadlock) propagates
	untouched so the caller's retry finds the upload alive."""
	size = cint(file_doc.file_size)
	with frappe.db.advisory_lock(_lock_key(assignment, file_doc.owner)):
		try:
			_assert_registration_allowed(assignment, file_doc.owner, size)
		except (frappe.PermissionError, frappe.ValidationError):
			_discard_verified_own(file_doc)
			raise
		row = _insert_attachment_row(assignment, file_doc.owner, file_doc, size)
		if not frappe.flags.in_test:
			frappe.db.commit()
	return {"name": row.name, "state": _public_state(assignment)}


@frappe.whitelist()
def attach_file(assignment: str, file_name: str | None = None) -> dict:
	"""Register one uploaded File as part of the solution.

	The classic two-step contract (upload through the platform's own file
	endpoint, then register by File id or private url) -- kept for callers
	and tests; the UI now posts straight to upload_solution_file. Supported
	image/document types are accepted; a KNOWN container must
	still match its declared extension (R09)."""
	doc = _assignment_for_student(assignment)
	if doc.student != frappe.session.user:
		frappe.throw(
			_("Only the assignment's own student can add solution files."),
			frappe.PermissionError,
		)
	file_doc = _resolve_upload(file_name or "")

	size = cint(file_doc.file_size)
	if size <= 0:
		_discard_verified_own(file_doc)
		frappe.throw(_("The file is empty."), frappe.ValidationError)
	try:
		_verify_content(file_doc, _extension_of(file_doc.file_name or ""))
	except frappe.ValidationError:
		_discard_verified_own(file_doc)
		raise

	return _register_with_upload(assignment, file_doc)


@frappe.whitelist()
def upload_solution_file(
	assignment: str | None = None,
	doctype: str | None = None,
	docname: str | None = None,
) -> dict:
	"""Single-request solution upload: the multipart ``file`` is posted
	straight here and registered in ONE transaction.

	Why (production incident 2026-10-25): the released UI uploaded through
	frappe's generic ``upload_file`` and then registered the returned File id
	from the browser -- every upload succeeded, yet the registration request
	never fired, so nothing attached. Posting the bytes here removes the
	client-side hand-off entirely; it also lifts the generic endpoint's
	website-user mime allowlist (which may reject otherwise supported formats) and
	leaves no orphan upload behind a refused registration."""
	if not assignment and doctype == "LMS Homework Assignment" and docname:
		# The uploader's own doctype/docname form fields carry the target.
		assignment = docname
	doc = _assignment_for_student(assignment or "")
	if doc.student != frappe.session.user:
		frappe.throw(
			_("Only the assignment's own student can add solution files."),
			frappe.PermissionError,
		)
	upload = (getattr(frappe.request, "files", None) or {}).get("file")
	if upload is None:
		frappe.throw(_("No file received."), frappe.ValidationError)
	content = upload.stream.read()
	file_name = get_safe_file_name(os.path.basename(upload.filename or "")) or "file"
	size = len(content)
	if size <= 0:
		frappe.throw(_("The file is empty."), frappe.ValidationError)
	if size > ATTACHMENT_QUOTA_BYTES:
		frappe.throw(
			_("The file alone exceeds the {0} MB solution quota.").format(
				ATTACHMENT_QUOTA_BYTES // (1024 * 1024)
			),
			frappe.ValidationError,
		)
	_verify_bytes(_extension_of(file_name), content)

	with frappe.db.advisory_lock(_lock_key(assignment, doc.student)):
		_assert_registration_allowed(assignment, doc.student, size)
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
			# Defensive: the platform must keep its own promise about private
			# storage before the solution row points at it.
			frappe.throw(
				_("The file could not be stored privately."), frappe.ValidationError
			)
		row = _insert_attachment_row(assignment, doc.student, file_doc, size)
		if not frappe.flags.in_test:
			frappe.db.commit()

	return {
		"name": row.name,
		"file": file_doc.name,
		"file_name": file_doc.file_name,
		"state": _public_state(assignment),
	}


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
	_verify_bytes(extension, content)


def _verify_bytes(extension: str, content: bytes) -> None:
	"""Validate the supported format and known containers on raw bytes."""
	if not content:
		frappe.throw(_("The file is empty."), frappe.ValidationError)
	if extension not in _ALLOWED_EXTENSIONS:
		frappe.throw(
			_("This file type is not supported. Attach an image, document, PDF, or text file."),
			frappe.ValidationError,
		)

	if extension == ".gif":
		if not content.startswith((b"GIF87a", b"GIF89a")):
			frappe.throw(_("The file content does not match a GIF image."))
		return
	if extension in _IMAGE_SIGNATURES:
		if not content.startswith(_IMAGE_SIGNATURES[extension]):
			frappe.throw(_("The file content does not match a {0} image.").format(extension.lstrip(".")))
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
