<template>
	<!-- Nothing to show for an attempt that graded zero questions (an empty
	     quiz): the Questions section is withheld rather than rendered empty. -->
	<div
		v-if="rows === null || rows.length > 0 || !!error"
		class="rounded-6 border border-outline-gray-2 p-3.5"
	>
		<div class="text-sm-semibold text-ink-gray-9">
			{{ __('Questions') }}
		</div>
		<ol v-if="rows?.length" data-testid="quiz-summary-rows" class="mt-2.5 space-y-2.5">
			<li
				v-for="row in rows"
				:key="row.questionName"
				data-testid="quiz-summary-row"
				class="rounded-6 border p-3"
				:class="
					row.status === 'incorrect'
						? 'border-outline-red-2 bg-surface-red-1'
						: 'border-outline-gray-1'
				"
			>
				<div class="flex flex-wrap items-center gap-2">
					<span class="text-sm-semibold text-ink-gray-8">
						{{ __('Question {0}').format(row.number) }}
					</span>
					<span
						data-testid="quiz-summary-status"
						class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium"
						:class="statusClass[row.status]"
					>
						{{ attemptRowStatusLabel(row.status) }}
					</span>
				</div>
				<!-- Only the question text and the learner's own answer are ever
				     rendered here; the correct answer, keys and explanations stay
				     out of this surface by construction (#27). -->
				<div
					class="mt-1.5 text-p-base text-ink-gray-8"
					v-safe-html:rich="row.question"
				/>
				<div
					v-if="row.status !== 'skipped'"
					class="mt-1.5 text-p-base text-ink-gray-7"
				>
					<span class="text-ink-gray-5">{{ __('Your answer:') }}</span>
					<span class="break-words" v-safe-html:rich="row.answer" />
				</div>
			</li>
		</ol>
		<div v-else-if="loading" class="mt-2.5 space-y-2.5">
			<Skeleton v-for="i in 3" :key="i" class="h-16 rounded-6" />
		</div>
		<template v-else>
			<p class="mt-2 text-p-base text-ink-gray-5">
				{{ __('Could not load question results') }}
			</p>
			<div class="mt-2 flex justify-end">
				<Button @click="emit('retry')">{{ __('Retry') }}</Button>
			</div>
		</template>
	</div>
</template>

<script setup lang="ts">
import { Button, Skeleton } from 'frappe-ui'
import { attemptRowStatusLabel } from '@/utils/quizSummary'
import type { QuizAttemptRowStatus, QuizSummaryRow } from '@/types'

// The read-only per-question rows of one finished attempt (#27). Rendered after
// every submission and on the exhausted-attempts card alike: one row per
// question in attempt order, with the learner's own answer and its textual
// verdict — correct answers and explanations are deliberately absent.
defineProps<{
	rows: QuizSummaryRow[] | null
	loading: boolean
	error: unknown
}>()

const emit = defineEmits<{ retry: [] }>()

// Colour echoes the chip's text, never replaces it; every state is readable
// without colour. Logical utilities only, so RTL layouts need no overrides.
const statusClass: Record<QuizAttemptRowStatus, string> = {
	correct: 'bg-surface-green-6 text-ink-green-1',
	incorrect: 'bg-surface-red-6 text-ink-red-1',
	skipped: 'bg-surface-gray-1 text-ink-gray-5 border border-outline-gray-2',
	pending: 'bg-surface-orange-1 text-ink-orange-6',
}
</script>
