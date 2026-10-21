<template>
	<Disclosure v-slot="{ open }" :key="section.name" :defaultOpen="defaultOpen">
		<div class="w-full rounded-4 px-2 py-2">
			<div class="flex w-full items-start gap-2">
				<DisclosureButton
					class="flex min-w-0 flex-1 items-start gap-2 text-start"
					:aria-describedby="
						canAddSection === false
							? `section-level-${section.name}`
							: undefined
					"
					@click="toggleSection(open, $event)"
				>
					<span
						:class="{
							'rotate-90': open,
							'rtl:rotate-180': !open,
							hidden: section.is_scorm_package,
							'self-start mt-0.5': inlineSelect,
						}"
						class="lucide-chevron-right mt-0.5 size-4 shrink-0 text-ink-gray-9 transform duration-200"
					/>
					<div
						v-if="allowEdit && !section.is_scorm_package"
						class="lucide-grip-vertical outline-drag-handle mt-0.5 size-4 shrink-0 cursor-grab text-ink-gray-5 active:cursor-grabbing"
						:class="currentLevel === 1 ? 'outline-drag-handle-level-1' : ''"
						:data-sortable-level="currentLevel"
						:title="__('Drag to reorder')"
						aria-hidden="true"
					/>
					<div
						class="min-w-0 flex-1 text-start"
						:class="[
							isScormSectionLocked ? 'cursor-not-allowed opacity-60' : '',
							outlineDrag?.state.hoveredTarget === section.name
								? 'rounded-4 bg-surface-blue-1 ring-2 ring-outline-blue-2'
								: '',
						]"
						:data-section-drop="allowEdit ? section.name : undefined"
						@dragover="outlineDrag?.over($event, section)"
						@dragleave="outlineDrag && (outlineDrag.state.hoveredTarget = null)"
						@drop="outlineDrag?.drop($event, section)"
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
							class="whitespace-normal break-words text-base-medium leading-5 text-ink-gray-9"
							:class="{ 'text-sm': level > 1 }"
							:title="section.title"
							@dblclick="
								allowEdit && !section.is_scorm_package && startRename()
							"
						>
							{{ section.title }}
						</div>
					</div>
					<div
						class="ms-2 shrink-0 self-start text-sm text-ink-gray-5"
						data-testid="section-count"
					>
						<span
							v-if="
								!section.is_scorm_package &&
								onlyLessons &&
								section.lessons?.length
							"
						>
							{{ section.lessons.length }}
						</span>
						<span
							v-else-if="
								!section.is_scorm_package &&
								(section.section_count || section.sections?.length)
							"
						>
							{{ countsLabel }}
						</span>
					</div>
					<template v-if="isScormSectionLocked">
						<span
							class="lucide-lock-keyhole mt-0.5 size-4 shrink-0 text-ink-gray-4"
							:title="__('Complete the previous lessons to unlock this one')"
							aria-hidden="true"
						/>
						<span class="sr-only">{{ __('Locked') }}</span>
					</template>
					<span
						v-else-if="section.is_scorm_package && isScormSectionComplete"
						class="lucide-check mt-0.5 size-4 shrink-0 text-ink-green-8"
					/>
				</DisclosureButton>
			</div>
			<div
				v-if="allowEdit"
				class="ms-8 mt-1 flex flex-wrap items-center gap-1"
				role="group"
				:aria-label="section.title"
			>
				<OutlineActionButton
					v-if="!section.is_scorm_package"
					:label="__('Add Lesson')"
					:disabled="creatingLesson"
					:busy="creatingLesson"
					@click="addLesson"
				>
					<span class="lucide-plus size-4" aria-hidden="true" />
				</OutlineActionButton>
				<OutlineActionButton
					v-if="!section.is_scorm_package"
					:label="
						canAddSection
							? __('Add Section')
							: __('Maximum depth reached — 4 section levels')
					"
					:disabled="!canAddSection"
					@click="emit('add-section', section)"
				>
					<span class="lucide-folder-plus size-4" aria-hidden="true" />
				</OutlineActionButton>
				<OutlineActionButton
					v-if="!section.is_scorm_package"
					:label="__('Move up')"
					:disabled="isFirstSibling"
					@click="reorderSection('up')"
				>
					<span class="lucide-arrow-up size-4" aria-hidden="true" />
				</OutlineActionButton>
				<OutlineActionButton
					v-if="!section.is_scorm_package"
					:label="__('Move down')"
					:disabled="isLastSibling"
					@click="reorderSection('down')"
				>
					<span class="lucide-arrow-down size-4" aria-hidden="true" />
				</OutlineActionButton>
				<OutlineActionButton
					v-if="!section.is_scorm_package"
					:label="__('Move to…')"
					@click="emit('move-section', section)"
				>
					<span class="lucide-folder-input size-4" aria-hidden="true" />
				</OutlineActionButton>
				<OutlineActionButton
					v-if="!section.is_scorm_package"
					:label="__('Rename')"
					@click="startRename"
				>
					<span class="lucide-pen-line size-4" aria-hidden="true" />
				</OutlineActionButton>
				<OutlineActionButton
					v-if="section.is_scorm_package"
					:label="__('Edit Chapter')"
					@click="emit('edit-chapter', section)"
				>
					<span class="lucide-file-pen-line size-4" aria-hidden="true" />
				</OutlineActionButton>
				<OutlineActionButton
					:label="__('Delete Chapter')"
					danger
					@click="emit('delete-chapter', section.name)"
				>
					<span class="lucide-trash-2 size-4" aria-hidden="true" />
				</OutlineActionButton>
				<span
					v-if="!canAddSection"
					:id="`section-level-${section.name}`"
					class="sr-only"
					>{{ __('Maximum depth reached — 4 section levels') }}</span
				>
			</div>
		</div>
		<DisclosurePanel
			v-if="!section.is_scorm_package"
			class="ms-4 border-s border-outline-gray-2"
			data-testid="section-branch"
		>
			<Draggable
				:list="mergedChildren"
				:disabled="!allowEdit || dragDisabled"
				item-key="key"
				:group="{
					name: 'outline-items',
					pull: canTransferChild,
					put: canTransferChild,
				}"
				:draggable="'.outline-section-row, .outline-lesson-row'"
				:handle="`.outline-drag-handle[data-sortable-level='${
					currentLevel + 1
				}']`"
				:filter="'.scorm-section-row'"
				:preventOnFilter="false"
				:data-chapter="section.name"
				@start="outlineDrag?.start($event, section.name)"
				@end="moveChild"
			>
				<template #item="{ element }">
					<div
						v-if="element.kind === 'section'"
						class="outline-section-row"
						:class="[
							childIndentClass,
							element.node!.is_scorm_package ? 'scorm-section-row' : '',
						]"
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
							:dragDisabled="dragDisabled"
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
						class="outline-lesson-row flex items-center py-2 pe-4 text-ink-gray-9"
						data-testid="outline-lesson"
						:class="childIndentClass"
					>
						<span
							v-if="allowEdit"
							class="lucide-grip-vertical outline-drag-handle me-2 size-4 shrink-0 cursor-grab text-ink-gray-5 active:cursor-grabbing"
							:data-sortable-level="currentLevel + 1"
							:title="__('Drag to reorder')"
							aria-hidden="true"
						/>
						<component
							:is="inlineSelect || element.lesson!.locked ? 'div' : 'router-link'"
							:to="
								inlineSelect || element.lesson!.locked
									? undefined
									: lessonRoute(element.lesson!)
							"
							:class="[
								'min-w-0 flex-1',
								element.lesson!.locked
									? 'cursor-not-allowed opacity-60'
									: inlineSelect
									? 'cursor-pointer'
									: '',
								isActiveLesson(element.lesson!.number)
									? 'bg-surface-gray-3 rounded-5'
									: '',
							]"
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
									<OutlineActionButton
										:label="__('Delete Lesson')"
										danger
										@click.prevent.stop="
											emit('delete-lesson', {
												lesson: element.lesson!.name,
												chapter: section.name,
											})
										"
										class="invisible group-hover:visible group-focus-within:visible [@media(hover:none)]:visible"
									>
										<span class="lucide-trash-2 size-4" aria-hidden="true" />
									</OutlineActionButton>
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
		</DisclosurePanel>
	</Disclosure>
