<template>
	<PageHeader :breadcrumbs="breadcrumbs">
		<template #actions>
			<!-- The PDF of this very report (#33): the same renderer the
			     completion email attaches, behind the same review rights. Own
			     attempt or not, downloading the report is a read, not a grade. -->
			<HeaderButton
				:label="__('Download PDF')"
				icon="lucide-file-down"
				@click="downloadPdf"
			/>
			<!-- The sentence is why the Save button is missing, so it has to stay
			     reachable on a phone. A tooltip would not do it: there is no hover on
			     a touch screen, so the header spells it out where it fits and hands
			     it to a tappable popover where it does not. -->
			<template v-if="isOwnSubmission">
				<!-- No @click: #trigger renders as-child through reka's PopoverTrigger,
				     which wires click, keyboard and aria itself. Toggling by hand as
				     well opened and immediately reclosed it.
				     `sm:hidden` belongs on the button, not on Popover: the component
				     only binds $attrs on its legacy anchor path.
				     The panel is portalled and positioned by `side`/`align`, so it
				     must not carry absolute positioning of its own. -->
				<Popover bare align="end" :offset="8">
					<template #trigger>
						<button
							type="button"
							class="flex items-center p-1 text-ink-gray-5 sm:hidden"
							:aria-label="ownSubmissionNotice"
						>
							<span class="lucide-info size-4" aria-hidden="true" />
						</button>
					</template>
					<template #default>
						<p
							class="w-56 rounded-6 bg-surface-base p-3 text-sm leading-5 text-ink-gray-7 shadow-2xl ring-1 ring-outline-gray-2"
						>
							{{ ownSubmissionNotice }}
						</p>
					</template>
				</Popover>

				<span
					class="hidden items-center gap-1.5 text-sm text-ink-gray-7 sm:flex"
				>
					<span class="lucide-info size-4 shrink-0" aria-hidden="true" />
					{{ ownSubmissionNotice }}
				</span>
			</template>
			<template v-else>
				<!-- Card #47: the second pass ends here. Pending while any open
				     answer has no recorded verdict - the endpoint re-checks
				     that, and the reviewer's authority, server-side. -->
				<HeaderButton
					v-if="reviewStatus === 'pending_review'"
					:label="__('Finish Review')"
					icon="lucide-check-check"
					@click="showFinishReview = true"
				/>
				<Badge
					v-if="submissionDetails.isDirty"
					:label="__('Not Saved')"
					variant="subtle"
					theme="amber"
				/>
				<ShortcutTooltip :label="__('Save')" combo="Mod+S">
					<HeaderButton
						:label="__('Save')"
						icon="lucide-check"
						variant="solid"
						@click="saveSubmission()"
					/>
				</ShortcutTooltip>
			</template>
		</template>
	</PageHeader>

	<PageBody>
		<!-- Questions read as the page; the sidebar is a margin note about who sat
		     it and how it went, so it stacks under them once there is no room for
		     a second column. PageBody owns the one scroll box.

		     The title sits in the grid rather than in PageBody's name strip so the
		     sidebar rule starts level with it instead of below a full-width strip.
		     Top padding therefore belongs to each column: on the grid it would sit
		     above the rule and leave the same gap again. -->
		<div
			v-if="submissionDetails.doc"
			class="grid lg:flex-1 lg:grid-cols-[minmax(0,1fr)_300px] lg:grid-rows-[auto_1fr]"
		>
			<!-- The rule belongs to this column, not to the sidebar blocks: they are
			     only as tall as their own content, so a submission with no
			     violations ended the line halfway down the page. Spanning both rows
			     against a grid that fills the body carries it to the bottom. -->
			<div
				class="order-3 min-w-0 lg:order-none lg:col-start-1 lg:row-start-1 lg:row-span-2 lg:border-e"
			>
				<h1 class="text-lg-semibold mb-4 px-5 pt-5 text-ink-gray-9 lg:pe-10">
					{{ submissionDetails.doc.quiz_title }}
				</h1>

				<!-- The report itself is the learner's per-attempt report (#31):
				     the same shared body, question-for-question and label-for-label,
				     so the two cannot drift apart. What stays this page's own is the
				     grader's hand: pending marks are editable in place, and the strict
				     verdicts of the attempt's grading stay exactly as stored. -->
				<div class="px-5 pb-5 lg:pe-10">
					<!-- Card #47: the submission's solution-file bundle, exactly
					     what the open part is graded against. One bundle for the
					     whole submission; the ZIP rides the reviewer-only
					     archive endpoint. -->
					<QuizFileAttachments
						v-if="hasOpenQuestions"
						:submission="props.submission"
						can-archive
						class="mb-4"
					/>

					<!-- Card #47: one list of every question, grouped by the two
					     parts of the test. The teacher sees each task, the
					     learner's answer and the files together, and may
					     override the score of ANY row - the auto-checked part
					     included. Untouched auto rows keep their preliminary
					     marks; overridden rows are marked in words. -->
					<template v-if="hasOpenQuestions">
						<h2 class="mb-2 text-sm-semibold text-ink-gray-7">
							{{ __('Part 1 · Auto-checked questions') }}
							<span class="ms-1 font-normal text-ink-gray-5">
								({{ __('preliminary scores; adjust where needed') }})
							</span>
						</h2>
						<QuizAttemptReport
							:results="autoRows"
							:questions-by-name="questionsByName"
							:can-view-correct-answers="true"
							:correct-answers="correctAnswers"
						>
							<template #marks="{ row, resultRow }">
								<div class="ms-auto flex shrink-0 items-center gap-1.5">
									<span
										v-if="resultRow.teacher_override"
										class="text-xs font-medium text-ink-amber-6"
									>
										{{ __('Adjusted by teacher') }}
									</span>
									<span
										class="text-xs font-medium uppercase tracking-wide text-ink-gray-4 lg:hidden"
									>
										{{ __('Marks:') }}
									</span>
									<FormControl
										v-if="!isOwnSubmission"
										v-model="resultRow.marks"
										type="number"
										class="w-20"
										@update:model-value="() => markAutoRowDirty(resultRow)"
									/>
									<span
										v-else
										class="text-sm font-medium text-ink-gray-7 lg:w-20 lg:text-end"
									>
										{{ row.marks }}
									</span>
									<span class="text-sm text-ink-gray-5">
										/ {{ row.marks_out_of }}
									</span>
								</div>
							</template>
						</QuizAttemptReport>

						<h2 class="mb-2 mt-6 text-sm-semibold text-ink-gray-7">
							{{ __('Part 2 · Open-answer tasks') }}
							<span class="ms-1 font-normal text-ink-gray-5">
								({{ __('checked by you; a recorded zero is allowed') }})
							</span>
						</h2>
						<QuizAttemptReport
							:results="openRows"
							:questions-by-name="questionsByName"
							:can-view-correct-answers="true"
							:correct-answers="correctAnswers"
							include-skipped-open
						>
							<template #marks="{ row, resultRow }">
								<div class="ms-auto flex shrink-0 items-center gap-1.5">
									<span
										class="text-xs font-medium uppercase tracking-wide text-ink-gray-4 lg:hidden"
									>
										{{ __('Marks:') }}
									</span>
									<!-- Task #35 (C01): a typed value IS the verdict --
									     including a deliberate 0 -- and writes the row's
									     graded flag in the same edit; clearing the input
									     takes the verdict back. Card #47: an unanswered
									     open task stays in this list, because it still
									     needs the teacher's verdict (a zero included). -->
									<FormControl
										v-if="!isOwnSubmission"
										v-model="resultRow.marks"
										type="number"
										class="w-20"
										@update:model-value="
											(value) => {
												resultRow.graded =
													value === null || value === '' ? 0 : 1
												markRowDirty(resultRow)
											}
										"
									/>
									<span
										v-else
										class="text-sm font-medium text-ink-gray-7 lg:w-20 lg:text-end"
									>
										{{ row.marks }}
									</span>
									<span class="text-sm text-ink-gray-5">
										/ {{ row.marks_out_of }}
									</span>
								</div>
							</template>
						</QuizAttemptReport>
					</template>
					<QuizAttemptReport
						v-else
						:results="submissionDetails.doc.result || []"
						:questions-by-name="questionsByName"
						:can-view-correct-answers="true"
						:correct-answers="correctAnswers"
					>
						<template #marks="{ row, resultRow }">
							<div class="ms-auto flex shrink-0 items-center gap-1.5">
								<span
									class="text-xs font-medium uppercase tracking-wide text-ink-gray-4 lg:hidden"
								>
									{{ __('Marks:') }}
								</span>
								<FormControl
									v-if="
										resultRow.question_type === 'Open Ended' &&
										!isOwnSubmission
									"
									v-model="resultRow.marks"
									type="number"
									class="w-20"
									@update:model-value="
										(value) => {
											resultRow.graded =
												value === null || value === '' ? 0 : 1
											markRowDirty(resultRow)
										}
									"
								/>
								<span
									v-else
									class="text-sm font-medium text-ink-gray-7 lg:w-20 lg:text-end"
								>
									{{ row.marks }}
								</span>
								<span class="text-sm text-ink-gray-5">
									/ {{ row.marks_out_of }}
								</span>
							</div>
						</template>
					</QuizAttemptReport>
				</div>
			</div>

			<!-- Padding lives on each block rather than on the column, so a rule
			     between two of them runs the full width of the sidebar instead of
			     stopping short of the divider it meets.

			     The `order-*` classes are what a phone follows: stacked, the whole
			     sidebar reads as context for the answers rather than a footnote to
			     them, so summary then log then questions. The explicit placement
			     outranks order once there are two columns. -->
			<aside
				class="order-1 border-b lg:order-none lg:col-start-2 lg:row-start-1 lg:border-b-0"
			>
				<div class="flex items-center gap-3 px-5 py-5">
					<Avatar
						:image="memberImage"
						:label="submissionDetails.doc.member_name"
						size="2xl"
					/>
					<div class="min-w-0">
						<div class="truncate text-base text-ink-gray-8">
							{{ submissionDetails.doc.member_name }}
						</div>
						<div class="mt-0.5 text-xs text-ink-gray-5">
							{{ formatDate(submissionDetails.doc.creation) }}
						</div>
						<!-- Card #47: the attempt's review state, in words - the
						     same chip the learner's surfaces carry, so both sides
						     read one status. -->
						<div v-if="reviewStatus" class="mt-1.5">
							<span
								class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium"
								:class="
									reviewStatus === 'final'
										? 'bg-surface-green-6 text-ink-green-1'
										: 'bg-surface-amber-1 text-ink-amber-6'
								"
								data-testid="submission-review-status"
							>
								<span
									class="me-1 size-3"
									:class="
										reviewStatus === 'final'
											? 'lucide-check-check'
											: 'lucide-clock'
									"
									aria-hidden="true"
								/>
								{{ reviewStatusLabel(reviewStatus) }}
							</span>
							<div
								v-if="reviewStatus === 'final' && submissionDetails.doc.reviewed_on"
								class="mt-1 text-xs text-ink-gray-5"
							>
								{{ formatDate(submissionDetails.doc.reviewed_on) }}
							</div>
						</div>
					</div>
				</div>

				<div class="border-t px-5 py-5">
					<div class="flex gap-6">
						<div>
							<div class="mb-0.5 text-xs text-ink-gray-5">
								{{ __('Score') }}
							</div>
							<div class="text-sm font-medium text-ink-gray-8">
								{{ submissionDetails.doc.score }} /
								{{ submissionDetails.doc.score_out_of }}
							</div>
						</div>
						<div>
							<div class="mb-0.5 text-xs text-ink-gray-5">
								{{ __('Percentage') }}
							</div>
							<div class="text-sm font-medium text-ink-gray-8">
								{{ submissionDetails.doc.percentage }}%
							</div>
						</div>
						<div v-if="submissionDetails.doc.violation_count">
							<div class="mb-0.5 text-xs text-ink-gray-5">
								{{ __('Violations') }}
							</div>
							<div class="text-sm font-medium text-ink-red-5">
								{{ submissionDetails.doc.violation_count }}
							</div>
						</div>
					</div>
				</div>
			</aside>

			<!-- Sits under the score on a phone, where it collapses: an attempt with
			     a long run of events would otherwise push the first question off the
			     screen. On a desk it is simply open, under the summary.

			     The rule above it is the summary's `border-b` while stacked and its
			     own `lg:border-t` beside it, so the two never double up — and a
			     submission with no violations still gets one from the summary. -->
			<aside
				v-if="submissionDetails.doc.violation_count"
				class="order-2 border-b px-5 py-5 lg:order-none lg:col-start-2 lg:row-start-2 lg:border-b-0 lg:border-t"
			>
				<details
					:open="logOpen"
					class="group"
					@toggle="logOpen = $event.target.open"
				>
					<summary
						class="flex cursor-pointer list-none items-center gap-1.5 [&::-webkit-details-marker]:hidden lg:cursor-default lg:pointer-events-none"
					>
						<h2 class="text-sm font-semibold text-ink-gray-7">
							{{ __('Proctoring Log') }}
						</h2>
						<span
							v-if="violationLog.data?.length"
							class="text-sm text-ink-gray-4"
						>
							({{ violationLog.data.length }})
						</span>
						<span
							class="lucide-chevron-down ms-auto size-4 shrink-0 text-ink-gray-5 transition-transform group-open:rotate-180 lg:hidden"
						/>
					</summary>

					<div class="mt-4">
						<!-- The rule runs behind the markers rather than between them,
						     so the events read as one run of time. -->
						<ol
							v-if="violationLog.data?.length"
							class="border-s border-outline-gray-2 ps-4"
						>
							<li
								v-for="entry in violationLog.data"
								:key="`${entry.event_type}-${entry.timestamp}`"
								class="relative pb-4 last:pb-0"
							>
								<span
									class="absolute -start-[21px] top-1 size-2 rounded-full"
									:class="
										entry.severity === 'violation'
											? 'bg-surface-red-6'
											: 'bg-surface-orange-6'
									"
								/>
								<div class="text-xs font-medium leading-5 text-ink-gray-7">
									{{
										violationEventLabels[entry.event_type] || entry.event_type
									}}
								</div>
								<div class="mt-0.5 flex items-center gap-1 text-xs leading-5">
									<span
										class="font-medium"
										:class="
											entry.severity === 'violation'
												? 'text-ink-red-5'
												: 'text-ink-orange-5'
										"
									>
										{{ severityLabel(entry.severity) }}
									</span>
									<span class="text-ink-gray-4">
										· {{ formatTime(entry.timestamp) }}
									</span>
								</div>
								<!-- What the camera saw as the event fired, behind a disclosure:
								     a run of full-size stills buries the timeline it belongs to,
								     and the log is read to find the moment worth looking at
								     rather than to look at all of them.
								     Absent on events recorded before frames were captured, and
								     on a camera disconnect, where there was nothing left to
								     draw — so the entry stands without it. -->
								<details v-if="safeUrl(entry.frame)" class="group mt-1.5">
									<!-- Subordinate to the event it belongs to: the timeline is
									     read for what happened and when, and the snapshot is the
									     follow-up. The label states what opening it costs the
									     reader, and swaps on open so the control still describes
									     what it does. -->
									<summary
										class="w-fit cursor-pointer list-none text-xs text-ink-gray-5 underline underline-offset-2 hover:text-ink-gray-7 [&::-webkit-details-marker]:hidden"
									>
										{{ __('Snapshot') }}
									</summary>
									<a
										v-external
										:href="safeUrl(entry.frame)"
										class="mt-1.5 block"
									>
										<img
											:src="safeUrl(entry.frame)"
											:alt="
												__('Camera at {0}').format(
													violationEventLabels[entry.event_type] ||
														entry.event_type
												)
											"
											class="w-full rounded-4 border"
										/>
									</a>
								</details>
							</li>
						</ol>

						<!-- The count is stored on the submission but the events are
						     sent separately, so a submission can be flagged with
						     nothing to show: say so rather than leave it blank. -->
						<p v-else class="text-xs leading-5 text-ink-gray-5">
							{{ __('No event details were recorded for this attempt.') }}
						</p>
					</div>
				</details>
			</aside>
		</div>
	</PageBody>

	<!-- Card #47: finishing the second pass fixes the final result. The
	     confirmation names what it means in counts, and the endpoint still
	     re-validates that every open answer carries a recorded verdict. -->
	<Dialog
		v-model:open="showFinishReview"
		:title="__('Finish review?')"
		:actions="[
			{
				size: 'sm',
				label: __('Back'),
				onClick() {
					showFinishReview = false
				},
			},
			{
				size: 'sm',
				label: __('Finish Review'),
				variant: 'solid',
				onClick() {
					finishReview()
				},
			},
		]"
	>
		<template #default>
			<div class="space-y-2" role="status" aria-live="polite">
				<p class="text-base text-ink-gray-6 leading-5">
					{{
						__('Adjusted by hand: {0}. Keeping their preliminary score: {1}.').format(
							overrideCount,
							Math.max(autoRows.length - overrideCount, 0)
						)
					}}
				</p>
				<p class="text-base text-ink-gray-6 leading-5">
					{{
						__('Open-answer tasks graded: {0} of {1}.').format(
							openRows.length - openUngradedCount,
							openRows.length
						)
					}}
				</p>
				<p class="text-base text-ink-gray-6 leading-5">
					{{
						__(
							'The result will be fixed as final for the learner. The review cannot be reopened from here.'
						)
					}}
				</p>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import {
	createResource,
	createDocumentResource,
	FormControl,
	Badge,
	Avatar,
	Dialog,
	Popover,
	usePageMeta,
	toast,
} from 'frappe-ui'
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useDebounceFn, useMediaQuery } from '@vueuse/core'
import { safeUrl } from '@/utils/safeUrl'
import { openExternal } from '@/utils/openExternal'
import PageHeader from '@/components/Layouts/pages/PageHeader.vue'
import PageBody from '@/components/Layouts/pages/PageBody.vue'
import HeaderButton from '@/components/HeaderButton.vue'
import ShortcutTooltip from '@/components/ShortcutTooltip.vue'
import QuizAttemptReport from '@/components/Assessment/QuizAttemptReport.vue'
import QuizFileAttachments from '@/components/Assessment/QuizFileAttachments.vue'
import {
	useKeyboardShortcuts,
	saveShortcut,
} from '@/composables/useKeyboardShortcuts'
import { useRouter } from 'vue-router'
import { sessionStore } from '@/stores/session'
import {
	reviewStatusLabel,
	submissionReviewStatus,
} from '@/utils/quizSummary'

