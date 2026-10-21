"""Fixture-free attempt-report tests (#33, #34); run without a Frappe site.

Load the report renderer and the completion email from the production source
with Frappe's I/O — and the PDF/mail transports — mocked. Nothing here builds
a real PDF or queues a real message; integration tests on a site should.
"""

import ast
import re
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

PATH = Path(__file__).parents[1] / "lms/doctype/lms_quiz/quiz_attempt_report.py"


def cint(value):
	try:
		return int(value or 0)
	except (TypeError, ValueError):
		return 0


class Row(dict):
	__getattr__ = dict.get


class TestQuizAttemptReport(unittest.TestCase):
	"""The shared fixtures every test in this file starts from."""

	maxDiff = None

	def setUp(self):
		self.get_pdf = Mock(return_value=b"%PDF-1.4 mocked")
		self.sendmail = Mock()
		self.log_error = Mock()
		self.enqueue = Mock()

		# The real imports inside the loaded functions resolve against these
		# stub modules, so no Frappe install is needed to run the logic.
		self.frappe = ModuleType("frappe")
		self.frappe.__path__ = []
		self.frappe._ = lambda text: text
		self.frappe.get_all = Mock(return_value=[])
		self.frappe.get_doc = Mock()
		self.frappe.get_cached_value = Mock(return_value=None)
		self.frappe.sendmail = self.sendmail
		self.frappe.log_error = self.log_error
		self.frappe.enqueue = self.enqueue
		self.frappe.bold = lambda text: f"<b>{text}</b>"
		self.frappe.conf = {}
		self.frappe.local = SimpleNamespace(response={})
		self.frappe.PermissionError = PermissionError
		self.frappe.ValidationError = ValueError
		self.frappe.throw = lambda message, error: (_ for _ in ()).throw(error(message))

		frappe_utils = ModuleType("frappe.utils")
		frappe_utils.cint = cint
		frappe_utils.get_url = Mock(return_value="https://lms.test")
		frappe_utils.format_datetime = lambda value, fmt: "04 Oct 2026 14:05"
		self.frappe.utils = frappe_utils
		frappe_utils_pdf = ModuleType("frappe.utils.pdf")
		frappe_utils_pdf.get_pdf = self.get_pdf

		html_sanitizer = ModuleType("lms.lms.html_sanitizer")
		html_sanitizer.sanitize_rich_text = lambda value: value
		lms_utils = ModuleType("lms.lms.utils")
		lms_utils.get_lms_route = lambda path="": f"/lms/{path}"
		lms_utils.get_readable_files = Mock(return_value={})
		self.lms_utils = lms_utils

		self.quiz_module = ModuleType("lms.lms.doctype.lms_quiz.lms_quiz")
		self.quiz_module._can_review_submission = Mock(return_value=True)
		self.quiz_module._correct_answers_for_questions = Mock(
			return_value={"q1": ["First option"]}
		)

		for name, module in {
			"frappe": self.frappe,
			"frappe.utils": frappe_utils,
			"frappe.utils.pdf": frappe_utils_pdf,
			"lms": ModuleType("lms"),
			"lms.lms": ModuleType("lms.lms"),
			"lms.lms.html_sanitizer": html_sanitizer,
			"lms.lms.utils": lms_utils,
			"lms.lms.doctype": ModuleType("lms.lms.doctype"),
			"lms.lms.doctype.lms_quiz": ModuleType("lms.lms.doctype.lms_quiz"),
			"lms.lms.doctype.lms_quiz.lms_quiz": self.quiz_module,
		}.items():
			sys.modules[name] = module

		tree = ast.parse(PATH.read_text())
		wanted = {
			"attempt_row_status",
			"_question_live_texts",
			"_quiz_teacher_recipients",
			"_absolute_asset_urls",
			"_inline_private_images",
			"render_attempt_report_html",
			"_report_pdf",
			"_attempt_report_filename",
			"download_attempt_report_pdf",
			"_email_transport_configured",
			"enqueue_attempt_report_email",
			"send_attempt_report_email",
		}
		functions = [
			node
			for node in tree.body
			if isinstance(node, ast.FunctionDef) and node.name in wanted
		]
		self.assertEqual(len(functions), len(wanted))
		for function in functions:
			function.decorator_list = []
		# The module-level table and pattern the loaded functions close over;
		# AST extraction carries only the functions, so their constants ride
		# along here, kept identical to the source by test_module_constants.
		relative_src = re.compile(r"""(src|href)=["'](?!https?://|data:|#)(/[^"']+)["']""")
		self.ns = {
			"frappe": self.frappe,
			"_": lambda text: text,
			"re": re,
			"_RELATIVE_SRC": relative_src,
			"_STATUS_LABELS": {
				"correct": "Correct",
				"incorrect": "Incorrect",
				"skipped": "Skipped",
				"pending": "Pending review",
			},
		}
		exec(compile(ast.Module(body=functions, type_ignores=[]), str(PATH), "exec"), self.ns)

	def submission_doc(self):
		return SimpleNamespace(
			name="SUBM-1",
			quiz="quiz-1",
			quiz_title="The Quiz",
			member="learner@example.com",
			member_name="Learner",
			score=1,
			score_out_of=3,
			percentage=33,
			violation_count=0,
			creation="2026-10-04 14:05:41.000000",
			result=[
				Row(
					question_name="q1",
					question="Stored snapshot",
					answer='Answer with <img src="/files/answer.png">',
					question_type="Choices",
					is_correct=1,
					marks=1,
					marks_out_of=1,
				),
				Row(
					question_name="q2",
					question="Essay prompt",
					answer="<p>An essay</p>",
					question_type="Open Ended",
					is_correct=0,
					marks=0,
					marks_out_of=2,
				),
				Row(
					question_name="q3",
					question="",
					answer="",
					question_type="Choices",
					is_correct=0,
					marks=0,
					marks_out_of=1,
				),
			],
		)

	def live_texts(self, rows=None):
		self.frappe.get_all = Mock(
			return_value=[
				Row(name="q1", question="<p>Live body one</p>"),
				Row(name="q2", question="Essay prompt"),
			]
		)


