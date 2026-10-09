/**
 * Tests for ImportChemedgePdfTrainerModal.vue: the optional per-file
 * first/last task-number range.
 *
 * The goal is to pin: empty fields send no range parameters (full import),
 * filled fields send them through importer.submit, light client validation
 * (both-or-neither, whole numbers, first <= last) stops the request with
 * file.error + toast, and backend errors keep landing in file.error + toast.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ImportChemedgePdfTrainerModal from '@/components/Modals/ImportChemedgePdfTrainerModal.vue'

// frappe-ui cannot load under vitest; hoisted spies are shared between the
// mock factory and the tests.
const { submitMock, toastMock, closeMock, pushMock } = vi.hoisted(() => ({
	submitMock: vi.fn(),
	toastMock: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
	closeMock: vi.fn(),
	pushMock: vi.fn(),
}))

vi.mock('frappe-ui', () => ({
	Button: {
		props: ['variant', 'theme', 'size', 'disabled', 'loading'],
		template: `
			<button :disabled="disabled || loading"><slot /></button>
		`,
	},
	// Minimal but functional: a native control behind the label, so the
	// show-answers tests can read and toggle it like the real component.
	Checkbox: {
		props: ['label', 'modelValue', 'disabled'],
		emits: ['update:modelValue'],
		template: `
			<label>
				<input
					type="checkbox"
					:checked="!!modelValue"
					:disabled="disabled"
					@change="$emit('update:modelValue', $event.target.checked)"
				/>
				{{ label }}
			</label>
		`,
	},
	createResource: () => ({ submit: submitMock }),
	Dialog: {
		// Mirrors Dialog: v-model:open, title/actions props, default slot.
		props: ['open', 'title', 'actions', 'size'],
		setup() {
			return { closeMock }
		},
		template: `
			<div v-if="open">
				<div data-testid="title">{{ title }}</div>
				<slot />
				<button
					v-for="a in actions"
					:key="a.label"
					:data-testid="'action-' + a.label"
					@click="a.onClick({ close: closeMock })"
				>{{ a.label }}</button>
			</div>
		`,
	},
	FileUploadHandler: class {
		on(_event: string, _handler: unknown) {}
		async upload(file: File) {
			return { name: `uploaded-${file.name}`, file_name: file.name }
		}
	},
	toast: toastMock,
}))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: pushMock }) }))

const mountModal = () =>
	mount(ImportChemedgePdfTrainerModal, {
		props: { modelValue: true },
	})

// Push one PDF through the real hidden-input change handler with a mocked
// FileUploadHandler so the file lands in the import list.
async function addFile(
	wrapper: ReturnType<typeof mountModal>,
	name = 'trainer.pdf'
) {
	const input = wrapper.find('input[type="file"]').element as HTMLInputElement
	const file = new File(['pdf-bytes'], name, { type: 'application/pdf' })
	Object.defineProperty(input, 'files', { value: [file], configurable: true })
	await wrapper.find('input[type="file"]').trigger('change')
	await flushPromises()
}

async function importAll(wrapper: ReturnType<typeof mountModal>) {
	await wrapper.get('[data-testid="action-Import all"]').trigger('click')
	await flushPromises()
}

function rangeInputs(wrapper: ReturnType<typeof mountModal>, id = 1) {
	return {
		first: wrapper.get(`#first-task-${id}`),
		last: wrapper.get(`#last-task-${id}`),
	}
}

beforeEach(() => {
	submitMock.mockReset()
	submitMock.mockResolvedValue({
		quiz: 'quiz-1',
		title: 'T',
		question_count: 3,
	})
	toastMock.success.mockReset()
	toastMock.error.mockReset()
	toastMock.warning.mockReset()
	closeMock.mockReset()
	pushMock.mockReset()
})

describe('ImportChemedgePdfTrainerModal: task number range', () => {
	it('renders empty number inputs per uploaded file', async () => {
		const wrapper = mountModal()
		await addFile(wrapper)
		const { first, last } = rangeInputs(wrapper)
		expect((first.element as HTMLInputElement).value).toBe('')
		expect((last.element as HTMLInputElement).value).toBe('')
		wrapper.unmount()
	})

	it('sends no range parameters when both fields stay empty', async () => {
		const wrapper = mountModal()
		await addFile(wrapper)
		await importAll(wrapper)
		expect(submitMock).toHaveBeenCalledTimes(1)
		expect(submitMock).toHaveBeenCalledWith({
			pdf_file: 'uploaded-trainer.pdf',
			source_folder: '',
			show_answers: 0,
		})
		wrapper.unmount()
	})

	it('sends both range parameters when filled', async () => {
		const wrapper = mountModal()
		await addFile(wrapper)
		const { first, last } = rangeInputs(wrapper)
		await first.setValue('1')
		await last.setValue('30')
		await importAll(wrapper)
		expect(submitMock).toHaveBeenCalledTimes(1)
		expect(submitMock).toHaveBeenCalledWith({
			pdf_file: 'uploaded-trainer.pdf',
			source_folder: '',
			show_answers: 0,
			first_task_number: '1',
			last_task_number: '30',
		})
		wrapper.unmount()
	})

	it('rejects only one filled field without calling the server', async () => {
		const wrapper = mountModal()
		await addFile(wrapper)
		const { first } = rangeInputs(wrapper)
		await first.setValue('5')
		await importAll(wrapper)
		expect(submitMock).not.toHaveBeenCalled()
		expect(toastMock.error).toHaveBeenCalledWith(
			expect.stringContaining('both the first and the last task number')
		)
		expect(wrapper.text()).toContain(
			'Fill in both the first and the last task number, or leave both empty'
		)
		wrapper.unmount()
	})

	it('rejects first greater than last without calling the server', async () => {
		const wrapper = mountModal()
		await addFile(wrapper)
		const { first, last } = rangeInputs(wrapper)
		await first.setValue('30')
		await last.setValue('1')
		await importAll(wrapper)
		expect(submitMock).not.toHaveBeenCalled()
		expect(toastMock.error).toHaveBeenCalledWith(
			expect.stringContaining('must not be greater than the last')
		)
		wrapper.unmount()
	})

	it('rejects non-integer numbers without calling the server', async () => {
		const wrapper = mountModal()
		await addFile(wrapper)
		const { first, last } = rangeInputs(wrapper)
		await first.setValue('2.5')
		await last.setValue('10')
		await importAll(wrapper)
		expect(submitMock).not.toHaveBeenCalled()
		expect(toastMock.error).toHaveBeenCalledWith(
			expect.stringContaining('whole numbers')
		)
		wrapper.unmount()
	})

	it('keeps backend errors in file.error and shows a toast', async () => {
		submitMock.mockRejectedValueOnce({
			message: 'No tasks with numbers 80–90 were found',
		})
		const wrapper = mountModal()
		await addFile(wrapper)
		const { first, last } = rangeInputs(wrapper)
		await first.setValue('80')
		await last.setValue('90')
		await importAll(wrapper)
		expect(submitMock).toHaveBeenCalledTimes(1)
		expect(wrapper.text()).toContain('No tasks with numbers 80–90 were found')
		expect(toastMock.error).toHaveBeenCalledWith(
			'trainer.pdf: No tasks with numbers 80–90 were found'
		)
		wrapper.unmount()
	})

	it('imports each file with its own range', async () => {
		const wrapper = mountModal()
		await addFile(wrapper, 'a.pdf')
		await addFile(wrapper, 'b.pdf')
		const a = rangeInputs(wrapper, 1)
		await a.first.setValue('1')
		await a.last.setValue('30')
		const b = rangeInputs(wrapper, 2)
		await b.first.setValue('31')
		await b.last.setValue('60')
		await importAll(wrapper)
		expect(submitMock).toHaveBeenCalledTimes(2)
		expect(submitMock).toHaveBeenNthCalledWith(1, {
			pdf_file: 'uploaded-a.pdf',
			source_folder: '',
			show_answers: 0,
			first_task_number: '1',
			last_task_number: '30',
		})
		expect(submitMock).toHaveBeenNthCalledWith(2, {
			pdf_file: 'uploaded-b.pdf',
			source_folder: '',
			show_answers: 0,
			first_task_number: '31',
			last_task_number: '60',
		})
		wrapper.unmount()
	})
})

describe('ImportChemedgePdfTrainerModal: show answers option', () => {
	it('leaves the show-answers checkbox unchecked by default', () => {
		const wrapper = mountModal()
		const checkbox = wrapper.get('input[type="checkbox"]')
		expect((checkbox.element as HTMLInputElement).checked).toBe(false)
		expect(wrapper.text()).toContain('Show correct answers')
		wrapper.unmount()
	})

	it('sends show_answers 1 for every import while checked', async () => {
		const wrapper = mountModal()
		await addFile(wrapper, 'a.pdf')
		await addFile(wrapper, 'b.pdf')
		await wrapper.get('input[type="checkbox"]').setValue(true)
		await importAll(wrapper)
		expect(submitMock).toHaveBeenCalledTimes(2)
		expect(submitMock).toHaveBeenNthCalledWith(1, {
			pdf_file: 'uploaded-a.pdf',
			source_folder: '',
			show_answers: 1,
		})
		expect(submitMock).toHaveBeenNthCalledWith(2, {
			pdf_file: 'uploaded-b.pdf',
			source_folder: '',
			show_answers: 1,
		})
		wrapper.unmount()
	})

	it('sends show_answers 0 again after the checkbox is unchecked', async () => {
		const wrapper = mountModal()
		await addFile(wrapper)
		await wrapper.get('input[type="checkbox"]').setValue(true)
		await wrapper.get('input[type="checkbox"]').setValue(false)
		await importAll(wrapper)
		expect(submitMock).toHaveBeenCalledWith({
			pdf_file: 'uploaded-trainer.pdf',
			source_folder: '',
			show_answers: 0,
		})
		wrapper.unmount()
	})
})
