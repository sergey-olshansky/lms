<template>
	<Disclosure v-slot="{ open }" :key="section.name" :defaultOpen="defaultOpen">
		<DisclosureButton
			class="flex items-center w-full p-2 group"
			:aria-describedby="`section-level-${section.name}`"
		>
			<span
				:class="{
					'rotate-90': open,
					'rtl:rotate-180': !open,
					hidden: section.is_scorm_package,
					'self-start mt-0.5': inlineSelect,
				}"
				class="lucide-chevron-right size-4 text-ink-gray-9 transform duration-200"
			/>
			<div
				class="ms-2 min-w-0 flex-1 text-start"
				:class="[
					inlineSelect ? '' : 'flex items-baseline justify-between gap-3',
					isScormSectionLocked ? 'cursor-not-allowed opacity-60' : '',
				]"
				@click="redirectToSection"
			>
				<TextInput
					v-if="isRenaming"
					ref="renameInput"
					v-model="renameValue"
					class="w-full"
					@click.stop.prevent
					@keydown.enter.stop.prevent="commitRename"
					@keydown.esc.stop.prevent="cancelRename"
					@blur="commitRename"
				/>
				<div
					v-else
					class="truncate text-base-medium leading-5 text-ink-gray-9"
					:class="{ 'text-sm': level > 1 }"
					:title="section.title"
					@dblclick="allowEdit && !section.is_scorm_package && startRename()"
				>
					{{ section.title }}
				</div>
			</div>
			<div class="flex ms-3 items-center gap-x-4 shrink-0">
				<span
					v-if="!section.is_scorm_package && onlyLessons && section.lessons?.length"
					class="text-sm text-ink-gray-5"
					:class="{
						'group-hover:hidden [@media(hover:none)]:hidden': allowEdit,
					}"
				>
					{{ section.lessons.length }}
				</span>
				<span
					v-else-if="!section.is_scorm_package && (section.section_count || section.sections?.length)"
					class="text-sm text-ink-gray-5"
					:class="{
						'group-hover:hidden [@media(hover:none)]:hidden': allowEdit,
					}"
				>
					{{ countsLabel }}
				</span>
				<template v-if="allowEdit">
					<Tooltip
						:text="__('Add Lesson')"
						side="bottom"
					>
						<span
							v-if="!section.is_scorm_package"
							@click.prevent="addLesson"
							class="lucide-plus size-4 text-ink-gray-9 invisible group-hover:visible [@media(hover:none)]:visible"
						/>
					</Tooltip>
					<Tooltip
						:text="
							canAddSection
								? __('Add Section')
								: __('Maximum depth reached — 4 section levels')
						"
						side="bottom"
					>
						<span
							v-if="!section.is_scorm_package"
							@click.prevent="canAddSection && emit('add-section', section)"
							class="lucide-folder-plus size-4 text-ink-gray-9 invisible group-hover:visible [@media(hover:none)]:visible"
							:class="{ 'opacity-40': !canAddSection }"
							:aria-disabled="canAddSection ? undefined : 'true'"
							role="button"
						/>
					</Tooltip>
					<span
						v-if="canAddSection === false"
						:id="`section-level-${section.name}`"
						class="sr-only"
					>
						{{ __('Maximum depth reached — 4 section levels') }}
					</span>
					<Tooltip :text="__('Move up')" side="bottom">
						<span
							v-if="!section.is_scorm_package"
							@click.prevent="reorderSection('up')"
							class="lucide-arrow-up size-4 text-ink-gray-9 invisible group-hover:visible [@media(hover:none)]:visible"
							:class="{ 'opacity-40': isFirstSibling }"
							:aria-disabled="isFirstSibling ? 'true' : undefined"
							role="button"
						/>
					</Tooltip>
					<Tooltip :text="__('Move down')" side="bottom">
						<span
							v-if="!section.is_scorm_package"
							@click.prevent="reorderSection('down')"
							class="lucide-arrow-down size-4 text-ink-gray-9 invisible group-hover:visible [@media(hover:none)]:visible"
							:class="{ 'opacity-40': isLastSibling }"
							:aria-disabled="isLastSibling ? 'true' : undefined"
							role="button"
						/>
					</Tooltip>
					<Tooltip :text="__('Move to…')" side="bottom">
						<span
							v-if="!section.is_scorm_package"
							@click.prevent="emit('move-section', section)"
							class="lucide-folder-input size-4 text-ink-gray-9 invisible group-hover:visible [@media(hover:none)]:visible"
						/>
					</Tooltip>
					<Tooltip :text="__('Rename')" side="bottom">
						<span
							v-if="!section.is_scorm_package"
							@click.prevent="startRename"
							class="lucide-pen-line size-4 text-ink-gray-9 invisible group-hover:visible [@media(hover:none)]:visible"
						/>
					</Tooltip>
					<Tooltip :text="__('Edit Chapter')" side="bottom">
						<span
							v-if="section.is_scorm_package"
							@click.prevent="emit('edit-chapter', section)"
							class="lucide-file-pen-line size-4 text-ink-gray-9 invisible group-hover:visible [@media(hover:none)]:visible"
						/>
					</Tooltip>
					<Tooltip :text="__('Delete Chapter')" side="bottom">
						<span
							@click.prevent="emit('delete-chapter', section.name)"
							class="lucide-trash-2 size-4 text-ink-red-5 hidden group-hover:inline-block [@media(hover:none)]:inline-block"
						/>
					</Tooltip>
				</template>
			</div>
			<template v-if="isScormSectionLocked">
				<span
					class="lucide-lock-keyhole size-4 text-ink-gray-4"
					:title="__('Complete the previous lessons to unlock this one')"
					aria-hidden="true"
				/>
				<span class="sr-only">{{ __('Locked') }}</span>
			</template>
			<span
				v-else-if="section.is_scorm_package && isScormSectionComplete"
				class="lucide-check size-4 text-ink-green-8"
			/>
		</DisclosureButton>
		<DisclosurePanel v-if="!section.is_scorm_package">
			<Draggable
				:list="mergedChildren"
				:disabled="!allowEdit"
				item-key="key"
				group="items"
				:filter="'.outline-section-row'"
				:preventOnFilter="false"
				:data-chapter="section.name"
				@end="(e: DraggableEvent) => emit('move-lesson', e)"
			>
				<template #item="{ element }">
					<div
						v-if="element.kind === 'section'"
						class="outline-section-row"
						:class="childIndentClass"
					>
						<SectionRow
							:section="element.node!"
							:level="level + 1"
							:ancestorPath="sectionPath"
							:position="element.rowIndex"
							:siblingCount="mergedChildren.length"
							:courseName="courseName"
							:allowEdit="allowEdit"
							:inlineSelect="inlineSelect"
							:editorLinks="editorLinks"
							:selectedLessonNumber="selectedLessonNumber"
							:creatingLesson="creatingLessonChapter === element.node!.name"
							@select-lesson="(payload) => emit('select-lesson', payload)"
							@edit-chapter="(chapter) => emit('edit-chapter', chapter)"
							@rename-chapter="(payload) => emit('rename-chapter', payload)"
							@renaming-change="(v) => emit('renaming-change', v)"
							@delete-chapter="(name) => emit('delete-chapter', name)"
							@delete-lesson="(payload) => emit('delete-lesson', payload)"
							@move-lesson="(e) => emit('move-lesson', e)"
							@create-lesson="(payload) => emit('create-lesson', payload)"
							@add-section="(node) => emit('add-section', node)"
							@move-section="(node) => emit('move-section', node)"
							@reorder-section="(payload) => emit('reorder-section', payload)"
						/>
					</div>
					<div
						v-else
						class="py-2 pe-4 text-ink-gray-9"
						data-testid="outline-lesson"
						:class="[
							childIndentClass,
							isActiveLesson(element.lesson!.number)
								? 'bg-surface-gray-3 rounded-5'
								: '',
						]"
					>
						<component
							:is="inlineSelect || element.lesson!.locked ? 'div' : 'router-link'"
							:to="
								inlineSelect || element.lesson!.locked
									? undefined
									: lessonRoute(element.lesson!)
							"
							:class="
								element.lesson!.locked
									? 'cursor-not-allowed opacity-60'
									: inlineSelect
									? 'cursor-pointer'
									: ''
							"
							@click="onLessonClick(element.lesson!)"
						>
							<div class="flex items-center text-sm leading-5 group">
								<span
									v-if="element.lesson!.icon === 'icon-youtube'"
									class="lucide-monitor-play h-4 w-4 me-2"
								/>
								<span
									v-else-if="element.lesson!.icon === 'icon-quiz'"
									class="lucide-help-circle h-4 w-4 me-2"
								/>
								<span
									v-else-if="element.lesson!.icon === 'icon-assignment'"
									class="lucide-notebook-pen h-4 w-4 me-2"
								/>
								<span
									v-else-if="element.lesson!.icon === 'icon-code'"
									class="lucide-square-code h-4 w-4 me-2"
								/>
								<span
									v-else-if="element.lesson!.icon === 'icon-list'"
									class="lucide-file-text h-4 w-4 text-ink-gray-9 me-2"
								/>
								{{ element.lesson!.title }}
								<div v-if="allowEdit" class="ms-auto flex items-center gap-2">
									<span
										@click.prevent="
											emit('delete-lesson', {
												lesson: element.lesson!.name,
												chapter: section.name,
											})
										"
										class="lucide-trash-2 h-4 w-4 text-ink-red-5 invisible group-hover:visible [@media(hover:none)]:visible"
									/>
								</div>
								<template v-if="element.lesson!.locked">
									<span
										class="lucide-lock-keyhole h-4 w-4 text-ink-gray-4 ms-2"
										:title="
											__('Complete the previous lesson to unlock this one')
										"
										aria-hidden="true"
									/>
									<span class="sr-only">{{ __('Locked') }}</span>
								</template>
								<span
									v-else-if="element.lesson!.is_complete"
									class="lucide-check h-4 w-4 text-ink-green-8 ms-2"
								/>
							</div>
						</component>
					</div>
				</template>
			</Draggable>
			<div
				v-if="allowEdit && !mergedChildren.length"
				class="flex items-center gap-3 py-2"
				:class="childIndentClass"
				data-testid="empty-section"
			>
				<span class="text-sm text-ink-gray-5">{{ __('Empty section') }}</span>
			</div>
			<div v-if="allowEdit" class="flex mt-2 mb-4 gap-2" :class="childIndentClass">
				<Button :loading="creatingLesson" @click="addLesson">
					<template #prefix>
						<span class="lucide-plus size-4" />
					</template>
					{{ __('Add Lesson') }}
				</Button>
				<Button v-if="canAddSection" @click="emit('add-section', section)">
					<template #prefix>
						<span class="lucide-folder-plus size-4" />
					</template>
					{{ __('Add Section') }}
				</Button>
			</div>
		</DisclosurePanel>
	</Disclosure>
