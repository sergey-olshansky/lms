<template>
	<!-- Task #35 (E05): the teacher's own materials of a homework TEMPLATE --
	     images, PDF, DOCX and the other accepted formats, up to 20 MB
	     TOGETHER (embedded description images included). Issuing freezes the
		 current set onto the assignment; editing the template never rewrites
		 an issued snapshot. -->
	<div
		v-if="homework"
		class="rounded-4 border border-outline-gray-2"
		data-testid="homework-teacher-materials"
	>
		<div class="flex items-center justify-between gap-2 border-b border-outline-gray-2 px-4 py-2">
			<span class="text-ink-gray-8">{{ __('Teacher materials') }}</span>
			<span class="text-xs text-ink-gray-5" data-testid="materials-quota">
				{{ __('{0} of {1} MB used').format(mbUsed, mbQuota) }}
			</span>
		</div>
		<div v-if="loading" class="px-4 py-3 text-sm text-ink-gray-5">
			{{ __('Loading…') }}
		</div>
		<template v-else>
			<div v-if="rows.length" class="divide-y divide-outline-gray-1">
				<div
					v-for="row in rows"
					:key="row.name"
					class="flex items-center gap-2 px-4 py-2"
					:data-testid="`teacher-material-${row.name}`"
				>
					<span class="lucide-file size-4 shrink-0 text-ink-gray-5" aria-hidden="true" />
					<span class="min-w-0 flex-1">
						<span class="block truncate text-sm text-ink-gray-8" :title="row.file_name">
							{{ row.file_name }}
						</span>
						<span class="block text-xs text-ink-gray-5">
							{{ formatSize(row.file_size) }}
							<template v-if="row.role === 'Detail Image'">
								· {{ __('embedded in the description') }}
							</template>
						</span>
					</span>
					<a
						v-if="row.file_url"
						:href="safeUrl(row.file_url)"
						:download="row.file_name || undefined"
						class="shrink-0 text-xs text-ink-gray-5 underline"
						:data-testid="`material-download-${row.name}`"
					>
						{{ __('Download') }}
					</a>
					<Button
						v-if="row.role === 'Material'"
						variant="ghost"
						size="sm"
						:aria-label="__('Remove material')"
						:data-testid="`material-remove-${row.name}`"
						@click="removeMaterial(row)"
					>
						<template #icon>
							<span class="lucide-trash-2 size-4" aria-hidden="true" />
						</template>
					</Button>
				</div>
			</div>
			<p v-else class="px-4 py-3 text-sm text-ink-gray-5">
				{{ __('No teacher materials attached yet.') }}
			</p>
			<p class="px-4 pb-2 text-xs text-ink-gray-5">
				{{
					__('Images, PDF, DOCX, ODT, TXT, XLSX, PPTX, ZIP — up to {0} MB total.')
						.format(mbQuota)
				}}
			</p>
			<div class="border-t border-outline-gray-2 px-4 py-3">
				<!-- The hardened uploader chain: private, unbound; the
				     registration call binds it under the template budget. -->
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
								data-testid="material-upload-button"
								@click="openFileSelector"
							>
								<template #prefix>
									<span class="lucide-upload size-4" aria-hidden="true" />
								</template>
								{{ uploading ? __('Uploading…') : __('Attach material') }}
							</Button>
							<span v-if="uploading" class="text-xs text-ink-gray-5">
								{{ `${Math.round(progress)}%` }}
							</span>
						</div>
					</template>
				</FileUploader>
			</div>
		</template>
	</div>
</template>

<script setup>
import { Button, FileUploader, toast, call } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { resourceErrorMessage } from '@/utils/resource'
import { safeUrl } from '@/utils/safeUrl'

const props = defineProps({
	// Saved template name; materials live on the template, not the draft.
	homework: { type: String, default: '' },
})

const state = ref({ loading: true, rows: [], used: 0, quota: 0, remaining: 0 })
const rows = computed(() => state.value.rows || [])
const mbUsed = computed(() => ((state.value.used || 0) / (1024 * 1024)).toFixed(1))
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

const validateUpload = (file) => {
	if (file.size > (state.value.remaining ?? 0)) {
		return __('This file does not fit the remaining {0} MB.').format(
			(((state.value.remaining || 0) / (1024 * 1024)) || 0).toFixed(1)
		)
	}
	return null
}

const onUploadFailure = (error) => {
	toast.error(
		String(error?.message || error || __('The upload failed. Please retry.'))
	)
}

const reload = () => {
	if (!props.homework) {
		state.value = { loading: false, rows: [], used: 0, quota: 0, remaining: 0 }
		return
	}
	state.value.loading = true
	call('lms.lms.homework_api.get_homework', { name: props.homework })
		.then((data) => {
			state.value = {
				loading: false,
				rows: data.materials || [],
				used: data.materials_budget?.used || 0,
				quota: data.materials_budget?.quota || 0,
				remaining: data.materials_budget?.remaining || 0,
			}
		})
		.catch((err) => {
			state.value = { loading: false, rows: [], used: 0, quota: 0, remaining: 0 }
			toast.error(resourceErrorMessage(err, __('Error')))
		})
}

watch(() => props.homework, reload, { immediate: true })

defineExpose({ reload })

const registerFile = (file) => {
	const fileName = file.name || file.file_name
	call('lms.lms.homework_materials.add_material', {
		homework: props.homework,
		file_name: fileName,
	})
		.then((data) => {
			toast.success(__('Material attached'))
			if (data) {
				state.value = {
					...state.value,
					used: data.used,
					quota: data.quota,
					remaining: data.remaining,
				}
			}
			reload()
		})
		.catch((err) => {
			toast.error(resourceErrorMessage(err, __('Error')))
			reload()
		})
}

const removeMaterial = (row) => {
	call('lms.lms.homework_materials.remove_material', { material: row.name })
		.then((data) => {
			toast.success(__('Material removed'))
			if (data) {
				state.value = {
					...state.value,
					used: data.used,
					quota: data.quota,
					remaining: data.remaining,
				}
			}
			reload()
		})
		.catch((err) => toast.error(resourceErrorMessage(err, __('Error'))))
}

const formatSize = (bytes) => {
	if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
	if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`
	return `${bytes} B`
}
</script>
