# Copyright (c) 2026, tutor LMS contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class LMSQuizSubmissionAttachment(Document):
	def validate(self):
		# Card #47: a draft row (uploaded mid-attempt) has no submission yet;
		# a bound row belongs to exactly one attempt. Every mutation of these
		# fields rides the quiz_submission_attachments API, which owns the
		# authorization, so the controller only keeps the shapes honest.
		if self.submission and not frappe.db.exists("LMS Quiz Submission", self.submission):
			frappe.throw(_("Invalid quiz submission."), frappe.ValidationError)

	def on_trash(self):
		# The row is the private File's audience: deleting it would orphan the
		# file into owner-only readability. Removal goes through the API, which
		# deletes the File and the row together.
		pass