</template>

<script setup lang="ts">
import { Button, TextInput, Tooltip, toast } from 'frappe-ui'
import { computed, inject, nextTick, ref, watch } from 'vue'
import Draggable from 'vuedraggable'
import { Disclosure, DisclosureButton, DisclosurePanel } from '@headlessui/vue'
import { useRoute, useRouter } from 'vue-router'
import type { RouteLocationRaw } from 'vue-router'
import type { InputExposed } from 'frappe-ui'
import SectionRow from '@/components/SectionRow.vue'
import type { OutlineChapter, OutlineLesson, SessionUser } from '@/types'
import { parseLessonNumber } from '@/utils/courseOutline'

interface DraggableEvent {
	item: { __draggable_context: { element: OutlineChapter | OutlineLesson } }
	from: { dataset: { chapter: string } }
	to: { dataset: { chapter: string } }
	newIndex: number
}

interface MergedChild {
	key: string
	kind: 'lesson' | 'section'
	rowIndex: number
	lesson?: OutlineLesson
	node?: OutlineChapter
}

// Authoring maximum: 4 structural section levels below the course root; the
// course root itself is not counted and lessons never count.
const MAX_SECTION_DEPTH = 4

const props = withDefaults(
	defineProps<{
		section: OutlineChapter
		level?: number
		ancestorPath?: string
		position?: number
		siblingCount?: number
		courseName: string
		allowEdit?: boolean
		inlineSelect?: boolean
		editorLinks?: boolean
		selectedLessonNumber?: string
		creatingLesson?: boolean
		creatingLessonChapter?: string
	}>(),
	{
		level: 1,
		ancestorPath: '',
		position: 0,
		siblingCount: 1,
		allowEdit: false,
		inlineSelect: false,
		editorLinks: false,
		selectedLessonNumber: '',
		creatingLesson: false,
		creatingLessonChapter: '',
	}
)

