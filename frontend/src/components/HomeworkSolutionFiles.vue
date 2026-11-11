<template>
	<!-- Task #35 (E03): the student's image/document solution files for THIS
	     assignment, up to 100 MB TOGETHER (card #45). The server re-checks ownership,
	     privateness, supported type and quota on every registration. Card #45
	     adds the batch upload (multi-photo, one request per file), the
	     teacher/staff photo gallery and the one-zip archive download. -->
	<section
		v-if="detail.data?.name"
		class="rounded-4 border border-outline-gray-2"
		data-testid="homework-solution-files"
	>
		<div class="flex items-center justify-between gap-2 border-b border-outline-gray-2 px-4 py-2">
			<span class="text-ink-gray-8">{{ __('Solution files') }}</span>
			<span class="flex items-center gap-3">
				<span v-if="!state.loading" class="text-xs text-ink-gray-5" data-testid="solution-quota">
					{{ __('{0} of {1} MB used').format(mbUsed, mbQuota) }}
				</span>
				<!-- Card #45: the whole solution as ONE streamed zip, for the same
				     readers the panel serves (assignment student + teacher +
				     privileged staff -- re-gated server-side on every download). -->
				<a
					v-if="detail.data?.viewer_can_teach && rows.length"
					:href="safeUrl(archiveUrl)"
					class="inline-flex items-center gap-1 text-xs text-ink-gray-6 underline"
					data-testid="solution-archive-download"
					:download="archiveName"
				>
					<span class="lucide-file-archive size-3.5" aria-hidden="true" />
					{{ __('Download all (ZIP)') }}
				</a>
			</span>
		</div>

		<div v-if="state.loading" class="px-4 py-3 text-sm text-ink-gray-5">
			{{ __('Loading…') }}
		</div>
		<template v-else>
			<!-- Card #45: the solution photos as an inline gallery for the
			     teacher/admin scope. Thumbnails ride the file's own PRIVATE
			     url, so serving re-checks the permission pair per photo; each
			     opens full-size in the lightbox below. -->
			<div
				v-if="detail.data?.viewer_can_teach && galleryRows.length"
				class="flex flex-wrap gap-2 px-4 pt-3"
				data-testid="solution-gallery"
			>
				<button
					v-for="row in galleryRows"
					:key="`gallery-${row.name}`"
					type="button"
					class="overflow-hidden rounded-4 border border-outline-gray-2 transition hover:border-outline-gray-4"
					:aria-label="__('Open photo {0}').format(row.file_name || '')"
					:data-testid="`solution-photo-${row.name}`"
					@click="openPhoto(row)"
				>
					<img
						:src="safeUrl(row.file_url)"
						:alt="row.file_name || __('Solution photo')"
						class="size-20 object-cover"
						loading="lazy"
					/>
				</button>
			</div>

			<div v-if="rows.length" class="divide-y divide-outline-gray-1" :class="galleryRows.length ? 'mt-3' : ''">
				<div
					v-for="row in rows"
					:key="row.name"
					class="flex items-center gap-2 px-4 py-2"
					:data-testid="`solution-file-${row.name}`"
				>
					<span class="lucide-file size-4 shrink-0 text-ink-gray-5" aria-hidden="true" />
					<span class="min-w-0 flex-1">
						<span class="block truncate text-sm text-ink-gray-8" :title="row.file_name">
							{{ row.file_name }}
						</span>
						<span class="block text-xs text-ink-gray-5">
							{{ formatSize(row.file_size) }} · {{ row.uploaded_by_name }} ·
							{{ formatDate(row.uploaded_at) }}
						</span>
					</span>
					<!-- R05: the download action both readers get -- the student and
					     the assignment's teacher. The URL is the file's own PRIVATE
					     path; serving re-checks the pair's permission on the row, so
					     the anchor is safe to render for any viewer of this panel. -->
					<a
						v-if="row.download_url || row.file_url"
						:href="safeUrl(row.download_url || row.file_url)"
						:download="row.file_name || undefined"
						class="shrink-0 text-xs text-ink-gray-5 underline"
						:data-testid="`solution-download-${row.name}`"
					>
						{{ __('Download') }}
					</a>
					<Button
						v-if="row.can_delete"
						variant="ghost"
						size="sm"
						:aria-label="__('Remove file')"
						:data-testid="`solution-remove-${row.name}`"
						@click="removeFile(row)"
					>
						<template #icon>
							<span class="lucide-trash-2 size-4" aria-hidden="true" />
						</template>
					</Button>
				</div>
			</div>
			<p v-else class="px-4 py-3 text-sm text-ink-gray-5">
				{{ __('No files attached yet.') }}
			</p>
			<p
				v-if="rows.length && !state.can_upload"
				class="border-t border-outline-gray-2 px-4 py-2 text-xs text-ink-gray-5"
			>
				{{
					detail.data?.viewer_can_teach
						? __('Download the student solution files to review their work.')
						: __('These files are read-only while the homework is on review or accepted.')
				}}
			</p>

			<p class="px-4 pb-2 text-xs text-ink-gray-5" v-if="state.can_upload">
				{{ __('Images, documents, PDF and text files — up to {0} MB total.').format(mbQuota) }}
			</p>

			<div v-if="state.can_upload" class="border-t border-outline-gray-2 px-4 py-3">
				<!-- Single-request transport (prod incident 2026-10-25), batched for
				     card #45: the picked photos post SEQUENTIALLY, one request per
				     file, straight to the homework endpoint, which stores each file
				     PRIVATE and registers it under the quota verdict in one
				     transaction -- per-file atomicity is preserved, and a mid-batch
				     quota overflow leaves the files that already fit attached. -->
				<SolutionBatchUploader
					upload-endpoint="/api/method/lms.lms.homework_attachments.upload_solution_file"
					:doctype="'LMS Homework Assignment'"
					:docname="detail.data?.name"
					:is-private="true"
					:validateFile="validateUpload"
					@uploading="setBusy"
					@file-success="registerFile"
					@file-failure="onUploadFailure"
					@batch-done="onBatchDone"
				>
					<template #default="{ uploading, progress, openFileSelector }">
						<div class="flex items-center gap-3">
							<Button
								variant="outline"
								size="sm"
								:disabled="uploading || busy"
								data-testid="solution-upload-button"
								@click="openFileSelector"
							>
								<template #prefix>
									<span class="lucide-upload size-4" aria-hidden="true" />
								</template>
								{{ uploading ? __('Uploading…') : __('Attach files') }}
							</Button>
							<span
								v-if="uploading"
								class="text-xs text-ink-gray-5"
								data-testid="solution-upload-progress"
							>
								{{ `${Math.round(progress)}%` }}
							</span>
						</div>
					</template>
				</SolutionBatchUploader>
			</div>
		</template>

		<!-- Card #45: the full-size photo lightbox. The image still rides the
		     file's own private url, so the browser session's permission pair
		     is re-checked by the serving path, never by this markup. -->
		<div
			v-if="lightbox"
			class="fixed inset-0 z-50 flex flex-col items-center justify-center gap-3 bg-black-overlay-200 p-4 dark:bg-black-overlay-700"
			role="dialog"
			aria-modal="true"
			data-testid="solution-photo-lightbox"
			tabindex="-1"
			@keydown.escape="closePhoto"
		>
			<img
				:src="safeUrl(lightbox.file_url)"
				:alt="lightbox.file_name || __('Solution photo')"
				class="max-h-[75vh] max-w-full rounded-4 object-contain"
				data-testid="solution-photo-full"
			/>
			<div class="flex items-center gap-4 text-sm text-ink-gray-2">
				<a
					v-external
					:href="safeUrl(lightbox.file_url)"
					class="underline"
					data-testid="solution-photo-open"
				>
					{{ __('Open in new tab') }}
				</a>
				<button
					type="button"
					class="rounded-4 bg-surface-gray-2 px-3 py-1 text-ink-gray-8"
					:aria-label="__('Close photo')"
					data-testid="solution-photo-close"
					@click="closePhoto"
				>
					{{ __('Close') }}
				</button>
			</div>
		</div>
	</section>
</template>

<script setup>
import { Button, toast, call } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { resourceErrorMessage } from '@/utils/resource'
import { safeUrl } from '@/utils/safeUrl'
import SolutionBatchUploader from '@/components/SolutionBatchUploader.vue'

const props = defineProps({
	// The loaded detail DTO: the server's own viewer flags decide what the
	// student may do here, never the client.
	detail: { type: Object, required: true },
})
const emit = defineEmits(['state', 'uploading'])
const busy = ref(false)
const setBusy = (value) => {
	busy.value = value
	emit('uploading', value)
}

const state = ref({ loading: true, rows: [], can_upload: false, used: 0, quota: 0, remaining: 0 })
const rows = computed(() => state.value.rows || [])
const mbUsed = computed(() =>
	((state.value.used || 0) / (1024 * 1024)).toFixed(1)
)
const mbQuota = computed(() =>
	String(Math.round((state.value.quota || 0) / (1024 * 1024)))
)

// The photo gallery the teacher/admin scope renders: exactly the attached
// rows whose names declare an image format (the supported list the server
// already verifies byte-by-byte).
const IMAGE_EXTENSIONS = ['.bmp', '.gif', '.heic', '.heif', '.jpeg', '.jpg', '.png', '.tif', '.tiff', '.webp']
const isImage = (row) => {
	const name = String(row.file_name || '')
	const dot = name.lastIndexOf('.')
	return dot >= 0 && IMAGE_EXTENSIONS.includes(name.slice(dot).toLowerCase())
}
const galleryRows = computed(() => rows.value.filter((row) => isImage(row) && row.file_url))

// Card #45: one streamed zip of every solution attachment. The endpoint
// re-checks the permission pair (assignment student + teacher + privileged
// staff) and re-reads the rows on every download.
const archiveUrl = computed(() =>
	`/api/method/lms.lms.homework_attachments.download_solution_archive?assignment=${encodeURIComponent(
		props.detail.data?.name || ''
	)}`
)
const archiveName = computed(() =>
	`solution-${props.detail.data?.name || ''}.zip`
)

const lightbox = ref(null)
const openPhoto = (row) => {
	lightbox.value = row
}
const closePhoto = () => {
	lightbox.value = null
}

// E03.3 / R04: warn BEFORE the bytes travel -- the sum of what is stored
// plus the picked file must fit the remaining quota. Called per file in
// pick order, against the cumulative remaining that every successful
// upload refreshes; falsy = allowed, truthy message/Error = blocked before
// the network. The server still re-checks the total on registration.
const validateUpload = (file) => {
	if (file.size > (state.value.remaining ?? 0)) {
		return __('This file does not fit the remaining {0} MB.').format(
			(((state.value.remaining || 0) / (1024 * 1024)) || 0).toFixed(1)
		)
	}
	return null
}

// R04: a transport failure (network, refused upload) is surfaced per file,
// not swallowed -- the failed file is NOT registered, the ones before it
// stay, and the queue stops (SolutionBatchUploader).
const onUploadFailure = (error) => {
	toast.error(
		String(error?.message || error || __('The upload failed. Please retry.'))
	)
}

const reload = () =>
	call('lms.lms.homework_attachments.list_attachments', {
		assignment: props.detail.data?.name,
	})
		.then((data) => {
			state.value = { loading: false, remaining: 0, ...data }
			emit('state', data)
		})
		.catch((err) => {
			state.value = { loading: false, rows: [], can_upload: false, used: 0, quota: 0, remaining: 0 }
			toast.error(resourceErrorMessage(err, __('Error')))
		})

watch(
	() => props.detail.data?.name,
	(name) => {
		if (name) reload()
	},
	{ immediate: true }
)

defineExpose({ reload })

// The upload endpoint did the registering in the same request: its payload
// carries the fresh quota state, which the NEXT queued file's client gate
// (and the server, always) re-checks cumulatively. Whatever shape comes
// back, the panel never depends on parsing it -- the server stays the
// single source of truth, and the batch's end-of-run reload reconciles the
// rows (prod incident 2026-10-25: the old two-step hand-off broke exactly
// there).
const registerFile = (file) => {
	toast.success(__('Attached {0}').format(file?.file_name || __('File')))
	if (file && file.state) {
		state.value = { ...state.value, ...file.state }
	}
}

// End of a batch (finished or stopped): reconcile the rows from the server
// so the panel shows every file that stayed registered -- including after a
// mid-batch quota overflow, where the files that fit must visibly remain.
// (The batch's own uploading=false event has already released the busy
// state; this handler only reconciles.)
const onBatchDone = () => {
	reload()
}

const removeFile = (row) => {
	call('lms.lms.homework_attachments.delete_attachment', {
		attachment: row.name,
	})
		.then(() => {
			toast.success(__('File removed'))
			reload()
		})
		.catch((err) => toast.error(resourceErrorMessage(err, __('Error'))))
}

const formatSize = (bytes) => {
	if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
	if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`
	return `${bytes} B`
}

const formatDate = (value) => {
	if (!value) return ''
	const match = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(String(value))
	return match ? `${match[3]}.${match[2]}.${match[1]} ${match[4]}:${match[5]}` : ''
}
</script>
