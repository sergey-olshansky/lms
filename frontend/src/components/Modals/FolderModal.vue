<template>
	<Dialog v-model:open="show" :title="folder?.title ?? ''" size="lg">
		<template #default>
			<div class="space-y-4">
				<div class="flex items-center justify-between gap-2">
					<div class="text-sm text-ink-gray-5">
						{{ imagesLabel }}
					</div>
					<template v-if="allowEdit">
						<input
							ref="fileInput"
							type="file"
							class="hidden"
							multiple
							:accept="FOLDER_IMAGE_ACCEPT"
							@change="onFilesSelected"
						/>
						<Button
							variant="solid"
							:loading="uploading"
							@click="pickFiles"
						>
							<template #prefix>
								<span class="lucide-image-up size-4" />
							</template>
							{{ __('Upload images') }}
						</Button>
					</template>
				</div>

				<div
					v-if="!images.length && !queue.length"
					class="flex flex-col items-center justify-center gap-2 py-10 text-center text-ink-gray-5"
					data-testid="folder-empty"
				>
					<span class="lucide-images size-8" aria-hidden="true" />
					<div class="text-sm">{{ __('No images yet') }}</div>
				</div>

				<div
					v-else
					class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4"
					data-testid="folder-gallery"
				>
					<div
						v-for="(image, index) in images"
						:key="image.name"
						class="group relative"
					>
						<img
							:src="safeUrl(image.file_url)"
							:alt="image.file_name"
							class="aspect-square w-full cursor-zoom-in rounded-4 border border-outline-gray-2 object-cover"
							loading="lazy"
							data-testid="folder-image"
							@click="lightboxIndex = index"
						/>
						<span
							class="absolute start-1 top-1 rounded-3 bg-surface-gray-7/80 px-1.5 py-0.5 text-xs text-white"
						>
							{{ index + 1 }}
						</span>
						<button
							v-if="allowEdit"
							type="button"
							class="absolute end-1 top-1 inline-flex size-7 items-center justify-center rounded-4 bg-surface-gray-7/80 text-white opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
							:aria-label="__('Delete this image?')"
							:disabled="deletingImage === image.name"
							@click="confirmDeleteImage(image)"
						>
							<span class="lucide-trash-2 size-4" aria-hidden="true" />
						</button>
					</div>
				</div>

				<div v-if="queue.length" class="space-y-2" data-testid="folder-queue">
					<div class="flex items-center justify-between gap-2">
						<div class="text-sm text-ink-gray-6">
							{{ __('Uploading {0} of {1}').format(uploadedCount, queue.length) }}
						</div>
						<Button
							v-if="failedCount && !uploading"
							size="sm"
							@click="retryFailed"
						>
							<template #prefix>
								<span class="lucide-rotate-ccw size-4" />
							</template>
							{{ __('Retry failed') }}
						</Button>
					</div>
					<div class="h-1.5 w-full overflow-hidden rounded-full bg-surface-gray-3">
						<div
							class="h-full rounded-full bg-surface-blue-2 transition-all"
							:style="{ width: `${queueProgress(queue)}%` }"
						/>
					</div>
					<ul class="max-h-40 space-y-1.5 overflow-y-auto pe-1">
						<li
							v-for="item in queue"
							:key="item.id"
							class="flex items-start gap-2 text-sm"
							:data-testid="`queue-${item.status}`"
						>
							<span
								class="mt-0.5 size-4 shrink-0"
								:class="{
									'lucide-check': item.status === 'done',
									'lucide-check-check text-ink-gray-4':
										item.status === 'skipped',
									'lucide-loader-circle animate-spin':
										item.status === 'uploading' || item.status === 'pending',
									'lucide-circle-x text-ink-red-5': item.status === 'error',
								}"
								aria-hidden="true"
							/>
							<span class="min-w-0 flex-1">
								<span class="block truncate" :title="item.file.name">{{
									item.file.name
								}}</span>
								<span
									v-if="item.status === 'error' && item.error"
									class="block text-xs text-ink-red-5"
								>
									{{ item.error }}
								</span>
								<span
									v-else-if="item.status === 'skipped'"
									class="block text-xs text-ink-gray-5"
								>
									{{ __('Already in the folder') }}
								</span>
							</span>
							<span
								v-if="item.status === 'uploading'"
								class="shrink-0 text-xs text-ink-gray-5"
							>
								{{ item.progress }}%
							</span>
							<span
								v-else
								class="shrink-0 text-xs text-ink-gray-5"
							>
								{{ formatFileSize(item.file.size) }}
							</span>
						</li>
					</ul>
				</div>
			</div>
		</template>
	</Dialog>
	<Teleport to="body">
		<div
			v-if="lightboxIndex !== null && images[lightboxIndex]"
			class="fixed inset-0 z-[100] flex items-center justify-center bg-surface-gray-8/90 p-4"
			role="dialog"
			aria-modal="true"
			:aria-label="__('Images')"
			data-testid="folder-lightbox"
			@click.self="lightboxIndex = null"
		>
			<button
				type="button"
				class="absolute end-4 top-4 inline-flex size-10 items-center justify-center rounded-4 text-white hover:bg-surface-gray-7"
				:aria-label="__('Close')"
				@click="lightboxIndex = null"
			>
				<span class="lucide-x size-6" aria-hidden="true" />
			</button>
			<button
				type="button"
				class="absolute start-4 top-1/2 inline-flex size-10 -translate-y-1/2 items-center justify-center rounded-4 text-white hover:bg-surface-gray-7 disabled:cursor-not-allowed disabled:opacity-40"
				:aria-label="__('Previous image')"
				:disabled="lightboxIndex <= 0"
				@click="stepLightbox(-1)"
			>
				<span class="lucide-chevron-left size-6 rtl:rotate-180" aria-hidden="true" />
			</button>
			<figure class="flex max-h-full max-w-full flex-col items-center gap-2">
				<img
					:src="safeUrl(images[lightboxIndex].file_url)"
					:alt="images[lightboxIndex].file_name"
					class="max-h-[82vh] max-w-full rounded-4 object-contain"
				/>
				<figcaption class="text-sm text-ink-gray-2">
					{{ images[lightboxIndex].file_name }}
					{{ lightboxIndex + 1 }}/{{ images.length }}
				</figcaption>
			</figure>
			<button
				type="button"
				class="absolute end-4 top-1/2 inline-flex size-10 -translate-y-1/2 items-center justify-center rounded-4 text-white hover:bg-surface-gray-7 disabled:cursor-not-allowed disabled:opacity-40"
				:aria-label="__('Next image')"
				:disabled="lightboxIndex >= images.length - 1"
				@click="stepLightbox(1)"
			>
				<span class="lucide-chevron-right size-6 rtl:rotate-180" aria-hidden="true" />
			</button>
		</div>
	</Teleport>
