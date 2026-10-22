# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""A reusable homework compilation: named, dated, and holding selected course sources.

The template is a draft until it is assigned. An empty compilation may be saved as a
draft, but the assignment API refuses to issue one (task #35 spec, section 3.3).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

MAX_HOMEWORK_DAYS = 3650

# source_type -> the Link field that must carry the value
SOURCE_FIELDS = {
	"Lesson": "lesson",
	"Quiz": "quiz",
	"Assignment": "assignment",
}


class LMSHomework(Document):
	def validate(self):
		self.validate_title()
		self.validate_days()
		self.validate_group()
		self.validate_items()

	def validate_title(self):
		self.title = (self.title or "").strip()
		if not self.title:
			frappe.throw(_("Homework title cannot be empty."))

	def validate_days(self):
		"""A positive whole number of days. Zero, fractions, negatives and overflow
		are all refused here, no matter what the client sent."""
		if self.days is None:
			frappe.throw(_("Number of days is required."))
		try:
			days = cint(self.days)
		except (TypeError, ValueError):
			frappe.throw(_("Number of days must be a whole number."))
		if str(self.days).strip() not in {str(days), f"{days}.0", f"{days}.00"}:
			frappe.throw(_("Number of days must be a whole number."))
		if days < 1:
			frappe.throw(_("Number of days must be at least 1."))
		if days > MAX_HOMEWORK_DAYS:
			frappe.throw(_("Number of days cannot exceed {0}.").format(MAX_HOMEWORK_DAYS))
		self.days = days

	def validate_group(self):
		if not self.group:
			return
		group_owner = frappe.db.get_value("LMS Homework Group", self.group, "owner")
		if not group_owner:
			frappe.throw(_("Group {0} does not exist.").format(self.group))
		if group_owner != self.owner:
			frappe.throw(_("You can only file homework into your own groups."))

	def validate_items(self):
		"""The canonical source invariant on EVERY save path (B01): raw REST or
		Desk writes pass the same resolution as the named API, so a forged row
		never lands in the database. Exact duplicate sources are dropped
		server-side: selecting a lesson on its own and through its chapter must
		still yield a single requirement (A07). An empty draft stays legal."""
		seen = set()
		kept = []
		for row in self.items:
			field = SOURCE_FIELDS.get(row.source_type)
			if not field or not row.get(field):
				frappe.throw(_("Material row {0} is missing its source.").format(row.idx))
			key = (row.source_type, row.get(field))
			if key in seen:
				continue
			seen.add(key)
			self._check_canonical_item(row)
			kept.append(row)
		self.items = kept

	def _check_canonical_item(self, row):
		"""One row re-resolved from the database: existence, SCORM refusal, the
		real course and the session teacher's right to source from it (B01).

		The stored ``course`` must match the material's actual course -- a Link
		proves existence, never belonging -- and the resolved course must be one
		the session user may pick from, exactly like ``canonicalize_selection``.
		Runs for the named API and for direct document writes alike."""
		from lms.lms.homework_sources import _canonical_item, can_source_from

		canonical = _canonical_item(row.source_type, row.get(SOURCE_FIELDS[row.source_type]))
		resolved_course = canonical["course"]
		if row.course and row.course != resolved_course:
			frappe.throw(
				_("{0} does not belong to the course stored on its row.").format(
					frappe.bold(canonical["label"])
				),
				frappe.ValidationError,
			)
		if not can_source_from(resolved_course):
			frappe.throw(
				_("You cannot pick materials from the course {0}.").format(
					frappe.bold(resolved_course)
				),
				frappe.PermissionError,
			)

	def on_trash(self):
		"""A compilation that has ever been issued can only be archived, not deleted:
		its assignments must stay readable (spec section 8.1)."""
		if frappe.db.exists("LMS Homework Assignment", {"homework": self.name}):
			frappe.throw(
				_("This homework has been assigned before. Archive it instead of deleting."),
				frappe.PermissionError,
			)
