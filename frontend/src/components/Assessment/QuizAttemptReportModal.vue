<template>
	<!-- The per-attempt report (#27): the Report action of one history row,
	     replaying only the questions that were answered. The rows themselves
	     are the shared report body (#31) — the teacher's review page renders
	     the very same component, so the two reports stay one report. Staff
	     always see the correct answers; the submission's owner sees them only
	     when the quiz's «Show Answers» checkbox is on (#1088). The server is
	     the arbiter of keys — the client only avoids requesting keys it would
	     be denied. -->
	<Dialog
		v-model:open="open"
		:title="reportTitle"
		size="2xl"
		:actions="[
			{
				label: __('Close'),
				onClick() {
					emit('close')
				},
			},
		]"
	>
		<template #default>
			<p
				data-testid="attempt-report-meta"
				class="mb-4 text-sm text-ink-gray-6"
			>
				{{ attempt.creation }} · {{ __('Score') }} {{ attempt.score }} /
				{{ attempt.score_out_of }} · {{ __('Percentage') }}
				{{ attempt.percentage }}%
			</p>

			<QuizAttemptReport
				:results="results"
				:questions-by-name="questionsByName"
				:can-view-correct-answers="canViewCorrectAnswers"
				:correct-answers="correctAnswers"
				:loading="loading"
				:error="submissionDoc.error"
				@retry="retry"
			/>
		</template>
	</Dialog>
</template>

<script setup lang="ts">
import { createResource, Dialog } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import QuizAttemptReport from '@/components/Assessment/QuizAttemptReport.vue'
import type {
	QuizAttempt,
	QuizQuestionDetails,
	QuizResultRow,
} from '@/types'

const props = defineProps<{
	/** The submission document the report replays (row.name of the history). */
	submissionName: string
	/** The history row itself: attempt number, date, score, percentage. */
	attempt: QuizAttempt
	/** Live question data of the quiz, for the question-text resolver. */
	questionsByName: Record<string, QuizQuestionDetails>
	/** Staff always; the submission's owner only when the quiz shows answers
	 * (#1088). The server re-checks every call regardless. */
	canViewCorrectAnswers: boolean
}>()

const emit = defineEmits<{ close: [] }>()

// The dialog owns its open state only so its built-in dismissal (Esc, close
// button, outside click) can notify the parent, which mounts it with v-if.
const open = ref(true)
watch(open, (value) => {
	if (!value) emit('close')
})

const reportTitle = __('Attempt {0} report').format(props.attempt.idx ?? '')

// The submission document the report rows come from. The doctype's
// permissions already restrict this read to the learner's own submissions and
// their instructors' — the same surface the result-screen summary reads.
const submissionDoc = createResource<{ result?: QuizResultRow[] } | null>({
	url: 'frappe.client.get',
	makeParams() {
		return {
			doctype: 'LMS Quiz Submission',
			name: props.submissionName,
		}
	},
	auto: true,
})

const results = computed<QuizResultRow[] | null>(() => {
	const value = submissionDoc.data?.result
	return Array.isArray(value) ? value : null
})

// Answer keys, from the one existing key source. Requested only for viewers
// the client believes are authorised; the server remains the arbiter
// (_can_review_submission for staff, submission owner + the quiz's
// show_answers for the learner, #1088).
const correctAnswers = createResource<Record<string, string[]> | null>({
	url: 'lms.lms.doctype.lms_quiz.lms_quiz.get_submission_correct_answers',
	makeParams() {
		return { submission: props.submissionName }
	},
	auto: props.canViewCorrectAnswers,
})

// True while the doc is on its way and nothing has failed; the report keeps
// its skeletons instead of flashing rows it does not have yet.
const loading = computed(
	() => results.value === null && !submissionDoc.error
)

const retry = () => {
	// fetch() clears the error on a real resource; clear it here too so the
	// body swaps back to its loading shape instead of staying on the retry
	// line until the response lands.
	submissionDoc.error = null
	submissionDoc.fetch()
}
</script>
