<template>
	<div class="flex h-full flex-col">
		<PageHeader :breadcrumbs="breadcrumbs">
			<template #actions>
				<!-- E08: the teacher flips between one student's board and the
				     overview of ALL their issued work. -->
				<Button
					v-if="canPickStudent"
					variant="subtle"
					size="sm"
					data-testid="overview-toggle"
					@click="overviewOpen = !overviewOpen"
				>
					{{ overviewOpen ? __('Student board') : __('All my students') }}
				</Button>
				<Select
					v-if="canPickStudent && !overviewOpen"
					v-model="student"
					:options="studentOptions"
					:placeholder="__('Student')"
					data-testid="board-student-select"
				/>
			</template>
		</PageHeader>

		<div class="flex flex-wrap items-center gap-2 px-4 pb-2 md:px-6">
			<FormControl
				type="text"
				v-model="search"
				:placeholder="__('Search')"
				:aria-label="__('Search')"
			>
				<template #prefix>
					<span class="lucide-search size-4 text-ink-gray-5" />
				</template>
			</FormControl>
			<Select
				v-model="statusFilter"
				:options="statusOptions"
				:placeholder="__('Status')"
			/>
			<Select
				v-if="canPickStudent"
				v-model="courseFilter"
				:options="courseOptions"
				:placeholder="__('Course')"
			/>
			<BooleanSwitch v-model="overdueOnly" size="sm" :label="__('Overdue')" />
			<BooleanSwitch
				v-model="cancelledOnly"
				size="sm"
				:label="__('Recalled')"
				data-testid="board-cancelled-switch"
			/>
		</div>
		<!-- E08: the overview table -- one row per issued assignment, full
		     server-side counts and paging, a jump to the card or the board. -->
		<div v-if="overviewOpen && canPickStudent" class="px-4 pb-2 md:px-6">
			<div class="mb-2 flex flex-wrap items-center gap-2 text-xs">
				<span
					v-for="(count, label) in overviewCounts"
					:key="label"
					class="rounded-4 bg-surface-gray-2 px-2 py-1 text-ink-gray-7"
					:data-testid="`overview-count-${label}`"
				>
					{{ statusLabel(label) }}: {{ count }}
				</span>
			</div>
			<div class="overflow-x-auto rounded-6 border border-outline-gray-2">
				<table class="w-full min-w-[760px] text-sm" data-testid="homework-overview">
					<thead class="bg-surface-gray-1 text-left text-xs text-ink-gray-5">
						<tr>
							<th class="px-3 py-2">{{ __('Student') }}</th>
							<th class="px-3 py-2">{{ __('Homework') }}</th>
							<th class="px-3 py-2">{{ __('Status') }}</th>
							<th class="px-3 py-2">{{ __('Done') }}</th>
							<th class="px-3 py-2">{{ __('Quizzes') }}</th>
							<th class="px-3 py-2">{{ __('Due') }}</th>
							<th class="px-3 py-2">{{ __('Sent') }}</th>
							<th class="px-3 py-2"></th>
						</tr>
					</thead>
					<tbody class="divide-y divide-outline-gray-1">
						<tr
							v-for="row in overviewRows"
							:key="row.name"
							:data-testid="`overview-row-${row.name}`"
						>
							<td class="px-3 py-2">{{ row.student_name }}</td>
							<td class="px-3 py-2">
								<router-link
									:to="{ name: 'HomeworkDetail', params: { assignmentID: row.name } }"
									class="text-ink-gray-9 underline"
								>
									{{ row.title }}
								</router-link>
							</td>
							<td class="px-3 py-2">
								{{ statusLabel(row.status) }}
								<span
									v-if="row.needs_revision"
									class="ml-1 rounded-4 bg-surface-orange-1 px-1.5 py-0.5 text-xs text-ink-orange-5"
								>
									{{ __('Needs rework') }}
								</span>
							</td>
							<td class="px-3 py-2">
								{{ row.completed_requirements }}/{{ row.total_requirements }}
							</td>
							<td class="px-3 py-2">
								{{ row.quizzes_completed }}/{{ row.quizzes_total }}
							</td>
							<td class="px-3 py-2">
								<span :class="row.overdue ? 'text-ink-red-5' : ''">
									{{ siteWallClockShort(row.due_at_iso) }}
								</span>
							</td>
							<td class="px-3 py-2 text-xs text-ink-gray-5">
								{{ siteWallClockShort(toIso(row.submitted_for_review_at)) || '—' }}
							</td>
							<td class="px-3 py-2">
								<Button
									variant="ghost"
									size="sm"
									@click="openStudentBoard(row.student)"
								>
									{{ __('Board') }}
								</Button>
							</td>
						</tr>
						<tr v-if="!overviewRows.length">
							<td colspan="8" class="px-3 py-4 text-sm text-ink-gray-5">
								{{ overview.loading ? __('Loading…') : __('No homework found') }}
							</td>
						</tr>
					</tbody>
				</table>
			</div>
			<div class="mt-2 flex items-center gap-2">
				<Button
					v-if="overview.data && overview.data.total > overviewRows.length"
					variant="subtle"
					size="sm"
					@click="overviewOffset += 25"
				>
					{{ __('Load more') }}
				</Button>
				<span class="text-xs text-ink-gray-5">
					{{ __('{0} of {1}').format(String(overviewRows.length), String(overview.data?.total ?? 0)) }}
				</span>
			</div>
		</div>

		<p
			v-if="cancelledOnly && !overviewOpen"
			class="px-4 pb-2 text-sm text-ink-gray-5 md:px-6"
			data-testid="board-cancelled-note"
		>
			{{ __('Recalled assignments: history only, no updates.') }}
		</p>

		<div
			v-if="!overviewOpen"
			class="board-scroll min-h-0 flex-1 overflow-x-auto overflow-y-auto px-4 pb-4 md:px-6"
			data-testid="homework-board"
		>
			<div class="flex h-full min-w-[720px] items-start gap-4">
				<section
					v-for="column in columns"
					:key="column.status"
					class="flex w-[260px] shrink-0 flex-col rounded-6 bg-surface-gray-2"
					:aria-label="statusLabel(column.status)"
					:data-testid="`board-column-${column.status}`"
				>
					<header class="flex items-center justify-between px-3 pt-3">
						<span class="text-sm font-medium text-ink-gray-7">
							{{ statusLabel(column.status) }}
						</span>
						<span
							class="rounded-4 bg-surface-gray-4 px-1.5 py-0.5 text-xs text-ink-gray-6"
							:data-testid="`board-count-${column.status}`"
						>
							{{ column.count }}
						</span>
					</header>

					<div class="flex flex-1 flex-col gap-2 overflow-y-auto p-2">
						<p
							v-if="!column.cards.length"
							class="px-1 py-3 text-center text-xs text-ink-gray-5"
						>
							{{ __('Nothing here') }}
						</p>

						<article
							v-for="card in column.cards"
							:key="card.name"
							class="cursor-pointer rounded-6 border border-outline-gray-2 bg-surface-base p-3 shadow-sm transition-shadow hover:shadow-md"
							:data-testid="`board-card-${card.name}`"
							tabindex="0"
							role="button"
							:aria-label="card.title"
							@click="openCard(card)"
							@keydown.enter="openCard(card)"
						>
							<h4
								class="text-sm font-medium text-ink-gray-9"
								:title="card.title"
							>
								{{ card.title }}
							</h4>
							<p class="mt-0.5 text-xs text-ink-gray-5">
								{{ card.teacher_name }}
							</p>

							<div class="mt-2 flex flex-wrap items-center gap-1">
								<span
									class="rounded-4 px-1.5 py-0.5 text-xs"
									:class="
										card.overdue
											? 'bg-surface-red-2 text-ink-red-5'
											: 'bg-surface-gray-3 text-ink-gray-7'
									"
								>
									<span
										:class="
											card.overdue ? 'lucide-alarm-clock' : 'lucide-calendar'
										"
										class="mr-1 inline-block size-3 align-[-2px]"
										aria-hidden="true"
									/>
									{{ dueLabel(card) }}
									{{ card.overdue ? ' · ' + __('Overdue') : '' }}
								</span>
								<span
									v-if="card.submitted_late"
									class="rounded-4 bg-surface-orange-1 px-1.5 py-0.5 text-xs text-ink-orange-5"
								>
									{{ __('Submitted after the deadline') }}
								</span>
								<span
									v-if="card.needs_revision"
									class="rounded-4 bg-surface-orange-1 px-1.5 py-0.5 text-xs text-ink-orange-6"
								>
									{{ __('Needs rework') }}
								</span>
							</div>

							<div class="mt-2">
								<div
									class="h-1.5 w-full overflow-hidden rounded-full bg-surface-gray-3"
								>
									<div
										class="h-full rounded-full bg-surface-green-7"
										:style="{ width: progressPercent(card) + '%' }"
									/>
								</div>
								<p class="mt-1 text-xs text-ink-gray-6">
									{{ progressLine(card) }}
									<template v-if="card.quizzes_total">
										· {{ __('quizzes') }}
									</template>
								</p>
							</div>

							<Button
								v-if="card.continue_target && column.status !== 'Done'"
								variant="outline"
								size="sm"
								class="mt-2 w-full"
								:aria-label="__('Continue')"
								@click.stop="continueCard(card)"
							>
								{{ __('Continue') }}
							</Button>
						</article>

						<Button
							v-if="column.has_more"
							variant="subtle"
							size="sm"
							class="w-full"
							@click="loadMore(column.status)"
						>
							{{ __('Load more') }}
						</Button>
					</div>
				</section>
			</div>
		</div>
	</div>
