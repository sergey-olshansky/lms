import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import Quiz from '@/components/Quiz.vue'

const resourceState = vi.hoisted(() => ({
	cache: new Map<string, any>(),
	request: vi.fn(),
	// Every resource submit, by url. `request` only records reads.
	submits: [] as string[],
	response: null as any,
	// Per-option verdict check_answer returns: 1 correct, 2 partial, 0 wrong.
	checkAnswer: [] as unknown[],
	// Attempts list rows for frappe.client.get_list, newest first.
	attempts: [] as any[],
	// Submission docs keyed by name for frappe.client.get, the shape
	// frappe.client.get returns: the graded rows ride in `result`.
	submissionDocs: {} as Record<string, any>,
	// What submit_quiz resolves with; null falls back to a passing default.
	submitResponse: null as any,
}))

vi.mock('frappe-ui', async () => {
	const { reactive } = await import('vue')

	const createResource = (options: any) => {
		const key = options.cache ? JSON.stringify(options.cache) : null
		const cached = key ? resourceState.cache.get(key) : null

		if (cached) {
			if (cached.auto) void cached.reload()
			return cached
		}

		let resource: any
		const reload = vi.fn(async () => {
			resource.loading = true
			const params = options.makeParams?.()
			resourceState.request(options.url, params)

			if (options.url === 'lms.lms.utils.get_quiz_with_questions') {
				// Match a real network response: let the remounted component finish setup before the cached resource's original callbacks run.
				await Promise.resolve()

				const raw = structuredClone(resourceState.response)
				const transformed = options.transform?.(raw)
				resource.data = transformed == null ? raw : transformed
				options.onSuccess?.(raw)
			}

			if (options.url === 'lms.lms.doctype.lms_quiz.lms_quiz.check_answer') {
				options.onSuccess?.(resourceState.checkAnswer)
			}

			if (options.url === 'frappe.client.get') {
				const params = options.makeParams?.()
				const raw = structuredClone(
					resourceState.submissionDocs[params?.name] ?? null
				)
				const transformed = options.transform?.(raw)
				resource.data = transformed == null ? raw : transformed
			}

			if (options.url === 'frappe.client.get_list' && options.transform) {
				// The attempts list: the real transform over the mocked rows. It
				// mutates in place and returns nothing, so rows carry the result.
				const rows = structuredClone(resourceState.attempts)
				const transformed = options.transform(rows)
				resource.data = transformed ?? rows
			}

			resource.loading = false
			return resource.data
		})

		resource = reactive({
			auto: options.auto,
			data: null,
			loading: false,
			reload,
			fetch: reload,
			submit: vi.fn((values?: any, handlers?: any) => {
				resourceState.submits.push(options.url)
				if (options.url === 'lms.lms.doctype.lms_quiz.lms_quiz.submit_quiz') {
					const raw = structuredClone(
						resourceState.submitResponse ?? {
							percentage: 100,
							score: 1,
							score_out_of: 1,
							submission: 'SUBM-1',
						}
					)
					resource.data = raw
					handlers?.onSuccess?.(raw)
				}
			}),
			reset: vi.fn(() => {
				resource.data = null
			}),
		})

		if (key) resourceState.cache.set(key, resource)
		if (options.auto) void reload()
		return resource
	}

	const empty = { template: '<div><slot /></div>' }

	return {
		createResource,
		call: vi.fn(),
		toast: { warning: vi.fn(), error: vi.fn() },
		Button: {
			props: { disabled: { type: Boolean, default: false } },
			emits: ['click'],
			template: `<button type="button" :disabled="disabled" @click="$emit('click')"><slot /></button>`,
		},
		Badge: empty,
		// The option controls render their content through a `label` slot, so a
		// bare `<slot />` stub would drop every answer from the markup.
		Checkbox: {
			props: ['modelValue'],
			template: '<div><slot name="label" /><slot /></div>',
		},
		// `Radio` reaches its group through provide/inject and is meaningless
		// outside one, so the stubs keep that contract rather than flattening it.
		RadioGroup: {
			props: ['modelValue', 'name'],
			emits: ['update:modelValue'],
			provide(this: any) {
				return {
					pickRadio: (value: unknown) => this.$emit('update:modelValue', value),
				}
			},
			template: '<div><slot /></div>',
		},
		Radio: {
			props: ['value'],
			inject: ['pickRadio'],
			template:
				'<button type="button" class="radio-option" @click="pickRadio(value)"><slot name="label" /></button>',
		},
		Dialog: {
			props: ['open'],
			template: '<div v-if="open"><slot /></div>',
		},
		FormControl: empty,
		LoadingIndicator: empty,
		Progress: empty,
		Skeleton: empty,
	}
})

