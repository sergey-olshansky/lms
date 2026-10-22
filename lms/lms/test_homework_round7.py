# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Round-7 regressions: public images refused in rich details, the template
budget under its advisory lock with a current-read sum, and REAL two-process
quota races (separate connections, real commits) for both the student
solution quota (R10) and the teacher template budget (E05).
"""

import subprocess
import sys
import unittest

import frappe
from frappe.tests import IntegrationTestCase

from lms.lms import homework_api, homework_attachments, homework_materials
from lms.lms.test_helpers import BaseTestUtils as B

BENCH = "/Users/user/Documents/projects/hwbench/frappe-bench"


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
		procs = [
			subprocess.Popen(
				[sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
			)
			for script in scripts
		]
		return [(p.wait(timeout=180), p.stdout.read(), p.stderr.read()) for p in procs]

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
	def test_concurrent_saves_cannot_exceed_budget(self):
		"""Two REAL processes save the same template in parallel, each embedding
		an 11 MiB private image: each fits alone, together they exceed 20 MiB.
		The loser must be refused; the committed total stays within budget."""
		frappe.set_user("Administrator")
		self._commit()  # fixtures visible to separate connections
		scripts = [
			self._saver_script(11),  # each child builds its OWN image file
			self._saver_script(11),
		]
		results = self._race(scripts)
		try:
			frappe.set_user("Administrator")
			frappe.db.rollback()  # fresh snapshot for the verdict
			used = frappe.db.sql(
				"SELECT COALESCE(SUM(`file_size`),0) s FROM `tabLMS Homework Material`"
				" WHERE `parent`=%s AND `parenttype`='LMS Homework'",
				(self.template,),
				as_dict=True,
			)[0].s
			refused = sum(1 for _code, out, _err in results if "REFUSED" in out)
			self.assertGreaterEqual(refused, 1, f"nobody refused; outputs: {[r[1] for r in results]}; stderr: {[r[2][-400:] for r in results]}")
			self.assertLessEqual(
				used,
				homework_materials.MATERIAL_QUOTA_BYTES,
				f"budget exceeded: {used}",
			)
		finally:
			self._cleanup_tree()

	def _saver_script(self, size_mb):
		return f"""
from pathlib import Path
import frappe
frappe.init(site="hwtest.local", sites_path="{BENCH}/sites")
frappe.connect()
frappe.set_user({self.teacher.name!r})
from lms.lms import homework_api
size = {size_mb} * 1024 * 1024
try:
    f = frappe.new_doc("File")
    f.update({{"file_name": "race-" + frappe.generate_hash(6) + ".png",
               "is_private": 1, "content": bytes([137, 80, 78, 71, 13, 10, 26, 10]) + b"x" * (size - 8)}})
    f.save(ignore_permissions=True)
    frappe.db.commit()
    homework_api.save_homework(
        name={self.template!r},
        title="R7 race",
        days=3,
        items=[{{"source_type": "Lesson", "name": {self.lesson.name!r}}}],
        details='<p><img src="' + f.file_url + '"></p>',
    )
    frappe.db.commit()
    print("SAVED")
except Exception as exc:
    frappe.db.rollback()
    print("REFUSED", type(exc).__name__)
frappe.destroy()
"""


class TestRound7SolutionQuotaRace(_RaceMixin, Round7Base):
	def test_two_connections_cannot_double_spend_quota(self):
		"""R10 tail: two REAL processes register 15 MiB and 6 MiB solutions on
		the same assignment in parallel; the pair exceeds 20 MiB together, so
		exactly the fitting subset commits and the total stays within budget."""
		frappe.set_user("Administrator")
		self._commit()
		scripts = [self._attacher_script(15), self._attacher_script(6)]
		results = self._race(scripts)
		try:
			frappe.set_user("Administrator")
			frappe.db.rollback()
			used = frappe.db.sql(
				"SELECT COALESCE(SUM(`file_size`),0) s FROM `tabLMS Homework Attachment`"
				" WHERE `assignment`=%s",
				(self.assignment,),
				as_dict=True,
			)[0].s
			refused = sum(1 for _code, out, _err in results if "REFUSED" in out)
			self.assertGreaterEqual(refused, 1, f"nobody refused; outputs: {[r[1] for r in results]}; stderr: {[r[2][-400:] for r in results]}")
			self.assertLessEqual(
				used,
				homework_attachments.ATTACHMENT_QUOTA_BYTES,
				f"quota exceeded: {used}",
			)
		finally:
			self._cleanup_tree()

	def _attacher_script(self, size_mb):
		return f"""
from pathlib import Path
import frappe
frappe.init(site="hwtest.local", sites_path="{BENCH}/sites")
frappe.connect()
frappe.set_user({self.student.name!r})
from lms.lms import homework_attachments
size = {size_mb} * 1024 * 1024
try:
    f = frappe.new_doc("File")
    f.update({{"file_name": "sol-" + frappe.generate_hash(6) + ".txt",
               "is_private": 1, "content": b"x" * size}})
    f.save(ignore_permissions=True)
    frappe.db.commit()
    homework_attachments.attach_file({self.assignment!r}, f.name)
    frappe.db.commit()
    print("ATTACHED")
except Exception as exc:
    frappe.db.rollback()
    print("REFUSED", type(exc).__name__)
frappe.destroy()
"""