</template>

<script setup>
// The execution board (spec 5.1): four columns, full counts, per-column paging,
// filters in the query string. A student always sees their own board -- the
// `student` URL parameter is never the authority, the server re-checks it. A
// teacher picks a student and the whole board state is re-fetched with the new
// target, so no card of the previous student survives the switch (A33).
import { Button, FormControl, call, createResource, toast } from 'frappe-ui'
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/Layouts/pages/PageHeader.vue'
import Select from '@/components/Controls/Select.vue'
import BooleanSwitch from '@/components/Controls/BooleanSwitch.vue'
import { lessonRouteParams, progressLine } from '@/utils/homeworkSelection'
import { resourceErrorMessage } from '@/utils/resource'
import { siteWallClockShort } from '@/utils/dueDate'

const route = useRoute()
const router = useRouter()
const user = inject('$user')

const BOARD_STATUSES = ['To Do', 'In Progress', 'Review', 'Done']
const STATUS_LABELS = {
	'To Do': 'To Do',
	'In Progress': 'In Progress',
	Review: 'Review',
	Done: 'Done',
}
const statusLabel = (status) => __(STATUS_LABELS[status] || status)

const canPickStudent = computed(() =>
	Boolean(
		user.data?.is_moderator ||
			user.data?.is_instructor ||
			user.data?.is_evaluator
	)
)

