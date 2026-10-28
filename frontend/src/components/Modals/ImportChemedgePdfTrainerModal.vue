<template>
	<Dialog
		v-model:open="show"
		title="Import PDF Trainer"
		size="lg"
		:actions="dialogActions"
	>
		<div v-if="showSummary" class="space-y-4 text-base">
			<div class="space-y-1">
				<p>PDF processing complete.</p>
				<p class="text-ink-gray-6">{{ completedCount }} imported.</p>
			</div>
			<div class="max-h-64 space-y-2 overflow-y-auto">
				<div
					v-for="file in files"
					:key="file.id"
					class="flex flex-wrap items-center gap-2 rounded border p-2 text-sm"
				>
					<span class="size-4" :class="statusIconClass(file.status)" />
					<span class="min-w-0 flex-1 truncate">{{ file.file_name }}</span>
					<span class="text-ink-gray-6">{{ statusLabel(file.status) }}</span>
					<Button
						v-if="file.result"
						variant="ghost"
						size="sm"
						@click="openQuiz(file.result)"
					>
						Open
					</Button>
					<p v-if="file.result?.warning" role="alert" class="w-full rounded bg-surface-amber-1 p-2 text-sm text-ink-amber-7">
						{{ file.result.warning }}
					</p>
					<p v-if="file.error" class="w-full text-xs text-ink-red-5">
						{{ file.error }}
					</p>
					<Button v-if="file.status === 'error'" variant="outline" :disabled="isProcessing" @click="retryImport(file)">
						{{ __('Retry import') }}
					</Button>
				</div>
			</div>
		</div>
		<div v-else class="space-y-4 text-base">
			<p class="text-ink-gray-6">
				Upload Chemedge PDFs or trainers with bracketed task numbers and an answer
				section at the end, including Stepenin OGE/EGE PDFs. The imported quizzes
				will have two attempts, an 85% passing score, and one mark per question.
			</p>
			<Checkbox
				label="Show correct answers"
				:model-value="showAnswers"
				:disabled="isProcessing"
				@update:model-value="(checked) => (showAnswers = !!checked)"
			/>
			<div class="rounded bg-surface-blue-1 p-3 text-sm text-ink-gray-7">
				{{ __('Every PDF is reviewed by AI for complete questions and the presence of answers. If needed, Z.AI plans the required pages and extracts each task separately. Answer correctness is not checked. If AI is unavailable, recognised PDFs are imported by the standard parser with a warning.') }}
			</div>
			<div class="space-y-1">
				<label class="text-xs text-ink-gray-6" for="ai-instruction">
					{{ __('Extra instruction for AI (optional)') }}
				</label>
				<textarea
					id="ai-instruction"
					v-model="aiInstruction"
					maxlength="1000"
					rows="3"
					:disabled="isProcessing"
					class="w-full rounded border border-outline-gray-2 px-3 py-2 text-sm"
					:placeholder="__('For example: preserve answer choices and chemical notation')"
				/>
				<p class="text-end text-xs text-ink-gray-5">{{ aiInstruction.length }}/1000</p>
			</div>
			<div
				class="rounded border border-dashed border-outline-gray-3 p-4 text-center"
				@dragover.prevent
				@drop.prevent="onDrop"
			>
				<input
					ref="fileInput"
					type="file"
					class="hidden"
					accept=".pdf,application/pdf"
					multiple="multiple"
					@change="onFileSelection"
				/>
				<input
					ref="directoryInput"
					type="file"
					class="hidden"
					accept=".pdf,application/pdf"
					webkitdirectory="webkitdirectory"
					multiple="multiple"
					@change="onDirectorySelection"
				/>
				<div class="flex flex-wrap justify-center gap-2">
					<Button :loading="uploading" @click="openFileSelector">
						{{ uploading ? `Uploading ${uploadProgress}%` : 'Add PDFs' }}
					</Button>
					<Button
						variant="outline"
						:disabled="uploading"
						@click="openDirectorySelector"
					>
						Select PDF folder
					</Button>
				</div>
				<p class="mt-2 text-sm text-ink-gray-6">
					Add files in multiple selections, or select a folder to add PDFs from
					it and its nested folders.
				</p>
			</div>
			<div v-if="files.length" class="space-y-2">
				<div
					v-for="file in files"
					:key="file.id"
					class="flex flex-wrap items-center gap-2 rounded border p-2"
				>
					<span class="lucide-file-text size-5 text-ink-gray-6" />
					<span class="min-w-0 flex-1 truncate">{{ file.file_name }}</span>
					<span class="text-xs text-ink-gray-6">{{
						statusLabel(file.status)
					}}</span>
					<Button
						variant="ghost"
						theme="red"
						:disabled="isProcessing"
						@click="removeFile(file.id)"
					>
						Remove
					</Button>
					<div class="flex w-full flex-wrap items-center gap-2">
						<label
							class="text-xs text-ink-gray-6"
							:for="`first-task-${file.id}`"
						>
							First task №
						</label>
						<input
							:id="`first-task-${file.id}`"
							v-model="file.first_task_number"
							type="number"
							min="1"
							max="9999"
							step="1"
							:disabled="isProcessing"
							class="w-24 rounded border border-outline-gray-2 px-2 py-1 text-sm"
						/>
						<label
							class="text-xs text-ink-gray-6"
							:for="`last-task-${file.id}`"
						>
							Last task №
						</label>
						<input
							:id="`last-task-${file.id}`"
							v-model="file.last_task_number"
							type="number"
							min="1"
							max="9999"
							step="1"
							:disabled="isProcessing"
							class="w-24 rounded border border-outline-gray-2 px-2 py-1 text-sm"
						/>
						<span class="text-xs text-ink-gray-5">
							Empty = import the full PDF
						</span>
					</div>
				</div>
			</div>
			<p v-if="uploadError" class="text-sm text-ink-red-5">{{ uploadError }}</p>
			<div
				v-if="isProcessing"
				class="rounded bg-surface-gray-2 p-3 text-sm text-ink-gray-6"
			>
				Processing {{ processedCount }} of {{ files.length }}…
				<p v-if="progressText" class="mt-1">{{ progressText }}</p>
			</div>
		</div>
	</Dialog>
