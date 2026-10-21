import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import SectionRow from '@/components/SectionRow.vue'
import {
	courseOutlineExpansionKey,
	isSectionExpanded,
	rememberSectionExpansion,
} from '@/utils/courseOutlineExpansion'
import type { OutlineChapter } from '@/types'

const key = courseOutlineExpansionKey('COURSE', 'user@example.com')
vi.mock('vue-router', () => ({
	useRoute: () => ({ params: {}, query: {} }),
	useRouter: () => ({ push: vi.fn() }),
}))
const child: OutlineChapter = {
	name: 'CHILD',
	title: 'Child',
	idx: 1,
	level: 2,
	lessons: [],
}
const root: OutlineChapter = {
	name: 'ROOT',
	title: 'Root',
	idx: 1,
	level: 1,
	sections: [child],
	lessons: [],
}
const render = () =>
	mount(SectionRow, {
		props: {
			section: root,
			courseName: 'COURSE',
			allowEdit: true,
			selectedLessonNumber: '1-1-1',
		},
		global: {
			mocks: { __ },
			provide: { $user: { data: { name: 'user@example.com' } } },
		},
	})

beforeEach(() => localStorage.clear())

describe('outline expansion memory', () => {
	it('starts closed, including the active lesson branch', () => {
		const wrapper = render()
		expect(
			wrapper.get('button[aria-expanded]').attributes('aria-expanded')
		).toBe('false')
		expect(wrapper.find('[title="Child"]').exists()).toBe(false)
	})
	it('restores only explicitly opened children when a parent is reopened or the view remounts', async () => {
		let wrapper = render()
		await wrapper.get('button[aria-expanded]').trigger('click')
		const childButton = () =>
			wrapper.get('[title="Child"]').element.closest('button')!
		expect(childButton().getAttribute('aria-expanded')).toBe('false')
		childButton().click()
		await wrapper.vm.$nextTick()
		expect(childButton().getAttribute('aria-expanded')).toBe('true')
		await wrapper.get('button[aria-expanded]').trigger('click')
		await wrapper.get('button[aria-expanded]').trigger('click')
		expect(childButton().getAttribute('aria-expanded')).toBe('true')
		childButton().click()
		await wrapper.vm.$nextTick()
		wrapper.unmount()
		wrapper = render()
		expect(
			wrapper.get('button[aria-expanded]').attributes('aria-expanded')
		).toBe('true')
		expect(childButton().getAttribute('aria-expanded')).toBe('false')
		expect(wrapper.get('[data-testid="section-branch"]').classes()).toContain(
			'border-s'
		)
	})
	it('isolates state by course, user and stable section ID', () => {
		rememberSectionExpansion(key, 'ROOT', true)
		expect(isSectionExpanded(key, 'ROOT')).toBe(true)
		expect(isSectionExpanded(key, 'CHILD')).toBe(false)
		expect(
			isSectionExpanded(
				courseOutlineExpansionKey('OTHER', 'user@example.com'),
				'ROOT'
			)
		).toBe(false)
		expect(
			isSectionExpanded(
				courseOutlineExpansionKey('COURSE', 'other@example.com'),
				'ROOT'
			)
		).toBe(false)
		rememberSectionExpansion(key, 'ROOT', false)
		expect(isSectionExpanded(key, 'ROOT')).toBe(false)
	})
	it('ignores malformed browser storage', () => {
		localStorage.setItem(key, '{broken')
		expect(isSectionExpanded(key, 'ROOT')).toBe(false)
		rememberSectionExpansion(key, 'ROOT', true)
		expect(isSectionExpanded(key, 'ROOT')).toBe(true)
	})
})
