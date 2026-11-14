<template>
	<!-- Card #47: the solution files of one quiz submission. Draft mode is the
	     learner's staging pane while the attempt is being sat (upload + remove,
	     quota line, one bundle for the WHOLE submission); readonly mode is the
	     finished bundle on the result screen, in the learner's report and on
	     the teacher's grading page. The server re-checks ownership, supported
	     type, privateness and the 100 MiB total on every upload. -->
	<section
		class="rounded-4 border border-outline-gray-2"
		data-testid="quiz-solution-files"
		:aria-label="__('Solution files')"
	>
		<div
			class="flex items-center justify-between gap-2 border-b border-outline-gray-2 px-4 py-2"
		>
			<span class="text-ink-gray-8">{{ __('Solution files') }}</span>
			<span
				v-if="editable && !state.loading"
				class="text-xs text-ink-gray-5"
				data-testid="quiz-files-quota"
			>
				{{ __('{0} of {1} MB used').format(mbUsed, mbQuota) }}
			</span>
		</div>

		<div v-if="state.loading" class="px-4 py-3 text-sm text-ink-gray-5">
			{{ __('Loading…') }}
		</div>
		<template v-else>
			<ul v-if="rows.length" class="divide-y divide-outline-gray-1" aria-live="polite">
				<li
					v-for="row in rows"
					:key="row.name"
					class="flex items-center gap-2 px-4 py-2"
					:data-testid="`quiz-file-${row.name}`"
				>
					<span
						class="lucide-file size-4 shrink-0 text-ink-gray-5"
						aria-hidden="true"
					/>
					<span class="min-w-0 flex-1">
						<span
							class="block truncate text-sm text-ink-gray-8"
							:title="row.file_name"
						>
							{{ row.file_name }}
						</span>
						<span class="block text-xs text-ink-gray-5">
							{{ formatSize(row.file_size) }}
						</span>
					</span>
					<!-- The file's own PRIVATE url: serving re-checks the pair's
					     permission on the attachment row, so the anchor is safe
					     to render for any viewer of this panel (member or
					     reviewer). -->
					<a
						v-if="safeUrl(row.file_url)"
						:href="safeUrl(row.file_url) + '?download=1'"
						:download="row.file_name || undefined"
						class="shrink-0 text-xs text-ink-gray-5 underline"
						:aria-label="__('Download file {0}').format(row.file_name)"
					>
						{{ __('Download') }}
					</a>
					<Button
						v-if="editable"
						variant="ghost"
						size="sm"
						:aria-label="__('Remove file {0}').format(row.file_name)"
						:data-testid="`quiz-file-remove-${row.name}`"
						@click="removeFile(row)"
					>
						<template #icon>
							<span class="lucide-trash-2 size-4" aria-hidden="true" />
						</template>
					</Button>
				</li>
			</ul>
			<p v-else class="px-4 py-3 text-sm text-ink-gray-5">
				{{
					editable
						? __(
								'No files attached yet. You can attach photos or documents with your solutions.'
						  )
						: __('No files were attached to this submission.')
				}}
			</p>

			<p
				v-if="editable"
				class="px-4 pb-2 text-xs text-ink-gray-5"
			>
				{{
					__(
						'One set of files for the whole submission — not per question. Images, documents, PDF and text files, up to {0} MB total.'
					).format(mbQuota)
				}}
			</p>

			<template v-if="editable">
				<div class="border-t border-outline-gray-2 px-4 py-3">
					<!-- Single-request transport (the homework incident
					     2026-10-25): the bytes are posted straight to the quiz
					     endpoint, which stores the file PRIVATE and registers it
					     under the quota verdict in one transaction. -->
					<FileUploader
						upload-endpoint="/api/method/lms.lms.quiz_submission_attachments.upload_quiz_attachment"
						:doctype="'LMS Quiz'"
						:docname="quiz"
						:private="true"
						:validateFile="validateUpload"
						@success="registerFile"
						@failure="onUploadFailure"
					>
						<template #default="{ uploading, progress, openFileSelector }">
							<div class="flex items-center gap-3">
								<Button
									variant="outline"
									size="sm"
									:disabled="uploading || busy"
									data-testid="quiz-files-upload-button"
									@click="openFileSelector"
								>
									<template #prefix>
										<span
											class="lucide-upload size-4"
											aria-hidden="true"
										/>
									</template>
									{{ uploading ? __('Uploading…') : __('Attach files') }}
								</Button>
								<span
									v-if="uploading"
									class="text-xs text-ink-gray-5"
									data-testid="quiz-files-upload-progress"
									role="status"
								>
									{{ `${Math.round(progress)}%` }}
								</span>
							</div>
						</template>
					</FileUploader>
				</div>
				<p
					v-if="uploadMessage"
					class="border-t border-outline-gray-2 px-4 py-2 text-xs text-ink-gray-6"
					role="status"
				>
					{{ uploadMessage }}
				</p>
			</template>

			<div
				v-if="canArchive && rows.length"
				class="border-t border-outline-gray-2 px-4 py-3"
			>
				<Button
					variant="outline"
					size="sm"
					data-testid="quiz-files-zip"
					@click="downloadArchive"
				>
					<template #prefix>
						<span class="lucide-file-archive size-4" aria-hidden="true" />
					</template>
					{{ __('Download all (ZIP)') }}
				</Button>
			</div>
		</template>
	</section>
