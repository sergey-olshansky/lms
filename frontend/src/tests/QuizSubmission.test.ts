import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QuizSubmission from '@/pages/QuizSubmission.vue'

const state = vi.hoisted(() => ({
	// Answer keys, as get_submission_correct_answers resolves them.
	keys: { data: null as any, loading: false, error: null as any },
	// The quiz payload get_quiz_with_questions resolves with; its live
	// question texts are what the report's resolver reads (#31).
	quizQuestions: { data: null as any, loading: false, error: null as any },
	// Every params object the live-questions request was fetched with: the
	// endpoint requires the quiz, so a paramless fetch is a broken report.
	liveQuestionsParams: [] as unknown[],
	// The graded rows of the submission document under review.
	result: [] as Record<string, unknown>[],
	// The submission's quiz, member and counters.
	docExtras: {} as Record<string, unknown>,
	push: vi.fn(),
	open: vi.fn(),
}))

vi.mock('frappe-ui', () => {
	const createResource = (options: any) => {
		if (
			options.url ===
			'lms.lms.doctype.lms_quiz.lms_quiz.get_submission_correct_answers'
		) {
			return state.keys
		}
		if (options.url === 'lms.lms.utils.get_quiz_with_questions') {
			const resource = {
				data: null as any,
				loading: false,
				error: null as any,
				fetch: vi.fn(() => {
					const params = options.makeParams?.()
					state.liveQuestionsParams.push(params)
					if (!params?.quiz) {
						// The endpoint's own contract: no quiz, no questions.
						resource.error = new Error('Quiz must be a string.')
						return
					}
					resource.data = state.quizQuestions.data
				}),
			}
			return resource
		}
		// The violation log and the member image are sidebar furniture; their
		// empty shapes are all the report path needs from them.
		return { data: [], loading: false, error: null, fetch: vi.fn() }
	}
	return {
		createDocumentResource: () => ({
			doc: {
				quiz: 'quiz-1',
				quiz_title: 'The Quiz',
				member: 'student@example.com',
				member_name: 'Student',
				score: 1,
				score_out_of: 4,
				percentage: 25,
				creation: '2026-10-19 10:20:00',
				violation_count: 0,
				...state.docExtras,
				get result() {
					return state.result
				},
			},
			save: { submit: vi.fn() },
		}),
		createResource,
		FormControl: {
			props: ['modelValue'],
			emits: ['update:modelValue'],
			template:
				'<input type="number" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
		},
		Badge: { template: '<div><slot /></div>' },
		Button: { template: '<button type="button"><slot /></button>' },
		Breadcrumbs: { template: '<nav />' },
		Popover: { template: '<div><slot /></div>' },
		Skeleton: { template: '<div><slot /></div>' },
		Avatar: {
			props: ['label'],
			template: '<span data-testid="avatar">{{ label }}</span>',
		},
		usePageMeta: vi.fn(),
		toast: { error: vi.fn() },
	}
})
vi.mock('vue-router', () => ({ useRouter: () => ({ push: state.push }) }))
vi.mock('@/stores/session', () => ({ sessionStore: () => ({ brand: {} }) }))
vi.mock('@/composables/useKeyboardShortcuts', () => ({
	useKeyboardShortcuts: vi.fn(),
	saveShortcut: () => ({}),
}))
vi.mock('@/components/Layouts/pages/PageHeader.vue', () => ({
	default: {
		props: ['breadcrumbs'],
		template: '<header><slot name="actions" /></header>',
	},
}))
vi.mock('@/components/Layouts/pages/PageBody.vue', () => ({
	default: { template: '<main><slot /></main>' },
}))
vi.mock('@/components/HeaderButton.vue', () => ({
	default: {
		props: ['label'],
		emits: ['click'],
		template:
			'<button type="button" data-testid="header-button" @click="$emit(\'click\')">{{ label }}</button>',
	},
}))
vi.mock('@/components/ShortcutTooltip.vue', () => ({
	default: { template: '<span><slot /></span>' },
}))

vi.stubGlobal('__', (s: string) => s)
// translation.js installs String.prototype.format at app boot; the report
// renders __('Q{0}:').format(...) and never reaches Vue without it.
if (!('format' in String.prototype)) {
	// eslint-disable-next-line no-extend-native
	Object.defineProperty(String.prototype, 'format', {
		value: function (...args: string[]) {
			return this.replace(/\{(\d+)\}/g, (_: string, i: string) => args[i] ?? '')
		},
	})
}

// One row of every shape the report must tell apart: a correct objective
// answer, a wrong one, an answered open-ended answer awaiting a grade, and a
// skipped question. The stored question snapshot is empty everywhere so the
// live question map is the only body the resolver can find (#31).
const gradedRows = () => [
	{
		name: 'row-1',
		question_name: 'q1',
		question: '',
		answer: '21',
		question_type: 'User Input',
		is_correct: 1,
		marks: 2,
		marks_out_of: 2,
	},
	{
		name: 'row-2',
		question_name: 'q2',
		question: '',
		answer: 'wrong',
		question_type: 'Choices',
		is_correct: 0,
		marks: 0,
		marks_out_of: 1,
	},
	{
		name: 'row-3',
		question_name: 'q3',
		question: '',
		answer: 'an essay worth reading',
		question_type: 'Open Ended',
		is_correct: 0,
		marks: 0,
		marks_out_of: 3,
	},
	{
		name: 'row-4',
		question_name: 'q4',
		question: '',
		answer: '',
		question_type: 'Choices',
		is_correct: 0,
		marks: 0,
		marks_out_of: 1,
	},
]

