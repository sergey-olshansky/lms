<template>
	<!-- The per-attempt report body (#27, shared since #31): the same rows the
	     learner's modal and the teacher's review page render — one component,
	     so the two reports cannot drift apart. Only answered questions are
	     replayed; the strict verdicts of the attempt's grading decide each row's
	     status. Correct answers render behind `canViewCorrectAnswers`; the
	     server remains the arbiter of the key request the caller makes. -->
	<div v-if="loading" class="space-y-2.5">
		<Skeleton v-for="i in 3" :key="i" class="h-20 rounded-6" />
	</div>

	<template v-else-if="error">
		<p class="text-p-base text-ink-gray-5">
			{{ __('Could not load report') }}
		</p>
		<div class="mt-2 flex justify-end">
			<Button data-testid="attempt-report-retry" @click="emit('retry')">
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
				v-for="item in rowsWithSource"
				:key="`${item.row.number}-${item.row.questionName}`"
				data-testid="attempt-report-row"
				class="rounded-6 border p-3"
				:class="
					item.row.status === 'incorrect'
						? 'border-outline-red-2 bg-surface-red-1'
						: 'border-outline-gray-1'
				"
			>
				<!-- Q{n} runs inline with the question, as the review page
				     renders it; the number is the row's position within the
				     whole attempt, not within this filtered list. The body renders
				     through v-safe-html:rich like the in-quiz question, and images
				     shrink to the container (max-width:100%; height:auto) instead of
				     overflowing it or being clipped away. -->
				<div class="flex items-start gap-2">
					<span class="me-1 shrink-0 text-sm-semibold text-ink-gray-8">
						{{ __('Q{0}:').format(item.row.number) }}
					</span>
					<div
						v-if="item.row.question"
						class="min-w-0 flex-1 break-words text-p-base text-ink-gray-8 [&_img]:h-auto [&_img]:max-w-full"
						v-safe-html:rich="item.row.question"
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
					<span class="break-words" v-safe-html:rich="item.row.answer" />
				</div>

				<div class="mt-1.5 flex flex-wrap items-center gap-2">
					<span
						data-testid="attempt-report-status"
						class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium"
						:class="statusClass[item.row.status]"
					>
						{{ attemptRowStatusLabel(item.row.status) }}
					</span>
					<!-- The marks cell is the one place a review page needs its own
					     hand: a grader edits the pending marks here (#31). Left
					     alone it is the read-only figure both reports show. -->
					<slot name="marks" :row="item.row" :result-row="item.source">
						<span
							v-if="item.row.marks_out_of != null"
							class="ms-auto text-sm text-ink-gray-5"
						>
							{{ item.row.marks ?? 0 }} / {{ item.row.marks_out_of }}
						</span>
					</slot>
				</div>

				<!-- Correct answers are decision-dependent (#1088): one
				     render point behind one prop. A key request that comes
				     back denied hides the section without breaking the report. -->
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
						v-safe-html:rich="correctAnswerText(item.row.questionName)"
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

<script setup lang="ts">
import { Button, Skeleton } from 'frappe-ui'
import { computed } from 'vue'
import {
	attemptRowStatus,
	attemptRowStatusLabel,
	resolveAttemptQuestionText,
} from '@/utils/quizSummary'
import type {
	QuizAttemptRowStatus,
	QuizQuestionDetails,
	QuizReportRow,
	QuizResultRow,
} from '@/types'

const props = defineProps<{
	/** The submission's raw result rows; null while its document loads. */
	results: QuizResultRow[] | null
	/** Live question data of the quiz, for the question-text resolver. */
	questionsByName: Record<string, QuizQuestionDetails>
	/** Staff always; the submission's owner only when the quiz shows answers
	 * (#1088). The server re-checks every key request regardless. */
	canViewCorrectAnswers: boolean
	/** The key request's resource shape: data, loading, error. */
	correctAnswers: {
		data?: Record<string, string[]> | null
		loading?: boolean
		error?: unknown
	}
	/** The submission document itself is still on its way. */
	loading?: boolean
	/** The submission document failed to load. */
	error?: unknown
}>()

const emit = defineEmits<{ retry: [] }>()

const correctAnswerText = (questionName: string): string => {
	const answers = props.correctAnswers.data?.[questionName] || []
	return answers.length ? answers.join(', ') : '—'
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
// position within the whole attempt so it matches what the learner sat. The
// source row rides along so a review page's grading edits write the document,
// not the display copy.
const rowsWithSource = computed<{ row: QuizReportRow; source: QuizResultRow }[]>(
	() => {
		if (!Array.isArray(props.results)) return []
		return props.results
			.map((row, index) => ({
				row: toReportRow(index + 1, row),
				source: row,
			}))
			.filter((item) => item.row.status !== 'skipped')
	}
)

const rows = computed<QuizReportRow[]>(() =>
	rowsWithSource.value.map((item) => item.row)
)

const skippedCount = computed(() => {
	if (!Array.isArray(props.results)) return 0
	return props.results.filter((row) => attemptRowStatus(row) === 'skipped')
		.length
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
