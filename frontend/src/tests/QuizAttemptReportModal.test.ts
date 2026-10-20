import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import QuizAttemptReportModal from '@/components/Assessment/QuizAttemptReportModal.vue'

const state = vi.hoisted(() => ({
	// Every resource read, by url with its params.
	requests: [] as [string, unknown][],
	// The submission doc frappe.client.get resolves with; its graded rows ride
	// in `result`, the shape the report replays.
	doc: null as { result?: unknown[] } | null,
	// Answer keys keyed by question name; an error simulates a denial.
	correctAnswers: {} as Record<string, string[]>,
	correctAnswersError: null as unknown,
}))

vi.mock('frappe-ui', async () => {
	const { reactive } = await import('vue')

	const createResource = (options: any) => {
		let resource: any
		const reload = vi.fn(async () => {
			resource.loading = true
			state.requests.push([options.url, options.makeParams?.()])
			if (options.url === 'frappe.client.get') {
				resource.data = structuredClone(state.doc ?? null)
			}
			if (
				options.url ===
				'lms.lms.doctype.lms_quiz.lms_quiz.get_submission_correct_answers'
			) {
				if (state.correctAnswersError) {
					resource.error = state.correctAnswersError
				} else {
					resource.data = structuredClone(state.correctAnswers)
				}
			}
			resource.loading = false
			return resource.data
		})
		resource = reactive({
			data: null,
			error: null,
			loading: false,
			reload,
			fetch: reload,
		})
		// auto is what keeps the modal's reads flowing on mount; the report
		// only ever reads what its props authorised.
		if (options.auto) void reload()
		return resource
	}

	return {
		createResource,
		Button: {
			template: '<button type="button"><slot /></button>',
		},
		Dialog: {
			props: ['open', 'title', 'actions'],
			template:
				'<div v-if="open"><h2 data-testid="dialog-title">{{ title }}</h2><slot /><footer><button v-for="(action, index) in actions" :key="index" type="button" @click="action.onClick">{{ action.label }}</button></footer></div>',
		},
		Skeleton: { template: '<div><slot /></div>' },
	}
})

vi.stubGlobal('__', (value: string) => value)

// `String.format` is supplied by Frappe in the browser runtime.
String.prototype.format = function (...args: unknown[]) {
	return this.replace(/\{(\d+)\}/g, (_match: string, index: string) =>
		String(args[index])
	)
}

const questionsByName = () => ({
	Q1: { name: 'Q1', question: 'Live question 1', type: 'Choices' },
	Q2: { name: 'Q2', question: 'Live question 2', type: 'Choices' },
	Q3: { name: 'Q3', question: 'Live question 3', type: 'Open Ended' },
})

const attempt = () => ({
	name: 'SUBM-1',
	creation: '2 days ago',
	score: 1,
	score_out_of: 3,
	percentage: 33,
	passing_percentage: 70,
	idx: 2,
})

const mountModal = (
	props: Record<string, unknown> = {},
	doc: { result?: unknown[] } | null = defaultDoc()
) => {
	state.doc = doc
	return mount(QuizAttemptReportModal, {
		props: {
			submissionName: 'SUBM-1',
			attempt: attempt(),
			questionsByName: questionsByName(),
			canViewCorrectAnswers: false,
			...props,
		},
		global: { mocks: { __: (value: string) => value } },
	})
}

// Q1 answered wrong, Q2 skipped, Q3 answered open-ended: the three shapes the
// report has to tell apart.
function defaultDoc() {
	return {
		result: [
			{
				question_name: 'Q1',
				question: 'Question body 1',
				answer: 'Second option 1',
				question_type: 'Choices',
				is_correct: 0,
				marks: 0,
				marks_out_of: 1,
			},
			{
				question_name: 'Q2',
				question: 'Question body 2',
				answer: '',
				question_type: 'Choices',
				is_correct: 0,
				marks: 0,
				marks_out_of: 1,
			},
			{
				question_name: 'Q3',
				question: 'Question body 3',
				answer: 'A written answer',
				question_type: 'Open Ended',
				is_correct: 0,
				marks: 0,
				marks_out_of: 1,
			},
		],
	}
}

const keyReads = () =>
	state.requests.filter(
		([url]) =>
			url === 'lms.lms.doctype.lms_quiz.lms_quiz.get_submission_correct_answers'
	)

beforeEach(() => {
	state.requests = []
	state.doc = null
	state.correctAnswers = {}
	state.correctAnswersError = null
})

