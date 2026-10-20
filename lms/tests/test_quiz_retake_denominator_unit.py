"""Fixture-free cumulative-denominator regression tests (#32); no site needed.

Drives the real ``submit_quiz`` path — processing, the retake merge, the
cumulative score_out_of, the submission's own scoring math — with Frappe's I/O
stubbed, the same contract the other quiz unit suites hold. The scoring itself
is the production ``validate_marks``/``set_percentage`` loaded from the
submission controller, so what these tests assert is the mark a site would
store.

The scenario the fixes answer: a shuffled quiz limited to a subset of its
questions. Retakes cover new questions while earlier credits ride along, so a
denominator pinned to the quiz's fixed total_marks can outscore 100%. Here it
must follow the union of unique credited questions and the attempt's offered
pool, and an offered-but-skipped question must keep its marks in that
denominator.
"""

import ast
import json
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


QUIZ_PATH = Path(__file__).parents[1] / "lms/doctype/lms_quiz/lms_quiz.py"
SUBMISSION_PATH = (
	Path(__file__).parents[1] / "lms/doctype/lms_quiz_submission/lms_quiz_submission.py"
)

# Six one-mark choice questions; the quiz draws three of them per attempt.
QUIZ_QUESTIONS = [
	Row(question=f"q{i}", question_detail=f"detail {i}", marks=1, type="Choices")
	for i in range(1, 7)
]