</template>

<script setup lang="ts">
import {
	Button,
	Checkbox,
	createResource,
	Dialog,
	FileUploadHandler,
	toast,
} from 'frappe-ui'
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { SessionUser } from '@/types'

type UploadedFile = { name: string; file_name: string }
type ImportResult = { quiz: string; title: string; question_count: number; used_ai?: boolean; warning?: string }
type ImportJobStatus = { status: 'queued' | 'processing' | 'cancelling' | 'cancelled' | 'done' | 'error'; message?: string; result?: ImportResult; error?: string }
type ImportStatus = 'uploaded' | 'processing' | 'success' | 'error' | 'cancelled'
type ImportFile = UploadedFile & {
	id: number
	request_id: string
	status: ImportStatus
	source_folder: string
	// Vue casts <input type="number"> values to numbers, so both shapes occur.
	first_task_number: string | number
	last_task_number: string | number
	result?: ImportResult
	error?: string
	job_id?: string
}

const show = defineModel<boolean>()
const router = useRouter()
const files = ref<ImportFile[]>([])
const uploadError = ref('')
const isProcessing = ref(false)
const progressText = ref('')
const showAnswers = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const directoryInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const uploadProgress = ref(0)
const aiInstruction = ref('')
let nextFileId = 1
const cancelRequested = ref(false)
const cancelling = ref(false)
const pollingJobs = new Set<string>()
const sessionUser = inject<SessionUser>('$user')
const storageKey = `lms-pdf-trainer-import:${sessionUser?.data?.name || 'guest'}`
let detached = false
onBeforeUnmount(() => { detached = true })

const importer = createResource({
	url: 'lms.lms.pdf_trainer_jobs.start_import',
})
const importStatus = createResource({
	url: 'lms.lms.pdf_trainer_jobs.get_status',
	method: 'GET',
})
const importSession = createResource({
	url: 'lms.lms.pdf_trainer_jobs.get_import_session',
	method: 'GET',
})
const cancelJob = createResource({ url: 'lms.lms.pdf_trainer_jobs.cancel_import' })