const { brand } = sessionStore()
const router = useRouter()
const user = inject('$user')

onMounted(() => {
	if (
		!user.data?.is_instructor &&
		!user.data?.is_moderator &&
		!user.data?.is_system_manager
	)
		router.push({ name: 'Courses' })
})

useKeyboardShortcuts({
	ignoreTyping: false,
	shortcuts: [
		{
			...saveShortcut(() => saveSubmission()),
			guard: (e) => !e.target?.classList?.contains('ProseMirror'),
		},
	],
})

const props = defineProps({
	submission: {
		type: String,
		required: true,
	},
})

const submissionDetails = createDocumentResource({
	doctype: 'LMS Quiz Submission',
	name: props.submission,
	auto: true,
})

const correctAnswers = createResource({
	url: 'lms.lms.doctype.lms_quiz.lms_quiz.get_submission_correct_answers',
	makeParams() {
		return { submission: props.submission }
	},
	auto: true,
})

// Live question data of the quiz, for the report's question-text resolver
// (#31): the stored snapshot of a row can be empty or stale, and the full
// assignment body — wording and task imagery — is what a review needs. Staff
// review rights are what the page already checked the caller for.
const quizQuestions = createResource({
	url: 'lms.lms.utils.get_quiz_with_questions',
	makeParams() {
		// The endpoint requires the quiz; without it every fetch throws and
		// the report falls back to the stored snapshots alone.
		return { quiz: submissionDetails.doc?.quiz }
	},
	auto: false,
})

