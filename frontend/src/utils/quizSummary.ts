import type { QuizAttemptRowStatus, QuizQuestionType } from '@/types/quiz'

// The quiz card's header line, shared by the learner card and the lesson
// editor's preview so the two always agree.
export const formatQuizSubtitle = (
	types: (QuizQuestionType | undefined)[],
	passingPercentage?: number
): string => {
	const parts: string[] = []
	if (types.length && types.every((type) => type == 'Choices')) {
		parts.push(__('Multiple choice'))
	} else if (types.length && types.every((type) => type != 'Choices')) {
		parts.push(__('Open ended'))
	}
	const count = types.length
	parts.push(`${count} ${count == 1 ? __('question') : __('questions')}`)
	if (passingPercentage) {
		parts.push(__('pass at {0}%').format(passingPercentage))
	}
	return parts.join(' · ')
}

export const attemptsLeftLabel = (attemptsLeft: number): string =>
	__('{0} {1} left').format(
		attemptsLeft,
		attemptsLeft == 1 ? __('attempt') : __('attempts')
	)

export const attemptsAllowedLabel = (maxAttempts: number): string =>
	__('{0} {1} allowed').format(
		maxAttempts,
		maxAttempts == 1 ? __('attempt') : __('attempts')
	)

// The verdict of one graded row of a submission's result table, as the
// post-submit attempt summary shows it (#27). The order matters:
//
// - An open-ended answer that actually carries content has no verdict until an
// instructor grades it, so it must read as pending review, never as
// incorrect, even though the server stores `is_correct = 0` at submit time —
// unless the grade already sits at full marks, which is exactly what
// "credited" means once a full-mark answer is carried into a retake (#32).
// - An empty answer is a skipped question whatever its type — the server
// normalises skipped answers to "", and a blank open-ended answer has nothing
// to review, so "pending" would promise a review of nothing.
// - Only then does the stored binary verdict decide correct vs incorrect.
//
// The answer is the learner's own response; nothing here can see the key.
export const attemptRowStatus = (row: {
	question_type?: QuizQuestionType | string | null
	answer?: string | null
	is_correct?: 0 | 1 | boolean | null
	marks?: number | null
	marks_out_of?: number | null
}): QuizAttemptRowStatus => {
	const answered = !!(row.answer ?? '').trim()
	if (row.question_type == 'Open Ended' && answered) {
		const marks = row.marks ?? 0
		const marksOutOf = row.marks_out_of ?? 0
		return marksOutOf > 0 && marks >= marksOutOf ? 'correct' : 'pending'
	}
	if (!answered) return 'skipped'
	return row.is_correct ? 'correct' : 'incorrect'
}

// The chip label carries the verdict in words, so the colour is never the only
// cue. Correct/Incorrect reuse the keys the live verdicts already translate;
// Skipped and Pending review are new #27 keys.
export const attemptRowStatusLabel = (status: QuizAttemptRowStatus): string =>
	({
		correct: __('Correct'),
		incorrect: __('Incorrect'),
		skipped: __('Skipped'),
		pending: __('Pending review'),
	})[status]

// The resolved question body of one graded row, shared by the per-attempt
// report modal (#27). The LIVE question text from questions_by_name comes
// first — it is the very field the in-quiz body renders
// (v-safe-html:rich="questions_by_name[name].question"), so it is the only
// copy guaranteed complete: rich markup and embedded task images included,
// and current with the question the learner can still read in the quiz. The
// submission's stored copy (LMS Quiz Result.question, filled from the quiz
// question row's question_detail fetch_from snapshot at grading time) is the
// fallback for questions the live map no longer carries — a quiz edited
// after the attempt — because that snapshot can be empty (quizzes authored
// or migrated outside the form never fill it) or stale (authored before the
// question gained its image or wording), which is exactly how the report
// lost the question body and its task imagery (#27 owner report). Both empty
// resolves to "", which the callers must render as the explicit unavailable
// state, never as a silently blank line. Other fields of questionsByName
// (options, keys, explanations) are never read here.
export const resolveAttemptQuestionText = (
	row: { question?: string | null; question_name?: string | null },
	questionsByName: Record<string, { question?: string | null }>
): string =>
	(questionsByName[row.question_name ?? '']?.question ?? '').trim() ||
	(row.question ?? '').trim() ||
	''
