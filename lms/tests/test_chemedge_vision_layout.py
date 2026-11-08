"""Vision-anchored crop layouts for digitized scans (task 44 fix round 2).

Reproduces the owner-observed mis-cuts (Telegram #1702, 2026-11-08: «все
задания нарезаны неправильно»): transcription-line arithmetic drifts whenever
the model's line structure does not match the rendered page. The layout
anchors cut between real ink rows instead, fall back to the arithmetic with
a visible warning when untrustworthy, and a fallback crop that fails the
vision sanity check fails the import cause-named. Fixtures are synthetic;
the private source PDF is never copied.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import frappe
from lms.lms import chemedge_pdf_import as importer

# Synthetic page: 500x700 pt rendered at 1000x1400 px (exactly 0.5 pt/px).
# Ink rows are where the page really prints its content; the transcription
# below deliberately carries a DIFFERENT line count, so transcription-line
# arithmetic would cut elsewhere — the anchored band must follow the ink.
PAGE_WIDTH, PAGE_HEIGHT = 500.0, 700.0
WIDTH_PX, HEIGHT_PX = 1000, 1400

INK_ROWS = [
	[40, 70, 80, 900],        # shared page header
	[100, 130, 60, 940],      # [6] marker line
	[140, 170, 60, 930],      # stem, wrapped to a second printed line
	[220, 250, 60, 500],      # option rows 1) .. 6)
	[260, 290, 60, 520],
	[300, 330, 60, 480],
	[340, 370, 60, 540],
	[380, 410, 60, 500],
	[420, 450, 60, 560],
	[460, 490, 60, 700],      # closing instruction
	[500, 530, 60, 500],      # printed answer cells (terminal row)
	[560, 590, 60, 940],      # [7] marker line
	[600, 630, 60, 930],      # stem
	[640, 670, 60, 940],      # options on one printed row
	[680, 710, 60, 700],      # closing instruction
	[1340, 1370, 400, 600],   # page footer
]

# The transcription's own line structure (20 lines, marker [6] on line 0,
# [7] on line 10) maps task 6 to a band of (0, 362) pt by even line
# distribution — visibly different from the ink-anchored truth.
DIGITIZED_PAGE = "\n".join([
	"[6] Выберите два исходных вещества, взаимодействию которых соответствует",
	"сокращённое ионное уравнение реакции",
	"1) Сероводород",
	"2) Хлорид цинка",
	"3) Нитрат бария",
	"4) Гидроксид цинка",
	"5) Оксид серы",
	"6) Сульфит натрия",
	"Запишите номера выбранных ответов.",
	"□ □",
	"[7] Выберите два исходных вещества для иного уравнения",
	"1) Cu 2) Fe 3) Zn 4) Mg 5) Ba 6) Al",
	"Запишите номера выбранных ответов.",
	"строка четырнадцать",
	"строка пятнадцать",
	"строка шестнадцать",
	"строка семнадцать",
	"строка восемнадцать",
	"строка девятнадцать",
	"строка двадцать",
])

RAW_ANCHORS = [
	{"number": 6, "top": 100 / HEIGHT_PX, "x0": 0.06},
	{"number": 7, "top": 560 / HEIGHT_PX, "x0": 0.06},
]

# Anchor band expectations (pt): task 6 runs from its marker row (100 px)
# down to the printed answer cells (530 px); task 7 stops before the page
# footer at the block's closing whitespace gap.
BAND_6 = (0.0, 100 * 0.5 - importer.LAYOUT_ANCHOR_PAD_PT, 500.0, (530 + importer.LAYOUT_ANCHOR_PAD_PT / 0.5) * 0.5)
BAND_7 = (0.0, 560 * 0.5 - importer.LAYOUT_ANCHOR_PAD_PT, 500.0, (710 + importer.LAYOUT_ANCHOR_PAD_PT / 0.5) * 0.5)


class _FakeBox:
	def __init__(self, bbox):
		self._bbox = bbox

	def getbbox(self):
		return self._bbox


class FakeInkImage:
	"""PIL-like image with precomputed ink rows (no PIL needed to test)."""

	def __init__(self, rows, size=(WIDTH_PX, HEIGHT_PX)):
		self._rows = [tuple(row) for row in rows]
		self.size = tuple(size)

	def convert(self, mode):
		return self

	def point(self, table):
		return self

	def close(self):
		pass

	def save(self, buffer, **kwargs):
		buffer.write(b"fake-render-bytes")

	def crop(self, box):
		left, upper, _right, lower = box
		spans = [row for row in self._rows if row[0] < lower and row[1] > upper]
		if not spans:
			return _FakeBox(None)
		return _FakeBox((
			max(0, min(row[2] for row in spans) - left),
			max(0, min(row[0] for row in spans) - upper),
			max(row[3] for row in spans) - left,
			min(lower - upper, max(row[1] for row in spans) - upper),
		))


def make_opened_pdf(width=PAGE_WIDTH, height=PAGE_HEIGHT, count=1):
	pages = []
	for _ in range(count):
		page = Mock()
		page.width, page.height = width, height
		pages.append(page)
	pdf = Mock()
	pdf.pages = pages
	opened = MagicMock()
	opened.__enter__.return_value = pdf
	return opened


def task_region(number, start, end, kind="task"):
	return {"page_number": 1, "start": start, "end": end, "kind": kind}


class VisionLayoutTestCase(unittest.TestCase):
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

	def warnings(self):
		return [str(call.args[0]) for call in self.progress.call_args_list]

	def layout(self, raw=RAW_ANCHORS, rows=INK_ROWS, text=DIGITIZED_PAGE):
		return importer._validated_page_layout(raw, rows, text, PAGE_WIDTH, PAGE_HEIGHT, WIDTH_PX, HEIGHT_PX)

	def bind(self, number, start, end, layout, kind="task", text=DIGITIZED_PAGE):
		task = {"number": number, "source_number": number, "source_regions": [task_region(number, start, end, kind)]}
		with patch.object(importer.pdfplumber, "open", return_value=make_opened_pdf()):
			importer._bind_digitized_regions(task, Path("scan.pdf"), {1: text}, {1: layout} if layout is not None else {1: None})
		return task["source_regions"][0]

	# --- ink rows and layout validation ----------------------------------

	def test_page_ink_rows_finds_printed_row_bands(self):
		rows = importer._page_ink_rows(FakeInkImage([[10, 20, 5, 90], [21, 30, 7, 88], [100, 110, 5, 60]]))
		# Rows one pixel apart merge; a real gap separates printed lines.
		self.assertEqual(rows, [[10, 30, 5, 90], [100, 110, 5, 60]])

	def test_valid_layout_snaps_anchors_to_real_ink_rows(self):
		layout = self.layout(raw=[
			{"number": 6, "top": 118 / HEIGHT_PX, "x0": 0.06},  # inside the marker line's ink
			{"number": 7, "top": 560 / HEIGHT_PX, "x0": 0.06},
		])
		self.assertIsNotNone(layout)
		anchors = {anchor["number"]: anchor["row_top"] for column in layout["columns"] for anchor in column["anchors"]}
		self.assertEqual(anchors, {6: 100, 7: 560})
		self.assertTrue(importer._is_page_layout(layout))

	def test_layout_missing_a_printed_number_is_rejected(self):
		self.assertIsNone(self.layout(raw=[{"number": 6, "top": 0.08, "x0": 0.06}]))

	def test_layout_with_out_of_order_numbers_is_rejected(self):
		self.assertIsNone(self.layout(raw=[
			{"number": 6, "top": 560 / HEIGHT_PX, "x0": 0.06},
			{"number": 7, "top": 100 / HEIGHT_PX, "x0": 0.06},
		]))

	def test_anchor_floating_in_whitespace_drops_the_layout(self):
		self.assertIsNone(self.layout(raw=[
			{"number": 6, "top": 100 / HEIGHT_PX, "x0": 0.06},
			{"number": 7, "top": 1000 / HEIGHT_PX, "x0": 0.06},  # no ink row nearby
		]))

	def test_garbage_anchor_payloads_are_rejected(self):
		self.assertIsNone(self.layout(raw=[{"number": "6", "top": 0.1}]))
		self.assertIsNone(self.layout(raw=[{"number": 6, "top": 1.4}]))
		self.assertIsNone(self.layout(raw=[{"number": 6, "top": 0.08}, {"number": 6, "top": 0.4}]))
		self.assertIsNone(self.layout(raw="not a list"))
		self.assertIsNone(importer._validated_page_layout(RAW_ANCHORS, [], DIGITIZED_PAGE, PAGE_WIDTH, PAGE_HEIGHT, WIDTH_PX, HEIGHT_PX))

	# --- anchored bands follow the page, not the transcription ------------

	def test_task_band_is_cut_between_real_ink_rows(self):
		bound = self.bind(6, "[6] Выберите два исходных вещества", "Запишите номера выбранных ответов.", self.layout())
		self.assertEqual(bound["band_source"], "layout")
		self.assertEqual(tuple(round(value, 4) for value in bound["bbox"]), tuple(round(value, 4) for value in BAND_6))
		# The transcription's own arithmetic would have cut elsewhere.
		line_height = PAGE_HEIGHT / 20
		self.assertNotAlmostEqual(bound["bbox"][3], 10 * line_height + 12.0)

	def test_final_task_stops_at_its_block_gap_before_the_footer(self):
		bound = self.bind(7, "[7] Выберите два исходных вещества", "Запишите номера выбранных ответов.", self.layout())
		self.assertEqual(bound["band_source"], "layout")
		self.assertEqual(tuple(round(value, 4) for value in bound["bbox"]), tuple(round(value, 4) for value in BAND_7))
		self.assertLess(bound["bbox"][3], 1340 * 0.5)  # the page footer stays out

	def test_unusable_layout_falls_back_to_transcription_lines(self):
		bound = self.bind(6, "[6] Выберите два исходных вещества", "Запишите номера выбранных ответов.", None)
		self.assertEqual(bound["band_source"], "transcription-lines")
		line_height = PAGE_HEIGHT / 20
		self.assertAlmostEqual(bound["bbox"][1], 0.0, places=4)
		self.assertAlmostEqual(bound["bbox"][3], 10 * line_height + 12.0, places=4)

	def test_context_regions_keep_the_transcription_band(self):
		bound = self.bind(6, "Выберите два исходных вещества", "ионное уравнение", self.layout(), kind="context")
		self.assertEqual(bound["band_source"], "transcription-lines")

	# --- two-column pages respect the column boundary ---------------------

	def test_two_column_bands_stay_inside_their_own_column(self):
		rows = [
			[200, 230, 90, 740], [240, 270, 90, 700],   # task 1 (left)
			[520, 550, 90, 740], [560, 590, 90, 720],   # task 2 (left)
			[200, 230, 830, 1480], [240, 270, 830, 1440],  # task 3 (right)
			[520, 550, 830, 1480], [560, 590, 830, 1460],  # task 4 (right)
		]
		raw = [
			{"number": 1, "top": 200 / 1350, "x0": 90 / 1950},
			{"number": 2, "top": 520 / 1350, "x0": 90 / 1950},
			{"number": 3, "top": 200 / 1350, "x0": 830 / 1950},
			{"number": 4, "top": 520 / 1350, "x0": 830 / 1950},
		]
		text = "[1] Левое задание\n[2] Второе левое\n[3] Правое задание\n[4] Второе правое"
		layout = importer._validated_page_layout(raw, rows, text, 780.0, 540.0, 1950, 1350)
		self.assertIsNotNone(layout)
		self.assertEqual(len(layout["columns"]), 2)
		text_page = "\n".join([
			"[1] Левое задание одно", "условие", "1) A 2) B", "Запишите номера выбранных ответов.",
			"[2] Второе левое задание", "условие", "1) C 2) D", "Запишите номера выбранных ответов.",
		])
		task2 = {"number": 2, "source_number": 2, "source_regions": [task_region(2, "[2] Второе левое", "Запишите номера выбранных ответов.")]}
		task3 = {"number": 3, "source_number": 3, "source_regions": [task_region(3, "[3] Правое задание", "Запишите номера выбранных ответов.")]}
		text_right = "\n".join([
			"[3] Правое задание одно", "условие", "1) E 2) F", "Запишите номера выбранных ответов.",
			"[4] Второе правое задание", "условие", "1) G 2) H", "Запишите номера выбранных ответов.",
		])
		opened = make_opened_pdf(width=780.0, height=540.0)
		with patch.object(importer.pdfplumber, "open", return_value=opened):
			importer._bind_digitized_regions(task2, Path("scan.pdf"), {1: text_page}, {1: layout})
			importer._bind_digitized_regions(task3, Path("scan.pdf"), {1: text_right}, {1: layout})
		left = task2["source_regions"][0]["bbox"]
		right = task3["source_regions"][0]["bbox"]
		# The boundary lands inside the ink-free corridor between the columns
		# (740..830 px = 296..332 pt), so each crop keeps only its own column:
		# the left band ends before the right column's ink, and the right band
		# starts after the left column's ink (padding may overlap the empty
		# corridor, never printed content).
		self.assertLess(740 * 0.4, right[0])
		self.assertLess(left[2], 830 * 0.4)
		self.assertEqual(left[0], 0.0)
		self.assertEqual(round(right[2], 4), 780.0)

	# --- layout fetch: vision outage and garbage fall back with a warning --

	def page_layouts_for(self, raw, render_rows=INK_ROWS):
		"""Fetch layouts with a controlled vision payload (a list means "always return this")."""
		if isinstance(raw, list):
			side = lambda *args, **kwargs: raw  # noqa: E731
		else:
			side = raw
		opened = make_opened_pdf()
		with patch.object(importer.pdfplumber, "open", return_value=opened), \
			patch.object(importer, "_page_render", return_value=FakeInkImage(render_rows)), \
			patch.object(importer, "_vision_page_layout", side_effect=side) as vision:
			layouts = importer._digitized_page_layouts(Path("scan.pdf"), {1: DIGITIZED_PAGE}, "prefix")
			cached_call_count = vision.call_count
			again = importer._digitized_page_layouts(Path("scan.pdf"), {1: DIGITIZED_PAGE}, "prefix")
		return layouts, again, cached_call_count

	def test_digitized_page_layouts_build_and_cache_a_valid_layout(self):
		layouts, again, calls = self.page_layouts_for(RAW_ANCHORS)
		self.assertEqual(calls, 1)
		self.assertIsNotNone(layouts[1])
		self.assertEqual(again, layouts)  # checkpointed: no new vision calls
		self.assertFalse(any("fall back to transcription line estimates" in message for message in self.warnings()))

	def test_vision_outage_falls_back_with_a_visible_warning(self):
		layouts, again, calls = self.page_layouts_for(importer.AIUnavailable("provider 500"))
		self.assertEqual(calls, 1)
		self.assertEqual(layouts, {1: None})
		self.assertEqual(again, {1: None})
		self.assertTrue(any("fall back to transcription line estimates" in message and "vision unavailable" in message for message in self.warnings()))

	def test_garbage_layout_falls_back_with_a_visible_warning(self):
		layouts, _again, _calls = self.page_layouts_for([{"number": 6, "top": 0.08}])
		self.assertEqual(layouts, {1: None})
		self.assertTrue(any("did not match the printed page" in message for message in self.warnings()))

	def test_revalidation_after_redigitize_drops_a_stale_layout(self):
		layout = self.layout()
		page_layouts = {1: layout}
		importer._revalidate_page_layouts(page_layouts, {1: DIGITIZED_PAGE.replace("[7]", "[12]")}, [1])
		self.assertIsNone(page_layouts[1])
		self.assertTrue(any("re-digitized transcription" in message for message in self.warnings()))
		fresh = {1: layout}
		importer._revalidate_page_layouts(fresh, {1: "[6] Только первое задание"}, [1])
		self.assertIs(fresh[1], layout)  # a subset of markers keeps the anchors

	# --- anchored bands are exempt from the arithmetic expectation ---------

	def test_anchored_bands_do_not_trip_the_transcription_height_check(self):
		task = {
			"number": 6, "source_number": 6, "options": ["A", "B"], "correct_options": [1],
			"source_regions": [{"kind": "task", "page_number": 1, "text": DIGITIZED_PAGE, "bbox": BAND_6, "page_height": PAGE_HEIGHT, "band_source": "layout"}],
		}
		self.assertEqual(importer._transcription_validation_violations({6: task}, {1: DIGITIZED_PAGE}), {})
		del task["source_regions"][0]["band_source"]
		violations = importer._transcription_validation_violations({6: task}, {1: DIGITIZED_PAGE})
		self.assertIn(6, violations)
		self.assertIn("does not cover the transcribed task block", violations[6])

	# --- fallback crops get the vision sanity check ------------------------

	def crop_task(self, band_source):
		return {
			"number": 6, "source_number": 6,
			"source_regions": [{"kind": "task", "page_number": 1, "text": "[6] задание", "bbox": (0, 0, 500, 300), "band_source": band_source}],
		}

	def test_negative_crop_verdict_fails_cause_named(self):
		with tempfile.NamedTemporaryFile(suffix=".png") as handle:
			handle.write(b"crop-bytes")
			handle.flush()
			with patch.object(importer, "_vision_crop_verdict", return_value=(False, "the last option row is cut off")) as verdict:
				with self.assertRaises(importer.AIExtractionInvalid) as raised:
					importer._verify_unanchored_digitized_crops([self.crop_task("transcription-lines")], {6: Path(handle.name)})
		verdict.assert_called_once()
		message = str(raised.exception)
		self.assertIn("[6]", message)
		self.assertIn("last option row is cut off", message)
		self.assertIn("Nothing was imported", message)

	def test_clean_crop_verdict_and_anchored_crops_are_not_verified(self):
		with tempfile.NamedTemporaryFile(suffix=".png") as handle:
			handle.write(b"crop-bytes")
			handle.flush()
			with patch.object(importer, "_vision_crop_verdict", return_value=(True, "")) as verdict:
				importer._verify_unanchored_digitized_crops([self.crop_task("transcription-lines")], {6: Path(handle.name)})
				importer._verify_unanchored_digitized_crops([self.crop_task("layout")], {6: Path(handle.name)})
		self.assertEqual(verdict.call_count, 1)

	def test_verification_outage_warns_but_never_guesses(self):
		with tempfile.NamedTemporaryFile(suffix=".png") as handle:
			handle.write(b"crop-bytes")
			handle.flush()
			with patch.object(importer, "_vision_crop_verdict", side_effect=importer.AIUnavailable("offline")):
				importer._verify_unanchored_digitized_crops([self.crop_task("transcription-lines")], {6: Path(handle.name)})
		self.assertTrue(any("could not be verified" in message for message in self.warnings()))

	# --- end to end: the drain binds anchored bands -------------------------

	def test_drain_binds_anchored_bands_without_a_repair_round(self):
		opened = make_opened_pdf()
		entry = {"number": 6, "question_pages": [1], "context_pages": [], "answer_pages": [1]}
		extraction = {"tasks": [{"number": 6, "reviewed": True,
			"question": "Выберите два исходных вещества, взаимодействию которых соответствует сокращённое ионное уравнение реакции",
			"answer": "16", "options": ["Сероводород", "Хлорид цинка", "Нитрат бария", "Гидроксид цинка", "Оксид серы", "Сульфит натрия"],
			"correct_options": [1, 6],
			"source_regions": [{"page": 1, "start": "[6] Выберите два исходных вещества", "end": "Запишите номера выбранных ответов.", "kind": "task"}]}]}
		layout = self.layout()
		with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
			handle.write(b"%PDF-fake")
			handle.flush()
			with patch.object(importer.pdfplumber, "open", return_value=opened), \
				patch.object(importer, "_verified_raster_answer", return_value=None), \
				patch.object(importer, "_resolve_extracted_task", side_effect=lambda task, path: task), \
				patch.object(importer, "_ai_json", return_value=extraction) as ai:
				_title, tasks = importer._extract_page_plan_tasks(
					Path(handle.name), ["--- PDF page 1 ---\n" + DIGITIZED_PAGE], [entry], {}, {}, "",
					"prefix", {"title": "Trainer"}, {1: DIGITIZED_PAGE}, {1: layout})
		self.assertEqual(ai.call_count, 1)  # the arithmetic mismatch must not trigger a repair
		bound = tasks[0]["source_regions"][0]
		self.assertEqual(bound["band_source"], "layout")
		self.assertEqual(tuple(round(value, 4) for value in bound["bbox"]), tuple(round(value, 4) for value in BAND_6))
		self.assertFalse(any("fall back to transcription line estimates" in message for message in self.warnings()))