const student = ref(String(route.query.student || ''))
const search = ref(String(route.query.title || ''))
const statusFilter = ref(String(route.query.status || ''))
const courseFilter = ref(String(route.query.course || ''))
const overdueOnly = ref(Boolean(route.query.overdue))
// The recalled-assignments history (spec 8.1): a separate read-only view, not a
// fifth board column.
const cancelledOnly = ref(Boolean(route.query.recalled))

const emptyColumns = () =>
	BOARD_STATUSES.map((status) => ({
		status,
		count: 0,
		cards: [],
		has_more: false,
	}))

const columns = ref(emptyColumns())
const offsets = ref({})

// R11: every fetch carries a generation number; a late answer of an earlier
// generation is dropped, so fast student switches can never paint the previous
// student's board (the resource contract alone cannot guarantee ordering).
let boardGeneration = 0

// The confirmed depth of a column moves ONLY with a response that was actually
// applied (B08/C03): `offsets` holds the number of cards each column shows after
// the last accepted window. A failed or superseded fetch leaves the boundary
// alone (or restores it from the cards on screen), so a retry asks for the same
// logical page instead of skipping ten cards.
const fetchBoard = ({ merge = false, offsets: requestedOffsets } = {}) => {
	const generation = ++boardGeneration
	const request = call('lms.lms.homework_api.get_homework_board', {
		student: student.value || null,
		search: search.value,
		status: statusFilter.value || null,
		overdue: overdueOnly.value,
		course: courseFilter.value || null,
		offsets: JSON.stringify(requestedOffsets || offsets.value),
		include_cancelled: cancelledOnly.value,
	})
	request
		.then((data) => {
			if (generation !== boardGeneration) return
			applyBoard(data, { merge })
			// C03: the confirmed depth follows what was actually applied -- the
			// authoritative window, never the number the request hoped for.
			offsets.value = Object.fromEntries(
				columns.value.map((column) => [column.status, column.cards.length])
			)
		})
		.catch((error) => {
			if (generation !== boardGeneration) return
			restoreOffsetsFromColumns()
			toast.error(resourceErrorMessage(error, __('Error')))
			console.error(error)
		})
	return request
}

