"""Import validated Chemedge PDF trainers into native LMS quiz documents."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import frappe
import pdfplumber
from frappe import _
from frappe.utils.html_utils import sanitize_html

from lms.lms.pdf_task_bundle_extractor import FormatError, build_bundle, validate_format
from lms.lms.utils import has_course_instructor_role, has_moderator_role


SOURCE_PDF_FIELD = "chemedge_source_pdf"
TASK_IMAGE_FIELD = "chemedge_task_image"


def _is_system_manager(member: str | None = None) -> bool:
	return bool(
		frappe.db.exists("Has Role", {"parent": member or frappe.session.user, "role": "System Manager"})
	)


def _require_import_permission():
	if frappe.session.user == "Guest" or not (
		_is_system_manager() or has_moderator_role() or has_course_instructor_role()
	):
		frappe.throw(_("You are not permitted to import PDF trainers."), frappe.PermissionError)


def _uploaded_pdf(file_name: str):
	if not isinstance(file_name, str) or not file_name:
		frappe.throw(_("Please upload a PDF file."), frappe.ValidationError)

	file_doc = frappe.get_doc("File", file_name)
	if file_doc.owner != frappe.session.user and not (
		_is_system_manager() or has_moderator_role()
	):
		frappe.throw(_("You are not permitted to use this file."), frappe.PermissionError)
	if Path(file_doc.file_name or "").suffix.lower() != ".pdf":
		frappe.throw(_("The uploaded file must be a PDF."), frappe.ValidationError)
	return file_doc


def _store_task_image(image_path: Path, quiz_name: str, task_number: int):
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"chemedge-task-{task_number:04d}.png",
			"content": image_path.read_bytes(),
			"decode": False,
			"is_private": True,
			"attached_to_doctype": "LMS Quiz",
			"attached_to_name": quiz_name,
			"attached_to_field": TASK_IMAGE_FIELD,
		}
	)
	file_doc.insert(ignore_permissions=True)
	return file_doc


def _question_html(task: dict, image_url: str) -> str:
	number = int(task["number"])
	task_id = frappe.utils.escape_html(str(task["id"]))
	return sanitize_html(
		f"<p>Task {number} · FIPI ID {task_id}</p><p><img src=\"{image_url}\" alt=\"Task {number}\"></p>",
		always_sanitize=True,
	)


def _source_folder_label(source_folder: str | None) -> str:
	"""Return a normalized relative folder label supplied by the browser."""
	if not isinstance(source_folder, str):
		return ""

	# The browser sends a relative folder path. Keep only ordinary path parts so
	# it cannot introduce traversal-looking labels into a quiz title.
	folder_parts = [
		part.strip()
		for part in source_folder.split("/")
		if part.strip() not in {"", ".", ".."}
	]
	return " / ".join(folder_parts)


def _quiz_title(meta: dict, source_folder: str | None) -> str:
	"""Prefix the PDF's quiz title with its selected directory path."""
	header = str(meta["header"]).strip()
	folder = _source_folder_label(source_folder)
	return f"{folder} · {header}" if folder else header


def _unique_quiz_title(title: str) -> str:
	"""Return a readable, non-conflicting Data-field title (140 chars max)."""
	base_title = (title or _("Imported Quiz")).strip()[:140]
	candidate = base_title
	sequence = 2
	while frappe.db.exists("LMS Quiz", {"title": candidate}):
		suffix = f" ({sequence})"
		candidate = f"{base_title[: 140 - len(suffix)]}{suffix}"
		sequence += 1
	return candidate


def _create_quiz(meta: dict, source_folder: str | None = None):
	quiz = frappe.get_doc(
		{
			"doctype": "LMS Quiz",
			"title": _unique_quiz_title(_quiz_title(meta, source_folder)),
			"passing_percentage": 85,
			"max_attempts": 2,
			"show_answers": 0,
			"show_submission_history": 1,
			"duration": None,
			"enable_negative_marking": 0,
		}
	)
	quiz.insert(ignore_permissions=True)
	return quiz


def _attach_source_pdf(source_file, quiz_name: str):
	source_file.db_set(
		{
			"attached_to_doctype": "LMS Quiz",
			"attached_to_name": quiz_name,
			"attached_to_field": SOURCE_PDF_FIELD,
		},
		update_modified=False,
	)


