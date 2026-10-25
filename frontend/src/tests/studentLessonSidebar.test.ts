import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
	courseOutlineExpansionKey,
	rememberSectionExpansion,
} from '@/utils/courseOutlineExpansion'
import StudentLessonSidebar from '@/components/StudentLessonSidebar.vue'

const flatOutline = vi.hoisted(() => [
	{
		name: 'CH-1',
		title: 'Chapter 1',
		idx: 1,
		lessons: [
			{
				name: 'L1',
				title: 'Lesson 1',
				number: '1-1',
				is_complete: 1,
				locked: 0,
			},
			{
				name: 'L2',
				title: 'Lesson 2',
				number: '1-2',
				is_complete: 0,
				locked: 0,
			},
			{
				name: 'L3',
				title: 'Lesson 3',
				number: '1-3',
				is_complete: 0,
				locked: 1,
			},
		],
	},
])

// Nested sections render recursively, saved expansion choices are restored,
// the badge counts the whole subtree, and lesson links carry
// the section path as the chapter param.
const nestedOutline = vi.hoisted(() => [
	{
		name: 'CH-1',
		title: 'Chapter 1',
		idx: 1,
		level: 1,
		total_lesson_count: 3,
		lessons: [
			{
				name: 'L1',
				title: 'Lesson 1',
				number: '1-1',
				locked: 0,
				is_complete: 0,
			},
		],
		sections: [
			{
				name: 'SUB-1',
				title: 'Subsection',
				idx: 1,
				level: 2,
				total_lesson_count: 2,
				lessons: [
					{
						name: 'L2',
						title: 'Nested 1',
						number: '1-1-1',
						locked: 0,
						is_complete: 0,
					},
					{
						name: 'L3',
						title: 'Nested 2',
						number: '1-1-2',
						locked: 0,
						is_complete: 0,
					},
				],
				sections: [],
			},
		],
	},
])

// Which outline the sidebar's resource resolves with; per-test switchable.
let servedOutline: unknown[] = flatOutline