watch(
	() => submissionDetails.doc?.quiz,
	(quiz) => {
		if (quiz) quizQuestions.fetch()
	},
	{ immediate: true }
)

const questionsByName = computed(
	() => quizQuestions.data?.questions_by_name || {}
)

// The PDF of this attempt (#33): the teacher-only download endpoint renders
// the same report server-side. Opened through the shared helper, so the URL
// clears the same allowlist every external window of the app does.
const downloadPdf = () => {
	openExternal(
		`/api/method/lms.lms.doctype.lms_quiz.quiz_attempt_report.download_attempt_report_pdf?submission=${encodeURIComponent(
			props.submission
		)}`
	)
}

const violationLog = createResource({
	url: 'lms.lms.doctype.lms_quiz.lms_quiz.get_quiz_violation_logs',
	makeParams() {
		return { submission: props.submission }
	},
	auto: true,
})

// Said in two places — the header spells it out, the popover carries it on a
// phone — so it is written once.
const ownSubmissionNotice = __('You cannot grade your own submission.')

const violationEventLabels = {
	tab_switch: __('Tab switched'),
	no_face: __('No face detected'),
	multiple_faces: __('Multiple faces'),
	focus_loss: __('Window focus lost'),
	camera_disconnect: __('Camera disconnected'),
}

