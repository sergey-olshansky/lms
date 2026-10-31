import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import {
	createMemoryHistory,
	createRouter,
	RouterView,
	type Router,
} from 'vue-router'
import { defineComponent, h, reactive } from 'vue'

vi.stubGlobal('__', (text: string) => text)

String.prototype.format = function (this: string, ...args: unknown[]): string {
	return this.replace(/{(\d+)}/g, (match, index) =>
		args[Number(index)] === undefined ? match : String(args[Number(index)])
	)
}

const { createResourceMock } = vi.hoisted(() => {
	// @/utils pulls in plyr, which touches matchMedia at import time.
	window.matchMedia ??= (() => ({
		matches: false,
		addEventListener: () => {},
		removeEventListener: () => {},
	})) as unknown as typeof window.matchMedia
	return { createResourceMock: vi.fn() }
})

// The page's own dependency surface: enough of frappe-ui for CourseOutline,
// SectionRow and CourseFolder to mount against the real route table.
vi.mock('frappe-ui', () => ({
	createResource: createResourceMock,
	Button: {
		inheritAttrs: false,
		template: `<button v-bind="$attrs"><slot name="prefix" /><slot /></button>`,
	},
	toast: { success: vi.fn(), error: vi.fn() },
	usePageMeta: vi.fn(),
	TextInput: {
		props: ['modelValue'],
		emits: ['update:modelValue'],
		template: `<input :value="modelValue" />`,
	},
	Tooltip: { template: `<span><slot /></span>` },
}))

vi.mock('@/stores/session', () => ({
	sessionStore: () => ({ brand: {} }),
}))

// The stub keeps the breadcrumb routes real: the back-navigation assertions
// read the rendered router-links, not a copy of the header's logic.
vi.mock('@/components/Layouts/pages/PageHeader.vue', () => ({
	default: {
		props: ['breadcrumbs', 'loading'],
		template: `<header data-testid="page-header">
			<template v-for="(crumb, i) in breadcrumbs" :key="i">
				<router-link v-if="crumb.route" :to="crumb.route">{{ crumb.label }}</router-link>
				<span v-else>{{ crumb.label }}</span>
			</template>
		</header>`,
	},
}))

// The course page is stubbed so this test does not drag in CourseDetail's own
// dependency chain when the folder page's back affordances point at it.
vi.mock('@/pages/Courses/CourseDetail.vue', () => ({
	default: defineComponent({
		render: () => h('div', ['COURSE', h(RouterView)]),
	}),
}))

// The item-slot-rendering mock: a folder row only exists inside a Draggable
// item template, so a `<div />` mock would hide the very link under test.
vi.mock('vuedraggable', () => ({
	default: {
		name: 'Draggable',
		props: ['list'],
		template:
			'<div><template v-for="item in list" :key="item.name"><slot name="item" :element="item" /></template></div>',
	},
}))

// THE REAL ROUTE TABLE, not a copy: a reimplemented table would only prove
// that vue-router resolves what you tell it to resolve.
import { routes } from '@/routes'
import CourseOutline from '@/components/CourseOutline.vue'
// Imported statically as well as through the table's lazy `() => import(...)`:
// a navigation started by a click would otherwise wait on a cold transform.
import CourseFolder from '@/pages/CourseFolder.vue'
import {
	courseOutlineExpansionKey,
	rememberSectionExpansion,
} from '@/utils/courseOutlineExpansion'

const FOLDER_IMAGES = [
	{
		name: 'FILE-1',
		file_name: 'cat.jpg',
		file_url: '/private/files/cat.jpg',
		file_size: 1024,
	},
	{
		name: 'FILE-2',
		file_name: 'dog.jpg',
		file_url: '/private/files/dog.jpg',
		file_size: 2048,
	},
]

const outlineResource = reactive({
	data: [
		{
			name: 'CH-1',
			title: 'Chapter One',
			idx: 1,
			level: 1,
			lessons: [],
			sections: [],
			folders: [
				{
					name: 'FOLDER-1',
					title: 'Материалы',
					position: 1,
					image_count: 2,
					images: FOLDER_IMAGES,
				},
			],
		},
	],
	loading: false,
	fetch: vi.fn(),
	reload: vi.fn(),
})

const courseResource = reactive({
	data: { title: 'Course One', instructors: [] as { name: string }[] },
	loading: false,
	fetch: vi.fn(),
	reload: vi.fn(),
})

createResourceMock.mockImplementation((options: { url: string }) =>
	options.url === 'lms.lms.utils.get_course_outline'
		? outlineResource
		: options.url === 'lms.lms.utils.get_course_details'
		? courseResource
		: reactive({ loading: false, submit: vi.fn(), reload: vi.fn() })
)

const USER = { data: { name: 'admin@example.com' } }

const makeRouter = (): Router =>
	createRouter({ history: createMemoryHistory(), routes })

// CourseOutline (the departure) beside the RouterView (the destination), so
// one mount covers both ends of the navigation under test.
const mountApp = async (router: Router, withOutline = true) => {
	const wrapper = mount(
		defineComponent({
			render: () => [
				withOutline
					? h(CourseOutline, { courseName: 'COURSE-1' })
					: null,
				h(RouterView),
			],
		}),
		{
			global: {
				plugins: [router],
				provide: { $user: USER },
				mocks: { __: (text: string) => text, $dialog: vi.fn() },
				stubs: { teleport: true },
			},
		}
	)
	await flushPromises()
	return wrapper
}