describe('QuizAttemptReportModal', () => {
	it('lists only the answered questions, numbered as they were attempted', async () => {
		const wrapper = mountModal()
		await flushPromises()

		expect(wrapper.find('[data-testid="dialog-title"]').text()).toBe(
			'Attempt 2 report'
		)
		expect(wrapper.find('[data-testid="attempt-report-meta"]').text()).toContain(
			'2 days ago'
		)
		expect(wrapper.find('[data-testid="attempt-report-meta"]').text()).toContain(
			'33%'
		)

		const rows = wrapper.findAll('[data-testid="attempt-report-row"]')
		expect(rows).toHaveLength(2)

		// Q1 keeps its attempt position — not its index in the filtered list —
		// so the numbers match what the learner sat.
		expect(rows[0].text()).toContain('Question body 1')
		expect(rows[0].text()).toContain('Q1:')
		expect(
			rows[0].find('[data-testid="attempt-report-status"]')!.text()
		).toBe('Incorrect')

		// Answered open-ended is pending review, never incorrect.
		expect(rows[1].text()).toContain('A written answer')
		expect(rows[1].text()).toContain('Q3:')
		expect(
			rows[1].find('[data-testid="attempt-report-status"]')!.text()
		).toBe('Pending review')

		// The skipped Q2 is absent from the list and counted in the footnote.
		expect(rows.map((row) => row.text())).not.toContain('Question body 2')
		expect(wrapper.find('[data-testid="attempt-report-skipped"]').text()).toBe(
			'1 skipped questions are not included in this report.'
		)
		wrapper.unmount()
	})

	// The resolver regression the owner review caught on the summary (#27):
	// a stored copy the submission never filled must not blank the question.
	it('resolves the question from the live quiz when the stored copy is empty', async () => {
		const doc = defaultDoc()
		doc.result = [
			{
				question_name: 'Q1',
				question: null,
				answer: 'Second option 1',
				question_type: 'Choices',
				is_correct: 0,
			},
			{
				question_name: 'Q2',
				question: '   ',
				answer: 'Second option 2',
				question_type: 'Choices',
				is_correct: 1,
			},
		]
		const wrapper = mountModal({}, doc)
		await flushPromises()

		const rows = wrapper.findAll('[data-testid="attempt-report-row"]')
		expect(rows).toHaveLength(2)
		expect(rows[0].text()).toContain('Live question 1')
		expect(rows[1].text()).toContain('Live question 2')
		// Neither row falls back to a silently blank assignment.
		expect(
			wrapper
				.findAll('[data-testid="attempt-report-question-unavailable"]')
				.length
		).toBe(0)
		wrapper.unmount()
	})

	it('states explicitly when no question text resolves at all', async () => {
		const doc = defaultDoc()
		doc.result = [
			{
				question_name: 'GONE',
				question: '',
				answer: 'An answer to something',
				question_type: 'Choices',
				is_correct: 1,
			},
		]
		const wrapper = mountModal({}, doc)
		await flushPromises()

		const unavailable = wrapper.find(
			'[data-testid="attempt-report-question-unavailable"]'
		)
		expect(unavailable.exists()).toBe(true)
		expect(unavailable.text()).toBe('Question text is not available')
		// The learner's own answer is still shown for the unanswered-question
		// text is not the learner's fault.
		expect(wrapper.find('[data-testid="attempt-report-row"]').text()).toContain(
			'An answer to something'
		)
		wrapper.unmount()
	})

	it('reads an attempt where nothing was answered as empty, not broken', async () => {
		const wrapper = mountModal({}, { result: [] })
		await flushPromises()

		expect(wrapper.text()).toContain(
			'No questions were answered in this attempt.'
		)
		expect(wrapper.find('[data-testid="attempt-report-row"]').exists()).toBe(
			false
		)
		wrapper.unmount()
	})

	it('never requests keys for a viewer the client did not authorise', async () => {
		const wrapper = mountModal({ canViewCorrectAnswers: false })
		await flushPromises()

		expect(keyReads()).toHaveLength(0)
		expect(wrapper.text()).not.toContain('Correct Answer:')
		// The report itself still works without the key endpoint.
		expect(wrapper.findAll('[data-testid="attempt-report-row"]')).toHaveLength(2)
		wrapper.unmount()
	})

	it('renders the keys of an authorised viewer and an em dash where none exist', async () => {
		state.correctAnswers = { Q1: ['First option 1', 'Also right'], Q3: [] }
		const wrapper = mountModal({ canViewCorrectAnswers: true })
		await flushPromises()

		expect(keyReads()).toEqual([
			[
				'lms.lms.doctype.lms_quiz.lms_quiz.get_submission_correct_answers',
				{ submission: 'SUBM-1' },
			],
		])
		const rows = wrapper.findAll('[data-testid="attempt-report-row"]')
		expect(rows[0].text()).toContain('Correct Answer:')
		// Choices join like the review page does.
		expect(rows[0].text()).toContain('First option 1, Also right')
		// An open-ended question has no key text at all: an em dash, not a
		// blank line.
		expect(rows[1].text()).toContain('—')
		wrapper.unmount()
	})

	it('hides the key section when the key request is denied but keeps the report', async () => {
		state.correctAnswersError = new Error(
			'You are not authorized to view correct quiz answers.'
		)
		const wrapper = mountModal({ canViewCorrectAnswers: true })
		await flushPromises()

		expect(wrapper.text()).not.toContain('Correct Answer:')
		expect(wrapper.findAll('[data-testid="attempt-report-row"]')).toHaveLength(2)
		expect(wrapper.text()).toContain('Question body 1')
		wrapper.unmount()
	})

	it('offers a retry when the submission itself cannot be loaded', async () => {
		const wrapper = mountModal({}, null)
		await flushPromises()

		// The mock resources cannot fail on their own, so the failure state is
		// injected the way a network error leaves the real resource.
		const doc = (wrapper.vm as any).submissionDoc
		doc.data = null
		doc.error = new Error('network')
		await flushPromises()

		expect(wrapper.text()).toContain('Could not load report')

		const reads = state.requests.filter(([url]) => url === 'frappe.client.get')
		const retry = wrapper.find('[data-testid="attempt-report-retry"]')
		expect(retry.exists()).toBe(true)
		state.doc = defaultDoc()
		await retry.trigger('click')
		await flushPromises()

		expect(wrapper.text()).not.toContain('Could not load report')
		expect(wrapper.findAll('[data-testid="attempt-report-row"]')).toHaveLength(2)
		const readsAfter = state.requests.filter(
			([url]) => url === 'frappe.client.get'
		)
		expect(readsAfter.length).toBeGreaterThan(reads.length)
		wrapper.unmount()
	})

	it('closes through its footer action', async () => {
		const wrapper = mountModal()
		await flushPromises()

		const close = wrapper
			.findAll('button')
			.find((button) => button.text() === 'Close')
		expect(close).toBeDefined()
		await close!.trigger('click')
		expect(wrapper.emitted('close')).toHaveLength(1)
		wrapper.unmount()
	})
})
