<template>
	<div ref="uploaderRoot">
		<FileUploader
			:fileTypes="['image/*', 'video/*', 'audio/*', '.pdf']"
			:private="true"
			v-bind="attachArgs"
			:validateFile="validateFile"
			@success="(data) => addFile(data)"
			v-slot="{ openFileSelector, uploading, progress, error }"
		>
			<div>
				<AutoOpen :open="openFileSelector" />
				<Button :loading="uploading" @click="openFileSelector">
					{{
						uploading
							? __('Uploading {0}%').format(progress)
							: __('Upload File')
					}}
				</Button>
				<ErrorMessage :message="error ?? undefined" class="mt-1" />
			</div>
		</FileUploader>
	</div>
</template>
<script setup>
import { Button, ErrorMessage, FileUploader } from 'frappe-ui'
import { nextTick, computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { transliterateFileName } from '@/utils/transliterateFileName'

const AutoOpen = {
	props: { open: { type: Function, required: true } },
	async mounted() {
		await nextTick()
		this.open()
	},
	render: () => null,
}

const uploaderRoot = ref(null)

// frappe-ui FileUploader uploads `file.name` as-is (fileUploadHandler.ts) and
// the backend does not transliterate names, so cyrillic attachments land with
// unusable URLs. The hidden <input type="file"> sits next to the slot (not
// inside it), so a capture-phase `change` on the wrapper fires before
// FileUploader's onFileAdd reads event.target.files; swap the files for
// transliterated copies there.
const onCapturedChange = (event) => {
	const input = event.target
	if (!(input instanceof HTMLInputElement) || input.type !== 'file') return
	const files = input.files
	if (!files || !files.length) return
	const renamed = []
	let changed = false
	for (const file of files) {
		if (/[А-яЁёІіЇїЄєҐґ]/.test(file.name)) {
			renamed.push(
				new File([file], transliterateFileName(file.name), {
					type: file.type,
					lastModified: file.lastModified,
				})
			)
			changed = true
		} else {
			renamed.push(file)
		}
	}
	if (!changed) return
	try {
		const dt = new DataTransfer()
		for (const file of renamed) dt.items.add(file)
		input.files = dt.files
	} catch {
		// jsdom has no DataTransfer; replace the getter for tests.
		Object.defineProperty(input, 'files', {
			value: renamed,
			configurable: true,
		})
	}
}

onMounted(() => {
	uploaderRoot.value?.addEventListener('change', onCapturedChange, true)
})

onBeforeUnmount(() => {
	uploaderRoot.value?.removeEventListener('change', onCapturedChange, true)
})

const props = defineProps({
	onFileUploaded: {
		type: Function,
		required: true,
	},
	uploadContext: {
		type: Object,
		default: () => ({}),
	},
})

// Attach to the lesson only once it exists: a null docname with doctype set
// makes the File doctype reject the upload. Uploads are always private
// (course lesson attachments, not public course media).
const attachArgs = computed(() => {
	const docname = props.uploadContext?.docname
	if (!docname) return {}
	return {
		doctype: 'Course Lesson',
		docname,
		fieldname: props.uploadContext?.fieldname || 'content',
	}
})

const addFile = (file) => {
	props.onFileUploaded({
		file_url: file.file_url,
		file_type: file.file_type,
	})
}

const validateFile = (file) => {
	let extension = file.name.split('.').pop().toLowerCase()
	if (!['jpg', 'jpeg', 'png', 'mp4', 'mov', 'mp3', 'pdf'].includes(extension)) {
		return __('Only image and video files are allowed.')
	}
}

const isVideo = (type) => {
	return ['mov', 'mp4', 'avi', 'mkv', 'webm'].includes(type.toLowerCase())
}

const isAudio = (type) => {
	return ['mp3', 'wav', 'ogg'].includes(type.toLowerCase())
}
</script>