vi.mock('frappe-ui/experimental', () => ({
	ListView: { template: '<div><slot /></div>' },
}))

vi.mock('@/components/ProgressBar.vue', () => ({
	default: { template: '<div />' },
}))

vi.mock('@/utils/sanitizeRichHTML', () => ({
	sanitizeRichHTML: (value: string) => value,
}))

vi.mock('@/utils/format', () => ({
	timeAgo: (value: string) => value,
}))

vi.stubGlobal('__', (value: string) => value)

// `String.format` is supplied by Frappe in the browser runtime.
String.prototype.format = function (...args: unknown[]) {
	return this.replace(/\{(\d+)\}/g, (_match: string, index: number) =>
		String(args[index])
	)
}

const quizResponse = () => ({
	quiz: {
		name: 'QUIZ-1',
		title: 'Quiz cache regression',
		duration: 0,
		passing_percentage: 70,
		shuffle_questions: 0,
		show_answers: 0,
		show_submission_history: 0,
		questions: [
			{ question: 'Q1', marks: 1 },
			{ question: 'DELETED', marks: 1 },
		],
	},
	questions_by_name: {
		Q1: {
			name: 'Q1',
			question: 'Visible question body',
			type: 'Choices',
			multiple: 0,
			option_1: 'Correct answer',
			is_correct_1: 1,
		},
	},
})

let mountedQuizzes = 0

// A distinct idPrefix per mount, as mountBlock gives each lesson block.
const mountQuiz = (props: Record<string, unknown> = {}) =>
	mount(Quiz, {
		props: { quizName: 'QUIZ-1', ...props },
		global: {
			config: { idPrefix: `quiz-${++mountedQuizzes}` },
			provide: { $user: { data: { name: 'learner@example.com' } } },
			mocks: { __: (value: string) => value },
		},
	})

beforeEach(() => {
	resourceState.cache.clear()
	resourceState.request.mockReset()
	resourceState.submits.length = 0
	resourceState.response = quizResponse()
	resourceState.checkAnswer = []
	resourceState.attempts = []
	resourceState.submissionDocs = {}
	resourceState.submitResponse = null
	localStorage.clear()
})

describe('Quiz remount', () => {
	it('restores valid questions without extra requests after remounting the same quiz', async () => {
		const first = mountQuiz()
		await flushPromises()

		expect(first.text()).toContain('1 question')
		expect(first.text()).toContain('Start')
		expect(first.text()).not.toContain(
			'This quiz has no questions available yet.'
		)
		expect(resourceState.request).toHaveBeenCalledTimes(1)
		first.unmount()

		const second = mountQuiz()
		await flushPromises()

		expect(resourceState.request).toHaveBeenCalledTimes(2)
		expect(resourceState.request.mock.calls).toEqual([
			['lms.lms.utils.get_quiz_with_questions', { quiz: 'QUIZ-1' }],
			['lms.lms.utils.get_quiz_with_questions', { quiz: 'QUIZ-1' }],
		])
		expect(second.text()).toContain('1 question')
		expect(second.text()).toContain('Start')
		expect(second.text()).not.toContain(
			'This quiz has no questions available yet.'
		)

		const start = second
			.findAll('button')
			.find((button) => button.text() === 'Start Quiz')
		expect(start).toBeDefined()
		await start!.trigger('click')
		await flushPromises()

		expect(second.text()).toContain('Visible question body')
		expect(resourceState.request).toHaveBeenCalledTimes(2)
		second.unmount()
	})
})

