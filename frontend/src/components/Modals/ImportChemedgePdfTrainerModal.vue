<template>
	<Dialog
		v-model:open="show"
		title="Import Chemedge PDF Trainer"
		size="lg"
		:actions="success ? successActions : importActions"
	>
		<div v-if="success" class="space-y-3 text-base">
			<p>Quiz created successfully.</p>
			<p class="text-ink-gray-6">{{ success.title }} · {{ success.question_count }} questions</p>
		</div>
		<div v-else class="space-y-4 text-base">
			<p class="text-ink-gray-6">
				Upload one supported Chemedge PDF. The imported quiz will have two attempts,
				an 85% passing score, and one mark per question.
			</p>
			<FileUploader
				v-if="!pdfFile"
				:file-types="['.pdf']"
				:upload-args="{ private: true }"
				@success="onUpload"
				@failure="onUploadFailure"
			>
				<template #default="{ uploading, progress, openFileSelector }">
					<Button :loading="uploading" @click="openFileSelector">
						{{ uploading ? `Uploading ${progress}%` : 'Upload PDF' }}
					</Button>
				</template>
			</FileUploader>
			<div v-else class="flex items-center gap-3 rounded border p-3">
				<span class="lucide-file-text size-5 text-ink-gray-6" />
				<span class="min-w-0 flex-1 truncate">{{ pdfFile.file_name }}</span>
				<Button variant="ghost" theme="red" @click="pdfFile = null">Remove</Button>
			</div>
		</div>
	</Dialog>
</template>

<script setup lang="ts">
import { Button, createResource, Dialog, FileUploader, toast } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

type UploadedFile = { name: string; file_name: string }
type ImportResult = { quiz: string; title: string; question_count: number }

const show = defineModel<boolean>()
const router = useRouter()
const pdfFile = ref<UploadedFile | null>(null)
const success = ref<ImportResult | null>(null)

const importer = createResource({
	url: 'lms.lms.chemedge_pdf_import.import_pdf_trainer',
	makeParams() {
		return { pdf_file: pdfFile.value?.name }
	},
})

const importActions = computed(() => [
	{
		label: 'Import',
		variant: 'solid',
		disabled: !pdfFile.value,
		loading: importer.loading,
		onClick: importPdf,
	},
])

const successActions = computed(() => [
	{
		label: 'Close',
		onClick: ({ close }: { close: () => void }) => close(),
	},
	{
		label: 'Open Quiz',
		variant: 'solid',
		onClick: openQuiz,
	},
])

function onUpload(file: UploadedFile) {
	pdfFile.value = file
}

function onUploadFailure(error: { messages?: string[]; message?: string }) {
	toast.error(error.messages?.[0] || error.message || 'PDF upload failed')
}

function importPdf() {
	importer.submit({}, {
		onSuccess(data: ImportResult) {
			success.value = data
		},
		onError(error: { messages?: string[]; message?: string }) {
			toast.error(error.messages?.[0] || error.message || 'PDF import failed')
		},
	})
}

function openQuiz({ close }: { close: () => void }) {
	if (!success.value) return
	close()
	router.push({ name: 'QuizForm', params: { quizID: success.value.quiz } })
}
</script>
