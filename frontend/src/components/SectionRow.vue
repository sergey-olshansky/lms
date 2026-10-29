<template>
	<Disclosure v-slot="{ open }" :key="section.name" :defaultOpen="defaultOpen">
		<div
			class="w-full rounded-4 py-1"
			:data-section-drop="allowEdit ? section.name : undefined"
			@dragover.capture="outlineDrag?.over($event, section)"
			@dragleave.self="outlineDrag?.leave(section)"
			@drop.capture="outlineDrag?.drop($event, section)"
		>
			<div
				class="outline-row outline-section-header flex w-full min-w-0 items-start gap-2 rounded-4 px-2 py-2 transition-colors hover:bg-surface-gray-1"
				:class="[
					allowEdit && !section.is_scorm_package
						? 'cursor-grab active:cursor-grabbing outline-drag-handle'
						: '',
					currentLevel === 1 && allowEdit && !section.is_scorm_package
						? 'outline-drag-handle-level-1'
						: '',
				]"
				:data-sortable-level="currentLevel"
			>
				<OutlineActionButton
					v-if="allowEdit && !section.is_scorm_package"
					:label="__('Drag to reorder')"
					class="outline-grip mt-0.5 cursor-grab active:cursor-grabbing"
				>
					<span class="lucide-grip-vertical size-4" aria-hidden="true" />
				</OutlineActionButton>
				<DisclosureButton
					v-if="!isRenaming"
					class="outline-disclosure-button flex min-w-0 flex-1 items-start gap-2 text-start"
					@click="toggleSection(open, $event)"
				>
					<span
						:class="{
							'rotate-90': open,
							'rtl:rotate-180': !open,
							hidden: section.is_scorm_package,
							'self-start mt-0.5': inlineSelect,
						}"
						class="outline-disclosure-toggle lucide-chevron-right mt-0.5 size-4 shrink-0 text-ink-gray-9 transform duration-200"
					/>
					<div
						class="min-w-0 flex-1 text-start"
						:class="[
							isScormSectionLocked ? 'cursor-not-allowed opacity-60' : '',
							outlineDrag?.state.hoveredTarget === section.name
								? 'rounded-4 bg-surface-blue-1 ring-2 ring-outline-blue-2'
								: '',
						]"
					>
						<div
							class="whitespace-normal break-words leading-5 text-ink-gray-9"
							:class="currentLevel > 1 ? 'text-sm font-bold' : 'text-base font-semibold'"
							:title="section.title"
							@dblclick.stop="
								allowEdit && !section.is_scorm_package && startRename()
							"
						>
							{{ section.title }}
							<span
								v-if="!section.is_scorm_package && countsLabel"
								class="ms-2 inline whitespace-nowrap align-baseline text-sm font-normal leading-5 text-ink-gray-5"
								data-testid="section-count"
							>
								{{ countsLabel }}
							</span>
						</div>
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
				<TextInput
					v-else
					ref="renameInput"
					v-model="renameValue"
					class="min-w-0 flex-1"
					@click.stop.prevent
					@keydown.enter.stop.prevent="commitRename"
					@keydown.esc.stop.prevent="cancelRename"
					@blur="commitRename"
				/>
				<div
				v-if="allowEdit"
				class="outline-actions ms-auto flex shrink-0 items-center justify-end gap-1"
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
					v-if="!section.is_scorm_package && canAddSection"
					:label="__('Add Section')"
					@click="emit('add-section', section)"
				>
					<span class="lucide-folder-plus size-4" aria-hidden="true" />
				</OutlineActionButton>
				<OutlineActionButton
					v-if="!section.is_scorm_package"
					:label="__('Add Folder')"
					@click="emit('add-folder', section)"
				>
					<span class="lucide-folder size-4" aria-hidden="true" />
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
					@click="emit('delete-chapter', section.name)"
				>
					<span class="lucide-trash-2 size-4" aria-hidden="true" />
				</OutlineActionButton>
			</div>
			</div>
		<DisclosurePanel
			v-if="!section.is_scorm_package"
			class="ms-4 border-s border-outline-gray-2"
			data-testid="section-branch"
		>
			<Draggable
				:data-outline-list="section.name"
				:list="mergedChildren"
				:disabled="!allowEdit || dragDisabled"
				item-key="key"
				:group="{
					name: 'outline-items',
					pull: canTransferChild,
					put: canTransferChild,
				}"
				:draggable="'.chapter-item, .outline-section-row, .outline-lesson-row'"
				:handle="`.outline-drag-handle[data-sortable-level='${
					currentLevel + 1
				}']`"
					:filter="'.scorm-section-row, .outline-folder-row, .outline-actions, .outline-disclosure-toggle, input, textarea'"
				:preventOnFilter="false"
				:move="outlineDrag?.move"
				:data-chapter="section.name"
				@start="outlineDrag?.start($event, section.name)"
				@end="moveChild"
			>
				<template #item="{ element }">
					<div
						v-if="element.kind === 'section'"
						class="outline-section-row"
						:data-outline-key="element.key"
						:style="outlineDrag?.state.hoveredTarget === section.name && outlineDrag?.state.hoveredBefore === element.key ? { boxShadow: 'inset 0 2px 0 var(--outline-blue-2, #2490ef)' } : undefined"
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
							@reorder-section="(payload) => emit('reorder-section', payload)"
							@add-folder="(node) => emit('add-folder', node)"
							@rename-folder="(node) => emit('rename-folder', node)"
							@delete-folder="(node) => emit('delete-folder', node)"
							@open-folder="(node) => emit('open-folder', node)"
							@move-folder="(payload) => emit('move-folder', payload)"
						/>
					</div>
					<div
						v-else-if="element.kind === 'folder'"
						:data-outline-key="element.key"
						:style="outlineDrag?.state.hoveredTarget === section.name && outlineDrag?.state.hoveredBefore === element.key ? { boxShadow: 'inset 0 2px 0 var(--outline-blue-2, #2490ef)' } : undefined"
						:class="childIndentClass"
					>
						<FolderRow
							:folder="element.folder!"
							:courseName="courseName"
							:allowEdit="allowEdit"
							:position="element.rowIndex"
							:siblingCount="mergedChildren.length"
							@open-folder="(node) => emit('open-folder', node)"
							@rename-folder="(node) => emit('rename-folder', node)"
							@delete-folder="(node) => emit('delete-folder', node)"
							@move-folder="
								(direction) =>
									emit('move-folder', {
										folder: element.folder!,
										direction,
										parent: section.name,
									})
							"
						/>
					</div>
					<div
						v-else
						:data-outline-key="element.key"
						:style="outlineDrag?.state.hoveredTarget === section.name && outlineDrag?.state.hoveredBefore === element.key ? { boxShadow: 'inset 0 2px 0 var(--outline-blue-2, #2490ef)' } : undefined"
					class="outline-row outline-lesson-row flex w-full min-w-0 items-start gap-2 rounded-4 px-2 py-2 text-ink-gray-9 transition-colors hover:bg-surface-gray-1"
					:class="[
						childIndentClass,
						allowEdit ? 'cursor-grab active:cursor-grabbing outline-drag-handle' : '',
					]"
					:data-sortable-level="currentLevel + 1"
						data-testid="outline-lesson"
					>
						<OutlineActionButton
							v-if="allowEdit"
							:label="__('Drag to reorder')"
							class="outline-grip mt-0.5 cursor-grab active:cursor-grabbing"
						>
							<span class="lucide-grip-vertical size-4" aria-hidden="true" />
						</OutlineActionButton>
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
							<div class="flex min-w-0 items-start py-1.5 text-sm leading-5">
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
								<span class="min-w-0 flex-1 whitespace-normal break-words">{{
									element.lesson!.title
								}}</span>
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
						<div
							v-if="allowEdit"
							class="outline-actions ms-auto flex shrink-0 items-center justify-end gap-1"
						>
							<OutlineActionButton
								:label="__('Delete Lesson')"
								@click.prevent.stop="
									emit('delete-lesson', {
										lesson: element.lesson!.name,
										chapter: section.name,
									})
								"
							>
								<span class="lucide-trash-2 size-4" aria-hidden="true" />
							</OutlineActionButton>
						</div>
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
		</div>
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
import FolderRow from '@/components/FolderRow.vue'
import OutlineActionButton from '@/components/OutlineActionButton.vue'
import type { OutlineChapter, OutlineFolder, OutlineLesson, SessionUser } from '@/types'
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
	kind: 'lesson' | 'section' | 'folder'
	rowIndex: number
	lesson?: OutlineLesson
	node?: OutlineChapter
	folder?: OutlineFolder
}