const emit = defineEmits<{
	'select-lesson': [{ chapterNumber: string; lessonNumber: string }]
	'edit-chapter': [OutlineChapter]
	'rename-chapter': [{ chapter: OutlineChapter; title: string }]
	'renaming-change': [boolean]
	'delete-chapter': [string]
	'delete-lesson': [{ lesson: string; chapter: string }]
	'move-lesson': [DraggableEvent]
	'create-lesson': [{ chapter: OutlineChapter; lessonIdx: number }]
	'add-section': [OutlineChapter]
	'move-section': [OutlineChapter]
	'reorder-section': [{ section: OutlineChapter; direction: 'up' | 'down' }]
}>()

const route = useRoute()
const router = useRouter()
const user = inject<SessionUser>('$user')!

const isRenaming = ref<boolean>(false)
const renameValue = ref<string>('')
const renameInput = ref<InputExposed | null>(null)

// Tell the parent outline to lock section dragging while a name is being
// edited, so a stray drag can't fire mid-rename.
watch(isRenaming, (renaming) => emit('renaming-change', renaming))

function startRename(): void {
	renameValue.value = props.section.title
	isRenaming.value = true
	nextTick(() => {
		renameInput.value?.focus()
	})
}

function commitRename(): void {
	if (!isRenaming.value) return
	isRenaming.value = false
	const title = renameValue.value.trim()
	if (!title || title === props.section.title) return
	emit('rename-chapter', { chapter: props.section, title })
}

