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
			quiz="quiz",
			member="learner@example.com",
			result=[Row(question_name="q1"), Row(question_name="q2")],
			check_permission=Mock(),
		)
		self.frappe.get_doc.return_value = self.doc
		# The quiz's show_answers switch, as the owner branch reads it. Routed
		# per test through _route_quiz_get_value; the staff gate's [owner, course]
		# read keeps the setUp default.
		self.show_answers = 0
		self.course_access = Mock(return_value=False)
		self.batch_access = Mock(return_value=False)
		path = Path(__file__).parents[1] / "lms/doctype/lms_quiz/lms_quiz.py"
		tree = ast.parse(path.read_text())
		functions = [
			node
			for node in tree.body
			if isinstance(node, ast.FunctionDef)
			and node.name
			in {
				"_can_review_submission",
				"_submission_owner_may_view_answers",
				"get_submission_correct_answers",
				"_correct_answers_for_questions",
			}
		]
		self.assertEqual(len(functions), 4)
		for function in functions:
			function.decorator_list = []
		self.ns = {
			"frappe": self.frappe,
			"_": lambda text: text,
			"can_modify_course": self.course_access,
			"can_modify_batch": self.batch_access,
			"QUESTION_OPTION_FIELDS": [f"option_{i}" for i in range(1, 11)],
			"QUESTION_CORRECTNESS_FIELDS": [f"is_correct_{i}" for i in range(1, 11)],
			"QUESTION_POSSIBILITY_FIELDS": [f"possibility_{i}" for i in range(1, 11)],
		}
		exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), self.ns)

	@staticmethod
	def raise_error(message, error):
		raise error(message)

	def _route_quiz_get_value(self):
		"""Answer db.get_value by fieldname: the staff gate's [owner, course]
		read keeps its setUp default; the show_answers read follows the test."""

		def quiz_value(_doctype, _name, fieldname, **_kwargs):
			if isinstance(fieldname, (list, tuple)):
				return Row(owner="teacher", course=None)
			return self.show_answers

		self.frappe.db.get_value.side_effect = quiz_value

	def review(self):
		return self.ns["get_submission_correct_answers"]("submission")

	def test_student_cannot_read_keys_even_for_own_submission(self):
		with self.assertRaises(PermissionError):
			self.review()
		self.assertFalse(any(call.args[0] == "LMS Question" for call in self.frappe.get_all.call_args_list))

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
		self.frappe.get_all.side_effect = (
			lambda doctype, **kw: ["course"] if doctype == "Course Lesson" else []
		)
		self.assertTrue(self.ns["_can_review_submission"]("quiz"))
		self.course_access.return_value = False
		self.batch_access.return_value = True
		self.frappe.get_all.side_effect = (
			lambda doctype, **kw: ["batch"] if doctype == "LMS Assessment" else []
		)
		self.assertTrue(self.ns["_can_review_submission"]("quiz"))

	def test_document_permission_denial_stops_answer_lookup(self):
		self.frappe.session.user = "teacher"
		self.doc.check_permission.side_effect = PermissionError("No read permission")
		with self.assertRaises(PermissionError):
			self.review()
		self.frappe.get_all.assert_not_called()

	# --- Owner branch (#1088): the submission's owner may read the keys of
	# their own finished attempt exactly when the quiz's show_answers
	# checkbox is on. Nobody else's attempt, and no keys when it is off.

	def test_owner_reads_keys_when_quiz_shows_answers(self):
		self.frappe.session.user = "learner@example.com"
		self.show_answers = 1
		self._route_quiz_get_value()
		self.frappe.get_all.return_value = [
			Row(name="q1", type="Choices", option_1="right", is_correct_1=1),
			Row(name="q2", type="User Input", possibility_1="12"),
		]
		self.assertEqual(self.review(), {"q1": ["right"], "q2": ["12"]})
		# The owner still passes the document read gate, like every other path.
		self.doc.check_permission.assert_called_once()

	def test_owner_is_denied_when_quiz_hides_answers(self):
		self.frappe.session.user = "learner@example.com"
		self.show_answers = 0
		self._route_quiz_get_value()
		with self.assertRaises(PermissionError):
			self.review()
		self.assertFalse(
			any(call.args[0] == "LMS Question" for call in self.frappe.get_all.call_args_list)
		)

	def test_show_answers_does_not_unlock_another_learners_submission(self):
		self.frappe.session.user = "someone-else@example.com"
		self.show_answers = 1
		self._route_quiz_get_value()
		with self.assertRaises(PermissionError):
			self.review()
		self.assertFalse(
			any(call.args[0] == "LMS Question" for call in self.frappe.get_all.call_args_list)
		)

	def test_staff_keys_do_not_depend_on_show_answers(self):
		# The owner decision (#1088) widened the gate for the submission owner
		# only; the staff branch behaves exactly as before, whatever the quiz's
		# show_answers state.
		self.frappe.session.user = "teacher"
		self.show_answers = 0
		self._route_quiz_get_value()
		self.assertEqual(self.review(), {})
		self.doc.check_permission.assert_called_once()

	def test_keys_include_all_ten_fields_and_exclude_wrong_options(self):
		self.frappe.session.user = "teacher"
		self.doc.result.append(Row(question_name="q3"))
		self.frappe.get_all.return_value = [
			Row(name="q1", type="User Input", possibility_1="12", possibility_10="21"),
			Row(
				name="q2",
				type="Choices",
				option_1="wrong",
				is_correct_1=0,
				option_2="right",
				is_correct_2=1,
				option_10="also right",
				is_correct_10=1,
			),
			Row(name="q3", type="Open Ended"),
		]
		self.assertEqual(self.review(), {"q1": ["12", "21"], "q2": ["right", "also right"], "q3": []})
		self.assertEqual(
			self.frappe.get_all.call_args.kwargs["filters"], [["name", "in", ["q1", "q2", "q3"]]]
		)


if __name__ == "__main__":
	unittest.main()
