import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MoveSectionModal from '@/components/Modals/MoveSectionModal.vue'
import type { OutlineChapter, Resource } from '@/types'

const { submit } = vi.hoisted(() => ({ submit: vi.fn() }))

vi.mock('frappe-ui', () => ({
	createResource: () => ({ submit }),
	toast: { success: vi.fn(), error: vi.fn() },
	Dialog: {
		props: ['open', 'actions'],
		template: `<div v-if="open"><slot /><button
			v-for="action in actions" :key="action.label" data-testid="move-submit"
			:disabled="action.disabled || action.loading" @click="action.onClick()"
		>{{ action.label }}</button></div>`,
	},
	FormControl: {
		props: ['modelValue'],
		emits: ['update:modelValue'],
		template: `<input :value="modelValue" @input="$emit('update:modelValue', $event.target.value)" />`,
	},
	Tooltip: { template: '<div><slot /></div>' },
}))

const branch: OutlineChapter = {
	name: 'PARENT',
	title: 'Parent',
	idx: 1,
	level: 1,
	sections: [{ name: 'MOVED', title: 'Moved section', idx: 1, level: 2 }],
}
const moved = branch.sections![0]
const outline: OutlineChapter[] = [
	branch,
	{ name: 'TARGET', title: 'Destination', idx: 2, level: 1 },
	{ name: 'DEEP', title: 'Deepest', idx: 3, level: 4 },
	{ name: 'SCORM', title: 'SCORM', idx: 4, level: 1, is_scorm_package: 1 },
]

async function openModal(section = moved) {
	const wrapper = mount(MoveSectionModal, {
		props: {
			courseName: 'COURSE',
			outline: { data: outline, reload: vi.fn() } as unknown as Resource<
				OutlineChapter[] | null
			>,
		},
		global: { mocks: { __ } },
	})
	wrapper.vm.open(section)
	await wrapper.vm.$nextTick()
	return wrapper
}

beforeEach(() => submit.mockReset())

describe('moving existing sections', () => {
	it('enables confirmation for the course root and sends a null parent', async () => {
		const wrapper = await openModal()
		const confirm = wrapper.get('[data-testid="move-submit"]')
		expect((confirm.element as HTMLButtonElement).disabled).toBe(true)

		await wrapper.get('[data-testid="move-target-root"]').trigger('click')
		expect((confirm.element as HTMLButtonElement).disabled).toBe(false)
		await confirm.trigger('click')
		expect(submit).toHaveBeenCalledExactlyOnceWith({
			section: 'MOVED',
			target_parent: null,
		})
	})

	it('moves the existing section by name to a selected section', async () => {
		const wrapper = await openModal()
		await wrapper.get('[data-testid="move-target-TARGET"]').trigger('click')
		await wrapper.get('[data-testid="move-submit"]').trigger('click')
		expect(submit).toHaveBeenCalledExactlyOnceWith({
			section: 'MOVED',
			target_parent: 'TARGET',
		})
	})

	it('excludes the moved subtree and SCORM and blocks destinations beyond depth four', async () => {
		const wrapper = await openModal(branch)
		expect(wrapper.find('[data-testid="move-target-PARENT"]').exists()).toBe(
			false
		)
		expect(wrapper.find('[data-testid="move-target-MOVED"]').exists()).toBe(
			false
		)
		expect(wrapper.find('[data-testid="move-target-SCORM"]').exists()).toBe(
			false
		)
		const deepest = wrapper.get('[data-testid="move-target-DEEP"]')
		expect((deepest.element as HTMLButtonElement).disabled).toBe(true)
		await deepest.trigger('click')
		expect(
			(wrapper.get('[data-testid="move-submit"]').element as HTMLButtonElement)
				.disabled
		).toBe(true)
		expect(submit).not.toHaveBeenCalled()
	})
})
