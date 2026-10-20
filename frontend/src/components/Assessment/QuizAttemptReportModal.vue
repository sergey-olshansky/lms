<template>
	<!-- The per-attempt report (#27): the Report action of one history row,
	     replaying only the questions that were answered. Staff always see the
	     correct answers; the submission's owner sees them only when the quiz's
	     «Show Answers» checkbox is on (#1088). The server is the arbiter of
	     keys — the client only avoids requesting keys it would be denied.
	     Skipped questions stay out of the list; the post-submit summary on the
	     result screen already shows every question, keys never included. -->
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

			<div v-if="loading" class="space-y-2.5">
				<Skeleton v-for="i in 3" :key="i" class="h-20 rounded-6" />
			</div>

			<template v-else-if="submissionDoc.error">
				<p class="text-p-base text-ink-gray-5">
					{{ __('Could not load report') }}
				</p>
				<div class="mt-2 flex justify-end">
					<Button data-testid="attempt-report-retry" @click="retry">
						{{ __('Retry') }}
					</Button>
				</div>
			</template>

			<p v-else-if="!rows.length" class="text-p-base text-ink-gray-5">
				{{ __('No questions were answered in this attempt.') }}
			</p>

			<template v-else>
				<ol data-testid="attempt-report-rows" class="space-y-2.5">
					<li
						v-for="row in rows"
						:key="`${row.number}-${row.questionName}`"
						data-testid="attempt-report-row"
						class="rounded-6 border p-3"
						:class="
							row.status === 'incorrect'
								? 'border-outline-red-2 bg-surface-red-1'
								: 'border-outline-gray-1'
						"
					>
						<!-- Q{n} runs inline with the question, as the review page
						     renders it; the number is the row's position within the
						     whole attempt, not within this filtered list. The body renders
						     through v-safe-html:rich like the in-quiz question, and images
						     shrink to the modal (max-width:100%; height:auto) instead of
						     overflowing it or being clipped away. -->
						<div class="flex items-start gap-2">
							<span class="me-1 shrink-0 text-sm-semibold text-ink-gray-8">
								{{ __('Q{0}:').format(row.number) }}
							</span>
							<div
								v-if="row.question"
								class="min-w-0 flex-1 break-words text-p-base text-ink-gray-8 [&_img]:h-auto [&_img]:max-w-full"
								v-safe-html:rich="row.question"
							/>
							<!-- Both resolver branches empty: an explicit state,
							     never a silently blank line (#27). -->
							<p
								v-else
								data-testid="attempt-report-question-unavailable"
								class="min-w-0 flex-1 text-p-base text-ink-gray-5"
							>
								{{ __('Question text is not available') }}
							</p>
						</div>

						<div class="mt-1.5 text-p-base text-ink-gray-7">
							<span class="text-ink-gray-5">{{ __('Your answer:') }}</span>
							<span class="break-words" v-safe-html:rich="row.answer" />
						</div>

						<div class="mt-1.5 flex flex-wrap items-center gap-2">
							<span
								data-testid="attempt-report-status"
								class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium"
								:class="statusClass[row.status]"
							>
								{{ attemptRowStatusLabel(row.status) }}
							</span>
							<span
								v-if="row.marks_out_of != null"
								class="ms-auto text-sm text-ink-gray-5"
							>
								{{ row.marks ?? 0 }} / {{ row.marks_out_of }}
							</span>
						</div>

						<!-- Correct answers are decision-dependent (#1088): one
						     render point behind one prop. A key request that comes
						     back denied (staff without rights to this quiz) hides
						     the section without breaking the report. -->
						<div
							v-if="canViewCorrectAnswers && !correctAnswers.error"
							class="mt-1.5 border-s border-outline-gray-2 ps-3 text-p-base text-ink-gray-7"
						>
							<span
								class="me-2 text-xs font-medium uppercase tracking-wide text-ink-gray-4"
							>
								{{ __('Correct Answer:') }}
							</span>
							<span v-if="correctAnswers.loading" class="leading-5">…</span>
							<span
								v-else
								class="break-words"
								v-safe-html:rich="correctAnswerText(row.questionName)"
							/>
						</div>
					</li>
				</ol>
				<p
					v-if="skippedCount"
					data-testid="attempt-report-skipped"
					class="mt-3 text-p-sm text-ink-gray-5"
				>
					{{
						__('{0} skipped questions are not included in this report.').format(
							skippedCount
						)
					}}
				</p>
			</template>
		</template>
	</Dialog>
</template>

<script setup lang="ts">
import { Button, createResource, Dialog, Skeleton } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import {
	attemptRowStatus,
	attemptRowStatusLabel,
	resolveAttemptQuestionText,
} from '@/utils/quizSummary'
import type {
	QuizAttempt,
	QuizAttemptRowStatus,
	QuizQuestionDetails,
	QuizReportRow,
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

const correctAnswerText = (questionName: string): string => {
	const answers = correctAnswers.data?.[questionName] || []
	return answers.length ? answers.join(', ') : '—'
}

// True while the doc is on its way and nothing has failed; the report keeps
// its skeletons instead of flashing rows it does not have yet.
const loading = computed(
	() => !Array.isArray(submissionDoc.data?.result) && !submissionDoc.error
)

const retry = () => {
	// fetch() clears the error on a real resource; clear it here too so the
	// body swaps back to its loading shape instead of staying on the retry
	// line until the response lands.
	submissionDoc.error = null
	submissionDoc.fetch()
}

const toReportRow = (number: number, row: QuizResultRow): QuizReportRow => ({
	number,
	questionName: row.question_name ?? '',
	question: resolveAttemptQuestionText(row, props.questionsByName),
	answer: row.answer ?? '',
	status: attemptRowStatus(row),
	marks: row.marks,
	marks_out_of: row.marks_out_of,
})

// Only answered questions belong to the report; the number keeps the row's
// position within the whole attempt so it matches what the learner sat.
const rows = computed<QuizReportRow[]>(() => {
	const results = submissionDoc.data?.result
	if (!Array.isArray(results)) return []
	return results
		.map((row, index) => toReportRow(index + 1, row))
		.filter((row) => row.status !== 'skipped')
})

const skippedCount = computed(() => {
	const results = submissionDoc.data?.result
	if (!Array.isArray(results)) return 0
	return results.filter((row) => attemptRowStatus(row) === 'skipped').length
})

// Same palette as the post-submit summary rows: colour echoes the chip's
// text, never replaces it. Logical utilities only, so RTL needs no override.
const statusClass: Record<QuizAttemptRowStatus, string> = {
	correct: 'bg-surface-green-6 text-ink-green-1',
	incorrect: 'bg-surface-red-6 text-ink-red-1',
	skipped: 'bg-surface-gray-1 text-ink-gray-5 border border-outline-gray-2',
	pending: 'bg-surface-orange-1 text-ink-orange-6',
}
</script>
