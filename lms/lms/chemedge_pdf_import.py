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
TASK_NUMBER_MIN = 1
TASK_NUMBER_MAX = 9999


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
	if file_doc.owner != frappe.session.user and not (_is_system_manager() or has_moderator_role()):
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
		f'<p>Task {number} · FIPI ID {task_id}</p><p><img src="{image_url}" alt="Task {number}"></p>',
		always_sanitize=True,
	)


def _source_folder_label(source_folder: str | None) -> str:
	"""Return a normalized relative folder label supplied by the browser."""
	if not isinstance(source_folder, str):
		return ""

	# The browser sends a relative folder path. Keep only ordinary path parts so
	# it cannot introduce traversal-looking labels into a quiz title.
	folder_parts = [part.strip() for part in source_folder.split("/") if part.strip() not in {"", ".", ".."}]
	return " / ".join(folder_parts)


def _quiz_title(
	meta: dict,
	source_folder: str | None,
	task_number_range: tuple[int, int] | None = None,
) -> str:
	"""Prefix the PDF's quiz title with its selected directory path."""
	header = str(meta["header"]).strip()
	folder = _source_folder_label(source_folder)
	parts = [part for part in (folder, header) if part]
	if task_number_range:
		parts.append(f"tasks {task_number_range[0]}–{task_number_range[1]}")
	return " · ".join(parts)


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


def _create_quiz(
	meta: dict,
	source_folder: str | None = None,
	task_number_range: tuple[int, int] | None = None,
):
	quiz = frappe.get_doc(
		{
			"doctype": "LMS Quiz",
			"title": _unique_quiz_title(_quiz_title(meta, source_folder, task_number_range)),
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


def _parse_task_number(value, field_label: str) -> int | None:
	"""Return an int task number for a whitelisted argument, or None when empty."""
	if value is None or (isinstance(value, str) and not value.strip()):
		return None
	try:
		number = int(str(value).strip())
	except (TypeError, ValueError):
		number = None
	if number is None or not TASK_NUMBER_MIN <= number <= TASK_NUMBER_MAX:
		frappe.throw(
			_("{0} must be a whole number between {1} and {2}.").format(
				field_label, TASK_NUMBER_MIN, TASK_NUMBER_MAX
			),
			frappe.ValidationError,
		)
	return number


def apply_task_number_range(
	first_task_number,
	last_task_number,
	tasks: list[dict],
) -> tuple[tuple[int, int] | None, list[dict]]:
	"""Validate an optional printed task-number range and filter tasks by it.

	Both bounds empty keeps the given task list untouched (full import). Any
	other combination must select an inclusive, existing range of the printed
	numbers; duplicates (compiled PDFs) reject selection because a repeated
	number is ambiguous. Returns ``(range, filtered_tasks)`` for the caller to
	suffix the quiz title with.
	"""
	first = _parse_task_number(first_task_number, _("First task number"))
	last = _parse_task_number(last_task_number, _("Last task number"))
	if (first is None) != (last is None):
		frappe.throw(
			_("Fill in both the first and the last task number, or leave both empty."),
			frappe.ValidationError,
		)
	if first is None or last is None:
		return None, tasks

	if first > last:
		frappe.throw(
			_("The first task number must not be greater than the last task number."),
			frappe.ValidationError,
		)

	numbers = [int(task["number"]) for task in tasks]
	duplicates = sorted({number for number in numbers if numbers.count(number) > 1})
	if duplicates:
		frappe.throw(
			_(
				"This PDF repeats task numbers ({0}), so a task-number range cannot be"
				" selected. Import it without a range instead."
			).format(", ".join(str(number) for number in duplicates)),
			frappe.ValidationError,
		)

	filtered = [task for task in tasks if first <= int(task["number"]) <= last]
	if not filtered:
		frappe.throw(
			_(
				"No tasks with numbers {0}–{1} were found in this PDF: it has {2} task(s)"
				" numbered {3}–{4}."
			).format(first, last, len(numbers), min(numbers), max(numbers)),
			frappe.ValidationError,
		)
	if first not in numbers or last not in numbers:
		frappe.throw(
			_(
				"Task numbers {0}–{1} must both exist in this PDF: it has {2} task(s)" " numbered {3}–{4}."
			).format(first, last, len(numbers), min(numbers), max(numbers)),
			frappe.ValidationError,
		)
	return (first, last), filtered


@frappe.whitelist(methods=["POST"])
def import_pdf_trainer(
	pdf_file: str,
	source_folder: str | None = None,
	first_task_number: str | int | None = None,
	last_task_number: str | int | None = None,
):
	"""Create one native LMS Quiz from one strict-format Chemedge PDF.

	The upload is attached to the created quiz only after every question and image
	has been created.  Any error deletes created LMS objects/files and the upload.
	An optional inclusive first/last printed task-number range filters the tasks
	that reach the quiz; answers stay unfiltered (they are keyed per task).
	"""
	_require_import_permission()
	source_file = _uploaded_pdf(pdf_file)
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

		task_number_range, tasks = apply_task_number_range(first_task_number, last_task_number, tasks)

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
		quiz = _create_quiz(meta, source_folder, task_number_range)
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
