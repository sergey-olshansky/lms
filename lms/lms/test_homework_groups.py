# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Library group rules (task #35 spec 3.2): two levels, no cycles, own tree only,
delete only when empty. Matrix A02/A03."""

import frappe
from frappe.tests import IntegrationTestCase

from lms.lms.test_helpers import BaseTestUtils


class TestHomeworkGroups(BaseTestUtils, IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.teacher = self._create_user(
			"hw-teacher@example.com", "Hana", "Teacher", ["Course Creator", "LMS Student"]
		)
		self.other_teacher = self._create_user(
			"hw-other-teacher@example.com", "Oleg", "Other", ["Course Creator", "LMS Student"]
		)
		frappe.set_user(self.teacher.email)

	def _group(self, title, parent=None, owner=None):
		doc = frappe.new_doc("LMS Homework Group")
		doc.title = title
		doc.parent_group = parent
		if owner:
			doc.owner = owner
		doc.save()
		return doc

	def test_two_levels_allowed_third_rejected(self):
		root = self._group("EGE")
		subgroup = self._group("October", parent=root.name)
		self.assertEqual(subgroup.parent_group, root.name)

		with self.assertRaises(frappe.ValidationError):
			self._group("Too deep", parent=subgroup.name)

	def test_self_parent_rejected(self):
		root = self._group("Root")
		with self.assertRaises(frappe.ValidationError):
			root.parent_group = root.name
			root.save()

	def test_group_with_children_cannot_get_parent(self):
		root = self._group("Root")
		self._group("Child", parent=root.name)
		second_root = self._group("Second root")

		with self.assertRaises(frappe.ValidationError):
			root.parent_group = second_root.name
			root.save()

	def test_foreign_parent_rejected(self):
		frappe.set_user(self.other_teacher.email)
		foreign_root = self._group("Foreign root")
		frappe.set_user(self.teacher.email)

		with self.assertRaises(frappe.ValidationError):
			self._group("Mine", parent=foreign_root.name)

	def test_delete_only_empty_group(self):
		root = self._group("Root with child")
		self._group("Child", parent=root.name)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("LMS Homework Group", root.name)

		root_with_work = self._group("Root with work")
		homework = frappe.new_doc("LMS Homework")
		homework.title = "Work"
		homework.days = 5
		homework.group = root_with_work.name
		homework.save()
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("LMS Homework Group", root_with_work.name)

	def test_empty_group_deletes(self):
		root = self._group("Lonely")
		frappe.delete_doc("LMS Homework Group", root.name)
		self.assertFalse(frappe.db.exists("LMS Homework Group", root.name))
