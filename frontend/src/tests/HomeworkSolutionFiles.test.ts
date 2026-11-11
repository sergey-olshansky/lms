import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Card #45 + R04/R05 (round 6) + hotfix 2026-10-25: the solution-files panel
// against the REAL batch uploader component -- the queue posts the picked
// files sequentially, ONE request per file (per-file atomicity), the
// client gate blocks a file that cannot fit the cumulative remaining quota
// BEFORE the network, a failed file reports its cause and stops the queue
// while the files that fit stay, and the one-request registration contract
// holds: no follow-up attach_file call (the prod incident was exactly that
// lost hand-off). The teacher scope additionally renders the photo gallery
// and the one-zip archive link.
const state = vi.hoisted(() => ({
	upload: vi.fn(),
	calls: { methods: [] as string[] },
	listPayload: null,
}))

// The frappe-ui transport (FileUploadHandler is exported from the package
// root): mocked at the module name -- no absolute paths, so the suite runs
// on any checkout.
vi.mock('frappe-ui', () => {
	class FakeHandler {
		listeners: Record<string, Function[]> = {}
		on(event: string, handler: Function) {
			;(this.listeners[event] ||= []).push(handler)
		}
		trigger(event: string, data?: unknown) {
			;(this.listeners[event] || []).forEach((handler) => handler(data))
		}
		upload(file: File, options: unknown) {
			this.trigger('start')
			this.trigger('progress', { uploaded: (file.size || 1) / 2, total: file.size || 1 })
			return state.upload(file, options)
		}
	}
	return {
		FileUploadHandler: FakeHandler,
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

const studentPayload = () => ({
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
	quota: 100 * 1024 * 1024,
	can_upload: true,
})

const teacherPayload = () => ({
	rows: [
		{
			name: 'row-1',
			file: 'file-1',
			file_name: 'page-1.png',
			file_size: 2048,
			uploaded_at: '2026-11-11 10:00:00',
			uploaded_by_name: 'Student',
			uploaded_by: 'student@example.com',
			file_url: '/private/files/page-1.png',
			download_url: '/private/files/page-1.png?download=1',
			can_delete: false,
		},
		{
			name: 'row-2',
			file: 'file-2',
			file_name: 'notes.txt',
			file_size: 32,
			uploaded_at: '2026-11-11 10:01:00',
			uploaded_by_name: 'Student',
			uploaded_by: 'student@example.com',
			file_url: '/private/files/notes.txt',
			download_url: '/private/files/notes.txt?download=1',
			can_delete: false,
		},
	],
	used: 2080,
	remaining: 0,
	quota: 100 * 1024 * 1024,
	can_upload: false,
})

beforeEach(() => {
	state.upload.mockReset()
	state.upload.mockImplementation(async (file: File) => ({
		name: 'row-9',
		file_name: file.name,
		state: { used: 20, quota: 100 * 1024 * 1024, remaining: 100 * 1024 * 1024 - 20 },
	}))
	state.calls.methods.length = 0
	state.listPayload = studentPayload()
})

const render = async (viewerCanTeach = false) => {
	const wrapper = mount(Panel, {
		props: {
			detail: { data: { name: 'hw-1', viewer_can_teach: viewerCanTeach } },
		},
		global: { mocks: { __: (s: string) => s } },
	})
	await flushPromises()
	return wrapper
}

const pick = async (wrapper: ReturnType<typeof mount>, files: [string, number][]) => {
	const input = wrapper.find('input[type=file]')
	expect(input.exists()).toBe(true)
	Object.defineProperty(input.element, 'files', {
		value: files.map(
			([name, size]) => new File(['x'.repeat(size)], name, { type: 'text/plain' })
		),
		configurable: true,
	})
	await input.trigger('change')
	await flushPromises()
}

const queueStatus = (wrapper: ReturnType<typeof mount>) =>
	wrapper.findAll('[data-testid^="batch-status-"]').map((node) => node.text())

describe('HomeworkSolutionFiles (card #45 batch + archive)', () => {
	it('uploads a file that fits the remaining quota', async () => {
		const wrapper = await render()
		await pick(wrapper, [['solution.txt', 10]])
		expect(state.upload).toHaveBeenCalledOnce()
		expect(wrapper.emitted('uploading')).toEqual([[true], [false]])
		wrapper.unmount()
	})

	it('uploads a picked batch sequentially, one request per file', async () => {
		const wrapper = await render()
		await pick(wrapper, [
			['photo-1.png', 10],
			['photo-2.png', 20],
			['photo-3.png', 30],
		])
		expect(state.upload).toHaveBeenCalledTimes(3)
		expect(state.upload.mock.calls.map(([file]) => file.name)).toEqual([
			'photo-1.png',
			'photo-2.png',
			'photo-3.png',
		])
		expect(queueStatus(wrapper)).toEqual(['Attached', 'Attached', 'Attached'])
		expect(wrapper.emitted('uploading')).toEqual([[true], [false]])
		wrapper.unmount()
	})

	it('blocks a file that exceeds the remaining quota before the network', async () => {
		const wrapper = await render()
		// listPayload.remaining = 100 bytes.
		await pick(wrapper, [['big.bin', 101]])
		expect(state.upload).not.toHaveBeenCalled()
		wrapper.unmount()
	})

	it('stops the queue at a failed file and keeps the files that fit', async () => {
		const wrapper = await render()
		state.upload.mockImplementation(async (file: File) => {
			if (file.name === 'photo-2.png') {
				throw new Error(
					'The solution files together cannot exceed 100 MB. Used: 98.0 MB, remaining: 2.0 MB.'
				)
			}
			return {
				name: 'row-9',
				file_name: file.name,
				state: { used: 20, quota: 100 * 1024 * 1024, remaining: 100 * 1024 * 1024 - 20 },
			}
		})
		await pick(wrapper, [
			['photo-1.png', 10],
			['photo-2.png', 20],
			['photo-3.png', 30],
		])
		// The overflowing file reported its cause and the queue stopped: the
		// third file never travelled, the first one stayed attached.
		expect(state.upload).toHaveBeenCalledTimes(2)
		const statuses = queueStatus(wrapper)
		expect(statuses[0]).toBe('Attached')
		expect(statuses[1]).toBe('Failed')
		expect(statuses[2]).toBe('Not uploaded')
		const error = wrapper.find('[data-testid^="batch-error-"]').text()
		expect(error).toContain('cannot exceed 100 MB')
		// The batch end reconciles from the server.
		expect(state.calls.methods).toContain('lms.lms.homework_attachments.list_attachments')
		expect(wrapper.emitted('uploading')).toEqual([[true], [false]])
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
		const wrapper = await render()
		state.calls.methods.length = 0
		await pick(wrapper, [
			['photo-1.png', 10],
			['photo-2.png', 20],
		])
		expect(state.upload).toHaveBeenCalledTimes(2)
		expect(state.calls.methods).not.toContain(
			'lms.lms.homework_attachments.attach_file'
		)
		wrapper.unmount()
	})

	it('survives a payload it cannot parse and still reconciles from the server', async () => {
		const wrapper = await render()
		state.upload.mockImplementationOnce(async () => null)
		await pick(wrapper, [['solution.txt', 10]])
		expect(state.upload).toHaveBeenCalledOnce()
		expect(wrapper.emitted('uploading')).toEqual([[true], [false]])
		expect(state.calls.methods).toContain(
			'lms.lms.homework_attachments.list_attachments'
		)
		wrapper.unmount()
	})
})

describe('HomeworkSolutionFiles (teacher gallery + archive, card #45)', () => {
	beforeEach(() => {
		state.listPayload = teacherPayload()
	})

	it('renders the photo gallery for the teacher scope only', async () => {
		const wrapper = await render(true)
		expect(wrapper.find('[data-testid="solution-gallery"]').exists()).toBe(true)
		const photo = wrapper.find('[data-testid="solution-photo-row-1"]')
		expect(photo.exists()).toBe(true)
		const image = photo.find('img')
		expect(image.attributes('src')).toBe('/private/files/page-1.png')
		wrapper.unmount()

		const asStudent = await render(false)
		expect(asStudent.find('[data-testid="solution-gallery"]').exists()).toBe(false)
		asStudent.unmount()
	})

	it('opens a gallery photo full-size and offers the raw file', async () => {
		const wrapper = await render(true)
		await wrapper.find('[data-testid="solution-photo-row-1"]').trigger('click')
		const lightbox = wrapper.find('[data-testid="solution-photo-lightbox"]')
		expect(lightbox.exists()).toBe(true)
		const full = wrapper.find('[data-testid="solution-photo-full"]')
		expect(full.attributes('src')).toBe('/private/files/page-1.png')
		const open = wrapper.find('[data-testid="solution-photo-open"]')
		expect(open.attributes('href')).toBe('/private/files/page-1.png')
		await wrapper.find('[data-testid="solution-photo-close"]').trigger('click')
		expect(wrapper.find('[data-testid="solution-photo-lightbox"]').exists()).toBe(false)
		wrapper.unmount()
	})

	it('links the streamed zip archive for the teacher scope only', async () => {
		const wrapper = await render(true)
		const link = wrapper.find('[data-testid="solution-archive-download"]')
		expect(link.exists()).toBe(true)
		expect(link.attributes('href')).toBe(
			'/api/method/lms.lms.homework_attachments.download_solution_archive?assignment=hw-1'
		)
		wrapper.unmount()

		const asStudent = await render(false)
		expect(asStudent.find('[data-testid="solution-archive-download"]').exists()).toBe(false)
		asStudent.unmount()
	})

	it('hides the archive link while there is nothing to archive', async () => {
		state.listPayload = { rows: [], used: 0, remaining: 0, quota: 100 * 1024 * 1024, can_upload: false }
		const wrapper = await render(true)
		expect(wrapper.find('[data-testid="solution-archive-download"]').exists()).toBe(false)
		wrapper.unmount()
	})
})
