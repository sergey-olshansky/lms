<template>
	<div class="not-prose my-5" contenteditable="false">
		<LessonVideoArticle
			v-if="source"
			:video-source="source"
			:manifest="current.manifest"
		/>
		<div v-if="!readOnly" class="mt-3">
			<Button
				:label="source ? 'Изменить видео и конспект' : 'Загрузить видео'"
				@click="openDialog"
			/>
		</div>
		<Dialog
			v-model:open="showDialog"
			title="Загрузить видео"
			size="xl"
			:dismissible="!importing"
			:show-close-button="!importing"
			@update:open="onDialogChange"
		>
			<template #default>
				<form class="space-y-4" @submit.prevent="submit">
					<div>
						<label :for="`${id}-iframe`" class="mb-2 block text-sm font-medium"
							>Фрейм вставки видео *</label
						>
						<textarea
							:id="`${id}-iframe`"
							ref="iframeInput"
							v-model="iframe"
							rows="5"
							required
							:disabled="importing"
							class="w-full rounded-6 border border-outline-gray-2 bg-surface-gray-1 p-3 font-mono text-sm text-ink-gray-9"
							:placeholder="iframePlaceholder"
						/>
						<p class="mt-1 text-xs text-ink-gray-5">
							Вставьте iframe из VK Видео.
						</p>
					</div>
					<div>
						<div class="mb-2 text-sm font-medium">Архив с метаданными *</div>
						<FileUploader
							:fileTypes="['.zip']"
							:private="true"
							:validateFile="validateArchive"
							v-bind="attachArgs"
							@change.capture="onArchiveSelection"
							@success="onArchiveUploaded"
							v-slot="{ openFileSelector, uploading, progress, error }"
						>
							<Button
								type="button"
								:disabled="importing"
								:loading="uploading"
								@click="openFileSelector"
							>
								{{
									uploading
										? `Загрузка ${Math.round(progress || 0)}%`
										: archive?.file_name || 'Выбрать ZIP-архив'
								}}
							</Button>
							<ErrorMessage :message="error ?? undefined" class="mt-2" />
						</FileUploader>
						<p class="mt-2 text-xs text-ink-gray-5">
							lesson.zip с manifest.json и кадрами. Для добавления нужны и
							видео, и архив.
						</p>
					</div>
					<ErrorMessage :message="errorMessage || undefined" />
					<div class="flex justify-end gap-2 pt-2">
						<Button
							type="button"
							label="Отмена"
							:disabled="importing"
							@click="cancel"
						/>
						<Button
							type="submit"
							variant="solid"
							label="Добавить видео и конспект"
							:loading="importing"
							:disabled="
								!vkVideoSource(iframe) || !archive?.file_url || importing
							"
						/>
					</div>
				</form>
			</template>
		</Dialog>
	</div>
</template>
<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useId } from 'vue'
import { Button, Dialog, ErrorMessage, FileUploader, call } from 'frappe-ui'
import LessonVideoArticle from '@/components/LessonVideoArticle.vue'
import { vkVideoSource } from '@/utils/lessonArchive'
import type {
	LessonUploadContext,
	VideoArchiveData,
} from '@/utils/lessonArchive'

const props = defineProps<{
	data: VideoArchiveData
	readOnly: boolean
	uploadContext: LessonUploadContext
	onSave: (data: VideoArchiveData) => void
	onCancel: () => void
}>()
const id = useId()
const current = ref(props.data)
const showDialog = ref(false)
const iframe = ref(
	props.data.iframe ||
		(props.data.video_src
			? `<iframe src="${props.data.video_src}"></iframe>`
			: '')
)
const archive = ref(props.data.archive || null)
const errorMessage = ref('')
const importing = ref(false)
const iframeInput = ref<HTMLTextAreaElement | null>(null)
const iframePlaceholder =
	'<iframe src="https://vkvideo.ru/video_ext.php?..."></iframe>'
const source = computed(() =>
	vkVideoSource(current.value.video_src || current.value.iframe || '')
)
const attachArgs = computed(() =>
	props.uploadContext.docname
		? {
				doctype: 'Course Lesson',
				docname: props.uploadContext.docname,
				fieldname: props.uploadContext.fieldname || 'content',
		  }
		: {}
)
onMounted(() => {
	if (!props.readOnly && !source.value) openDialog()
})
async function openDialog() {
	showDialog.value = true
	errorMessage.value = ''
	await nextTick()
	iframeInput.value?.focus()
}
function onArchiveSelection(event: Event) {
	const input = event.target
	if (
		input instanceof HTMLInputElement &&
		input.type === 'file' &&
		input.files?.length
	)
		archive.value = null
}
function onArchiveUploaded(file: {
	file_url: string
	file_name?: string
	name?: string
}) {
	archive.value = {
		file_url: file.file_url,
		file_name: file.file_name || 'lesson.zip',
	}
	errorMessage.value = ''
}
function validateArchive(file: File) {
	if (!/\.zip$/i.test(file.name)) return 'Выберите ZIP-архив.'
	if (file.size > 100 * 1024 * 1024)
		return 'Размер ZIP не должен превышать 100 МБ.'
}
async function submit() {
	if (importing.value) return
	const video_src = vkVideoSource(iframe.value)
	if (!video_src || !archive.value?.file_url) {
		errorMessage.value = 'Укажите iframe и ZIP-архив.'
		return
	}
	if (!props.uploadContext.course) {
		errorMessage.value = 'Откройте редактор урока курса.'
		return
	}
	importing.value = true
	errorMessage.value = ''
	try {
		const data = await call<VideoArchiveData>(
			'lms.lms.lesson_archive.import_lesson_archive',
			{
				video_src,
				archive_url: archive.value.file_url,
				course: props.uploadContext.course,
				lesson: props.uploadContext.docname || undefined,
				fieldname: props.uploadContext.fieldname || 'content',
			}
		)
		current.value = data
		props.onSave(data)
		showDialog.value = false
	} catch (error) {
		const e = error as { messages?: string[]; message?: string }
		errorMessage.value =
			e.messages?.join('\n') ||
			e.message ||
			'Не удалось прочитать архив. Проверьте manifest.json и кадры.'
	} finally {
		importing.value = false
	}
}
function cancel() {
	if (importing.value) return
	showDialog.value = false
	if (!source.value) props.onCancel()
}
function onDialogChange(open: boolean) {
	if (importing.value) {
		showDialog.value = true
		return
	}
	if (!open && !source.value) props.onCancel()
}
</script>