class TestAttemptRowStatus(TestQuizAttemptReport):
	def test_module_constants_stay_in_sync_with_the_source(self):
		"""The pattern and labels live at module level; if the source changes
		them, the copies in setUp must follow, or these tests stop testing the
		real renderer."""
		source = PATH.read_text()
		self.assertIn('_STATUS_LABELS = {', source)
		self.assertIn('"pending": "Pending review",', source)
		self.assertIn("_RELATIVE_SRC = re.compile(", source)

	def test_mirrors_the_report_truth_table(self):
		status = self.ns["attempt_row_status"]
		self.assertEqual(
			status(Row(question_type="Choices", answer="x", is_correct=1)), "correct"
		)
		self.assertEqual(
			status(Row(question_type="Choices", answer="x", is_correct=0)), "incorrect"
		)
		self.assertEqual(status(Row(question_type="Choices", answer="")), "skipped")
		self.assertEqual(
			status(Row(question_type="Open Ended", answer="<p>y</p>", marks=0, marks_out_of=2)),
			"pending",
		)
		# A full-mark grade — an instructor's or a retake's carried credit —
		# reads as correct, never as pending.
		self.assertEqual(
			status(Row(question_type="Open Ended", answer="<p>y</p>", marks=2, marks_out_of=2)),
			"correct",
		)
		self.assertEqual(
			status(Row(question_type="Open Ended", answer="<p>y</p>", marks=1, marks_out_of=2)),
			"pending",
		)


class TestRenderAttemptReportHtml(TestQuizAttemptReport):
	def test_prefers_live_question_text_and_marks_absolute_assets(self):
		self.live_texts()
		html = self.ns["render_attempt_report_html"](self.submission_doc(), correct_answers=None)
		self.assertIn("Live body one", html)
		self.assertNotIn("Stored snapshot", html)
		self.assertIn("src=\"https://lms.test/files/answer.png\"", html)
		# Skipped row out of the body, counted at the end; numbering keeps the
		# whole attempt's positions.
		self.assertIn("Q1:", html)
		self.assertIn("Q3", html)
		self.assertIn("1 skipped questions are not included in this report.", html)
		self.assertIn("Pending review", html)

	def test_inlines_authorized_private_question_images_for_pdf(self):
		self.live_texts()
		self.frappe.get_all = Mock(
			return_value=[
				Row(
					name="q1",
					question='<p><img src="/private/files/task.png" alt="Task"></p>',
				)
			]
		)
		file_doc = SimpleNamespace(
			file_name="task.png",
			get_content=Mock(return_value=b"png-bytes"),
		)
		self.lms_utils.get_readable_files.return_value = {
			"/private/files/task.png": file_doc
		}

		html = self.ns["render_attempt_report_html"](
			self.submission_doc(), correct_answers=None
		)

		self.assertIn("src=\"data:image/png;base64,cG5nLWJ5dGVz\"", html)
		self.assertNotIn("/private/files/task.png", html)
		self.lms_utils.get_readable_files.assert_called_once_with(
			["/private/files/task.png"]
		)

	def test_renders_the_key_block_only_when_keys_are_given(self):
		self.live_texts()
		doc = self.submission_doc()
		without_keys = self.ns["render_attempt_report_html"](doc, correct_answers=None)
		self.assertNotIn("Correct Answer:", without_keys)

		with_keys = self.ns["render_attempt_report_html"](
			doc, correct_answers={"q1": ["First option"]}
		)
		self.assertIn("Correct Answer:", with_keys)
		self.assertIn("First option", with_keys)

	def test_states_a_missing_question_body_rather_than_a_blank_line(self):
		doc = self.submission_doc()
		doc.result = [
			Row(question_name="gone", question="", answer="x", question_type="Choices", is_correct=1, marks=1, marks_out_of=1)
		]
		html = self.ns["render_attempt_report_html"](doc, correct_answers=None)
		self.assertIn("Question text is not available", html)

	def test_answers_every_empty_attempt_with_an_explicit_line(self):
		doc = self.submission_doc()
		doc.result = []
		html = self.ns["render_attempt_report_html"](doc, correct_answers=None)
		self.assertIn("No questions were answered in this attempt.", html)


