"""Quiz↔transcription consistency guards for vision-digitized imports.

Reproduces the three artifact classes of the production quiz 14 import
(2026-11-07, «Задание 14 ОГЭ.pdf») with mocked transcription outputs —
leaked printed option numbering, placeholder literals in question/alt, and
fragment bands that no longer cover the transcription's task block — plus
the clean happy path. Content is synthetic and only mirrors the observed
structure; the private source PDF is never copied.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import frappe
from lms.lms import chemedge_pdf_import as importer

# A digitized page shaped like the ОГЭ-14 scan: printed [N] markers, six
# printed options per task and the shared closing line.
OGE14_STYLE_PAGE = (
	"[6] Выберите два исходных вещества, взаимодействию которых в растворе соответствует\n"
	"сокращённое ионное уравнение реакции\n"
	"S²⁻ + 2H⁺ = H₂S\n"
	"1) Сероводород\n"
	"2) Хлорид цинка\n"
	"3) Нитрат бария\n"
	"4) Гидроксид цинка\n"
	"5) Оксид серы\n"
	"6) Сульфит натрия\n"
	"Запишите номера выбранных ответов.\n"
	"[7] Выберите два исходных вещества для иного уравнения\n"
	"1) Cu 2) Fe 3) Zn 4) Mg 5) Ba 6) Al\n"
	"Запишите номера выбранных ответов.\n"
)

# The drift shape: the extraction model's start anchor sits deep inside the
# block (five lines below its own printed marker), so the marker and the
# printed stem fall outside the produced fragment band — the class seen as
# cut-off tops and shifted boundaries on quiz 14.
DRIFTED_ANCHOR_PAGE = (
	"[10] Выберите два исходных вещества, взаимодействию которых соответствует\n"
	"сокращённое ионное уравнение реакции\n"
	"Ba²⁺ + SO₄²⁻ = BaSO₄\n"
	"первая дополнительная строка условия\n"
	"вторая дополнительная строка условия\n"
	"1) Нитрат бария\n"
	"2) Хлорид бария\n"
	"3) Сульфат натрия\n"
	"4) Сульфит калия\n"
	"5) Оксид бария\n"
	"6) Карбонат бария\n"
	"Запишите номера выбранных ответов.\n"
	"[11] Следующее задание с другим уравнением\n"
	"1) Cu 2) Fe 3) Zn 4) Mg 5) Ba 6) Al\n"
	"Запишите номера выбранных ответов.\n"
)

LEAKED_OPTIONS = [
	"1) Сероводород", "2) Хлорид цинка", "3) Нитрат бария",
	"4) Гидроксид цинка", "5) Оксид серы", "6) Сульфит натрия",
]
CLEAN_OPTIONS = [
	"Сероводород", "Хлорид цинка", "Нитрат бария",
	"Гидроксид цинка", "Оксид серы", "Сульфит натрия",
]


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


def extraction(number, question, options, correct_options, answer, start, end, page=1):
	return {"tasks": [{
		"number": number, "reviewed": True, "question": question, "answer": answer,
		"options": options, "correct_options": correct_options,
		"source_regions": [{"page": page, "start": start, "end": end, "kind": "task"}],
	}]}


class TranscriptionValidationTestCase(unittest.TestCase):
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
		from lms.lms.pdf_trainer_jobs import report_progress
		self.progress = report_progress

	def extract_page(self, page_text, responses, entries=None):
		"""Drive the digitized page-plan drain with mocked model responses."""
		opened = make_opened_pdf(["🐾"])
		entries = entries or [{"number": responses and int(responses[0]["tasks"][0]["number"]) or 6,
			"question_pages": [1], "context_pages": [], "answer_pages": [1]}]
		with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
			handle.write(b"%PDF-fake")
			handle.flush()
			with patch.object(importer.pdfplumber, "open", return_value=opened), \
				patch.object(importer, "_verified_raster_answer", return_value=None), \
				patch.object(importer, "_resolve_extracted_task", side_effect=lambda task, path: task), \
				patch.object(importer, "_ai_json", side_effect=responses) as ai:
				title, tasks = importer._extract_page_plan_tasks(
					Path(handle.name), ["--- PDF page 1 ---\n" + page_text], entries, {}, {}, "",
					"prefix", {"title": "Trainer"}, {1: page_text})
		return title, tasks, ai

	def transcription_warnings(self):
		return [str(call.args[0]) for call in self.progress.call_args_list
			if "does not match its page transcription" in str(call.args[0])]

	# --- unit level -------------------------------------------------------

	def test_option_prefix_is_stripped_only_when_it_duplicates_the_index(self):
		self.assertEqual(importer._strip_leaked_option_numbering(LEAKED_OPTIONS), CLEAN_OPTIONS)
		# A numbering that disagrees with the position stays untouched:
		# renumbering content would invent meaning.
		shifted = ["2) Оксид серы", "3) Сульфит натрия"]
		self.assertEqual(importer._strip_leaked_option_numbering(shifted), shifted)
		clean = ["Сероводород", "Хлорид цинка"]
		self.assertEqual(importer._strip_leaked_option_numbering(clean), clean)
		# Stripping must never empty an option text.
		self.assertEqual(importer._strip_leaked_option_numbering(["1) "]), ["1)"])

	def test_placeholder_literals_are_detected_case_insensitively(self):
		self.assertEqual(
			importer._placeholder_literals_in("среди dummy5) Li₂SO₃ и dummy6) H₂SiO₃", ""),
			["dummy5", "dummy6"],
		)
		self.assertEqual(importer._placeholder_literals_in("Чистый текст", "Сероводород"), [])
		self.assertEqual(importer._placeholder_literals_in("Dummy7 вариант"), ["dummy7"])

	def test_validate_ai_tasks_rejects_placeholder_texts(self):
		result = extraction(
			6, "Какое вещество соответствует уравнению dummy5) Li₂SO₃",
			["Li₂SO₃", "H₂SiO₃"], [1], "", "First words", "Last words",
		)
		with self.assertRaises(importer.AIExtractionInvalid) as raised:
			importer._validate_ai_tasks(result, Path("source.pdf"), {"tasks": []})
		self.assertIn("placeholder", str(raised.exception))
		self.assertIn("dummy5", str(raised.exception))
		result["tasks"][0]["options"] = ["dummy6) H₂SiO₃", "Li₂SO₃"]
		with self.assertRaises(importer.AIExtractionInvalid):
			importer._validate_ai_tasks(result, Path("source.pdf"), {"tasks": []})

	def test_transcription_validation_detects_option_count_and_band_drift(self):
		task_slice = OGE14_STYLE_PAGE[OGE14_STYLE_PAGE.index("[6]"):OGE14_STYLE_PAGE.index("[7]")]
		count_mismatch = {
			"number": 6, "source_number": 6, "options": CLEAN_OPTIONS[:4], "correct_options": [1, 4],
			"source_regions": [{"kind": "task", "page_number": 1, "text": task_slice, "bbox": (0.0, 0.0, 595.0, 659.7), "page_height": 842.0}],
		}
		violations = importer._transcription_validation_violations({6: count_mismatch}, {1: OGE14_STYLE_PAGE})
		self.assertIn(6, violations)
		self.assertIn("prints 6 answer options but 4 were extracted", violations[6])
		# The drifted band (start anchor five lines below the marker) misses
		# its own block by five transcribed lines.
		line_height = 842.0 / 15
		drifted_band = (0.0, 5 * line_height - 12.0, 595.0, 12 * line_height + 12.0)
		drifted = {
			"number": 10, "source_number": 10, "options": ["Нитрат бария", "Хлорид бария", "Сульфат натрия", "Сульфит калия", "Оксид бария", "Карбонат бария"], "correct_options": [1, 2],
			"source_regions": [{"kind": "task", "page_number": 1, "text": DRIFTED_ANCHOR_PAGE, "bbox": drifted_band, "page_height": 842.0}],
		}
		violations = importer._transcription_validation_violations({10: drifted}, {1: DRIFTED_ANCHOR_PAGE})
		self.assertIn(10, violations)
		self.assertIn("does not cover the transcribed task block", violations[10])

	def test_transcription_validation_skips_pages_without_block_structure(self):
		whole_page = {
			"number": 1, "source_number": 1, "options": ["A", "B"], "correct_options": [1],
			"source_regions": [{"kind": "task", "page_number": 1, "text": "[1] Question\n1) A\n2) B", "bbox": (0.0, 0.0, 595.0, 842.0), "page_height": 842.0}],
		}
		# A single-line transcription carries no block structure to expect.
		self.assertEqual(importer._transcription_validation_violations({1: whole_page}, {1: "[1] Question 1) A 2) B"}), {})
		# The last task on a page has no following marker: no bottom bound.
		last_task = {
			"number": 7, "source_number": 7, "options": ["Cu", "Fe", "Zn", "Mg", "Ba", "Al"], "correct_options": [1],
			"source_regions": [{"kind": "task", "page_number": 1, "text": "\n".join(OGE14_STYLE_PAGE.split("\n")[10:]), "bbox": (0.0, 700.0, 595.0, 842.0), "page_height": 842.0}],
		}
		self.assertEqual(importer._transcription_validation_violations({7: last_task}, {1: OGE14_STYLE_PAGE}), {})

	# --- the three artifact classes + happy path, mocked drain ------------

	def test_happy_path_import_matches_its_transcription(self):
		_title, tasks, ai = self.extract_page(OGE14_STYLE_PAGE, [extraction(
			6, "Выберите два исходных вещества, взаимодействию которых в растворе соответствует сокращённое ионное уравнение реакции",
			CLEAN_OPTIONS, [1, 6], "16", "[6] Выберите два исходных вещества", "Запишите номера выбранных ответов.",
		)])
		self.assertEqual(ai.call_count, 1)
		self.assertEqual(self.transcription_warnings(), [])
		self.assertEqual(len(tasks), 1)
		self.assertEqual(tasks[0]["options"], CLEAN_OPTIONS)
		band = tasks[0]["source_regions"][0]
		self.assertAlmostEqual(band["bbox"][1], 0.0, places=4)
		self.assertAlmostEqual(band["bbox"][3], 10 * (842.0 / 13) + 12.0, places=4)

	def test_leaked_printed_numbering_is_stripped_deterministically(self):
		_title, tasks, ai = self.extract_page(OGE14_STYLE_PAGE, [extraction(
			6, "Выберите два исходных вещества, взаимодействию которых в растворе соответствует сокращённое ионное уравнение реакции",
			LEAKED_OPTIONS, [1, 6], "16", "[6] Выберите два исходных вещества", "Запишите номера выбранных ответов.",
		)])
		# A deterministic strip, never a re-extraction.
		self.assertEqual(ai.call_count, 1)
		self.assertEqual(self.transcription_warnings(), [])
		self.assertEqual(tasks[0]["options"], CLEAN_OPTIONS)
		self.assertEqual(tasks[0]["correct_options"], [1, 6])

	def test_placeholder_question_is_retried_and_alt_stays_clean(self):
		bad = extraction(
			6, "Какое вещество соответствует уравнению dummy5) Li₂SO₃",
			CLEAN_OPTIONS, [1], "", "[6] Выберите два исходных вещества", "Запишите номера выбранных ответов.",
		)
		good = extraction(
			6, "Какое вещество соответствует уравнению",
			CLEAN_OPTIONS, [1], "", "[6] Выберите два исходных вещества", "Запишите номера выбранных ответов.",
		)
		_title, tasks, ai = self.extract_page(OGE14_STYLE_PAGE, [bad, good])
		self.assertEqual(ai.call_count, 2)
		self.assertIn("placeholder", ai.call_args_list[1].args[0])
		self.assertNotIn("dummy", tasks[0]["question"])
		html = importer._ai_question_html(tasks[0], "/files/chemedge-task-0006.png")
		self.assertIn("alt=", html)
		self.assertNotIn("dummy", html)

	def test_option_count_mismatch_is_recovered_by_one_reextraction(self):
		short = extraction(
			6, "Выберите два исходных вещества, взаимодействию которых в растворе соответствует сокращённое ионное уравнение реакции",
			CLEAN_OPTIONS[:4], [1, 4], "14", "[6] Выберите два исходных вещества", "Запишите номера выбранных ответов.",
		)
		full = extraction(
			6, "Выберите два исходных вещества, взаимодействию которых в растворе соответствует сокращённое ионное уравнение реакции",
			CLEAN_OPTIONS, [1, 6], "16", "[6] Выберите два исходных вещества", "Запишите номера выбранных ответов.",
		)
		_title, tasks, ai = self.extract_page(OGE14_STYLE_PAGE, [short, full])
		self.assertEqual(ai.call_count, 2)
		self.assertIn("prints 6 answer options but 4 were extracted", ai.call_args_list[1].args[0])
		self.assertEqual(len(self.transcription_warnings()), 1)
		self.assertEqual(tasks[0]["options"], CLEAN_OPTIONS)

	def test_drifted_fragment_band_is_recovered_by_one_reextraction(self):
		drifted = extraction(
			10, "Выберите два исходных вещества, взаимодействию которых соответствует сокращённое ионное уравнение реакции",
			["Нитрат бария", "Хлорид бария", "Сульфат натрия", "Сульфит калия", "Оксид бария", "Карбонат бария"], [1, 2], "12",
			"1) Нитрат бария", "Запишите номера выбранных ответов.",
		)
		repaired = extraction(
			10, "Выберите два исходных вещества, взаимодействию которых соответствует сокращённое ионное уравнение реакции",
			["Нитрат бария", "Хлорид бария", "Сульфат натрия", "Сульфит калия", "Оксид бария", "Карбонат бария"], [1, 2], "12",
			"[10] Выберите два исходных вещества", "Запишите номера выбранных ответов.",
		)
		_title, tasks, ai = self.extract_page(DRIFTED_ANCHOR_PAGE, [drifted, repaired])
		self.assertEqual(ai.call_count, 2)
		self.assertIn("does not cover the transcribed task block", ai.call_args_list[1].args[0])
		self.assertEqual(len(self.transcription_warnings()), 1)
		band = tasks[0]["source_regions"][0]
		# The repaired fragment covers the transcription's own task block
		# from its printed marker line, not from the first option row.
		self.assertAlmostEqual(band["bbox"][1], 0.0, places=4)
		self.assertAlmostEqual(band["bbox"][3], 12 * (842.0 / 15) + 12.0, places=4)
		self.assertTrue(band["text"].startswith("[10]"))

	def test_persistent_drift_fails_with_the_transcription_cause(self):
		drifted = extraction(
			10, "Выберите два исходных вещества, взаимодействию которых соответствует сокращённое ионное уравнение реакции",
			["Нитрат бария", "Хлорид бария", "Сульфат натрия", "Сульфит калия", "Оксид бария", "Карбонат бария"], [1, 2], "12",
			"1) Нитрат бария", "Запишите номера выбранных ответов.",
		)
		with self.assertRaises(importer.AIExtractionInvalid) as raised:
			self.extract_page(DRIFTED_ANCHOR_PAGE, [drifted, drifted])
		message = str(raised.exception)
		self.assertIn("did not match the digitized page transcription", message)
		self.assertIn("does not cover the transcribed task block", message)

	# --- final save-time hygiene gate --------------------------------------

	def import_tasks(self, tasks):
		upload = Mock()
		upload.get_full_path.return_value = "/tmp/scan.pdf"
		quiz = Mock()
		quiz.name = "QUIZ"
		quiz.title = "Trainer"
		saved = []

		def make_doc(data):
			if data.get("doctype") == "LMS Question":
				doc = Mock()
				doc.name = "Q1"
				doc.insert = Mock()
				saved.append(data)
				return doc
			return Mock()

		with patch.object(importer, "_require_import_permission"), \
			patch.object(importer, "_uploaded_pdf", return_value=upload), \
			patch.object(importer, "_template_candidate", return_value={}), \
			patch.object(importer, "_prepare_trainer", return_value=("Trainer", tasks, True, "")), \
			patch.object(importer, "_create_ai_task_crops", return_value={6: Path("crop.png")}), \
			patch.object(importer, "_create_answer_images", return_value={}), \
			patch.object(importer, "_create_quiz", return_value=quiz), \
			patch.object(importer, "_store_task_image", return_value=Mock(file_url="/files/crop.png", name="f1")), \
			patch.object(importer, "_attach_source_pdf"), \
			patch.object(importer, "_delete_files"), \
			patch.object(importer, "_delete_questions"), \
			patch.object(frappe.db, "exists", return_value=None), \
			patch.object(frappe, "delete_doc"), \
			patch.object(frappe, "get_doc", side_effect=make_doc):
			importer.import_pdf_trainer("uploaded-file")
		return saved

	def test_import_save_strips_digit_key_option_prefixes(self):
		digit_key_task = {
			"number": 6, "question": "Выберите два исходных вещества", "answer": "16",
			"options": list(LEAKED_OPTIONS), "correct_options": [1, 6], "source_regions": [],
		}
		saved = self.import_tasks([digit_key_task])
		self.assertEqual(len(saved), 1)
		self.assertEqual(saved[0]["option_1"], "Сероводород")
		self.assertEqual(saved[0]["option_6"], "Сульфит натрия")
		for index in range(1, 7):
			self.assertFalse(str(saved[0][f"option_{index}"]).startswith(f"{index}) "))
		self.assertEqual(saved[0]["type"], "Choices")
		self.assertEqual(saved[0]["is_correct_1"], 1)
		self.assertEqual(saved[0]["is_correct_6"], 1)

	def test_import_save_blocks_placeholder_texts(self):
		placeholder_task = {
			"number": 6, "question": "Какое вещество: dummy5) Li₂SO₃", "answer": "",
			"options": ["Li₂SO₃", "H₂SiO₃"], "correct_options": [1], "source_regions": [],
		}
		with self.assertRaises(frappe.ValidationError) as raised:
			self.import_tasks([placeholder_task])
		self.assertIn("placeholder", str(raised.exception))


if __name__ == "__main__":
	unittest.main()
