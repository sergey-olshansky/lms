import { describe, expect, it, vi } from 'vitest'

// FileUploader mock renders a real hidden <input type="file"> next to the
// slot, mirroring frappe-ui@1.0.0-rc.1 (the input is a sibling of the slot,
// not inside it). The real component reads event.target.files synchronously
// from a non-capture change listener on the input, so a capture listener on an
// ancestor fires first — which is what the component under test relies on.
vi.mock('frappe-ui', async () => {
	const { h } = await import('vue')
	return {
		Button: {
			name: 'Button',
			emits: ['click'],
			setup(_: unknown, { slots }: any) {
				return () => h('button', { onClick: () => {} }, slots.default?.())
			},
		},
		ErrorMessage: {
			name: 'ErrorMessage',
			props: ['message'],
			setup(props: { message?: string }) {
				return () => h('p', { class: 'error-message' }, props.message ?? '')
			},
		},
		FileUploader: {
			name: 'FileUploader',
			setup(_: unknown, { slots }: any) {
				return () => [
					h('input', { type: 'file', class: 'mock-file-input' }),
					h('div', slots.default?.({ openFileSelector: () => {} })),
				]
			},
		},
	}
})

import { mount } from '@vue/test-utils'
import UploadPlugin from '@/components/UploadPlugin.vue'
import translationPlugin from '@/translation'

const mountPlugin = () => {
	;(window as any).translatedMessages = {}
	return mount(UploadPlugin, {
		props: { onFileUploaded: () => {}, uploadContext: { docname: 'l1' } },
		global: { plugins: [translationPlugin] },
	})
}

const setInputFiles = (input: HTMLInputElement, files: File[]) => {
	Object.defineProperty(input, 'files', { value: files, configurable: true })
}

describe('UploadPlugin: cyrillic filename transliteration', () => {
	it('renames a cyrillic file before the uploader reads it', () => {
		const wrapper = mountPlugin()
		const input = wrapper.find('input[type="file"]').element
		setInputFiles(input, [
			new File(['body'], 'Домашка_Глава1.pdf', { type: 'application/pdf' }),
		])
		input.dispatchEvent(new Event('change'))
		expect(input.files?.[0].name).toBe('Domashka_Glava1.pdf')
		expect(input.files?.[0].type).toBe('application/pdf')
	})

	it('renames each cyrillic file in a multi-file selection', () => {
		const wrapper = mountPlugin()
		const input = wrapper.find('input[type="file"]').element
		setInputFiles(input, [
			new File(['a'], 'Фото.jpg', { type: 'image/jpeg' }),
			new File(['b'], 'Видео.mp4', { type: 'video/mp4' }),
		])
		input.dispatchEvent(new Event('change'))
		expect([...(input.files ?? [])].map((f) => f.name)).toEqual([
			'Foto.jpg',
			'Video.mp4',
		])
	})

	it('leaves latin filenames untouched', () => {
		const wrapper = mountPlugin()
		const input = wrapper.find('input[type="file"]').element
		const original = new File(['body'], 'report.pdf', {
			type: 'application/pdf',
		})
		setInputFiles(input, [original])
		input.dispatchEvent(new Event('change'))
		expect(input.files?.[0]).toBe(original)
		expect(input.files?.[0].name).toBe('report.pdf')
	})

	it('ignores change events from non-file inputs', () => {
		const wrapper = mountPlugin()
		const input = wrapper.find('input[type="file"]').element
		input.type = 'text'
		setInputFiles(input, [
			new File(['body'], 'Домашка.pdf', { type: 'application/pdf' }),
		])
		input.dispatchEvent(new Event('change'))
		expect(input.files?.[0].name).toBe('Домашка.pdf')
	})

	it('removes the capture listener on unmount', () => {
		const wrapper = mountPlugin()
		const input = wrapper.find('input[type="file"]').element
		wrapper.unmount()
		setInputFiles(input, [
			new File(['body'], 'Домашка.pdf', { type: 'application/pdf' }),
		])
		input.dispatchEvent(new Event('change'))
		expect(input.files?.[0].name).toBe('Домашка.pdf')
	})
})
