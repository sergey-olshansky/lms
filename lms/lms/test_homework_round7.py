# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Round-7 regressions: public images refused in rich details, the template
budget under its advisory lock with a current-read sum, and REAL two-process
quota races (separate connections, real commits) for both the student
solution quota (R10) and the teacher template budget (E05).
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase

from lms.lms import homework_api, homework_attachments, homework_materials
from lms.lms.test_helpers import BaseTestUtils as B

# Environment-derived, not machine-specific: the races spawn child
# processes against THIS bench/site, wherever they run (reviewer checkout or
# CI container alike). Skipped when the site does not allow tests.
BENCH = str(Path(frappe.utils.get_bench_path()))
SITE = frappe.local.site


def _file(owner, *, private=True, filename=None, content=None):
	frappe.set_user(owner)
	doc = frappe.new_doc("File")
	doc.update(
		{
			"file_name": filename or ("r7-" + frappe.generate_hash(length=10) + ".txt"),
			"is_private": int(private),
			"content": content or ("probe-" + frappe.generate_hash(length=12)).encode(),
		}
	)
	doc.save(ignore_permissions=True)
	return doc


class Round7Base(B, IntegrationTestCase):
	def setUp(self):
		super().setUp()
		# This module verifies synchronous application behavior, not RQ. Keep its
		# incidental enqueue requests local to this test process instead of
		# mutating the shared Redis queue (which may contain unrelated work).
		original_enqueue = frappe.enqueue
		self.addCleanup(setattr, frappe, "enqueue", original_enqueue)
		frappe.enqueue = lambda *args, **kwargs: None
		frappe.set_user("Administrator")
		token = frappe.generate_hash(length=10)
		self.teacher = B._create_user(
			f"r7t-{token}@example.com", "R7", "Teach", ["Course Creator", "LMS Student"]
		)
		self.student = B._create_user(
			f"r7s-{token}@example.com", "R7", "Stud", ["LMS Student"]
		)
		frappe.set_user(self.teacher.name)
		self.course = B._create_course(title=f"R7 Course {token}", instructor=self.teacher.name)
		self.chapter = B._create_chapter(f"R7 ch {token}", self.course.name)
		B._create_chapter_reference(self.course.name, self.chapter.name)
		self.lesson = B._create_lesson(f"R7 lesson {token}", self.chapter.name, self.course.name)
		B._create_lesson_reference(self.chapter.name, self.lesson.name)
		B._create_enrollment(self.student.name, self.course.name)
		self.template = homework_api.save_homework(
			title=f"R7 hw {token}", days=3, items=[{"source_type": "Lesson", "name": self.lesson.name}]
		)["name"]
		self.assignment = homework_api.assign_homework(
			homework=self.template,
			student=self.student.name,
			idempotency_key=frappe.generate_hash(length=24),
		)["name"]


class TestRound7PublicImages(Round7Base):
	def test_public_image_refused_by_direct_api(self):
		"""Round 7: the server itself refuses a public image reference in the
		rich details -- the UI's private default is not the gate."""
		public = _file(self.teacher.name, private=False)
		details = f'<p>текст</p><p><img src="{public.file_url}"></p>'
		frappe.set_user(self.teacher.name)
		with self.assertRaises(frappe.ValidationError):
			homework_api.save_homework(
				title="R7 public img", days=3,
				items=[{"source_type": "Lesson", "name": self.lesson.name}],
				details=details,
			)

	def test_private_image_accepted_and_managed(self):
		private = _file(self.teacher.name, private=True)
		frappe.set_user(self.teacher.name)
		name = homework_api.save_homework(
			title="R7 private img", days=3,
			items=[{"source_type": "Lesson", "name": self.lesson.name}],
			details=f'<p><img src="{private.file_url}"></p>',
		)["name"]
		rows = frappe.get_all(
			"LMS Homework Material",
			filters={"parent": name, "role": "Detail Image"},
			pluck="file",
		)
		self.assertIn(private.name, rows)


