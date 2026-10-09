# Copyright (c) 2026, Contributors
# See license.txt

"""Pure parameter checks for the Chemedge import's show_answers flag.

The flag rides through import_pdf_trainer into _create_quiz's quiz fields;
these tests pin that hand-off without the heavy PDF/integration path.
"""

import inspect
import unittest
from unittest import mock

import frappe

from lms.lms.chemedge_pdf_import import (
	_create_quiz,
	_parse_show_answers,
	import_pdf_trainer,
)


class TestParseShowAnswers(unittest.TestCase):
	def test_falsy_values_stay_off(self):
		for value in [False, 0, None, "", "  ", "0", "false", "off", "no"]:
			with self.subTest(value=value):
				self.assertIs(_parse_show_answers(value), False)

	def test_truthy_values_switch_on(self):
		for value in [True, 1, "1", " true ", "ON", "Yes"]:
			with self.subTest(value=value):
				self.assertIs(_parse_show_answers(value), True)


class TestCreateQuizShowAnswers(unittest.TestCase):
	"""_create_quiz must put the caller's flag into the quiz fields, not a
	hard-coded 0."""

	def _created_show_answers(self, show_answers) -> int:
		captured = {}

		def fake_get_doc(fields):
			captured.update(fields)
			return mock.MagicMock(name="quiz")

		with (
			mock.patch(
				"lms.lms.chemedge_pdf_import._unique_quiz_title",
				side_effect=lambda title: title,
			),
			mock.patch.object(frappe, "get_doc", side_effect=fake_get_doc),
		):
			_create_quiz({"header": "Trainer 2026"}, None, None, show_answers)
		return captured["show_answers"]

	def test_default_keeps_show_answers_off(self):
		self.assertEqual(self._created_show_answers(False), 0)

	def test_enabled_flag_is_written_as_one(self):
		self.assertEqual(self._created_show_answers(True), 1)

	def test_string_forms_are_coerced(self):
		self.assertEqual(self._created_show_answers("1"), 1)
		self.assertEqual(self._created_show_answers("0"), 0)

	def test_backward_compatible_default(self):
		# Old callers pass three arguments; they must keep show_answers off.
		captured = {}

		def fake_get_doc(fields):
			captured.update(fields)
			return mock.MagicMock(name="quiz")

		with (
			mock.patch(
				"lms.lms.chemedge_pdf_import._unique_quiz_title",
				side_effect=lambda title: title,
			),
			mock.patch.object(frappe, "get_doc", side_effect=fake_get_doc),
		):
			_create_quiz({"header": "Trainer 2026"})
		self.assertEqual(captured["show_answers"], 0)


class TestImportPdfTrainerShowAnswersSignature(unittest.TestCase):
	def test_whitelisted_method_accepts_show_answers(self):
		parameter = inspect.signature(import_pdf_trainer).parameters.get("show_answers")
		self.assertIsNotNone(parameter)
		self.assertIs(parameter.default, False)
		self.assertEqual(parameter.kind, inspect.Parameter.POSITIONAL_OR_KEYWORD)


if __name__ == "__main__":
	unittest.main()