const routeQuery = vi.hoisted(() => ({} as Record<string, string>))
vi.mock('vue-router', () => ({
	useRoute: () => ({ params: {}, query: routeQuery }),
	useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('frappe-ui', () => ({
	createResource: () => ({
		get data() {
			return servedOutline
		},
		reload: vi.fn(),
	}),
}))

vi.mock('lucide-vue-next', () => ({
	ChevronDown: { template: '<span />' },
	Circle: { template: '<span />' },
	CircleCheck: { template: '<span />' },
	Cloud: { template: '<span />' },
	FileText: { template: '<span />' },
	HelpCircle: { template: '<span />' },
	LockKeyhole: { template: '<span class="lucide-lock-keyhole" />' },
	MonitorPlay: { template: '<span />' },
	NotebookPen: { template: '<span />' },
	SquareCode: { template: '<span />' },
}))

vi.stubGlobal('__', (s: string) => s)

const mountSidebar = (selectedLessonNumber = '1-2') =>
	mount(StudentLessonSidebar, {
		props: {
			courseName: 'COURSE-1',
			courseTitle: 'Course 1',
			progress: 33,
			selectedLessonNumber,
		},
		global: {
			provide: { $user: { data: { name: 'learner@example.com' } } },
			mocks: { __: (s: string) => s },
			stubs: {
				'router-link': {
					props: ['to'],
					template: '<a :data-to="JSON.stringify(to)"><slot /></a>',
				},
			},
		},
	})

beforeEach(() => {
	localStorage.clear()
	const key = courseOutlineExpansionKey('COURSE-1', 'learner@example.com')
	rememberSectionExpansion(key, 'CH-1', true)
	rememberSectionExpansion(key, 'SUB-1', true)
})

it('starts closed without saved state even on an active nested lesson, then remembers the learner choice', async () => {
	localStorage.clear()
	let wrapper = mountSidebar()
	expect(wrapper.get('button[aria-expanded]').attributes('aria-expanded')).toBe(
		'false'
	)
	await wrapper.get('button[aria-expanded]').trigger('click')
	const title = wrapper.get('[title="Chapter 1"]')
	expect(title.classes()).toContain('whitespace-normal')
	expect(title.element.parentElement!.classList.contains('font-semibold')).toBe(
		true
	)
	expect(
		wrapper.get('[data-testid="student-section-branch"]').classes()
	).toContain('border-s')
	wrapper.unmount()
	wrapper = mountSidebar()
	expect(wrapper.get('button[aria-expanded]').attributes('aria-expanded')).toBe(
		'true'
	)
})

describe('StudentLessonSidebar locked lesson', () => {
	it('keeps the homework return link and student preview mode across sidebar navigation', () => {
		routeQuery.hw = 'HW-ONE'
		routeQuery.studentView = '1'
		try {
			const wrapper = mountSidebar()
			const route = JSON.parse(wrapper.find('li li a').attributes('data-to') || '{}')
			expect(route.query).toEqual({ hw: 'HW-ONE', studentView: 1 })
		} finally {
			delete routeQuery.hw
			delete routeQuery.studentView
		}
	})
	it('renders a lock for a locked lesson and no link', () => {
		const wrapper = mountSidebar()
		const rows = wrapper.findAll('li li')

		expect(rows).toHaveLength(3)
		expect(rows[2].find('a').exists()).toBe(false)
		expect(rows[2].find('.cursor-not-allowed').exists()).toBe(true)
		expect(rows[2].find('.sr-only').text()).toBe('Locked')
		expect(rows[2].find('[aria-label]').exists()).toBe(false)
		expect(rows[2].find('[aria-disabled]').exists()).toBe(false)
	})

	it('still links unlocked lessons', () => {
		const wrapper = mountSidebar()
		const rows = wrapper.findAll('li li')

		expect(rows[0].find('a').exists()).toBe(true)
		expect(rows[1].find('a').exists()).toBe(true)
	})

	it('does not emit select-lesson when a locked row is clicked', async () => {
		const wrapper = mountSidebar()
		const rows = wrapper.findAll('li li')

		await rows[2].find('.cursor-not-allowed').trigger('click')

		expect(wrapper.emitted('select-lesson')).toBeUndefined()
	})
})

describe('StudentLessonSidebar nested sections (task 28)', () => {
	it('renders the nested section and its lessons', () => {
		servedOutline = nestedOutline
		try {
			const wrapper = mountSidebar('1-1-2')
			const text = wrapper.text()
			expect(text).toContain('Chapter 1')
			expect(text).toContain('Subsection')
			expect(text).toContain('Nested 2')
		} finally {
			servedOutline = flatOutline
		}
	})

	it('shows the subtree lesson count on the parent badge', () => {
		servedOutline = nestedOutline
		try {
			const wrapper = mountSidebar('1-1-2')
			const badges = wrapper
				.findAll('span.text-ink-gray-5')
				.map((b) => b.text())
			// The level-1 badge counts all three lessons of its subtree; the
			// nested one counts its own two. For a flat chapter the two
			// coincide (legacy parity).
			expect(badges).toContain('3')
			expect(badges).toContain('2')
		} finally {
			servedOutline = flatOutline
		}
	})

	it('links nested lessons with the section path as the chapter param', () => {
		servedOutline = nestedOutline
		try {
			const wrapper = mountSidebar('1-1-2')
			const link = wrapper
				.findAll('a[data-to]')
				.find((a) => a.text().includes('Nested 2'))
			expect(link).toBeDefined()
			const to = JSON.parse(link!.attributes('data-to'))
			expect(to.name).toBe('Lesson')
			expect(to.params.chapterNumber).toBe('1-1')
			expect(to.params.lessonNumber).toBe('2')
		} finally {
			servedOutline = flatOutline
		}
	})
})