const liveQuestions = () => ({
	data: {
		quiz: { name: 'quiz-1' },
		questions_by_name: {
			q1: { name: 'q1', question: '<p>Live body one</p>', type: 'User Input' },
			q2: { name: 'q2', question: 'Live body two', type: 'Choices' },
			q3: { name: 'q3', question: 'Live body three', type: 'Open Ended' },
			q4: { name: 'q4', question: 'Live body four', type: 'Choices' },
		},
	},
	loading: false,
	error: null,
})

const render = () =>
	mount(QuizSubmission, {
		props: { submission: 'SUBM-1' },
		global: {
			provide: { $user: { data: { is_system_manager: true } } },
			mocks: { __: (s: string) => s },
		},
	})

beforeEach(() => {
	state.keys = { data: { q1: ['21'], q2: ['right'] }, loading: false, error: null }
	state.quizQuestions = liveQuestions()
	state.liveQuestionsParams = []
	state.result = gradedRows()
	state.docExtras = {}
	state.push.mockReset()
	state.open.mockReset()
	vi.stubGlobal('open', state.open)
})

describe('Quiz submission review', () => {
	it('renders the shared report: live question bodies, own answers, strict verdicts', () => {
		const wrapper = render()
		const rows = wrapper.findAll('[data-testid="attempt-report-row"]')
		// Skipped row-4 is filtered; the three answered rows remain, numbered
		// by their position in the whole attempt (#31, 1:1 with the learner
		// report).
		expect(rows).toHaveLength(3)
		expect(rows[0].text()).toContain('Q1:')
		expect(rows[0].text()).toContain('Live body one')
		expect(rows[0].text()).toContain('Your answer:')
		expect(rows[0].text()).toContain('21')
		expect(rows[0].text()).toContain('Correct Answer:')
		expect(rows[0].text()).toContain('21')

		const statuses = wrapper
			.findAll('[data-testid="attempt-report-status"]')
			.map((chip) => chip.text())
		expect(statuses).toEqual(['Correct', 'Incorrect', 'Pending review'])
		expect(wrapper.find('[data-testid="attempt-report-skipped"]').text()).toContain(
			'1 skipped questions are not included in this report.'
		)
		wrapper.unmount()
	})

	it('keeps the grader hand: pending marks editable, verdicts strict', async () => {
		const wrapper = render()
		const inputs = wrapper.findAll('input[type="number"]')
		// Only the open-ended answer awaits a grade; the checked ones are
		// figures, not fields.
		expect(inputs).toHaveLength(1)
		await inputs[0].setValue('2')
		expect(state.result[2].marks).toBe('2')
		wrapper.unmount()
	})

	it('fetches the live questions with the submission\'s own quiz', () => {
		const wrapper = render()
		// The endpoint requires the quiz; a paramless fetch would throw and
		// leave the report on stale stored snapshots.
		expect(state.liveQuestionsParams).toEqual([{ quiz: 'quiz-1' }])
		wrapper.unmount()
	})

	it('falls back to the stored snapshot when no live text resolves', () => {
		state.result[0].question = 'Stored snapshot one'
		state.quizQuestions = {
			data: { quiz: { name: 'quiz-1' }, questions_by_name: {} },
			loading: false,
			error: null,
		}
		const wrapper = render()
		expect(wrapper.text()).toContain('Stored snapshot one')
		wrapper.unmount()
	})

	it('offers the PDF of this attempt through the review endpoint', () => {
		const wrapper = render()
		const pdf = wrapper
			.findAll('[data-testid="header-button"]')
			.find((button) => button.text() === 'Download PDF')
		expect(pdf).toBeDefined()
		pdf!.trigger('click')
		// openExternal adds the noopener guard the whole app opens windows with.
		expect(state.open).toHaveBeenCalledWith(
			'/api/method/lms.lms.doctype.lms_quiz.quiz_attempt_report.download_attempt_report_pdf?submission=SUBM-1',
			'_blank',
			'noopener'
		)
		wrapper.unmount()
	})

	it('does not render executable HTML in an answer key', () => {
		state.keys.data = {
			q1: ['<img src="x" onerror="alert(1)"><script>alert(2)</script>21'],
		}
		const wrapper = render()
		expect(wrapper.find('script').exists()).toBe(false)
		expect(wrapper.find('img').attributes('onerror')).toBeUndefined()
		wrapper.unmount()
	})

	it('hides the key section, not the report, when keys cannot load', () => {
		state.keys = { data: null, loading: false, error: new Error('Denied') }
		const wrapper = render()
		expect(wrapper.text()).not.toContain('Correct Answer:')
		expect(wrapper.findAll('[data-testid="attempt-report-row"]')).toHaveLength(3)
		wrapper.unmount()
	})
})
