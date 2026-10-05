import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QuizSubmission from '@/pages/QuizSubmission.vue'

const state = vi.hoisted(() => ({
	keys: { data: null as any, loading: false, error: null as any },
	push: vi.fn(),
}))

vi.mock('frappe-ui', () => ({
	createDocumentResource: () => ({
		doc: {
			quiz: 'quiz',
			member_name: 'Student',
			result: [
				{ name: 'row', question_name: 'q1', question: 'Task 1', answer: '21' },
			],
		},
	}),
	createResource: () => state.keys,
	FormControl: { template: '<input />' },
	Badge: { template: '<div />' },
	Button: { template: '<button />' },
	Breadcrumbs: { template: '<nav />' },
	usePageMeta: vi.fn(),
	toast: { error: vi.fn() },
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: state.push }) }))
vi.mock('@/stores/session', () => ({ sessionStore: () => ({ brand: {} }) }))
vi.mock('@/composables/useKeyboardShortcuts', () => ({
	useKeyboardShortcuts: vi.fn(),
	saveShortcut: () => ({}),
}))
vi.mock('@/components/Layouts/PageHeader.vue', () => ({
	default: { template: '<header />' },
}))
vi.mock('@/components/Layouts/PageBody.vue', () => ({
	default: { template: '<main><slot /></main>' },
}))
vi.mock('@/components/HeaderButton.vue', () => ({
	default: { template: '<button />' },
}))
vi.mock('@/components/ShortcutTooltip.vue', () => ({
	default: { template: '<span />' },
}))

vi.stubGlobal('__', (s: string) => s)
// translation.js installs String.prototype.format at app boot; the page
// calls __('Q{0}:').format(index + 1) and never reaches Vue without it.
if (!('format' in String.prototype)) {
	// eslint-disable-next-line no-extend-native
	Object.defineProperty(String.prototype, 'format', {
		value: function (...args: string[]) {
			return this.replace(/\{(\d+)\}/g, (_: string, i: number) => args[i] ?? '')
		},
	})
}
const render = () =>
	mount(QuizSubmission, {
		props: { submission: 'submission' },
		global: {
			provide: { $user: { data: { is_system_manager: true } } },
			mocks: { __: (s: string) => s },
		},
	})

beforeEach(() => {
	state.keys.data = { q1: ['12', '21'] }
	state.keys.loading = false
	state.keys.error = null
	state.push.mockReset()
})

describe('Quiz submission review', () => {
	it('shows student and accepted answers separately for a system manager', () => {
		const wrapper = render()
		expect(wrapper.text()).toMatch(/Answered\s*:\s*21/)
		expect(wrapper.text()).toMatch(/Correct Answer\s*:\s*12, 21/)
		expect(state.push).not.toHaveBeenCalled()
		wrapper.unmount()
	})
	it('does not render executable HTML in an answer key', () => {
		state.keys.data = {
			q1: ['<img src="x" onerror="alert(1)"><script>alert(2)</script>12'],
		}
		const wrapper = render()
		expect(wrapper.find('script').exists()).toBe(false)
		expect(wrapper.find('img').attributes('onerror')).toBeUndefined()
		wrapper.unmount()
	})
	it('distinguishes an answer loading error from an absent answer', () => {
		state.keys.data = null
		state.keys.error = new Error('Denied')
		const wrapper = render()
		expect(wrapper.text()).toContain('Could not load correct answers')
		wrapper.unmount()
	})
})
