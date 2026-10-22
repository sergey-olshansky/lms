# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Library groups: a teacher's own folders, at most two levels deep.

`Все работы -> Группа -> Подгруппа -> Домашняя работа`. The root "All works" and the
homework itself are not group levels, so a subgroup can never become a parent.
Groups are not courses and are deliberately not stored in Course Chapter.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from lms.lms.utils import has_moderator_role

MAX_GROUP_DEPTH = 2


class LMSHomeworkGroup(Document):
	def validate(self):
		self.title = (self.title or "").strip()
		if not self.title:
			frappe.throw(_("Group title cannot be empty."))
		self.validate_parent()

	def validate_parent(self):
		if not self.parent_group:
			return
		if self.parent_group == self.name:
			frappe.throw(_("A group cannot be its own parent."))

		parent = frappe.db.get_value(
			"LMS Homework Group", self.parent_group, ["name", "parent_group", "owner"], as_dict=True
		)
		if not parent:
			frappe.throw(_("Parent group {0} does not exist.").format(self.parent_group))

		# Owner check: a teacher nests inside their own tree only. Privileged staff
		# (Moderator/System Manager) may organise anyone's groups.
		if parent.owner != self.owner and not _is_privileged():
			frappe.throw(_("You can only use your own groups."))

		# Depth: the parent must be a first-level group, and the moved group must not
		# bring children of its own -- both halves of "depth of the whole subtree".
		if parent.parent_group:
			frappe.throw(
				_("Nested groups can only be two levels deep: {0} already has a parent group.").format(
					parent.name
				)
			)
		if frappe.db.exists("LMS Homework Group", {"parent_group": self.name}):
			frappe.throw(
				_("Group {0} has subgroups and cannot be nested inside another group.").format(self.title)
			)

	def on_trash(self):
		"""A group can only be deleted when it is empty; the UI offers to move the
		contents out first."""
		if frappe.db.exists("LMS Homework Group", {"parent_group": self.name}):
			frappe.throw(_("Delete the subgroups of {0} first.").format(self.title))
		if frappe.db.exists("LMS Homework", {"group": self.name}):
			frappe.throw(
				_("Group {0} still has homeworks. Move them to another group first.").format(self.title)
			)


def _is_privileged() -> bool:
	user = frappe.session.user
	return user == "Administrator" or "System Manager" in frappe.get_roles(user) or has_moderator_role(user)
