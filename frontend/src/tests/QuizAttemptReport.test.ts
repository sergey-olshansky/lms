import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import QuizAttemptReport from '@/components/Assessment/QuizAttemptReport.vue'

vi.mock('frappe-ui', () => ({
	Button: {
		props: ['label'],
		template: '<button type="button"><slot /></button>',
	},
	Skeleton: { template: '<div data-testid="skeleton"><slot /></div>' },
}))

vi.stubGlobal('__', (s: string) => s)
if (!('format' in String.prototype)) {
	// eslint-disable-next-line no-extend-native
	Object.defineProperty(String.prototype, 'format', {
		value: function (...args: string[]) {
			return this.replace(/\{(\d+)\}/g, (_: string, i: string) => args[i] ?? '')
		},
	})
}

// The graded rows of one attempt, in the shape frappe.client.get returns:
// a live-resolvable question, a stored-only question, an open-ended answer
// awaiting a grade, and a skipped question.
const results = () => [
	{
		name: 'row-1',
		question_name: 'Q1',
		question: 'Stored snapshot one',
		answer: 'First option 1',
		question_type: 'Choices',
		is_correct: 1,
		marks: 1,
		marks_out_of: 1,
	},
	{
		name: 'row-2',
		question_name: 'Q2',
		question: '',
		answer: 'An essay',
		question_type: 'Open Ended',
		is_correct: 0,
		marks: 0,
		marks_out_of: 4,
	},
	{
		name: 'row-3',
		question_name: 'GONE',
		question: 'Stored copy of a deleted question',
		answer: 'wrong answer',
		question_type: 'Choices',
		is_correct: 0,
		marks: 0,
		marks_out_of: 1,
	},
	{
		name: 'row-4',
		question_name: 'Q4',
		question: 'Stored snapshot four',
		answer: '',
		question_type: 'User Input',
		is_correct: 0,
		marks: 0,
		marks_out_of: 1,
	},
]

const questionsByName = () => ({
	Q1: { name: 'Q1', question: 'Live body one', type: 'Choices' },
	Q4: { name: 'Q4', question: 'Live body four', type: 'User Input' },
})

const emptyKeys = () => ({ data: null, loading: false, error: null })

const mountReport = (props: Record<string, unknown> = {}) =>
	mount(QuizAttemptReport, {
		props: {
			results: results(),
			questionsByName: questionsByName(),
			canViewCorrectAnswers: false,
			correctAnswers: emptyKeys(),
			...props,
		},
		global: { mocks: { __: (s: string) => s } },
	})

describe('QuizAttemptReport', () => {
	it('replays the answered questions with strict verdicts and attempt numbering', () => {
		const wrapper = mountReport()
		const rows = wrapper.findAll('[data-testid="attempt-report-row"]')
		expect(rows).toHaveLength(3)

		// Live body first, stored snapshot as fallback (#27's resolver).
		expect(rows[0].text()).toContain('Q1:')
		expect(rows[0].text()).toContain('Live body one')
		expect(rows[0].text()).not.toContain('Stored snapshot one')

		// The skipped fourth row is out of the list, counted below, and the
		// numbers keep the positions of the whole attempt.
		expect(rows[2].text()).toContain('Q3:')
		expect(wrapper.find('[data-testid="attempt-report-skipped"]').text()).toContain(
			'1 skipped questions'
		)

		const statuses = wrapper
			.findAll('[data-testid="attempt-report-status"]')
			.map((chip) => chip.text())
		expect(statuses).toEqual(['Correct', 'Pending review', 'Incorrect'])
		wrapper.unmount()
	})

	it('states a missing question body explicitly, never a blank line', () => {
		const wrapper = mountReport()
		expect(
			wrapper.find('[data-testid="attempt-report-question-unavailable"]').exists()
		).toBe(true)
		wrapper.unmount()
	})

	it('renders the answer-key section only behind the authorization prop', () => {
		const hidden = mountReport()
		expect(hidden.text()).not.toContain('Correct Answer:')
		hidden.unmount()

		const shown = mountReport({
			canViewCorrectAnswers: true,
			correctAnswers: { data: { Q1: ['First option 1'] }, loading: false, error: null },
		})
		expect(shown.text()).toContain('Correct Answer:')
		expect(shown.text()).toContain('First option 1')
		shown.unmount()
	})

	it('keeps its loading, error and empty states distinct', async () => {
		const loading = mountReport({ results: null, loading: true })
		expect(loading.findAll('[data-testid="skeleton"]').length).toBeGreaterThan(0)
		loading.unmount()

		const failed = mountReport({ results: null, error: new Error('Denied') })
		expect(failed.text()).toContain('Could not load report')
		await failed
			.find('[data-testid="attempt-report-retry"]')
			.trigger('click')
	// The retry is the parent's resource to refetch; only the event matters.
		expect(failed.emitted('retry')).toHaveLength(1)
		failed.unmount()

		const empty = mountReport({ results: [] })
		expect(empty.text()).toContain(
			'No questions were answered in this attempt.'
		)
		empty.unmount()
	})

	it('hands the raw row to a marks slot so a review page can grade in place', () => {
		const wrapper = mountReport({
			results: [results()[1]],
		})
		wrapper.unmount()

		const grading = mount(QuizAttemptReport, {
			props: {
				results: [results()[1]],
				questionsByName: questionsByName(),
				canViewCorrectAnswers: false,
				correctAnswers: emptyKeys(),
			},
			slots: {
				marks:
					'<input data-testid="grade" type="number" :value="resultRow.marks" />',
			},
			global: { mocks: { __: (s: string) => s } },
		})
		const input = grading.find('[data-testid="grade"]')
		expect(input.exists()).toBe(true)
		// The slot receives the document's own row, not the display copy.
		expect((input.element as HTMLInputElement).value).toBe('0')
		grading.unmount()
	})
})
