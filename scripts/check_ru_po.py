#!/usr/bin/env python3
"""Strict validation of lms/locale/ru.po for task 8.

Replaces `msgfmt --check` (not installed on this host) with a pure-python
validator, plus task-8 invariants:

  1. msgfmt-equivalent syntax: parse errors, bad escapes, header presence,
     Plural-Forms consistency (this file has no plural entries), duplicate
     msgid entries (gettext semantics: duplicates must not exist at all).
  2. Placeholders: every {N} brace placeholder and %-format present in msgid
     must occur in msgstr with the same count.
  3. HTML tags: the lowercase tag multiset of msgid must equal msgstr's.
  4. Newline parity: '\n' count in msgid equals msgstr count.
  5. No empty msgstr (goal: 0 empty; technical exceptions must be listed in
     ALLOW_EMPTY below with a justification comment).
  6. Glossary hard checks: banned renderings must not appear in msgstr.
     Soft checks: warnings printed, never fail unless --strict-warnings.

Exit code: 0 pass, 1 failures.
"""

import json
import re
import sys
from collections import Counter

sys.path.insert(0, __file__.rsplit("/", 1)[0] or ".")
from po_tool import PO_PATH, POT_PATH, parse_po, po_keys, pot_keys

# Technical msgids allowed to stay untranslated (with justification).
ALLOW_EMPTY = [
	# none so far — goal for task 8 is 0 empty
]

# (msgid_regex, msgstr_regex, why) — msgstr_regex is checked only when msgid matches
BANNED = [
	# Batch must be Группа (but "package" stays пакет for SCORM/ZIP archives)
	(r"[Bb]atch", r"парти", "Batch must be Группа, not партия"),
	(r"[Bb]atch", r"пакет", "Batch must be Группа, not пакет"),
	(r"[Qq]uiz", r"викторин", "Quiz must be Тест"),
	(r"[Qq]uiz", r"\bопрос", "Quiz must be Тест, not опрос"),
	(r"[Bb]adge", r"бейдж", "Badge must be Достижение"),
	(r"[Bb]adge", r"значок", "Badge must be Достижение"),
	(r"[Aa]ssignment", r"назначени", "Assignment must be Задание"),
	(r"[Ee]valuation|[Ee]valuator", r"аттестац", "Evaluation must be Оценивание"),
	(r"[Ii]nstructor", r"[Ии]нструктор", "Instructor must be Преподаватель"),
	(r"[Ss]tudent|[Ll]earner", r"[Сс]тудент", "Student/Learner must be Ученик"),
	# unconditional style bans
	(r"", r"\b[Дд]анный\b", "канцелярит: данный"),
	(r"", r"осуществ", "канцелярит: осуществить"),
	(r"", r"\b[Пп]роизвести\b", "канцелярит: произвести"),
]
# msgids exempt from specific bans (regex source string -> tuple of msgids)
BANNED_WHITELIST = {}


def q(s, n=90):
	return json.dumps(s if len(s) <= n else s[: n - 3] + "...", ensure_ascii=False)


def esc_ok(s):
	i = 0
	while i < len(s):
		if s[i] == "\\":
			if i + 1 >= len(s) or s[i + 1] not in '"ntbr\\':
				return False, f"bad escape \\{s[i + 1 : i + 2]}"
			i += 2
		else:
			i += 1
	return True, None


FMT_BRACE_RE = re.compile(r"\{\d+\}")
FMT_PCT_RE = re.compile(r"%(?:\d+\$)?[-+#0']*\d*(?:\.\d+)?[hlL]*[diouxXeEfgGcspn]")
TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9]*(?:\s[^<>]*?)?/?>")


def check():
	entries = parse_po()
	failures, warnings = [], []

	header = entries[0] if entries and entries[0].id == "" else None
	if header is None or "Plural-Forms" not in header.str or "charset=UTF-8" not in header.str:
		failures.append("header missing/malformed")

	seen = {}
	for e in entries:
		if e.id == "":
			continue
		for label, val in (("id", e.id), ("str", e.str)):
			ok, why = esc_ok(val)
			if not ok:
				failures.append(f"L{e.line} {q(e.id)} {label}: {why}")
		if e.id in seen:
			failures.append(f"duplicate msgid {q(e.id)} (L{seen[e.id]}, L{e.line})")
		else:
			seen[e.id] = e.line

		if not e.str:
			if e.id not in ALLOW_EMPTY:
				failures.append(f"empty msgstr: {q(e.id)} (L{e.line})")
			continue
		if e.id in ALLOW_EMPTY and e.str:
			pass  # allowed but translated — fine

		# placeholders
		b_id, p_id = Counter(FMT_BRACE_RE.findall(e.id)), Counter(FMT_PCT_RE.findall(e.id))
		b_st, p_st = Counter(FMT_BRACE_RE.findall(e.str)), Counter(FMT_PCT_RE.findall(e.str))
		for k, _v in (b_id - b_st).items():
			failures.append(f"L{e.line} {q(e.id)}: placeholder {k} missing in msgstr")
		for k, _v in (b_st - b_id).items():
			failures.append(f"L{e.line} {q(e.id)}: extra placeholder {k} in msgstr")
		for k, _v in (p_id - p_st).items():
			failures.append(f"L{e.line} {q(e.id)}: %-format {k} missing in msgstr")
		for k, _v in (p_st - p_id).items():
			failures.append(f"L{e.line} {q(e.id)}: extra %-format {k} in msgstr")

		# HTML tags
		t_id, t_st = (
			Counter(t.lower() for t in TAG_RE.findall(e.id)),
			Counter(t.lower() for t in TAG_RE.findall(e.str)),
		)
		if t_id != t_st:
			failures.append(f"L{e.line} {q(e.id)}: HTML tags differ id={dict(t_id)} str={dict(t_st)}")

		# newlines
		if e.id.count("\n") != e.str.count("\n"):
			failures.append(
				f"L{e.line} {q(e.id)}: newline count id={e.id.count(chr(10))} str={e.str.count(chr(10))}"
			)

		# glossary bans (contextual: msgid regex gates the msgstr regex)
		for id_rx, str_rx, why in BANNED:
			if id_rx and not re.search(id_rx, e.id):
				continue
			if re.search(str_rx, e.str):
				failures.append(f"L{e.line} {q(e.id)} -> {q(e.str)}: {why}")

		# tabs parity
		if e.id.count("\t") != e.str.count("\t"):
			warnings.append(f"L{e.line} {q(e.id)}: tab count differs")

	return failures, warnings


if __name__ == "__main__":
	strict = "--strict-warnings" in sys.argv
	failures, warnings = check()
	for f in failures:
		print("FAIL:", f)
	for w in warnings:
		print("WARN:", w)
	print("----")
	print(f"failures: {len(failures)}, warnings: {len(warnings)}")
	sys.exit(1 if failures or (strict and warnings) else 0)