</template>

<script setup lang="ts">
import { TextInput, toast } from 'frappe-ui'
import { computed, inject, nextTick, ref, watch } from 'vue'
import Draggable from 'vuedraggable'
import { Disclosure, DisclosureButton, DisclosurePanel } from '@headlessui/vue'
import { useRoute, useRouter } from 'vue-router'
import type { RouteLocationRaw } from 'vue-router'
import type { InputExposed } from 'frappe-ui'
import SectionRow from '@/components/SectionRow.vue'
import OutlineActionButton from '@/components/OutlineActionButton.vue'
import type { OutlineChapter, OutlineLesson, SessionUser } from '@/types'
import { parseLessonNumber } from '@/utils/courseOutline'
import { courseOutlineDragKey } from '@/composables/courseOutlineDrag'
import {
	courseOutlineExpansionKey,
	isSectionExpanded,
	rememberSectionExpansion,
} from '@/utils/courseOutlineExpansion'

interface DraggableEvent {
	item: {
		__draggable_context: {
			element: OutlineChapter | OutlineLesson | MergedChild
		}
	}
	from: { dataset: { chapter: string } }
	to: { dataset: { chapter: string } }
	newIndex: number
	oldIndex?: number
	originalEvent?: Event
}

interface MergedChild {
	key: string
	kind: 'lesson' | 'section'
	rowIndex: number
	lesson?: OutlineLesson
	node?: OutlineChapter
}