// The submission carries the member's id but not their picture, and the doc
// lands after this page mounts, so the avatar is fetched once it does.
const memberImageResource = createResource({
	url: 'frappe.client.get_value',
	makeParams() {
		return {
			doctype: 'User',
			filters: submissionDetails.doc?.member || '',
			fieldname: 'user_image',
		}
	},
	auto: false,
})

watch(
	() => submissionDetails.doc?.member,
	(member) => {
		if (member) memberImageResource.fetch()
	},
	{ immediate: true }
)

const memberImage = computed(() => memberImageResource.data?.user_image || '')

const formatDate = (value) => {
	if (!value) return ''
	return new Date(value).toLocaleDateString(undefined, {
		year: 'numeric',
		month: 'short',
		day: 'numeric',
	})
}

const formatTime = (value) => {
	if (!value) return ''
	return new Date(value).toLocaleTimeString(undefined, {
		hour: '2-digit',
		minute: '2-digit',
		second: '2-digit',
	})
}

// Matches the `lg` breakpoint the sidebar itself switches on. useScreenSize()
// reports mobile below 640px, which would leave the log expanded through the
// whole band where it is already stacked full-width under the answers.
//
// Seeded into a ref rather than bound to `open` directly: bound, every render
// would re-assert the query and spring the panel back open under a reader who
// had just collapsed it. The @toggle handler writes their choice back.
const isDesktop = useMediaQuery('(min-width: 1024px)')
const logOpen = ref(isDesktop.value)

