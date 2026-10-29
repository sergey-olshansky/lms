"""Regression checks for mandatory AI review and shared PDF instructions."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import frappe

from lms.lms import chemedge_pdf_import as importer


def candidate():
	return {
		"tasks": [{"number": 1, "region_refs": ["context", "body"]}],
		"regions": {
			"context": {"kind": "context", "page_number": 1, "text": "1) Si 2) K 3) Ca 4) Zn 5) Be"},
			"body": {"kind": "task", "page_number": 1, "text": "Расположите выбранные элементы в порядке увеличения свойств."},
		},
	}


class TestPDFReview(unittest.TestCase):
	def setUp(self):
		# These tests exercise planning and answer semantics; PDF-coordinate
		# resolution is covered separately with real/mocked page geometry.
		resolver = patch.object(importer, "_resolve_extracted_task", side_effect=lambda task, path: task)
		resolver.start()
		self.addCleanup(resolver.stop)

	def test_text_planner_accepts_a_pdf_above_the_old_30_page_limit(self):
		page = Mock()
		page.extract_text.return_value = "Page text"
		pdf = Mock()
		pdf.pages = [page for _ in range(37)]
		with patch.object(importer.pdfplumber, "open") as opened:
			opened.return_value.__enter__.return_value = pdf
			pages = importer._pdf_pages_as_text(Path("trainer.pdf"))
		self.assertEqual(len(pages), 37)
		self.assertIn("--- PDF page 37 ---", pages[-1])

	def test_streamed_json_ignores_reasoning_and_requires_completion(self):
		response = Mock()
		# Construct content with the same JSON encoding used by the provider.
		response.iter_lines.return_value = iter([
			b'data: ' + json.dumps({"choices": [{"delta": {"reasoning_content": "reasoning"}}]}).encode(),
			b'data: ' + json.dumps({"choices": [{"delta": {"content": '{"tasks":[]}'}}]}).encode(),
			b'data: ' + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}).encode(),
			b'data: [DONE]',
		])
		with patch.object(importer, "_zai_setting", return_value="private-setting"), patch.object(importer.requests, "post", return_value=response) as request:
			self.assertEqual(importer._ai_json("audit", "data"), {"tasks": []})
		self.assertTrue(request.call_args.kwargs["stream"])
		response.close.assert_called_once()

	def test_truncated_stream_cannot_be_saved(self):
		response = Mock()
		response.iter_lines.return_value = iter([b'data: ' + json.dumps({"choices": [{"delta": {"content": '{"tasks":[]}'}}]}).encode()])
		with patch.object(importer, "_zai_setting", return_value="private-setting"), patch.object(importer.requests, "post", return_value=response), patch.object(frappe, "log_error"), self.assertRaises(frappe.ValidationError):
			importer._ai_json("audit", "data")
		response.close.assert_called_once()

	def test_model_cannot_drop_printed_shared_condition(self):
		regions = importer._validate_ai_regions([{"ref": "body"}], candidate(), 1)
		self.assertEqual([region["kind"] for region in regions], ["context", "task"])

	def test_long_model_anchors_are_compacted_without_another_request(self):
		regions = importer._validate_ai_regions([{"page": 1, "start": "opening " * 40, "end": "ending " * 40, "kind": "task"}], {}, 1)
		self.assertLessEqual(len(regions[0]["start"]), 160)
		self.assertLessEqual(len(regions[0]["end"]), 160)

	def test_ambiguous_source_anchor_is_rejected(self):
		page = Mock()
		page.search.return_value = [{"top": 10, "bottom": 20}, {"top": 30, "bottom": 40}]
		self.assertIsNone(importer._find_source_anchor(page, "same repeated text"))

	def test_two_token_source_anchor_can_be_located_from_pdf_words(self):
		page = Mock()
		page.search.return_value = []
		page.extract_words.return_value = [
			{"text": "5)", "top": 10, "bottom": 20},
			{"text": "толуол", "top": 10, "bottom": 20},
			{"text": "6)", "top": 30, "bottom": 40},
			{"text": "стирол", "top": 30, "bottom": 40},
		]
		self.assertEqual(importer._find_source_anchor(page, "6) стирол"), (30.0, 40.0))

	def test_repeated_short_ending_is_unique_inside_task_boundary(self):
		page = Mock()
		page.search.return_value = [
			{"top": 100, "bottom": 110},
			{"top": 200, "bottom": 210},
		]
		self.assertEqual(importer._find_source_anchor(page, "Ответ:", after=80, before=150), (100.0, 110.0))

	def test_unknown_region_is_rejected_instead_of_guessing_a_page(self):
		with self.assertRaises(frappe.ValidationError):
			importer._validate_ai_regions([{"ref": "invented"}], candidate(), 1)

	def test_unlocatable_or_empty_source_plan_is_rejected(self):
		for regions in [[], [{"page": 1, "start": "", "end": "last", "kind": "task"}], [{"ref": "context"}]]:
			with self.subTest(regions=regions), self.assertRaises(frappe.ValidationError):
				importer._validate_ai_regions(regions, candidate(), 1)

	def test_order_requirement_in_source_overrides_ai_multiple_choice(self):
		_, tasks = importer._validate_ai_tasks({"tasks": [{"number": 1, "reviewed": True, "question": "Выберите элементы.", "answer": "432", "options": ["K", "Ca", "Zn"], "correct_options": [1, 2, 3], "source_regions": [{"ref": "context"}, {"ref": "body"}]}]}, Path("source.pdf"), candidate())
		self.assertEqual(tasks[0]["options"], [])
		self.assertEqual(tasks[0]["answer"], "432")

	def test_legacy_false_flag_still_requires_ai_and_preserves_upload_on_failure(self):
		upload = Mock(name="upload")
		upload.get_full_path.return_value = "/tmp/source.pdf"
		with patch.object(importer, "_require_import_permission"), patch.object(importer, "_uploaded_pdf", return_value=upload), patch.object(importer, "_template_candidate", return_value={}), patch.object(importer, "_extract_trainer_with_ai", side_effect=RuntimeError("AI unavailable")) as review, patch.object(importer, "_create_quiz") as create, patch.object(importer, "_delete_files") as delete:
			with self.assertRaisesRegex(RuntimeError, "AI unavailable"):
				importer.import_pdf_trainer("uploaded-file", use_ai=0)
			review.assert_called_once()
			create.assert_not_called()
			self.assertEqual(delete.call_args.args[0], [])

	def test_numeric_sequence_does_not_accept_a_transposed_digit(self):
		from lms.lms.doctype.lms_quiz.lms_quiz import check_input_answers
		from lms.lms.doctype.lms_question.lms_question import QUESTION_POSSIBILITY_FIELDS
		values = dict.fromkeys(QUESTION_POSSIBILITY_FIELDS, "")
		values["possibility_1"] = "1234567"
		with patch.object(frappe.db, "get_value", return_value=values):
			self.assertEqual(check_input_answers("question", "1234576"), 0)
			self.assertEqual(check_input_answers("question", "1 2 3 4 5 6 7"), 1)
		values["possibility_1"] = "hydroxide"
		with patch.object(frappe.db, "get_value", return_value=values):
			self.assertEqual(check_input_answers("question", "hydroxid"), 1)

	def test_passed_parser_needs_only_audit_without_pdf_or_answers(self):
		base = candidate()
		base.update(parsed_ok=True, title="Quiz")
		base["regions"]["body"]["embedded_images"] = 1
		base["tasks"][0].update(question="Расположите элементы.", answer="432", options=[], correct_options=[])
		with patch.object(importer, "_ai_json", return_value={"tasks": [{"number": 1, "complete": True, "has_answer": True, "issues": ["cosmetic artifact, understanding unaffected"]}]}) as ai, patch.object(importer, "_pdf_pages_as_text") as pages:
			_, tasks = importer._extract_trainer_with_ai(Path("source.pdf"), Path("/tmp"), candidate=base)
		self.assertEqual(tasks[0]["answer"], "432")
		self.assertEqual(ai.call_count, 1)
		pages.assert_not_called()
		self.assertNotIn("432", ai.call_args.args[1])
		self.assertEqual(json.loads(ai.call_args.args[1])["tasks"][0]["preserved_source_images"], 1)
		self.assertIn("Do NOT check answer correctness", ai.call_args.args[0])

	def test_fallback_plans_once_and_sends_only_requested_pages(self):
		plan = {"title": "Quiz", "total_tasks": 1, "tasks": [{"number": 1, "question_pages": [1], "context_pages": [], "answer_pages": [3]}]}
		result = {"tasks": [{"number": 1, "reviewed": True, "question": "Question", "answer": "42", "source_regions": [{"page": 1, "start": "Question", "end": "end", "kind": "task"}]}]}
		with patch.object(importer, "_ai_json", side_effect=[plan, result]) as ai, patch.object(importer, "_pdf_pages_as_text", return_value=["QUESTION_PAGE", "UNRELATED_PAGE", "ANSWER_PAGE"]) as pages:
			_, tasks = importer._extract_trainer_with_ai(Path("source.pdf"), Path("/tmp"), candidate={"parsed_ok": False})
		self.assertEqual(ai.call_count, 2)
		pages.assert_called_once()
		self.assertIn("UNRELATED_PAGE", ai.call_args_list[0].args[1])
		self.assertNotIn("UNRELATED_PAGE", ai.call_args_list[1].args[1])
		self.assertIn("ANSWER_PAGE", ai.call_args_list[1].args[1])
		self.assertEqual(tasks[0]["answer"], "42")

	def test_unrecognised_layout_reaches_ai_planner(self):
		with patch.object(importer.pdfplumber, "open"), patch.object(importer, "validate_format", side_effect=importer.FormatError("unknown")), patch.object(importer, "find_tasks", side_effect=importer.FormatError("unknown")):
			base = importer._template_candidate(Path("unknown.pdf"), None)
		self.assertFalse(base["parsed_ok"])
		self.assertEqual(base["tasks"], [])

	def test_only_failed_question_is_extracted_again(self):
		base = candidate()
		base.update(parsed_ok=True, title="Quiz")
		base["tasks"][0].update(question="Question one", answer="432")
		base["tasks"].append({**base["tasks"][0], "number": 2, "question": "Question two"})
		audit = {"tasks": [{"number": 1, "complete": True, "has_answer": True, "issues": []}, {"number": 2, "complete": False, "has_answer": True, "issues": ["missing context"]}]}
		plan = {"total_tasks": 2, "tasks": [{"number": n, "question_pages": [1]} for n in [1, 2]]}
		result = {"tasks": [{"number": 2, "reviewed": True, "question": "Complete two", "answer": "42", "source_regions": [{"page": 1, "start": "Complete", "end": "two", "kind": "task"}]}]}
		with patch.object(importer, "_ai_json", side_effect=[audit, plan, result]) as ai, patch.object(importer, "_pdf_pages_as_text", return_value=["FULL PDF"]):
			_, tasks = importer._extract_trainer_with_ai(Path("source.pdf"), Path("/tmp"), candidate=base)
		self.assertEqual([task["number"] for task in tasks], [1, 2])
		self.assertEqual(tasks[1]["answer"], "432")
		self.assertEqual(ai.call_count, 3)
		self.assertIn("stable import number 2", ai.call_args.args[0])

	def test_invalid_plan_count_or_pages_fail_closed(self):
		for plan in [{"total_tasks": 2, "tasks": [{"number": 1, "question_pages": [1]}]}, {"total_tasks": 1, "tasks": [{"number": 1, "question_pages": [4]}]}]:
			with self.subTest(plan=plan), self.assertRaises(frappe.ValidationError):
				importer._validate_page_plan(plan, 3)

	def test_candidate_is_not_saved_without_explicit_ai_confirmation(self):
		with self.assertRaises(frappe.ValidationError):
			importer._validate_ai_tasks({"tasks": [{"number": 1}]}, Path("source.pdf"), candidate())


class TestAIServiceFallback(unittest.TestCase):
	def setUp(self):
		resolver = patch.object(importer, "_resolve_extracted_task", side_effect=lambda task, path: task)
		resolver.start()
		self.addCleanup(resolver.stop)

	def recognised(self):
		base = candidate()
		base.update(parsed_ok=True, title="Recognised PDF")
		base["tasks"][0].update(question="Расположите элементы.", answer="432")
		return base

	def test_service_failure_reuses_recognised_questions_with_warning(self):
		with patch.object(importer, "_extract_trainer_with_ai", side_effect=importer.AIUnavailable("offline")):
			title, tasks, used_ai, warning = importer._prepare_trainer(Path("source.pdf"), Path("/tmp"), None, "", self.recognised())
		self.assertEqual(title, "Recognised PDF")
		self.assertEqual(tasks[0]["answer"], "432")
		self.assertEqual(tasks[0]["options"], [])
		self.assertFalse(used_ai)
		self.assertIn("without AI review", warning)
		self.assertEqual([r["kind"] for r in tasks[0]["source_regions"]], ["context", "task"])

	def test_incomplete_review_uses_parser_and_specific_warning(self):
		with patch.object(importer, "_extract_trainer_with_ai", side_effect=importer.AIReviewIncomplete("incomplete response")):
			_, tasks, used_ai, warning = importer._prepare_trainer(Path("source.pdf"), Path("/tmp"), None, "", self.recognised())
		self.assertEqual(tasks[0]["answer"], "432")
		self.assertFalse(used_ai)
		self.assertIn("AI returned an incomplete review", warning)

	def test_restarted_printed_numbers_keep_all_tasks_and_answers(self):
		page = Mock(); page.images = []
		pdf = Mock(); pdf.pages = [page]
		tasks = [{"number": number, "key": f"task-{index}", "text": f"{number}. Question {index}", "page_number": 1, "page_width": 600, "page_height": 800, "bbox": (0, index * 50, 500, index * 50 + 40)} for index, number in enumerate([1, 2, 1], start=1)]
		answers = {task["key"]: {"text": str(index)} for index, task in enumerate(tasks, start=1)}
		with patch.object(importer.pdfplumber, "open") as opened, patch.object(importer, "validate_format", return_value=("Quiz", None, tasks, answers, None, None)):
			opened.return_value.__enter__.return_value = pdf
			base = importer._template_candidate(Path("source.pdf"), None)
			selected = importer._template_candidate(Path("source.pdf"), (3, 3))
		self.assertEqual([task["number"] for task in base["tasks"]], [1, 2, 3])
		self.assertEqual([task["source_number"] for task in base["tasks"]], [1, 2, 1])
		self.assertEqual(selected["tasks"][0]["answer"], "3")
		self.assertEqual(selected["tasks"][0]["source_number"], 1)

	def test_incomplete_audit_moves_to_page_planning(self):
		plan = {"title": "Planned", "total_tasks": 1, "tasks": [{"number": 1, "question_pages": [1], "answer_pages": [2]}]}
		extracted = {"tasks": [{"number": 1, "reviewed": True, "question": "Полное условие", "answer": "432", "source_regions": [{"page": 1, "start": "Полное", "end": "условие", "kind": "task"}]}]}
		with patch.object(importer, "_ai_json", side_effect=[{"tasks": []}, plan, extracted]) as ai, patch.object(importer, "_pdf_pages_as_text", return_value=["page1", "page2"]):
			_, tasks, used_ai, warning = importer._prepare_trainer(Path("source.pdf"), Path("/tmp"), None, "", self.recognised())
		self.assertEqual(ai.call_count, 3)
		self.assertTrue(used_ai)
		self.assertEqual(warning, "")
		self.assertEqual(tasks[0]["answer"], "432")
		self.assertIn("Plan extraction", ai.call_args_list[1].args[0])

	def test_string_numbers_in_review_are_normalised(self):
		verdicts = importer._validated_review_verdicts({"tasks": [{"number": "1", "complete": True, "has_answer": True}]}, {1})
		self.assertEqual(verdicts[0]["number"], 1)

	def test_invalid_review_shapes_are_technical_failures(self):
		for audit in [{}, {"tasks": [None]}, {"tasks": [{"number": 1}]}, {"tasks": [{"number": [1], "complete": True, "has_answer": True}]}, {"tasks": [{"number": 1, "complete": True, "has_answer": True}] * 2}]:
			with self.subTest(audit=audit), self.assertRaises(importer.AIReviewIncomplete):
				importer._validated_review_verdicts(audit, {1})

	def test_valid_negative_review_still_requires_ai_repair(self):
		verdicts = importer._validated_review_verdicts({"tasks": [{"number": 1, "complete": False, "has_answer": True}]}, {1})
		self.assertFalse(verdicts[0]["complete"])

	def test_unknown_format_cannot_fallback(self):
		with patch.object(importer, "_extract_trainer_with_ai", side_effect=importer.AIUnavailable("offline")), self.assertRaises(importer.AIUnavailable):
			importer._prepare_trainer(Path("source.pdf"), Path("/tmp"), None, "", {"parsed_ok": False})

	def test_missing_parser_answer_cannot_fallback(self):
		base = self.recognised()
		base["tasks"][0]["answer"] = ""
		with patch.object(importer, "_extract_trainer_with_ai", side_effect=importer.AIUnavailable("offline")), self.assertRaises(frappe.ValidationError):
			importer._prepare_trainer(Path("source.pdf"), Path("/tmp"), None, "", base)

	def test_rejected_ai_result_is_not_a_service_outage(self):
		with patch.object(importer, "_extract_trainer_with_ai", side_effect=frappe.ValidationError("Incomplete source question")), self.assertRaisesRegex(frappe.ValidationError, "Incomplete source"):
			importer._prepare_trainer(Path("source.pdf"), Path("/tmp"), None, "", self.recognised())

	def test_network_error_is_classified_as_service_unavailable(self):
		with patch.object(importer, "_zai_setting", return_value="private-setting"), patch.object(importer.requests, "post", side_effect=importer.requests.Timeout()), patch.object(frappe, "log_error"), self.assertRaises(importer.AIUnavailable):
			importer._ai_json("check", "data")


class TestPDFImportJobs(unittest.TestCase):
	def setUp(self):
		from contextlib import nullcontext
		translation = patch("lms.lms.pdf_trainer_jobs._", side_effect=lambda text: text)
		translation.start()
		self.addCleanup(translation.stop)
		self.cache = Mock()
		self.values = {}
		self.cache.lock.side_effect = lambda *args, **kwargs: nullcontext()
		self.cache.get_value.side_effect = lambda key: self.values.get(key)
		self.cache.set_value.side_effect = lambda key, value, **kwargs: self.values.__setitem__(key, value)

	def test_queued_cancellation_is_confirmed_without_waiting_for_a_busy_worker(self):
		from lms.lms import pdf_trainer_jobs as jobs
		job_id = "b" * 24
		key = jobs._key(frappe.session.user, job_id)
		self.values[key] = {"status": "queued"}
		with patch.object(frappe, "cache", self.cache), patch.object(importer, "_require_import_permission"), patch("frappe.utils.background_jobs.get_job_status", return_value="queued"):
			state = jobs.cancel_import(job_id)
		self.assertEqual(state["status"], "cancelled")
		self.assertTrue(state["cancel_requested"])

	def test_failed_worker_job_does_not_leave_the_ui_processing_forever(self):
		from lms.lms import pdf_trainer_jobs as jobs
		job_id = "c" * 24
		self.values[jobs._key(frappe.session.user, job_id)] = {"status": "processing"}
		with patch.object(frappe, "cache", self.cache), patch.object(importer, "_require_import_permission"), patch("frappe.utils.background_jobs.get_job_status", return_value="failed"):
			state = jobs.get_status(job_id)
		self.assertEqual(state["status"], "error")
		self.assertIn("retry", state["error"])
		self.assertIn("no-store", frappe.local.response_headers["Cache-Control"])

	def test_progress_does_not_overwrite_a_cancellation_request(self):
		from lms.lms import pdf_trainer_jobs as jobs
		job_id = "d" * 24
		self.values[jobs._key(frappe.session.user, job_id)] = {"status": "cancelling", "cancel_requested": True}
		frappe.flags.pdf_trainer_job = {"user": frappe.session.user, "job_id": job_id}
		try:
			with patch.object(frappe, "cache", self.cache), self.assertRaises(jobs.ImportCancelled):
				jobs.report_progress("next stage")
		finally:
			frappe.flags.pdf_trainer_job = None

	def test_import_session_refresh_keeps_csrf_protection_and_disables_cache(self):
		from lms.lms import pdf_trainer_jobs as jobs
		with patch.object(importer, "_require_import_permission") as permission, patch("frappe.sessions.get_csrf_token", return_value="fresh-test-token"):
			result = jobs.get_import_session()
		permission.assert_called_once()
		self.assertEqual(result, {"csrf_token": "fresh-test-token"})
		self.assertEqual(frappe.local.response_headers["Cache-Control"], "no-store")
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[jobs.get_import_session], ("GET", "QUERY"))

	def test_public_job_endpoints_pass_enforced_frappe_types(self):
		import inspect
		from frappe.utils.typing_validations import transform_parameter_types
		from lms.lms import pdf_trainer_jobs as jobs
		params = {"pdf_file": "source-file", "request_id": "request-1", "source_folder": "Folder", "first_task_number": 1, "last_task_number": 3, "show_answers": 0, "use_ai": 1, "ai_instruction": ""}
		transform_parameter_types(inspect.unwrap(jobs.start_import), (), params, force_types=True)
		transform_parameter_types(inspect.unwrap(jobs.get_status), (), {"job_id": "a" * 24}, force_types=True)

	def test_retry_does_not_enqueue_a_second_running_import(self):
		from lms.lms import pdf_trainer_jobs as jobs
		with patch.object(frappe, "cache", self.cache), patch.object(frappe, "enqueue") as enqueue, patch("frappe.utils.background_jobs.get_job_status", return_value="queued"), patch.object(importer, "_require_import_permission"), patch.object(importer, "_uploaded_pdf"):
			first = jobs.start_import("source-file", request_id="same-upload-request")
			second = jobs.start_import("source-file", request_id="same-upload-request")
			self.assertEqual(first, second)
			enqueue.assert_called_once()

	def test_job_result_is_private_to_its_owner(self):
		from lms.lms import pdf_trainer_jobs as jobs
		job_id = "a" * 24
		self.values[jobs._key("someone-else", job_id)] = {"status": "done", "result": {"quiz": "private"}}
		with patch.object(frappe, "cache", self.cache), patch.object(importer, "_require_import_permission"), self.assertRaises(frappe.DoesNotExistError):
			jobs.get_status(job_id)
