<template>
	<div
		v-if="summary"
		class="flex items-center gap-3 border-b bg-surface-gray-1 px-5 py-2 text-sm"
		data-testid="homework-context-banner"
	>
		<router-link
			:to="{
				name: 'HomeworkDetail',
				params: { assignmentID: props.assignmentId },
			}"
			class="flex items-center gap-2 text-ink-gray-7 transition-colors hover:text-ink-gray-9"
		>
			<span class="lucide-clipboard-list size-4" aria-hidden="true" />
			{{ __('Back to homework') }}
		</router-link>
		<span class="ml-auto flex items-center gap-2 text-xs text-ink-gray-5">
			<span class="h-1 w-16 overflow-hidden rounded-full bg-surface-gray-3">
				<span
					class="block h-full rounded-full bg-surface-green-7"
					:style="{ width: progressPercent + '%' }"
				/>
			</span>
			{{
				__('{0} of {1} done').format(
					String(summary.completed_requirements),
					String(summary.total_requirements)
				)
			}}
			<span v-if="summary.status === 'Review'" class="text-ink-green-6">{{
				__('Sent for review')
			}}</span>
			<span v-else-if="summary.status === 'Done'" class="text-ink-green-6">{{
				__('Homework accepted')
			}}</span>
		</span>
	</div>
</template>

<script setup>
// The homework context strip (spec 5.3.6, R10/R18): carried by ?hw= on a lesson,
// a standalone quiz or a written assignment, it keeps the way back one click
// away and shows live progress.
//
// The prop is deliberately `assignmentId` (not `assignmentID`): Vue's
// kebab-case -> camelCase conversion of `assignment-id` yields exactly this
// spelling, and the taller `assignmentID` variant silently never receives the
// attribute -- a real browser session caught the banner mounting with an empty
// id while every isolated harness passed.
import { call, createResource } from 'frappe-ui'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps({
	assignmentId: { type: String, required: true },
	start: { type: Boolean, default: false },
})
const emit = defineEmits(['summary'])

const summary = ref(null)
let generation = 0
const startApplied = ref(false)

const detail = createResource({
	url: 'lms.lms.homework_api.get_homework_assignment',
	makeParams: () => ({ name: props.assignmentId }),
})

const refresh = async () => {
	const run = ++generation
	let data
	try {
		data = await detail.submit()
	} catch {
		// Not this viewer's homework (stale link, other user): no banner.
		if (run === generation) summary.value = null
		return
	}
	if (run !== generation) return
	summary.value = data
	emit('summary', data)

	if (!props.start || !data?.viewer_is_student || startApplied.value) return
	// Standalone material: this page IS the student's first touch of the card.
	startApplied.value = true
	try {
		await call('lms.lms.homework_api.open_homework', {
			assignment: props.assignmentId,
		})
		const fresh = await detail.submit()
		if (run !== generation) return
		summary.value = fresh
		emit('summary', fresh)
	} catch {
		// Already started elsewhere, or the card moved on: the summary shown
		// stays whatever the server last said.
	}
}

watch(
	() => props.assignmentId,
	() => {
		startApplied.value = false
		summary.value = null
		refresh()
	},
	{ immediate: true }
)

const refetchIfVisible = () => {
	if (document.visibilityState === 'visible') refresh()
}
onMounted(() => {
	window.addEventListener('lms:homework-progress', refresh)
	window.addEventListener('focus', refetchIfVisible)
	document.addEventListener('visibilitychange', refetchIfVisible)
})
onUnmounted(() => {
	window.removeEventListener('lms:homework-progress', refresh)
	window.removeEventListener('focus', refetchIfVisible)
	document.removeEventListener('visibilitychange', refetchIfVisible)
})

defineExpose({ refresh })

const progressPercent = computed(() =>
	summary.value && summary.value.total_requirements
		? Math.round(
				(summary.value.completed_requirements /
					summary.value.total_requirements) *
					100
			)
		: 0
)
</script>
