<template>
	<div class="p-3 h-full">
		<div
			v-if="!hideHeader && title && (outline.data?.length || allowEdit)"
			class="flex items-center justify-between gap-x-2 mb-4 px-2"
			:class="{
				'sticky top-0 z-10 bg-surface-base border-b px-3 py-2.5 sm:px-5':
					allowEdit,
			}"
		>
			<div
				class="text-lg-semibold leading-5 text-ink-gray-9"
				:class="{ 'font-medium text-p-base': allowEdit }"
			>
				{{ __(title) }}
			</div>
			<Button size="sm" v-if="allowEdit" @click="openChapterForm()">
				<template #prefix>
					<span class="lucide-plus size-4" />
				</template>
				{{ __('Add') }}
			</Button>
		</div>
		<div
			v-if="allowEdit && outline.data && !outline.data.length"
			class="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center text-ink-gray-5 h-full"
		>
			<span class="lucide-book-open size-8" />
			<div class="text-sm">{{ __('No sections yet') }}</div>
			<Button @click="openChapterForm()">
				<template #prefix>
					<span class="lucide-plus size-4" />
				</template>
				{{ __('Create section') }}
			</Button>
		</div>
		<div
			v-else
			:class="{
				'border-2 rounded-5 py-2 px-2': showOutline && outline.data?.length,
			}"
		>
			<Draggable
				:list="outline.data"
				:disabled="!allowEdit || chapterRenaming"
				item-key="name"
				group="chapters"
				:draggable="'.chapter-item'"
				:handle="'.outline-drag-handle-level-1'"
				:filter="'.outline-section-row, .outline-lesson-row, .scorm-section-row'"
				:preventOnFilter="false"
				@end="updateChapterOrder"
			>
				<template #item="{ element: chapter }">
					<div
						class="chapter-item"
						:class="chapter.is_scorm_package ? 'scorm-section-row' : ''"
					>
						<SectionRow
							:section="chapter"
							:level="1"
							:ancestorPath="''"
							:position="chapterIndex(chapter)"
							:siblingCount="outline.data?.length ?? 1"
							:courseName="courseName"
							:allowEdit="allowEdit"
							:dragDisabled="chapterRenaming"
							:inlineSelect="inlineSelect"
							:editorLinks="editorLinks"
							:selectedLessonNumber="selectedLessonNumber"
							:creatingLessonChapter="creatingLessonChapter === chapter.name"
							@select-lesson="(payload) => emit('select-lesson', payload)"
							@edit-chapter="openChapterForm"
							@rename-chapter="renameChapter"
							@renaming-change="(v) => (chapterRenaming = v)"
							@delete-chapter="trashChapter"
							@delete-lesson="
								({ lesson, chapter: chapterName }) =>
									trashLesson(lesson, chapterName)
							"
							@move-lesson="updateOutline"
							@create-lesson="createLessonInline"
							@add-section="openAddSection"
							@move-section="openMoveSection"
							@reorder-section="reorderSection"
						/>
					</div>
				</template>
			</Draggable>
		</div>
		<SectionFormModal
			v-if="allowEdit"
			ref="sectionForm"
			:courseName="courseName"
			:outline="outline"
		/>
		<MoveSectionModal
			v-if="allowEdit"
			ref="moveForm"
			:courseName="courseName"
			:outline="outline"
		/>
	</div>
</template>