type SectionReorderPayload =
	| { section: OutlineChapter; direction: 'up' | 'down' }
	| { section: OutlineChapter; parent: string; idx: number }

// Authoring maximum: 4 structural section levels below the course root; the
// course root itself is not counted and lessons never count.
const MAX_SECTION_DEPTH = 2

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
	'reorder-section': [SectionReorderPayload]
	'add-folder': [OutlineChapter]
	'rename-folder': [OutlineFolder]
	'delete-folder': [OutlineFolder]
	'open-folder': [OutlineFolder]
	'move-folder': [{ folder: OutlineFolder; parent: string; direction: 'up' | 'down' }]
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
	for (const folder of props.section.folders ?? []) {
		children.push({
			key: `folder-${folder.name}`,
			kind: 'folder',
			rowIndex: folder.position ?? children.length,
			folder,
		})
	}
	return children.sort((a, b) => a.rowIndex - b.rowIndex)
})

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
// holds both kinds shows the combined direct counts instead. Folders are
// counted in the folder row itself, not here.
const childIndentClass = computed<string>(() =>
	currentLevel.value === 1 ? 'ps-6' : 'ps-4'
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

// Lesson and section rows share a Sortable group across section levels. Section
// reparenting itself is committed by the guarded section/root drop target.
function canTransferChild(
	_to: unknown,
	_from: unknown,
	element: HTMLElement
): boolean {
	// Root-level sections are wrapped as `.chapter-item`; nested sections and
	// lessons use their own row classes. Accept root rows here too so the shared
	// Sortable group can reach the guarded title drop target inside a section.
	return (
		!element.classList.contains('scorm-section-row') &&
		(element.classList.contains('chapter-item') ||
			element.classList.contains('outline-section-row') ||
			element.classList.contains('outline-lesson-row'))
	)
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

<style scoped>
.outline-actions,
.outline-grip {
	opacity: 0;
	pointer-events: none;
	transition:
		opacity 140ms ease,
		background-color 140ms ease;
}

.outline-row:hover .outline-actions,
.outline-row:hover .outline-grip,
.outline-row:focus-within .outline-actions,
.outline-row:focus-within .outline-grip {
	opacity: 1;
	pointer-events: auto;
}

.outline-row:focus-within {
	background-color: var(--surface-gray-1);
}

@media (hover: none) {
	.outline-actions,
	.outline-grip {
		opacity: 1;
		pointer-events: auto;
	}
}

@media (prefers-reduced-motion: reduce) {
	.outline-actions,
	.outline-grip {
		transition: none;
	}
}
</style>
