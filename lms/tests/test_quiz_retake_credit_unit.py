"""Fixture-free retake-credit tests (#32); run without a Frappe site or database.

Load the credit functions from the production source with Frappe's I/O mocked,
the same contract test_quiz_review_answers_unit holds. Integration tests should
additionally exercise document permissions and the submit path on a site.
"""

import ast
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock


def cint(value):
	try:
		return int(value or 0)
	except (TypeError, ValueError):
		return 0


class Row(dict):
	__getattr__ = dict.get


class TestQuizRetakeCredit(unittest.TestCase):
	def setUp(self):
		self.frappe = SimpleNamespace(
			session=SimpleNamespace(user="learner@example.com"),
			db=Mock(),
			get_all=Mock(return_value=[]),
			whitelist=lambda fn: fn,
			PermissionError=PermissionError,
			ValidationError=ValueError,
			throw=lambda message, error: self.raise_error(message, error),
			_=lambda text: text,
		)
		# The permissions import inside get_quiz_credited_questions.
		self.permissions = ModuleType("lms.lms.permissions")
		self.permissions.can_access_quiz = Mock(return_value=True)
		for name in ("lms", "lms.lms", "lms.lms.permissions"):
			sys.modules.setdefault(name, ModuleType(name))
		sys.modules["lms.lms.permissions"] = self.permissions

		path = Path(__file__).parents[1] / "lms/doctype/lms_quiz/lms_quiz.py"
		tree = ast.parse(path.read_text())
		wanted = {
			"_quiz_question_rows",
			"_credited_question_rows",
			"merge_credited_results",
			"get_quiz_credited_questions",
		}
		functions = [
			node
			for node in tree.body
			if isinstance(node, ast.FunctionDef) and node.name in wanted
		]
		self.assertEqual(len(functions), len(wanted))
		for function in functions:
			function.decorator_list = []
		self.ns = {
			"frappe": self.frappe,
			"_": lambda text: text,
			"cint": cint,
		}
		exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), self.ns)

	@staticmethod
	def raise_error(message, error):
		raise error(message)

	def route_get_all(self, submissions, results, quiz_questions):
		"""frappe.get_all answers by doctype, in the order the code asks."""

		def get_all(doctype, **_kwargs):
			if doctype == "LMS Quiz Submission":
				return submissions
			if doctype == "LMS Quiz Result":
				return results
			if doctype == "LMS Quiz Question":
				return quiz_questions
			if doctype == "LMS Question":
				# Every referenced question stays live; pluck returns plain names.
				return [row.question for row in quiz_questions if row.question]
			raise AssertionError(f"unexpected doctype {doctype}")

		self.frappe.get_all.side_effect = get_all

	# The tables the merge reads: earlier submissions, their graded rows, and
	# the quiz's current question rows. q4 is credited on an earlier attempt
	# but no longer sits in the quiz.
	SUBMISSIONS = ["SUBM-1"]
	QUIZ_QUESTIONS = [
		Row(question="q1", question_detail="detail one", marks=2, type="Choices"),
		Row(question="q2", question_detail="detail two", marks=1, type="Choices"),
		Row(question="q3", question_detail="essay", marks=5, type="Open Ended"),
	]

	def tables(self):
		"""Load the two dicts the submit path itself builds, from the routed I/O."""
		self.route_get_all(self.SUBMISSIONS, self.credited_results(), self.QUIZ_QUESTIONS)
		quiz_questions = self.ns["_quiz_question_rows"]("quiz")
		credited = self.ns["_credited_question_rows"]("quiz", "learner@example.com")
		return quiz_questions, credited

	def credited_results(self):
		return [
			# q1 credited at full marks on an earlier attempt.
			Row(
				question_name="q1",
				question="old snapshot",
				answer="First option",
				marks=2,
				marks_out_of=2,
				question_type="Choices",
				is_correct=1,
			),
			# q2 wrong: never credited, free to re-answer.
			Row(
				question_name="q2",
				question="old snapshot",
				answer="Second option",
				marks=0,
				marks_out_of=1,
				question_type="Choices",
				is_correct=0,
			),
			# q3 partially graded: a retake may improve it.
			Row(
				question_name="q3",
				question="essay",
				answer="<p>An essay</p>",
				marks=2,
				marks_out_of=5,
				question_type="Open Ended",
				is_correct=0,
			),
			# q4 credited, but no longer in the quiz's rows above.
			Row(
				question_name="q4",
				question="old snapshot",
				answer="Whatever",
				marks=1,
				marks_out_of=1,
				question_type="Choices",
				is_correct=1,
			),
		]

	def test_merge_carries_credited_answers_at_current_marks(self):
		quiz_questions, credited = self.tables()
		results = [
			{
				"question_name": "q2",
				"question": "detail two",
				"question_type": "Choices",
				"answer": "First option",
				"marks": 1,
				"marks_out_of": 1,
				"is_correct": 1,
			},
			{
				"question_name": "q3",
				"question": "essay",
				"question_type": "Open Ended",
				"answer": "<p>A better essay</p>",
				"marks": 0,
				"marks_out_of": 5,
				"is_correct": 0,
			},
		]
		self.ns["merge_credited_results"](quiz_questions, credited, results)

		self.assertEqual([row["question_name"] for row in results], ["q2", "q3", "q1"])
		carried = results[2]
		self.assertEqual(carried["question_name"], "q1")
		self.assertEqual(carried["question"], "detail one")
		self.assertEqual(carried["answer"], "First option")
		self.assertEqual(carried["marks"], 2)
		self.assertEqual(carried["marks_out_of"], 2)
		self.assertEqual(carried["is_correct"], 1)
		# The never-credited and partial rows are untouched by the merge.
		self.assertEqual(results[0]["answer"], "First option")
		self.assertEqual(results[1]["marks"], 0)

	def test_merge_keeps_credit_a_stale_client_re_answers(self):
		quiz_questions, credited = self.tables()
		results = [
			{
				"question_name": "q1",
				"question": "detail one",
				"question_type": "Choices",
				"answer": "a wrong re-answer",
				"marks": 0,
				"marks_out_of": 2,
				"is_correct": 0,
			}
		]
		self.ns["merge_credited_results"](quiz_questions, credited, results)

		self.assertEqual(len(results), 1)
		# The credited verdict and the answer that earned it stand.
		self.assertEqual(results[0]["answer"], "First option")
		self.assertEqual(results[0]["marks"], 2)
		self.assertEqual(results[0]["is_correct"], 1)

	def test_merge_drops_credit_for_a_question_that_left_the_quiz(self):
		quiz_questions, credited = self.tables()
		results = []
		self.ns["merge_credited_results"](quiz_questions, credited, results)
		self.assertEqual(
			[row["question_name"] for row in results],
			["q1"],
		)

	def test_merge_without_earlier_credit_touches_nothing(self):
		self.route_get_all([], [], self.QUIZ_QUESTIONS)
		quiz_questions = self.ns["_quiz_question_rows"]("quiz")
		results = [
			{"question_name": "q2", "answer": "x", "marks": 0, "marks_out_of": 1}
		]
		self.ns["merge_credited_results"](quiz_questions, {}, results)
		self.assertEqual(len(results), 1)
		self.assertEqual(results[0]["answer"], "x")

	def test_full_mark_open_ended_grade_counts_as_credited(self):
		self.route_get_all(
			self.SUBMISSIONS,
			[
				Row(
					question_name="q3",
					question="essay",
					answer="<p>An essay</p>",
					marks=5,
					marks_out_of=5,
					question_type="Open Ended",
					is_correct=0,
				)
			],
			self.QUIZ_QUESTIONS,
		)
		credited = self.ns["_credited_question_rows"]("quiz", "learner@example.com")
		self.assertEqual(list(credited), ["q3"])

	def test_guest_has_no_credits(self):
		credited = self.ns["_credited_question_rows"]("quiz", "Guest")
		self.assertEqual(credited, {})
		self.frappe.get_all.assert_not_called()

	def test_endpoint_gates_on_quiz_access_and_returns_sorted_names(self):
		self.route_get_all(
			self.SUBMISSIONS, self.credited_results(), self.QUIZ_QUESTIONS
		)
		self.frappe.db.exists = Mock(return_value=True)

		names = self.ns["get_quiz_credited_questions"]("quiz")
		self.assertEqual(names, ["q1", "q4"])

		self.permissions.can_access_quiz = Mock(return_value=False)
		with self.assertRaises(PermissionError):
			self.ns["get_quiz_credited_questions"]("quiz")

	def test_endpoint_rejects_a_missing_quiz(self):
		self.frappe.db.exists = Mock(return_value=False)
		with self.assertRaises(ValueError):
			self.ns["get_quiz_credited_questions"]("nope")


if __name__ == "__main__":
	unittest.main()
