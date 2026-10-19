import { createApp, h } from 'vue'
import type { App } from 'vue'
import type { API, BlockAPI } from '@editorjs/editorjs'
import { Video } from 'lucide-vue-next'
import { registerDirectives } from '@/directives'
import VideoArchiveBlock from '@/components/VideoArchiveBlock.vue'
import type {
	LessonUploadContext,
	VideoArchiveData,
} from '@/utils/lessonArchive'
import { vkVideoSource } from '@/utils/lessonArchive'
import translationPlugin from '../translation'

export class VideoArchive {
	data: VideoArchiveData
	readOnly: boolean
	block?: BlockAPI
	api?: API
	config: LessonUploadContext
	app: App | null = null

	constructor({
		data,
		readOnly,
		block,
		api,
		config,
	}: {
		data: VideoArchiveData
		readOnly: boolean
		block?: BlockAPI
		api?: API
		config?: LessonUploadContext
	}) {
		this.data = data || {}
		this.readOnly = readOnly
		this.block = block
		this.api = api
		this.config = config || {}
	}

	static get toolbox() {
		const app = createApp({
			render: () => h(Video, { size: 18, strokeWidth: 1.5 }),
		})
		registerDirectives(app)
		const icon = document.createElement('div')
		app.mount(icon)
		const html = icon.innerHTML
		app.unmount()
		return { title: 'Загрузить видео', icon: html }
	}

	static get isReadOnlySupported() {
		return true
	}

	render() {
		const wrapper = document.createElement('div')
		this.app = createApp(VideoArchiveBlock, {
			data: this.data,
			readOnly: this.readOnly,
			uploadContext: this.config,
			onSave: (data: VideoArchiveData) => {
				this.data = data
				this.block?.dispatchChange()
			},
			onCancel: () => {
				// Let EditorJS remove its own block and dispatch the normal change.
				if (!this.block || !this.api) return
				const index = this.api.blocks.getBlockIndex(this.block.id)
				if (index >= 0) this.api.blocks.delete(index)
			},
		})
		registerDirectives(this.app)
		this.app.use(translationPlugin)
		this.app.mount(wrapper)
		return wrapper
	}

	validate(data: VideoArchiveData) {
		return Boolean(
			vkVideoSource(data.video_src || data.iframe || '') &&
				data.archive?.file_url
		)
	}
	save(): VideoArchiveData {
		return { ...this.data }
	}
	destroy() {
		this.app?.unmount()
		this.app = null
	}
}