const choicesQuizResponse = (count: number) => ({
	quiz: {
		name: 'QUIZ-1',
		title: 'Quiz pager states',
		duration: 0,
		passing_percentage: 70,
		shuffle_questions: 0,
		show_answers: 0,
		show_submission_history: 0,
		questions: Array.from({ length: count }, (_unused, index) => ({
			question: `Q${index + 1}`,
			marks: 1,
		})),
	},
	questions_by_name: Object.fromEntries(
		Array.from({ length: count }, (_unused, index) => [
			`Q${index + 1}`,
			{
				name: `Q${index + 1}`,
				question: `Question body ${index + 1}`,
				type: 'Choices',
				multiple: 0,
				option_1: `First option ${index + 1}`,
				is_correct_1: 1,
				option_2: `Second option ${index + 1}`,
			},
		])
	),
})

const startQuiz = async (wrapper: VueWrapper<any>) => {
	const start = wrapper
		.findAll('button')
		.find((button) => button.text() === 'Start Quiz')
	expect(start).toBeDefined()
	await start!.trigger('click')
	await flushPromises()
}
describe('Quiz in an author preview', () => {
	beforeEach(() => {
		resourceState.response = choicesQuizResponse(1)
	})

	// Guards the lesson-only "Preview only" badge leaking onto the quiz form.
	// Came with this branch's quiz assessment card restyle.
	// Added on feat/assessment-visual-redesign; the badge marks lesson embeds.
	it('shows no Preview only badge on the authoring preview', async () => {
		const wrapper = mountQuiz({ preview: true })
		await flushPromises()

		const header = wrapper.findComponent({ name: 'AssessmentCardHeader' })
		expect(header.exists()).toBe(true)
		expect(header.props('preview')).toBe(false)
		wrapper.unmount()
	})

	// The quiz form's Preview mounts this as it ships, and the button is not the
	// only way in: a timed quiz auto-submits and proctoring submits on a
	// violation. That submission is real.
	it('writes nothing when a submit is triggered anyway', async () => {
		vi.useFakeTimers()
		try {
			const wrapper = mountQuiz({ preview: true })
			await flushPromises()
			await startQuiz(wrapper)
			resourceState.submits.length = 0
			;(wrapper.vm as any).submitQuiz('timeout')
			await vi.advanceTimersByTimeAsync(1000)
			await flushPromises()

			expect(resourceState.submits).not.toContain(
				'lms.lms.doctype.lms_quiz.lms_quiz.submit_quiz'
			)
			wrapper.unmount()
		} finally {
			vi.useRealTimers()
		}
	})
})

describe('Quiz choices', () => {
	// `Check` only renders when the quiz shows answers, and it is the only
	// caller of checkAnswer, so this is the one flow that reaches the verdict
	// markup at all.
	beforeEach(() => {
		const response = choicesQuizResponse(1)
		response.quiz.show_answers = 1
		resourceState.response = response
	})

	const pickFirstAndCheck = async (wrapper: VueWrapper<any>) => {
		await startQuiz(wrapper)
		await wrapper.findAll('input[type="radio"]')[0].trigger('change')
		const check = wrapper.findAll('button').find((b) => b.text() === 'Check')
		expect(check).toBeDefined()
		await check!.trigger('click')
		await flushPromises()
	}

	it('sends the option the learner picks', async () => {
		const wrapper = mountQuiz()
		await flushPromises()
		resourceState.checkAnswer = [1, 0]
		await pickFirstAndCheck(wrapper)

		// The warning toast instead of a request would mean getAnswers() saw
		// nothing selected, i.e. the radio never reached selectedOptions.
		expect(resourceState.request.mock.calls.map((call) => call[0])).toContain(
			'lms.lms.doctype.lms_quiz.lms_quiz.check_answer'
		)
		wrapper.unmount()
	})

	it('marks each option right or wrong once checked, keeping the labels', async () => {
		const wrapper = mountQuiz()
		await flushPromises()
		resourceState.checkAnswer = [1, 0]
		await pickFirstAndCheck(wrapper)

		expect(wrapper.text()).toContain('First option 1')
		expect(wrapper.text()).toContain('Second option 1')
		const firstOption = wrapper.findAll('label')[0]
		expect(firstOption.find('.lucide-check-circle').exists()).toBe(true)
		wrapper.unmount()
	})

	// Guards two quizzes asking the same question sharing one radio group.
	// Broke with this branch's quiz card restyle (radios named by question text).
	// Added on feat/assessment-visual-redesign when quizzes became lesson blocks.
	it('keeps two quizzes on one page in separate radio groups', async () => {
		const first = mountQuiz()
		const second = mountQuiz()
		await flushPromises()
		await startQuiz(first)
		await startQuiz(second)

		const nameOf = (wrapper: VueWrapper<any>) =>
			wrapper.find('input[type="radio"]').attributes('name')
		expect(nameOf(first)).not.toBe(nameOf(second))
		first.unmount()
		second.unmount()
	})
})

