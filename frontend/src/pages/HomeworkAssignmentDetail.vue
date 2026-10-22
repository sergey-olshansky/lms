<template>
	<div class="flex h-full flex-col">
		<PageHeader :breadcrumbs="breadcrumbs">
			<template #actions>
				<Button
					v-if="detail.data?.viewer_is_student && !detail.data?.cancelled"
					variant="solid"
					:disabled="!detail.data?.continue_target"
					@click="continueWorking"
				>
					{{ __('Continue') }}
				</Button>
				<template
					v-if="detail.data?.viewer_can_teach && !detail.data?.cancelled"
				>
					<Button
						v-if="detail.data?.status === 'Review'"
						variant="solid"
						data-testid="accept-button"
						@click="accept"
					>
						{{ __('Accept') }}
					</Button>
					<Button
						v-if="detail.data?.status === 'Review'"
						variant="subtle"
						data-testid="return-button"
						@click="commentDialog = 'return'"
					>
						{{ __('Return for rework') }}
					</Button>
					<Button
						v-if="detail.data?.status === 'Done'"
						variant="subtle"
						data-testid="reopen-button"
						@click="commentDialog = 'reopen'"
					>
						{{ __('Reopen') }}
					</Button>
					<Dropdown :options="teacherMenu">
						<Button variant="ghost">
							<template #icon>
								<span
									class="lucide-more-horizontal size-4"
									aria-hidden="true"
								/>
							</template>
						</Button>
					</Dropdown>
				</template>
			</template>
		</PageHeader>

		<div class="min-h-0 flex-1 overflow-y-auto px-4 pb-8 md:px-6">
			<div v-if="detail.loading" class="py-8 text-sm text-ink-gray-5">
				{{ __('Loading…') }}
			</div>
			<div v-else-if="!detail.data" class="py-8 text-sm text-ink-gray-5">
				{{ __('Not found') }}
			</div>
			<article
				v-else
				class="mx-auto max-w-3xl space-y-6"
				data-testid="homework-detail"
			>
				<header class="space-y-2">
					<div class="flex flex-wrap items-center gap-2">
						<h2 class="text-xl font-semibold text-ink-gray-9">
							{{ detail.data.title }}
						</h2>
						<span
							class="rounded-4 bg-surface-gray-3 px-2 py-0.5 text-sm text-ink-gray-7"
						>
							{{ statusLabel(detail.data.status) }}
						</span>
					</div>
					<p class="text-sm text-ink-gray-6">
						{{
							__('Assigned by {0} on {1}').format(
								detail.data.teacher_name,
								siteWallClock(detail.data.assigned_at_iso)
							)
						}}
					</p>
					<p class="text-sm text-ink-gray-6">
						{{ __('Due') }}:
						<span class="text-ink-gray-9">
							{{ formatDueAt(detail.data.due_at_iso) }}
						</span>
						<span
							v-if="detail.data.overdue"
							class="ml-2 rounded-4 bg-surface-red-2 px-1.5 py-0.5 text-xs text-ink-red-5"
						>
							{{ __('Overdue') }}
						</span>
						<span
							v-if="detail.data.submitted_late"
							class="ml-2 rounded-4 bg-surface-orange-1 px-1.5 py-0.5 text-xs text-ink-orange-5"
						>
							{{ __('Submitted after the deadline') }}
						</span>
					</p>
					<!-- E05: rich details render as the sanitized HTML they are;
					     a legacy plain-text description keeps its line breaks. -->
					<div
						v-if="detail.data.details && isRichDetails"
						class="hw-details-rich text-base text-ink-gray-8"
						v-safe-html:rich="detail.data.details"
						data-testid="homework-details-rich"
					></div>
					<p
						v-else-if="detail.data.details"
						class="whitespace-pre-line text-base text-ink-gray-8"
					>
						{{ detail.data.details }}
					</p>

					<!-- E05: the teacher's materials frozen into THIS assignment
					     (or the template's current set, before any issue). -->
					<div
						v-if="materialRows.length"
						class="rounded-4 border border-outline-gray-2"
						data-testid="homework-teacher-materials-view"
					>
						<div class="border-b border-outline-gray-2 px-4 py-2 text-sm text-ink-gray-8">
							{{ __('Teacher materials') }}
						</div>
						<div class="divide-y divide-outline-gray-1">
							<div
								v-for="row in materialRows"
								:key="row.name"
								class="flex items-center gap-2 px-4 py-2"
							>
								<span class="lucide-file size-4 shrink-0 text-ink-gray-5" aria-hidden="true" />
								<span class="min-w-0 flex-1 truncate text-sm text-ink-gray-8" :title="row.file_name">
									{{ row.file_name }}
								</span>
								<a
									v-if="row.file_url"
									:href="safeUrl(row.file_url)"
									:download="row.file_name || undefined"
									class="shrink-0 text-xs text-ink-gray-5 underline"
									:data-testid="`assignment-material-download-${row.name}`"
								>
									{{ __('Download') }}
								</a>
							</div>
						</div>
					</div>
				</header>

				<div
					v-if="detail.data.cancelled"
					class="rounded-6 border border-outline-gray-2 bg-surface-gray-1 p-3 text-sm text-ink-gray-6"
				>
					{{ __('This homework was recalled by the teacher.') }}
					{{ detail.data.cancellation_reason }}
				</div>

				<!-- E06: a work that must be solved by file never auto-submits.
				     When its materials are done the card sits In Progress,
				     "ready to submit", until the student attaches a solution
				     and presses Send -- the button is disabled (with the
				     reason) until both hold. -->
				<div
					v-if="
						detail.data.viewer_is_student &&
						detail.data.require_solution &&
						detail.data.status === 'In Progress' &&
						!detail.data.needs_revision &&
						!detail.data.cancelled
					"
					class="rounded-6 border border-outline-gray-2 bg-surface-gray-1 p-3 text-sm"
					data-testid="solution-submit-panel"
				>
					<p class="font-medium text-ink-gray-9">
						{{ allConfirmed ? __('Ready to submit') : __('Finish the work first') }}
					</p>
					<p class="mt-1 text-ink-gray-6">
						{{
							__(
								'This homework needs your file solution: attach it below, then send the work for review.'
							)
						}}
					</p>
					<Button
						variant="solid"
						size="sm"
						class="mt-2"
						data-testid="solution-submit-button"
						:disabled="!allConfirmed || solutionUploading"
						@click="submitSolution"
					>
						{{ __('Send for review') }}
					</Button>
					<p
						v-if="allConfirmed && !hasSolutionFile"
						class="mt-1 text-xs text-ink-gray-5"
					>
						{{ __('Attach at least one solution file first.') }}
					</p>
				</div>

				<div
					v-if="detail.data.needs_revision"
					class="rounded-6 border border-outline-gray-2 bg-surface-orange-1 p-3 text-sm text-ink-gray-9"
					data-testid="revision-banner"
				>
					<p class="font-medium">{{ __('Needs rework') }}</p>
					<p class="mt-1 whitespace-pre-line">
						{{ detail.data.last_revision_comment }}
					</p>
					<Button
						v-if="detail.data.viewer_is_student && !detail.data.cancelled"
						variant="outline"
						size="sm"
						class="mt-2"
						data-testid="resubmit-button"
						:disabled="!allConfirmed"
						@click="resubmit"
					>
						{{ __('Send for review again') }}
					</Button>
					<p v-if="!allConfirmed" class="mt-1 text-xs">
						{{
							__(
								'Finish the remaining requirements to send it for review again.'
							)
						}}
					</p>
				</div>

				<!-- Checklist grouped by course and chapter (spec 5.3) -->
				<section
					v-for="(chapters, courseName) in groupedRequirements"
					:key="courseName"
					class="space-y-3"
					:data-testid="`checklist-course-${courseName}`"
				>
					<h3
						class="text-sm font-medium uppercase tracking-wide text-ink-gray-5"
					>
						{{ courseTitle(courseName) }}
					</h3>
					<div
						v-for="(rows, chapterTitle) in chapters"
						:key="chapterTitle"
						class="rounded-6 border border-outline-gray-2"
					>
						<p
							v-if="chapterTitle"
							class="border-b border-outline-gray-2 px-4 py-2 text-sm font-medium text-ink-gray-7"
						>
							{{ chapterTitle }}
						</p>
						<div class="divide-y divide-outline-gray-1">
							<div v-for="row in rows" :key="rowKey(row)" class="px-4 py-2">
								<div class="flex items-start gap-3">
									<span
										class="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-4 border"
										:class="stateClass(row)"
										:aria-label="row.state_label"
									>
										<span
											v-if="isDone(row)"
											class="lucide-check size-3.5"
											aria-hidden="true"
										/>
										<span
											v-else-if="row.status === 'Awaiting Grading'"
											class="lucide-hourglass size-3.5"
											aria-hidden="true"
										/>
									</span>
									<span class="min-w-0 flex-1">
										<span
											class="block truncate text-sm text-ink-gray-9"
											:title="row.path"
										>
											{{ row.label }}
										</span>
										<span
											class="block truncate text-xs text-ink-gray-5"
											:title="row.path"
										>
											{{ row.path }}
										</span>
									</span>
									<span
										class="shrink-0 rounded-4 px-1.5 py-0.5 text-xs"
										:class="stateTextClass(row)"
									>
										{{ row.state_label }}
									</span>
									<!-- U02: an exhausted attempt limit is the one reason a
									     stuck card may have that the checklist alone never
									     shows. Teacher-only, with the count and a link to the
									     existing review mechanism; never a limit reset. -->
									<span
										v-if="
											detail.data.viewer_can_teach &&
											row.attempts_exhausted
										"
										class="shrink-0 rounded-4 bg-surface-orange-1 px-1.5 py-0.5 text-xs text-ink-orange-5"
										:data-testid="`attempts-exhausted-${row.quiz}`"
									>
										{{
											__('{0} of {1} attempts used').format(
												String(row.attempts_used ?? 0),
												String(row.attempts_max ?? 0)
											)
										}}
									</span>
									<router-link
										v-if="
											detail.data.viewer_can_teach &&
											row.attempts_exhausted &&
											row.latest_submission
										"
										:to="{
											name: 'QuizSubmission',
											params: { submission: row.latest_submission },
										}"
										class="shrink-0 text-xs text-ink-gray-5 underline"
									>
										{{ __('Review latest attempt') }}
									</router-link>
									<router-link
										v-if="row.route && row.status !== 'Unavailable'"
										:to="rowRoute(row.route)"
										class="shrink-0 text-xs text-ink-gray-5 underline"
										:data-testid="`open-material-${row.lesson || row.quiz}`"
									>
										{{ __('Open') }}
									</router-link>
									<router-link
										v-if="row.quiz"
										:to="attemptRoute(row)"
										class="shrink-0 text-xs text-ink-gray-5 underline"
										:data-testid="`attempt-${row.quiz}`"
									>
										{{ attemptLinkLabel(row) }}
									</router-link>
								</div>

								<!-- Spec 5.3.4: the quizzes of a selected lesson are
								expandable sub-rows of that lesson, each with its own
								state and, when passed, the attempt link. -->
								<div
									v-if="quizzesOf(row).length"
									class="mt-1 ms-8 divide-y divide-outline-gray-1 rounded-4 border border-outline-gray-2"
								>
									<button
										type="button"
										class="flex w-full items-center gap-2 px-2 py-1 text-start text-xs text-ink-gray-6 hover:bg-surface-gray-1"
										:aria-expanded="quizExpanded(rowKey(row))"
										:data-testid="`quiz-toggle-${row.lesson}`"
										@click="toggleQuizzes(rowKey(row))"
									>
										<span
											class="block size-3.5 transition-transform"
											:class="
												quizExpanded(rowKey(row))
													? 'lucide-chevron-down'
													: 'lucide-chevron-right'
											"
										/>
										{{
											__('{0} quizzes').format(String(quizzesOf(row).length))
										}}
									</button>
									<div v-if="quizExpanded(rowKey(row))">
										<div
											v-for="quiz in quizzesOf(row)"
											:key="rowKey(quiz)"
											class="flex items-start gap-3 px-2 py-1.5"
										>
											<span
												class="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-4 border text-[10px]"
												:class="stateClass(quiz)"
												:aria-label="quiz.state_label"
											>
												<span
													v-if="isDone(quiz)"
													class="lucide-check size-3"
													aria-hidden="true"
												/>
												<span
													v-else-if="quiz.status === 'Awaiting Grading'"
													class="lucide-hourglass size-3"
													aria-hidden="true"
												/>
											</span>
											<span
												class="min-w-0 flex-1 truncate text-xs text-ink-gray-7"
												:title="quiz.path"
											>
												{{ quiz.label }}
											</span>
											<span
												class="shrink-0 rounded-4 px-1.5 py-0.5 text-[10px]"
												:class="stateTextClass(quiz)"
											>
												{{ quiz.state_label }}
											</span>
											<router-link
												v-if="quiz.quiz"
												:to="attemptRoute(quiz)"
												class="shrink-0 text-[10px] text-ink-gray-5 underline"
												:data-testid="`attempt-${quiz.quiz}`"
											>
												{{ attemptLinkLabel(quiz) }}
											</router-link>
										</div>
									</div>
								</div>
							</div>
						</div>
					</div>
				</section>

				<!-- Progress summary -->
				<section
					class="rounded-6 bg-surface-gray-1 p-4 text-sm text-ink-gray-7"
				>
					{{
						__('{0} of {1} requirements done').format(
							String(detail.data.completed_requirements),
							String(detail.data.total_requirements)
						)
					}}
				</section>

				<!-- Task #35 (E03): the student's optional solution files. Purely
				     additive: attaching nothing changes no requirement, no
				     status and no review decision. -->
				<HomeworkSolutionFiles :detail="detail" ref="solutionFiles" @state="onSolutionState" />

				<!-- History (spec 5.3.5) -->
				<section class="space-y-2">
					<h3 class="text-sm font-medium text-ink-gray-7">
						{{ __('History') }}
					</h3>
					<ol class="space-y-2">
						<li
							v-for="event in detail.data.history"
							:key="event.creation"
							class="rounded-4 border border-outline-gray-2 px-3 py-2 text-sm"
						>
							<p class="text-ink-gray-8">
								<span class="font-medium">{{ event.actor_name }}</span>
								· {{ eventLabel(event.event) }}
								<template v-if="event.from_status || event.to_status">
									({{ statusLabel(event.from_status) }} →
									{{ statusLabel(event.to_status) }})
								</template>
							</p>
							<p class="text-xs text-ink-gray-5">
								{{ dayjs(event.creation).format('DD.MM.YYYY HH:mm') }}
							</p>
							<p
								v-if="event.comment"
								class="mt-1 whitespace-pre-line text-ink-gray-7"
							>
								{{ event.comment }}
							</p>
						</li>
					</ol>
				</section>
			</article>
		</div>

		<Dialog
			v-if="commentDialog"
			:open="true"
			:title="
				commentDialog === 'return'
					? __('Return for rework')
					: commentDialog === 'reopen'
					? __('Reopen homework')
					: __('Change deadline')
			"
			size="md"
			@update:open="(value) => (value ? null : (commentDialog = ''))"
		>
			<template #default>
				<div class="space-y-3">
					<FormControl
						v-if="commentDialog !== 'deadline'"
						type="textarea"
						v-model="actionComment"
						rows="4"
						:label="__('Comment')"
						:required="true"
					/>
					<FormControl
						v-if="commentDialog === 'deadline'"
						type="number"
						v-model="actionDays"
						:min="1"
						:label="__('For how many days')"
					/>
				</div>
			</template>
			<template #actions>
				<Button variant="subtle" @click="commentDialog = ''">{{
					__('Cancel')
				}}</Button>
				<Button variant="solid" :loading="acting" @click="runCommentAction">
					{{ __('Confirm') }}
				</Button>
			</template>
		</Dialog>

		<Dialog
			v-if="revokeOpen"
			:open="true"
			:title="__('Recall homework')"
			size="md"
			@update:open="(value) => (value ? null : (revokeOpen = false))"
		>
			<template #default>
				<FormControl
					type="textarea"
					v-model="revokeReason"
					rows="3"
					:label="__('Reason')"
					:required="true"
				/>
			</template>
			<template #actions>
				<Button variant="subtle" @click="revokeOpen = false">{{
					__('Cancel')
				}}</Button>
				<Button variant="solid" theme="red" :loading="acting" @click="revoke">
					{{ __('Recall') }}
				</Button>
			</template>
		</Dialog>
	</div>
