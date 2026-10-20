import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Quizzes from '@/pages/Quizzes.vue'
import QuizSubmissions from '@/pages/QuizSubmissions.vue'

vi.stubGlobal('__', (text: string) => text)

const state = vi.hoisted(() => ({
	// The options each page handed createListResource, so the transform the
	// page applies to its rows can be run by the test.
	listOptions: null as Record<string, any> | null,
	list: {
		data: [],
		list: { loading: false },
		hasNextPage: false,
		next: vi.fn(),
		update: vi.fn(),
		reload: vi.fn(),
	},
	push: vi.fn(),
	// The columns each page passed to ListPage.
	quizzesColumns: [] as Record<string, any>[],
	submissionsColumns: [] as Record<string, any>[],
}))

vi.mock('frappe-ui', () => ({
	createListResource: (options: Record<string, any>) => {
		state.listOptions = options
		return state.list
	},
	Button: { template: '<button type="button"><slot /></button>' },
	Checkbox: { props: ['modelValue'], template: '<input type="checkbox" />' },
	usePageMeta: vi.fn(),
}))

vi.mock('vue-router', () => ({
	useRouter: () => ({
		push: state.push,
		currentRoute: { value: { query: {} } },
	}),
}))

vi.mock('@/stores/session', () => ({ sessionStore: () => ({ brand: {} }) }))
vi.mock('@/utils/bulkDelete', () => ({
	useBulkDeleteAction: () => ({
		deleting: false,
		announcement: '',
		run: vi.fn(),
	}),
}))

vi.mock('@/components/Layouts/pages/ListPage.vue', () => ({
	default: {
		name: 'ListPage',
		props: ['columns', 'rows', 'listOptions', 'listResource'],
		template: '<section data-testid="list-page" />',
		created() {
			// Quizzes and Submissions are the two pages under test; tell them
			// apart by the doctype their resource asked for.
			if (state.listOptions?.doctype === 'LMS Quiz') {
				state.quizzesColumns = this.columns
			} else if (state.listOptions?.doctype === 'LMS Quiz Submission') {
				state.submissionsColumns = this.columns
			}
		},
	},
}))

vi.mock('@/components/HeaderButton.vue', () => ({
	default: { template: '<button type="button" />' },
}))

vi.mock('@/components/Modals/ImportChemedgePdfTrainerModal.vue', () => ({
	default: { template: '<div />' },
}))

vi.mock('@/components/Controls/Link.vue', () => ({
	default: { template: '<input />' },
}))

// A dayjs stand-in whose only job is to report the format string the page
// asked for, and to shape a fixed timestamp the way the real one would.
const dayjsCalls: string[] = []
const dayjs = (value: string) => ({
	format(fmt: string) {
		dayjsCalls.push(fmt)
		const [date, time] = value.split(' ')
		const [y, m, d] = date.split('-')
		const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
		return fmt
			.replace('DD MMM YYYY', `${d} ${months[Number(m) - 1]} ${y}`)
			.replace('HH:mm', time.slice(0, 5))
	},
})

const staffUser = { data: { is_moderator: true } }

beforeEach(() => {
	state.listOptions = null
	state.quizzesColumns = []
	state.submissionsColumns = []
	dayjsCalls.length = 0
})

describe('Quizzes table (#29)', () => {
	it('gives the title the width the secondary columns give up, and wraps it', () => {
		const wrapper = mount(Quizzes, {
			global: {
				provide: { $user: staffUser, $dayjs: dayjs },
				mocks: { __: (s: string) => s },
			},
		})

		const columns = state.quizzesColumns
		expect(columns.length).toBeGreaterThan(1)
		const title = columns.find((column) => column.key === 'title')
		const secondary = columns.filter((column) => column.key !== 'title')
		const secondaryWidth = secondary.reduce((sum, c) => sum + c.width, 0)

		// The table fits by proportion, not by scrolling: the identifying
		// column is the widest thing on the row, the numeric columns around
		// it give up the space, and a long title wraps instead of clipping.
		expect(title.wrap).toBe(true)
		expect(title.width).toBeGreaterThan(secondaryWidth)
		secondary.forEach((column) => {
			expect(column.width).toBeLessThan(title.width)
		})

		// The date column is secondary on the phone card too: hideOnMobile
		// keeps the card to its title instead of a three-part detail line.
		expect(
			columns.find((column) => column.key === 'modified').hideOnMobile
		).toBe(true)
		wrapper.unmount()
	})
})

describe('Quiz submissions table (#30)', () => {
	it('keeps the identifier columns ahead of the numeric ones', () => {
		const wrapper = mount(QuizSubmissions, {
			global: {
				provide: { $user: staffUser, $dayjs: dayjs },
				mocks: { __: (s: string) => s },
			},
		})

		const columns = state.submissionsColumns
		const identifiers = columns.filter((column) =>
			['member_name', 'quiz_title'].includes(column.key)
		)
		const numeric = columns.filter((column) =>
			['score', 'percentage'].includes(column.key)
		)
		const identifierWidth = identifiers.reduce((sum, c) => sum + c.width, 0)
		const numericWidth = numeric.reduce((sum, c) => sum + c.width, 0)

		// Compact: the numbers qualify a row, they do not describe it, so
		// they cannot out-weigh who sat which quiz.
		expect(identifierWidth).toBeGreaterThan(numericWidth)
		// A quiz name is identity too, not an ellipsis.
		expect(
			columns.find((column) => column.key === 'quiz_title').wrap
		).toBe(true)
		wrapper.unmount()
	})

	it('shows the time of submission, to the minute, beside its date', () => {
		const wrapper = mount(QuizSubmissions, {
			global: {
				provide: { $user: staffUser, $dayjs: dayjs },
				mocks: { __: (s: string) => s },
			},
		})

		const transformed = state.listOptions.transform([
			{ name: 'SUBM-1', creation: '2026-10-04 14:05:41' },
		])
		expect(transformed[0].creation).toBe('04 Oct 2026 14:05')
		wrapper.unmount()
	})
})