function cancelRename(): void {
	isRenaming.value = false
	renameValue.value = props.section.title
}

// The dash-joined sibling positions from the first level-1 section down to
// this one; a lesson number is this path plus the lesson's own position.
const sectionPath = computed<string>(() =>
	props.ancestorPath
		? `${props.ancestorPath}-${props.section.idx}`
		: `${props.section.idx}`
)

// The server computes levels by traversal (design §3); the prop is only a
// fallback for outline data that predates the field.
const currentLevel = computed<number>(() => props.section.level ?? props.level)

// Sections on the path to the open lesson expand on (re)mount; the student
// view carries the active lesson in route params, the in-page editor in
// ?editLesson, with selectedLessonNumber as a fallback. With nothing active,
// only the first level-1 section opens.
const defaultOpen = computed<boolean>(() => {
	const editLesson =
		typeof route.query.editLesson === 'string' ? route.query.editLesson : ''
	const active = String(
		route.params.chapterNumber || editLesson || props.selectedLessonNumber || ''
	)
	if (!active) return props.section.idx === 1 && currentLevel.value === 1
	const segments = active.split('-')
	const pathSegments = sectionPath.value.split('-')
	if (pathSegments.length > segments.length) return false
	return pathSegments.every((segment, i) => segment === segments[i])
})

const canAddSection = computed<boolean>(() => currentLevel.value < MAX_SECTION_DEPTH)

const isFirstSibling = computed<boolean>(() => (props.position ?? 0) <= 0)
const isLastSibling = computed<boolean>(
	() => (props.position ?? 0) >= (props.siblingCount ?? 1) - 1
)

