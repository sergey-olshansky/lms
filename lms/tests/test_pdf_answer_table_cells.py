"""Regression checks for answer table cells with adjacent task and key text."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from lms.lms.pdf_task_bundle_extractor import find_answers


class TestPDFAnswerTableCells(unittest.TestCase):
	def test_combined_number_and_choice_key_uses_known_task_numbers(self):
		page = Mock()
		page.width = 595
		page.height = 842
		page.extract_words.return_value = [
			{"text": "103.12", "x0": 100, "x1": 140, "top": 100, "bottom": 112}
		]
		pdf = SimpleNamespace(pages=[page])

		answers = find_answers(pdf, 0, expected_numbers={103})

		self.assertEqual(answers[103]["text"], "12")

	def test_combined_decimal_is_not_a_task_answer_without_task_numbers(self):
		page = Mock()
		page.width = 595
		page.height = 842
		page.extract_words.return_value = [
			{"text": "103.12", "x0": 100, "x1": 140, "top": 100, "bottom": 112}
		]
		pdf = SimpleNamespace(pages=[page])

		self.assertEqual(find_answers(pdf, 0), {})


if __name__ == "__main__":
	unittest.main()
