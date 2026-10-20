/** What `lms.lms.utils.get_quiz_with_questions` returns, as the quiz card reads it. */

export type QuizQuestionType = 'Choices' | 'User Input' | 'Open Ended'

/** One LMS Question. `option_N` / `explanation_N` run from 1 to 10. */
export type QuizQuestionDetails = {
	name: string
	question: string
	type: QuizQuestionType
	multiple?: 0 | 1
} & {
	[key: `option_${number}` | `explanation_${number}`]: string | null | undefined
}

/** A row of the quiz's question table. */
export interface QuizQuestionRow {
	name?: string
	question: string
	marks?: number
	// Copied from the question when the quiz is saved.
	type?: QuizQuestionType
}

export interface QuizDetails {
	name: string
	title: string
	duration: number
	questions?: QuizQuestionRow[]
	passing_percentage?: number
	max_attempts?: number
	show_answers?: 0 | 1
	show_submission_history?: 0 | 1
	shuffle_questions?: 0 | 1
	limit_questions_to?: number
	enable_proctoring?: 0 | 1
	max_violations: number
	enable_negative_marking?: 0 | 1
	marks_to_cut?: number
	enable_scheduling?: 0 | 1
	schedule_start?: string | null
	schedule_start_iso?: string | null
	schedule_end?: string | null
	schedule_end_iso?: string | null
}

export interface QuizWithQuestions {
	quiz?: QuizDetails
	questions_by_name?: Record<string, QuizQuestionDetails>
}

/** A past attempt, as the history list shows it. A type, not an interface, so it
 * passes as a ResponsiveListView row. */
export type QuizAttempt = {
	name: string
	creation: string
	score: number
	score_out_of: number
	percentage: number
	passing_percentage: number
	idx?: number
}

/** What `lms_quiz.submit_quiz` returns. */
export interface QuizSubmissionResult {
	pass: boolean
	submission?: string
	is_open_ended?: boolean | 0 | 1
	percentage: number
	score: number
	score_out_of: number
}

/** A child row of a submission's result table, the shape `frappe.client.get`
 * returns it in. `is_correct` is binary: 1 marks a fully correct answer;
 * `answer` is the learner's own response ("" once the server normalised a
 * skipped question), never a correct answer or key. */
export interface QuizResultRow {
	name: string
	parent: string
	question_name: string | null
	question_type?: QuizQuestionType
	is_correct?: 0 | 1
	question?: string | null
	answer?: string | null
	marks?: number
	marks_out_of?: number
}

/** The verdict of one row of the post-submit attempt summary (#27). */
export type QuizAttemptRowStatus = 'correct' | 'incorrect' | 'skipped' | 'pending'

/** One rendered row of the post-submit attempt summary (#27): the question
 * text, the learner's own answer and its verdict — never the answer key. */
export interface QuizSummaryRow {
	number: number
	questionName: string
	question: string
	answer: string
	status: QuizAttemptRowStatus
}

/** One rendered row of the per-attempt report modal (#27): a summary row plus
 * the marks the attempt's row carries. The answer key is never part of the
 * row — it is rendered separately, and only for viewers the server
 * authorises. */
export interface QuizReportRow {
	number: number
	questionName: string
	question: string
	answer: string
	status: QuizAttemptRowStatus
	marks?: number
	marks_out_of?: number
}

/** 1 correct, 2 partially correct, 0 wrong; undefined for an untouched option. */
export type AnswerVerdict = 0 | 1 | 2 | undefined

/** A learner's answer to one question, as kept in localStorage until submit. */
export interface SavedAnswer {
	question_name: string
	answer: (string | null | undefined)[]
}

export type ViolationSeverity = 'violation' | 'warning'

/** A proctoring event as the card lists it. */
export interface ViolationEvent {
	eventType: string
	severity: ViolationSeverity
	timestamp: string
	frame: string | null
}

/** A proctoring event as `get_quiz_violation_logs` stores it. */
export interface StoredViolationRow {
	event_type: string
	severity: ViolationSeverity
	timestamp: string
	frame: string | null
}
