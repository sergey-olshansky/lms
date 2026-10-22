# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Teacher materials and rich-text details of a homework TEMPLATE (task #35,
E05).

The teacher's own files live on the template as ``LMS Homework Material``
rows; the details field carries sanitized rich text whose embedded images are
managed files too -- every ``/private/files/...`` reference found in the HTML
is bound as a ``Detail Image`` row, so images ride the same permission and
quota rules as attachments (never public, never base64 payloads). An issue
FREEZES the current material set onto the assignment as
``LMS Homework Assignment Material`` rows referencing the SAME File ids (no
blob copies): later template edits never rewrite an issued snapshot, and a
file the teacher removes stays alive while any snapshot still references it.

The budget is 20 MiB per template, materials and detail images together
(E05.8) -- separate from each student's 20 MiB solution quota, which is
unchanged. All trust rules of the hardened solution uploader apply here too
(R01-R03, R09): only the session teacher's own fresh PRIVATE upload, content
signature verified, refused uploads cleaned without touching anyone else's
files.
"""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.utils import cint

from lms.lms.homework_attachments import (
	_discard_verified_own,
	_extension_of,
	_own_fresh_private_upload,
	_verify_content,
)

MATERIAL_QUOTA_BYTES = 20 * 1024 * 1024

_ALLOWED_EXTENSIONS = None  # resolved lazily from the attachments module

# src/href references into managed storage: private files and (legacy) public
_FILE_REF = re.compile(r"""(?:src|href)=["'](/(?:private/)?files/[^"']+)["']""")


def _allowed_extensions():
	global _ALLOWED_EXTENSIONS
	if _ALLOWED_EXTENSIONS is None:
		from lms.lms.homework_attachments import ALLOWED_EXTENSIONS

		_ALLOWED_EXTENSIONS = ALLOWED_EXTENSIONS
	return _ALLOWED_EXTENSIONS


def _template_budget_state(homework: str) -> dict:
	rows = frappe.get_all(
		"LMS Homework Material",
		filters={"parent": homework, "parenttype": "LMS Homework"},
		fields=["name", "role", "file", "file_name", "file_size", "content_type"],
		order_by="creation asc",
	)
	used = sum(cint(row.file_size) for row in rows)
	return {
		"rows": rows,
		"used": used,
		"quota": MATERIAL_QUOTA_BYTES,
		"remaining": max(0, MATERIAL_QUOTA_BYTES - used),
	}


def sanitize_details(details: str | None) -> str:
	"""Rich text is stored SANITIZED (E05.4): scripts, unsafe URLs and active
	insertions never reach the database, whatever the client sent."""
	from lms.lms.html_sanitizer import sanitize_rich_text

	return sanitize_rich_text(details or "") or ""


def sync_detail_images(homework_doc, details_html: str) -> None:
	"""Bind every managed-storage image referenced by the details HTML as a
	``Detail Image`` row of THIS (freshly loaded) template, and drop rows
	whose reference left the HTML (E05.10). Only files owned by the template's
	author are accepted -- a pasted reference to someone else's file neither
	renders for students nor enters the budget. The caller holds the template
	budget lock and passes the doc it just reloaded, so the child list this
	syncs against already contains every parallel writer's committed rows
	(round 8: a stale list made one save REPLACE a peer's rows)."""
	homework_name = homework_doc.name
	referenced_urls = set(_FILE_REF.findall(details_html or ""))
	owner = frappe.db.get_value("LMS Homework", homework_name, "owner")
	by_url = {}
	public_refs = []
	for url in referenced_urls:
		file_name = frappe.db.get_value("File", {"file_url": url}, "name")
		if not file_name:
			continue
		row = frappe.db.get_value("File", file_name, ["owner", "is_private"], as_dict=True)
		if row.owner != owner:
			continue
		if not url.startswith("/private/files/") or not row.is_private:
			# Round 7: a public image stays fetchable by its raw URL to anyone,
			# outside every assignment's grant. Refuse it -- the editor uploads
			# privately; the author re-uploads stray public picks.
			public_refs.append(url)
			continue
		by_url[url] = file_name
	if public_refs:
		frappe.throw(
			_(
				"The description contains publicly stored images. Re-upload them"
				" through the editor so they are private: {0}"
			).format(", ".join(public_refs[:3])),
			frappe.ValidationError,
		)
	if not by_url and not _has_detail_rows(homework_name):
		return

	doc = homework_doc
	current = {row.file: row for row in doc.materials if row.role == "Detail Image"}
	wanted_names = set(by_url.values())
	files = frappe.get_all(
		"File",
		filters={"name": ("in", list(wanted_names))},
		fields=["name", "file_name", "file_size"],
	)
	file_info = {row.name: row for row in files}
	for _url, file_name in by_url.items():
		if file_name in current:
			continue
		info = file_info.get(file_name)
		doc.append(
			"materials",
			{
				"role": "Detail Image",
				"file": file_name,
				"file_name": info.file_name if info else file_name,
				"file_size": cint(info.file_size) if info else 0,
				"content_type": _content_type_of(info.file_name if info else file_name),
			},
		)
	for file_name, row in list(current.items()):
		if file_name not in wanted_names:
			doc.remove(row)
	doc.flags.homework_service = True
	doc.save(ignore_permissions=True)


def _has_detail_rows(homework_name: str) -> bool:
	return bool(
		frappe.db.exists(
			"LMS Homework Material",
			{"parent": homework_name, "parenttype": "LMS Homework", "role": "Detail Image"},
		)
	)


def _content_type_of(file_name: str) -> str:
	import mimetypes

	return mimetypes.guess_type(file_name or "")[0] or ""


def assert_template_budget(homework_name: str, incoming: int = 0) -> None:
	"""E05.8 / round 7: 20 MiB per template, materials and detail images
	together. The sum is a CURRENT read (FOR UPDATE): callers hold the
	template's advisory lock, and a plain snapshot sum could miss another
	save's uncommitted image rows under REPEATABLE READ -- two parallel
	saves would each pass and together exceed the budget."""
	used = frappe.db.sql(
		"SELECT COALESCE(SUM(`file_size`), 0) AS used"
		" FROM `tabLMS Homework Material` WHERE `parent` = %s"
		" AND `parenttype` = 'LMS Homework' FOR UPDATE",
		(homework_name,),
		as_dict=True,
	)[0].used
	if used + incoming > MATERIAL_QUOTA_BYTES:
		frappe.throw(
			_(
				"The teacher materials together cannot exceed {0} MB (images embedded in"
				" the description included). Used: {1:.1f} MB, remaining: {2:.1f} MB."
			).format(
				MATERIAL_QUOTA_BYTES // (1024 * 1024),
				used / (1024 * 1024),
				max(0, MATERIAL_QUOTA_BYTES - used) / (1024 * 1024),
			),
			frappe.ValidationError,
		)


@frappe.whitelist()
def add_material(homework: str, file_name: str | None = None) -> dict:
	"""Register one uploaded File as a teacher material of the template. The
	same hardened trust chain as the student solution uploader: the session
	teacher's own fresh PRIVATE upload, content signature verified, budget
	checked under a template-scoped advisory lock."""
	from lms.lms.homework_api import _require_homework_access

	doc = _require_homework_access(homework)
	if doc.owner != frappe.session.user:
		frappe.throw(
			_("Only the homework's author can add teacher materials."), frappe.PermissionError
		)
	file_doc = _own_fresh_private_upload(file_name)
	extension = _extension_of(file_doc.file_name or "")
	if extension not in _allowed_extensions():
		_discard_verified_own(file_doc)
		frappe.throw(
			_("File type {0} is not allowed.").format(frappe.bold(extension or "?")),
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

	with frappe.db.advisory_lock(f"homework_material_budget:{homework}"):
		assert_template_budget(homework, size)
		row = frappe.new_doc("LMS Homework Material")
		row.update(
			{
				"parent": homework,
				"parenttype": "LMS Homework",
				"parentfield": "materials",
				"role": "Material",
				"file": file_doc.name,
				"file_name": file_doc.file_name,
				"file_size": size,
				"content_type": _content_type_of(file_doc.file_name),
			}
		)
		row.insert(ignore_permissions=True)
		frappe.db.set_value(
			"File",
			file_doc.name,
			{
				"attached_to_doctype": "LMS Homework Material",
				"attached_to_name": row.name,
			},
		)
		if not frappe.flags.in_test:
			frappe.db.commit()
	state = _template_budget_state(homework)
	return {"name": row.name, "used": state["used"], "quota": state["quota"], "remaining": state["remaining"]}


@frappe.whitelist()
def remove_material(material: str) -> dict:
	"""Remove a material row from the template. The FILE survives while any
	issued snapshot (or another row) still references it (E05.6) -- template
	edits never pull bytes out from under an issued work."""
	row = frappe.get_doc("LMS Homework Material", material)
	homework = frappe.get_doc("LMS Homework", row.parent)
	if homework.owner != frappe.session.user and not _privileged():
		frappe.throw(
			_("Only the homework's author can remove teacher materials."), frappe.PermissionError
		)
	file_name = row.file
	# Detach the File's back-reference first: the platform's link integrity
	# would otherwise refuse the row's own deletion.
	if file_name and frappe.db.exists("File", file_name):
		frappe.db.set_value(
			"File",
			file_name,
			{"attached_to_doctype": None, "attached_to_name": None},
		)
	frappe.delete_doc("LMS Homework Material", row.name, ignore_permissions=True)
	still_referenced = frappe.db.exists(
		"LMS Homework Material", {"file": file_name}
	) or frappe.db.exists(
		"LMS Homework Assignment Material", {"file": file_name}
	)
	if file_name and not still_referenced and frappe.db.exists("File", file_name):
		try:
			frappe.delete_doc("File", file_name, ignore_permissions=True)
		except frappe.LinkExistsError:
			# The platform's own link integrity knows a reference we do not
			# (a race): the bytes stay, which is the safe side of E05.6.
			frappe.clear_last_message()
	if not frappe.flags.in_test:
		frappe.db.commit()
	state = _template_budget_state(row.parent)
	return {"deleted": True, "used": state["used"], "quota": state["quota"], "remaining": state["remaining"]}


def freeze_materials(template_doc, assignment_doc) -> None:
	"""E05.5: the issue snapshots the CURRENT material set (materials and
	detail images) onto the assignment, reusing the same File ids."""
	for row in template_doc.materials or []:
		assignment_doc.append(
			"materials",
			{
				"role": row.role,
				"file": row.file,
				"file_name": row.file_name,
				"file_size": row.file_size,
				"content_type": row.content_type,
			},
		)


def _privileged() -> bool:
	from lms.lms.homework_api import _is_privileged

	return _is_privileged()


def material_rows_public(rows: list, *, with_urls: bool = True) -> list[dict]:
	"""One material row for the client: identity, size, role, and the file's
	own PRIVATE url -- downloads go through the permission-checked private
	serving, so the URL is handed out but the bytes still answer to the pair
	of hooks."""
	out = []
	for row in rows:
		out.append(
			{
				"name": row.name,
				"role": row.role,
				"file": row.file,
				"file_name": row.file_name,
				"file_size": cint(row.file_size),
				# The authorized endpoint, not the raw private path: the
				# verdict lives in download_material (E05.7).
				"file_url": material_download_url(row.file) if with_urls else "",
			}
		)
	return out


def _material_download_allowed(file_doc, user: str) -> bool:
	"""The decisive reader list of one teacher-material file (E05.7, served
	through :func:`download_material`): staff, the template's author, and the
	students/teachers of ACTIVE assignments whose frozen snapshot still
	references this file. Assignments in Review/Done keep the reading right;
	a recall ends it."""
	from lms.lms.permissions import has_moderator_role

	if user == "Administrator" or has_moderator_role(user):
		return True
	template_rows = frappe.get_all(
		"LMS Homework Material",
		filters={"file": file_doc.name, "parenttype": "LMS Homework"},
		pluck="parent",
	)
	for template_name in set(template_rows):
		if frappe.db.get_value("LMS Homework", template_name, "owner") == user:
			return True
	assignment_names = set(
		frappe.get_all(
			"LMS Homework Assignment Material",
			filters={"file": file_doc.name, "parenttype": "LMS Homework Assignment"},
			pluck="parent",
		)
	)
	for assignment_name in assignment_names:
		row = frappe.db.get_value(
			"LMS Homework Assignment",
			assignment_name,
			["student", "teacher", "cancelled"],
			as_dict=True,
		)
		if not row or row.cancelled:
			continue
		if user in (row.student, row.teacher):
			return True
	return False


@frappe.whitelist()
def download_material(file: str) -> None:
	"""The authorized download path of one teacher material (E05.7): the
	verdict is computed here, in Python, from the snapshot rows -- the raw
	private URL answers to the platform's own File chain, which cannot express
	"the author OR any issued student" for a template-bound file. Bytes,
	filename and content type come from the stored File; nothing is published
	and no requirement is credited by a download (E05.12)."""
	if not isinstance(file, str) or not file or not frappe.db.exists("File", file):
		frappe.throw(_("Invalid file."), frappe.ValidationError)
	file_doc = frappe.get_doc("File", file)
	if not _material_download_allowed(file_doc, frappe.session.user):
		frappe.throw(
			_("You are not allowed to download this material."), frappe.PermissionError
		)
	frappe.local.response["filename"] = file_doc.file_name or file
	frappe.local.response["filecontent"] = file_doc.get_content()
	frappe.local.response["type"] = "download"


def material_download_url(file_name: str) -> str:
	"""The endpoint URL handed to clients and the PDF alike -- absolute paths
	stay the endpoint's own business (same-origin)."""
	return f"/api/method/lms.lms.homework_materials.download_material?file={file_name}"


def rewrite_detail_urls(details_html: str) -> str:
	"""Point the details' embedded images at the authorized download endpoint
	for readers the raw private URL would refuse (E05.10/E05.7): every
	/private/files/... src of a MANAGED file becomes its endpoint URL. The
	stored HTML keeps the storage URL; only the served copy is rewritten."""
	if not details_html:
		return details_html or ""
	mapping = {}
	for url in set(_FILE_REF.findall(details_html)):
		file_name = frappe.db.get_value("File", {"file_url": url}, "name")
		if file_name:
			mapping[url] = material_download_url(file_name)
	for url, endpoint in mapping.items():
		details_html = details_html.replace(url, endpoint)
	return details_html