</template>

<script setup>
// The assignment's own address (spec 5.3): checklist grouped by course and
// chapter, read-only progress states with text labels, the revision comment and
// history, and the role-scoped actions. The student's first open of this page
// starts execution (A15); a teacher's open never does (A14).
import {
	Button,
	Dialog,
	Dropdown,
	FormControl,
	call,
	createResource,
	toast,
} from 'frappe-ui'
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/Layouts/pages/PageHeader.vue'
import HomeworkSolutionFiles from '@/components/HomeworkSolutionFiles.vue'
import { lessonRouteParams } from '@/utils/homeworkSelection'
import { resourceErrorMessage } from '@/utils/resource'
import { formatDueAt, siteWallClock } from '@/utils/dueDate'
import { downloadViaAnchor } from '@/utils/download'
import { safeUrl } from '@/utils/safeUrl'

const route = useRoute()
const router = useRouter()
const dayjs = inject('$dayjs')
// E01: the guest-vs-signed distinction the login return needs (a guest has
// no user data at all).
const user = inject('$user')

const props = defineProps({ assignmentID: { type: String, required: true } })

const STATUS_LABELS = {
	'To Do': 'To Do',
	'In Progress': 'In Progress',
	Review: 'Review',
	Done: 'Done',
}
const statusLabel = (status) => __(STATUS_LABELS[status] || status || '')