def _existing_import(source_file, source_folder: str | None):
	"""Find a prior import of the same filename from the same selected folder."""
	folder = _source_folder_label(source_folder)
	for quiz_name in frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "LMS Quiz",
			"attached_to_field": SOURCE_PDF_FIELD,
			"file_name": source_file.file_name,
		},
		pluck="attached_to_name",
	):
		quiz = frappe.db.get_value("LMS Quiz", quiz_name, ["name", "title", "total_marks"], as_dict=True)
		if not quiz:
			continue
		if not folder or str(quiz.title).startswith(f"{folder} · "):
			return quiz
	return None


def _delete_files(file_names: list[str]):
	for name in file_names:
		if frappe.db.exists("File", name):
			try:
				frappe.delete_doc("File", name, ignore_permissions=True)
			except Exception:
				frappe.log_error(frappe.get_traceback(), "Could not clean up Chemedge import file")


def _delete_questions(question_names: list[str]):
	for name in question_names:
		if frappe.db.exists("LMS Question", name):
			frappe.delete_doc("LMS Question", name, ignore_permissions=True)


@frappe.whitelist()
def import_pdf_trainer(pdf_file: str, source_folder: str | None = None):
	"""Create one native LMS Quiz from one strict-format Chemedge PDF.

	The upload is attached to the created quiz only after every question and image
	has been created.  Any error deletes created LMS objects/files and the upload.
	"""
	_require_import_permission()
	source_file = _uploaded_pdf(pdf_file)
	existing_quiz = _existing_import(source_file, source_folder)
	if existing_quiz:
		return {
			"quiz": existing_quiz.name,
			"title": existing_quiz.title,
			"question_count": existing_quiz.total_marks,
			"skipped": True,
		}
	created_file_names: list[str] = []
	created_question_names: list[str] = []
	quiz_name = None
	succeeded = False
	work_dir = Path(tempfile.mkdtemp(prefix="chemedge-pdf-import-"))

	try:
		pdf_path = Path(source_file.get_full_path())
		with pdfplumber.open(pdf_path) as pdf:
			header, header_lines, tasks, answers, answer_page_start, warnings = validate_format(pdf)
			page_count = len(pdf.pages)
			first_page_size = (float(pdf.pages[0].width), float(pdf.pages[0].height))

		bundle_dir = build_bundle(
			pdf_path=pdf_path,
			output_root=work_dir,
			dpi=200,
			header=header,
			header_lines=header_lines,
			tasks=tasks,
			answers=answers,
			answer_page_start=answer_page_start,
			validation_warnings=warnings,
			page_count=page_count,
			first_page_size=first_page_size,
		)
		meta = json.loads((bundle_dir / "meta.json").read_text(encoding="utf-8"))
		quiz = _create_quiz(meta, source_folder)
		quiz_name = quiz.name

		for task in meta["tasks"]:
			image_file = _store_task_image(bundle_dir / task["image"], quiz.name, int(task["number"]))
			created_file_names.append(image_file.name)
			question = frappe.get_doc(
				{
					"doctype": "LMS Question",
					"question": _question_html(task, image_file.file_url),
					"type": "User Input",
					"possibility_1": str(task["answer"]["text"]),
				}
			)
			question.insert(ignore_permissions=True)
			created_question_names.append(question.name)
			quiz.append("questions", {"question": question.name, "marks": 1})

		quiz.save(ignore_permissions=True)
		_attach_source_pdf(source_file, quiz.name)
		succeeded = True
		return {"quiz": quiz.name, "title": quiz.title, "question_count": len(meta["tasks"])}
	except FormatError as exc:
		frappe.throw(_("This PDF does not match the supported Chemedge trainer format: {0}").format(str(exc)))
	except Exception:
		raise
	finally:
		shutil.rmtree(work_dir, ignore_errors=True)
		if not succeeded:
			if quiz_name and frappe.db.exists("LMS Quiz", quiz_name):
				frappe.delete_doc("LMS Quiz", quiz_name, ignore_permissions=True)
			_delete_questions(created_question_names)
			_delete_files(created_file_names + [source_file.name])