function persistState() {
	try { localStorage.setItem(storageKey, JSON.stringify({ files: files.value, showAnswers: showAnswers.value, aiInstruction: aiInstruction.value, nextFileId })) } catch { /* Storage can be disabled by browser policy. */ }
}

function restoreState() {
	try {
		const saved = JSON.parse(localStorage.getItem(storageKey) || 'null')
		if (!saved || !Array.isArray(saved.files)) return
		files.value = saved.files.filter((file: ImportFile) => file && typeof file.name === 'string' && typeof file.file_name === 'string')
		showAnswers.value = !!saved.showAnswers
		aiInstruction.value = typeof saved.aiInstruction === 'string' ? saved.aiInstruction : ''
		nextFileId = Math.max(Number(saved.nextFileId) || 1, ...files.value.map((file) => file.id + 1), 1)
	} catch { localStorage.removeItem(storageKey) }
}

restoreState()
watch([files, showAnswers, aiInstruction], persistState, { deep: true })
watch(show, (open) => { if (open) resumePendingImports() }, { immediate: true })

async function refreshImportSession() {
	const session = (await importSession.fetch()) as { csrf_token: string }
	if (!session?.csrf_token) throw new Error('Could not refresh the upload session')
	;(window as Window & { csrf_token: string }).csrf_token = session.csrf_token
}

const importActions = computed(() => [
	{
		label: 'Import all',
		variant: 'solid',
		disabled: !files.value.length || isProcessing.value,
		loading: isProcessing.value,
		onClick: importPdfs,
	},
])

const dialogActions = computed(() => isProcessing.value ? [
	{ label: cancelling.value ? 'Cancelling…' : 'Cancel import', variant: 'outline', disabled: cancelling.value, onClick: cancelCurrentImport },
] : showSummary.value ? successActions.value : importActions.value)

const successActions = computed(() => [
	{
		label: 'Close',
		onClick: closeAndReset,
	},
	{
		label: 'Import more PDFs',
		variant: 'solid',
		onClick: resetImports,
	},
])

const hasCompletedImports = computed(() =>
	files.value.some(
		(file) =>
			file.status === 'success' ||
			file.status === 'error' ||
			file.status === 'cancelled'
	)
)
const showSummary = computed(
	() => hasCompletedImports.value && !isProcessing.value
)
const completedCount = computed(
	() => files.value.filter((file) => file.status === 'success').length
)
const processedCount = computed(
	() =>
		files.value.filter(
			(file) =>
				file.status === 'success' ||
					file.status === 'error' ||
					file.status === 'cancelled'
		).length
)

function openFileSelector() {
	fileInput.value?.click()
}

function openDirectorySelector() {
	directoryInput.value?.click()
}

function resetImports() {
	files.value = []
	uploadError.value = ''
	uploadProgress.value = 0
	nextFileId = 1
	localStorage.removeItem(storageKey)
}

function closeAndReset({ close }: { close: () => void }) {
	resetImports()
	close()
}

async function onFileSelection(event: Event) {
	const input = event.target as HTMLInputElement
	await uploadSelectedFiles(input.files)
	input.value = ''
}

async function onDirectorySelection(event: Event) {
	const input = event.target as HTMLInputElement
	await uploadSelectedFiles(input.files)
	input.value = ''
}

async function onDrop(event: DragEvent) {
	await uploadSelectedFiles(event.dataTransfer?.files || null)
}

async function uploadSelectedFiles(fileList: FileList | null) {
	const selectedFiles = Array.from(fileList || [])
	const filesWithinDepthLimit = selectedFiles.filter(
		(file) => relativeFolderDepth(file) <= 3
	)
	const skippedFiles = selectedFiles.length - filesWithinDepthLimit.length
	if (skippedFiles) {
		toast.warning(
			`Skipped ${skippedFiles} PDF file(s) nested deeper than 3 folders`
		)
	}
	for (const file of filesWithinDepthLimit) {
		if (
			file.type !== 'application/pdf' &&
			!file.name.toLowerCase().endsWith('.pdf')
		) {
			onUploadFailure({ message: `${file.name}: only PDF files are supported` })
			continue
		}
		await uploadFile(file)
	}
}

