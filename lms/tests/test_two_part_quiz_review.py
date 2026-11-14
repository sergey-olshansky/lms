# Copyright (c) 2026, tutor LMS contributors
# For license information, please see license.txt

"""Card #47 -- the two-part quiz: mixed question types, the preliminary/final
review status, the teacher's second pass over EVERY row, and the submission's
solution-file bundle.

The attempt-level contract these tests pin:

- A quiz may mix Choices / User Input with Open Ended; the one surviving rule
  of the old validator is ``show_answers = 0`` whenever an open question is
  present.
- An attempt with any open-answer row is ``pending_review``; without one it is
  ``final`` the moment the automation has checked everything.
- The teacher (never the member) may override marks of ANY row, including the
  auto-checked part; touched objective rows are stamped ``teacher_override``.
- ``finalize_submission_review`` refuses while an open row carries no recorded
  verdict, then freezes the attempt as ``final`` with reviewer and timestamp.
- The staged file bundle binds to the attempt that consumed it and becomes
  immutable for the member afterwards.
"""

import io
import unittest

import frappe

from lms.lms.doctype.lms_quiz_submission.lms_quiz_submission import (
	finalize_submission_review,
	save_submission_grades,
)
from lms.lms.quiz_submission_attachments import (
	QUIZ_ATTACHMENT_QUOTA_BYTES,
	bind_draft_attachments,
	delete_quiz_attachment,
	get_submission_attachments,
	upload_quiz_attachment,
)
from lms.lms.test_helpers import BaseTestUtils