// Direct children in the section's single manual order: lessons and nested
// sections interleaved by the child-table row the server reports for each.
const mergedChildren = computed<MergedChild[]>(() => {
	const children: MergedChild[] = []
	for (const lesson of props.section.lessons ?? []) {
		children.push({
			key: `lesson-${lesson.name}`,
			kind: 'lesson',
			rowIndex: lesson.position ?? children.length,
			lesson,
		})
	}
	for (const node of props.section.sections ?? []) {
		children.push({
			key: `section-${node.name}`,
			kind: 'section',
			rowIndex: node.position ?? children.length,
			node,
		})
	}
	return children.sort((a, b) => a.rowIndex - b.rowIndex)
})

const onlyLessons = computed<boolean>(
	() => !props.section.sections?.length
)

const countsLabel = computed<string>(() => {
	const sections = props.section.section_count ?? props.section.sections?.length ?? 0
	const lessons = props.section.lesson_count ?? props.section.lessons?.length ?? 0
	const parts: string[] = []
	if (sections) {
		parts.push(`${sections} ${sections === 1 ? __('section') : __('sections')}`)
	}
	if (lessons) {
		parts.push(`${lessons} ${lessons === 1 ? __('lesson') : __('lessons')}`)
	}
	return parts.join(' · ')
})

// Legacy chapters keep their lesson-only number badge (above); a section that
// holds both kinds shows the combined direct counts instead.
const childIndentClass = computed<string>(() =>
	currentLevel.value === 1 ? 'ps-8' : 'ps-4'
)

const isScormSectionComplete = computed<boolean>(() =>
	Boolean(
		props.section.lessons?.length &&
			props.section.lessons.every((l) => l.is_complete)
	)
)

// A SCORM section has no DisclosurePanel, so it never reaches the per-lesson
// lock affordance below: without this it looks identical to an open one and
// the student only learns it is locked after SCORMChapter.vue bounces them
// back. Same rule as that page's own isLocked.
const isScormSectionLocked = computed<boolean>(() =>
	Boolean(
		props.section.is_scorm_package &&
			props.section.lessons?.length &&
			props.section.lessons.every((l) => l.locked)
	)
)

function isActiveLesson(lessonNumber: string): boolean {
	if (props.inlineSelect) return props.selectedLessonNumber === lessonNumber
	const { chapterNumber, lessonNumber: lesson } = parseLessonNumber(lessonNumber)
	return (
		route.params.chapterNumber == chapterNumber &&
		route.params.lessonNumber == lesson
	)
}

// Admins (editorLinks) deep-link into the in-page editor; everyone else
// opens the student view.
function lessonRoute(lesson: OutlineLesson): RouteLocationRaw {
	const { chapterNumber, lessonNumber } = parseLessonNumber(lesson.number)
	if (props.editorLinks) {
		return {
			name: 'CourseDetail',
			params: { courseName: props.courseName },
			hash: '#editor',
			query: { editLesson: lesson.number },
		}
	}
	return {
		name: 'Lesson',
		params: { courseName: props.courseName, chapterNumber, lessonNumber },
	}
}

function onLessonClick(lesson: OutlineLesson) {
	if (lesson.locked) return
	if (!props.inlineSelect) return
	const { chapterNumber, lessonNumber } = parseLessonNumber(lesson.number)
	emit('select-lesson', { chapterNumber, lessonNumber })
}

function addLesson() {
	emit('create-lesson', {
		chapter: props.section,
		lessonIdx: (props.section.lessons?.length ?? 0) + 1,
	})
}

function reorderSection(direction: 'up' | 'down') {
	if (direction === 'up' && isFirstSibling.value) return
	if (direction === 'down' && isLastSibling.value) return
	emit('reorder-section', { section: props.section, direction })
}

function redirectToSection() {
	if (!props.section.is_scorm_package) return
	;(event as Event | undefined)?.preventDefault()
	if (isScormSectionLocked.value) return
	if (!user.data) {
		toast.success(__('Please enroll for this course to view this lesson'))
		return
	}
	router.push({
		name: 'SCORMChapter',
		params: {
			courseName: props.courseName,
			chapterName: props.section.name,
		},
	})
}
</script>