function relativeFolderDepth(file: File) {
	const relativePath = file.webkitRelativePath
	if (!relativePath) return 0
	return Math.max(0, relativePath.split('/').length - 2)
}

async function uploadFile(file: File) {
	uploading.value = true
	uploadProgress.value = 0
	const uploader = new FileUploadHandler()
	uploader.on('progress', (data: { uploaded: number; total: number }) => {
		uploadProgress.value = data.total
			? Math.floor((data.uploaded / data.total) * 100)
			: 0
	})
	try {
		await refreshImportSession()
		const uploadedFile = await uploader.upload(file, { private: true })
		onUpload(uploadedFile as UploadedFile, sourceFolder(file))
	} catch (error) {
		onUploadFailure(error as { messages?: string[]; message?: string })
	} finally {
		uploading.value = false
	}
}

function sourceFolder(file: File) {
	const relativePath = file.webkitRelativePath
	if (!relativePath) return ''
	return relativePath.split('/').slice(0, -1).join(' / ')
}

function onUpload(file: UploadedFile, source_folder: string) {
	if (files.value.some((item) => item.name === file.name)) return
	files.value.push({
		...file,
		id: nextFileId++,
		request_id: newRequestId(),
		status: 'uploaded',
		source_folder,
		first_task_number: '',
		last_task_number: '',
	})
}

function onUploadFailure(error: { messages?: string[]; message?: string }) {
	uploadError.value =
		error.messages?.[0] || error.message || 'PDF upload failed'
	toast.error(uploadError.value)
}

async function importPdfs() {
	if (isProcessing.value) return
	isProcessing.value = true
	cancelRequested.value = false
	cancelling.value = false
	uploadError.value = ''
	for (const file of files.value) {
		if (cancelRequested.value) break
		if (file.status !== 'uploaded') continue
		const rangeError = validateTaskRange(file)
		if (rangeError) {
			file.status = 'error'
			file.error = rangeError
			toast.error(`${file.file_name}: ${rangeError}`)
			continue
		}
		file.status = 'processing'
		try {
			await refreshImportSession()
			const job = (await importer.submit({
				pdf_file: file.name,
				request_id: file.request_id,
				source_folder: file.source_folder,
				show_answers: showAnswers.value ? 1 : 0,
				use_ai: 1,
				ai_instruction: aiInstruction.value,
				...taskRangeParams(file),
			})) as { job_id: string }
			file.job_id = job.job_id
			persistState()
			if (cancelRequested.value) await cancelJob.submit({ job_id: job.job_id })
			file.result = await trackJob(file)
			file.status = 'success'
			if (file.result.warning) toast.warning(file.result.warning)
		} catch (error) {
			if (detached) return
			if (cancelRequested.value || getErrorMessage(error, '').includes('cancelled')) {
				file.status = 'cancelled'
				file.error = 'Import cancelled'
			} else {
				file.status = 'error'
				file.error = getErrorMessage(error, 'PDF import failed')
				toast.error(`${file.file_name}: ${file.error}`)
			}
		}
	}
	isProcessing.value = false
	cancelling.value = false
	progressText.value = ''
}

async function trackJob(file: ImportFile) {
	if (!file.job_id) throw new Error('Missing import job ID')
	if (pollingJobs.has(file.job_id)) throw new Error('This import is already being monitored')
	pollingJobs.add(file.job_id)
	try { return await waitForImport(file.job_id) } finally { pollingJobs.delete(file.job_id) }
}

async function resumePendingImports() {
	const pending = files.value.filter((file) => file.status === 'processing' && file.job_id && !pollingJobs.has(file.job_id))
	if (!pending.length || isProcessing.value) return
	isProcessing.value = true
	for (const file of pending) {
		try {
			file.result = await trackJob(file)
			file.status = 'success'
		} catch (error) {
			if (detached) return
			if (getErrorMessage(error, '').includes('cancelled')) file.status = 'cancelled'
			else { file.status = 'error'; file.error = getErrorMessage(error, 'PDF import failed') }
		}
	}
	isProcessing.value = false
	progressText.value = ''
}

