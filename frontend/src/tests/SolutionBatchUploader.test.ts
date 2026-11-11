import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Card #45: the batch uploader component on its own. The vendored
// frappe-ui FileUploader posts only files[0]; this local wrap posts the
// whole pick SEQUENTIALLY, one request per file, so the per-file verdicts
// stay atomic. Here: pick order, the per-file client gate (cumulative
// remaining), the failure that stops the queue with a cause-named report,
// and the live per-file progress.
const state = vi.hoisted(() => ({
	upload: vi.fn(),
}))

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
			return state.upload(file, options)
		}
	}
	return { FileUploadHandler: FakeHandler }
})

import Uploader from '@/components/SolutionBatchUploader.vue'

beforeEach(() => {
	state.upload.mockReset()
	state.upload.mockImplementation(async (file: File) => ({
		name: 'row-9',
		file_name: file.name,
		state: { used: 1, quota: 100, remaining: 99 },
	}))
})

const render = (validateFile?: (file: File) => string | null) =>
	mount(Uploader, {
		props: {
			uploadEndpoint: '/api/method/lms.lms.homework_attachments.upload_solution_file',
			doctype: 'LMS Homework Assignment',
			docname: 'hw-1',
			isPrivate: true,
			...(validateFile ? { validateFile } : {}),
		},
		global: { mocks: { __: (s: string) => s } },
	})

const pick = async (wrapper: ReturnType<typeof mount>, files: [string, number][]) => {
	const input = wrapper.find('input[type=file]')
	expect(input.exists()).toBe(true)
	expect(input.attributes('multiple')).toBeDefined()
	Object.defineProperty(input.element, 'files', {
		value: files.map(
			([name, size]) => new File(['x'.repeat(size)], name, { type: 'text/plain' })
		),
		configurable: true,
	})
	await input.trigger('change')
	await flushPromises()
}

const statuses = (wrapper: ReturnType<typeof mount>) =>
	wrapper.findAll('[data-testid^="batch-status-"]').map((node) => node.text())

describe('SolutionBatchUploader (card #45)', () => {
	it('posts the picked files sequentially, one request per file in pick order', async () => {
		const wrapper = render()
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
		// The transport contract is unchanged: private, the assignment as the
		// docname, the single-request homework endpoint.
		const [, options] = state.upload.mock.calls[0]
		expect(options).toEqual({
			private: true,
			folder: 'Home',
			doctype: 'LMS Homework Assignment',
			docname: 'hw-1',
			upload_endpoint: '/api/method/lms.lms.homework_attachments.upload_solution_file',
		})
		expect(statuses(wrapper)).toEqual(['Attached', 'Attached', 'Attached'])
		wrapper.unmount()
	})

	it('emits uploading for the whole batch and a per-file success each', async () => {
		const wrapper = render()
		await pick(wrapper, [
			['a.png', 5],
			['b.png', 5],
		])
		expect(wrapper.emitted('uploading')).toEqual([[true], [false]])
		const successes = wrapper.emitted('file-success') || []
		expect(successes).toHaveLength(2)
		expect(successes[0][0]).toMatchObject({ name: 'row-9', file_name: 'a.png' })
		const done = wrapper.emitted('batch-done')?.at(-1)?.[0]
		expect(done).toMatchObject({ uploaded: 2, failed: 0, blocked: 0, total: 2 })
		wrapper.unmount()
	})

	it('consults the cumulative client gate before EVERY file', async () => {
		const validateFile = vi.fn(() => null)
		const wrapper = render(validateFile)
		await pick(wrapper, [
			['a.png', 5],
			['b.png', 5],
		])
		expect(validateFile).toHaveBeenCalledTimes(2)
		expect(state.upload).toHaveBeenCalledTimes(2)
		wrapper.unmount()
	})

	it('stops the queue at a server refusal and reports the cause', async () => {
		const wrapper = render()
		state.upload.mockImplementation(async (file: File) => {
			if (file.name === 'b.png') {
				throw new Error(
					'The solution files together cannot exceed 100 MB. Used: 98.0 MB, remaining: 2.0 MB.'
				)
			}
			return { name: 'row-9', file_name: file.name, state: { used: 1, quota: 100, remaining: 99 } }
		})
		await pick(wrapper, [
			['a.png', 5],
			['b.png', 5000],
			['c.png', 5],
		])
		expect(state.upload).toHaveBeenCalledTimes(2)
		const current = statuses(wrapper)
		expect(current[0]).toBe('Attached')
		expect(current[1]).toBe('Failed')
		expect(current[2]).toBe('Not uploaded')
		expect(wrapper.find('[data-testid="batch-error-1"]').text()).toContain(
			'cannot exceed 100 MB'
		)
		const done = wrapper.emitted('batch-done')?.at(-1)?.[0]
		expect(done).toMatchObject({ uploaded: 1, failed: 1, blocked: 1, total: 3 })
		expect(wrapper.emitted('uploading')).toEqual([[true], [false]])
		wrapper.unmount()
	})

	it('stops the queue when the client gate blocks a file before the network', async () => {
		let remaining = 10
		const validateFile = vi.fn((file: File) =>
			file.size > remaining ? 'This file does not fit the remaining 0.0 MB.' : null
		)
		const wrapper = render(validateFile)
		state.upload.mockImplementation(async (file: File) => {
			remaining -= file.size
			return { name: 'row-9', file_name: file.name, state: { used: 1, quota: 100, remaining } }
		})
		await pick(wrapper, [
			['a.png', 5],
			['b.png', 9],
			['c.png', 5],
		])
		// a fits (5 of 10); b would overflow the refreshed remaining (5):
		// blocked client-side, queue stops, c never travels.
		expect(state.upload).toHaveBeenCalledTimes(1)
		const current = statuses(wrapper)
		expect(current[0]).toBe('Attached')
		expect(current[1]).toBe('Failed')
		expect(current[2]).toBe('Not uploaded')
		expect(wrapper.find('[data-testid="batch-error-1"]').text()).toContain(
			'does not fit the remaining'
		)
		wrapper.unmount()
	})

	it('shows live per-file progress while a photo uploads', async () => {
		const wrapper = render()
		let resolveUpload: (value: unknown) => void = () => {}
		state.upload.mockImplementationOnce(
			() =>
				new Promise((resolve) => {
					resolveUpload = resolve
				})
		)
		const input = wrapper.find('input[type=file]')
		Object.defineProperty(input.element, 'files', {
			value: [new File(['x'.repeat(1000)], 'slow.png', { type: 'image/png' })],
			configurable: true,
		})
		await input.trigger('change')
		// 'start' fired synchronously; the file is mid-flight.
		await flushPromises()
		expect(wrapper.find('[data-testid="batch-status-0"]').text()).toBe('Uploading')
		resolveUpload({ name: 'row-9', file_name: 'slow.png', state: { used: 1, quota: 100, remaining: 99 } })
		await flushPromises()
		expect(wrapper.find('[data-testid="batch-status-0"]').text()).toBe('Attached')
		wrapper.unmount()
	})

	it('re-allows picking a new batch after one finishes', async () => {
		const wrapper = render()
		await pick(wrapper, [['a.png', 5]])
		expect(statuses(wrapper)).toEqual(['Attached'])
		await pick(wrapper, [['b.png', 5]])
		// The queue reflects only the new pick.
		expect(statuses(wrapper)).toEqual(['Attached'])
		expect(state.upload).toHaveBeenCalledTimes(2)
		wrapper.unmount()
	})
})