// Guards the tutor customisations lost in the upstream sync (PR #3): early
// quiz completion from any question, and checked answers staying locked after
// a page reload instead of being answerable again.
describe('Quiz completion and checked-answer persistence', () => {
	beforeEach(() => {
		const response = choicesQuizResponse(2)
		response.quiz.show_answers = 1
		resourceState.response = response
	})

	it('shows Finish Quiz on the first question and submits directly on quizzes with live checking', async () => {
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)

		expect(wrapper.text()).toContain('Question 1 of 2')
		const finish = wrapper
			.findAll('button')
			.find((button) => button.text() === 'Finish Quiz')
		expect(finish).toBeDefined()
		await finish!.trigger('click')
		await flushPromises()

		expect(resourceState.submits).toContain(
			'lms.lms.doctype.lms_quiz.lms_quiz.submit_quiz'
		)
		wrapper.unmount()
	})

	it('shows Finish Quiz on the first question and asks for confirmation on quizzes without live checking', async () => {
		const response = choicesQuizResponse(2)
		response.quiz.show_answers = 0
		resourceState.response = response
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)

		const finish = wrapper
			.findAll('button')
			.find((button) => button.text() === 'Finish Quiz')
		expect(finish).toBeDefined()
		await finish!.trigger('click')
		await flushPromises()

		// The Dialog stub renders the slot, not its title prop; the body text
		// only exists inside the confirmation dialog.
		expect(wrapper.text()).toContain('You have 2 unattempted questions')
		expect(resourceState.submits).not.toContain(
			'lms.lms.doctype.lms_quiz.lms_quiz.submit_quiz'
		)
		wrapper.unmount()
	})

	it('keeps a checked answer locked after the page is reloaded', async () => {
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)

		resourceState.checkAnswer = [1, 0]
		await wrapper.findAll('input[type="radio"]')[0].trigger('change')
		const check = wrapper.findAll('button').find((b) => b.text() === 'Check')
		expect(check).toBeDefined()
		await check!.trigger('click')
		await flushPromises()

		// The verdict is part of the persisted draft, ready for a reload.
		const draft = JSON.parse(
			localStorage.getItem('lms-quiz-draft:learner@example.com:QUIZ-1')!
		)
		expect(draft.version).toBe(2)
		// Undefined slots round-trip through JSON as null; the array always
		// covers all ten option slots.
		expect(draft.verdicts.Q1.slice(0, 2)).toEqual([1, null])
		expect(draft.verdicts.Q1).toHaveLength(10)
		wrapper.unmount()

		const restored = mountQuiz()
		await flushPromises()

		// The checked question is back: verdict shown, answer picked...
		const feedback = restored.find('[data-testid="quiz-feedback"]')
		expect(feedback.exists()).toBe(true)
		expect(feedback.text()).toBe('Correct')
		const radios = restored.findAll('input[type="radio"]')
		expect((radios[0].element as HTMLInputElement).checked).toBe(true)

		// ...the inputs are locked and Check cannot be pressed again.
		expect(radios[0].attributes('disabled')).toBeDefined()
		expect(
			restored.findAll('button').find((b) => b.text() === 'Check')
		).toBeUndefined()
		restored.unmount()
	})

	it('re-locks the verdict when jumping back to a checked question', async () => {
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)

		resourceState.checkAnswer = [1, 0]
		await wrapper.findAll('input[type="radio"]')[0].trigger('change')
		const check = wrapper.findAll('button').find((b) => b.text() === 'Check')
		await check!.trigger('click')
		await flushPromises()

		const next = wrapper.findAll('button').find((b) => b.text() === 'Next')
		await next!.trigger('click')
		await flushPromises()
		// On the unchecked question the inputs are open and Check is back.
		expect(
			wrapper.findAll('input[type="radio"]')[0].attributes('disabled')
		).toBeUndefined()
		expect(
			wrapper.findAll('button').find((b) => b.text() === 'Check')
		).toBeDefined()

		// Live-checking quizzes have no Previous button; the question is
		// revisited through the component's navigation itself.
		;(wrapper.vm as any).switchQuestion(1)
		await flushPromises()

		// Returning to the checked question restores its verdict and lock.
		expect(
			wrapper.findAll('input[type="radio"]')[0].attributes('disabled')
		).toBeDefined()
		expect(wrapper.find('[data-testid="quiz-feedback"]').text()).toBe('Correct')
		wrapper.unmount()
	})
})