class _RaceMixin:
	"""Shared machinery for the two-process quota races: fixtures are REALLY
	committed (in_test suppresses the API's own commits, so this is explicit),
	two subprocesses with separate connections race in parallel, and the
	verdict is read from a fresh snapshot afterwards. The disposable
	allow_tests site carries the committed rows only until cleanup."""

	def _commit(self):
		frappe.db.commit()

	def setUp(self):
		super().setUp()

	def tearDown(self):
		# The committed fixtures release the class savepoint; the race classes
		# own their cleanup explicitly instead of the rollback-to-savepoint.
		frappe.db.rollback()
		frappe.set_user("Administrator")

	def _race(self, scripts):
		"""Two children behind a REAL two-sided barrier at the critical
		section: each writes its ready-marker, then EVERY child polls until
		both markers exist, and only then enters the quota-verdict region --
		neither can start before the other has arrived (round 9; the previous
		one-sided latch let slot 0 run ahead). Verdicts are STRICT: rc=0 and
		exactly one of SAVED/ADDED/ATTACHED or REFUSED_QUOTA per child; any
		other failure is an ERROR the assertions reject."""
		procs = [
			subprocess.Popen(
				[sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
			)
			for script in scripts
		]
		return [(p.wait(timeout=240), p.stdout.read(), p.stderr.read()) for p in procs]

	def _barrier_files(self, stem):
		"""ready-marker per slot + the shared release gate."""
		base = Path(frappe.get_site_path("private", "files"))
		ready = [base / f"{stem}.ready{slot}" for slot in (0, 1)]
		release = base / f"{stem}.go"
		for marker in (*ready, release):
			marker.unlink(missing_ok=True)
		return ready, release

	def _barrier_wait_child(self, slot, ready, release):
		"""Child-side barrier code (indented to sit inside the caller's try):
		announce, wait for EVERYONE, wait for the gate. The parent opens the
		gate only once both ready-markers exist."""
		lines = [
			f"barrier_ready = Path({str(ready[slot].resolve())!r})",
			f"barrier_release = Path({str(release.resolve())!r})",
			f"barrier_all = [{str(ready[0].resolve())!r}, {str(ready[1].resolve())!r}]",
			'barrier_ready.write_text("ready")',
			"import time as _bt",
			"for _ in range(400):",
			"    if all(Path(p).exists() for p in barrier_all):",
			"        break",
			"    _bt.sleep(0.05)",
			"for _ in range(400):",
			"    if barrier_release.exists():",
			"        break",
			"    _bt.sleep(0.05)",
		]
		return "\n".join("    " + line for line in lines)

	def _assert_strict_race(self, results, success_word, expect_sum_bytes):
		for code, out, err in results:
			self.assertEqual(code, 0, f"child crashed: rc={code}, out={out[-500:]}, err={err[-300:]}")
			self.assertNotIn("ERROR", out, f"unexpected child failure: {out}")
		successes = [out for _c, out, _e in results if success_word in out]
		refusals = [out for _c, out, _e in results if "REFUSED_QUOTA" in out]
		self.assertEqual(len(successes), 1, f"expected exactly one commit: {[r[1] for r in results]}")
		self.assertEqual(len(refusals), 1, f"expected exactly one quota refusal: {[r[1] for r in results]}")

	def _cleanup_tree(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		for doctype, filters in [
			("LMS Homework Attachment", {"assignment": self.assignment}),
			("LMS Homework Assignment Material", {"parent": self.assignment}),
			("LMS Homework Assignment", {"name": self.assignment}),
			("LMS Homework Material", {"parent": self.template}),
			("LMS Homework", {"name": self.template}),
			("Lesson Reference", {"lesson": self.lesson.name}),
			("Course Lesson", {"name": self.lesson.name}),
			("Chapter Reference", {"parent": self.course.name}),
			("Course Chapter", {"name": self.chapter.name}),
			("LMS Enrollment", {"course": self.course.name}),
			("LMS Course", {"name": self.course.name}),
		]:
			for name in frappe.get_all(doctype, filters, pluck="name"):
				frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
		for email in (self.teacher.name, self.student.name):
			for row in frappe.get_all("File", {"owner": email}, pluck="name"):
				frappe.delete_doc("File", row, ignore_permissions=True, force=True)
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, ignore_permissions=True, force=True)
		frappe.db.commit()


class TestRound7BudgetLock(_RaceMixin, Round7Base):
	def test_parallel_material_adds_cannot_exceed_budget(self):
		"""Two REAL processes add an 11 MiB teacher material to the same
		template, released together by a TWO-SIDED barrier at the critical
		section, in BOTH slot orders (round 9): each fits alone, together
		22 MiB > 20 MiB. Every round must yield exactly one commit and one
		QUOTA refusal, with the committed total exactly one file."""
		frappe.set_user("Administrator")
		self._commit()
		try:
			for order in ((0, 1), (1, 0)):
				ready, release = self._barrier_files(f"r7mat-{frappe.generate_hash(4)}")
				scripts = [self._adder_script(11, ready, release, slot) for slot in order]
				procs = [subprocess.Popen(
					[sys.executable, "-c", s], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
				) for s in scripts]
				# Gate opens only once BOTH children announced readiness.
				import time as _t
				for _ in range(400):
					if all(m.exists() for m in ready):
						break
					_t.sleep(0.05)
				release.write_text("go")
				results = [(p.wait(timeout=240), p.stdout.read(), p.stderr.read()) for p in procs]
				frappe.set_user("Administrator")
				frappe.db.rollback()  # fresh snapshot for the verdict
				used = frappe.db.sql(
					"SELECT COALESCE(SUM(`file_size`),0) s FROM `tabLMS Homework Material`"
					" WHERE `parent`=%s AND `parenttype`='LMS Homework'",
					(self.template,),
					as_dict=True,
				)[0].s
				self._assert_strict_race(results, "ADDED", used)
				self.assertEqual(used, 11 * 1024 * 1024, f"order {order}: expected one file: {used}")
				# Reset the board for the second order: drop the winner.
				for row in frappe.get_all("LMS Homework Material", {"parent": self.template}, pluck="name"):
					frappe.delete_doc("LMS Homework Material", row, ignore_permissions=True, force=True)
				for doctype, filters in [("File", {"attached_to_doctype": "LMS Homework Material"})]:
					for name in frappe.get_all(doctype, filters, pluck="name"):
						frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
				frappe.db.commit()
				frappe.db.rollback()
		finally:
			self._cleanup_tree()

	def test_single_save_with_oversized_images_refused(self):
		"""One save whose details reference two 11 MiB private images is
		refused by the budget verdict outright (22 MiB > 20 MiB) -- the
		images-vs-budget guard does not depend on interleaving at all."""
		frappe.set_user("Administrator")
		images = []
		for index in range(2):
			# Distinct content per image: frappe dedupes byte-identical files
			# to one URL, and one shared row cannot exceed anything.
			img = _file(
				self.teacher.name,
				private=True,
				filename=f"big-{index}-{frappe.generate_hash(6)}.png",
				content=(
					bytes([137, 80, 78, 71, 13, 10, 26, 10])
					+ frappe.generate_hash(length=32).encode()
					+ b"x" * (11 * 1024 * 1024 - 40)
				),
			)
			images.append(img)
		self.assertNotEqual(images[0].file_url, images[1].file_url)
		frappe.set_user(self.teacher.name)
		details = f'<p><img src="{images[0].file_url}"><img src="{images[1].file_url}"></p>'
		with self.assertRaises(frappe.ValidationError) as ctx:
			homework_api.save_homework(
				title="R7 oversize", days=3,
				items=[{"source_type": "Lesson", "name": self.lesson.name}],
				details=details,
			)
		self.assertIn("cannot exceed", str(ctx.exception))

	def _adder_script(self, size_mb, ready, release, slot):
		barrier = self._barrier_wait_child(slot, ready, release)
		return f"""
from pathlib import Path
import frappe
frappe.init(site="{SITE}", sites_path="{BENCH}/sites")
frappe.connect()
# The raced operations never depend on background jobs; not enqueueing keeps
# a workerless bench from tripping QueueOverloaded under test load.
frappe.enqueue = lambda *args, **kwargs: None
frappe.set_user({self.teacher.name!r})
from lms.lms import homework_materials
size = {size_mb} * 1024 * 1024
try:
    f = frappe.new_doc("File")
    f.update({{"file_name": "mat-" + frappe.generate_hash(6) + ".txt",
               "is_private": 1, "content": b"x" * size}})
    f.save(ignore_permissions=True)
    frappe.db.commit()
{barrier}
    import time as _t
    for attempt in range(2):
        try:
            homework_materials.add_material({self.template!r}, f.name)
            break
        except frappe.QueryDeadlockError:
            # A framework-level naming race on concurrent child inserts; one
            # bounded retry, then the verdict (success or the QUOTA refusal)
            # still comes from the serialized budget lock.
            if attempt == 1:
                raise
            frappe.db.rollback()
            _t.sleep(0.3)
    frappe.db.commit()
    print("ADDED")
except frappe.ValidationError as exc:
    frappe.db.rollback()
    msg = str(exc)
    if "cannot exceed" in msg:
        print("REFUSED_QUOTA")
    else:
        print("ERROR validation:", msg[:200])
        raise SystemExit(3)
except Exception as exc:
    frappe.db.rollback()
    print("ERROR", type(exc).__name__, str(exc)[:200])
    raise SystemExit(4)
frappe.destroy()
"""


class TestRound7SolutionQuotaRace(_RaceMixin, Round7Base):
	def test_two_connections_cannot_double_spend_quota(self):
		"""R10 tail: two REAL processes register 15 MiB and 6 MiB solutions on
		the same assignment, released together by the two-sided barrier, in
		BOTH slot orders: the pair exceeds 20 MiB together, so exactly one
		commits, one is refused by the quota, and the committed sum is the
		winner's size."""
		frappe.set_user("Administrator")
		self._commit()
		sizes = {15: 15 * 1024 * 1024, 6: 6 * 1024 * 1024}
		try:
			for order in ((15, 6), (6, 15)):
				ready, release = self._barrier_files(f"r7sol-{frappe.generate_hash(4)}")
				scripts = [self._attacher_script(size_mb, ready, release, slot)
					for slot, size_mb in enumerate(order)]
				procs = [subprocess.Popen(
					[sys.executable, "-c", s], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
				) for s in scripts]
				import time as _t
				for _ in range(400):
					if all(m.exists() for m in ready):
						break
					_t.sleep(0.05)
				release.write_text("go")
				results = [(p.wait(timeout=240), p.stdout.read(), p.stderr.read()) for p in procs]
				frappe.set_user("Administrator")
				frappe.db.rollback()
				used = frappe.db.sql(
					"SELECT COALESCE(SUM(`file_size`),0) s FROM `tabLMS Homework Attachment`"
					" WHERE `assignment`=%s",
					(self.assignment,),
					as_dict=True,
				)[0].s
				self._assert_strict_race(results, "ATTACHED", used)
				self.assertIn(used, sizes.values(), f"order {order}: unexpected total: {used}")
				self.assertLessEqual(used, homework_attachments.ATTACHMENT_QUOTA_BYTES)
				# Reset for the second order: drop the winner's rows/files.
				for row in frappe.get_all("LMS Homework Attachment", {"assignment": self.assignment}, pluck="name"):
					frappe.delete_doc("LMS Homework Attachment", row, ignore_permissions=True, force=True)
				for name in frappe.get_all("File", {"attached_to_doctype": "LMS Homework Attachment"}, pluck="name"):
					frappe.delete_doc("File", name, ignore_permissions=True, force=True)
				frappe.db.commit()
				frappe.db.rollback()
		finally:
			self._cleanup_tree()

	def _attacher_script(self, size_mb, ready, release, slot):
		barrier = self._barrier_wait_child(slot, ready, release)
		return f"""
from pathlib import Path
import frappe
frappe.init(site="{SITE}", sites_path="{BENCH}/sites")
frappe.connect()
frappe.enqueue = lambda *args, **kwargs: None
frappe.set_user({self.student.name!r})
from lms.lms import homework_attachments
size = {size_mb} * 1024 * 1024
try:
    f = frappe.new_doc("File")
    f.update({{"file_name": "sol-" + frappe.generate_hash(6) + ".txt",
               "is_private": 1, "content": b"x" * size}})
    f.save(ignore_permissions=True)
    frappe.db.commit()
{barrier}
    import time as _t
    for attempt in range(2):
        try:
            homework_attachments.attach_file({self.assignment!r}, f.name)
            break
        except frappe.QueryDeadlockError:
            # Framework naming race on truly simultaneous child inserts; one
            # bounded retry, the quota verdict still comes from the lock.
            if attempt == 1:
                raise
            frappe.db.rollback()
            _t.sleep(0.3)
    frappe.db.commit()
    print("ATTACHED")
except frappe.ValidationError as exc:
    frappe.db.rollback()
    msg = str(exc)
    if "cannot exceed" in msg:
        print("REFUSED_QUOTA")
    else:
        print("ERROR validation:", msg[:200])
        raise SystemExit(3)
except Exception as exc:
    frappe.db.rollback()
    print("ERROR", type(exc).__name__, str(exc)[:200])
    raise SystemExit(4)
frappe.destroy()
"""


class TestRound7AttemptPool(Round7Base):
	"""F03 / rounds 8-9: the OFFERED pool of an attempt is persisted
	separately from its result rows, in exactly the validated form the score
	resolver accepted. Two REAL attempts through submit_quiz."""

	def _choices_quiz(self, questions_count=2):
		frappe.set_user(self.teacher.name)
		questions = []
		for label in ("Alpha", "Beta", "Gamma", "Delta")[:questions_count]:
			q = frappe.get_doc(
				{
					"doctype": "LMS Question",
					"question": f"R7 pool {label} {frappe.generate_hash(4)}",
					"type": "Choices",
					"option_1": "One",
					"is_correct_1": 1,
					"option_2": "Two",
				}
			)
			q.insert()
			questions.append(q)
		quiz = frappe.new_doc("LMS Quiz")
		quiz.update({"title": "R7 pool quiz", "passing_percentage": 50})
		for q in questions:
			quiz.append("questions", {"question": q.name, "marks": 1, "type": "Choices"})
		quiz.insert()
		# On this stack a member reaches an assessment through a lesson
		# placement (or a batch) -- embed the quiz in a dedicated lesson of
		# the fixture course, where self.student is enrolled.
		chapter = frappe.db.get_value(
			"Course Chapter", {"course": self.course.name}, "name"
		)
		holder = frappe.new_doc("Course Lesson")
		holder.update(
			{
				"title": f"R7 pool holder {frappe.generate_hash(4)}",
				"chapter": chapter,
				"course": self.course.name,
				"content": json.dumps({"blocks": [{"type": "quiz", "data": {"quiz": quiz.name}}]}),
			}
		)
		holder.insert()
		frappe.get_doc(
			{
				"doctype": "Lesson Reference",
				"parent": chapter,
				"parenttype": "Course Chapter",
				"parentfield": "lessons",
				"lesson": holder.name,
			}
		).insert(ignore_permissions=True)
		return quiz, questions

	def _submit(self, quiz, answers, pool=None):
		from lms.lms.doctype.lms_quiz.lms_quiz import submit_quiz

		frappe.set_user(self.student.name)
		payload = {"quiz": quiz.name, "results": json.dumps(answers)}
		if pool is not None:
			payload["question_pool"] = json.dumps(pool)
		submit_quiz(**payload)
		return frappe.get_all(
			"LMS Quiz Submission",
			filters={"quiz": quiz.name, "member": self.student.name},
			order_by="creation desc",
			pluck="name",
			limit=1,
		)[0]

	def test_partial_then_retake_pool_contract(self):
		quiz, questions = self._choices_quiz()
		# Attempt 1: pass Alpha only (partial).
		first = self._submit(
			quiz,
			[{"question_name": questions[0].name, "answer": ["One"]}],
			pool=[questions[0].name],
		)
		self.assertEqual(
			json.loads(frappe.db.get_value("LMS Quiz Submission", first, "question_pool")),
			[questions[0].name],
		)
		# Attempt 2 (retake of the failure): offered Beta only; Alpha rides
		# along as a carried credited answer.
		second = self._submit(
			quiz,
			[{"question_name": questions[1].name, "answer": ["One"]}],
			# Simulate a stale/corrupted client that resends the already-credited
			# Alpha alongside Beta. The persisted offered pool must match what the
			# score resolver actually counts: Beta only.
			pool=[questions[0].name, questions[1].name],
		)
		doc = frappe.get_doc("LMS Quiz Submission", second)
		row_names = {row.question_name for row in doc.result}
		self.assertEqual(row_names, {questions[0].name, questions[1].name})
		self.assertEqual(json.loads(doc.question_pool), [questions[1].name])
		# The student reads the field back through the REAL client API: the
		# JSON field serializes and the permission pair holds (round 9).
		frappe.set_user(self.student.name)
		rows = frappe.client.get_list(
			"LMS Quiz Submission",
			filters={"name": second},
			fields=["name", "question_pool"],
			limit_page_length=1,
		)
		self.assertEqual(json.loads(rows[0]["question_pool"]), [questions[1].name])
		# A pool-less client's submission stores no pool (legacy shape).
		legacy = self._submit(quiz, [{"question_name": questions[1].name, "answer": ["Two"]}])
		self.assertFalse(frappe.db.get_value("LMS Quiz Submission", legacy, "question_pool"))

	def test_pool_narrowed_to_the_resolver_accepted_form(self):
		"""Round 9: a corrupted declaration (foreign ids, duplicates, a quiz
		that no longer has one of the names) is narrowed to the validated
		intersection before BOTH the score denominator and the record."""
		quiz, questions = self._choices_quiz()
		foreign = "NOT-A-QUESTION-NAME"
		poisoned = [questions[0].name, foreign, questions[0].name, questions[1].name]
		name = self._submit(
			quiz,
			[{"question_name": questions[0].name, "answer": ["One"]}],
			pool=poisoned,
		)
		stored = json.loads(frappe.db.get_value("LMS Quiz Submission", name, "question_pool"))
		self.assertEqual(sorted(stored), sorted({questions[0].name, questions[1].name}))
		self.assertNotIn(foreign, stored)
		# An entirely-foreign pool reads as "declared nothing": no pool stored.
		blank = self._submit(
			quiz,
			[{"question_name": questions[1].name, "answer": ["One"]}],
			pool=[foreign],
		)
		self.assertFalse(frappe.db.get_value("LMS Quiz Submission", blank, "question_pool"))
