<template>
	<div class="flex h-full flex-col">
		<PageHeader :breadcrumbs="breadcrumbs">
			<template #actions>
				<Select
					v-if="canPickStudent"
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
		<p
			v-if="cancelledOnly"
			class="px-4 pb-2 text-sm text-ink-gray-5 md:px-6"
			data-testid="board-cancelled-note"
		>
			{{ __('Recalled assignments: history only, no updates.') }}
		</p>

		<div
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
import { Button, FormControl, createResource, toast } from 'frappe-ui'
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/Layouts/pages/PageHeader.vue'
import Select from '@/components/Controls/Select.vue'
import BooleanSwitch from '@/components/Controls/BooleanSwitch.vue'
import { lessonRouteParams, progressLine } from '@/utils/homeworkSelection'
import { resourceErrorMessage } from '@/utils/resource'

const route = useRoute()
const router = useRouter()
const user = inject('$user')
const dayjs = inject('$dayjs')

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

const board = createResource({
	url: 'lms.lms.homework_api.get_homework_board',
	makeParams: () => ({
		student: student.value || null,
		search: search.value,
		status: statusFilter.value || null,
		overdue: overdueOnly.value,
		course: courseFilter.value || null,
		offsets: JSON.stringify(offsets.value),
		include_cancelled: cancelledOnly.value,
	}),
	onSuccess(data) {
		columns.value = data.columns
	},
	onError(err) {
		toast.error(resourceErrorMessage(err, __('Error')))
		console.error(err)
	},
})

const reloadBoard = () => {
	// A different board target means no card of the previous one may linger on
	// screen while the fetch is in flight (spec 5.1: the client cache is
	// re-isolated on student change), and paging resets with it.
	columns.value = emptyColumns()
	offsets.value = {}
	board.reload()
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

const dueLabel = (card) =>
	card.due_at ? dayjs(card.due_at).format('DD.MM HH:mm') : ''

const progressPercent = (card) =>
	card.total_requirements
		? Math.round((card.completed_requirements / card.total_requirements) * 100)
		: 0

const openCard = (card) => {
	router.push({ name: 'HomeworkDetail', params: { assignmentID: card.name } })
}

const continueCard = (card) => {
	const target = card.continue_target
	if (!target) return openCard(card)
	if (target.type === 'lesson' && target.course && target.number) {
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
	offsets.value = {
		...offsets.value,
		[status]: (offsets.value[status] || 0) + 10,
	}
	board.reload()
}

const breadcrumbs = computed(() => [
	{ label: __('Homework execution'), route: { name: 'HomeworkExecution' } },
])
</script>