// Guards the quiz card's skeleton, header summary, option rows and verdict.
// Came with this branch's restyle of the quiz block as an assessment card.
// Added on feat/assessment-visual-redesign to pin the new card's states.
describe('Quiz card', () => {
	it('shows a skeleton card until the quiz lands', async () => {
		const wrapper = mountQuiz()
		expect(wrapper.find('[data-testid="quiz-skeleton"]').exists()).toBe(true)

		await flushPromises()
		expect(wrapper.find('[data-testid="quiz-skeleton"]').exists()).toBe(false)
		expect(wrapper.text()).toContain('Start Quiz')
	})

	it('summarises the quiz type, size and pass mark in the header', async () => {
		resourceState.response = choicesQuizResponse(2)
		const wrapper = mountQuiz()
		await flushPromises()

		expect(wrapper.text()).toContain(
			'Multiple choice · 2 questions · pass at 70%'
		)
	})

	it('renders one option row per option and a verdict after Check', async () => {
		const response = choicesQuizResponse(1)
		response.quiz.show_answers = 1
		resourceState.response = response
		resourceState.checkAnswer = [1, 0]
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)

		expect(wrapper.text()).toContain('Question 1 of 1')
		const options = wrapper.findAll('input[type="radio"]')
		expect(options).toHaveLength(2)
		expect(wrapper.find('[data-testid="quiz-feedback"]').exists()).toBe(false)

		await options[0].trigger('change')
		const check = wrapper
			.findAll('button')
			.find((button) => button.text() === 'Check')
		await check!.trigger('click')
		await flushPromises()

		const feedback = wrapper.find('[data-testid="quiz-feedback"]')
		expect(feedback.exists()).toBe(true)
		expect(feedback.text()).toBe('Correct')
		const firstOption = wrapper.findAll('label')[0]
		expect(firstOption.find('.lucide-check-circle').exists()).toBe(true)
	})
})

