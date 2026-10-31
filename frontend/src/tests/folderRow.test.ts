import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

vi.stubGlobal('__', (text: string) => text)

String.prototype.format = function (this: string, ...args: unknown[]): string {
	return this.replace(/{(\d+)}/g, (match, index) =>
		args[Number(index)] === undefined ? match : String(args[Number(index)])
	)
}

// OutlineActionButton renders frappe-ui's Tooltip; a passthrough keeps the
// real button (and its aria-label/disabled attributes) in the tree.
vi.mock('frappe-ui', () => ({
	Tooltip: {
		name: 'Tooltip',
		props: ['text', 'side'],
		template: `<div><slot /></div>`,
	},
}))

import FolderRow from '@/components/FolderRow.vue'
import type { OutlineFolder } from '@/types'
import { routes } from '@/routes'
import {
	createMemoryHistory,
	createRouter,
	type Router,
} from 'vue-router'

// The REAL route table: the folder row is a router-link now (task #39 UI
// correction — the gallery is a page, not a modal), so the link is asserted
// against the routes the app actually registers.
const makeRouter = (): Router =>
	createRouter({ history: createMemoryHistory(), routes })

// OutlineActionButton renders frappe-ui's Tooltip; a passthrough keeps the
// real button (and its aria-label/disabled attributes) in the tree.
function mountRow(props: Record<string, unknown>) {
	return mount(FolderRow, {
		props: { courseName: 'COURSE-1', ...props },
		global: {
			plugins: [makeRouter()],
			config: { globalProperties: { __: (s: string) => s } as any },
		},
	})
}

const folder: OutlineFolder = {
	name: '0001 Materials',
	title: 'Наглядные материалы',
	position: 2,
	image_count: 12,
	images: [],
}

function buttonByLabel(wrapper: ReturnType<typeof mount>, label: string) {
	return wrapper
		.findAll('button')
		.find((button) => button.attributes('aria-label') === label)
}

describe('FolderRow (task #39)', () => {
	beforeEach(() => {
		vi.clearAllMocks()
	})

	it('renders the folder title and its image count', () => {
		const wrapper = mountRow({ folder })
		expect(wrapper.text()).toContain('Наглядные материалы')
		expect(wrapper.text()).toContain('12 images')
		expect(wrapper.attributes('data-testid')).toBe('outline-folder')
	})

	it('singularises the count for one image', () => {
		const wrapper = mountRow({
			folder: { ...folder, image_count: 1 },
		})
		expect(wrapper.text()).toContain('1 image')
	})

	it('links the folder row to its own course page', () => {
		const wrapper = mountRow({ folder })
		const link = wrapper.find('[data-testid="open-folder"]')
		// A navigation element, not an action button: the gallery opens as a
		// dedicated page (task #39 UI correction), never an overlay.
		expect(link.element.tagName).toBe('A')
		expect(link.attributes('href')).toBe(
			`/courses/COURSE-1/folder/${encodeURIComponent(folder.name)}`
		)
	})

	it('shows no editing actions for a student', () => {
		const wrapper = mountRow({
			folder,
			allowEdit: false,
		})
		expect(buttonByLabel(wrapper, 'Rename folder')).toBeUndefined()
		expect(buttonByLabel(wrapper, 'Delete folder')).toBeUndefined()
		expect(buttonByLabel(wrapper, 'Move folder up')).toBeUndefined()
		expect(buttonByLabel(wrapper, 'Move folder down')).toBeUndefined()
	})

	it('emits rename and delete for an editor', () => {
		const wrapper = mountRow({
			folder,
			allowEdit: true,
			position: 1,
			siblingCount: 2,
		})
		buttonByLabel(wrapper, 'Rename folder')!.trigger('click')
		buttonByLabel(wrapper, 'Delete folder')!.trigger('click')
		expect(wrapper.emitted('rename-folder')![0][0]).toMatchObject({
			name: folder.name,
		})
		expect(wrapper.emitted('delete-folder')![0][0]).toMatchObject({
			name: folder.name,
		})
	})

	it('moves up and down, disabled at the ends of the mixed order', () => {
		const wrapper = mountRow({
			folder,
			allowEdit: true,
			position: 2,
			siblingCount: 3,
		})
		buttonByLabel(wrapper, 'Move folder up')!.trigger('click')
		buttonByLabel(wrapper, 'Move folder down')!.trigger('click')
		expect(wrapper.emitted('move-folder')).toEqual([['up'], ['down']])
		expect(
			buttonByLabel(wrapper, 'Move folder up')!.attributes('disabled')
		).toBeUndefined()
		expect(
			buttonByLabel(wrapper, 'Move folder down')!.attributes('disabled')
		).toBeUndefined()
	})

	it('disables up at the first row and down at the last row', () => {
		const first = mountRow({
			folder,
			allowEdit: true,
			position: 1,
			siblingCount: 3,
		})
		expect(
			buttonByLabel(first, 'Move folder up')!.attributes('disabled')
		).toBeDefined()
		expect(
			buttonByLabel(first, 'Move folder down')!.attributes('disabled')
		).toBeUndefined()

		const last = mountRow({
			folder,
			allowEdit: true,
			position: 3,
			siblingCount: 3,
		})
		expect(
			buttonByLabel(last, 'Move folder down')!.attributes('disabled')
		).toBeDefined()
	})
})