</template>

<script setup lang="ts">
import { Button, FileUploader, call, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { openExternal } from '@/utils/openExternal'
import { resourceErrorMessage } from '@/utils/resource'
import { safeUrl } from '@/utils/safeUrl'
import type { QuizAttachmentRow } from '@/types'

const props = withDefaults(
	defineProps<{
		/** Draft mode: the quiz being sat; the member stages their bundle. */
		quiz?: string
		/** Readonly mode: the finished submission whose bundle is shown. */
		submission?: string
		/** Draft (upload + remove) vs readonly (the bound bundle). */
		editable?: boolean
		/** The teacher's grading pane adds the one-click ZIP (reviewer-only
		 * endpoint; the member keeps per-file links). */
		canArchive?: boolean
	}>(),
	{
		quiz: '',
		submission: '',
		editable: false,
		canArchive: false,
	}
)

const emit = defineEmits<{ state: [data: { rows?: QuizAttachmentRow[]; count?: number }] }>()

const busy = ref(false)
const uploadMessage = ref('')
const state = ref<{
	loading: boolean
	rows: QuizAttachmentRow[]
	used: number
	quota: number
	remaining?: number
}>({ loading: true, rows: [], used: 0, quota: 0 })

const rows = computed(() => state.value.rows || [])
const mbUsed = computed(() =>
	((state.value.used || 0) / (1024 * 1024)).toFixed(1)
)
const mbQuota = computed(() =>
	String(Math.round((state.value.quota || 0) / (1024 * 1024)))
)

const setBusy = (value: boolean) => {
	busy.value = value
}

// Warn BEFORE the bytes travel: the picked file must fit what the bundle has
// left. The server re-checks the total on every registration anyway.
const validateUpload = (file: File) => {
	uploadMessage.value = ''
	if (file.size > (state.value.remaining ?? 0)) {
		return __('This file does not fit the remaining {0} MB.').format(
			(((state.value.remaining || 0) / (1024 * 1024)) || 0).toFixed(1)
		)
	}
	setBusy(true)
	return null
}

const onUploadFailure = (error: unknown) => {
	setBusy(false)
	toast.error(
		String(
			(error as { message?: string })?.message ||
				error ||
				__('The upload failed. Please retry.')
		)
	)
}

const registerFile = () => {
	uploadMessage.value = __('File attached.')
	reload()
	setBusy(false)
}

const removeFile = (row: QuizAttachmentRow) => {
	call('lms.lms.quiz_submission_attachments.delete_quiz_attachment', {
		attachment: row.name,
	})
		.then(() => {
			toast.success(__('File removed'))
			reload()
		})
		.catch((err: unknown) =>
			toast.error(resourceErrorMessage(err, __('Error')))
		)
}

const downloadArchive = () => {
	if (!props.submission) return
	openExternal(
		`/api/method/lms.lms.quiz_submission_attachments.download_submission_archive?submission=${encodeURIComponent(
			props.submission
		)}`
	)
}

const reload = () => {
	if (props.editable && props.quiz) {
		return call('lms.lms.quiz_submission_attachments.get_draft_attachments', {
			quiz: props.quiz,
		})
			.then((data: { rows?: QuizAttachmentRow[]; used?: number; quota?: number }) => {
				state.value = { loading: false, ...(data as object), rows: data?.rows || [] }
				emit('state', data || {})
			})
			.catch(() => {
				state.value = { loading: false, rows: [], used: 0, quota: 0 }
			})
	}
	if (props.submission) {
		return call(
			'lms.lms.quiz_submission_attachments.get_submission_attachments',
			{ submission: props.submission }
		)
			.then((data: { rows?: QuizAttachmentRow[] }) => {
				state.value = {
					loading: false,
					rows: data?.rows || [],
					used: 0,
					quota: 0,
				}
				emit('state', data || {})
			})
			.catch(() => {
				state.value = { loading: false, rows: [], used: 0, quota: 0 }
			})
	}
	state.value = { loading: false, rows: [], used: 0, quota: 0 }
	return Promise.resolve()
}

watch(
	() => [props.quiz, props.submission, props.editable] as const,
	() => {
		state.value = { loading: true, rows: [], used: 0, quota: 0 }
		reload()
	},
	{ immediate: true }
)

defineExpose({ reload })

const formatSize = (bytes: number) => {
	if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
	if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`
	return `${bytes} B`
}
</script>
