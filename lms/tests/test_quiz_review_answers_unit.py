"""Fixture-free answer-key tests; run without a Frappe site or database.

Load the review functions from the production source with Frappe's I/O mocked.
Integration tests should additionally exercise document permissions on a site.
"""

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


class Row(dict):
	__getattr__ = dict.get


class TestQuizReviewAnswers(unittest.TestCase):
	def setUp(self):
		self.frappe = SimpleNamespace(
			session=SimpleNamespace(user="student"),
			db=Mock(),
			get_roles=Mock(return_value=["LMS Student"]),
			get_all=Mock(return_value=[]),
			get_doc=Mock(),
			PermissionError=PermissionError,
			ValidationError=ValueError,
			throw=lambda message, error: self.raise_error(message, error),
		)
		self.frappe.db.get_value.return_value = Row(owner="teacher", course=None)
		self.doc = SimpleNamespace(
			quiz="quiz", result=[Row(question_name="q1"), Row(question_name="q2")],
			check_permission=Mock(),
		)
		self.frappe.get_doc.return_value = self.doc
		self.course_access = Mock(return_value=False)
		self.batch_access = Mock(return_value=False)
		path = Path(__file__).parents[1] / "lms/doctype/lms_quiz/lms_quiz.py"
		tree = ast.parse(path.read_text())
		functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
			and node.name in {"_can_review_submission", "get_submission_correct_answers"}]
		self.assertEqual(len(functions), 2)
		for function in functions:
			function.decorator_list = []
		self.ns = {
			"frappe": self.frappe, "_": lambda text: text,
			"can_modify_course": self.course_access, "can_modify_batch": self.batch_access,
			"QUESTION_OPTION_FIELDS": [f"option_{i}" for i in range(1, 11)],
			"QUESTION_CORRECTNESS_FIELDS": [f"is_correct_{i}" for i in range(1, 11)],
			"QUESTION_POSSIBILITY_FIELDS": [f"possibility_{i}" for i in range(1, 11)],
		}
		exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), self.ns)

	@staticmethod
	def raise_error(message, error):
		raise error(message)

	def review(self):
		return self.ns["get_submission_correct_answers"]("submission")

	def test_student_cannot_read_keys_even_for_own_submission(self):
		with self.assertRaises(PermissionError):
			self.review()
		self.assertFalse(any(call.args[0] == "LMS Question"
			for call in self.frappe.get_all.call_args_list))

	def test_guest_and_unrelated_instructor_are_denied(self):
		for user, roles in [("Guest", []), ("other-teacher", ["Course Creator"])]:
			with self.subTest(user=user):
				self.frappe.session.user = user
				self.frappe.get_roles.return_value = roles
				with self.assertRaises(PermissionError):
					self.review()

	def test_author_admin_and_moderator_can_review(self):
		for user, roles in [("teacher", []), ("admin", ["System Manager"]), ("mod", ["Moderator"])]:
			with self.subTest(user=user):
				self.frappe.session.user = user
				self.frappe.get_roles.return_value = roles
				self.assertEqual(self.review(), {})
		self.assertEqual(self.doc.check_permission.call_count, 3)

	def test_course_lesson_and_batch_instructors_can_review(self):
		self.frappe.db.get_value.return_value = Row(owner="teacher", course="course")
		self.course_access.return_value = True
		self.assertTrue(self.ns["_can_review_submission"]("quiz"))
		self.frappe.db.get_value.return_value = Row(owner="teacher", course=None)
		self.frappe.get_all.side_effect = lambda doctype, **kw: ["course"] if doctype == "Course Lesson" else []
		self.assertTrue(self.ns["_can_review_submission"]("quiz"))
		self.course_access.return_value = False
		self.batch_access.return_value = True
		self.frappe.get_all.side_effect = lambda doctype, **kw: ["batch"] if doctype == "LMS Assessment" else []
		self.assertTrue(self.ns["_can_review_submission"]("quiz"))

	def test_document_permission_denial_stops_answer_lookup(self):
		self.frappe.session.user = "teacher"
		self.doc.check_permission.side_effect = PermissionError("No read permission")
		with self.assertRaises(PermissionError):
			self.review()
		self.frappe.get_all.assert_not_called()

	def test_keys_include_all_ten_fields_and_exclude_wrong_options(self):
		self.frappe.session.user = "teacher"
		self.doc.result.append(Row(question_name="q3"))
		self.frappe.get_all.return_value = [
			Row(name="q1", type="User Input", possibility_1="12", possibility_10="21"),
			Row(name="q2", type="Choices", option_1="wrong", is_correct_1=0,
				option_2="right", is_correct_2=1, option_10="also right", is_correct_10=1),
			Row(name="q3", type="Open Ended"),
		]
		self.assertEqual(self.review(), {"q1": ["12", "21"], "q2": ["right", "also right"], "q3": []})
		self.assertEqual(self.frappe.get_all.call_args.kwargs["filters"], [["name", "in", ["q1", "q2", "q3"]]])


if __name__ == "__main__":
	unittest.main()