</template>

<script setup lang="ts">
import { Button, Dialog, createResource, toast } from 'frappe-ui'
import { computed, getCurrentInstance, onBeforeUnmount, ref, watch } from 'vue'
import type { FrappeResourceError } from 'frappe-ui'
import { resourceErrorMessage } from '@/utils/resource'
import { safeUrl } from '@/utils/safeUrl'
import {
	FOLDER_IMAGE_ACCEPT,
	buildUploadItems,
	formatFileSize,
	queueFinished,
	queueProgress,
	retryTargets,
	type FolderUploadItem,
} from '@/utils/folderImages'
import type { OutlineFolder, OutlineFolderImage, Resource } from '@/types'

type DialogAction = {
	label: string
	theme?: string
	variant?: string
	onClick: (context: { close: () => void }) => void
}
type DialogFn = (opts: {
	title: string
	message: string
	actions: DialogAction[]
}) => void

const { $dialog } = getCurrentInstance()!.appContext.config.globalProperties as {
	$dialog: DialogFn
}

/** One image folder, open: the gallery for every viewer, plus — for course
 * editors — bulk upload with per-file progress, per-failure reasons and a
 * retry-failed-only pass (successful files never re-upload, and the server
 * skips duplicates, so retries are idempotent). */
const props = defineProps<{
	courseName: string
	outline: Resource<unknown>
}>()

const show = ref(false)
const allowEdit = ref(false)
const folder = ref<OutlineFolder | null>(null)
const images = ref<OutlineFolderImage[]>([])
const queue = ref<FolderUploadItem[]>([])
const uploading = ref(false)
const lightboxIndex = ref<number | null>(null)
const deletingImage = ref<string>('')
const fileInput = ref<HTMLInputElement | null>(null)
const dirty = ref(false)

const imagesLabel = computed<string>(() => {
	const count = images.value.length
	return `${count} ${count === 1 ? __('image') : __('images')}`
})
const uploadedCount = computed<number>(
	() => queue.value.filter((item) => ['done', 'skipped'].includes(item.status)).length
)
const failedCount = computed<number>(
	() => queue.value.filter((item) => item.status === 'error').length
)

function open(target: OutlineFolder, editable: boolean) {
	folder.value = target
	allowEdit.value = editable
	images.value = [...(target.images ?? [])]
	queue.value = []
	lightboxIndex.value = null
	dirty.value = false
	show.value = true
}

watch(show, (openNow) => {
	if (openNow) return
	lightboxIndex.value = null
	if (dirty.value) props.outline.reload()
})

const deleteImage = createResource({
	url: 'lms.lms.api.delete_folder_image',
	makeParams(values: { folder: string; image: string }) {
		return values
	},
	onSuccess(_data: unknown, values: { folder: string; image: string }) {
		images.value = images.value.filter((image) => image.name !== values.image)
		deletingImage.value = ''
		dirty.value = true
		toast.success(__('Image deleted'))
	},
	onError(err: FrappeResourceError) {
		deletingImage.value = ''
		toast.error(resourceErrorMessage(err, __('Error')))
	},
})

