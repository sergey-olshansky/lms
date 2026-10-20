import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import Quiz from '@/components/Quiz.vue'

const resourceState = vi.hoisted(() => ({
	cache: new Map<string, any>(),
	request: vi.fn(),
	// Every resource submit, by url with its params. `request` only records
	// reads.
	submits: [] as [string, unknown][],
	response: null as any,
	// Per-option verdict check_answer returns: 1 correct, 2 partial, 0 wrong.
	checkAnswer: [] as unknown[] | number,
	// Attempts list rows for frappe.client.get_list, newest first.
	attempts: [] as any[],
	// Answer keys get_submission_correct_answers resolves with, keyed by
	// question name; an Error simulates a denied or failed key request.
	correctAnswers: {} as Record<string, string[]> | Error,
	// Question names the learner has already credited (#32); the retake pool
	// is the quiz's questions minus these.
	creditedQuestions: [] as string[],
	// Submission docs keyed by name for frappe.client.get, the shape
	// frappe.client.get returns: the graded rows ride in `result`.
	submissionDocs: {} as Record<string, any>,
	// What submit_quiz resolves with; null falls back to a passing default.
	submitResponse: null as any,
	// A server-side submission rejection, if this test needs to model one.
	submitError: null as any,
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

			if (
				options.url ===
				'lms.lms.doctype.lms_quiz.lms_quiz.get_submission_correct_answers'
			) {
				if (resourceState.correctAnswers instanceof Error) {
					resource.error = resourceState.correctAnswers
				} else {
					resource.data = structuredClone(resourceState.correctAnswers)
				}
			}

			if (
				options.url ===
				'lms.lms.doctype.lms_quiz.lms_quiz.get_quiz_credited_questions'
			) {
				resource.data = structuredClone(resourceState.creditedQuestions)
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
				resourceState.submits.push([options.url, options.makeParams?.(values)])
				if (options.url === 'lms.lms.doctype.lms_quiz.lms_quiz.submit_quiz') {
					if (resourceState.submitError) {
						handlers?.onError?.(resourceState.submitError)
						return
					}
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
		// Renders the body slot, the title and the footer actions, so a
		// mounted dialog's buttons are reachable the way frappe-ui draws them.
		Dialog: {
			props: ['open', 'title', 'actions'],
			template:
				'<div v-if="open" data-testid="dialog-stub"><slot />{{ title }}<button v-for="(action, index) in actions" :key="index" type="button" @click="action.onClick">{{ action.label }}</button></div>',
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

// The submission history renders through ResponsiveListView, whose real
// implementation leans on frappe-ui/experimental list internals the mock
// above does not provide. The stub keeps the contract Quiz.vue's template
// relies on — one cell slot per column per row — so the #27 report action is
// exercised at the Quiz level; the real list keeps its own test file.
vi.mock('@/components/ResponsiveListView.vue', () => ({
	default: {
		name: 'ResponsiveListView',
		props: ['columns', 'rows', 'rowKey', 'titleKey', 'options'],
		template: `
			<div data-testid="submission-history">
				<div v-for="row in rows" :key="row[rowKey]" data-testid="attempt-row">
					<template v-for="column in columns" :key="column.key">
						<slot name="cell" :column="column" :row="row" :value="row[column.key]" />
					</template>
				</div>
			</div>
		`,
	},
}))

vi.mock('@/components/ProgressBar.vue', () => ({
	default: { template: '<div />' },
}))

// The rich text editor drags in ProseMirror and its upload composable, and
// the open-ended summaries here read stored rows, not live editor content.
vi.mock('@/components/RichTextEditor.vue', () => ({
	default: defineComponent({
		name: 'RichTextEditor',
		emits: ['change'],
		render: () => h('div', { class: 'editor' }),
	}),
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

// A distinct idPrefix per mount, as mountBlock gives each lesson block. The
// session user defaults to the learner; the report tests pass a staff shape.
const mountQuiz = (
	props: Record<string, unknown> = {},
	options = {},
	sessionUser: Record<string, unknown> = { name: 'learner@example.com' }
) =>
	mount(Quiz, {
		...options,
		props: { quizName: 'QUIZ-1', ...props },
		global: {
			config: { idPrefix: `quiz-${++mountedQuizzes}` },
			provide: { $user: { data: sessionUser } },
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
	resourceState.correctAnswers = {}
	resourceState.creditedQuestions = []
	resourceState.submissionDocs = {}
	resourceState.submitResponse = null
	resourceState.submitError = null
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
		// The quiz and the learner's credited set (#32) — one request each.
		expect(resourceState.request).toHaveBeenCalledTimes(2)
		first.unmount()

		const second = mountQuiz()
		await flushPromises()

		expect(resourceState.request).toHaveBeenCalledTimes(4)
		expect(resourceState.request.mock.calls).toEqual([
			['lms.lms.utils.get_quiz_with_questions', { quiz: 'QUIZ-1' }],
			[
				'lms.lms.doctype.lms_quiz.lms_quiz.get_quiz_credited_questions',
				{ quiz: 'QUIZ-1' },
			],
			['lms.lms.utils.get_quiz_with_questions', { quiz: 'QUIZ-1' }],
			[
				'lms.lms.doctype.lms_quiz.lms_quiz.get_quiz_credited_questions',
				{ quiz: 'QUIZ-1' },
			],
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
		expect(resourceState.request).toHaveBeenCalledTimes(4)
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

// Submitting on a quiz without live checking defers the POST by 500ms so the
// last answer can reach localStorage first (see submitQuiz in Quiz.vue).
const submitWithoutLiveChecking = async (wrapper: VueWrapper<any>) => {
	vi.useFakeTimers()
	try {
		;(wrapper.vm as any).submitQuiz()
		await vi.advanceTimersByTimeAsync(1000)
	} finally {
		vi.useRealTimers()
	}
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

			expect(
				resourceState.submits.some(([url]) => url === 'lms.lms.doctype.lms_quiz.lms_quiz.submit_quiz')
			).toBe(false)
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

		expect(
			resourceState.submits.some(([url]) => url === 'lms.lms.doctype.lms_quiz.lms_quiz.submit_quiz')
		).toBe(true)
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

		// The confirmation is not auto-submitted: the dialog is open with its
		// body text, and nothing has been submitted until its action is used.
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
			.find((button) => button.text() === 'Retake')
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

describe('Quiz result screen after submission', () => {
	// #1102/#1103 item 2: no per-question report is displayed automatically
	// after a quiz is answered — the learner opens reports only from each
	// attempt's «Report» button in the history table. The overall score line,
	// the pending notice and the retry/history mechanics stay untouched.
	it('keeps the overall score and shows no automatic per-question report', async () => {
		resourceState.response = choicesQuizResponse(2)
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)
		await submitWithoutLiveChecking(wrapper)

		expect(wrapper.text()).toContain('Quiz Summary')
		expect(wrapper.text()).toContain(
			'You got 100% correct answers with a score of 1 out of 1'
		)
		expect(wrapper.text()).toContain('Retake')
		// The per-question rows are gone from the result screen; the graded
		// submission is not even fetched on the learner's behalf anymore.
		expect(wrapper.find('[data-testid="quiz-summary-row"]').exists()).toBe(
			false
		)
		const submissionReads = resourceState.request.mock.calls.filter(
			([url]) => url === 'frappe.client.get'
		)
		expect(submissionReads).toHaveLength(0)
		wrapper.unmount()
	})

	it('shows the retake action only while attempts remain', async () => {
		const response = choicesQuizResponse(2)
		response.quiz.max_attempts = 2
		resourceState.response = response
		resourceState.attempts = [
			{
				name: 'SUBM-1',
				creation: '2026-10-08 10:00:00',
				score: 0,
				score_out_of: 2,
				percentage: 0,
				passing_percentage: 70,
			},
		]
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)
		await submitWithoutLiveChecking(wrapper)

		const retakeLabel = 'Retake'
		expect(wrapper.text()).toContain(retakeLabel)

		// Simulate the server history now including this attempt: the result
		// remains visible, but the action must disappear at the configured limit.
		resourceState.attempts = [
			...resourceState.attempts,
			{
				name: 'SUBM-2',
				creation: '2026-10-09 10:00:00',
				score: 1,
				score_out_of: 2,
				percentage: 50,
				passing_percentage: 70,
			},
		]
		await wrapper.vm.attempts.reload()
		await flushPromises()
		expect(wrapper.text()).toContain('Quiz Summary')
		expect(wrapper.text()).not.toContain(retakeLabel)
		wrapper.unmount()
	})

	it('closes the active form when the server rejects the last attempt', async () => {
		const response = choicesQuizResponse(2)
		response.quiz.max_attempts = 2
		resourceState.response = response
		resourceState.attempts = [
			{
				name: 'SUBM-1',
				creation: '2026-10-08 10:00:00',
				score: 0,
				score_out_of: 2,
				percentage: 0,
				passing_percentage: 70,
			},
		]
		resourceState.submitError = {
			message: 'MaximumAttemptsExceededError',
			messages: ["You've used all 2 attempts"],
		}
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)

		// Another tab spent the last attempt while this form was open.
		resourceState.attempts = [
			...resourceState.attempts,
			{
				name: 'SUBM-2',
				creation: '2026-10-09 10:00:00',
				score: 1,
				score_out_of: 2,
				percentage: 50,
				passing_percentage: 70,
			},
		]
		await submitWithoutLiveChecking(wrapper)

		expect(wrapper.text()).toContain("You've used all 2 attempts")
		expect(wrapper.text()).not.toContain('Finish Quiz')
		expect(wrapper.text()).not.toContain('Retake')
		wrapper.unmount()
	})

	it('keeps the pending-review notice for open-ended attempts without a per-question report', async () => {
		const response = choicesQuizResponse(2)
		response.questions_by_name.Q2.type = 'Open Ended'
		resourceState.response = response
		resourceState.submitResponse = {
			pass: false,
			submission: 'SUBM-1',
			is_open_ended: 1,
			percentage: 50,
			score: 0.5,
			score_out_of: 2,
		}
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)
		await submitWithoutLiveChecking(wrapper)

		// The overall outcome stays, with the review notice beside it.
		expect(wrapper.text()).toContain(
			'You got 50% correct answers with a score of 0.5 out of 2'
		)
		expect(wrapper.text()).toContain(
			'Open-ended answers are pending instructor review.'
		)
		// The per-question reading, pending included, is the report modal's
		// to show — never the result screen's.
		expect(wrapper.find('[data-testid="quiz-summary-row"]').exists()).toBe(
			false
		)
		const submissionReads = resourceState.request.mock.calls.filter(
			([url]) => url === 'frappe.client.get'
		)
		expect(submissionReads).toHaveLength(0)
		wrapper.unmount()
	})

	it('drops the pending notice when the submission is not open-ended', async () => {
		resourceState.response = choicesQuizResponse(1)
		resourceState.submitResponse = {
			pass: true,
			submission: 'SUBM-1',
			is_open_ended: 0,
			percentage: 100,
			score: 1,
			score_out_of: 1,
		}
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)
		await submitWithoutLiveChecking(wrapper)

		expect(wrapper.text()).not.toContain(
			'Open-ended answers are pending instructor review.'
		)
		expect(wrapper.find('[data-testid="quiz-summary-row"]').exists()).toBe(
			false
		)
		wrapper.unmount()
	})

	it('focuses the summary heading after submitting', async () => {
		resourceState.response = choicesQuizResponse(1)
		const wrapper = mountQuiz({}, { attachTo: document.body })
		await flushPromises()
		await startQuiz(wrapper)
		await submitWithoutLiveChecking(wrapper)

		const heading = wrapper.find('h2[tabindex="-1"]')
		expect(heading.exists()).toBe(true)
		expect(heading.text()).toContain('Quiz Summary')
		// Moving focus announces the summary instead of staying on Finish.
		expect(document.activeElement?.textContent).toContain('Quiz Summary')
		// The result line is announced politely once it appears.
		expect(
			wrapper.find('[role="status"][aria-live="polite"]').exists()
		).toBe(true)
		wrapper.unmount()
	})

	it('lets the learner try again without a report in between', async () => {
		const response = choicesQuizResponse(2)
		response.quiz.show_answers = 1
		resourceState.response = response
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)

		const finish = wrapper
			.findAll('button')
			.find((button) => button.text() === 'Finish Quiz')
		await finish!.trigger('click')
		await flushPromises()
		expect(wrapper.text()).toContain('Quiz Summary')

		const tryAgain = wrapper
			.findAll('button')
			.find((button) => button.text() === 'Retake')
		expect(tryAgain).toBeDefined()
		await tryAgain!.trigger('click')
		await flushPromises()

		// Back on the start card: a new attempt can begin, no report shown.
		expect(wrapper.text()).toContain('Start Quiz')
		expect(wrapper.find('[data-testid="quiz-summary-row"]').exists()).toBe(
			false
		)
		wrapper.unmount()
	})
})

describe('Quiz exhausted attempts card', () => {
	it('blocks new attempts without an automatic report, keeping the Report action', async () => {
		const response = choicesQuizResponse(2)
		response.quiz.max_attempts = 2
		response.quiz.show_submission_history = 1
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
				{
					question_name: 'Q1',
					question: null,
					answer: 'First option 1',
					question_type: 'Choices',
					is_correct: 1,
				},
			],
		}
		const wrapper = mountQuiz()
		await flushPromises()

		expect(wrapper.text()).toContain("You've used all 2 attempts")
		// Nothing replays the latest attempt on its own — not the rows, not
		// even a fetch of the submission doc.
		expect(wrapper.find('[data-testid="quiz-summary-row"]').exists()).toBe(
			false
		)
		expect(resourceState.request.mock.calls.filter(
			([url]) => url === 'frappe.client.get'
		)).toHaveLength(0)
		// The history table is the one way in: its Report action opens the
		// modal for the attempt the learner picks.
		const buttons = wrapper.findAll('[data-testid="attempt-report-button"]')
		expect(buttons).toHaveLength(2)
		await buttons[0].trigger('click')
		await flushPromises()
		expect(wrapper.find('[data-testid="attempt-report-row"]').exists()).toBe(
			true
		)
		wrapper.unmount()
	})
})

describe('Quiz submission history report action', () => {
	// A quiz whose history table shows: max_attempts makes the card load the
	// attempts list, show_submission_history makes it render them (#27).
	const historyQuizResponse = () => {
		const response = choicesQuizResponse(2)
		response.quiz.max_attempts = 5
		response.quiz.show_submission_history = 1
		return response
	}

	const twoAttempts = () => [
		{
			name: 'SUBM-2',
			creation: '2026-10-08 10:00:00',
			score: 1,
			score_out_of: 2,
			percentage: 50,
			passing_percentage: 70,
		},
		{
			name: 'SUBM-1',
			creation: '2026-10-07 10:00:00',
			score: 0,
			score_out_of: 2,
			percentage: 0,
			passing_percentage: 70,
		},
	]

	const gradedRows = () => [
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
	]

	const keyReads = () =>
		resourceState.request.mock.calls.filter(
			([url]) =>
				url === 'lms.lms.doctype.lms_quiz.lms_quiz.get_submission_correct_answers'
		)

	beforeEach(() => {
		resourceState.response = historyQuizResponse()
		resourceState.attempts = twoAttempts()
		resourceState.submissionDocs['SUBM-2'] = {
			name: 'SUBM-2',
			result: gradedRows(),
		}
		resourceState.submissionDocs['SUBM-1'] = {
			name: 'SUBM-1',
			result: gradedRows().slice(0, 1),
		}
	})

	it('opens the report of exactly the clicked attempt', async () => {
		const wrapper = mountQuiz()
		await flushPromises()

		const buttons = wrapper.findAll('[data-testid="attempt-report-button"]')
		expect(buttons).toHaveLength(2)
		// Newest first: the list numbers the newest attempt 1; the label names
		// the attempt so N identical buttons stay distinguishable.
		expect(buttons[0].attributes('aria-label')).toBe('Report for attempt 1')
		expect(buttons[1].attributes('aria-label')).toBe('Report for attempt 2')

		await buttons[1].trigger('click')
		await flushPromises()

		// The older row opened its own submission, not the latest one.
		expect(resourceState.request).toHaveBeenCalledWith('frappe.client.get', {
			doctype: 'LMS Quiz Submission',
			name: 'SUBM-1',
		})
		const rows = wrapper.findAll('[data-testid="attempt-report-row"]')
		expect(rows).toHaveLength(1)
		expect(rows[0].text()).toContain('Question body 1')
		expect(
			rows[0].find('[data-testid="attempt-report-status"]')!.text()
		).toBe('Incorrect')
		// The metadata line carries the attempt, not another one.
		expect(wrapper.find('[data-testid="attempt-report-meta"]').text()).toContain(
			'2026-10-07 10:00:00'
		)
		wrapper.unmount()
	})

	// #27 owner correction: the modal must carry the question body itself —
	// text and embedded task image — not only the verdict chips. The live
	// quiz data is the resolver's first source, and a graded row whose stored
	// copy was never filled (quizzes authored outside the form) still shows
	// the complete body the learner answered.
	it('renders the question text and its task image from the live quiz data', async () => {
		const response = historyQuizResponse()
		response.questions_by_name.Q1.question =
			'<p>Study the <strong>diagram</strong> below.</p><img src="/files/task-diagram.png" alt="Task diagram">'
		resourceState.response = response
		resourceState.submissionDocs['SUBM-2'] = {
			name: 'SUBM-2',
			result: [
				{
					question_name: 'Q1',
					question: null,
					answer: 'Second option 1',
					question_type: 'Choices',
					is_correct: 0,
					marks: 0,
					marks_out_of: 1,
				},
			],
		}
		const wrapper = mountQuiz()
		await flushPromises()

		await wrapper.findAll('[data-testid="attempt-report-button"]')[0].trigger('click')
		await flushPromises()

		const row = wrapper.find('[data-testid="attempt-report-row"]')
		expect(row.exists()).toBe(true)
		// The question text renders beside its number, not only a verdict.
		expect(row.text()).toContain('Study the')
		expect(row.text()).toContain('diagram')
		expect(row.find('strong').text()).toBe('diagram')
		// The embedded task image is present, src and alt intact.
		const img = row.find('img')
		expect(img.exists()).toBe(true)
		expect(img.attributes('src')).toBe('/files/task-diagram.png')
		expect(img.attributes('alt')).toBe('Task diagram')
		// Verdict and the learner's own answer remain on the row.
		expect(row.find('[data-testid="attempt-report-status"]').text()).toBe(
			'Incorrect'
		)
		expect(row.text()).toContain('Second option 1')
		wrapper.unmount()
	})

	it('shows no report action when the quiz hides the submission history', async () => {
		const response = historyQuizResponse()
		response.quiz.show_submission_history = 0
		resourceState.response = response
		const wrapper = mountQuiz()
		await flushPromises()

		expect(wrapper.find('[data-testid="submission-history"]').exists()).toBe(
			false
		)
		expect(
			wrapper.find('[data-testid="attempt-report-button"]').exists()
		).toBe(false)
		wrapper.unmount()
	})

	it('keeps answer keys from the learner while the quiz hides answers', async () => {
		const response = historyQuizResponse()
		response.quiz.show_answers = 0
		resourceState.response = response
		const wrapper = mountQuiz()
		await flushPromises()

		await wrapper.findAll('[data-testid="attempt-report-button"]')[0].trigger('click')
		await flushPromises()

		// The report itself renders — answered rows, verdicts, no keys: neither
		// the request nor the section may exist (#1088: show_answers off).
		expect(wrapper.find('[data-testid="attempt-report-row"]').text()).toContain(
			'Question body 1'
		)
		expect(keyReads()).toHaveLength(0)
		expect(wrapper.text()).not.toContain('Correct Answer:')
		// The option the learner missed is a key; it must not surface.
		expect(wrapper.text()).not.toContain('First option 1')
		wrapper.unmount()
	})

	it('shows the correct answers to the attempt owner when the quiz shows answers', async () => {
		const response = historyQuizResponse()
		response.quiz.show_answers = 1
		resourceState.response = response
		resourceState.correctAnswers = { Q1: ['First option 1'] }
		const wrapper = mountQuiz()
		await flushPromises()

		await wrapper.findAll('[data-testid="attempt-report-button"]')[0].trigger('click')
		await flushPromises()

		expect(keyReads()).toEqual([
			[
				'lms.lms.doctype.lms_quiz.lms_quiz.get_submission_correct_answers',
				{ submission: 'SUBM-2' },
			],
		])
		expect(wrapper.text()).toContain('Correct Answer:')
		// The key comes from the key endpoint, not from the learner's answer.
		expect(wrapper.text()).toContain('First option 1')
		// The skipped question stays out of the report; the footnote counts it.
		expect(wrapper.find('[data-testid="attempt-report-row"]').exists()).toBe(true)
		expect(wrapper.findAll('[data-testid="attempt-report-row"]')).toHaveLength(1)
		expect(
			wrapper.find('[data-testid="attempt-report-skipped"]').text()
		).toContain('1 skipped questions are not included in this report.')
		wrapper.unmount()
	})

	it('always asks staff for the answer keys, whatever the quiz flag', async () => {
		const response = historyQuizResponse()
		response.quiz.show_answers = 0
		resourceState.response = response
		resourceState.correctAnswers = { Q1: ['First option 1'] }
		const wrapper = mountQuiz({}, {}, { name: 'teacher@example.com', is_instructor: true })
		await flushPromises()

		await wrapper.findAll('[data-testid="attempt-report-button"]')[0].trigger('click')
		await flushPromises()

		expect(keyReads()).toHaveLength(1)
		expect(wrapper.text()).toContain('Correct Answer:')
		expect(wrapper.text()).toContain('First option 1')
		wrapper.unmount()
	})

	it('closes the report and can open another attempt afterwards', async () => {
		const wrapper = mountQuiz()
		await flushPromises()

		await wrapper.findAll('[data-testid="attempt-report-button"]')[0].trigger('click')
		await flushPromises()
		expect(wrapper.find('[data-testid="attempt-report-row"]').exists()).toBe(true)

		const close = wrapper
			.findAll('button')
			.find((button) => button.text() === 'Close')
		expect(close).toBeDefined()
		await close!.trigger('click')
		await flushPromises()
		expect(wrapper.find('[data-testid="attempt-report-row"]').exists()).toBe(false)

		// Reopening targets the other submission: the modal is keyed by name,
		// so it remounts with fresh resources rather than showing stale rows.
		await wrapper.findAll('[data-testid="attempt-report-button"]')[1].trigger('click')
		await flushPromises()
		expect(resourceState.request).toHaveBeenCalledWith('frappe.client.get', {
			doctype: 'LMS Quiz Submission',
			name: 'SUBM-1',
		})
		expect(wrapper.find('[data-testid="attempt-report-row"]').exists()).toBe(true)
		wrapper.unmount()
	})
})

describe('owner R5 written-answer check action', () => {
	it.each([0, 1])('keeps native User Input check, draft and verdict %i with secondary Check / primary Finish', async (verdict) => {
		const response = quizResponse()
		response.quiz.show_answers = 1
		response.quiz.questions = [{ question: 'Q1', marks: 1 }]
		response.questions_by_name.Q1.type = 'User Input'
		resourceState.response = response
		resourceState.checkAnswer = verdict
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)
		const check = wrapper.findAll('button').find((b) => b.text() === 'Check')!
		expect(check.classes()).toContain('lms-quiz-secondary')
		expect(wrapper.findAll('button').find((b) => b.text() === 'Finish Quiz')!.classes()).toContain('lms-quiz-primary')
		wrapper.vm.possibleAnswer = 'Retained written answer'
		await check.trigger('click')
		await flushPromises()
		expect(resourceState.request).toHaveBeenCalledWith('lms.lms.doctype.lms_quiz.lms_quiz.check_answer', undefined)
		expect(wrapper.vm.possibleAnswer).toBe('Retained written answer')
		expect(wrapper.find('[data-testid="quiz-feedback"]').text()).toContain(verdict ? 'Correct' : 'Incorrect')
		expect(wrapper.findAll('button').find((b) => b.text() === 'Check')).toBeUndefined()
		wrapper.unmount()
		const restored = mountQuiz()
		await flushPromises()
		expect(restored.vm.possibleAnswer).toBe('Retained written answer')
		expect(restored.find('[data-testid="quiz-feedback"]').text()).toContain(verdict ? 'Correct' : 'Incorrect')
		restored.unmount()
	})
})

describe('Quiz retake credit (#32)', () => {
	it('offers only the never-credited questions and says what carries over', async () => {
		resourceState.response = choicesQuizResponse(3)
		resourceState.creditedQuestions = ['Q1']
		const wrapper = mountQuiz()
		await flushPromises()

		// Q1 stays out of the offered pool; the card counts what is left.
		expect(wrapper.text()).toContain('2 questions')
		expect(wrapper.text()).toContain('1 credited answer')
		expect(wrapper.text()).toContain('remaining 2 questions')

		await startQuiz(wrapper)
		expect(wrapper.text()).toContain('Question body 2')
		expect(wrapper.text()).not.toContain('Question body 1')
		wrapper.unmount()
	})

	it('answers every question of the quiz as credited with a finished banner, no empty start', async () => {
		resourceState.response = choicesQuizResponse(2)
		resourceState.creditedQuestions = ['Q1', 'Q2']
		const wrapper = mountQuiz()
		await flushPromises()

		expect(
			wrapper.find('[data-testid="quiz-schedule-blocked"]').exists()
		).toBe(false)
		expect(wrapper.text()).toContain(
			'You have already answered every question of this quiz correctly.'
		)
		expect(
			wrapper.findAll('button').find((button) => button.text() === 'Start Quiz')
		).toBeUndefined()
		wrapper.unmount()
	})

	it('keeps the offered pool whole in an author preview', async () => {
		resourceState.response = choicesQuizResponse(3)
		resourceState.creditedQuestions = ['Q1']
		const wrapper = mountQuiz({ preview: true })
		await flushPromises()

		expect(wrapper.text()).toContain('3 questions')
		await startQuiz(wrapper)
		expect(wrapper.text()).toContain('Question body 1')
		wrapper.unmount()
	})

	it('drops a restored draft answer for a question the retake no longer asks', async () => {
		resourceState.response = choicesQuizResponse(3)
		resourceState.creditedQuestions = ['Q1']
		// A draft saved while attempt one was mid-flight, carrying an answer
		// for the question that attempt later credited.
		localStorage.setItem(
			'lms-quiz-draft:learner@example.com:QUIZ-1',
			JSON.stringify({
				version: 2,
				questions: ['Q1', 'Q2', 'Q3'],
				answers: [
					{ question_name: 'Q1', answer: ['First option 1'] },
					{ question_name: 'Q2', answer: ['First option 2'] },
				],
				activeQuestion: 'Q2',
				reviewQuestions: [],
				verdicts: {},
				deadline: null,
			})
		)
		const wrapper = mountQuiz()
		await flushPromises()

		const answers = (wrapper.vm as any).savedAnswers as {
			question_name: string
		}[]
		expect(answers.map((answer) => answer.question_name)).toEqual(['Q2'])
		wrapper.unmount()
	})
})

describe('Quiz retake credit after a submit (#32)', () => {
	it('refetches the credited set so the next retake drops newly credited questions', async () => {
		resourceState.response = choicesQuizResponse(3)
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)
		await submitWithoutLiveChecking(wrapper)

		const creditedCalls = resourceState.request.mock.calls.filter(
			([url]) =>
				url === 'lms.lms.doctype.lms_quiz.lms_quiz.get_quiz_credited_questions'
		)
		expect(creditedCalls).toHaveLength(2)
		wrapper.unmount()
	})

	it('rebuilds the offered pool around the freshly credited answers', async () => {
		resourceState.response = choicesQuizResponse(3)
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)
		expect((wrapper.vm as any).questions).toHaveLength(3)

		// What the server answers once this attempt is graded: Q1 credited.
		resourceState.creditedQuestions = ['Q1']
		await submitWithoutLiveChecking(wrapper)

		expect((wrapper.vm as any).questions).toHaveLength(2)
		expect(
			(wrapper.vm as any).questions.map((row: { question: string }) => row.question)
		).toEqual(['Q2', 'Q3'])
		wrapper.unmount()
	})
})

describe('Quiz submit declares its offered pool (#32)', () => {
	it('submits the offered questions with the results, retake-filtered', async () => {
		resourceState.response = choicesQuizResponse(3)
		resourceState.creditedQuestions = ['Q1']
		const wrapper = mountQuiz()
		await flushPromises()
		await startQuiz(wrapper)
		wrapper.vm.possibleAnswer = null
		await submitWithoutLiveChecking(wrapper)

		const submit = resourceState.submits.find(
			([url]) => url === 'lms.lms.doctype.lms_quiz.lms_quiz.submit_quiz'
		)
		expect(submit).toBeDefined()
		// The retake offered Q2 and Q3 only — the server sizes this attempt's
		// denominator by the declaration, skipped questions included.
		expect(JSON.parse((submit![1] as any).question_pool)).toEqual(['Q2', 'Q3'])
		wrapper.unmount()
	})
})
