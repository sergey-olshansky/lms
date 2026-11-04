"""Regression checks for two-column trainer pages and select-all answer keys.

Reproduces the «Полувариант 2. Органика» failure (task 40): a wide
slide-format page holds tasks [1]/[2] in the left column and [3]/[4] in the
right column, so one vertical band interleaves two tasks. The resolved region
must stay inside the task's own column, the printed task-number check must
read that column's own heading, and end anchors spanning a column's line wrap
must still be located. «Выберите все вещества» tasks repair their numbered
options from a concatenated digit key («15» → options 1 and 5).
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lms.lms.chemedge_pdf_import import (
	_find_source_anchor,
	_next_task_heading_top,
	_resolve_source_region,
	_task_column,
	_validate_ai_tasks,
	_validate_printed_task_number,
)


def block(text, top, bottom, x0, x1):
	"""A pdfplumber-like word/char item; blocks double as extractable text."""
	return {"text": text, "top": float(top), "bottom": float(bottom), "x0": float(x0), "x1": float(x1)}


RIGHT_COLUMN_TOP = "Из предложенного перечня выберите всевещества, из которых"


class TwoColumnPage:
	"""pdfplumber-like page mirroring the reported 780x540 slide layout.

	Left column (x 37-380): task [1] from y=80, task [2] from y=263.
	Right column (x 410-740): task [3] from y=80, task [4] from y=263.
	"""

	WIDTH = 780.0
	HEIGHT = 540.0

	CHARS = [
		block("[1]Установите соответствие между молекулярной формулой", 80, 92, 37, 380),
		block("и его тривиальным названием", 94, 106, 37, 250),
		block("А) C3H6 1) стирол", 130, 142, 65, 340),
		block("левый столбец продолжается ниже", 150, 162, 37, 300),
		block("[2]Из предложенного перечня выберите два", 263, 275, 37, 350),
		block("[3]Из предложенного перечня выберите всевещества", 80, 92, 410, 620),
		block("в одну стадию может быть получен алкин:", 100, 112, 432, 660),
		block("1) карбид кальция", 120, 132, 432, 540),
		block("2) 2,3-дибром-2,3-диметилбутан", 135, 147, 432, 600),
		block("3) бензол", 150, 162, 432, 500),
		block("4) этиленгликоль", 170, 182, 432, 540),
		block("5) хлорэтен", 185, 197, 432, 520),
		block("[4]Из предложенного перечня выберите два", 263, 275, 410, 740),
	]

	WORDS = [
		block("[1]Установите", 80, 92, 37, 100),
		block("соответствие", 80, 92, 104, 175),
		block("между", 80, 92, 178, 210),
		block("молекулярной", 80, 92, 213, 290),
		block("левый", 150, 162, 37, 65),
		block("столбец", 150, 162, 68, 115),
		block("[2]Из", 263, 275, 37, 57),
		block("[3]Из", 80, 92, 410, 440),
		block("предложенного", 80, 92, 441, 520),
		block("перечня", 80, 92, 523, 575),
		block("выберите", 80, 92, 578, 620),
		block("всевещества", 80, 92, 623, 700),
		block("из", 92, 104, 432, 450),
		block("которых", 92, 104, 453, 500),
		block("алкин:", 100, 112, 560, 600),
		block("4)", 170, 182, 432, 447),
		block("этиленгликоль", 170, 182, 450, 540),
		block("5)", 185, 197, 432, 447),
		block("хлорэтен", 185, 197, 450, 520),
		block("[4]Из", 263, 275, 410, 440),
	]

	LINES = [
		block("[1]Установите соответствие [3]Из предложенного перечня выберите", 80, 92, 37, 740),
		block("[2]Из предложенного перечня [4]Из предложенного перечня", 263, 275, 37, 745),
	]

	def __init__(self, right_column=True):
		self.width = self.WIDTH
		self.height = self.HEIGHT
		keep = (lambda item: True) if right_column else (lambda item: float(item["x0"]) < 395)
		self.chars = [item for item in self.CHARS if keep(item)]
		self.words = [item for item in self.WORDS if keep(item)]
		self.lines = [item for item in self.LINES if keep(item)]
		self.images = []
		self.rects = []
		self.curves = []

	def search(self, pattern, regex=True, case=True):
		# The physical lines merge both columns, so direct text search never
		# returns a unique hit; resolution goes through the word stream.
		return []

	def extract_words(self):
		return [dict(item) for item in self.words]

	def extract_text_lines(self, strip=True, return_chars=False):
		return [dict(item) for item in self.lines]

	def crop(self, bbox):
		x0, _, x1, _ = bbox
		inside = sorted(
			(item for item in self.chars if float(item["x0"]) >= x0 - 0.5 and float(item["x1"]) <= x1 + 0.5),
			key=lambda item: (item["top"], item["x0"]),
		)
		return SimpleNamespace(extract_text=lambda: "\n".join(item["text"] for item in inside))


class TestTwoColumnExtraction(unittest.TestCase):
	def setUp(self):
		translation = patch("lms.lms.chemedge_pdf_import._", side_effect=lambda text: text)
		translation.start()
		self.addCleanup(translation.stop)
		self.heading_patch = patch("lms.lms.chemedge_pdf_import.find_stepenin_task_headings", return_value=[])
		self.heading_patch.start()
		self.addCleanup(self.heading_patch.stop)

	def test_start_anchor_in_right_column_binds_the_task_column(self):
		page = TwoColumnPage()
		start = _find_source_anchor(page, RIGHT_COLUMN_TOP)
		column = _task_column(page, start)
		self.assertIsNotNone(column)
		self.assertGreaterEqual(column[0], 395)
		self.assertEqual(column[1], 780.0)

	def test_resolved_region_stays_inside_the_right_column(self):
		page = TwoColumnPage()
		region = {"page_number": 1, "start": RIGHT_COLUMN_TOP, "end": "5) хлорэтен", "kind": "task"}
		resolved = _resolve_source_region(SimpleNamespace(pages=[page]), region)
		self.assertGreaterEqual(resolved["bbox"][0], 395, "crop must exclude the left column")
		self.assertIn("[3]", resolved["text"])
		self.assertNotIn("[1]", resolved["text"])
		self.assertIn("5) хлорэтен", resolved["text"])
		_validate_printed_task_number({"number": 3, "source_number": 3}, resolved)

	def test_printed_task_number_check_rejects_a_different_task_number(self):
		page = TwoColumnPage()
		region = {"page_number": 1, "start": RIGHT_COLUMN_TOP, "end": "5) хлорэтен", "kind": "task"}
		resolved = _resolve_source_region(SimpleNamespace(pages=[page]), region)
		with self.assertRaises(Exception):
			_validate_printed_task_number({"number": 2, "source_number": 2}, resolved)

	def test_end_anchor_spanning_a_column_line_wrap_is_located(self):
		page = TwoColumnPage()
		start = _find_source_anchor(page, RIGHT_COLUMN_TOP)
		column = _task_column(page, start)
		end = _find_source_anchor(page, "4) этиленгликоль 5) хлорэтен", after=start[0], column=column)
		self.assertIsNotNone(end)
		self.assertGreaterEqual(end[2], 400, "the located option line must come from the task's column")

	def test_next_heading_limit_stays_inside_the_task_column(self):
		page = TwoColumnPage()
		start = _find_source_anchor(page, RIGHT_COLUMN_TOP)
		column = _task_column(page, start)
		limit = _next_task_heading_top(page, start[0], column=column)
		self.assertEqual(limit, 263.0, "task 4 in the same column bounds the region, not task 2")

	def test_single_column_page_keeps_the_full_width_crop(self):
		page = TwoColumnPage(right_column=False)
		region = {"page_number": 1, "start": "Установите соответствие между молекулярной", "end": "левый столбец", "kind": "task"}
		resolved = _resolve_source_region(SimpleNamespace(pages=[page]), region)
		self.assertLess(resolved["bbox"][0], 40)

	def test_select_all_question_repairs_numbered_options_from_the_digit_key(self):
		source_text = (
			"[3]Из предложенного перечня выберите всевещества, из которых\n"
			"в одну стадию может быть получен алкин:\n"
			"1) карбид кальция\n2) 2,3-дибром-2,3-диметилбутан\n3) бензол\n"
			"4) этиленгликоль\n5) хлорэтен"
		)
		candidate = {
			"tasks": [{"number": 3, "region_refs": ["body"]}],
			"regions": {"body": {"kind": "task", "page_number": 1, "text": source_text}},
		}
		result = {
			"title": "Trainer",
			"tasks": [{
				"number": 3, "reviewed": True,
				"question": "Из предложенного перечня выберите всевещества, из которых в одну стадию может быть получен алкин",
				"answer": "15",
				"options": [], "correct_options": [],
				"source_regions": [{"ref": "body"}],
			}],
		}
		_, tasks = _validate_ai_tasks(result, Path("trainer.pdf"), candidate)
		self.assertEqual(len(tasks[0]["options"]), 5)
		self.assertEqual(tasks[0]["correct_options"], [1, 5])
		self.assertFalse(any("все" in option for option in tasks[0]["options"]))


if __name__ == "__main__":
	unittest.main()
