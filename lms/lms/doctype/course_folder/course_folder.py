# Copyright (c) 2026, FOSS United and Contributors
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class CourseFolder(Document):
	# pylint: disable=no-member
	def validate(self):
		self.validate_chapter()

	def validate_chapter(self):
		"""The folder must belong to a section of its own course.

		Denormalising course/chapter the way Course Lesson does keeps access
		checks and subtree cleanup off the child-table rows.
		"""
		if not self.chapter:
			return
		chapter = frappe.db.get_value(
			"Course Chapter", self.chapter, ["name", "course"], as_dict=True
		)
		if not chapter:
			frappe.throw(
				_("Section {0} not found").format(self.chapter), frappe.DoesNotExistError
			)
		if self.course and chapter.course and chapter.course != self.course:
			frappe.throw(_("A folder can only live inside a section of the same course."))

	def on_trash(self):
		"""Folder deletion takes its images with it.

		Only files this folder owns (attached to it) are removed, so a File row
		linked in from elsewhere survives; the Lesson Reference child rows that
		place the folder in its section go too.
		"""
		owned = []
		for row in self.images or []:
			if not (row.image and frappe.db.exists("File", row.image)):
				continue
			owner = frappe.db.get_value(
				"File",
				row.image,
				["attached_to_doctype", "attached_to_name"],
				as_dict=True,
			)
			if (
				owner
				and owner.attached_to_doctype == self.doctype
				and owner.attached_to_name == self.name
			):
				owned.append(row.image)
		# Image rows and placement rows go before the File docs: each image row
		# is a Link to its File, and frappe's link check refuses to delete a
		# File a child row still points at (delete_folder_image clears its row
		# first for the same reason).
		frappe.db.delete("Folder Image Reference", {"parent": self.name})
		frappe.db.delete("Lesson Reference", {"folder": self.name})
		for file_name in owned:
			frappe.delete_doc("File", file_name, ignore_permissions=True)
