import { shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, reactive } from 'vue'
import CourseEditor from '@/pages/Courses/CourseEditor.vue'
import type { OutlineChapter } from '@/types'

const { createResource, replace } = vi.hoisted(() => ({
	createResource: vi.fn(),
	replace: vi.fn(),
}))
const route = reactive<{ query: Record<string, string>; hash: string }>({
	query: {},
	hash: '#editor',
})
const outline = reactive({ data: [] as OutlineChapter[], fetch: vi.fn() })

vi.mock('frappe-ui', () => ({
	createResource,
	Button: { template: '<button><slot /></button>' },
}))
vi.mock('vue-router', () => ({
	useRoute: () => route,
	useRouter: () => ({ replace }),
}))
vi.mock('@/stores/sidebar', () => ({
	useSidebar: () => ({ isSidebarCollapsed: false }),
}))
vi.mock('@/utils/composables', () => ({
	useScreenSize: () => ({ isMobile: false }),
}))
vi.mock('@/components/CourseOutline.vue', () => ({
	default: { template: '<div />' },
}))
vi.mock('@/components/BottomSheet.vue', () => ({
	default: { template: '<div />' },
}))
vi.mock('@/components/SkeletonLoader.vue', () => ({
	default: { template: '<div />' },
}))
vi.mock('@/components/Modals/VideoStatistics.vue', () => ({
	default: { template: '<div />' },
}))
vi.mock('@/pages/LessonForm.vue', () => ({
	default: {
		name: 'LessonForm',
		props: ['courseName', 'chapterNumber', 'lessonNumber'],
		template: '<div />',
	},
}))

const tree = (): OutlineChapter[] => [
	{
		name: 'ROOT',
		title: 'Root',
		idx: 1,
		lessons: [{ name: 'OPEN', title: 'First', number: '1-1', position: 1 }],
		sections: [
			{
				name: 'L2',
				title: 'Level 2',
				idx: 1,
				position: 2,
				sections: [
					{
						name: 'L3',
						title: 'Level 3',
						idx: 1,
						sections: [
							{
								name: 'L4',
								title: 'Level 4',
								idx: 1,
								lessons: [
									{
										name: 'DEEP',
										title: 'Deep lesson',
										number: '1-1-1-1-1',
										position: 1,
									},
								],
							},
						],
					},
				],
			},
		],
	},
	{
		name: 'OTHER',
		title: 'Other root',
		idx: 2,
		lessons: [{ name: 'LAST', title: 'Last', number: '2-1', position: 1 }],
	},
]

const mountEditor = () =>
	shallowMount(CourseEditor, {
		props: { course: { data: { name: 'COURSE' } } },
		global: { mocks: { __ } },
	})

beforeEach(() => {
	route.query = {}
	replace.mockReset()
	outline.data = tree()
	createResource.mockReturnValue(outline)
	localStorage.clear()
})

describe('tree-aware course editor selection', () => {
	it('steps through nested lessons using their full section paths', async () => {
		const wrapper = mountEditor()
		expect(wrapper.vm.lessonTotal).toBe(3)
		wrapper.vm.goNext()
		await nextTick()
		expect(wrapper.findComponent({ name: 'LessonForm' }).props()).toMatchObject(
			{
				chapterNumber: '1-1-1-1',
				lessonNumber: '1',
			}
		)
		expect(wrapper.vm.lessonIndex).toBe(2)
		wrapper.vm.goNext()
		await nextTick()
		expect(
			wrapper.findComponent({ name: 'LessonForm' }).props('chapterNumber')
		).toBe('2')
		wrapper.vm.goPrev()
		await nextTick()
		expect(
			wrapper.findComponent({ name: 'LessonForm' }).props('chapterNumber')
		).toBe('1-1-1-1')
	})

	it('keeps the same lesson open when another lesson takes its previous position', async () => {
		const wrapper = mountEditor()
		outline.data = [
			{
				name: 'OTHER',
				title: 'Other root',
				idx: 1,
				lessons: [{ name: 'LAST', title: 'Last', number: '1-1', position: 1 }],
			},
			{
				name: 'ROOT',
				title: 'Root',
				idx: 2,
				lessons: [{ name: 'OPEN', title: 'First', number: '2-1', position: 1 }],
			},
		]
		await nextTick()
		expect(wrapper.findComponent({ name: 'LessonForm' }).props()).toMatchObject(
			{
				chapterNumber: '2',
				lessonNumber: '1',
			}
		)
		expect(replace).toHaveBeenLastCalledWith({
			query: { editLesson: '2-1' },
			hash: '#editor',
		})
		expect(
			JSON.parse(localStorage.getItem('lms-course-editor-last-lesson')!)
		).toEqual({ COURSE: '2-1' })
	})

	it('keeps a full nested path when following a legacy preview link', () => {
		route.query = { editLesson: '1-1-1-1-1', lessonMode: 'preview' }
		mountEditor()
		expect(replace).toHaveBeenLastCalledWith({
			name: 'Lesson',
			params: {
				courseName: 'COURSE',
				chapterNumber: '1-1-1-1',
				lessonNumber: '1',
			},
			query: { studentView: 1 },
		})
	})
})
