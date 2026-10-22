# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""The homework PDF (task #35, E02).

Two documents share one generator: a template's composition (title, details,
the ordered material list with full paths) and one assignment's frozen snapshot
(plus the student, the dates and the deadline with its timezone). Every
material row is a REAL link annotation carrying an absolute working URL built
from the site's own configuration -- never a blue underline, never a relative
href, never a hard-coded host. Links follow the lesson's CURRENT placement
(D07), so a material moved between courses keeps a working link; a deleted one
is labelled unavailable and links nowhere (never onto a neighbour that merely
inherited its ordinal). Nothing here renders answers, instructor content or
any key: the generator reads only the snapshot's identity fields.

Rendering goes through the platform's own ``frappe.utils.pdf.get_pdf`` over an
HTML document -- the same pipe the attempt report already uses -- because a
wkhtmltopdf-run page turns ``<a href>`` into genuine PDF link annotations for
free, Cyrillic and long-line wrapping included.
"""

from __future__ import annotations

import base64
import html
import mimetypes
import re

import frappe
from frappe import _
from frappe.utils import cint, format_datetime

from lms.lms import homework_api, homework_materials
from lms.lms.utils import get_lms_route

TYPE_LABELS = {
	"Open Lesson": _("Lesson"),
	"Pass Quiz": _("Quiz"),
	"Open Assignment": _("Written assignment"),
	"Reference": _("Material"),
}


def _site_url(path: str) -> str:
	"""One absolute URL from the site's own host configuration (E02.3)."""
	base = frappe.utils.get_url()
	if not base:
		return path
	return f"{base.rstrip('/')}{path}"


def _requirement_link(row: dict) -> tuple[str, bool]:
	"""(absolute URL, alive) for one checklist row, following the CURRENT
	placement the detail DTO already resolved (D07)."""
	route = row.get("route")
	if not route:
		return "", False
	if route.get("type") == "lesson" and route.get("course") and route.get("number"):
		# "2-1-3" -> chapter path "2-1", lesson "3", the SPA's own URL shape
		# (/lms/courses/<course>/learn/<chapter>-<lesson>).
		segments = str(route["number"]).split("-")
		lesson_number = segments.pop() or "1"
		chapter_number = "-".join(segments) or "1"
		path = get_lms_route(
			f"courses/{route['course']}/learn/{chapter_number}-{lesson_number}"
		)
		return _site_url(path), True
	if route.get("type") == "quiz" and route.get("quiz"):
		return _site_url(get_lms_route(f"quiz/{route['quiz']}")), True
	if route.get("type") == "assignment" and route.get("assignment"):
		return _site_url(
			get_lms_route(f"assignment-submission/{route['assignment']}/new")
		), True
	return "", False


def _material_lines(rows: list[dict]) -> list[str]:
	"""The ordered material list as HTML rows: number, type, label, full path,
	and a REAL link (or the explicit unavailable marker)."""
	parts = []
	for index, row in enumerate(rows, start=1):
		type_label = TYPE_LABELS.get(row.get("requirement_type"), _("Material"))
		label = html.escape(str(row.get("label") or ""))
		path = html.escape(str(row.get("path") or ""))
		url, alive = _requirement_link(row)
		if alive and url:
			link = f'<a class="mat" href="{html.escape(url, quote=True)}">{label}</a>'
		else:
			link = f'<span class="mat dead">{label}</span>'
		parts.append(
			f'<li><span class="num">{index}.</span> <span class="tag">{html.escape(type_label)}</span> '
			f"{link}"
			f'<br><span class="path">{path}</span>'
			+ (
				f'<br><span class="dead-note">{_("This material is no longer available")}</span>'
				if not alive
				else ""
			)
			+ "</li>"
		)
	return parts


def _zone_label(iso: str | None) -> str:
	if not iso:
		return ""
	# "+03:00" tail of the offset-bearing ISO the service attaches.
	tail = iso[-6:] if len(iso) >= 6 and iso[-6] in ("+", "-") else ""
	return f" UTC{tail}" if tail else ""


