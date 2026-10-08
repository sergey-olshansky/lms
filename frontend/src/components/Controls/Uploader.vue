<template>
	<div class="space-y-1.5">
		<div ref="uploaderRoot">
			<InputLabel
				v-if="label"
				:id="labelId"
				:for-id="inputId"
				:label="label ? __(label) : undefined"
				:required="required"
			/>
			<FileUploader
				:fileTypes="[fileType]"
				:private="false"
				:validateFile="(file: File) => validateFile(file, false, type)"
				@success="(file: { file_url: string }) => saveFile(file)"
				@failure="onUploadFailure"
			>
				<template v-slot="{ uploading, progress, openFileSelector }">
					<div class="flex items-start gap-4">
						<div
							:class="[
								'relative shrink-0 border rounded-5 bg-surface-gray-2 grid place-items-center overflow-hidden',
								previewBoxClasses,
							]"
						>
							<template v-if="modelValue">
								<img
									v-if="type === 'image'"
									:src="safeUrl(modelValue)"
									:alt="label ? __(label) : __('Uploaded image preview')"
									class="size-full object-cover"
								/>
								<video v-else controls class="size-full object-cover">
									<source :src="safeUrl(modelValue)" />
									{{ __('Your browser does not support the video tag.') }}
								</video>
							</template>
							<component
								v-else
								:is="type === 'image' ? Image : Video"
								class="size-5 text-ink-gray-5"
							/>
						</div>
						<div class="flex items-center gap-2">
							<Button
								:id="inputId"
								@click="openFileSelector"
								:loading="uploading"
							>
								{{
									uploading
										? `${__('Uploading')} ${progress}%`
										: modelValue
										? __('Replace')
										: __('Upload')
								}}
							</Button>
							<Button
								v-if="modelValue && !uploading"
								variant="ghost"
								theme="red"
								@click="removeImage()"
							>
								{{ __('Remove') }}
							</Button>
						</div>
					</div>
				</template>
			</FileUploader>
		</div>
		<InputDescription
			v-if="showDescription"
			:id="descriptionId"
			:description="description ? __(description) : undefined"
		/>
		<InputError v-if="hasError" :id="errorMessageId" :lines="errorLines" />
	</div>
</template>

<script setup lang="ts">
import { validateFile } from '@/utils'
import { transliterateFileName } from '@/utils/transliterateFileName'
import { Button, FileUploader, UploadError, toast } from 'frappe-ui'
import {
	InputDescription,
	InputError,
	InputLabel,
	useInputLabeling,
} from 'frappe-ui/experimental'
import { Image, Video } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { safeUrl } from '@/utils/safeUrl'

const emit = defineEmits<{
	(e: 'update:modelValue', value: string): void
}>()

const props = withDefaults(
	defineProps<{
		modelValue: string | null
		label?: string
		type?: 'image' | 'video'
		required?: boolean
		shape?: 'square' | 'circle'
		description?: string
		error?: string
	}>(),
	{
		type: 'image',
		required: true,
		shape: 'square',
	}
)

const {
	inputId,
	labelId,
	descriptionId,
	errorMessageId,
	hasError,
	errorLines,
	showDescription,
} = useInputLabeling(props)

const uploaderRoot = ref<HTMLElement | null>(null)

// frappe-ui FileUploader uploads `file.name` as-is (fileUploadHandler.ts) and
// the backend does not transliterate names, so cyrillic uploads land with
// unusable URLs. The hidden <input type="file"> sits next to the slot (not
// inside it), so a capture-phase `change` on the wrapper fires before
// FileUploader's onFileAdd reads event.target.files; swap the files for
// transliterated copies there.
const onCapturedChange = (event: Event) => {
	const input = event.target
	if (!(input instanceof HTMLInputElement) || input.type !== 'file') return
	const files = input.files
	if (!files || !files.length) return
	const renamed: File[] = []
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

const fileType = computed<string>(() =>
	props.type === 'image' ? 'image/*' : 'video/*'
)

const previewBoxClasses = computed<string>(() => {
	if (props.shape === 'circle') return 'size-24 rounded-full'
	return 'w-56 aspect-[750/422] rounded-5'
})

const saveFile = (file: { file_url: string }) => {
	emit('update:modelValue', file.file_url)
}

const removeImage = () => {
	emit('update:modelValue', '')
}

const uploadErrorMessage = (error: unknown): string => {
	if (typeof error === 'string') return error
	if (error instanceof UploadError) return error.messages[0] || error.message
	return __('Error Uploading File')
}

const onUploadFailure = (error: unknown) => {
	toast.error(uploadErrorMessage(error))
}
</script>