watch(isDesktop, (desktop) => {
	logOpen.value = desktop
})

// The log stores only these two severities, so anything else reads as the
// milder of them rather than surfacing a raw value.
const severityLabel = (severity) =>
	severity === 'violation' ? __('Violation') : __('Warning')

// The header renders before the doc lands, so this must not read `.quiz` off an
// undefined doc. Matches the list page: no quiz crumb, and no `?quiz=` back,
// which used to relocate the list.
const breadcrumbs = computed(() => {
	const crumbs = [
		{ label: __('Quizzes'), route: { name: 'Quizzes' } },
		{ label: __('Submissions'), route: { name: 'QuizSubmissions' } },
	]
	const doc = submissionDetails.doc
	if (doc) crumbs.push({ label: doc.member_name || doc.name })
	return crumbs
})

const isOwnSubmission = computed(
	() =>
		user.data?.is_instructor &&
		submissionDetails.doc?.member === user.data?.name
)

// --- Card #47: the two-part review of this attempt --------------------------------
// The review state resolves the way the server's report renderer does: the
// stored status first, an honest derivation from the rows for attempts sat
// before the field existed. Null when the attempt never awaited a teacher.
const reviewStatus = computed(() => submissionReviewStatus(submissionDetails.doc))

const resultRows = computed(() => submissionDetails.doc?.result || [])
const hasOpenQuestions = computed(() =>
	resultRows.value.some((row) => row.question_type == 'Open Ended')
)
const autoRows = computed(() =>
	resultRows.value.filter((row) => row.question_type != 'Open Ended')
)
const openRows = computed(() =>
	resultRows.value.filter((row) => row.question_type == 'Open Ended')
)

