<template>
	<Dialog
		v-model:open="show"
		title="Import Chemedge PDF Trainer"
		size="lg"
		:actions="showSummary ? successActions : importActions"
	>
		<div v-if="showSummary" class="space-y-4 text-base">
			<div class="space-y-1">
				<p>Import complete.</p>
				<p class="text-ink-gray-6">
					{{ completedCount }} of {{ files.length }} trainer(s) imported successfully.
				</p>
			</div>
			<div class="max-h-64 space-y-2 overflow-y-auto">
				<div
					v-for="file in files"
					:key="file.id"
					class="flex flex-wrap items-center gap-2 rounded border p-2 text-sm"
				>
					<span
						class="size-4"
						:class="statusIconClass(file.status)"
					/>
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
					<p v-if="file.error" class="w-full text-xs text-ink-red-5">{{ file.error }}</p>
				</div>
			</div>
		</div>
		<div v-else class="space-y-4 text-base">
			<p class="text-ink-gray-6">
				Upload one or more supported Chemedge PDFs. The imported quizzes will have two attempts,
				an 85% passing score, and one mark per question.
			</p>
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
					<Button variant="outline" :disabled="uploading" @click="openDirectorySelector">
						Select PDF folder
					</Button>
				</div>
				<p class="mt-2 text-sm text-ink-gray-6">
					Add files in multiple selections, or select a folder to add PDFs from it and its nested folders.
				</p>
			</div>
			<div v-if="files.length" class="space-y-2">
				<div
					v-for="file in files"
					:key="file.id"
					class="flex items-center gap-2 rounded border p-2"
				>
					<span class="lucide-file-text size-5 text-ink-gray-6" />
					<span class="min-w-0 flex-1 truncate">{{ file.file_name }}</span>
					<span class="text-xs text-ink-gray-6">{{ statusLabel(file.status) }}</span>
					<Button
						variant="ghost"
						theme="red"
						:disabled="isProcessing"
						@click="removeFile(file.id)"
					>
						Remove
					</Button>
				</div>
			</div>
			<p v-if="uploadError" class="text-sm text-ink-red-5">{{ uploadError }}</p>
			<div v-if="isProcessing" class="rounded bg-surface-gray-2 p-3 text-sm text-ink-gray-6">
				Processing {{ processedCount }} of {{ files.length }}…
			</div>
		</div>
	</Dialog>
</template>

<script setup lang="ts">
import { Button, createResource, Dialog, FileUploadHandler, toast } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

type UploadedFile = { name: string; file_name: string }
type ImportResult = { quiz: string; title: string; question_count: number }
type ImportStatus = 'uploaded' | 'processing' | 'success' | 'error'
type ImportFile = UploadedFile & {
	id: number
	status: ImportStatus
	source_folder: string
	result?: ImportResult
	error?: string
}

const show = defineModel<boolean>()
const router = useRouter()
const files = ref<ImportFile[]>([])
const uploadError = ref('')
const isProcessing = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const directoryInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const uploadProgress = ref(0)
let nextFileId = 1

const importer = createResource({
	url: 'lms.lms.chemedge_pdf_import.import_pdf_trainer',
})

const importActions = computed(() => [
	{
		label: 'Import all',
		variant: 'solid',
		disabled: !files.value.length || isProcessing.value,
		loading: isProcessing.value,
		onClick: importPdfs,
	},
])

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

const hasCompletedImports = computed(() => files.value.some((file) => file.status === 'success' || file.status === 'error'))
const showSummary = computed(() => hasCompletedImports.value && !isProcessing.value)
const completedCount = computed(() => files.value.filter((file) => file.status === 'success').length)
const processedCount = computed(() => files.value.filter((file) => file.status === 'success' || file.status === 'error').length)

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
	const filesWithinDepthLimit = selectedFiles.filter((file) => relativeFolderDepth(file) <= 3)
	const skippedFiles = selectedFiles.length - filesWithinDepthLimit.length
	if (skippedFiles) {
		toast.warning(`Skipped ${skippedFiles} PDF file(s) nested deeper than 3 folders`)
	}
	for (const file of filesWithinDepthLimit) {
		if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
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
		uploadProgress.value = data.total ? Math.floor((data.uploaded / data.total) * 100) : 0
	})
	try {
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
	files.value.push({ ...file, id: nextFileId++, status: 'uploaded', source_folder })
}

function onUploadFailure(error: { messages?: string[]; message?: string }) {
	uploadError.value = error.messages?.[0] || error.message || 'PDF upload failed'
	toast.error(uploadError.value)
}

async function importPdfs() {
	isProcessing.value = true
	uploadError.value = ''
	for (const file of files.value) {
		if (file.status !== 'uploaded') continue
		file.status = 'processing'
		try {
			file.result = await importer.submit({
				pdf_file: file.name,
				source_folder: file.source_folder,
			})
			file.status = 'success'
		} catch (error) {
			file.status = 'error'
			file.error = getErrorMessage(error, 'PDF import failed')
			toast.error(`${file.file_name}: ${file.error}`)
		}
	}
	isProcessing.value = false
}

function removeFile(id: number) {
	files.value = files.value.filter((file) => file.id !== id)
}

function openQuiz(result: ImportResult) {
	router.push({ name: 'QuizForm', params: { quizID: result.quiz } })
}

function statusLabel(status: ImportStatus) {
	return { uploaded: 'Ready', processing: 'Processing…', success: 'Done', error: 'Error' }[status]
}

function statusIconClass(status: ImportStatus) {
	return {
		uploaded: 'lucide-circle-check text-ink-gray-5',
		processing: 'lucide-loader-circle animate-spin text-ink-blue-5',
		success: 'lucide-circle-check text-ink-green-5',
		error: 'lucide-circle-x text-ink-red-5',
	}[status]
}

function getErrorMessage(error: unknown, fallback: string) {
	const value = error as { messages?: string[]; message?: string }
	return value?.messages?.[0] || value?.message || fallback
}
</script>
