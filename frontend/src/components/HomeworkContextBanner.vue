<template>
	<div
		v-if="summary"
		class="flex items-center gap-3 border-b bg-surface-gray-1 px-5 py-2 text-sm"
		data-testid="homework-context-banner"
	>
		<router-link
			:to="{
				name: 'HomeworkDetail',
				params: { assignmentID: props.assignmentID },
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
		</span>
	</div>
</template>

<script setup>
// The homework context strip (spec 5.3.6, R10/R18): carried by ?hw= on a lesson,
// a standalone quiz or a written assignment, it keeps the way back one click
// away and shows live progress. With `start`, the material is standalone -- the
// student's first touch of it must begin the card, exactly like opening a lesson.
import { call } from 'frappe-ui'
import { computed, onMounted, ref } from 'vue'

const props = defineProps({
	assignmentID: { type: String, required: true },
	start: { type: Boolean, default: false },
})

const summary = ref(null)

const progressPercent = computed(() =>
	summary.value && summary.value.total_requirements
		? Math.round(
				(summary.value.completed_requirements /
					summary.value.total_requirements) *
					100
		  )
		: 0
)

onMounted(async () => {
	try {
		summary.value = await call('lms.lms.homework_api.get_homework_assignment', {
			name: props.assignmentID,
		})
	} catch {
		// Not this viewer's homework (stale link, other user): no banner.
		return
	}
	if (props.start) {
		try {
			await call('lms.lms.homework_api.open_homework', {
				assignment: props.assignmentID,
			})
		} catch {
			// A teacher's preview open is refused by design.
		}
	}
})
</script>
