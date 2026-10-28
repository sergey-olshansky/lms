import unittest
from pathlib import Path
from unittest.mock import patch

from lms.lms.chemedge_pdf_import import (
	AIExtractionInvalid,
	_bind_regions_to_page_plan,
	_prepare_trainer,
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

	def test_does_not_accept_matching_text_on_an_unplanned_page(self):
		with self.assertRaises(AIExtractionInvalid):
			_bind_regions_to_page_plan([self.region], self.pages, {3})

	def test_rejects_ambiguous_page_matches(self):
		with self.assertRaises(AIExtractionInvalid):
			_bind_regions_to_page_plan([self.region], [*self.pages, self.pages[1]], {2, 4})

	def test_preserves_valid_absolute_page_numbers(self):
		region = {**self.region, "page_number": 2}
		self.assertEqual(_bind_regions_to_page_plan([region], self.pages, {2}), [region])

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
