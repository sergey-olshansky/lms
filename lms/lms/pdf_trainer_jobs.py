"""Private, idempotent background jobs for AI-reviewed PDF imports."""

from __future__ import annotations

import hashlib
import json
import os
import re

import frappe
from frappe import _

TTL = 60 * 60


def _key(user, job_id):
	return f"pdf-trainer-job:{user}:{job_id}"


def report_progress(message, completed=0, total=0):
	job = frappe.flags.get("pdf_trainer_job")
	if not job:
		return
	key = _key(job["user"], job["job_id"])
	state = frappe.cache.get_value(key) or {}
	state.update(status="processing", message=message, completed=completed, total=total)
	frappe.cache.set_value(key, state, expires_in_sec=TTL)


@frappe.whitelist(methods=["GET"])
def get_import_session():
	"""Refresh this session's CSRF token before sending a private PDF."""
	from lms.lms.chemedge_pdf_import import _require_import_permission
	from frappe.sessions import get_csrf_token

	_require_import_permission()
	frappe.local.response_headers["Cache-Control"] = "no-store"
	return {"csrf_token": get_csrf_token()}


@frappe.whitelist(methods=["POST"])
def start_import(
	pdf_file: str,
	request_id: str | None = None,
	source_folder: str | None = None,
	first_task_number: str | int | None = None,
	last_task_number: str | int | None = None,
	show_answers: bool | int | str = False,
	use_ai: bool | int | str = True,
	ai_instruction: str = "",
):
	from lms.lms.chemedge_pdf_import import (
		_parse_show_answers, _requested_task_number_range, _require_import_permission,
		_source_folder_label, _uploaded_pdf,
	)

	_require_import_permission()
	_uploaded_pdf(pdf_file)
	if not isinstance(ai_instruction, str) or len(ai_instruction) > 1000:
		frappe.throw(_("AI guidance must be 1000 characters or fewer."), frappe.ValidationError)
	task_range = _requested_task_number_range(first_task_number, last_task_number)
	request_id = request_id or frappe.generate_hash(length=24)
	if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,80}", request_id):
		frappe.throw(_("Invalid PDF import request ID."), frappe.ValidationError)
	params = dict(pdf_file=pdf_file, source_folder=_source_folder_label(source_folder),
		first_task_number=task_range[0] if task_range else None,
		last_task_number=task_range[1] if task_range else None,
		show_answers=_parse_show_answers(show_answers), ai_instruction=ai_instruction.strip())
	user = frappe.session.user
	fingerprint = hashlib.sha256(json.dumps([user, request_id, params], sort_keys=True).encode()).hexdigest()
	index_key = f"pdf-trainer-request:{fingerprint}"
	with frappe.cache.lock(index_key + ":lock", timeout=15):
		job_id = frappe.cache.get_value(index_key)
		state = frappe.cache.get_value(_key(user, job_id)) if job_id else None
		if state and state.get("status") in {"queued", "processing", "done"}:
			return {"job_id": job_id}
		job_id = frappe.generate_hash(length=24)
		key = _key(user, job_id)
		frappe.cache.set_value(key, {"status": "queued", "message": _("Waiting for AI review")}, expires_in_sec=TTL)
		try:
			frappe.enqueue("lms.lms.pdf_trainer_jobs.run_import", queue=os.environ.get("LMS_PDF_IMPORT_QUEUE") or frappe.conf.get("pdf_import_queue") or "long",
				timeout=1200, job_id=f"pdf-trainer-{job_id}", deduplicate=True,
				owner=user, import_job_id=job_id, params=params)
		except Exception:
			frappe.cache.delete_value(key)
			raise
		frappe.cache.set_value(index_key, job_id, expires_in_sec=TTL)
	return {"job_id": job_id}


@frappe.whitelist()
def get_status(job_id: str):
	from lms.lms.chemedge_pdf_import import _require_import_permission

	_require_import_permission()
	if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9]{24}", job_id):
		frappe.throw(_("Invalid PDF import job ID."), frappe.ValidationError)
	state = frappe.cache.get_value(_key(frappe.session.user, job_id))
	if not state:
		frappe.throw(_("PDF import job was not found or has expired."), frappe.DoesNotExistError)
	return state


def run_import(owner, import_job_id, params):
	from lms.lms.chemedge_pdf_import import import_pdf_trainer

	frappe.set_user(owner)
	frappe.flags.pdf_trainer_job = {"user": owner, "job_id": import_job_id}
	key = _key(owner, import_job_id)
	try:
		report_progress(_("Reading PDF structure"))
		result = import_pdf_trainer(**params)
		frappe.db.commit()
		frappe.cache.set_value(key, {"status": "done", "result": result}, expires_in_sec=TTL)
	except Exception as exc:
		frappe.db.rollback()
		message = str(exc) if isinstance(exc, frappe.ValidationError) else _("PDF import failed. Your private PDF is kept; retry the import.")
		frappe.log_error(title="AI PDF import job failed", message=frappe.get_traceback())
		frappe.cache.set_value(key, {"status": "error", "error": message}, expires_in_sec=TTL)
	finally:
		frappe.flags.pdf_trainer_job = None
