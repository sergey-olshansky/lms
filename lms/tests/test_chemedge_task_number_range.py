# Copyright (c) 2026, Contributors
# See license.txt

import inspect
import unittest

import frappe

from lms.lms.chemedge_pdf_import import (
	_quiz_title,
	apply_task_number_range,
	import_pdf_trainer,
)


def make_tasks(*numbers):
	"""Tasks in the extractor's shape; only 'number' matters for the range."""
	return [{"number": number, "id": f"id{number:06d}", "key": f"key-{number}"} for number in numbers]


class TestApplyTaskNumberRange(unittest.TestCase):
	def test_both_empty_keeps_full_task_list(self):
		tasks = make_tasks(1, 2, 3)
		for first, last in [(None, None), ("", ""), ("  ", "\t")]:
			with self.subTest(first=first, last=last):
				task_range, filtered = apply_task_number_range(first, last, tasks)
				self.assertIsNone(task_range)
				self.assertEqual(filtered, tasks)

	def test_filters_inclusively_and_keeps_order(self):
		tasks = make_tasks(1, 2, 3, 4, 5, 6, 7)
		task_range, filtered = apply_task_number_range(3, 5, tasks)
		self.assertEqual(task_range, (3, 5))
		self.assertEqual([task["number"] for task in filtered], [3, 4, 5])

	def test_range_bounds_are_included(self):
		tasks = make_tasks(1, 2, 3)
		_, filtered = apply_task_number_range("1", "3", tasks)
		self.assertEqual([task["number"] for task in filtered], [1, 2, 3])

	def test_single_task_range(self):
		tasks = make_tasks(1, 2, 3)
		task_range, filtered = apply_task_number_range(2, 2, tasks)
		self.assertEqual(task_range, (2, 2))
		self.assertEqual([task["number"] for task in filtered], [2])

	def test_numbering_gaps_inside_range_are_accepted(self):
		tasks = make_tasks(1, 2, 4, 5)
		_, filtered = apply_task_number_range(1, 5, tasks)
		self.assertEqual([task["number"] for task in filtered], [1, 2, 4, 5])

	def test_first_greater_than_last_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			apply_task_number_range(5, 3, make_tasks(1, 2, 3))

	def test_only_one_bound_is_rejected(self):
		tasks = make_tasks(1, 2, 3)
		with self.assertRaises(frappe.ValidationError):
			apply_task_number_range(2, None, tasks)
		with self.assertRaises(frappe.ValidationError):
			apply_task_number_range(None, 2, tasks)

	def test_non_integer_values_are_rejected(self):
		tasks = make_tasks(1, 2, 3)
		for value in ["abc", "2.5", 2.5, 0, 10000]:
			with self.subTest(value=value):
				with self.assertRaises(frappe.ValidationError):
					apply_task_number_range(value, value, tasks)

	def test_outside_numbers_range_reports_actual_range(self):
		tasks = make_tasks(1, 2, 3)
		with self.assertRaises(frappe.ValidationError) as ctx:
			apply_task_number_range(80, 90, tasks)
		message = str(ctx.exception)
		self.assertIn("80", message)
		self.assertIn("90", message)
		self.assertIn("1–3", message)
		self.assertIn("3 task(s)", message)

	def test_missing_bound_reports_actual_range(self):
		# 5 exists, 6 does not: the selection is not an existing range.
		tasks = make_tasks(1, 3, 5, 7)
		with self.assertRaises(frappe.ValidationError) as ctx:
			apply_task_number_range(5, 6, tasks)
		message = str(ctx.exception)
		self.assertIn("5–6", message)
		self.assertIn("1–7", message)

	def test_repeated_numbers_reject_range_selection(self):
		# Compiled PDFs restart numbering; a repeated number is ambiguous.
		tasks = make_tasks(1, 2, 3, 1, 2)
		with self.assertRaises(frappe.ValidationError) as ctx:
			apply_task_number_range(1, 2, tasks)
		self.assertIn("1, 2", str(ctx.exception))

	def test_repeated_numbers_still_allow_full_import(self):
		tasks = make_tasks(1, 2, 1, 2)
		task_range, filtered = apply_task_number_range(None, None, tasks)
		self.assertIsNone(task_range)
		self.assertEqual(filtered, tasks)


class TestQuizTitleTaskRangeSuffix(unittest.TestCase):
	def test_no_range_keeps_title_unchanged(self):
		meta = {"header": "Trainer 2026"}
		self.assertEqual(_quiz_title(meta, None), "Trainer 2026")
		self.assertEqual(_quiz_title(meta, "Folder / Sub"), "Folder / Sub · Trainer 2026")

	def test_range_appends_suffix(self):
		meta = {"header": "Trainer 2026"}
		self.assertEqual(
			_quiz_title(meta, None, (1, 30)),
			"Trainer 2026 · tasks 1–30",
		)
		self.assertEqual(
			_quiz_title(meta, "Folder", (5, 10)),
			"Folder · Trainer 2026 · tasks 5–10",
		)


class TestImportPdfTrainerSignature(unittest.TestCase):
	def test_whitelisted_method_accepts_task_number_range(self):
		parameters = inspect.signature(import_pdf_trainer).parameters
		for name in ("first_task_number", "last_task_number"):
			with self.subTest(parameter=name):
				self.assertIn(name, parameters)
				self.assertIsNone(parameters[name].default)
				self.assertEqual(parameters[name].kind, inspect.Parameter.POSITIONAL_OR_KEYWORD)


if __name__ == "__main__":
	unittest.main()
