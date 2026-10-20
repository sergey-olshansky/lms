import { beforeEach, describe, expect, it, vi } from 'vitest'

import { attemptRowStatus, attemptRowStatusLabel } from '@/utils/quizSummary'

vi.stubGlobal('__', (message: string) => message)

// The truth table behind the post-submit attempt summary (#27). The server
// stores skipped answers as "" with is_correct = 0, and open-ended rows as
// is_correct = 0 until an instructor grades them, so the order of the checks
// — pending before skipped before the binary verdict — is the behaviour under
// test, not just the individual rows.
describe('attemptRowStatus', () => {
	beforeEach(() => {
		vi.clearAllMocks()
	})

	it('marks a fully correct stored verdict correct', () => {
		expect(
			attemptRowStatus({
				question_type: 'Choices',
				answer: 'First option',
				is_correct: 1,
			})
		).toBe('correct')
	})

	it('marks an answered wrong response incorrect', () => {
		expect(
			attemptRowStatus({
				question_type: 'Choices',
				answer: 'Second option',
				is_correct: 0,
			})
		).toBe('incorrect')
		expect(
			attemptRowStatus({
				question_type: 'User Input',
				answer: 'Paris',
				is_correct: 0,
			})
		).toBe('incorrect')
	})

	it('marks an empty answer skipped whatever the stored verdict says', () => {
		// The server normalises skipped questions to "" with is_correct = 0;
		// the row carries no answer, so it cannot read as incorrect.
		expect(
			attemptRowStatus({ question_type: 'Choices', answer: '', is_correct: 0 })
		).toBe('skipped')
		expect(
			attemptRowStatus({ question_type: 'User Input', answer: '', is_correct: 0 })
		).toBe('skipped')
	})

	it('treats a missing answer as skipped for older rows', () => {
		expect(attemptRowStatus({ question_type: 'Choices', is_correct: 0 })).toBe(
			'skipped'
		)
		expect(
			attemptRowStatus({ question_type: 'Choices', answer: null, is_correct: 0 })
		).toBe('skipped')
	})

	it('treats a whitespace-only answer as skipped', () => {
		expect(
			attemptRowStatus({
				question_type: 'User Input',
				answer: '   ',
				is_correct: 0,
			})
		).toBe('skipped')
	})

	it('marks an answered open-ended question pending review, not incorrect', () => {
		// Open-ended rows keep is_correct = 0 at submit time; grading comes
		// later, so the summary must not report a false incorrect.
		expect(
			attemptRowStatus({
				question_type: 'Open Ended',
				answer: '<p>My essay</p>',
				is_correct: 0,
			})
		).toBe('pending')
	})

	it('marks a blank open-ended question skipped — nothing to review', () => {
		expect(
			attemptRowStatus({
				question_type: 'Open Ended',
				answer: '',
				is_correct: 0,
			})
		).toBe('skipped')
		expect(
			attemptRowStatus({ question_type: 'Open Ended', answer: ' ', is_correct: 0 })
		).toBe('skipped')
	})
})

describe('attemptRowStatusLabel', () => {
	it('gives every status a word, so colour is never the only cue', () => {
		expect(attemptRowStatusLabel('correct')).toBe('Correct')
		expect(attemptRowStatusLabel('incorrect')).toBe('Incorrect')
		expect(attemptRowStatusLabel('skipped')).toBe('Skipped')
		expect(attemptRowStatusLabel('pending')).toBe('Pending review')
	})
})