async function cancelCurrentImport() {
	if (cancelling.value) return
	cancelRequested.value = true
	cancelling.value = true
	const active = files.value.find((file) => file.status === 'processing' && file.job_id)
	if (active?.job_id) {
		try { await cancelJob.submit({ job_id: active.job_id }) }
		catch (error) { toast.error(getErrorMessage(error, 'Could not cancel import')); cancelRequested.value = false; cancelling.value = false; return }
	} else {
		files.value.filter((file) => file.status === 'uploaded').forEach((file) => { file.status = 'cancelled'; file.error = 'Import cancelled' })
	}
}

async function waitForImport(jobId: string): Promise<ImportResult> {
	const deadline = Date.now() + 22 * 60 * 1000
	let failures = 0
	while (Date.now() < deadline) {
		if (detached) throw new Error('Import monitoring paused')
		let state: ImportJobStatus
		try {
			state = (await importStatus.submit({ job_id: jobId })) as ImportJobStatus
			failures = 0
		} catch (error) {
			if (++failures >= 3) throw error
			await new Promise((resolve) => setTimeout(resolve, 2000))
			continue
		}
		progressText.value = state.message || ''
		if (state.status === 'done' && state.result) return state.result
		if (state.status === 'error') throw new Error(state.error || 'AI review failed')
		if (state.status === 'cancelled') throw new Error('Import cancelled')
		await new Promise((resolve) => setTimeout(resolve, 2000))
	}
	throw new Error('AI review is taking longer than expected. Retry to check the same import job.')
}

async function retryImport(file: ImportFile) {
	file.status = 'uploaded'
	file.error = ''
	await importPdfs()
}

function validateTaskRange(file: ImportFile) {
	const first = String(file.first_task_number ?? '').trim()
	const last = String(file.last_task_number ?? '').trim()
	if (!first && !last) return ''
	if (!first || !last) {
		return 'Fill in both the first and the last task number, or leave both empty'
	}
	const firstNumber = Number(first)
	const lastNumber = Number(last)
	if (!Number.isInteger(firstNumber) || !Number.isInteger(lastNumber)) {
		return 'Task numbers must be whole numbers'
	}
	if (
		firstNumber < 1 ||
		lastNumber < 1 ||
		firstNumber > 9999 ||
		lastNumber > 9999
	) {
		return 'Task numbers must be between 1 and 9999'
	}
	if (firstNumber > lastNumber) {
		return 'The first task number must not be greater than the last task number'
	}
	return ''
}

function taskRangeParams(file: ImportFile) {
	const first = String(file.first_task_number ?? '').trim()
	const last = String(file.last_task_number ?? '').trim()
	if (!first || !last) return {}
	return { first_task_number: first, last_task_number: last }
}

async function removeFile(id: number) {

	files.value = files.value.filter((file) => file.id !== id)
}

function openQuiz(result: ImportResult) {
	router.push({ name: 'QuizForm', params: { quizID: result.quiz } })
}

function statusLabel(status: ImportStatus) {
	return {
		uploaded: 'Ready',
		processing: 'Processing…',
		success: 'Done',
		error: 'Error',
		cancelled: 'Cancelled',
	}[status]
}

function statusIconClass(status: ImportStatus) {
	return {
		uploaded: 'lucide-circle-check text-ink-gray-5',
		processing: 'lucide-loader-circle animate-spin text-ink-blue-5',
		success: 'lucide-circle-check text-ink-green-5',
		error: 'lucide-circle-x text-ink-red-5',
		cancelled: 'lucide-circle-x text-ink-gray-5',
	}[status]
}

let requestFallbackCounter = 0
function newRequestId() {
	return globalThis.crypto?.randomUUID?.() || `pdf-${Date.now()}-${++requestFallbackCounter}`
}

function getErrorMessage(error: unknown, fallback: string) {
	const value = error as { messages?: string[]; message?: string }
	return value?.messages?.[0] || value?.message || fallback
}
</script>
