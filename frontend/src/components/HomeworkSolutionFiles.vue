<template>
	<!-- Task #35 (E03): the student's solution files for THIS assignment --
	     images, PDFs, DOCX and the project's other accepted formats, up to
	     20 MB TOGETHER. The quota line shows used/remaining; the server
	     re-checks ownership, privateness, real content type and the sum on
	     every registration, so the numbers here are a convenience, never
	     the gate. -->
	<section
		v-if="detail.data?.name"
		class="rounded-4 border border-outline-gray-2"
		data-testid="homework-solution-files"
	>
		<div class="flex items-center justify-between gap-2 border-b border-outline-gray-2 px-4 py-2">
			<span class="text-ink-gray-8">{{ __('Solution files') }}</span>
			<span class="text-xs text-ink-gray-5" data-testid="solution-quota">
				{{ __('{0} of {1} MB used').format(mbUsed, mbQuota) }}
			</span>
		</div>

		<div v-if="state.loading" class="px-4 py-3 text-sm text-ink-gray-5">
			{{ __('Loading…') }}
		</div>
		<template v-else>
			<div v-if="rows.length" class="divide-y divide-outline-gray-1">
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
						v-if="row.file_url"
						:href="safeUrl(row.file_url)"
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
					__(
						'These files are read-only while the homework is on review or accepted.'
					)
				}}
			</p>

			<p class="px-4 pb-2 text-xs text-ink-gray-5" v-if="state.can_upload">
				{{
					__('Allowed: images, PDF, DOCX, ODT, TXT, XLSX, PPTX, ZIP — up to {0} MB total.')
						.format(mbQuota)
				}}
			</p>

			<div v-if="state.can_upload" class="border-t border-outline-gray-2 px-4 py-3">
				<!-- No doctype wiring on the uploader itself: the generic
				     upload_file requires doctype write a student does not
				     hold. The file lands unattached and PRIVATE; the
				     registration call below binds it under the quota
				     verdict. -->
				<FileUploader
					:fileTypes="acceptedTypes"
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
								:disabled="uploading"
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
				</FileUploader>
			</div>
		</template>
	</section>
</template>

<script setup>
import { Button, FileUploader, toast, call } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { resourceErrorMessage } from '@/utils/resource'
import { safeUrl } from '@/utils/safeUrl'

const props = defineProps({
	// The loaded detail DTO: the server's own viewer flags decide what the
	// student may do here, never the client.
	detail: { type: Object, required: true },
})
const emit = defineEmits(['state'])

const state = ref({ loading: true, rows: [], can_upload: false, used: 0, quota: 0 })
const rows = computed(() => state.value.rows || [])
const mbUsed = computed(() =>
	((state.value.used || 0) / (1024 * 1024)).toFixed(1)
)
const mbQuota = computed(() =>
	String(Math.round((state.value.quota || 0) / (1024 * 1024)))
)

const acceptedTypes = [
	'image/*',
	'.pdf',
	'.doc',
	'.docx',
	'.odt',
	'.rtf',
	'.txt',
	'.csv',
	'.xls',
	'.xlsx',
	'.ods',
	'.ppt',
	'.pptx',
	'.zip',
]

// E03.3 / R04: warn BEFORE the bytes travel -- the sum of what is stored
// plus the picked file must fit the remaining quota. The FileUploader
// contract is falsy = allowed, truthy message/Error = blocked before the
// network; the server still re-checks the total on registration.
const validateUpload = (file) => {
	if (file.size > (state.value.remaining ?? 0)) {
		return __('This file does not fit the remaining {0} MB.').format(
			(((state.value.remaining || 0) / (1024 * 1024)) || 0).toFixed(1)
		)
	}
	return null
}

// R04: a transport failure (network, refused upload) is surfaced, not
// swallowed -- the file is NOT registered, so the panel stays truthful.
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
			state.value = { loading: false, ...data }
			emit('state', data)
		})
		.catch((err) => {
			state.value = { loading: false, rows: [], can_upload: false, used: 0, quota: 0 }
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

// The uploader hands the stored File document; the quota verdict and the
// private binding live on the server side of register. A refused
// registration (foreign file, public file, wrong content, frozen state,
// over-quota) is cleaned server-side and reported here.
const registerFile = (file) => {
	const fileName = file.name || file.file_name
	call('lms.lms.homework_attachments.attach_file', {
		assignment: props.detail.data?.name,
		file_name: fileName,
	})
		.then((data) => {
			toast.success(__('File attached'))
			if (data?.state) {
				state.value = { ...state.value, ...data.state }
			}
			reload()
		})
		.catch((err) => {
			toast.error(resourceErrorMessage(err, __('Error')))
			reload()
		})
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
