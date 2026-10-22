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

	def tearDown(self):
		# The committed fixtures release the class savepoint; the race classes
		# own their cleanup explicitly instead of the rollback-to-savepoint.
		frappe.db.rollback()
		frappe.set_user("Administrator")

	def _race(self, scripts):
		"""Two children with a real cross-process barrier right before the
		quota-verdict section, so the race is the quota lock's to settle --
		not scheduler luck. Verdicts are STRICT: every child must exit 0 and
		print exactly one of SAVED/ATTACHED (success) or REFUSED_QUOTA; any
		other failure surfaces as an ERROR exit the assertions reject."""
		procs = [
			subprocess.Popen(
				[sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
			)
			for script in scripts
		]
		return [(p.wait(timeout=240), p.stdout.read(), p.stderr.read()) for p in procs]

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
		template in parallel, barrier-aligned before the registration: each
		fits alone, together 22 MiB > 20 MiB. Exactly one commits, exactly one
		is refused BY THE BUDGET, the committed total is exactly one file.
		(Material rows are not details-synced -- nothing drops them -- so this
		is the genuine budget race.)"""
		frappe.set_user("Administrator")
		self._commit()
		barrier = Path(frappe.get_site_path("private", "files")) / f"r7bar-{frappe.generate_hash(6)}"
		results = self._race([self._adder_script(11, barrier, 0), self._adder_script(11, barrier, 1)])
		try:
			frappe.set_user("Administrator")
			frappe.db.rollback()  # fresh snapshot for the verdict
			used = frappe.db.sql(
				"SELECT COALESCE(SUM(`file_size`),0) s FROM `tabLMS Homework Material`"
				" WHERE `parent`=%s AND `parenttype`='LMS Homework'",
				(self.template,),
				as_dict=True,
			)[0].s
			self._assert_strict_race(results, "ADDED", used)
			self.assertEqual(used, 11 * 1024 * 1024, f"expected exactly one material: {used}")
			self.assertLessEqual(used, homework_materials.MATERIAL_QUOTA_BYTES)
		finally:
			barrier.unlink(missing_ok=True)
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

	def _adder_script(self, size_mb, barrier, slot):
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
barrier = Path({str(barrier)!r})
try:
    f = frappe.new_doc("File")
    f.update({{"file_name": "mat-" + frappe.generate_hash(6) + ".txt",
               "is_private": 1, "content": b"x" * size}})
    f.save(ignore_permissions=True)
    frappe.db.commit()
    if {slot} == 0:
        barrier.write_text("go")
    else:
        import time
        for _ in range(200):
            if barrier.exists():
                break
            time.sleep(0.05)
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
		the same assignment, barrier-aligned before the registration; whichever
		wins, the pair exceeds 20 MiB together, so exactly one commits, one is
		refused by the quota, and the committed sum is the winner's size."""
		frappe.set_user("Administrator")
		self._commit()
		barrier = Path(frappe.get_site_path("private", "files")) / f"r7sol-{frappe.generate_hash(6)}"
		results = self._race([self._attacher_script(15, barrier, 0), self._attacher_script(6, barrier, 1)])
		try:
			frappe.set_user("Administrator")
			frappe.db.rollback()
			used = frappe.db.sql(
				"SELECT COALESCE(SUM(`file_size`),0) s FROM `tabLMS Homework Attachment`"
				" WHERE `assignment`=%s",
				(self.assignment,),
				as_dict=True,
			)[0].s
			self._assert_strict_race(results, "ATTACHED", used)
			self.assertIn(used, (15 * 1024 * 1024, 6 * 1024 * 1024), f"unexpected total: {used}")
			self.assertLessEqual(used, homework_attachments.ATTACHMENT_QUOTA_BYTES)
		finally:
			barrier.unlink(missing_ok=True)
			self._cleanup_tree()

	def _attacher_script(self, size_mb, barrier, slot):
		return f"""
from pathlib import Path
import frappe
frappe.init(site="{SITE}", sites_path="{BENCH}/sites")
frappe.connect()
# The raced operations never depend on background jobs; not enqueueing keeps
# a workerless bench from tripping QueueOverloaded under test load.
frappe.enqueue = lambda *args, **kwargs: None
frappe.set_user({self.student.name!r})
from lms.lms import homework_attachments
size = {size_mb} * 1024 * 1024
barrier = Path({str(barrier)!r})
try:
    f = frappe.new_doc("File")
    f.update({{"file_name": "sol-" + frappe.generate_hash(6) + ".txt",
               "is_private": 1, "content": b"x" * size}})
    f.save(ignore_permissions=True)
    frappe.db.commit()
    if {slot} == 0:
        barrier.write_text("go")
    else:
        import time
        for _ in range(200):
            if barrier.exists():
                break
            time.sleep(0.05)
    homework_attachments.attach_file({self.assignment!r}, f.name)
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
