import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// R04/R05 (round 6) + hotfix 2026-10-25: the solution-files panel against
// the REAL FileUploader contract -- falsy validateFile result allows the
// upload, a truthy message blocks it BEFORE the network -- plus the download
// action every reader gets, and the one-request registration contract: a
// successful upload does NOT fire a second attach_file call (the prod
// incident was exactly that lost hand-off), and a payload the component
// cannot parse must not break the panel.
const state = vi.hoisted(() => ({
	upload: vi.fn(async () => ({ name: 'row-9', state: { used: 20, quota: 20971520, remaining: 20971500 } })),
	calls: { methods: [] as string[] },
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
				download_url: '/private/files/solution.pdf?download=1',
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
		call: (method: string) => {
			state.calls.methods.push(method)
			return method.endsWith('list_attachments')
				? Promise.resolve(state.listPayload)
				: Promise.resolve({})
		},
	}
})

if (!('format' in String.prototype)) {
	Object.defineProperty(String.prototype, 'format', {
		value(this: string, ...args: unknown[]) {
			return this.replace(
				/\{(\d+)\}/g,
				(_: string, i: string) =>
					// @ts-expect-error index access on unknown
					args[Number(i)] ?? ''
			)
		},
	})
}

import Panel from '@/components/HomeworkSolutionFiles.vue'

beforeEach(() => {
	state.upload.mockClear()
	state.upload.mockImplementation(async () => ({
		name: 'row-9',
		state: { used: 20, quota: 20971520, remaining: 20971500 },
	}))
	state.calls.methods.length = 0
})

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
		value: [
			new File(['x'.repeat(size)], 'solution.txt', { type: 'text/plain' }),
		],
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
		expect(wrapper.emitted('uploading')).toEqual([[true], [false]])
		wrapper.unmount()
	})

	it('blocks a file that exceeds the remaining quota before the network', async () => {
		const wrapper = await render()
		await pick(wrapper, 101)
		expect(state.upload).not.toHaveBeenCalled()
		wrapper.unmount()
	})

	it('renders a download action with the forced-download URL for an existing solution', async () => {
		const wrapper = await render()
		const link = wrapper.find('[data-testid="solution-download-row-1"]')
		expect(link.exists()).toBe(true)
		expect(link.attributes('href')).toBe('/private/files/solution.pdf?download=1')
		wrapper.unmount()
	})

	it('registers in the upload request itself -- no follow-up attach_file call', async () => {
		// The prod incident of 2026-10-25: the upload succeeded and the
		// browser then had to PARSE the generic endpoint's response to fire
		// the registration. The single-request contract must keep every
		// registration decision on the server.
		const wrapper = await render()
		state.calls.methods.length = 0
		await pick(wrapper, 10)
		expect(state.upload).toHaveBeenCalledOnce()
		expect(state.calls.methods).not.toContain(
			'lms.lms.homework_attachments.attach_file'
		)
		expect(wrapper.emitted('uploading')).toEqual([[true], [false]])
		wrapper.unmount()
	})

	it('survives a payload it cannot parse and still reconciles from the server', async () => {
		const wrapper = await render()
		state.upload.mockImplementationOnce(async () => null)
		await pick(wrapper, 10)
		expect(state.upload).toHaveBeenCalledOnce()
		expect(wrapper.emitted('uploading')).toEqual([[true], [false]])
		expect(state.calls.methods).toContain(
			'lms.lms.homework_attachments.list_attachments'
		)
		wrapper.unmount()
	})
})
