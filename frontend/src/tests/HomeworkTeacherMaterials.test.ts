import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ call: vi.fn() }))
vi.mock('frappe-ui', () => ({
	call: api.call,
	toast: { error: vi.fn() },
	Button: { template: '<button><slot /></button>' },
	FileUploader: { template: '<div data-testid="uploader" />' },
}))

import Panel from '@/components/HomeworkTeacherMaterials.vue'

if (!('format' in String.prototype)) {
	Object.defineProperty(String.prototype, 'format', {
		value(this: string, ...args: unknown[]) {
			return this.replace(/\{(\d+)\}/g, (_: string, index: string) =>
				String(args[Number(index)] ?? '')
			)
		},
	})
}

describe('teacher material loading', () => {
	it('shows loading instead of an empty panel with a zero budget', async () => {
		let resolve!: (data: unknown) => void
		api.call.mockReturnValueOnce(
			new Promise((done) => {
				resolve = done
			})
		)
		const wrapper = mount(Panel, {
			props: { homework: 'hw-template' },
			global: { mocks: { __: (s: string) => s } },
		})
		expect(wrapper.text()).toContain('Loading…')
		expect(wrapper.find('[data-testid="materials-quota"]').exists()).toBe(false)
		expect(wrapper.find('[data-testid="uploader"]').exists()).toBe(false)
		resolve({
			materials: [],
			materials_budget: {
				quota: 20 * 1024 * 1024,
				remaining: 20 * 1024 * 1024,
			},
		})
		await flushPromises()
		expect(wrapper.find('[data-testid="materials-quota"]').text()).toContain(
			'20'
		)
		expect(wrapper.find('[data-testid="uploader"]').exists()).toBe(true)
		wrapper.unmount()
	})
})