class QuizHarness(unittest.TestCase):
	"""One in-memory quiz site: submissions accumulate, instructors can grade."""

	maxDiff = None

	def setUp(self):
		self.submissions = []
		self.enqueued_emails = []
		self.quiz = Row(
			name="quiz-1",
			title="Limited shuffled quiz",
			total_marks=3,
			passing_percentage=50,
			lesson=None,
			course=None,
			enable_negative_marking=0,
			marks_to_cut=0,
			enable_proctoring=0,
			max_violations=0,
			enable_scheduling=0,
			schedule_start=None,
			schedule_end=None,
			limit_questions_to=3,
		)

		self.frappe = SimpleNamespace(
			session=SimpleNamespace(user="learner@example.com"),
			flags=SimpleNamespace(),
			conf={},
			local=SimpleNamespace(response={}),
			whitelist=lambda fn: fn,
			PermissionError=PermissionError,
			ValidationError=ValueError,
			log_error=Mock(),
			get_doc=Mock(),
			new_doc=Mock(side_effect=self._new_submission),
			db=Mock(),
			get_all=Mock(side_effect=self._get_all),
			throw=lambda message, error: (_ for _ in ()).throw(error(message)),
		)
		self.frappe.db.get_value = Mock(side_effect=self._db_get_value)
		self.frappe.db.count = Mock(return_value=0)

		# The lazy imports inside the loaded functions resolve here.
		permissions = ModuleType("lms.lms.permissions")
		permissions.can_access_quiz = Mock(return_value=True)
		schedule_utils = ModuleType("lms.lms.schedule_utils")
		schedule_utils.assert_within_schedule = lambda *a, **k: None
		schedule_utils.validate_schedule_fields = lambda *a, **k: None
		report = ModuleType("lms.lms.doctype.lms_quiz.quiz_attempt_report")
		report.enqueue_attempt_report_email = Mock(
			side_effect=lambda name: self.enqueued_emails.append(name)
		)
		html_utils = ModuleType("frappe.utils.html_utils")
		html_utils.sanitize_html = lambda value, **k: value
		for name, module in {
			"lms": ModuleType("lms"),
			"lms.lms": ModuleType("lms.lms"),
			"lms.lms.permissions": permissions,
			"lms.lms.schedule_utils": schedule_utils,
			"lms.lms.doctype": ModuleType("lms.lms.doctype"),
			"lms.lms.doctype.lms_quiz": ModuleType("lms.lms.doctype.lms_quiz"),
			"lms.lms.doctype.lms_quiz.quiz_attempt_report": report,
			"frappe.utils.html_utils": html_utils,
		}.items():
			sys.modules[name] = module

		self.ns = self._load_module(
			QUIZ_PATH,
			{
				"submit_quiz",
				"process_results",
				"_parse_json_arg",
				"_validate_quiz_results",
				"create_submission",
				"verify_answer",
				"get_question_details",
				"check_input_answers",
				"_build_proctoring_record",
				"_save_violation_events",
				"_attach_answer_files",
				"save_progress_after_quiz",
				"_quiz_question_rows",
				"_credited_question_rows",
				"merge_credited_results",
				"_parse_question_pool",
				"resolve_attempt_score_out_of",
			},
			{
				"QUESTION_OPTION_FIELDS": [f"option_{i}" for i in range(1, 11)],
				"QUESTION_CORRECTNESS_FIELDS": [f"is_correct_{i}" for i in range(1, 11)],
				"QUESTION_POSSIBILITY_FIELDS": [f"possibility_{i}" for i in range(1, 11)],
				"sanitize_html": lambda value, **k: value,
			},
		)

		# The submission's own scoring, from the controller: what a site stores.
		scoring = self._load_class_methods(
			SUBMISSION_PATH,
			"LMSQuizSubmission",
			{"validate_marks", "set_percentage"},
		)
		self.validate_marks = scoring["validate_marks"]
		self.set_percentage = scoring["set_percentage"]

	# --- module loading ----------------------------------------------------

	def _load_module(self, path, wanted, extra):
		tree = ast.parse(path.read_text())
		functions = [
			node
			for node in tree.body
			if isinstance(node, ast.FunctionDef) and node.name in wanted
		]
		self.assertEqual(len(functions), len(wanted), "every wanted function loaded")
		for function in functions:
			function.decorator_list = []
		ns = {
			"frappe": self.frappe,
			"_": lambda text: text,
			"cint": cint,
			"json": json,
			# Module-level imports of the source, bound here because AST
			# extraction carries only the functions.
			"assert_within_schedule": lambda *a, **k: None,
			"validate_schedule_fields": lambda *a, **k: None,
			"get_lesson_course": lambda lesson: None,
			"save_progress": Mock(),
			"SUBMISSION_REASONS": {"manual", "timer_expired", "max_violations", "browser_closed"},
			**extra,
		}
		exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), ns)
		return ns

	def _load_class_methods(self, path, class_name, wanted):
		tree = ast.parse(path.read_text())
		klass = next(
			node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
		)
		methods = [node for node in klass.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
		self.assertEqual(len(methods), len(wanted), "every wanted method loaded")
		ns = {
			"frappe": self.frappe,
			"_": lambda text: text,
			"cint": cint,
			"sanitize_rich_text": lambda value: value,
			"make_notification_logs": Mock(),
		}
		exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec"), ns)
		return ns

	# --- the in-memory site --------------------------------------------------

	def _new_submission(self, doctype):
		submission = FakeSubmission(self)
		self.submissions.append(submission)
		return submission

	def _get_all(self, doctype, filters=None, **_kwargs):
		if doctype == "LMS Quiz Submission":
			return [s.name for s in self.submissions]
		if doctype == "LMS Quiz Result":
			rows = []
			for submission in self.submissions:
				for row in submission.result:
					rows.append(Row(parent=submission.name, **row))
			return rows
		if doctype == "LMS Quiz Question":
			return QUIZ_QUESTIONS
		if doctype == "LMS Question":
			return [row.question for row in QUIZ_QUESTIONS]
		raise AssertionError(f"unexpected doctype {doctype}")

	def _db_get_value(self, doctype, filters=None, *args, **kwargs):
		if doctype == "LMS Quiz":
			return self.quiz
		if doctype == "LMS Quiz Question":
			name = filters["question"]
			return next(
				Row(
					question=name,
					question_detail=f"detail {name[1:]}",
					marks=1,
					type="Choices",
				)
				for row in QUIZ_QUESTIONS
				if row.question == name
			)
		if doctype == "LMS Question":
			# Every option list is one right answer and one wrong one; the
			# remaining slots exist (verify_answer subscripts all ten).
			fields = {"multiple": 0, "option_1": "Right", "is_correct_1": 1, "option_2": "Wrong", "is_correct_2": 0}
			for i in range(3, 11):
				fields[f"option_{i}"] = None
				fields[f"is_correct_{i}"] = None
			return Row(fields)
		raise AssertionError(f"unexpected doctype {doctype}")

	# --- the learner and the grader ------------------------------------------

	def submit(self, answers: dict, pool=None, raw_results=None):
		"""answers: {question: 'Right'|'Wrong'}; pool: the offered names;
		raw_results: hand-built rows, sent verbatim as a client would post them."""
		results = raw_results if raw_results is not None else [
			{"question_name": name, "answer": [answer]}
			for name, answer in answers.items()
		]
		kwargs = {
			"quiz": "quiz-1",
			"results": json.dumps(results),
		}
		if pool is not None:
			kwargs["question_pool"] = json.dumps(pool)
		return self.ns["submit_quiz"](**kwargs)

	def grade_full(self, index: int, question: str):
		"""An instructor awards full marks to a stored row."""
		for row in self.submissions[index].result:
			if row["question_name"] == question:
				row["marks"] = row["marks_out_of"]


class FakeSubmission:
	"""The shape create_submission drives, scored by the controller's math."""

	def __init__(self, harness):
		self.harness = harness
		self.name = f"SUBM-{len(harness.submissions) + 1}"
		self.result = []
		self.score = 0
		self.score_out_of = 0
		self.percentage = 0

	def update(self, values):
		for key, value in values.items():
			if key == "result":
				self.result = [row if isinstance(row, Row) else Row(**row) for row in value]
			else:
				setattr(self, key, value)

	def save(self, ignore_permissions=False):
		self.harness.validate_marks(self)
		self.harness.set_percentage(self)


class TestTwoRetakes(QuizHarness):
	def test_two_retakes_score_against_the_union_never_past_100(self):
		# Attempt 1: q1 right, q2 wrong, q3 offered and skipped.
		first = self.submit({"q1": "Right", "q2": "Wrong"}, pool=["q1", "q2", "q3"])
		self.assertEqual(first["score"], 1)
		self.assertEqual(first["score_out_of"], 3)
		self.assertEqual(first["pass"], False)
		self.assertAlmostEqual(first["percentage"], 100 / 3, places=5)

		# Attempt 2 (first retake): a fresh draw minus the credited q1; q4
		# right, q5 wrong, q6 offered and skipped; q1 rides along credited.
		second = self.submit({"q4": "Right", "q5": "Wrong"}, pool=["q4", "q5", "q6"])
		self.assertEqual(second["score"], 2)  # q4 + carried q1
		self.assertEqual(second["score_out_of"], 4)  # q1 + q4 + q5 + q6
		self.assertEqual(second["pass"], True)
		self.assertEqual(second["percentage"], 50)

		# Attempt 3 (second retake): q2 was never credited and comes back.
		third = self.submit({"q2": "Right", "q3": "Wrong"}, pool=["q2", "q3", "q5"])
		self.assertEqual(third["score"], 3)  # q2 + carried q1, q4
		self.assertEqual(third["score_out_of"], 5)  # q1, q4 + q2, q3, q5
		self.assertEqual(third["pass"], True)
		self.assertTrue(0 <= third["percentage"] <= 100)

		for attempt in (first, second, third):
			self.assertLessEqual(attempt["percentage"], 100)

		# History stays whole: each attempt its own document, earlier ones
		# untouched by the later submissions.
		self.assertEqual(
			[(row["question_name"], row["marks"]) for row in self.submissions[0].result],
			[("q1", 1), ("q2", 0)],
		)
		self.assertEqual(self.submissions[0].score, 1)
		self.assertEqual(self.submissions[0].score_out_of, 3)
		self.assertEqual(
			[(row["question_name"], row["marks"]) for row in self.submissions[1].result],
			[("q4", 1), ("q5", 0), ("q1", 1)],
		)
		self.assertEqual(self.submissions[1].score, 2)
		self.assertEqual(self.submissions[1].score_out_of, 4)

		# Every completion queues the teacher's report email (#34).
		self.assertEqual(self.enqueued_emails, ["SUBM-1", "SUBM-2", "SUBM-3"])

	def test_full_coverage_lands_exactly_on_100_not_beyond(self):
		# Three attempts together cover all six questions correctly; the last
		# one must read 6/6 = 100%, never 6/3 = 200%.
		self.submit({"q1": "Right", "q2": "Right", "q3": "Right"}, pool=["q1", "q2", "q3"])
		self.submit({"q4": "Right", "q5": "Right", "q6": "Right"}, pool=["q4", "q5", "q6"])
		final = self.submissions[1]
		self.assertEqual(final.score, 6)
		self.assertEqual(final.score_out_of, 6)
		self.assertEqual(final.percentage, 100)


class TestSkipAndDeclarationGuards(QuizHarness):
	def test_offered_but_skipped_questions_stay_in_the_denominator(self):
		# First attempt aces its draw; the retake answers one of its three
		# offered questions and skips the rest. The skipped pair keeps its
		# marks in the denominator, so the percentage cannot stay at 100%.
		self.submit({"q1": "Right", "q2": "Right", "q3": "Right"}, pool=["q1", "q2", "q3"])
		second = self.submit({"q4": "Right"}, pool=["q4", "q5", "q6"])
		self.assertEqual(second["score"], 4)  # q4 + the three carried credits
		self.assertEqual(second["score_out_of"], 6)  # every question now covered
		self.assertAlmostEqual(second["percentage"], 400 / 6, places=5)

	def test_a_shrunken_pool_declaration_widens_to_the_strict_reading(self):
		# A pool shorter than the quiz could have offered is not trusted: the
		# denominator falls back to every question the quiz currently asks.
		self.submit({"q1": "Right", "q2": "Right", "q3": "Right"}, pool=["q1", "q2", "q3"])
		second = self.submit({"q4": "Right"}, pool=["q4"])
		self.assertEqual(second["score"], 4)
		self.assertEqual(second["score_out_of"], 6)

	def test_an_undeclared_retake_also_gets_the_strict_reading(self):
		# No declaration (an older client, a beacon without state): the retake
		# cannot shrink its coverage by omission.
		self.submit({"q1": "Right", "q2": "Wrong"}, pool=["q1", "q2", "q3"])
		second = self.submit({"q4": "Right"})
		self.assertEqual(second["score"], 2)
		self.assertEqual(second["score_out_of"], 6)

	def test_a_first_attempt_without_a_declaration_keeps_the_quiz_total(self):
		# The legacy shape: nothing credited, nothing declared — the quiz's
		# total_marks has always been this attempt's coverage.
		first = self.submit({"q1": "Right", "q2": "Right"})
		self.assertEqual(first["score"], 2)
		self.assertEqual(first["score_out_of"], 3)


class TestDuplicateAnswerRows(QuizHarness):
	"""One question, one row: duplicates would grade twice against a
	denominator that counts the question once (#32)."""

	def test_rejects_a_duplicated_question_and_creates_no_submission(self):
		with self.assertRaises(ValueError):
			self.submit(
				{"q1": "Right", "q2": "Right"},
				pool=["q1", "q2"],
				raw_results=[
					{"question_name": "q1", "answer": ["Right"]},
					{"question_name": "q1", "answer": ["Right"]},
				],
			)
		# The attempt is refused whole: no submission, no score, no email.
		self.assertEqual(self.submissions, [])
		self.assertEqual(self.enqueued_emails, [])

	def test_rejects_a_duplicated_already_credited_question_on_a_retake(self):
		# q1 is credited by the first attempt; a retake that re-submits it
		# twice would carry the full-mark credit in two rows.
		self.submit({"q1": "Right"}, pool=["q1", "q2", "q3"])
		with self.assertRaises(ValueError):
			self.submit(
				{},
				pool=["q2", "q3", "q4"],
				raw_results=[
					{"question_name": "q1", "answer": ["Right"]},
					{"question_name": "q1", "answer": ["Wrong"]},
				],
			)
		self.assertEqual(len(self.submissions), 1)
		self.assertEqual(self.enqueued_emails, ["SUBM-1"])

	def test_a_non_string_question_name_is_rejected_rather_than_crashing(self):
		with self.assertRaises(ValueError):
			self.submit(
				{},
				pool=["q1"],
				raw_results=[{"question_name": {"q1": True}, "answer": ["Right"]}],
			)


class TestQuestionPoolParsing(QuizHarness):
	def test_parses_deduplicated_names_from_json(self):
		pool = self.ns["_parse_question_pool"](json.dumps(["q1", "q1", "q2"]))
		self.assertEqual(pool, ["q1", "q2"])

	def test_absent_declaration_is_none_and_garbage_is_rejected(self):
		self.assertIsNone(self.ns["_parse_question_pool"](None))
		with self.assertRaises(ValueError):
			self.ns["_parse_question_pool"](json.dumps(["q1", 5]))
		with self.assertRaises(ValueError):
			self.ns["_parse_question_pool"]("not json")


if __name__ == "__main__":
	unittest.main()
