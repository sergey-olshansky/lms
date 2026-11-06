"""Vision digitization of scanned (textless) PDFs in the AI import pipeline."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import frappe
from lms.lms import chemedge_pdf_import as importer

LONG_TASK_TEXT = (
	"[1] First words of task with a complete chemistry condition, a table of "
	"substances and printed answer options followed by Last words of task"
)
LONG_KEY_TEXT = "Ключ ответов: [1] 2 [2] 3 [3] 1 и записано достаточно текста для порога распознавания"

# Real digitization artefacts observed on the staged scan (task-42 fix):
# the vision model decorates markers/headings with Markdown and the
# extraction model quotes plain anchors back.
MARKDOWN_DIGITIZED_PAGE = (
	"# Вопрос №14 ОГЭ\n\n"
	"**[10]** Выберите два исходных вещества, взаимодействию которых соответствует сокращённое ионное уравнение\n"
	"1) NaOH\n2) KOH\n3) Ba(OH)₂\n4) BaCO₃\n5) HBr\n6) HNO₂\n\n"
	"Запишите номера выбранных ответов.\n\n"
	"**[11]** Выберите два исходных вещества, взаимодействию которых соответствует иное уравнение\n"
	"1) Cu\n2) Fe\n3) Zn\n4) Mg\n5) Ba\n6) **Al**\n\n"
	"Запишите номера выбранных ответов.\n"
)


def make_opened_pdf(pages_text, width=595.0, height=842.0):
	pages = []
	for text in pages_text:
		page = Mock()
		page.extract_text.return_value = text
		page.width, page.height = width, height
		pages.append(page)
	pdf = Mock()
	pdf.pages = pages
	opened = MagicMock()
	opened.__enter__.return_value = pdf
	return opened


def stream_response(*deltas):
	response = Mock()
	response.iter_lines.return_value = iter(
		[b"data: " + json.dumps({"choices": [{"delta": {"content": part}}]}).encode() for part in deltas]
		+ [b"data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}).encode(), b"data: [DONE]"]
	)
	return response


class VisionDigitizeTestCase(unittest.TestCase):
	def setUp(self):
		self.cache = {}

		def zai_setting(name, config_name=None, default=""):
			return {"ZAI_VISION_MODEL": "glm-5.3-flash", "LMS_PDF_AI_CONCURRENCY": "2"}.get(name, default)

		patches = [
			patch.object(importer, "_", side_effect=lambda text: text),
			patch.object(importer, "_ai_settings", return_value={"api_key": "test-key", "model": "glm-5.3", "url": "https://zai.example/chat/completions"}),
			patch.object(importer, "_zai_setting", side_effect=zai_setting),
			patch.object(importer, "_checkpoint_get", side_effect=lambda prefix, suffix: self.cache.get((prefix, suffix))),
			patch.object(importer, "_checkpoint_set", side_effect=lambda prefix, suffix, value: self.cache.__setitem__((prefix, suffix), value)),
			patch("lms.lms.pdf_trainer_jobs.report_progress"),
		]
		for item in patches:
			item.start()
			self.addCleanup(item.stop)

	def test_text_layer_pdf_skips_vision_digitization(self):
		opened = make_opened_pdf(["Real printed task text with enough characters to pass the threshold. " * 3])
		with patch.object(importer.pdfplumber, "open", return_value=opened), patch.object(importer, "_digitize_pdf_pages") as digitize:
			pages = importer._pdf_pages_as_text(Path("trainer.pdf"))
		digitize.assert_not_called()
		self.assertIn("Real printed task text", pages[0])

	def test_emoji_only_text_layer_triggers_digitization(self):
		opened = make_opened_pdf(["🐾", "🐾"])
		with patch.object(importer.pdfplumber, "open", return_value=opened), patch.object(importer, "_digitize_pdf_pages", return_value=["[1] digitized", "[2] key"]) as digitize:
			pages = importer._pdf_pages_as_text(Path("trainer.pdf"), "prefix")
		digitize.assert_called_once()
		self.assertIn("[1] digitized", pages[0])
		self.assertIn("--- PDF page 2 ---", pages[1])
		self.assertIn("[2] key", pages[1])

	def test_digitize_uses_vision_model_and_checkpoints_the_result(self):
		opened = make_opened_pdf(["", ""])
		with patch.object(importer.pdfplumber, "open", return_value=opened), \
			patch.object(importer, "_page_image_data_url", side_effect=lambda pdf, index: f"data:image/png;base64,page{index}"), \
			patch.object(importer, "_vision_page_text", side_effect=[LONG_TASK_TEXT, LONG_KEY_TEXT]) as vision:
			pages = importer._digitize_pdf_pages(Path("scan.pdf"), ["", ""], "prefix")
		self.assertEqual(pages, [LONG_TASK_TEXT, LONG_KEY_TEXT])
		self.assertEqual(vision.call_count, 2)
		self.assertEqual(vision.call_args.args[3]["model"], "glm-5.3-flash")
		self.assertEqual(self.cache[("prefix", "digitized:glm-5.3-flash")], [LONG_TASK_TEXT, LONG_KEY_TEXT])

	def test_digitize_resume_reuses_checkpoint_without_new_vision_calls(self):
		self.cache[("prefix", "digitized:glm-5.3-flash")] = [LONG_TASK_TEXT, LONG_KEY_TEXT]
		with patch.object(importer, "_vision_page_text", side_effect=AssertionError("vision must not run again")):
			pages = importer._digitize_pdf_pages(Path("scan.pdf"), ["", ""], "prefix")
		self.assertEqual(pages, [LONG_TASK_TEXT, LONG_KEY_TEXT])

	def test_unusable_digitization_names_the_cause(self):
		opened = make_opened_pdf(["", ""])
		with patch.object(importer.pdfplumber, "open", return_value=opened), \
			patch.object(importer, "_page_image_data_url", return_value="data:image/png;base64,AAA"), \
			patch.object(importer, "_vision_page_text", return_value=""):
			with self.assertRaises(frappe.ValidationError) as raised:
				importer._digitize_pdf_pages(Path("scan.pdf"), ["", ""], "prefix")
		message = str(raised.exception)
		self.assertIn("no selectable text layer", message)
		self.assertIn("OCR failed", message)
		self.assertNotIn("invalid PDF page plan", message)

	def test_vision_outage_is_wrapped_with_the_no_text_layer_cause(self):
		opened = make_opened_pdf(["", ""])
		with patch.object(importer.pdfplumber, "open", return_value=opened), \
			patch.object(importer, "_page_image_data_url", return_value="data:image/png;base64,AAA"), \
			patch.object(importer, "_vision_page_text", side_effect=importer.AIUnavailable("provider 500")):
			with self.assertRaises(importer.AIUnavailable) as raised:
				importer._digitize_pdf_pages(Path("scan.pdf"), ["", ""], "prefix")
		message = str(raised.exception)
		self.assertIn("no selectable text layer", message)
		self.assertIn("vision", message)

	def test_digitized_plan_failure_never_reports_the_bare_page_plan_error(self):
		opened = make_opened_pdf(["🐾"])
		with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
			handle.write(b"%PDF-fake")
			handle.flush()
			with patch.object(importer.pdfplumber, "open", return_value=opened), \
				patch.object(importer, "_checkpoint_prefix", return_value="prefix"), \
				patch.object(importer, "_page_image_data_url", return_value="data:image/png;base64,AAA"), \
				patch.object(importer, "_vision_page_text", return_value=LONG_TASK_TEXT), \
				patch.object(importer, "_ai_json", return_value={"title": "Broken", "total_tasks": 0, "tasks": []}):
				with self.assertRaises(frappe.ValidationError) as raised:
					importer._extract_trainer_with_ai(Path(handle.name), Path(tempfile.gettempdir()), candidate={"parsed_ok": False})
		message = str(raised.exception)
		self.assertIn("digitized", message)
		self.assertIn("no text layer", message)
		self.assertNotIn("invalid PDF page plan", message)

	def test_digitized_success_flows_through_planning_and_extraction(self):
		opened = make_opened_pdf(["🐾", "🐾"])
		plan = {"title": "Trainer", "total_tasks": 1, "tasks": [{"number": 1, "question_pages": [1], "context_pages": [], "answer_pages": [2]}]}
		extraction = {"tasks": [{"number": 1, "reviewed": True, "question": "Question", "answer": "2", "source_regions": [{"page": 1, "start": "[1] First words of task", "end": "Last words of task", "kind": "task"}]}]}
		with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
			handle.write(b"%PDF-fake")
			handle.flush()
			with patch.object(importer.pdfplumber, "open", return_value=opened), \
				patch.object(importer, "_checkpoint_prefix", return_value="prefix"), \
				patch.object(importer, "_page_image_data_url", return_value="data:image/png;base64,AAA"), \
				patch.object(importer, "_vision_page_text", side_effect=[LONG_TASK_TEXT, LONG_KEY_TEXT]), \
				patch.object(importer, "_verified_raster_answer", return_value=None), \
				patch.object(importer, "_resolve_extracted_task", side_effect=lambda task, path: task), \
				patch.object(importer, "_ai_json", side_effect=[plan, extraction]) as ai:
				title, tasks = importer._extract_trainer_with_ai(Path(handle.name), Path(tempfile.gettempdir()), candidate={"parsed_ok": False})
		self.assertEqual(title, "Trainer")
		self.assertEqual(tasks[0]["answer"], "2")
		self.assertIn("transcribed from scanned page images", ai.call_args_list[0].args[0])
		self.assertIn(LONG_TASK_TEXT, ai.call_args_list[1].args[1])
		bound = tasks[0]["source_regions"][0]
		self.assertEqual(bound["bbox"], (0.0, 0.0, 595.0, 842.0))
		self.assertEqual(bound["page_width"], 595.0)
		self.assertTrue(bound["text"].startswith("[1]"))

	def test_vision_payload_sends_image_parts_without_json_mode(self):
		settings = {"api_key": "test-key", "model": "glm-5.3-flash", "url": "https://zai.example/chat/completions"}
		messages = [{"role": "user", "content": [
			{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
			{"type": "text", "text": "Transcribe"},
		]}]
		with patch.object(importer.requests, "post", return_value=stream_response("transcription")) as request:
			text = importer._ai_chat(messages, settings, vision=True)
		self.assertEqual(text, "transcription")
		payload = request.call_args.kwargs["json"]
		self.assertEqual(payload["model"], "glm-5.3-flash")
		self.assertIs(payload["messages"], messages)
		self.assertNotIn("response_format", payload)
		self.assertNotIn("thinking", payload)
		self.assertNotIn("reasoning_effort", payload)

	def test_text_payload_keeps_the_audited_json_shape(self):
		settings = {"api_key": "test-key", "model": "glm-5.3", "url": "https://zai.example/chat/completions"}
		messages = [{"role": "system", "content": "system prompt"}, {"role": "user", "content": "user content"}]
		with patch.object(importer.requests, "post", return_value=stream_response("{}")) as request:
			importer._ai_chat(messages, settings)
		payload = request.call_args.kwargs["json"]
		self.assertEqual(payload["model"], "glm-5.3")
		self.assertEqual(payload["response_format"], {"type": "json_object"})
		self.assertEqual(payload["thinking"], {"type": "enabled"})
		self.assertEqual(payload["reasoning_effort"], "max")
		self.assertEqual(payload["messages"], messages)
		self.assertTrue(request.call_args.kwargs["stream"])

	def test_digitized_anchor_slice_locates_in_order_slices(self):
		text = "[1] First task words here\nMore lines follow\n[2] Second task begins now\nEnd words close it"
		self.assertEqual(importer._digitized_anchor_slice(text, "First task words", "More lines"), "First task words here\nMore lines")
		self.assertIsNone(importer._digitized_anchor_slice(text, "Missing anchor", "End words"))
		self.assertIsNone(importer._digitized_anchor_slice(text, "", "End words"))
		self.assertEqual(importer._digitized_anchor_slice(text, "Second task begins", "Second task begins"), "Second task begins")

	def test_anchor_slice_survives_markdown_marker_decoration(self):
		slice_text = importer._digitized_anchor_slice(
			MARKDOWN_DIGITIZED_PAGE,
			"[10] Выберите два исходных вещества",
			"Запишите номера выбранных ответов.",
		)
		self.assertIsNotNone(slice_text)
		self.assertIn("Выберите два исходных вещества", slice_text)
		# The slice keeps the original transcription characters for the safeguard.
		self.assertTrue(slice_text.startswith("10]"))
		importer._validate_printed_task_number({"number": 10, "source_number": 10}, {"kind": "task", "text": slice_text})
		with self.assertRaises(frappe.ValidationError):
			importer._validate_printed_task_number({"number": 11, "source_number": 11}, {"kind": "task", "text": slice_text})

	def test_anchor_slice_tolerates_decorated_option_and_closer(self):
		slice_text = importer._digitized_anchor_slice(
			MARKDOWN_DIGITIZED_PAGE,
			"[11] Выберите два исходных вещества",
			"4) Al Запишите номера выбранных ответов.",
		)
		self.assertIsNotNone(slice_text)
		self.assertIn("**Al**", slice_text)

	def test_anchor_slice_normalises_letter_case_and_yo(self):
		text = "[3] Выберите два исходных вещества, сокращённое уравнение\n6) стирол"
		slice_text = importer._digitized_anchor_slice(text, "[3] ВЫБЕРИТЕ ДВА исходных вещества", "6) стирол")
		self.assertIsNotNone(slice_text)
		self.assertIn("сокращённое", slice_text)

	def test_anchor_slice_rejects_reordered_or_absent_anchor_words(self):
		# Strict safety: tolerance never invents locations for absent fragments
		# or accepts words quoted out of their printed order.
		self.assertIsNone(importer._digitized_anchor_slice(
			MARKDOWN_DIGITIZED_PAGE, "[12] Выберите два исходных вещества", "Запишите номера выбранных ответов."))
		self.assertIsNone(importer._digitized_anchor_slice(
			MARKDOWN_DIGITIZED_PAGE, "вещества исходных два Выберите [10]", "Запишите номера выбранных ответов."))
		self.assertIsNone(importer._digitized_anchor_slice(
			MARKDOWN_DIGITIZED_PAGE, "Запишите номера выбранных ответов.", "[10] Выберите два исходных вещества"))

	def test_bind_digitized_regions_locates_markdown_decorated_anchors(self):
		opened = make_opened_pdf(["🐾"])
		task = {"number": 10, "source_regions": [
			{"page_number": 1, "start": "[10] Выберите два исходных вещества", "end": "Запишите номера выбранных ответов.", "kind": "task"},
		]}
		with patch.object(importer.pdfplumber, "open", return_value=opened):
			importer._bind_digitized_regions(task, Path("scan.pdf"), {1: MARKDOWN_DIGITIZED_PAGE})
		bound = task["source_regions"][0]
		self.assertEqual(bound["bbox"], (0.0, 0.0, 595.0, 842.0))
		self.assertTrue(bound["text"].startswith("10]"))
		importer._validate_printed_task_number({"number": 10, "source_number": 10}, bound)

	def test_bind_digitized_regions_crops_the_whole_page_and_keeps_the_slice(self):
		opened = make_opened_pdf(["🐾"])
		task = {"number": 1, "source_regions": [{"page_number": 1, "start": "[1] First words of task", "end": "Last words of task", "kind": "task"}]}
		with patch.object(importer.pdfplumber, "open", return_value=opened):
			importer._bind_digitized_regions(task, Path("scan.pdf"), {1: LONG_TASK_TEXT})
		bound = task["source_regions"][0]
		self.assertEqual(bound["bbox"], (0.0, 0.0, 595.0, 842.0))
		self.assertEqual(bound["page_height"], 842.0)
		self.assertTrue(bound["text"].startswith("[1]"))
		self.assertTrue(bound["text"].endswith("Last words of task"))
		# The printed-number safeguard still applies to digitized slices.
		importer._validate_printed_task_number({"number": 1, "source_number": 1}, bound)
		with self.assertRaises(frappe.ValidationError):
			importer._validate_printed_task_number({"number": 2, "source_number": 2}, bound)

	def test_bind_digitized_regions_leaves_text_pages_and_bbox_regions_alone(self):
		opened = make_opened_pdf(["🐾", "text page"])
		with_bbox = {"page_number": 1, "bbox": [1, 2, 3, 4], "kind": "task"}
		text_page = {"page_number": 2, "start": "anchor", "end": "anchor", "kind": "task"}
		task = {"source_regions": [with_bbox, text_page]}
		with patch.object(importer.pdfplumber, "open", return_value=opened):
			importer._bind_digitized_regions(task, Path("scan.pdf"), {1: LONG_TASK_TEXT})
		self.assertIs(task["source_regions"][0], with_bbox)
		self.assertEqual(task["source_regions"][1], text_page)

	def test_bind_digitized_regions_rejects_unlocatable_anchors(self):
		opened = make_opened_pdf(["🐾"])
		task = {"source_regions": [{"page_number": 1, "start": "not present", "end": "not present", "kind": "task"}]}
		with patch.object(importer.pdfplumber, "open", return_value=opened):
			with self.assertRaises(frappe.ValidationError):
				importer._bind_digitized_regions(task, Path("scan.pdf"), {1: LONG_TASK_TEXT})