function confirmDeleteImage(image: OutlineFolderImage) {
	if (!folder.value) return
	$dialog({
		title: __('Delete this image?'),
		message: __(
			'This image will be permanently removed from the folder. This action cannot be undone.'
		),
		actions: [
			{
				label: __('Delete'),
				theme: 'red',
				variant: 'solid',
				onClick({ close }) {
					deletingImage.value = image.name
					deleteImage.submit({ folder: folder.value!.name, image: image.name })
					close()
				},
			},
		],
	})
}

function pickFiles() {
	fileInput.value?.click()
}

function onFilesSelected(event: Event) {
	const input = event.target as HTMLInputElement
	const files = Array.from(input.files ?? [])
	input.value = ''
	if (!files.length || !folder.value) return

	const { accepted, rejected } = buildUploadItems(files)
	for (const rejection of rejected) {
		toast.error(`${rejection.file.name}: ${rejection.reason}`)
	}
	if (!accepted.length) return
	queue.value.push(...accepted)
	startPump()
}

async function startPump() {
	if (uploading.value || !folder.value) return
	uploading.value = true
	try {
		while (true) {
			const next = queue.value.find((item) => item.status === 'pending')
			if (!next) break
			next.status = 'uploading'
			next.progress = 0
			try {
				const response = await uploadOne(folder.value.name, next)
				if (response.status === 'skipped') {
					next.status = 'skipped'
					next.uploadedFile = response.file
				} else {
					next.status = 'done'
					next.progress = 100
					next.uploadedFile = response.file
					images.value.push(response.file)
					dirty.value = true
				}
			} catch (error) {
				next.status = 'error'
				next.progress = 0
				next.error = errorMessage(error)
			}
		}
	} finally {
		uploading.value = false
		if (queueFinished(queue.value)) queue.value = []
	}
}

function retryFailed() {
	for (const item of retryTargets(queue.value)) {
		item.status = 'pending'
		item.progress = 0
		item.error = undefined
	}
	startPump()
}

interface UploadResponse {
	status: 'uploaded' | 'skipped'
	file: OutlineFolderImage
}

function uploadOne(
	folderName: string,
	item: FolderUploadItem
): Promise<UploadResponse> {
	return new Promise((resolve, reject) => {
		const xhr = new XMLHttpRequest()
		xhr.open('POST', '/api/method/lms.lms.api.upload_folder_image')
		xhr.setRequestHeader('Accept', 'application/json')
		xhr.upload.onprogress = (event) => {
			if (event.lengthComputable) {
				item.progress = Math.round((event.loaded / event.total) * 100)
			}
		}
		xhr.onerror = () => reject(new Error(__('Network error')))
		xhr.onload = () => {
			if (xhr.status >= 200 && xhr.status < 300) {
				try {
					const body =
						typeof xhr.response === 'string'
							? JSON.parse(xhr.response)
							: xhr.response
					const message = body?.message ?? body
					if (message?.file?.name) resolve(message)
					else reject(new Error(__('Error Uploading File')))
				} catch {
					reject(new Error(__('Error Uploading File')))
				}
			} else {
				reject(new Error(serverErrorMessage(xhr)))
			}
		}
		const form = new FormData()
		form.append('folder', folderName)
		form.append('file', item.file)
		xhr.send(form)
	})
}

/** Pull the human-readable reason out of a Frappe JSON error body. */
function serverErrorMessage(xhr: XMLHttpRequest): string {
	try {
		const body =
			typeof xhr.response === 'string' && xhr.response
				? JSON.parse(xhr.response)
				: xhr.response
		const raw = body?._server_messages
		if (typeof raw === 'string') {
			const messages = JSON.parse(raw)
			const first = typeof messages?.[0] === 'string' ? JSON.parse(messages[0]) : messages?.[0]
			const text = first?.message ?? first
			if (typeof text === 'string' && text) return stripTags(text)
		}
		if (typeof body?.message === 'string' && body.message) {
			return stripTags(body.message)
		}
	} catch {
		// fall through to the generic message
	}
	if (xhr.status === 413) {
		return __('Image is larger than the {0} MB limit.').format(10)
	}
	return __('Error Uploading File')
}

function stripTags(text: string): string {
	return text.replace(/<[^>]*>/g, '').trim()
}

function errorMessage(error: unknown): string {
	return error instanceof Error && error.message ? error.message : __('Error')
}

function stepLightbox(delta: number) {
	if (lightboxIndex.value === null) return
	const next = lightboxIndex.value + delta
	if (next >= 0 && next < images.value.length) lightboxIndex.value = next
}

function onKeydown(event: KeyboardEvent) {
	if (lightboxIndex.value === null) return
	if (event.key === 'Escape') lightboxIndex.value = null
	else if (event.key === 'ArrowLeft') stepLightbox(-1)
	else if (event.key === 'ArrowRight') stepLightbox(1)
}

if (typeof window !== 'undefined') {
	window.addEventListener('keydown', onKeydown)
}
onBeforeUnmount(() => {
	if (typeof window !== 'undefined') {
		window.removeEventListener('keydown', onKeydown)
	}
})

defineExpose({ open })
</script>
