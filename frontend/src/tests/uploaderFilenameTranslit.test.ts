import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

const { UploadError, toastError } = vi.hoisted(() => {
	window.matchMedia ??= (() => ({
		matches: false,
		addEventListener: () => {},
		removeEventListener: () => {},
	})) as unknown as typeof window.matchMedia
	class UploadError extends Error {
		messages: string[]
		constructor(message: string, options: { messages?: string[] }) {
			super(message)
			this.messages = options.messages ?? []
		}
	}
	return { UploadError, toastError: vi.fn() }
})

vi.mock('frappe-ui', async () => {
	const { h } = await import('vue')
	return {
		FileUploader: {
			name: 'FileUploader',
			props: ['private', 'fileTypes', 'validateFile'],
			emits: ['success', 'failure'],
			// The real frappe-ui input is a sibling of the slot, not inside it.
			setup(_: unknown, { slots }: any) {
				return () => [
					h('input', { type: 'file', class: 'mock-file-input' }),
					h('div', slots.default?.({ openFileSelector: () => {} })),
				]
			},
		},
		Button: { template: '<button><slot /></button>' },
		UploadError,
		toast: { success: vi.fn(), error: toastError },
	}
})

vi.mock('@/utils', async () => {
	// The real @/utils imports plyr, which reads matchMedia at import time.
	const actual = await vi.importActual<typeof import('@/utils')>('@/utils')
	return { validateFile: actual.validateFile }
})

vi.mock('frappe-ui/experimental', async () => {
	const { h, defineComponent } = await import('vue')
	const stub = (name: string) =>
		defineComponent({ name, render: () => h('div') })
	const useInputLabeling = () => ({
		inputId: 'input-id',
		labelId: 'label-id',
		descriptionId: 'description-id',
		errorMessageId: 'error-id',
		hasError: false,
		errorLines: [] as string[],
		showDescription: false,
	})
	return {
		InputDescription: stub('InputDescription'),
		InputError: stub('InputError'),
		InputLabel: stub('InputLabel'),
		useInputLabeling,
	}
})

const mountUploader = async () => {
	const Uploader = (await import('@/components/Controls/Uploader.vue')).default
	return mount(Uploader, {
		props: { modelValue: null },
		global: { mocks: { __: (s: string) => s } },
	})
}

const setInputFiles = (input: HTMLInputElement, files: File[]) => {
	Object.defineProperty(input, 'files', { value: files, configurable: true })
}

describe('Uploader: cyrillic filename transliteration', () => {
	it('renames a cyrillic file before the uploader reads it', async () => {
		const w = await mountUploader()
		const input = w.find('input[type="file"]').element
		setInputFiles(input, [
			new File(['body'], 'Домашка_Глава1.jpg', { type: 'image/jpeg' }),
		])
		input.dispatchEvent(new Event('change'))
		expect(input.files?.[0].name).toBe('Domashka_Glava1.jpg')
		expect(input.files?.[0].type).toBe('image/jpeg')
	})

	it('renames each cyrillic file in a multi-file selection', async () => {
		const w = await mountUploader()
		const input = w.find('input[type="file"]').element
		setInputFiles(input, [
			new File(['a'], 'Фото.png', { type: 'image/png' }),
			new File(['b'], 'Видео.mp4', { type: 'video/mp4' }),
			new File(['c'], 'Аудио.mp3', { type: 'audio/mpeg' }),
		])
		input.dispatchEvent(new Event('change'))
		expect([...(input.files ?? [])].map((f) => f.name)).toEqual([
			'Foto.png',
			'Video.mp4',
			'Audio.mp3',
		])
	})

	it('leaves latin filenames untouched', async () => {
		const w = await mountUploader()
		const input = w.find('input[type="file"]').element
		const original = new File(['body'], 'cover.png', { type: 'image/png' })
		setInputFiles(input, [original])
		input.dispatchEvent(new Event('change'))
		expect(input.files?.[0]).toBe(original)
		expect(input.files?.[0].name).toBe('cover.png')
	})

	it('removes the capture listener on unmount', async () => {
		const w = await mountUploader()
		const input = w.find('input[type="file"]').element
		w.unmount()
		setInputFiles(input, [
			new File(['body'], 'Обложка.jpg', { type: 'image/jpeg' }),
		])
		input.dispatchEvent(new Event('change'))
		expect(input.files?.[0].name).toBe('Обложка.jpg')
	})
})
