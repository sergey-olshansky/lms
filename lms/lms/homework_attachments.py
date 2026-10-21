# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Solution files of one homework assignment (task #35, E03).

A student may attach images, PDFs, DOCX and the project's other accepted
formats to THEIR assignment -- bound to the (assignment, student) pair, never
to the shared template -- with a quota of 20 MiB TOTAL across every file of
that solution, not per file. The quota is enforced server-side against the
ACTUAL stored sizes plus the incoming upload, under a per-assignment advisory
lock so two parallel uploads cannot each spend the same remaining space.

Everything rides on Frappe's own File storage: uploads go through the
platform's upload endpoint conventions (the client uses ``upload_files``
below, wrapping frappe's handler), files are created private, and downloads
are served through the app's permission-checked private-file route -- the
``is_private`` flag alone is never treated as the access check, which is why
``serve_attachment`` re-resolves the row's assignment and judges the viewer.
"""

from __future__ import annotations

import mimetypes

import frappe
from frappe import _
from frappe.utils import cint

# E03.3: one number, one meaning -- 20 * 1024 * 1024 bytes, total per solution.
ATTACHMENT_QUOTA_BYTES = 20 * 1024 * 1024

# The accepted extension allowlist. Anything active (HTML/svg-with-script,
# executables) is refused regardless of the client's declared type; the
# server re-derives the extension from the stored file name, and the size is
# read from the File row Frappe itself recorded.
ALLOWED_EXTENSIONS = {
	".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
	".pdf",
	".doc", ".docx", ".odt", ".rtf", ".txt", ".csv",
	".xls", ".xlsx", ".ods", ".ppt", ".pptx",
	".zip",
}


def _assignment_for_student(name: str):
	"""The assignment the session student owns, refused otherwise."""
	doc = frappe.get_doc("LMS Homework Assignment", name)
	if doc.student != frappe.session.user and not _teacher_of(doc):
		frappe.throw(_("You cannot work with this homework."), frappe.PermissionError)
	return doc


def _teacher_of(doc) -> bool:
	from lms.lms.homework_api import _is_privileged

	return doc.teacher == frappe.session.user or _is_privileged()


def _student_editable(doc) -> bool:
	"""E03.5: the student adds/removes their files only while the work is
	theirs to edit -- To Do / In Progress (including a returned card). Review,
	Done and a recalled assignment are read-only, and the state is RE-READ on
	every write, never trusted from the client."""
	if doc.cancelled:
		return False
	return doc.status in ("To Do", "In Progress")


def _quota_state(assignment: str) -> dict:
	"""Used / remaining bytes of the solution's quota, from the files Frappe
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


def _lock_key(assignment: str, student: str) -> str:
	return f"homework_attachment_quota:{assignment}:{student}"


