<template>
	<Disclosure v-slot="{ open }" :defaultOpen="defaultOpen">
		<DisclosureButton
			class="w-full flex items-center justify-between rounded-4 px-3 py-2 hover:bg-surface-gray-2 text-start"
		>
			<div
				class="flex items-center gap-2 min-w-0"
				:class="
					level > 1
						? 'text-sm leading-5 text-ink-gray-8'
						: 'text-base-medium leading-5 text-ink-gray-9'
				"
			>
				<ChevronDown
					class="size-4 stroke-1.5 shrink-0 transition-transform"
					:class="{ '-rotate-90': !open }"
				/>
				<span class="truncate">{{ section.title }}</span>
			</div>
			<span
				v-if="badgeCount"
				class="text-sm text-ink-gray-5 shrink-0"
			>
				{{ badgeCount }}
			</span>
		</DisclosureButton>
		<DisclosurePanel>
			<ul class="list-none">
				<template v-for="child in mergedChildren" :key="child.key">
					<li v-if="child.kind === 'section'" class="ps-2 sm:ps-3">
						<SidebarSection
							:section="child.node"
							:level="level + 1"
							:ancestorPath="sectionPath"
							:courseName="courseName"
							:selectedLessonNumber="selectedLessonNumber"
							:inlineSelect="inlineSelect"
							:studentViewQuery="studentViewQuery"
							@select-lesson="(payload) => emit('select-lesson', payload)"
						/>
					</li>
					<li v-else>
						<component
							:is="
								child.lesson.locked
									? 'div'
									: inlineSelect
									? 'button'
									: 'router-link'
							"
							:type="!child.lesson.locked && inlineSelect ? 'button' : undefined"
							:to="
								child.lesson.locked || inlineSelect
									? undefined
									: {
											name: 'Lesson',
											params: lessonParams(child.lesson),
											query: studentViewQuery,
									  }
							"
							class="flex w-full items-center gap-3 rounded-4 ps-9 pe-3 py-2 text-start text-sm leading-5 text-ink-gray-8 hover:bg-surface-gray-2"
							:class="[
								child.lesson.locked
									? 'cursor-not-allowed opacity-60'
									: inlineSelect
									? 'cursor-pointer'
									: '',
								isActive(child.lesson.number)
									? 'bg-surface-gray-2 text-ink-gray-9'
									: '',
							]"
							@click="onLessonClick(child.lesson)"
						>
							<component
								:is="iconFor(child.lesson.icon)"
								class="size-4 stroke-1.5 shrink-0 text-ink-gray-7"
							/>
							<span class="truncate flex-1">{{ child.lesson.title }}</span>
							<template v-if="child.lesson.locked">
								<LockKeyhole
									class="size-4 stroke-1.5 shrink-0 text-ink-gray-4"
									aria-hidden="true"
								/>
								<span class="sr-only">{{ __('Locked') }}</span>
							</template>
							<CircleCheck
								v-else-if="child.lesson.is_complete"
								class="size-4 stroke-1.5 shrink-0 text-ink-green-8 fill-none"
							/>
							<Circle
								v-else
								class="size-4 stroke-1.5 shrink-0 text-ink-gray-4"
							/>
						</component>
					</li>
				</template>
			</ul>
		</DisclosurePanel>
	</Disclosure>
</template>

<script setup>
import { computed } from 'vue'
import { Disclosure, DisclosureButton, DisclosurePanel } from '@headlessui/vue'
import {
	ChevronDown,
	Circle,
	CircleCheck,
	FileText,
	HelpCircle,
	LockKeyhole,
	MonitorPlay,
	NotebookPen,
	SquareCode,
} from 'lucide-vue-next'
import SidebarSection from '@/components/SidebarSection.vue'

/**
 * One recursive section row of the learner sidebar (design §5.1): children
 * render in the section's single manual order — lessons and nested sections
 * interleaved — with ps-3 indentation per level (ps-2 under 768px).
 */
const props = defineProps({
	section: { type: Object, required: true },
	level: { type: Number, default: 1 },
	ancestorPath: { type: String, default: '' },
	courseName: { type: String, required: true },
	selectedLessonNumber: { type: String, default: '' },
	inlineSelect: { type: Boolean, default: false },
	studentViewQuery: { type: Object, default: undefined },
})

const emit = defineEmits(['select-lesson'])

// Learner-facing count: every lesson in the subtree. For a legacy chapter
// (no nested sections) this equals the direct count, so the badge is
// unchanged.
const badgeCount = computed(() =>
	props.section.total_lesson_count ?? props.section.lessons?.length ?? 0
)

const sectionPath = computed(() =>
	props.ancestorPath
		? `${props.ancestorPath}-${props.section.idx}`
		: `${props.section.idx}`
)

// Sections on the path to the open lesson expand; with nothing open, only the
// first level-1 section does (legacy chapterDefaultOpen generalized).
const defaultOpen = computed(() => {
	const active = props.selectedLessonNumber
	if (!active) return props.section.idx === 1 && props.level === 1
	const segments = String(active).split('-')
	const pathSegments = sectionPath.value.split('-')
	if (pathSegments.length > segments.length) return false
	return pathSegments.every((segment, i) => segment === segments[i])
})

const mergedChildren = computed(() => {
	const children = []
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

function iconFor(icon) {
	switch (icon) {
		case 'icon-youtube':
			return MonitorPlay
		case 'icon-quiz':
			return HelpCircle
		case 'icon-assignment':
			return NotebookPen
		case 'icon-code':
			return SquareCode
		case 'icon-lock':
			return LockKeyhole
		default:
			return FileText
	}
}

// A lesson number is "path-…-lesson": the chapter param carries the whole
// section path, the lesson param the trailing position (design §3).
function lessonParams(lesson) {
	const segments = lesson.number.split('-')
	const lessonNumber = segments.pop()
	return {
		courseName: props.courseName,
		chapterNumber: segments.join('-'),
		lessonNumber,
	}
}

function isActive(number) {
	return props.selectedLessonNumber === number
}

function onLessonClick(lesson) {
	if (lesson.locked) return
	if (!props.inlineSelect) return
	const params = lessonParams(lesson)
	emit('select-lesson', {
		chapterNumber: params.chapterNumber,
		lessonNumber: params.lessonNumber,
	})
}
</script>