class TestDownloadAttemptReportPdf(TestQuizAttemptReport):
	def test_builds_the_pdf_from_the_shared_renderer_with_keys(self):
		self.live_texts()
		doc = self.submission_doc()
		doc.check_permission = Mock()
		self.frappe.get_doc = Mock(return_value=doc)

		self.ns["download_attempt_report_pdf"]("SUBM-1")

		self.quiz_module._correct_answers_for_questions.assert_called_once_with(["q1", "q2", "q3"])
		html = self.get_pdf.call_args.args[0]
		self.assertIn("Live body one", html)
		self.assertIn("Correct Answer:", html)
		self.assertEqual(self.frappe.local.response["type"], "download")
		self.assertTrue(self.frappe.local.response["filename"].endswith(".pdf"))
		self.assertEqual(self.frappe.local.response["filecontent"], b"%PDF-1.4 mocked")

	def test_refuses_anyone_without_review_rights(self):
		doc = self.submission_doc()
		doc.check_permission = Mock()
		self.frappe.get_doc = Mock(return_value=doc)
		self.quiz_module._can_review_submission = Mock(return_value=False)

		with self.assertRaises(PermissionError):
			self.ns["download_attempt_report_pdf"]("SUBM-1")
		self.get_pdf.assert_not_called()


class TestAttemptReportEmail(TestQuizAttemptReport):
	def enable_transport(
		self,
		*,
		owner="owner@example.com",
		member="learner@example.com",
		lesson_courses=(),
		assessment_batches=(),
		instructors=(),
		enabled_emails=None,
	):
		"""Stand the site up: transport on, and the quiz placed exactly where
		the caller says — its owner, the courses whose lessons name it, the
		batches whose assessment plans run it, and the Course Instructor rows
		those parents carry. `instructors` is {(parent): [usernames]}.

		`enabled_emails` maps username → the email an enabled User carries
		(None or missing = the account cannot be mailed).
		"""
		self.frappe.get_cached_value = Mock(return_value="Outgoing")
		doc = self.submission_doc()
		doc.member = member
		self.frappe.get_doc = Mock(return_value=doc)
		self.frappe.db = Mock()
		self.frappe.db.get_value = Mock(return_value=owner)
		enabled_emails = enabled_emails if enabled_emails is not None else {
			"owner@example.com": "owner@example.com",
			member: f"{member}",
		}

		def get_all(doctype, filters=None, **_kwargs):
			if doctype == "Course Lesson":
				# pluck="course": plain names.
				return list(lesson_courses)
			if doctype == "LMS Assessment":
				# pluck="parent": plain batch names.
				return list(assessment_batches)
			if doctype == "Course Instructor":
				# pluck="instructor": plain usernames.
				names = []
				for parent in filters["parent"][1]:
					names.extend(instructors.get(parent, ()))
				return names
			if doctype == "User":
				# pluck="email": plain addresses of the enabled, mailed users.
				names = filters["name"][1]
				return [
					enabled_emails[name]
					for name in names
					if enabled_emails.get(name)
				]
			if doctype == "LMS Question":
				# The renderer's live-text lookup: empty means the report
				# falls back to the stored snapshots, as this suite always did.
				return []
			raise AssertionError(f"unexpected doctype {doctype}")

		self.frappe.get_all = Mock(side_effect=get_all)
		return doc

	def test_mails_the_author_when_the_quiz_stands_alone(self):
		self.enable_transport(owner="owner@example.com")

		self.ns["send_attempt_report_email"]("SUBM-1")
		self.sendmail.assert_called_once()
		kwargs = self.sendmail.call_args.kwargs
		self.assertEqual(kwargs["recipients"], ["owner@example.com"])
		self.assertEqual(len(kwargs["attachments"]), 1)
		self.assertEqual(kwargs["attachments"][0]["fcontent"], b"%PDF-1.4 mocked")
		self.assertIn("The Quiz", kwargs["subject"])
		html = self.get_pdf.call_args.args[0]
		self.assertIn("Correct Answer:", html)

	def test_mails_the_assigned_course_instructors_of_a_lesson_placed_quiz(self):
		self.enable_transport(
			owner="author@example.com",
			lesson_courses=["COURSE-1"],
			instructors={"COURSE-1": ["author@example.com", "instructor@example.com"]},
			enabled_emails={
				"author@example.com": "author@example.com",
				"instructor@example.com": "instructor@example.com",
			},
		)

		self.ns["send_attempt_report_email"]("SUBM-1")
		# The author is also the course's instructor: one mailbox, once.
		self.assertEqual(
			self.sendmail.call_args.kwargs["recipients"],
			["author@example.com", "instructor@example.com"],
		)

	def test_mails_the_assigned_evaluators_of_a_batch_run_quiz(self):
		self.enable_transport(
			owner="author@example.com",
			assessment_batches=["BATCH-1"],
			instructors={"BATCH-1": ["evaluator@example.com"]},
			enabled_emails={
				"author@example.com": "author@example.com",
				"evaluator@example.com": "evaluator@example.com",
			},
		)

		self.ns["send_attempt_report_email"]("SUBM-1")
		self.assertEqual(
			self.sendmail.call_args.kwargs["recipients"],
			["author@example.com", "evaluator@example.com"],
		)

	def test_drops_accounts_with_no_active_mailbox_and_sends_to_nobody_without_one(self):
		# The author's account is disabled and nobody is assigned to teach.
		self.enable_transport(
			owner="author@example.com",
			enabled_emails={},
		)
		self.ns["send_attempt_report_email"]("SUBM-1")
		self.sendmail.assert_not_called()

		# An assigned instructor whose account is disabled alone changes
		# nothing; a second, enabled one still receives the report.
		self.enable_transport(
			owner="author@example.com",
			lesson_courses=["COURSE-1"],
			instructors={"COURSE-1": ["gone@example.com", "instructor@example.com"]},
			enabled_emails={"instructor@example.com": "instructor@example.com"},
		)
		self.ns["send_attempt_report_email"]("SUBM-1")
		self.assertEqual(
			self.sendmail.call_args.kwargs["recipients"],
			["instructor@example.com"],
		)

	def test_never_mails_the_member_about_their_own_attempt(self):
		# The member is the course's instructor and the author: their own
		# attempt is a preview, and nobody else teaches this quiz.
		self.enable_transport(
			owner="learner@example.com",
			member="learner@example.com",
			lesson_courses=["COURSE-1"],
			instructors={"COURSE-1": ["learner@example.com"]},
			enabled_emails={"learner@example.com": "learner@example.com"},
		)
		self.ns["send_attempt_report_email"]("SUBM-1")
		self.sendmail.assert_not_called()

		# With a second teacher assigned, the preview still skips the member
		# and reaches the other one.
		self.enable_transport(
			owner="learner@example.com",
			member="learner@example.com",
			lesson_courses=["COURSE-1"],
			instructors={"COURSE-1": ["learner@example.com", "instructor@example.com"]},
			enabled_emails={
				"learner@example.com": "learner@example.com",
				"instructor@example.com": "instructor@example.com",
			},
		)
		self.ns["send_attempt_report_email"]("SUBM-1")
		self.assertEqual(
			self.sendmail.call_args.kwargs["recipients"],
			["instructor@example.com"],
		)

	def test_no_transport_configured_means_no_mail(self):
		self.enable_transport()
		self.frappe.get_cached_value = Mock(return_value=None)
		self.frappe.conf = {}

		self.ns["send_attempt_report_email"]("SUBM-1")
		self.sendmail.assert_not_called()

	def test_a_failed_render_logs_and_never_mails(self):
		self.enable_transport()
		self.get_pdf = Mock(side_effect=RuntimeError("no wkhtmltopdf"))
		# get_pdf is imported inside _report_pdf from the stub module.
		sys.modules["frappe.utils.pdf"].get_pdf = self.get_pdf

		self.ns["send_attempt_report_email"]("SUBM-1")
		self.sendmail.assert_not_called()
		self.log_error.assert_called_once()

	def test_submit_queues_the_mail_after_commit(self):
		self.ns["enqueue_attempt_report_email"]("SUBM-1")
		self.enqueue.assert_called_once()
		self.assertEqual(self.enqueue.call_args.kwargs.get("enqueue_after_commit"), True)


if __name__ == "__main__":
	unittest.main()