// The finish-review dialog's counts: what the teacher changed, what keeps its
// preliminary verdict, and what still waits for a verdict.
const overrideCount = computed(
	() => resultRows.value.filter((row) => row.teacher_override).length
)
const openUngradedCount = computed(
	() => openRows.value.filter((row) => !row.graded).length
)

// The second pass (card #47): editing an auto row's score IS the override.
// The verdict chip follows the teacher's mark - full marks reads correct -
// and the marker rides the payload's shape, not a client-side flag the
// endpoint would have to trust: touching an objective row is what the server
// stamps.
const markAutoRowDirty = (resultRow) => {
	resultRow.is_correct =
		Number(resultRow.marks) >= Number(resultRow.marks_out_of ?? 0) ? 1 : 0
	resultRow.teacher_override = 1
	markRowDirty(resultRow)
}

const showFinishReview = ref(false)
const finalizeResource = createResource({
	url: 'lms.lms.doctype.lms_quiz_submission.lms_quiz_submission.finalize_submission_review',
	makeParams() {
		return { submission: props.submission }
	},
})
const finishReview = () => {
	if (openUngradedCount.value > 0) {
		toast.error(
			__(
				'Grade every open-answer task first (question {0} of this list still has no verdict).'
			).format(openUngradedCount.value)
		)
		return
	}
	finalizeResource.submit(
		{},
		{
			onSuccess() {
				showFinishReview.value = false
				toast.success(__('Review finished. The result is final for the learner.'))
				submissionDetails.reload()
			},
			onError(err) {
				toast.error(err?.messages?.[0] || String(err))
			},
		}
	)
}

