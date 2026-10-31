<template>
	<PageHeader :breadcrumbs="breadcrumbs" :loading="outline.loading && !outline.data" />
	<div
		v-if="outline.data && !found"
		class="flex flex-col items-center justify-center gap-3 py-16 text-center text-ink-gray-5"
		data-testid="folder-not-found"
	>
		<span class="lucide-folder size-8" aria-hidden="true" />
		<div class="text-sm">
			{{ __('This folder does not exist in this course anymore.') }}
		</div>
		<Button
			variant="solid"
			data-testid="folder-back-to-course"
			@click="backToCourse()"
		>
			<template #prefix>
				<span class="lucide-arrow-left size-4 rtl:rotate-180" />
			</template>
			{{ __('Back to course') }}
		</Button>
	</div>
	<div
		v-else-if="found"
		class="mx-auto w-full max-w-screen-lg px-5 pb-16 pt-6"
		data-testid="folder-page"
	>
		<div class="mb-4 flex flex-wrap items-center justify-between gap-2">
			<h1 class="text-2xl-semibold text-ink-gray-9" :title="folder!.title">
				{{ folder!.title }}
			</h1>
			<div class="flex items-center gap-3">
				<div class="text-sm text-ink-gray-5" data-testid="folder-image-count">
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
						data-testid="folder-upload-button"
						@click="pickFiles"
					>
						<template #prefix>
							<span class="lucide-image-up size-4" />
						</template>
						{{ __('Upload images') }}
					</Button>
				</template>
			</div>
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
			<div v-for="(image, index) in images" :key="image.name" class="group relative">
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

		<div v-if="queue.length" class="mt-4 space-y-2" data-testid="folder-queue">
			<div class="flex items-center justify-between gap-2">
				<div class="text-sm text-ink-gray-6">
					{{ __('Uploading {0} of {1}').format(uploadedCount, queue.length) }}
				</div>
				<Button v-if="failedCount && !uploading" size="sm" @click="retryFailed">
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
							'lucide-check-check text-ink-gray-4': item.status === 'skipped',
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
					<span v-if="item.status === 'uploading'" class="shrink-0 text-xs text-ink-gray-5">
						{{ item.progress }}%
					</span>
					<span v-else class="shrink-0 text-xs text-ink-gray-5">
						{{ formatFileSize(item.file.size) }}
					</span>
				</li>
			</ul>
		</div>
	</div>
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
import { Button, createResource, toast, usePageMeta } from 'frappe-ui'
import type { FrappeResourceError } from 'frappe-ui'
import { computed, getCurrentInstance, inject, onBeforeUnmount, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import PageHeader from '@/components/Layouts/pages/PageHeader.vue'
import { sessionStore } from '@/stores/session'
import { resourceErrorMessage } from '@/utils/resource'
import { safeUrl } from '@/utils/safeUrl'
import {
	FOLDER_IMAGE_ACCEPT,
	buildUploadItems,
	formatFileSize,
	queueFinished,
	queueProgress,
	retryTargets,
	uploadFolderImage,
	type FolderUploadItem,
} from '@/utils/folderImages'
import { findFolder } from '@/utils/courseOutline'
import type {
	Breadcrumb,
	CourseDetails,
	OutlineChapter,
	OutlineFolderImage,
	Resource,
	SessionUser,
} from '@/types'

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

const router = useRouter()
const { brand } = sessionStore()
const user = inject<SessionUser>('$user')

// Task #39 UI correction: a folder's gallery is a destination of its own —
// a full page reached through the course's navigation, not an overlay over
// the course overview. Everything the folder modal served lives here: the
// ordered gallery, the lightbox, and — for course editors — bulk upload with
// per-file progress, per-failure reasons and a retry-failed-only pass.
const props = defineProps<{
	courseName: string
	folderName: string
}>()

// The SAME cache key CourseOutline reads: opening a row and arriving here are
// one shared outline, and the reload below keeps its counts fresh on return.
const outline = createResource({
	url: 'lms.lms.utils.get_course_outline',
	cache: ['course_outline', props.courseName],
	makeParams() {
		return { course: props.courseName, progress: false }
	},
	auto: true,
}) as Resource<OutlineChapter[] | null>

// Course title for the breadcrumbs and the instructor list for the edit
// gate — the same pair of facts CourseOverview derives its editor links from.
const course = createResource({
	url: 'lms.lms.utils.get_course_details',
	makeParams() {
		return { course: props.courseName }
	},
	auto: true,
}) as Resource<CourseDetails | null>

const queue = ref<FolderUploadItem[]>([])
const uploading = ref(false)
const lightboxIndex = ref<number | null>(null)
const deletingImage = ref<string>('')
const fileInput = ref<HTMLInputElement | null>(null)
const dirty = ref(false)

const found = computed(() => findFolder(outline.data, props.folderName))
const folder = computed(() => found.value?.folder ?? null)
const images = ref<OutlineFolderImage[]>([])

// Moderator or this course's instructor — the client mirror of the server's
// can_modify_course, which every folder write re-checks anyway.
const allowEdit = computed<boolean>(
	() =>
		Boolean(user?.data?.is_moderator) ||
		(course.data?.instructors || []).some(
			(instructor) => instructor.name === user?.data?.name
		)
)

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

// Seed the gallery when the folder arrives (or the route param changes);
// local edits afterwards keep their own state until the page is left, so an
// in-flight upload queue is never clobbered by a background outline refresh.
watch(
	found,
	(lookup, previous) => {
		if (!lookup || uploading.value || queue.value.length) return
		if (previous?.folder.name === lookup.folder.name) return
		images.value = [...(lookup.folder.images ?? [])]
		queue.value = []
		lightboxIndex.value = null
	},
	{ immediate: true }
)

watch(
	() => props.courseName,
	() => {
		if (props.courseName) {
			outline.reload()
			course.reload()
		}
	}
)

const breadcrumbs = computed<Breadcrumb[]>(() => {
	const crumbs: Breadcrumb[] = [{ label: __('Courses'), route: { name: 'Courses' } }]
	crumbs.push({
		label: course.data?.title || props.courseName,
		route: {
			name: 'CourseDetail',
			params: { courseName: props.courseName },
		},
	})
	// The section chain that holds the folder — the same chapter context the
	// outline row sits in. Each crumb returns to the course page, where that
	// section's outline lives; on phones the header's back arrow is this route.
	for (const ancestor of found.value?.ancestors ?? []) {
		crumbs.push({
			label: ancestor.title,
			route: {
				name: 'CourseDetail',
				params: { courseName: props.courseName },
			},
		})
	}
	if (folder.value) crumbs.push({ label: folder.value.title })
	return crumbs
})

usePageMeta(() => ({
	title: folder.value?.title,
	icon: brand.favicon,
}))

// The modal deferred its outline reload to its own close; the page defers it
// to leaving, so the outline's folder counts are fresh when the course page
// renders again.
onBeforeRouteLeave(() => {
	if (dirty.value) outline.reload()
})

function backToCourse() {
	router.push({
		name: 'CourseDetail',
		params: { courseName: props.courseName },
	})
}

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
				const response = await uploadFolderImage({
					folder: folder.value.name,
					file: next.file,
					onProgress: (percent) => {
						next.progress = percent
					},
				})
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
</script>