// Guards task #2: the show_answers flag highlights the question dots during
// the attempt (after Check), on the result screen and on the exhausted-attempts
// card, while show_answers=0 quizzes keep the plain navigation dots.
describe('Quiz question dots', () => {
	const dotsNav = () => 'nav[aria-label="Question navigation"]'
	const gradedNav = () => 'nav[aria-label="Question results"]'

	const showAnswersResponse = (count: number) => {
		const response = choicesQuizResponse(count)
		response.quiz.show_answers = 1
		return response
	}

	const checkFirstOption = async (wrapper: VueWrapper<any>) => {
		await startQuiz(wrapper)
		await wrapper.findAll('input[type="radio"]')[0].trigger('change')
		const check = wrapper.findAll('button').find((b) => b.text() === 'Check')
		expect(check).toBeDefined()
		await check!.trigger('click')
		await flushPromises()
	}

	it('renders the navigation dots during the attempt with live checking on', async () => {
		resourceState.response = showAnswersResponse(2)
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)

		const dots = wrapper.findAll(`${dotsNav()} button`)
		expect(dots).toHaveLength(2)
		expect(dots[0].classes()).toContain('lms-dot-active')
		expect(dots[1].classes()).toContain('lms-dot-untouched')

		// Navigation still works: the dots move between questions.
		await dots[1].trigger('click')
		await flushPromises()
		expect(wrapper.text()).toContain('Question 2 of 2')
		wrapper.unmount()
	})

	it('colours the checked dot green with a text label', async () => {
		resourceState.response = showAnswersResponse(2)
		resourceState.checkAnswer = [1, 0]
		const wrapper = mountQuiz()
		await flushPromises()
		await checkFirstOption(wrapper)

		const dots = wrapper.findAll(`${dotsNav()} button`)
		expect(dots[0].classes()).toContain('bg-surface-green-6')
		expect(dots[0].attributes('aria-label')).toBe('Question 1: Correct')
		expect(dots[0].attributes('title')).toBe('Question 1: Correct')
		// The untouched question keeps its neutral dot.
		expect(dots[1].classes()).not.toContain('bg-surface-green-6')
		wrapper.unmount()
	})

	it('colours the checked dot red when the answer is wrong', async () => {
		resourceState.response = showAnswersResponse(1)
		resourceState.checkAnswer = [0, 1]
		const wrapper = mountQuiz()
		await flushPromises()
		await checkFirstOption(wrapper)

		const dot = wrapper.find(`${dotsNav()} button`)
		expect(dot.classes()).toContain('bg-surface-red-6')
		expect(dot.attributes('aria-label')).toBe('Question 1: Incorrect')
		wrapper.unmount()
	})

	it('colours the dot for a checked User Input answer (PDF trainer shape)', async () => {
		const response = showAnswersResponse(1)
		response.questions_by_name.Q1 = {
			name: 'Q1',
			question: 'Type the answer',
			type: 'User Input',
		}
		resourceState.response = response
		resourceState.checkAnswer = 0
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)
		;(wrapper.vm as any).possibleAnswer = 'wrong guess'
		;(wrapper.vm as any).checkAnswer()
		await flushPromises()

		const dot = wrapper.find(`${dotsNav()} button`)
		expect(dot.classes()).toContain('bg-surface-red-6')
		expect(dot.attributes('aria-label')).toBe('Question 1: Incorrect')
		wrapper.unmount()
	})

	it('locks the answer together with the dot colour', async () => {
		resourceState.response = showAnswersResponse(1)
		resourceState.checkAnswer = [1, 0]
		const wrapper = mountQuiz()
		await flushPromises()
		await checkFirstOption(wrapper)

		const radio = wrapper.find('input[type="radio"]')
		expect(radio.attributes('disabled')).toBeDefined()
		expect(
			wrapper.findAll('button').find((b) => b.text() === 'Check')
		).toBeUndefined()
		expect(wrapper.find(`${dotsNav()} button`).classes()).toContain(
			'bg-surface-green-6'
		)
		wrapper.unmount()
	})

	it('keeps the dot colour across a reload', async () => {
		resourceState.response = showAnswersResponse(1)
		resourceState.checkAnswer = [1, 0]
		const wrapper = mountQuiz()
		await flushPromises()
		await checkFirstOption(wrapper)
		wrapper.unmount()

		const restored = mountQuiz()
		await flushPromises()

		// restoreDraft reopens the checked question with its verdict.
		const dot = restored.find(`${dotsNav()} button`)
		expect(dot.exists()).toBe(true)
		expect(dot.classes()).toContain('bg-surface-green-6')
		expect(dot.attributes('aria-label')).toBe('Question 1: Correct')
		restored.unmount()
	})

	it('clears the colours on a new attempt', async () => {
		resourceState.response = showAnswersResponse(1)
		resourceState.checkAnswer = [1, 0]
		const wrapper = mountQuiz()
		await flushPromises()
		await checkFirstOption(wrapper)

		const finish = wrapper
			.findAll('button')
			.find((button) => button.text() === 'Finish Quiz')
		await finish!.trigger('click')
		await flushPromises()
		expect(wrapper.text()).toContain('Quiz Summary')

		const tryAgain = wrapper
			.findAll('button')
			.find((button) => button.text() === 'Try Again')
		expect(tryAgain).toBeDefined()
		await tryAgain!.trigger('click')
		await flushPromises()
		await startQuiz(wrapper)

		const dot = wrapper.find(`${dotsNav()} button`)
		expect(dot.classes()).not.toContain('bg-surface-green-6')
		expect(dot.attributes('aria-label')).toBe('Question 1')
		wrapper.unmount()
	})

	it('keeps the dots plain without verdicts when show_answers is off', async () => {
		resourceState.response = choicesQuizResponse(2)
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)

		const dots = wrapper.findAll(`${dotsNav()} button`)
		expect(dots).toHaveLength(2)
		await wrapper.findAll('input[type="radio"]')[0].trigger('change')
		const next = wrapper.findAll('button').find((b) => b.text() === 'Next')
		await next!.trigger('click')
		await flushPromises()

		// Answered navigation is distinct from current and graded correctness.
		expect(dots[0].classes()).toContain('lms-dot-attempted')
		expect(dots[1].attributes('aria-current')).toBe('page')
		expect(next!.classes()).toContain('lms-quiz-secondary')
		expect(
			wrapper
				.findAll('button')
				.find((b) => b.text() === 'Finish Quiz')!
				.classes()
		).toContain('lms-quiz-primary')
		wrapper.vm.markForReview(true, 1)
		await flushPromises()
		expect(dots[0].attributes('data-flagged')).toBe('true')
		expect(dots[0].attributes('aria-label')).toContain('Mark for review')
		for (const dot of dots) {
			expect(dot.classes()).not.toContain('bg-surface-green-6')
			expect(dot.classes()).not.toContain('bg-surface-red-6')
		}
		expect(
			wrapper.findAll('button').find((b) => b.text() === 'Check')
		).toBeUndefined()
		wrapper.unmount()
	})
})