// B08: after anything but a clean apply, the boundary is re-derived from what
// is really on screen -- never left pointing past a page that never arrived.
const restoreOffsetsFromColumns = () => {
	const restored = {}
	for (const column of columns.value) {
		restored[column.status] = column.cards.length
	}
	offsets.value = restored
}

// C02: the server answers with each column's whole requested window FROM THE
// TOP, so every applied response -- load-more and refresh alike -- is
// authoritative for that window. A card missing from the fresh window has
// moved to another column or been recalled; keeping it would leave a stale
// duplicate beside a count that disagrees. `merge` stays in the signature for
// the call sites; with full-depth windows, replacing IS the merge.
const applyBoard = (data, { merge }) => {
	columns.value = data.columns
}

const reloadBoard = () => {
	// A different board target means no card of the previous one may linger on
	// screen while the fetch is in flight (spec 5.1: the client cache is
	// re-isolated on student change), and paging resets with it.
	columns.value = emptyColumns()
	offsets.value = {}
	fetchBoard()
}

onMounted(() => {
	if (!user.data) router.push({ name: 'Courses' })
	else reloadBoard()
})

watch(
	[student, search, statusFilter, courseFilter, overdueOnly, cancelledOnly],
	() => {
		router.replace({
			query: {
				student: student.value || undefined,
				title: search.value || undefined,
				status: statusFilter.value || undefined,
				course: courseFilter.value || undefined,
				overdue: overdueOnly.value ? 1 : undefined,
				recalled: cancelledOnly.value ? 1 : undefined,
			},
		})
		reloadBoard()
	}
)

const students = createResource({
	url: 'lms.lms.homework_api.get_homework_students',
})
const courses = createResource({
	url: 'lms.lms.homework_api.get_homework_courses',
})
if (canPickStudent.value) {
	students.reload()
	courses.reload()
}

const studentOptions = computed(() => [
	{ label: __('Me'), value: '' },
	...(students.data || []).map((row) => ({
		label: row.full_name,
		value: row.name,
	})),
])

const courseOptions = computed(() => [
	{ label: '', value: '' },
	...(courses.data || []).map((row) => ({ label: row.title, value: row.name })),
])

const statusOptions = computed(() => [
	{ label: __('All'), value: '' },
	...BOARD_STATUSES.map((status) => ({
		label: statusLabel(status),
		value: status,
	})),
])