type SectionReorderPayload =
	| { section: OutlineChapter; direction: 'up' | 'down' }
	| { section: OutlineChapter; parent: string; idx: number }

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
		dragDisabled?: boolean
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
		dragDisabled: false,
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
	'reorder-section': [SectionReorderPayload]
}>()

const route = useRoute()
const router = useRouter()
const user = inject<SessionUser>('$user')!
const outlineDrag = inject(courseOutlineDragKey, null)

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

const expansionKey = computed(() =>
	courseOutlineExpansionKey(props.courseName, user.data?.name ?? 'Guest')
)
// New sections start closed. Reopening a parent restores each child's own
// choice instead of expanding the whole active lesson path on every remount.
const defaultOpen = isSectionExpanded(expansionKey.value, props.section.name)

function toggleSection(wasOpen: boolean, event: MouseEvent): void {
	if (!props.section.is_scorm_package) {
		rememberSectionExpansion(expansionKey.value, props.section.name, !wasOpen)
	}
	redirectToSection(event)
}

const canAddSection = computed<boolean>(
	() => currentLevel.value < MAX_SECTION_DEPTH
)

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

const onlyLessons = computed<boolean>(() => !props.section.sections?.length)

const countsLabel = computed<string>(() => {
	const sections =
		props.section.section_count ?? props.section.sections?.length ?? 0
	const lessons =
		props.section.lesson_count ?? props.section.lessons?.length ?? 0
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
	currentLevel.value === 1 ? 'ps-4' : 'ps-2'
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
	const { chapterNumber, lessonNumber: lesson } =
		parseLessonNumber(lessonNumber)
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
	if (props.creatingLesson) return
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

// Sections reorder inside their own parent; lesson rows retain the existing
// cross-section transfer behavior. Reparenting a section uses the target dialog.
function canTransferChild(
	_to: unknown,
	_from: unknown,
	element: HTMLElement
): boolean {
	return element.classList.contains('outline-lesson-row')
}

function moveChild(event: DraggableEvent) {
	if (outlineDrag?.finish(event)) return
	if (!Number.isInteger(event.newIndex)) return
	if (event.from === event.to && event.oldIndex === event.newIndex) return
	const child = event.item.__draggable_context.element
	if ('kind' in child && child.kind === 'section' && child.node) {
		emit('reorder-section', {
			section: child.node,
			parent: props.section.name,
			idx: event.newIndex,
		})
		return
	}
	if ('kind' in child && child.kind === 'lesson' && child.lesson) {
		emit('move-lesson', {
			...event,
			item: {
				...event.item,
				__draggable_context: {
					...event.item.__draggable_context,
					element: child.lesson,
				},
			},
		})
	}
}

function redirectToSection(event?: MouseEvent) {
	if (!props.section.is_scorm_package) return
	event?.preventDefault()
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
