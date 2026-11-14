import { describe, expect, it } from 'vitest'
import { submissionReviewStatus } from '@/utils/quizSummary'

// Card #47: the review state of an attempt, resolved the same way on every
// surface. The stored status wins; attempts sat before the field existed
// derive it from their rows; an attempt with no open-answer question never
// awaited anyone and shows no chip at all.
describe('submissionReviewStatus: the two-part review state', () => {
	const openRow = (over: Record<string, unknown> = {}) => ({
		name: 'row-open',
		parent: 'SUB-1',
		question_name: 'Q-OPEN',
		question_type: 'Open Ended',
		graded: 0,
		...over,
	})
	const autoRow = {
		name: 'row-auto',
		parent: 'SUB-1',
		question_name: 'Q-AUTO',
		question_type: 'Choices',
		graded: 1,
	}

	it('an attempt with open answers awaits the teacher', () => {
		expect(
			submissionReviewStatus({ review_status: 'pending_review', result: [autoRow, openRow()] })
		).toBe('pending_review')
	})

	it('the stored final status wins', () => {
		expect(
			submissionReviewStatus({ review_status: 'final', result: [autoRow, openRow({ graded: 0 })] })
		).toBe('final')
	})

	it('a legacy attempt with an ungraded open answer still awaits one', () => {
		expect(submissionReviewStatus({ result: [autoRow, openRow()] })).toBe('pending_review')
	})

	it('a legacy attempt whose open answers all carry verdicts reads finished', () => {
		expect(
			submissionReviewStatus({ result: [autoRow, openRow({ graded: 1 })] })
		).toBe('final')
	})

	it('an attempt without open answers never awaited anyone', () => {
		expect(submissionReviewStatus({ review_status: 'final', result: [autoRow] })).toBeNull()
		// Even a stale status cannot invent a chip for a plain auto quiz.
		expect(
			submissionReviewStatus({ review_status: 'pending_review', result: [autoRow] })
		).toBeNull()
	})

	it('no document, no chip', () => {
		expect(submissionReviewStatus(null)).toBeNull()
		expect(submissionReviewStatus({ result: [] })).toBeNull()
	})
})