const EVENT_LABELS = {
	assigned: 'Assigned',
	started: 'Started',
	submitted_for_review: 'Sent for review',
	accepted: 'Accepted',
	returned_for_revision: 'Returned for rework',
	resubmitted: 'Sent again',
	reopened: 'Reopened',
	deadline_changed: 'Deadline changed',
	revoked: 'Recalled',
	requirement_invalidated: 'Result invalidated',
}
const eventLabel = (event) => __(EVENT_LABELS[event] || event)

const detail = createResource({
	url: 'lms.lms.homework_api.get_homework_assignment',
	makeParams: () => ({ name: props.assignmentID }),
})

// E03: the solution-files panel reloads with the card so a status change
// (review submitted, accepted, returned) flips its editability at once.
const solutionFiles = ref(null)
watch(
	() => detail.data?.status,
	() => {
		if (detail.data?.name) solutionFiles.value?.reload?.()
	}
)

onMounted(async () => {
	// B11: read the card FIRST -- the payload's viewer_is_student is the
	// structured role signal. Only the student's own open starts execution, so a
	// teacher's preview fires no student-only action at all and no suppressed
	// error toast is needed (the old locale-string sniffing is gone). The state
	// the opening produced is read back with a second reload -- a fully
	// pre-credited card arrives already in Review. frappe-ui's `call` returns a
	// real promise; wiring resolve/reject through resource.update() never
	// settles (R01).
	try {
		const payload = await detail.reload()
		if (!payload?.viewer_is_student) return
		await call('lms.lms.homework_api.open_homework', {
			assignment: props.assignmentID,
		})
	} catch (error) {
		// E01: on a guest-access site the router lets a Guest through, but the
		// card itself is never public -- the API refuses. A guest here is
		// offered the login that returns them to exactly this page; a signed-in
		// viewer who merely lacks this card keeps the plain refusal (no data
		// leak, no redirect loop).
		if (!user.data?.name) {
			const target = `${window.location.pathname}${window.location.search}${window.location.hash}`
			window.location.href = `/login?redirect-to=${encodeURIComponent(target)}`
			return
		}
		toast.error(resourceErrorMessage(error, __('Error')))
		return
	}
	detail.reload()
})