// Task #35 (D01): grades commit through the narrow server action, not the
// generic document save. Only rows the grader actually touched travel; the
// endpoint re-checks the reviewer's authority server-side.
const gradeResource = createResource({
	url: 'lms.lms.doctype.lms_quiz_submission.lms_quiz_submission.save_submission_grades',
})

// R06: per-row sequence numbers. A save in flight captures each dirty row's
// seq; on success only rows whose seq has NOT advanced since (no newer
// keystroke) are cleared, so edits typed during the request stay queued for
// the next save instead of being silently dropped.
const dirtyRows = ref(new Map())
const rowSeq = new Map()

const markRowDirty = (resultRow) => {
	const seq = (rowSeq.get(resultRow.name) || 0) + 1
	rowSeq.set(resultRow.name, seq)
	// Card #47: an objective row's edit also carries its re-derived verdict;
	// open rows keep the graded-flag contract of task #35.
	const isObjective = resultRow.question_type != 'Open Ended'
	dirtyRows.value.set(resultRow.name, {
		name: resultRow.name,
		marks: resultRow.marks ?? 0,
		graded: isObjective ? 1 : resultRow.graded ? 1 : 0,
		is_correct: isObjective ? (resultRow.is_correct ? 1 : 0) : undefined,
		seq,
	})
	autoSave()
}

const saveSubmission = (opts = {}) => {
	if (isOwnSubmission.value || !dirtyRows.value.size) return
	const batch = [...dirtyRows.value.values()]
	gradeResource.submit(
		{
			submission: props.submission,
			grades: batch.map(({ name, marks, graded, is_correct }) =>
				is_correct === undefined
					? { name, marks, graded }
					: { name, marks, graded, is_correct }
			),
		},
		{
			onSuccess() {
				for (const sent of batch) {
					const current = dirtyRows.value.get(sent.name)
					if (current && current.seq === sent.seq) {
						dirtyRows.value.delete(sent.name)
					}
				}
				if (!opts.silent) toast.success(__('Saved'))
			},
			onError(err) {
				toast.error(err.messages?.[0] || err)
			},
		}
	)
}

// Marks are typed one field at a time, so the grade is committed as it is
// entered rather than left to a Save the grader may never press.
const autoSave = useDebounceFn(() => {
	saveSubmission({ silent: true })
}, 1000)

onBeforeUnmount(() => {
	if (dirtyRows.value.size) saveSubmission({ silent: true })
})

usePageMeta(() => ({
	title: submissionDetails.doc?.quiz_title || __('Quiz Submission'),
	icon: brand.favicon,
}))
</script>
