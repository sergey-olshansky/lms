import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import {
	lessonTimecode,
	videoAtTime,
	vkVideoSource,
} from '@/utils/lessonArchive'
import type { VideoArchiveData } from '@/utils/lessonArchive'
const api = vi.hoisted(() => ({ call: vi.fn() }))
vi.mock('frappe-ui', () => ({
	call: api.call,
	Button: defineComponent({
		props: ['label', 'loading'],
		setup:
			(p, { slots }) =>
			() =>
				h('button', {}, slots.default?.() || p.label),
	}),
	Dialog: defineComponent({
		props: ['open'],
		setup:
			(p, { slots }) =>
			() =>
				p.open ? h('div', { role: 'dialog' }, slots.default?.()) : null,
	}),
	ErrorMessage: defineComponent({
		props: ['message'],
		setup: (p) => () => h('div', { role: 'alert' }, p.message),
	}),
	FileUploader: defineComponent({
		emits: ['success'],
		setup:
			(_, { slots, emit }) =>
			() =>
				h(
					'div',
					slots.default?.({
						openFileSelector: () =>
							emit('success', {
								file_url: '/private/files/lesson.zip',
								file_name: 'lesson.zip',
							}),
						uploading: false,
						progress: 0,
						error: null,
					})
				),
	}),
}))
import VideoArchiveBlock from '@/components/VideoArchiveBlock.vue'
import LessonVideoArticle from '@/components/LessonVideoArticle.vue'
const src = 'https://vkvideo.ru/video_ext.php?oid=-1&id=2&hash=abc&hd=4'
const data: VideoArchiveData = {
	video_src: src,
	archive: { file_url: '/private/files/lesson.zip' },
	manifest: {
		schema_version: '1.0',
		lecture_title: 'Хром в ОВР',
		summary: 'Описание',
		top_tags: ['#хром'],
		source: { duration_sec: 3700 },
		sections: [
			{
				id: 1,
				title: 'Окислители',
				start_sec: 0,
				end_sec: 3700,
				tags: [],
				bullets: ['Тезис <img onerror="bad()">'],
				equations: ['Cr³⁺ → Cr⁶⁺'],
				frames: [
					{
						file: 'frames/01.png',
						image_url: '/private/files/01.png',
						caption: 'Доска',
						timestamp_sec: 90,
						board_text: 'Формулы',
					},
				],
			},
		],
	},
}
describe('lesson archive video and article', () => {
	it('accepts only HTTPS VK embed sources and ignores pasted attributes', () => {
		expect(
			vkVideoSource(`<iframe src="${src}" onload="alert(1)"></iframe>`)
		).toBe(src)
		for (const input of [
			'javascript:alert(1)',
			'https://example.com/video_ext.php',
			'http://vkvideo.ru/video_ext.php',
			'https://vkvideo.ru:1234/video_ext.php',
		])
			expect(vkVideoSource(input)).toBe('')
	})
	it('formats hour timestamps and retains embed hash when seeking', () => {
		expect(lessonTimecode(90)).toBe('01:30')
		expect(lessonTimecode(3730)).toBe('1:02:10')
		const url = new URL(videoAtTime(src, 3730))
		expect(url.searchParams.get('hash')).toBe('abc')
		expect(url.searchParams.get('t')).toBe('1h2m10s')
	})
	it('requires both iframe and archive and persists the returned article', async () => {
		const onSave = vi.fn()
		const wrapper = mount(VideoArchiveBlock, {
			props: {
				data: {},
				readOnly: false,
				uploadContext: { course: 'chemistry', docname: 'lesson-1' },
				onSave,
				onCancel: vi.fn(),
			},
		})
		await flushPromises()
		const submit = wrapper.get('button[type="submit"]')
		expect(submit.attributes('disabled')).toBeDefined()
		await wrapper.get('textarea').setValue(`<iframe src="${src}"></iframe>`)
		expect(submit.attributes('disabled')).toBeDefined()
		await wrapper
			.findAll('button')
			.find((b) => b.text() === 'Выбрать ZIP-архив')!
			.trigger('click')
		expect(submit.attributes('disabled')).toBeUndefined()
		api.call.mockResolvedValueOnce(data)
		await wrapper.get('form').trigger('submit')
		await flushPromises()
		expect(api.call).toHaveBeenCalledWith(
			'lms.lms.lesson_archive.import_lesson_archive',
			expect.objectContaining({
				video_src: src,
				archive_url: '/private/files/lesson.zip',
				course: 'chemistry',
				lesson: 'lesson-1',
			})
		)
		expect(onSave).toHaveBeenCalledWith(data)
		expect(wrapper.text()).toContain('Хром в ОВР')
		expect(wrapper.find('textarea').exists()).toBe(false)
		wrapper.unmount()
	})
	it('keeps a rejected archive in the modal without saving', async () => {
		const onSave = vi.fn()
		const wrapper = mount(VideoArchiveBlock, {
			props: {
				data: { video_src: src, archive: data.archive },
				readOnly: false,
				uploadContext: { course: 'chemistry' },
				onSave,
				onCancel: vi.fn(),
			},
		})
		await wrapper
			.findAll('button')
			.find((b) => b.text() === 'Изменить видео и конспект')!
			.trigger('click')
		api.call.mockRejectedValueOnce({ messages: ['Нет manifest.json'] })
		await wrapper.get('form').trigger('submit')
		await flushPromises()
		expect(wrapper.text()).toContain('Нет manifest.json')
		expect(wrapper.get('[role="dialog"]').exists()).toBe(true)
		expect(onSave).not.toHaveBeenCalled()
		wrapper.unmount()
	})
	it('renders private images, formulas and plain text safely after reopening', () => {
		const wrapper = mount(LessonVideoArticle, {
			props: { videoSource: src, manifest: data.manifest },
		})
		expect(wrapper.text()).toContain('Cr³⁺ → Cr⁶⁺')
		expect(wrapper.text()).toContain('Тезис <img onerror="bad()">')
		expect(wrapper.find('[onerror]').exists()).toBe(false)
		expect(wrapper.get('img').attributes('src')).toBe('/private/files/01.png')
		expect(wrapper.get('iframe').attributes('src')).toBe(src)
		wrapper.unmount()
	})
	it('shows saved ASCII arrows and decoded text without creating HTML elements', () => {
		const manifest = structuredClone(data.manifest!)
		manifest.sections[0].equations = ['Cr --OH--&gt; Cr']
		manifest.sections[0].bullets = ['&lt;img onerror="bad()"&gt;']
		const wrapper = mount(LessonVideoArticle, {
			props: { videoSource: src, manifest },
		})
		expect(wrapper.text()).toContain('Cr --OH--> Cr')
		expect(wrapper.text()).toContain('<img onerror="bad()">')
		expect(wrapper.find('[onerror]').exists()).toBe(false)
		wrapper.unmount()
	})
})