// Spec 5.3.4: a lesson's quizzes render as expandable sub-rows of that lesson,
// so quiz rows with a lesson are pulled out of the flat list here and handed
// back through quizzesOf(). Standalone quizzes (no lesson) stay top-level.
const quizzesOf = (lessonRow) =>
	(detail.data?.requirements || []).filter(
		(row) =>
			row.requirement_type === 'Pass Quiz' && row.lesson === lessonRow.lesson
	)

const expandedQuizLessons = ref(new Set())
const quizExpanded = (key) => expandedQuizLessons.value.has(key)
const toggleQuizzes = (key) => {
	const next = new Set(expandedQuizLessons.value)
	if (next.has(key)) next.delete(key)
	else next.add(key)
	expandedQuizLessons.value = next
}

const groupedRequirements = computed(() => {
	const groups = {}
	const all = detail.data?.requirements || []
	const nested = new Set(
		all
			.filter((row) => row.requirement_type === 'Pass Quiz' && row.lesson)
			.map(rowKey)
	)
	for (const row of all) {
		if (nested.has(rowKey(row))) continue
		const course = row.course || '—'
		const chapter = row.chapter_title || ''
		groups[course] = groups[course] || {}
		groups[course][chapter] = groups[course][chapter] || []
		groups[course][chapter].push(row)
	}
	return groups
})