class TwoPartQuizTestUtils(BaseTestUtils):
	"""Shared fixtures: one objective + one open question, one mixed quiz, one
	student who sits it, and the attempt rows a submit would have written."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.student = cls._create_user(
			"two-part-student@example.com",
			"Two",
			"Part",
			["LMS Student"],
		)

		choice = frappe.new_doc("LMS Question")
		choice.update(
			{
				"question": "2 + 2 = ?",
				"type": "Choices",
				"option_1": "4",
				"is_correct_1": 1,
				"option_2": "5",
				"is_correct_2": 0,
			}
		)
		choice.save()
		cls.choice = choice

		blank = frappe.new_doc("LMS Question")
		blank.update(
			{
				"question": "6 x 7 = ?",
				"type": "User Input",
				"possibility_1": "42",
			}
		)
		blank.save()
		cls.user_input = blank

		open_ended = frappe.new_doc("LMS Question")
		open_ended.update(
			{"question": "Explain your solution.", "type": "Open Ended", "marks": 5}
		)
		open_ended.save()
		cls.open_ended = open_ended

	@classmethod
	def _make_quiz(cls, title: str, rows: list[tuple], show_answers: int = 0) -> str:
		quiz = frappe.new_doc("LMS Quiz")
		quiz.update(
			{
				"title": f"{title} {frappe.generate_hash(length=6)}",
				"passing_percentage": 50,
				"show_answers": show_answers,
			}
		)
		for question, marks in rows:
			quiz.append("questions", {"question": question.name, "marks": marks})
		quiz.save()
		return quiz.name

	@classmethod
	def _make_submission(cls, quiz: str, *, member: str | None = None, with_open: bool = True):
		doc = frappe.new_doc("LMS Quiz Submission")
		doc.update(
			{
				"quiz": quiz,
				"member": member or cls.student.email,
				"passing_percentage": 50,
			}
		)
		doc.append(
			"result",
			{
				"question_name": cls.choice.name,
				"question_type": "Choices",
				"answer": "4",
				"is_correct": 1,
				"marks": 2,
				"marks_out_of": 2,
				"graded": 1,
			},
		)
		if with_open:
			doc.append(
				"result",
				{
					"question_name": cls.open_ended.name,
					"question_type": "Open Ended",
					"answer": "<p>My reasoning.</p>",
					"is_correct": 0,
					"marks": 0,
					"marks_out_of": 5,
					"graded": 0,
				},
			)
		doc.insert()
		return doc


class TestMixedQuizValidation(TwoPartQuizTestUtils):
	def test_open_ended_mixes_with_other_types(self):
		name = self._make_quiz(
			"Two-part quiz",
			[(self.choice, 2), (self.user_input, 1), (self.open_ended, 5)],
		)
		types = frappe.get_all(
			"LMS Quiz Question", filters={"parent": name}, pluck="type", order_by="idx asc"
		)
		self.assertEqual(types, ["Choices", "User Input", "Open Ended"])

	def test_mixed_quiz_disables_live_answer_checking(self):
		name = self._make_quiz(
			"Show answers lift",
			[(self.choice, 2), (self.open_ended, 5)],
			show_answers=1,
		)
		self.assertEqual(frappe.db.get_value("LMS Quiz", name, "show_answers"), 0)

	def test_objective_quiz_keeps_its_show_answers(self):
		name = self._make_quiz("Plain quiz", [(self.choice, 2), (self.user_input, 1)], show_answers=1)
		self.assertEqual(frappe.db.get_value("LMS Quiz", name, "show_answers"), 1)


class TestReviewStatus(TwoPartQuizTestUtils):
	def test_attempt_with_open_answers_awaits_the_teacher(self):
		quiz = self._make_quiz("Pending quiz", [(self.choice, 2), (self.open_ended, 5)])
		doc = self._make_submission(quiz)
		self.assertEqual(doc.review_status, "pending_review")

	def test_attempt_without_open_answers_is_final_at_submission(self):
		quiz = self._make_quiz("Auto quiz", [(self.choice, 2), (self.user_input, 1)])
		doc = self._make_submission(quiz, with_open=False)
		self.assertEqual(doc.review_status, "final")
		# Nothing awaited anyone: no reviewer is recorded.
		self.assertFalse(doc.reviewed_by)


class TestTeacherSecondPass(TwoPartQuizTestUtils):
	def setUp(self):
		super().setUp()
		self.quiz = self._make_quiz("Second pass", [(self.choice, 2), (self.open_ended, 5)])
		self.doc = self._make_submission(self.quiz)
		self.rows = {row.question_type: row for row in self.doc.result}

	def _grade(self, grades, as_user="Administrator"):
		frappe.set_user(as_user)
		try:
			return save_submission_grades(self.doc.name, grades)
		finally:
			frappe.set_user("Administrator")

	def test_teacher_overrides_the_score_of_an_auto_row(self):
		self._grade(
			[{"name": self.rows["Choices"].name, "marks": 1, "is_correct": 0}]
		)
		row = frappe.get_doc("LMS Quiz Result", self.rows["Choices"].name)
		self.assertEqual(row.marks, 1)
		self.assertEqual(row.teacher_override, 1)
		# The score follows the override; open marks still enter the total.
		self.assertEqual(frappe.db.get_value("LMS Quiz Submission", self.doc.name, "score"), 1)

	def test_untouched_auto_row_keeps_its_preliminary_marks(self):
		self._grade([{"name": self.rows["Open Ended"].name, "marks": 3, "graded": 1}])
		row = frappe.get_doc("LMS Quiz Result", self.rows["Choices"].name)
		self.assertEqual(row.marks, 2)
		self.assertEqual(row.teacher_override, 0)

	def test_open_row_grading_is_not_marked_as_an_override(self):
		self._grade([{"name": self.rows["Open Ended"].name, "marks": 5, "graded": 1}])
		row = frappe.get_doc("LMS Quiz Result", self.rows["Open Ended"].name)
		self.assertEqual(row.marks, 5)
		self.assertEqual(row.teacher_override, 0)

	def test_teacher_cannot_award_above_the_question_maximum(self):
		with self.assertRaises(frappe.ValidationError):
			self._grade([{"name": self.rows["Open Ended"].name, "marks": 6, "graded": 1}])

	def test_member_cannot_grade_their_own_attempt(self):
		with self.assertRaises(frappe.PermissionError):
			self._grade(
				[{"name": self.rows["Open Ended"].name, "marks": 5, "graded": 1}],
				as_user=self.student.email,
			)

	def test_finalize_refuses_while_an_open_answer_has_no_verdict(self):
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			finalize_submission_review(self.doc.name)

	def test_finalize_freezes_the_attempt_after_all_open_answers_are_graded(self):
		self._grade([{"name": self.rows["Open Ended"].name, "marks": 4, "graded": 1}])
		frappe.set_user("Administrator")
		result = finalize_submission_review(self.doc.name)
		self.assertTrue(result["finalized"])
		stored = frappe.db.get_value(
			"LMS Quiz Submission", self.doc.name, ["review_status", "reviewed_by", "reviewed_on"], as_dict=True
		)
		self.assertEqual(stored.review_status, "final")
		self.assertEqual(stored.reviewed_by, "Administrator")
		self.assertTrue(stored.reviewed_on)
		# Open marks entered the total: 2 + 4 of 7.
		score = frappe.db.get_value("LMS Quiz Submission", self.doc.name, "score")
		self.assertEqual(score, 6)

	def test_finalize_is_idempotent(self):
		self._grade([{"name": self.rows["Open Ended"].name, "marks": 0, "graded": 1}])
		frappe.set_user("Administrator")
		finalize_submission_review(self.doc.name)
		result = finalize_submission_review(self.doc.name)
		self.assertTrue(result["finalized"])

	def test_member_cannot_finalize(self):
		self._grade([{"name": self.rows["Open Ended"].name, "marks": 0, "graded": 1}])
		frappe.set_user(self.student.email)
		with self.assertRaises(frappe.PermissionError):
			finalize_submission_review(self.doc.name)


class TestSubmissionFileBundle(TwoPartQuizTestUtils):
	"""The staged bundle: drafts bind at submit and freeze for the member."""

	PNG_1PX = bytes.fromhex(
		"89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
		"0000000d4944415478da6364f8cfc00000030101006b04e9a70000000049454e44ae426082"
	)

	def setUp(self):
		super().setUp()
		self.quiz = self._make_quiz("Files quiz", [(self.choice, 2), (self.open_ended, 5)])

	def _upload(self, name: str, content: bytes | None = None, as_user: str = "Administrator"):
		frappe.set_user(as_user)
		try:
			from werkzeug.datastructures import FileStorage

			storage = FileStorage(
				stream=io.BytesIO(content or self.PNG_1PX), filename=name
			)
			previous_request = getattr(frappe.local, "request", None)
			frappe.local.request = frappe._dict(files={"file": storage})
			try:
				return upload_quiz_attachment(self.quiz)
			finally:
				frappe.local.request = previous_request
		finally:
			frappe.set_user("Administrator")

	def test_draft_upload_binds_at_submission_and_freezes(self):
		uploaded = self._upload("solution.png")
		self.assertTrue(frappe.db.exists("LMS Quiz Submission Attachment", uploaded["name"]))
		self.assertEqual(uploaded["state"]["used"], len(self.PNG_1PX))

		doc = self._make_submission(self.quiz, member="Administrator")
		bound = bind_draft_attachments(self.quiz, "Administrator", doc.name)
		self.assertEqual(bound, 1)

		# The bundle now belongs to the finished attempt: the member cannot
		# remove a file from it any more.
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.PermissionError):
			delete_quiz_attachment(uploaded["name"])

	def test_bundle_is_readable_by_the_member_and_the_reviewer_only(self):
		uploaded = self._upload("solution.png")
		doc = self._make_submission(self.quiz)
		bind_draft_attachments(self.quiz, "Administrator", doc.name)

		# The reviewer (quiz owner = Administrator) reads it...
		frappe.set_user("Administrator")
		review = get_submission_attachments(doc.name)
		self.assertEqual(review["count"], 1)
		self.assertEqual(review["rows"][0]["file_name"], "solution.png")

		# ...the member who sat the attempt reads their own...
		frappe.set_user(self.student.email)
		own = get_submission_attachments(doc.name)
		self.assertEqual(own["count"], 1)

		# ...another student does not.
		other = self._create_user(
			"two-part-other@example.com", "Other", "Student", ["LMS Student"]
		)
		frappe.set_user(other.email)
		with self.assertRaises(frappe.PermissionError):
			get_submission_attachments(doc.name)

	def test_quota_refuses_past_the_100_mib_bundle_cap(self):
		# A draft row already carrying the whole quota leaves nothing for a
		# second file, however small.
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "big.png",
				"folder": "Home",
				"is_private": 1,
				"content": self.PNG_1PX,
			}
		).insert(ignore_permissions=True)
		row = frappe.new_doc("LMS Quiz Submission Attachment")
		row.update(
			{
				"quiz": self.quiz,
				"member": "Administrator",
				"file": file_doc.name,
				"file_name": "big.png",
				"file_size": QUIZ_ATTACHMENT_QUOTA_BYTES,
				"uploaded_by": "Administrator",
			}
		)
		row.insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			self._upload("second.png")
