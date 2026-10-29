import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lms.lms.chemedge_pdf_import import (
	AIExtractionInvalid,
	_bind_regions_to_page_plan,
	_next_task_heading_top,
	_prepare_trainer,
	_resolve_source_region,
)


class TestAIPageScope(unittest.TestCase):
	def setUp(self):
		translation = patch("lms.lms.chemedge_pdf_import._", side_effect=lambda text: text)
		translation.start()
		self.addCleanup(translation.stop)
		self.pages = ["unrelated page", "Determine which two substances react. Record the selected numbers.", "Answer table on another page"]
		self.region = {"page_number": 1, "start": "Determine which two", "end": "the selected numbers.", "kind": "task"}

	def test_repairs_subset_numbering_from_unique_anchors_on_planned_pages(self):
		regions = _bind_regions_to_page_plan([self.region], self.pages, {2, 3})
		self.assertEqual(regions[0]["page_number"], 2)
		self.assertEqual(self.region["page_number"], 1)

	def test_repairs_page_number_with_short_numbered_choice_ending(self):
		pages = ["unrelated page", "[2] Установите соответствие между формулой и названием вещества. 6) стирол", "answer table"]
		region = {"page_number": 1, "start": "[2] Установите соответствие между формулой", "end": "6) стирол", "kind": "task"}
		regions = _bind_regions_to_page_plan([region], pages, {2, 3})
		self.assertEqual(regions[0]["page_number"], 2)

	def test_does_not_accept_matching_text_on_an_unplanned_page(self):
		with self.assertRaises(AIExtractionInvalid):
			_bind_regions_to_page_plan([self.region], self.pages, {3})

	def test_rejects_ambiguous_page_matches(self):
		with self.assertRaises(AIExtractionInvalid):
			_bind_regions_to_page_plan([self.region], [*self.pages, self.pages[1]], {2, 4})

	def test_preserves_valid_absolute_page_numbers(self):
		region = {**self.region, "page_number": 2}
		self.assertEqual(_bind_regions_to_page_plan([region], self.pages, {2}), [region])

	def test_numbered_choices_do_not_truncate_the_question(self):
		page = SimpleNamespace(extract_text_lines=lambda **kwargs: [
			{"text": "4) бензол", "top": 150},
			{"text": "6) стирол", "top": 180},
			{"text": "3. Следующее задание", "top": 250},
		])
		with patch("lms.lms.chemedge_pdf_import.find_stepenin_task_headings", return_value=[]):
			self.assertEqual(_next_task_heading_top(page, 100), 250)

	def test_invalid_ai_scope_falls_back_to_recognised_parser(self):
		candidate = {"parsed_ok": True, "title": "Trainer", "tasks": [{"number": 1}]}
		with patch("lms.lms.chemedge_pdf_import._extract_trainer_with_ai", side_effect=AIExtractionInvalid("wrong page")), patch("lms.lms.chemedge_pdf_import._validate_ai_tasks", return_value=("Trainer", [{"number": 1}])), patch("lms.lms.pdf_trainer_jobs.report_progress"):
			title, tasks, used_ai, warning = _prepare_trainer(Path("test.pdf"), Path("."), None, "", candidate)
		self.assertFalse(used_ai)
		self.assertEqual((title, tasks), ("Trainer", [{"number": 1}]))
		self.assertIn("standard parser", warning)

	def test_invalid_ai_scope_without_parser_result_is_not_silently_accepted(self):
		with patch("lms.lms.chemedge_pdf_import._extract_trainer_with_ai", side_effect=AIExtractionInvalid("wrong page")):
			with self.assertRaises(AIExtractionInvalid):
				_prepare_trainer(Path("test.pdf"), Path("."), None, "", {"parsed_ok": False})

	def test_crop_keeps_nearby_diagrams_without_crossing_whitespace_to_footer_ad(self):
		nearby = {"top": 180, "bottom": 240, "x0": 50, "x1": 400}
		advert = {"top": 600, "bottom": 740, "x0": 0, "x1": 600}
		page = SimpleNamespace(width=600, height=800, images=[nearby, advert], rects=[], curves=[],
			chars=[{"top": 100, "bottom": 170, "x0": 50, "x1": 550}],
			crop=Mock(return_value=SimpleNamespace(extract_text=lambda: "question and diagram")))
		with patch("lms.lms.chemedge_pdf_import._find_source_anchor", side_effect=[(100, 110), (160, 170)]), patch("lms.lms.chemedge_pdf_import.find_stepenin_task_headings", return_value=[]):
			region = _resolve_source_region(SimpleNamespace(pages=[page]), {"page_number": 1, "start": "question start words", "end": "question end words", "kind": "task"})
		self.assertEqual(region["bbox"][3], 244)