// R18: the course titles ship with the assignment payload itself -- the
// student's checklist must not depend on the teacher's course list.
const courseTitles = computed(() => detail.data?.course_titles || {})
const courseTitle = (name) => courseTitles.value[name] || name

const isDone = (row) =>
	row.status === 'Completed' || row.status === 'Completed Earlier'
// E05: rich details render sanitized; plain text keeps its line breaks.
const isRichDetails = computed(() =>
	/<[a-z][\s\S]*>/i.test(detail.data?.details || '')
)

// E05: the frozen teacher materials of this assignment -- every row carries
// its private download URL.
const materialRows = computed(() => {
	const rows = detail.data?.materials || []
	return rows.filter((row) => row.role === 'Material' || row.role === 'Detail Image')
})

// E06: the student's current solution files -- the explicit Send waits for
// both the requirements and a file to exist.
const solutionRows = ref([])
const hasSolutionFile = computed(() => solutionRows.value.length > 0)
const onSolutionState = (payload) => {
	solutionRows.value = payload?.rows || []
}

const allConfirmed = computed(() => {
	const data = detail.data
	return Boolean(
		data &&
			data.total_requirements > 0 &&
			data.completed_requirements >= data.total_requirements
	)
})
const stateClass = (row) => {
	if (isDone(row))
		return 'border-outline-gray-3 bg-surface-green-2 text-ink-green-5'
	if (row.status === 'Awaiting Grading')
		return 'border-outline-gray-3 bg-surface-orange-1 text-ink-orange-5'
	if (row.status === 'Unavailable')
		return 'border-outline-gray-3 bg-surface-gray-2 text-ink-gray-5'
	return 'border-outline-red-2 bg-surface-red-1 text-ink-red-5'
}
const stateTextClass = (row) => {
	if (isDone(row)) return 'bg-surface-green-2 text-ink-green-5'
	if (row.status === 'Awaiting Grading')
		return 'bg-surface-orange-1 text-ink-orange-5'
	if (row.status === 'Unavailable') return 'bg-surface-gray-2 text-ink-gray-5'
	return 'bg-surface-red-1 text-ink-red-5'
}
const rowKey = (row) =>
	row.id ||
	[row.requirement_type, row.lesson, row.quiz, row.reference_assignment]
		.filter(Boolean)
		.join(':')

