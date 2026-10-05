#!/usr/bin/env bash
set -euo pipefail

title="${1:-}"
pattern='^(fix|feat|chore|docs|refactor|test|ci)(\([[:alnum:]_.:/-]+\))?!?: .+'

if [[ ! "$title" =~ $pattern ]]; then
	echo "Invalid pull request title: $title" >&2
	echo 'Expected a Conventional Commit title, for example: feat(courses): add progress filters' >&2
	exit 1
fi
