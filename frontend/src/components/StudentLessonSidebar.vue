<template>
	<div class="flex flex-col h-full">
		<div class="bg-surface-gray-1 px-5 py-5 border-b">
			<div
				v-if="!hideHeader"
				class="text-lg-semibold text-ink-gray-9 leading-snug"
			>
				{{ courseTitle }}
			</div>
			<div
				class="flex items-center gap-2 text-sm text-ink-gray-7"
				:class="{ 'mt-4': !hideHeader }"
			>
				<Cloud class="size-4 stroke-1.5" />
				<span>{{ __('Completed') }} {{ displayedProgress }}%</span>
			</div>
			<div
				class="h-1 w-full rounded-full bg-surface-gray-2 overflow-hidden mt-2"
			>
				<div
					class="h-full bg-surface-green-3 transition-all"
					:style="{ width: `${displayedProgress}%` }"
				/>
			</div>
		</div>

		<ul
			class="flex-1 overflow-y-auto px-2 py-3 list-none [scrollbar-gutter:stable]"
		>
			<li v-for="chapter in outline.data || []" :key="chapter.name">
				<SidebarSection
					:section="chapter"
					:level="1"
					:courseName="courseName"
					:selectedLessonNumber="selectedLessonNumber"
					:inlineSelect="inlineSelect"
					:studentViewQuery="studentViewQuery"
					@select-lesson="(payload) => emit('select-lesson', payload)"
				/>
			</li>
		</ul>
	</div>
</template>

<script setup>
import { computed, watch, watchEffect } from 'vue'
import { useRoute } from 'vue-router'
import { createResource } from 'frappe-ui'
import { Cloud } from 'lucide-vue-next'
import SidebarSection from '@/components/SidebarSection.vue'

const props = defineProps({
	courseName: { type: String, required: true },
	courseTitle: { type: String, default: '' },
	progress: { type: Number, default: 0 },
	selectedLessonNumber: { type: String, default: '' },
	completedLesson: { type: String, default: null },
	inlineSelect: { type: Boolean, default: false },
	withProgress: { type: Boolean, default: true },
	hideHeader: { type: Boolean, default: false },
})

const emit = defineEmits(['select-lesson'])

// Keep ?studentView=1 across lesson hops, or a moderator previewing the course
// silently reverts to their own identity on the first sidebar click.
const route = useRoute()
const studentViewQuery = computed(() => {
	const query = {}
	if (route.query.studentView === '1') query.studentView = 1
	if (typeof route.query.hw === 'string') query.hw = route.query.hw
	return Object.keys(query).length ? query : undefined
})

const outline = createResource({
	url: 'lms.lms.utils.get_course_outline',
	cache: [
		'course_outline_student',
		props.courseName,
		props.withProgress ? 'progress' : 'no-progress',
	],
	makeParams() {
		return {
			course: props.courseName,
			progress: props.withProgress,
		}
	},
	auto: Boolean(props.courseName),
})

watch(
	() => props.courseName,
	() => {
		if (props.courseName) outline.reload()
	}
)

// Re-runs whenever either source updates so a completion event that
// lands before outline.data finishes loading still gets applied (and a
// late-arriving outline reload doesn't wipe an already-marked lesson).
// The walk is the whole tree now: a completed lesson may sit at any depth.
watchEffect(() => {
	const lessonName = props.completedLesson
	if (!lessonName || !outline.data) return
	const mark = (sections) => {
		for (const section of sections ?? []) {
			for (const lesson of section.lessons ?? []) {
				if (lesson.name === lessonName) {
					lesson.is_complete = true
					return true
				}
			}
			if (mark(section.sections)) return true
		}
		return false
	}
	mark(outline.data)
})

const displayedProgress = computed(() => Math.ceil(props.progress || 0))
</script>