@frappe.whitelist()
def list_attachments(assignment: str) -> dict:
	"""The solution's files plus the quota line the UI shows (E03.7)."""
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
		rows.append(
			{
				"name": row.name,
				"file": row.file,
				"file_name": row.file_name or file_row.get("file_name"),
				"file_size": cint(row.file_size),
				"uploaded_by": row.uploaded_by,
				"uploaded_at": row.uploaded_at,
				"uploaded_by_name": frappe.utils.get_fullname(row.uploaded_by),
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


@frappe.whitelist()
def attach_file(assignment: str, file_name: str | None = None) -> dict:
	"""Register one uploaded File as part of the solution.

	The client uploads through Frappe's own file endpoint with
	``doctype=LMS Homework Assignment`` wiring already pointing the File at
	this card, then registers the file HERE, where the quota verdict lives:
	the sum of the stored files' sizes plus the new one must fit the 20 MiB
	total. Parallel registrations serialise on the per-assignment lock, so two
	uploads racing for the same remaining space cannot both win -- the second
	one is refused and its File unlinked, leaving no orphan behind."""
	doc = _assignment_for_student(assignment)
	if doc.student != frappe.session.user:
		frappe.throw(
			_("Only the assignment's own student can add solution files."),
			frappe.PermissionError,
		)
	if not file_name or not frappe.db.exists("File", file_name):
		frappe.throw(_("Invalid file."), frappe.ValidationError)
	if not _student_editable(doc):
		# The upload may already have landed (the client uploads, then
		# registers): a refused registration must not leave it behind (E03.7).
		_discard(file_name)
		frappe.throw(
			_("Solution files can only be changed while the homework is not yet"
			  " submitted for review."),
			frappe.PermissionError,
		)

	file_doc = frappe.get_doc("File", file_name)
	if file_doc.attached_to_doctype or file_doc.attached_to_name:
		# The uploader sends the file with no attachment wiring at all (a
		# student holds no doctype write to pre-bind it); anything already
		# bound is not a fresh solution upload.
		frappe.throw(_("This file is already attached elsewhere."), frappe.ValidationError)

	extension = _extension_of(file_doc.file_name or "")
	if extension not in ALLOWED_EXTENSIONS:
		_discard(file_name)
		frappe.throw(
			_("File type {0} is not allowed. Allowed: {1}").format(
				frappe.bold(extension or "?"),
				", ".join(sorted(ALLOWED_EXTENSIONS)),
			),
			frappe.ValidationError,
		)

	size = cint(file_doc.file_size)
	if size <= 0:
		_discard(file_name)
		frappe.throw(_("The file is empty."), frappe.ValidationError)

	with frappe.db.advisory_lock(_lock_key(assignment, doc.student)):
		state = _quota_state(assignment)
		if state["used"] + size > ATTACHMENT_QUOTA_BYTES:
			_discard(file_name)
			frappe.throw(
				_(
					"The solution files together cannot exceed {0} MB. Used: {1:.1f} MB,"
					" remaining: {2:.1f} MB."
				).format(
					ATTACHMENT_QUOTA_BYTES // (1024 * 1024),
					state["used"] / (1024 * 1024),
					state["remaining"] / (1024 * 1024),
				),
				frappe.ValidationError,
			)
		row = frappe.new_doc("LMS Homework Attachment")
		row.update(
			{
				"assignment": assignment,
				"student": doc.student,
				"file": file_name,
				"file_name": file_doc.file_name,
				"file_size": size,
				# The stored type is derived from the name the platform itself
				# recorded -- never from any client-declared header.
				"content_type": mimetypes.guess_type(file_doc.file_name or "")[0] or "",
			}
		)
		row.insert(ignore_permissions=True)
		# Private, and bound to the row: the File's own permission check now
		# answers through the attachment row's assignment, exactly like the
		# quiz submission's answer files.
		frappe.db.set_value(
			"File",
			file_name,
			{
				"is_private": 1,
				"attached_to_doctype": "LMS Homework Attachment",
				"attached_to_name": row.name,
			},
		)
		# The commit lands INSIDE the lock: the next registration must see this
		# row's bytes even under REPEATABLE READ, or two parallel uploads could
		# each spend the same remaining quota. Tests skip it so their rollback
		# still cleans everything up.
		if not frappe.flags.in_test:
			frappe.db.commit()

	return {"name": row.name, "state": _public_state(assignment)}


@frappe.whitelist()
def delete_attachment(attachment: str) -> dict:
	"""The student removes one of their own files while the card is editable
	(E03.8): the link breaks and the stored file is deleted, releasing its
	bytes back to the quota. A teacher never deletes a student's file."""
	row = frappe.get_doc("LMS Homework Attachment", attachment)
	doc = frappe.get_doc("LMS Homework Assignment", row.assignment)
	if row.student != frappe.session.user:
		frappe.throw(
			_("Only the student who uploaded a file can remove it."), frappe.PermissionError
		)
	if not _student_editable(doc):
		frappe.throw(
			_("Solution files can only be changed while the homework is not yet"
			  " submitted for review."),
			frappe.PermissionError,
		)
	file_name = row.file
	frappe.delete_doc("LMS Homework Attachment", row.name, ignore_permissions=True)
	if file_name and frappe.db.exists("File", file_name):
		frappe.delete_doc("File", file_name, ignore_permissions=True)
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


def _discard(file_name: str) -> None:
	"""Refused uploads leave nothing behind (E03.7): no orphaned file keeps
	quota space or a guessable URL."""
	if file_name and frappe.db.exists("File", file_name):
		frappe.delete_doc("File", file_name, ignore_permissions=True)
	if not frappe.flags.in_test:
		frappe.db.commit()


def _extension_of(file_name: str) -> str:
	return ("." + file_name.rsplit(".", 1)[-1].lower()) if "." in file_name else ""