// R18: a detail left open goes stale while the other side works; a controlled
// refetch on visibility/focus keeps it current, with listeners cleaned up.
const refetchIfVisible = () => {
	if (document.visibilityState === 'visible' && detail.data) detail.reload()
}
onMounted(() => {
	window.addEventListener('focus', refetchIfVisible)
	document.addEventListener('visibilitychange', refetchIfVisible)
})
onUnmounted(() => {
	window.removeEventListener('focus', refetchIfVisible)
	document.removeEventListener('visibilitychange', refetchIfVisible)
})

const breadcrumbs = computed(() => [
	{ label: __('Homework execution'), route: { name: 'HomeworkExecution' } },
	{
		label: detail.data?.title || '…',
		route: {
			name: 'HomeworkDetail',
			params: { assignmentID: props.assignmentID },
		},
	},
])

// A checklist row's own link into the real course page (spec 5.3.3), carrying
// the homework context so the way back is right there after opening. Numbers
// are the outline's multi-segment route numbers (task #28: "2-1-3").
const rowRoute = (route) => {
	if (!route) return null
	if (route.type === 'lesson' && route.number) {
		return {
			name: 'Lesson',
			params: {
				courseName: route.course,
				...lessonRouteParams(route.number),
			},
			query: { hw: props.assignmentID },
		}
	}
	if (route.type === 'quiz') {
		return {
			name: 'QuizPage',
			params: { quizID: route.quiz },
			query: { hw: props.assignmentID },
		}
	}
	if (route.type === 'assignment') {
		return {
			name: 'AssignmentSubmission',
			params: { assignmentID: route.assignment, submissionName: 'new' },
			query: { hw: props.assignmentID },
		}
	}
	return null
}

