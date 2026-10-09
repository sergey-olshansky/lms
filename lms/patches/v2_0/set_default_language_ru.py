import frappe


def execute():
	"""Default the site language to Russian.

	Owner decision (task #8 rework, 2026-10-09): the sign-in page and every
	guest surface must greet visitors in Russian without waiting for a user
	preference. System Settings.language is the site-wide fallback Frappe uses
	for guests and the login page, so that is the one knob to turn.

	Idempotent: re-running keeps an explicitly chosen language and only fills
	the English placeholder (""). Per-user language choices are untouched.
	"""
	current = frappe.db.get_single_value("System Settings", "language")
	if current == "ru":
		return
	if current:
		# An administrator has deliberately picked another language for the
		# site; respect that rather than overriding on every migrate.
		return
	frappe.db.set_single_value("System Settings", "language", "ru")
	frappe.db.commit()