const nextNavigation = (router: Router): Promise<void> =>
	new Promise((resolve) => {
		const off = router.afterEach(() => {
			off()
			resolve()
		})
	})

const openFolderPageFromRow = async () => {
	const router = makeRouter()
	await router.push('/courses/COURSE-1')
	// The folder row lives inside its section's disclosure panel, and sections
	// open expanded only when the user chose to keep them so — seed that choice.
	rememberSectionExpansion(
		courseOutlineExpansionKey('COURSE-1', USER.data.name),
		'CH-1',
		true
	)
	const wrapper = await mountApp(router)
	const row = wrapper.find('[data-testid="open-folder"]')
	expect(row.exists()).toBe(true)
	const navigated = nextNavigation(router)
	await row.trigger('click')
	await navigated
	await flushPromises()
	return { wrapper, router }
}

beforeEach(() => {
	localStorage.clear()
	courseResource.data = { title: 'Course One', instructors: [] }
})

describe('the course folder route (task #39 UI correction)', () => {
	// resolve(), not push(): matching is synchronous and does not pull in the
	// lazy page components for an assertion purely about the route table.
	it('resolves /courses/X/folder/Y to the folder page', () => {
		const router = makeRouter()
		const resolved = router.resolve('/courses/COURSE-1/folder/FOLDER-1')
		expect(resolved.name).toBe('CourseFolder')
		expect(resolved.params).toMatchObject({
			courseName: 'COURSE-1',
			folderName: 'FOLDER-1',
		})
	})

	it('navigates from an outline folder row to the folder page, not an overlay', async () => {
		const { wrapper, router } = await openFolderPageFromRow()
		expect(router.currentRoute.value.name).toBe('CourseFolder')
		expect(router.currentRoute.value.params.folderName).toBe('FOLDER-1')

		// The gallery is its own page: rendered in the document body, never
		// inside a dialog over the course overview.
		expect(wrapper.find('[data-testid="folder-page"]').exists()).toBe(true)
		expect(wrapper.find('[data-testid="folder-gallery"]').exists()).toBe(true)
		expect(wrapper.findAll('[data-testid="folder-image"]')).toHaveLength(2)
		expect(wrapper.find('[role="dialog"]').exists()).toBe(false)

		// Student permissions preserved: the images are readable...
		expect(wrapper.text()).toContain('Материалы')
		expect(wrapper.text()).toContain('2 images')
		// ...and the upload control is absent for a non-editor.
		expect(wrapper.find('[data-testid="folder-upload-button"]').exists()).toBe(
			false
		)
		wrapper.unmount()
	})

	it('keeps image viewing: an image opens the lightbox on the folder page', async () => {
		const { wrapper } = await openFolderPageFromRow()
		await wrapper.findAll('[data-testid="folder-image"]')[0].trigger('click')
		await flushPromises()
		const lightbox = wrapper.find('[data-testid="folder-lightbox"]')
		expect(lightbox.exists()).toBe(true)
		expect(lightbox.text()).toContain('cat.jpg')
		wrapper.unmount()
	})

	it('offers breadcrumbs back to the course and the parent section', async () => {
		const { wrapper } = await openFolderPageFromRow()
		const header = wrapper.find('[data-testid="page-header"]')
		expect(header.exists()).toBe(true)
		// Course crumb and the parent section's crumb both return to the
		// course page, where the section's outline lives.
		const backLinks = header.findAll('a[href="/courses/COURSE-1"]')
		expect(backLinks.length).toBeGreaterThanOrEqual(2)
		expect(header.text()).toContain('Course One')
		expect(header.text()).toContain('Chapter One')
		// The folder itself is the current page, not a link.
		const currentLabels = header.findAll('span').map((span) => span.text())
		expect(
			currentLabels.some((label) => label.includes('Материалы'))
		).toBe(true)
		wrapper.unmount()
	})

	it('shows a course editor the upload controls on the folder page', async () => {
		courseResource.data = {
			title: 'Course One',
			instructors: [{ name: USER.data.name }],
		}
		const router = makeRouter()
		await router.push('/courses/COURSE-1/folder/FOLDER-1')
		const wrapper = await mountApp(router, false)
		expect(wrapper.find('[data-testid="folder-upload-button"]').exists()).toBe(
			true
		)
		wrapper.unmount()
	})

	it('shows a missing folder with a way back to the course', async () => {
		const router = makeRouter()
		await router.push('/courses/COURSE-1/folder/GONE')
		const wrapper = await mountApp(router, false)
		expect(wrapper.find('[data-testid="folder-not-found"]').exists()).toBe(
			true
		)
		const navigated = nextNavigation(router)
		await wrapper.find('[data-testid="folder-back-to-course"]').trigger('click')
		await navigated
		await flushPromises()
		expect(router.currentRoute.value.name).toBe('CourseDetail')
		expect(wrapper.text()).toContain('COURSE')
		wrapper.unmount()
	})
})