// B11: the quiz link is ADDRESSABLE. A confirmed row carries its proof -- the
// very submission that earned the pass, which may not be the newest attempt --
// so the link opens that attempt's own report on the quiz page. An unfinished
// row still links to a fresh attempt of the quiz itself.
const attemptRoute = (row) => ({
	name: 'QuizPage',
	params: { quizID: row.quiz },
	query: {
		hw: props.assignmentID,
		...(isDone(row) && row.proof_name ? { submission: row.proof_name } : {}),
	},
})

const attemptLinkLabel = (row) =>
	isDone(row) && row.proof_name ? __('Report') : __('Attempt')

const continueWorking = () => {
	const target = detail.data?.continue_target
	if (!target) return
	if (target.type === 'lesson' && target.course && target.number) {
		router.push({
			name: 'Lesson',
			params: {
				courseName: target.course,
				...lessonRouteParams(target.number),
			},
			query: { hw: props.assignmentID },
		})
	} else if (target.type === 'quiz' && target.quiz) {
		router.push({
			name: 'QuizPage',
			params: { quizID: target.quiz },
			query: { hw: props.assignmentID },
		})
	} else if (target.type === 'assignment' && target.assignment) {
		router.push({
			name: 'AssignmentSubmission',
			params: { assignmentID: target.assignment, submissionName: 'new' },
			query: { hw: props.assignmentID },
		})
	}
}

const acting = ref(false)
const commentDialog = ref('')
const actionComment = ref('')
const actionDays = ref(7)
const revokeOpen = ref(false)
const revokeReason = ref('')

