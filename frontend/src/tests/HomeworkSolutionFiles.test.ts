import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// R04/R05 (round 6): the solution-files panel against the REAL FileUploader
// contract -- falsy validateFile result allows the upload, a truthy
// message blocks it BEFORE the network -- plus the download action every
// reader of the panel gets.
const state = vi.hoisted(() => ({
	upload: vi.fn(async () => ({ name: 'file-1' })),
	listPayload: {
		rows: [
			{
				name: 'row-1',
				file: 'file-1',
				file_name: 'solution.pdf',
				file_size: 10,
				uploaded_at: '2026-10-22 10:00:00',
				uploaded_by_name: 'Student',
				uploaded_by: 'student@example.com',
				file_url: '/private/files/solution.pdf',
				can_delete: true,
			},
		],
		used: 10,
		remaining: 100,
		quota: 20 * 1024 * 1024,
		can_upload: true,
	},
}))

// The real FileUploader's transport: mocked at its own module (absolute
// path -- package exports hide src) so a passing validation visibly reaches
// "the network" without one.
vi.mock(
	// @ts-expect-error absolute module path
	'/Users/user/Documents/projects/lms/frontend/node_modules/frappe-ui/src/utils/fileUploadHandler.ts',
	() => ({
		default: class {
			on() {}
			upload(...args: unknown[]) {
				return state.upload(...(args as []))
			}
		},
	})
)

vi.mock('frappe-ui', async () => {
	// The REAL FileUploader, loaded by absolute path (the package's exports
	// field hides its src tree from subpath imports) -- the whole point is
	// to test against the installed component's actual validateFile
	// contract, not a re-implementation of it.
	const real = await import(
		// @ts-expect-error absolute module path
		'/Users/user/Documents/projects/lms/frontend/node_modules/frappe-ui/src/components/FileUploader/FileUploader.vue'
	)
	return {
		FileUploader: real.default,
		Button: { template: '<button type="button"><slot /></button>' },
		toast: { success: vi.fn(), error: vi.fn() },
		call: vi.fn(async (method: string) =>
			method.endsWith('list_attachments') ? state.listPayload : {}
		),
	}
})

if (!('format' in String.prototype)) {
	Object.defineProperty(String.prototype, 'format', {
		value(this: string, ...args: unknown[]) {
			return this.replace(/\{(\d+)\}/g, (_: string, i: string) =>
				// @ts-expect-error index access on unknown
				args[Number(i)] ?? ''
			)
		},
	})
}

import Panel from '@/components/HomeworkSolutionFiles.vue'

beforeEach(() => state.upload.mockClear())

const render = async () => {
	const wrapper = mount(Panel, {
		props: { detail: { data: { name: 'hw-1' } } },
		global: { mocks: { __: (s: string) => s } },
	})
	await flushPromises()
	return wrapper
}

const pick = async (wrapper: ReturnType<typeof mount>, size: number) => {
	const input = wrapper.find('input[type=file]')
	Object.defineProperty(input.element, 'files', {
		value: [new File(['x'.repeat(size)], 'solution.txt', { type: 'text/plain' })],
		configurable: true,
	})
	await input.trigger('change')
	await flushPromises()
}

describe('HomeworkSolutionFiles (round-6 contract)', () => {
	it('uploads a file that fits the remaining quota', async () => {
		const wrapper = await render()
		await pick(wrapper, 10)
		expect(state.upload).toHaveBeenCalledOnce()
		wrapper.unmount()
	})

	it('blocks a file that exceeds the remaining quota before the network', async () => {
		const wrapper = await render()
		await pick(wrapper, 101)
		expect(state.upload).not.toHaveBeenCalled()
		wrapper.unmount()
	})

	it('renders a download action with the private URL for an existing solution', async () => {
		const wrapper = await render()
		const link = wrapper.find('[data-testid="solution-download-row-1"]')
		expect(link.exists()).toBe(true)
		expect(link.attributes('href')).toBe('/private/files/solution.pdf')
		wrapper.unmount()
	})
})