<script setup lang="ts">
import { Button, createResource, toast } from 'frappe-ui'
import type { FrappeResourceError } from 'frappe-ui'
import { resourceErrorMessage } from '@/utils/resource'
import { getCurrentInstance, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Draggable from 'vuedraggable'

import SectionRow from '@/components/SectionRow.vue'
import SectionFormModal from '@/components/Modals/SectionFormModal.vue'
import MoveSectionModal from '@/components/Modals/MoveSectionModal.vue'
import { openFormRoute } from '@/composables/useFormRoute'
import {
	flattenLessons,
	forEachLesson,
	parseLessonNumber,
} from '@/utils/courseOutline'
import type { OutlineChapter, OutlineLesson, Resource } from '@/types'

interface DraggableEvent {
	item: {
		__draggable_context: {
			element:
				| OutlineChapter
				| OutlineLesson
				| { kind: 'section'; node?: OutlineChapter }
				| { kind: 'lesson'; lesson?: OutlineLesson }
		}
	}
	from: { dataset: { chapter: string } }
	to: { dataset: { chapter: string } }
	newIndex: number
}

interface DialogAction {
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

const router = useRouter()
const route = useRoute()
// True while a SectionRow is in inline-rename mode; locks section drag.
const chapterRenaming = ref<boolean>(false)
const { $dialog } = getCurrentInstance()!.appContext.config
	.globalProperties as {
	$dialog: DialogFn
}

const emit = defineEmits<{
	'select-lesson': [{ chapterNumber: string; lessonNumber: string }]
	// Keyed delete signals so the parent can match the open lesson precisely. The
	// name is carried per emit (no shared slot), so concurrent deletes can't name
	// the wrong doc and an unrelated reload can't consume the signal.
	'lesson-deleted': [{ lesson: string }]
	'chapter-deleted': [{ chapter: string }]
}>()

// The chapter whose "Add Lesson" button is mid-create (for the button spinner).
const creatingLessonChapter = ref<string>('')
const sectionForm = ref<InstanceType<typeof SectionFormModal> | null>(null)
const moveForm = ref<InstanceType<typeof MoveSectionModal> | null>(null)

const props = withDefaults(
	defineProps<{
		courseName: string
		showOutline?: boolean
		title?: string
		allowEdit?: boolean
		getProgress?: boolean
		completedLesson?: string | null
		inlineSelect?: boolean
		editorLinks?: boolean
		selectedLessonNumber?: string
		hideHeader?: boolean
	}>(),
	{
		showOutline: false,
		title: '',
		allowEdit: false,
		getProgress: false,
		inlineSelect: false,
		editorLinks: false,
		selectedLessonNumber: '',
		completedLesson: null,
		hideHeader: false,
	}
)

defineExpose({ openChapterForm })

const outline = createResource({
	url: 'lms.lms.utils.get_course_outline',
	cache: ['course_outline', props.courseName],
	makeParams() {
		return { course: props.courseName, progress: props.getProgress }
	},
	auto: Boolean(props.courseName),
}) as Resource<OutlineChapter[] | null>

watch(
	() => props.courseName,
	() => {
		if (props.courseName) outline.reload()
	}
)

watch(
	() => props.completedLesson,
	(lessonName) => {
		if (!lessonName || !outline.data) return
		forEachLesson(outline.data, (lesson) => {
			if (lesson.name === lessonName) lesson.is_complete = true
		})
	}
)

const deleteLesson = createResource({
	url: 'lms.lms.api.delete_lesson',
	makeParams(values: { lesson: string; chapter: string }) {
		return values
	},
	onSuccess() {
		outline.reload()
		toast.success(__('Lesson deleted successfully'))
	},
	onError(err: FrappeResourceError) {
		toast.error(resourceErrorMessage(err, __('Error')))
	},
})

const updateLessonIndex = createResource({
	url: 'lms.lms.api.update_lesson_index',
	makeParams(values: {
		lesson: string
		sourceChapter: string
		targetChapter: string
		idx: number
	}) {
		return values
	},
	onSuccess() {
		outline.reload()
		toast.success(__('Lesson moved successfully'))
	},
})

const updateChapterIndex = createResource({
	url: 'lms.lms.api.update_chapter_index',
	makeParams(values: { chapter: string; course: string; idx: number }) {
		return values
	},
	onSuccess() {
		outline.reload()
		toast.success(__('Chapter moved successfully'))
	},
})

const updateSectionIndex = createResource({
	url: 'lms.lms.api.update_section_index',
	makeParams(values: { section: string; parent: string; idx: number }) {
		return values
	},
	onSuccess() {
		outline.reload()
		toast.success(__('Order updated'))
	},
})

const deleteChapter = createResource({
	url: 'lms.lms.api.delete_chapter',
	makeParams(values: { chapter: string }) {
		return values
	},
	onSuccess() {
		outline.reload()
		toast.success(__('Chapter deleted successfully'))
	},
	onError(err: FrappeResourceError) {
		toast.error(resourceErrorMessage(err, __('Error')))
	},
})

const renameChapterResource = createResource({
	url: 'lms.lms.api.upsert_chapter',
	makeParams(values: { chapter: OutlineChapter; title: string }) {
		return {
			name: values.chapter.name,
			title: values.title,
			course: props.courseName,
			is_scorm_package: values.chapter.is_scorm_package ?? 0,
			scorm_package: values.chapter.scorm_package ?? null,
		}
	},
	onSuccess() {
		outline.reload()
		toast.success(__('Chapter renamed successfully'))
	},
	onError(err: FrappeResourceError) {
		outline.reload()
		toast.error(resourceErrorMessage(err, 'Error'))
	},
})

function renameChapter(payload: { chapter: OutlineChapter; title: string }) {
	renameChapterResource.submit(payload)
}

// Inserts the Course Lesson and its chapter reference in one request, so a
// failure on either rolls back atomically: no orphaned lesson. Returns the
// new lesson's docname.
const addLesson = createResource({
	url: 'lms.lms.api.create_lesson',
	makeParams(values: { chapter: string }) {
		return { chapter: values.chapter }
	},
})

// Create the lesson immediately as "Untitled lesson", then open it in the
// editor so the title is edited inline on the lesson itself.
function createLessonInline(payload: {
	chapter: OutlineChapter
	lessonIdx: number
}) {
	creatingLessonChapter.value = payload.chapter.name
	addLesson.submit(
		{ chapter: payload.chapter.name },
		{
			onSuccess(lessonName: string) {
				creatingLessonChapter.value = ''
				outline.reload().then(() => {
					const created = flattenLessons(outline.data).find(
						(l) => l.name === lessonName
					)
					if (created) navigateToLesson(created)
				})
			},
			onError(err: FrappeResourceError) {
				creatingLessonChapter.value = ''
				toast.error(resourceErrorMessage(err, 'Error'))
			},
		}
	)
}

function navigateToLesson(lesson: OutlineLesson) {
	const { chapterNumber, lessonNumber } = parseLessonNumber(lesson.number)
	if (props.inlineSelect) {
		emit('select-lesson', { chapterNumber, lessonNumber })
		return
	}
	if (props.editorLinks) {
		router.push({
			name: 'CourseDetail',
			params: { courseName: props.courseName },
			hash: '#editor',
			query: { editLesson: lesson.number },
		})
	}
}

function trashLesson(lessonName: string, chapterName: string) {
	$dialog({
		title: __('Delete this lesson?'),
		message: __(
			'Deleting this lesson will permanently remove it from the course. This action cannot be undone. Are you sure you want to continue?'
		),
		actions: [
			{
				label: __('Delete'),
				theme: 'red',
				variant: 'solid',
				onClick({ close }) {
					// Per-call onSuccess closes over this lessonName, so the editor is
					// told exactly which lesson went: no shared slot to drift on
					// concurrent deletes. Runs alongside the resource-level reload.
					deleteLesson.submit(
						{ lesson: lessonName, chapter: chapterName },
						{ onSuccess: () => emit('lesson-deleted', { lesson: lessonName }) }
					)
					close()
				},
			},
		],
	})
}

function chapterIndex(chapter: OutlineChapter): number {
	return outline.data?.findIndex((c) => c.name === chapter.name) ?? 0
}

// Subtree counts for the delete confirmation (design §4.7): nested sections
// and lessons going with the section, zero parts omitted.
function subtreeCounts(chapterName: string): { sections: number; lessons: number } {
	const section = (outline.data ?? []).find((c) => c.name === chapterName)
	if (!section) return { sections: 0, lessons: 0 }
	const collect = (nodes: OutlineChapter[], sections: number, lessons: number) => {
		for (const node of nodes) {
			sections += 1
			lessons += node.lessons?.length ?? 0
			;[sections, lessons] = collect(node.sections ?? [], sections, lessons)
		}
		return [sections, lessons] as const
	}
	const [sections, lessons] = collect(section.sections ?? [], 0, 0)
	return { sections, lessons }
}

function trashChapter(chapterName: string) {
	const { sections, lessons } = subtreeCounts(chapterName)
	const parts: string[] = []
	if (sections) {
		parts.push(`${sections} ${__('sections')}`)
	}
	if (lessons) {
		parts.push(`${lessons} ${lessons === 1 ? __('lesson') : __('lessons')}`)
	}
	const message = parts.length
		? __('Will be deleted: {0}, including student progress on those lessons').format(
				parts.join(' and ')
		  )
		: __('This section is empty.')
	$dialog({
		title: __('Delete section?'),
		message,
		actions: [
			{
				label: __('Delete'),
				theme: 'red',
				variant: 'solid',
				onClick({ close }) {
					deleteChapter.submit(
						{ chapter: chapterName },
						{
							onSuccess: () =>
								emit('chapter-deleted', { chapter: chapterName }),
						}
					)
					close()
				},
			},
		],
	})
}

// openFormRoute, not a bare router.push: it stamps the history entry so the
// form's own back/Escape pops that one entry instead of replacing to the parent
// and leaving a duplicate behind.
//
// route.hash and route.query travel with it because CourseDetail reads its
// active tab off the hash and CourseEditor reads the open lesson off the query
// (design doc C2). Dropping either would reset the page behind the open form.
function openChapterForm(chapter: OutlineChapter | null = null) {
	openFormRoute(router, {
		name: 'ChapterForm',
		params: {
			courseName: props.courseName,
			chapterName: chapter?.name ?? 'new',
		},
		hash: route.hash,
		query: { ...route.query },
	})
}

// The create-section dialog's context line: the titles from the first
// level-1 section down to the parent (design §4.3).
function openAddSection(parent: OutlineChapter) {
	const ancestors = findAncestorsByName(parent.name)
	sectionForm.value?.open(parent, ancestors.map((a) => a.title))
}

function findAncestorsByName(name: string): OutlineChapter[] {
	const walk = (nodes: OutlineChapter[], path: OutlineChapter[]): OutlineChapter[] | null => {
		for (const node of nodes) {
			const next = [...path, node]
			if (node.name === name) return next
			const found = walk(node.sections ?? [], next)
			if (found) return found
		}
		return null
	}
	return walk(outline.data ?? [], []) ?? []
}

function openMoveSection(section: OutlineChapter) {
	moveForm.value?.open(section)
}

// Выше/Ниже for a section: level-1 sections reorder within the course's
// chapter list (the same order the top-level drag writes); a nested section
// swaps with its previous/next child row of the parent, whatever kind it is.
function reorderSection(
	payload:
		| { section: OutlineChapter; direction: 'up' | 'down' }
		| { section: OutlineChapter; parent: string; idx: number }
) {
	const { section } = payload
	if ('parent' in payload) {
		updateSectionIndex.submit({
			section: section.name,
			parent: payload.parent,
			idx: payload.idx,
		})
		return
	}
	const { direction } = payload
	const ancestors = findAncestorsByName(section.name)
	const parent = ancestors.length > 1 ? ancestors[ancestors.length - 2] : null
	const delta = direction === 'up' ? -1 : 1
	if (!parent) {
		const index = chapterIndex(section)
		updateChapterIndex.submit({
			chapter: section.name,
			course: props.courseName,
			idx: Math.max(0, index + delta),
		})
		return
	}
	const rowIndex = (section.position ?? 1) - 1
	updateSectionIndex.submit({
		section: section.name,
		parent: parent.name,
		idx: Math.max(0, rowIndex + delta),
	})
}

function updateOutline(e: DraggableEvent) {
	const lesson = e.item.__draggable_context.element as OutlineLesson
	updateLessonIndex.submit({
		lesson: lesson.name,
		sourceChapter: e.from.dataset.chapter,
		targetChapter: e.to.dataset.chapter,
		idx: e.newIndex,
	})
}

function updateChapterOrder(e: DraggableEvent) {
	const chapter = e.item.__draggable_context.element as OutlineChapter
	updateChapterIndex.submit({
		chapter: chapter.name,
		course: props.courseName,
		idx: e.newIndex,
	})
}
</script>