const teacherMenu = computed(() => [
	{
		// E01: the card's own permanent address, ready to paste into any
		// channel. The link grants nothing by itself -- the server re-checks
		// the viewer on open -- and a guest landing on it comes straight back
		// after login through the redirect the router attaches.
		label: copied.value ? __('Link copied') : __('Copy link for student'),
		icon: copied.value ? 'lucide-check' : 'lucide-link',
		onClick: copyStudentLink,
	},
	{
		// E02: the frozen snapshot PDF -- student, term, materials with links.
		label: __('Download PDF'),
		icon: 'lucide-file-down',
		onClick: downloadAssignmentPdf,
	},
	{
		label: __('Change deadline'),
		icon: 'lucide-calendar-clock',
		onClick: () => {
			actionDays.value = detail.data?.days || 7
			commentDialog.value = 'deadline'
		},
	},
	{
		label: __('Recall'),
		icon: 'lucide-undo-2',
		onClick: () => {
			revokeReason.value = ''
			revokeOpen.value = true
		},
	},
])

function downloadAssignmentPdf() {
	// F04: a real download through a programmatic anchor -- the server sets
	// Content-Disposition, no popup involved.
	downloadViaAnchor(
		`/api/method/lms.lms.homework_pdf.download_homework_assignment_pdf?name=${encodeURIComponent(
			props.assignmentID
		)}`
	)
}

// E01: the full origin + SPA path of THIS card, so the link works from mail,
// chat and external readers alike.
const studentLink = computed(() => {
	if (!detail.data?.name) return ''
	const basePath = window.lms_path ? `/${window.lms_path}` : '/lms'
	return `${window.location.origin}${basePath}/homework/assignment/${detail.data.name}`
})

const copied = ref(false)

async function copyStudentLink() {
	try {
		await navigator.clipboard.writeText(studentLink.value)
		copied.value = true
		setTimeout(() => (copied.value = false), 2000)
	} catch {
		toast.error(__('Could not copy the link'))
	}
}

const callAction = (url, params) =>
	new Promise((resolve, reject) => {
		createResource({
			url,
			params,
			auto: true,
			onSuccess: resolve,
			onError: reject,
		})
	})

const runAction = async (promise, successMessage) => {
	acting.value = true
	try {
		await promise
		toast.success(__(successMessage))
		detail.reload()
	} catch (err) {
		toast.error(resourceErrorMessage(err, __('Error')))
		console.error(err)
	}
	acting.value = false
}

const accept = () =>
	runAction(
		callAction('lms.lms.homework_api.accept_homework', {
			assignment: props.assignmentID,
		}),
		'Accepted'
	)

const submitSolution = () =>
	runAction(
		callAction('lms.lms.homework_api.submit_homework_solution', {
			assignment: props.assignmentID,
		}),
		'Sent for review'
	)

const resubmit = () =>
	runAction(
		callAction('lms.lms.homework_api.resubmit_homework', {
			assignment: props.assignmentID,
		}),
		'Sent for review'
	)

const runCommentAction = () => {
	const comment = actionComment.value.trim()
	if (commentDialog.value === 'deadline') {
		const days = Number(actionDays.value)
		if (!Number.isInteger(days) || days < 1) {
			toast.error(__('Number of days must be a whole number of at least 1'))
			return
		}
		commentDialog.value = ''
		return runAction(
			callAction('lms.lms.homework_api.change_homework_deadline', {
				assignment: props.assignmentID,
				days,
			}),
			'Deadline changed'
		)
	}
	if (!comment) {
		toast.error(__('A comment is required'))
		return
	}
	const kind = commentDialog.value
	commentDialog.value = ''
	const url =
		kind === 'return'
			? 'lms.lms.homework_api.return_homework'
			: 'lms.lms.homework_api.reopen_homework'
	return runAction(
		callAction(url, { assignment: props.assignmentID, comment }),
		'Saved'
	)
}

const revoke = async () => {
	const reason = revokeReason.value.trim()
	if (!reason) {
		toast.error(__('A reason is required'))
		return
	}
	revokeOpen.value = false
	await runAction(
		callAction('lms.lms.homework_api.revoke_homework', {
			assignment: props.assignmentID,
			reason,
		}),
		'Recalled'
	)
	router.push({ name: 'HomeworkExecution' })
}
</script>