// U01: the card reads the site-local wall clock straight from the offset-aware
// ISO the server sends -- `dayjs(naive)` would repaint it in the browser's
// zone and disagree with the dialog and the detail page.
// E08: the teacher's cross-student overview -- one table of every issued
// assignment with full server-side counts and paging.
const overviewOpen = ref(false)
const overviewOffset = ref(0)
const overview = createResource({
	url: 'lms.lms.homework_api.get_homework_overview',
	makeParams: () => ({
		search: search.value,
		status: statusFilter.value || undefined,
		overdue: overdueOnly.value,
		limit: 25,
		offset: overviewOffset.value,
	}),
})
const overviewRows = computed(() => overview.data?.rows || [])
const overviewCounts = computed(() => {
	const counts = overview.data?.counts || {}
	// Recalled rows are history, not a chip.
	delete counts.Cancelled
	return counts
})
watch([overviewOpen, search, statusFilter, overdueOnly], (openChanged) => {
	overviewOffset.value = 0
	if (overviewOpen.value) overview.reload()
})
const openStudentBoard = (studentName) => {
	overviewOpen.value = false
	student.value = studentName
}
const toIso = (value) => (value ? new Date(value).toISOString() : '')

const dueLabel = (card) => siteWallClockShort(card.due_at_iso || '')

const progressPercent = (card) =>
	card.total_requirements
		? Math.round((card.completed_requirements / card.total_requirements) * 100)
		: 0

const openCard = (card) => {
	router.push({ name: 'HomeworkDetail', params: { assignmentID: card.name } })
}

const continueCard = async (card) => {
	const target = card.continue_target
	if (!target) return openCard(card)
	// R10: continuing straight from the card IS the student starting the work
	// -- the card's first open is recorded before the jump, and a teacher's
	// preview open is simply refused by the server.
	try {
		await call('lms.lms.homework_api.open_homework', { assignment: card.name })
	} catch {
		// Teacher preview or already started: either way, the jump proceeds.
	}
	if (target.type === 'assignment' && target.assignment) {
		router.push({
			name: 'AssignmentSubmission',
			params: { assignmentID: target.assignment, submissionName: 'new' },
			query: { hw: card.name },
		})
	} else if (target.type === 'lesson' && target.course && target.number) {
		router.push({
			name: 'Lesson',
			params: {
				courseName: target.course,
				...lessonRouteParams(target.number),
			},
			query: { hw: card.name },
		})
	} else if (target.type === 'quiz' && target.quiz) {
		router.push({
			name: 'QuizPage',
			params: { quizID: target.quiz },
			query: { hw: card.name },
		})
	} else {
		openCard(card)
	}
}

const loadMore = (status) => {
	// C03: the first page is always on screen before this button exists, so the
	// confirmed depth starts at the page size; each accepted load-more raises
	// the requested window by one page. The requested depth moves first and
	// rolls back on rejection, so an error retries the same logical page; the
	// confirmed depth itself is re-derived from the applied columns.
	const previous = offsets.value[status] || 10
	const requested = previous + 10
	offsets.value = { ...offsets.value, [status]: requested }
	fetchBoard({ merge: true }).catch(() => {
		offsets.value = { ...offsets.value, [status]: previous }
	})
}

// R18/B08: a board left open goes stale while the student works elsewhere; a
// controlled refetch on tab visibility and window focus keeps it current. The
// refresh re-requests each column's whole loaded DEPTH (merge keeps every
// loaded card and updates its content in place), so switching tabs can never
// trade the board for one stale-offset page of itself.
const refetchIfIdle = () => {
	if (document.visibilityState === 'visible') fetchBoard({ merge: true })
}
onMounted(() => {
	window.addEventListener('focus', refetchIfIdle)
	document.addEventListener('visibilitychange', refetchIfIdle)
})
onUnmounted(() => {
	window.removeEventListener('focus', refetchIfIdle)
	document.removeEventListener('visibilitychange', refetchIfIdle)
})

const breadcrumbs = computed(() => [
	{ label: __('Homework execution'), route: { name: 'HomeworkExecution' } },
])
</script>
