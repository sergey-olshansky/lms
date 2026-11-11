<template>
	<!-- Card #45: the batch solution uploader. The vendored frappe-ui
	     FileUploader posts only files[0]; this local wrap keeps its exact
	     transport (FileUploadHandler XHR to upload_solution_file, private
	     storage, CSRF header) and adds the multi-photo queue: the picked
	     files upload SEQUENTIALLY -- one request per file -- so every
	     per-file verdict (ownership, container, cumulative quota) stays
	     atomic on the server. A failed file reports its cause and stops the
	     queue; the files already uploaded stay. -->
	<div data-testid="solution-batch-uploader">
		<input ref="input" type="file" multiple class="hidden" @change="onFilesPicked" />
		<slot
			v-bind="{
				uploading: busy,
				progress: overallProgress,
				openFileSelector,
				queue,
			}"
		>
			<button type="button" :disabled="busy" @click="openFileSelector">
				{{ busy ? __('Uploading…') : __('Attach files') }}
			</button>
		</slot>

		<!-- Per-photo feedback: name, size, live progress and the failed
		     file's cause-named verdict, in pick order. -->
		<ul v-if="queue.length" class="mt-3 space-y-1" data-testid="solution-batch-queue">
			<li
				v-for="item in queue"
				:key="item.id"
				class="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs"
				:data-testid="`batch-item-${item.id}`"
			>
				<span
					:class="{
						'lucide-check size-4 shrink-0 text-ink-green-3': item.status === 'success',
						'lucide-alert-circle size-4 shrink-0 text-ink-red-4':
							item.status === 'failed' || item.status === 'blocked',
						'lucide-loader-circle size-4 shrink-0 animate-spin text-ink-gray-5':
							item.status === 'uploading',
						'lucide-circle-dot size-4 shrink-0 text-ink-gray-4': item.status === 'pending',
					}"
					aria-hidden="true"
				/>
				<span class="min-w-0 flex-1 truncate text-ink-gray-7" :title="item.file.name">
					{{ item.file.name }}
					<span class="text-ink-gray-5">· {{ formatSize(item.file.size) }}</span>
				</span>
				<span
					v-if="item.status === 'uploading'"
					class="shrink-0 text-ink-gray-5"
					:data-testid="`batch-progress-${item.id}`"
				>
					{{ `${Math.round(item.progress)}%` }}
				</span>
				<span class="shrink-0 text-ink-gray-6" :data-testid="`batch-status-${item.id}`">
					{{ statusLabel(item.status) }}
				</span>
				<span
					v-if="item.error"
					class="w-full text-ink-red-4"
					:data-testid="`batch-error-${item.id}`"
				>
					{{ item.error }}
				</span>
			</li>
		</ul>
	</div>
</template>

<script setup>
import { FileUploadHandler } from 'frappe-ui'
import { computed, ref } from 'vue'

const props = defineProps({
	// The homework single-request endpoint: bytes, private storage and the
	// quota registration commit together per file.
	uploadEndpoint: { type: String, required: true },
	doctype: { type: String, default: '' },
	docname: { type: String, default: '' },
	isPrivate: { type: Boolean, default: true },
	// Per-file gate called BEFORE each POST (falsy = allowed, truthy
	// message/Error = blocked). The parent feeds it the CURRENT cumulative
	// remaining bytes, so a batch cannot outsmart the quota client-side --
	// and the server still re-checks under its advisory lock.
	validateFile: { type: Function, default: null },
})
const emit = defineEmits(['uploading', 'file-success', 'file-failure', 'batch-done'])

const input = ref(null)
const queue = ref([])
const busy = ref(false)

const overallProgress = computed(() => {
	const items = queue.value
	if (!items.length) return 0
	const total = items.reduce((sum, item) => sum + (item.file.size || 1), 0)
	const done = items.reduce(
		(sum, item) =>
			sum +
			(item.status === 'success'
				? item.file.size || 1
				: ((item.file.size || 1) * (item.progress || 0)) / 100),
		0
	)
	return Math.round((done / total) * 100)
})

const uploadOptions = computed(() => ({
	private: props.isPrivate,
	folder: 'Home',
	doctype: props.doctype,
	docname: props.docname,
	upload_endpoint: props.uploadEndpoint,
}))

const openFileSelector = () => input.value?.click()

const messageOf = (error) => {
	if (!error) return ''
	if (error instanceof Error) return error.message
	if (typeof error === 'string') return error
	return error.message || ''
}

// The pick loop: strictly sequential, one POST per file. A refusal (blocked
// by the client gate or rejected by the server) marks the file with its
// cause and STOPS the queue -- anything not yet uploaded stays visibly
// unuploaded instead of failing silently.
const onFilesPicked = async (event) => {
	const target = event.target
	const files = Array.from(target.files || [])
	target.value = ''
	if (!files.length) return

	queue.value = files.map((file, index) => ({
		id: String(index),
		file,
		status: 'pending',
		progress: 0,
		error: '',
	}))

	let stopped = false
	let uploaded = 0
	let failed = 0
	let blocked = 0
	emit('uploading', true)
	for (const item of queue.value) {
		if (stopped) {
			item.status = 'blocked'
			blocked += 1
			continue
		}
		const verdict = await runValidate(item.file)
		if (verdict) {
			item.status = 'failed'
			item.error = messageOf(verdict) || __('The file was not uploaded.')
			failed += 1
			stopped = true
			emit('file-failure', verdict)
			continue
		}
		try {
			const response = await uploadOne(item)
			item.status = 'success'
			uploaded += 1
			emit('file-success', response ?? {})
		} catch (error) {
			item.status = 'failed'
			item.error = messageOf(error) || __('The upload failed. Please retry.')
			failed += 1
			stopped = true
			emit('file-failure', error)
		}
	}
	emit('uploading', false)
	emit('batch-done', { uploaded, failed, blocked, total: queue.value.length })
}

const runValidate = async (file) => {
	if (typeof props.validateFile !== 'function') return null
	try {
		return await props.validateFile(file)
	} catch (error) {
		return error
	}
}

const uploadOne = (item) =>
	new Promise((resolve, reject) => {
		const uploader = new FileUploadHandler()
		uploader.on('start', () => {
			item.status = 'uploading'
			item.progress = 0
		})
		uploader.on('progress', (data) => {
			item.progress = data && data.total ? (data.uploaded / data.total) * 100 : 0
		})
		uploader.on('finish', () => {
			item.progress = 100
		})
		uploader.upload(item.file, uploadOptions.value).then(resolve, reject)
	})

const statusLabel = (status) =>
	({
		pending: __('Waiting'),
		uploading: __('Uploading'),
		success: __('Attached'),
		failed: __('Failed'),
		blocked: __('Not uploaded'),
	}[status] || status)

const formatSize = (bytes) => {
	if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
	if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`
	return `${bytes} B`
}

defineExpose({ openFileSelector, queue })
</script>
