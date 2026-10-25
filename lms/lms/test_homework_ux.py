"""The teacher can issue a first homework to a registered student by exact email."""

import frappe

from lms.lms import homework_api
from lms.lms.test_helpers import BaseTestUtils


class TestHomeworkStudentSelection(BaseTestUtils):
	def setUp(self):
		super().setUp()
		self.teacher = self._create_user("ux35-teacher@example.com", "UX", "Teacher", ["Course Creator", "LMS Student"])
		self.student = self._create_user("ux35-student@example.com", "UX", "Student", ["LMS Student"])
		frappe.set_user(self.teacher.name)

	def test_exact_lookup_then_first_issue_establishes_roster(self):
		self.assertEqual(homework_api.find_homework_student(" UX35-STUDENT@EXAMPLE.COM ")["name"], self.student.name)
		self.assertNotIn(self.student.name, [row.name for row in homework_api.get_homework_students()])
		course = self._create_course(title="UX35 student lookup", instructor=self.teacher.name)
		chapter = self._create_chapter("Practice", course.name)
		self._create_chapter_reference(course.name, chapter.name)
		lesson = self._create_lesson("Read", chapter.name, course.name)
		self._create_lesson_reference(chapter.name, lesson.name)
		template = homework_api.save_homework(title="UX first issue", days=3, items=[{"source_type": "Lesson", "name": lesson.name}])
		result = homework_api.assign_homework(homework=template["name"], student=self.student.name, days=3, idempotency_key=frappe.generate_hash(length=20))
		self.assertTrue(result["name"])
		self.assertIn(self.student.name, [row.name for row in homework_api.get_homework_students()])
		self.assertFalse(frappe.db.exists("LMS Enrollment", {"member": self.student.name, "course": course.name}))
		frappe.set_user(self.student.name)
		homework_api.open_homework(assignment=result["name"])
		homework_api.record_material_opened(lesson=lesson.name)
		issued = frappe.get_doc("LMS Homework Assignment", result["name"])
		self.assertEqual(issued.completed_requirements, 1)
		self.assertEqual(issued.status, "Review")

	def test_lookup_refuses_student_callers(self):
		frappe.set_user(self.student.name)
		for operation in (lambda: homework_api.find_homework_student(self.teacher.name), homework_api.get_homework_students):
			with self.assertRaises(frappe.PermissionError):
				operation()

	def test_lookup_rejects_unknown_disabled_and_self(self):
		for address in ("ux35-missing@example.com", self.teacher.name):
			with self.assertRaises(frappe.ValidationError):
				homework_api.find_homework_student(address)
		frappe.db.set_value("User", self.student.name, "enabled", 0)
		with self.assertRaises(frappe.ValidationError):
			homework_api.find_homework_student(self.student.name)

	def test_assignment_pdf_links_keep_homework_context(self):
		from lms.lms.homework_pdf import _material_lines

		row = {"requirement_type": "Open Lesson", "label": "Read", "route": {"type": "lesson", "course": "ux", "number": "1-1"}}
		assigned = "".join(_material_lines([row], "HW-ASN-UX"))
		self.assertIn("/lms/courses/ux/learn/1-1?hw=HW-ASN-UX", assigned)
		self.assertNotIn("?hw=", "".join(_material_lines([row])))
