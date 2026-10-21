import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CourseOutline from '@/components/CourseOutline.vue'

const { createResource, dialog } = vi.hoisted(() => ({
	createResource: vi.fn(),
	dialog: vi.fn(),
}))
vi.mock('frappe-ui', () => ({
	createResource,
	Button: { template: '<button><slot /></button>' },
	toast: { success: vi.fn(), error: vi.fn() },
}))
vi.mock('vue-router', () => ({
	useRoute: () => ({ query: {}, params: {} }),
	useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('@/composables/useFormRoute', () => ({ openFormRoute: vi.fn() }))
vi.mock('@/components/SectionRow.vue', () => ({
	default: {
		name: 'SectionRow',
		props: ['section'],
		emits: ['delete-chapter'],
		template: '<div />',
	},
}))
vi.mock('@/components/Modals/SectionFormModal.vue', () => ({
	default: { template: '<div />' },
}))
vi.mock('@/components/Modals/MoveSectionModal.vue', () => ({
	default: { template: '<div />' },
}))
vi.mock('vuedraggable', () => ({
	default: {
		props: ['list'],
		template:
			'<div><template v-for="item in list" :key="item.name"><slot name="item" :element="item" /></template></div>',
	},
}))

beforeEach(() => {
	dialog.mockReset()
	createResource.mockImplementation((options) => ({
		data: options.url.endsWith('get_course_outline')
			? [
					{
						name: 'ROOT',
						title: 'Root',
						idx: 1,
						lessons: [
							{ name: 'A', number: '1-1' },
							{ name: 'B', number: '1-2' },
						],
						sections: [
							{
								name: 'NESTED',
								title: 'Nested',
								idx: 1,
								lessons: [{ name: 'C', number: '1-1-1' }],
							},
						],
					},
			  ]
			: null,
		fetch: vi.fn(),
		reload: vi.fn(),
		submit: vi.fn(),
	}))
})

describe('course outline delete confirmation', () => {
	it.each([
		['ROOT', '1 section', '3 lessons'],
		['NESTED', null, '1 lesson'],
	])(
		'counts the actual descendants of %s before asking to delete',
		(name, sectionCount, lessonCount) => {
			const wrapper = mount(CourseOutline, {
				props: { courseName: 'COURSE', allowEdit: true },
				global: {
					mocks: { __ },
					config: { globalProperties: { $dialog: dialog } },
				},
			})
			wrapper
				.findComponent({ name: 'SectionRow' })
				.vm.$emit('delete-chapter', name)
			const confirmation = dialog.mock.calls[0][0]
			expect(confirmation.message).toContain(lessonCount)
			if (sectionCount) expect(confirmation.message).toContain(sectionCount)
			expect(confirmation.message).not.toContain('This section is empty')
		}
	)
})