describe('Quiz result screen verdict dots', () => {
	it('replays the submission verdicts, marking unattempted questions wrong', async () => {
		const response = choicesQuizResponse(3)
		response.quiz.show_answers = 1
		resourceState.response = response
		resourceState.submissionDocs['SUBM-1'] = {
			name: 'SUBM-1',
			result: [
				{ question_name: 'Q1', is_correct: 1 },
				{ question_name: 'Q2', is_correct: 0 },
			],
		}
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)

		const finish = wrapper
			.findAll('button')
			.find((button) => button.text() === 'Finish Quiz')
		await finish!.trigger('click')
		await flushPromises()

		expect(wrapper.text()).toContain('Quiz Summary')
		const graded = wrapper.findAll(`nav[aria-label="Question results"] span`)
		expect(graded).toHaveLength(3)
		expect(graded[0].classes()).toContain('bg-surface-green-6')
		expect(graded[0].attributes('aria-label')).toBe('Question 1: Correct')
		expect(graded[1].classes()).toContain('bg-surface-red-6')
		expect(graded[1].attributes('aria-label')).toBe('Question 2: Incorrect')
		// No row for Q3: it counts as wrong, not as a missing dot.
		expect(graded[2].classes()).toContain('bg-surface-red-6')
		wrapper.unmount()
	})

	it('shows no graded dots when show_answers is off', async () => {
		vi.useFakeTimers()
		try {
			resourceState.response = choicesQuizResponse(1)
			const wrapper = mountQuiz()
			await flushPromises()
			await startQuiz(wrapper)
			;(wrapper.vm as any).submitQuiz()
			await vi.advanceTimersByTimeAsync(1000)
			await flushPromises()

			expect(wrapper.text()).toContain('Quiz Summary')
			expect(wrapper.find('nav[aria-label="Question results"]').exists()).toBe(
				false
			)
			wrapper.unmount()
		} finally {
			vi.useRealTimers()
		}
	})
})

describe('Quiz exhausted attempts verdict dots', () => {
	it('verdicts the latest attempt on the card that blocks new ones', async () => {
		const response = choicesQuizResponse(2)
		response.quiz.show_answers = 1
		response.quiz.max_attempts = 2
		resourceState.response = response
		resourceState.attempts = [
			{
				name: 'SUBM-2',
				creation: '2026-10-08 10:00:00',
				score: 1,
				score_out_of: 2,
				percentage: 50,
				passing_percentage: 85,
			},
			{
				name: 'SUBM-1',
				creation: '2026-10-07 10:00:00',
				score: 0,
				score_out_of: 2,
				percentage: 0,
				passing_percentage: 85,
			},
		]
		resourceState.submissionDocs['SUBM-2'] = {
			name: 'SUBM-2',
			result: [
				{ question_name: 'Q1', is_correct: 1 },
				{ question_name: 'Q2', is_correct: 0 },
			],
		}
		const wrapper = mountQuiz()
		await flushPromises()

		expect(wrapper.text()).toContain("You've used all 2 attempts")
		const graded = wrapper.findAll('nav[aria-label="Question results"] span')
		expect(graded).toHaveLength(2)
		expect(graded[0].classes()).toContain('bg-surface-green-6')
		expect(graded[1].classes()).toContain('bg-surface-red-6')
		wrapper.unmount()
	})
})