def render_homework_pdf_html(payload: dict) -> str:
	"""The shared body: header block, optional assignment facts, materials,
	details. ``payload`` is either the template shape from ``_template_payload``
	or the assignment shape from ``_assignment_payload``."""
	is_assignment = bool(payload.get("assignment_name"))
	heading = html.escape(str(payload.get("title") or ""))
	subtitle = (
		_("Assigned homework") if is_assignment else _("Homework template (not assigned)")
	)

	meta: list[str] = []
	if is_assignment:
		meta.append(f"{_('Student')}: {html.escape(str(payload.get('student_name') or ''))}")
		meta.append(
			f"{_('Assigned on')}: {html.escape(format_datetime(payload.get('assigned_at'), 'dd.MM.yyyy HH:mm'))}"
		)
		due_iso = payload.get("due_at_iso") or ""
		due_clock = due_iso[:16].replace("T", " ") if due_iso else ""
		meta.append(
			f"{_('Due')}: {html.escape(due_clock + _zone_label(due_iso))}"
		)
		meta.append(f"{_('Status')}: {html.escape(str(payload.get('status') or ''))}")
	else:
		meta.append(f"{_('Duration')}: {cint(payload.get('days') or 0)} {_('days')}")

	materials = "".join(_material_lines(payload.get("requirements") or []))
	details_html = _details_block(
		payload.get("details"), payload.get("detail_materials") or []
	)
	teacher_materials = _teacher_material_lines(payload.get("teacher_materials") or [])
	assignment_link = ""
	if is_assignment and payload.get("assignment_name"):
		url = _site_url(
			get_lms_route(f"homework/assignment/{payload['assignment_name']}")
		)
		assignment_link = (
			f'<p class="selflink">{_("Open this homework")}: '
			f'<a href="{html.escape(url, quote=True)}">{html.escape(url)}</a></p>'
		)

	return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
	body {{ font-family: sans-serif; font-size: 12px; color: #202124; margin: 24px; }}
	h1 {{ font-size: 18px; margin: 0 0 4px; }}
	.kind {{ color: #5f6368; font-size: 11px; margin-bottom: 12px; }}
	.meta {{ color: #3c4043; font-size: 12px; margin-bottom: 18px; }}
	.meta span {{ margin-right: 14px; }}
	h2 {{ font-size: 13px; margin: 16px 0 6px; }}
	ol.materials {{ padding-left: 0; list-style: none; }}
	ol.materials li {{ border: 1px solid #dadce0; border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; page-break-inside: avoid; }}
	ul.teacher {{ padding-left: 0; list-style: none; }}
	ul.teacher li {{ border: 1px solid #dadce0; border-radius: 6px; padding: 6px 10px; margin-bottom: 6px; }}
	.num {{ color: #5f6368; }}
	.tag {{ display: inline-block; background: #f1f3f4; border-radius: 8px; font-size: 10px; padding: 1px 8px; margin: 0 6px; color: #3c4043; }}
	a.mat {{ color: #1a73e8; text-decoration: underline; font-size: 12px; }}
	.dead {{ color: #5f6368; }}
	.dead-note {{ color: #d93025; font-size: 11px; }}
	.path {{ color: #5f6368; font-size: 11px; }}
	.details {{ font-family: sans-serif; white-space: pre-wrap; word-break: break-word; border: 1px solid #dadce0; border-radius: 6px; padding: 10px; }}
	.details-rich {{ border: 1px solid #dadce0; border-radius: 6px; padding: 10px; }}
	.details-rich img {{ max-width: 100%; }}
	.details-rich p {{ margin: 0 0 8px; }}
	.selflink {{ margin-top: 18px; }}
</style></head>
<body>
<h1>{heading}</h1>
<div class="kind">{html.escape(str(subtitle))}</div>
<div class="meta">{''.join(f'<span>{part}</span>' for part in meta)}</div>
<h2>{_('Materials')}</h2>
<ol class="materials">{''.join(materials) or f'<li>{_("No materials")}</li>'}</ol>
{teacher_materials}
{details_html}
{assignment_link}
</body></html>"""


def _details_block(details, detail_materials=()) -> str:
	"""E05/E07: rich details render as the sanitized HTML they are (images
	absolute, so wkhtmltopdf fetches them); a legacy plain-text description
	keeps the pre-wrap block -- never raw tags, never double-escaped."""
	from lms.lms.html_sanitizer import sanitize_rich_text

	text = str(details or "").strip()
	if not text:
		return ""
	if "<" in text:
		rendered = sanitize_rich_text(text)
		rendered = _inline_private_detail_images(rendered, detail_materials)
		rendered = _absolute_asset_urls(rendered)
		return f"<h2>{_('Details')}</h2><div class='details-rich'>{rendered}</div>"
	return f"<h2>{_('Details')}</h2><pre class='details'>{html.escape(text)}</pre>"


def _inline_private_detail_images(rendered: str, detail_materials) -> str:
	"""Embed only private images already included in this authorized template
	or assignment snapshot. The isolated PDF browser has no user's session
	cookies, so protected image URLs would otherwise render as broken links."""
	for row in detail_materials:
		role = row.get("role") if isinstance(row, dict) else getattr(row, "role", None)
		if role != "Detail Image":
			continue
		file_name = row.get("file") if isinstance(row, dict) else getattr(row, "file", None)
		if not file_name or not frappe.db.exists("File", file_name):
			continue
		file_doc = frappe.get_doc("File", file_name)
		file_url = file_doc.file_url or ""
		if not file_doc.is_private or not file_url or file_url not in rendered:
			continue
		file_name_label = file_doc.file_name or file_url
		content_type = mimetypes.guess_type(file_name_label)[0] or ""
		if not content_type.startswith("image/"):
			continue
		content = file_doc.get_content()
		if isinstance(content, str):
			content = content.encode("utf-8")
		data_uri = f"data:{content_type};base64,{base64.b64encode(content).decode('ascii')}"
		rendered = rendered.replace(file_url, data_uri)
	return rendered


def _absolute_asset_urls(rendered: str) -> str:
	"""Root-relative image/storage URLs become absolute: the PDF renderer has
	no page origin to inherit them from (same stance as the attempt report)."""
	site = frappe.utils.get_url()
	if not site:
		return rendered
	return _RELATIVE_SRC.sub(lambda m: f'{m.group(1)}="{site}{m.group(2)}"', rendered)


_RELATIVE_SRC = re.compile(r"""(src|href)=["'](?!https?://|data:|#)(/[^"']+)["']""")


def _teacher_material_lines(rows: list[dict]) -> str:
	"""E07.2: the teacher's own materials (or the assignment's frozen snapshot
	of them) as REAL download links -- absolute, permission-checked on click."""
	visible = [row for row in rows if row.get("role") == "Material" and row.get("file_url")]
	if not visible:
		return ""
	parts = [f"<h2>{_('Teacher materials')}</h2><ul class='teacher'>"]
	for row in visible:
		url = _site_url(row["file_url"])
		label = html.escape(str(row.get("file_name") or row.get("file") or ""))
		size_kb = cint(row.get("file_size")) / 1024
		parts.append(
			f'<li><a class="mat" href="{html.escape(url, quote=True)}">{label}</a> '
			f'<span class="path">{size_kb:.0f} KB</span></li>'
		)
	parts.append("</ul>")
	return "".join(parts)


def _template_payload(doc) -> dict:
	"""The template's own composition, expanded exactly the way an issue would
	freeze it (embedded quizzes and assignments included), from the teacher's
	session (the door below already checked ownership)."""
	from lms.lms.homework_sources import expand_requirements

	requirements = []
	for row in expand_requirements(doc.items):
		row = dict(row)
		row["status"] = "Pending"
		requirements.append(row)
	# The picker-like routes: current placement per material.
	routes = homework_api._lesson_route_lookup(
		{row["lesson"] for row in requirements if row.get("lesson")}
	)
	for row in requirements:
		placement = routes.get(row.get("lesson")) if row.get("lesson") else None
		if placement:
			row["route"] = {
				"type": "lesson",
				"course": placement["course"],
				"number": placement["number"],
			}
		elif row.get("quiz"):
			row["route"] = {"type": "quiz", "quiz": row["quiz"], "course": row.get("course")}
		elif row.get("reference_assignment"):
			row["route"] = {
				"type": "assignment",
				"assignment": row["reference_assignment"],
				"course": row.get("course"),
			}
	return {
		"title": doc.title,
		"days": doc.days,
		"details": doc.details,
		"detail_materials": [row for row in (doc.materials or []) if row.role == "Detail Image"],
		"requirements": requirements,
		"teacher_materials": homework_materials.material_rows_public(doc.materials or []),
	}


def _assignment_payload(doc) -> dict:
	"""The frozen snapshot of one issued assignment, read through the same
	detail DTO the page uses (D07 routes and liveness included)."""
	payload = homework_api.get_homework_assignment(doc.name)
	return {
		"title": payload["title"],
		# Use the stored source URLs here so the PDF can inline only the detail
		# images present in this assignment's frozen material snapshot.
		"details": doc.details,
		"detail_materials": [row for row in (doc.materials or []) if row.role == "Detail Image"],
		"assignment_name": payload["name"],
		"student_name": payload["student_name"],
		"assigned_at": payload["assigned_at"],
		"due_at_iso": payload["due_at_iso"],
		"status": payload["status"],
		"requirements": payload["requirements"],
		"teacher_materials": payload.get("materials") or [],
	}


def _homework_pdf_bytes(payload: dict) -> bytes:
	from frappe.utils.pdf import get_pdf

	return get_pdf(render_homework_pdf_html(payload))


def _download_response(filename_stem: str, pdf: bytes) -> None:
	frappe.local.response["filename"] = f"{filename_stem}.pdf"
	frappe.local.response["filecontent"] = pdf
	frappe.local.response["type"] = "download"


@frappe.whitelist()
def download_homework_template_pdf(name: str) -> None:
	"""The teacher's PDF of a saved compilation (E02.1). The library's own door
	(`_require_homework_access`: owner or privileged staff) decides who may
	export it; a foreign teacher or a student is refused."""
	doc = homework_api._require_homework_access(name)
	_download_response(
		f"homework-{doc.name}", _homework_pdf_bytes(_template_payload(doc))
	)


@frappe.whitelist()
def download_homework_assignment_pdf(name: str) -> None:
	"""The PDF of one issued assignment: teacher or privileged staff of THAT
	assignment (the detail read's own authority, E02.7)."""
	doc = frappe.get_doc("LMS Homework Assignment", name)
	if doc.teacher != frappe.session.user and not homework_api._is_privileged():
		frappe.throw(_("You cannot view this homework."), frappe.PermissionError)
	_download_response(
		f"homework-{doc.name}", _homework_pdf_bytes(_assignment_payload(doc))
	)
