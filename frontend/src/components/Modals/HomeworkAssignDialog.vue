<template>
	<Dialog
		:open="open"
		:title="__('Assign homework')"
		size="lg"
		@update:open="(value) => (value ? null : emit('cancel'))"
	>
		<template #default>
			<div
				v-if="open"
				class="space-y-4 text-base"
				data-testid="homework-assign-dialog"
			>
				<div
					v-if="homeworkDoc.data"
					class="rounded-4 bg-surface-gray-1 p-3 text-sm"
				>
					<p class="font-medium text-ink-gray-9">
						{{ homeworkDoc.data.title }}
					</p>
					<p class="mt-1 text-ink-gray-6">
						{{
							__('{0} lessons · {1} quizzes').format(
								String(composition.lessons),
								String(composition.quizzes)
							)
						}}
					</p>
				</div>

				<div>
					<p class="mb-1 text-sm text-ink-gray-7">{{ __('Student') }}</p>
					<FormControl
						v-if="students.data && students.data.length > 8"
						type="text"
						v-model="studentSearch"
						:placeholder="__('Search students')"
						:aria-label="__('Search students')"
					/>
					<RadioGroup
						class="mt-1 max-h-44 overflow-y-auto rounded-4 border border-outline-gray-2"
						:model-value="student"
						@update:model-value="(value) => (student = value)"
					>
						<Radio
							v-for="candidate in filteredStudents"
							:key="candidate.name"
							:value="candidate.name"
							:label="candidate.full_name"
							size="sm"
							class="px-3 py-1.5"
						/>
					</RadioGroup>
					<p
						v-if="!filteredStudents.length"
						class="mt-1 rounded-4 border border-outline-gray-2 px-3 py-3 text-sm text-ink-gray-5"
					>
						{{ __('No students found') }}
					</p>
				</div>

				<FormControl
					type="number"
					v-model="days"
					:min="1"
					:label="__('For how many days')"
					:required="true"
				/>

				<p v-if="dueLabel" class="text-sm text-ink-gray-6">
					{{ __('Due') }}:
					<span class="text-ink-gray-9">{{ dueLabel }}</span>
					<span v-if="dueZone" class="text-xs">({{ dueZone }})</span>
				</p>

				<div
					v-if="
						precheck.data &&
						precheck.data.reasons &&
						precheck.data.reasons.length
					"
					class="space-y-1 rounded-4 border border-outline-red-2 bg-surface-red-1 p-3 text-sm text-ink-red-5"
					data-testid="assign-block-reasons"
				>
					<p v-for="(reason, index) in precheck.data.reasons" :key="index">
						{{ reason }}
					</p>
					<p class="text-xs">
						{{
							__(
								'Grant the student access to the course first, or change the composition.'
							)
						}}
					</p>
					<!-- Spec 4: the block comes with a way into the app's own access
					management, not just the reason in prose. -->
					<p
						v-if="
							precheck.data.missing_courses &&
							precheck.data.missing_courses.length
						"
						class="flex flex-wrap gap-2 text-xs"
					>
						<router-link
							v-for="courseName in precheck.data.missing_courses"
							:key="courseName"
							:to="{ name: 'CourseDetail', params: { courseName } }"
							class="underline"
							data-testid="assign-missing-course-link"
						>
							{{ courseName }}
						</router-link>
					</p>
				</div>

				<div
					v-if="precheck.data && precheck.data.already_active"
					class="space-y-1 rounded-4 border border-outline-gray-2 bg-surface-gray-1 p-3 text-sm"
					data-testid="assign-already-active"
				>
					<p>
						{{
							__(
								'This student already has an active assignment of this homework.'
							)
						}}
					</p>
					<router-link
						:to="{
							name: 'HomeworkDetail',
							params: { assignmentID: precheck.data.already_active },
						}"
						class="underline"
					>
						{{ __('Open it') }}
					</router-link>
				</div>
			</div>
		</template>
		<template #actions>
			<div class="flex items-center justify-end gap-2">
				<Button variant="subtle" @click="emit('cancel')">{{
					__('Cancel')
				}}</Button>
				<Button
					v-if="confirmExtra"
					variant="solid"
					:loading="assigning"
					@click="assign(true)"
					data-testid="assign-confirm-extra"
				>
					{{ __('Assign anyway') }}
				</Button>
				<Button
					v-else
					variant="solid"
					:disabled="!student || blocked"
					:loading="assigning"
					@click="assign(false)"
					data-testid="assign-confirm"
				>
					{{ __('Assign to student') }}
				</Button>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
// The assign dialog (spec 4): composition summary, student search, an editable
// number of days with the computed due date/time in the site timezone, the
// blocking reasons when access or locks refuse the composition (A10), and the
// already-active flow that ends in a deliberate second issue (A11).
import {
	Button,
	Dialog,
	FormControl,
	Radio,
	RadioGroup,
	createResource,
	toast,
} from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { resourceErrorMessage } from '@/utils/resource'
import { siteWallClock, siteZoneLabel } from '@/utils/dueDate'

const props = defineProps({
	open: { type: Boolean, default: false },
	homework: { type: String, default: '' },
	presetDays: { type: Number, default: 7 },
})
const emit = defineEmits(['done', 'cancel'])

const student = ref('')
const studentSearch = ref('')
const days = ref(props.presetDays || 7)
const confirmExtra = ref(false)
const assigning = ref(false)

const students = createResource({
	url: 'lms.lms.homework_api.get_homework_students',
})
const homeworkDoc = createResource({
	url: 'lms.lms.homework_api.get_homework',
	makeParams: () => ({ name: props.homework }),
})

const composition = computed(() => {
	const items = homeworkDoc.data?.items || []
	return {
		lessons: items.filter((item) => item.source_type === 'Lesson').length,
		quizzes: items.filter((item) => item.source_type === 'Quiz').length,
	}
})

const filteredStudents = computed(() => {
	const rows = students.data || []
	if (!studentSearch.value.trim()) return rows
	const needle = studentSearch.value.trim().toLowerCase()
	return rows.filter(
		(candidate) =>
			candidate.full_name.toLowerCase().includes(needle) ||
			candidate.name.toLowerCase().includes(needle)
	)
})

const precheck = createResource({
	url: 'lms.lms.homework_api.precheck_assignment',
	makeParams: () => ({
		homework: props.homework,
		student: student.value,
		days: Number(days.value),
	}),
})

const blocked = computed(
	() =>
		Boolean(
			precheck.data && precheck.data.reasons && precheck.data.reasons.length
		) || Boolean(precheck.data?.archived)
)

// The deadline renders in the site's timezone with its offset named (spec 4.1,
// U01): the shared dueDate helper reads both straight from the server's
// offset-bearing ISO -- never from the browser's zone.
const dueLabel = computed(() =>
	siteWallClock(precheck.data?.due_at || '')
)

const dueZone = computed(() =>
	siteZoneLabel(precheck.data?.due_at || '')
)

watch(
	() => props.open,
	(isOpen) => {
		if (!isOpen) return
		student.value = ''
		studentSearch.value = ''
		days.value = props.presetDays || 7
		confirmExtra.value = false
		precheck.data = null
		// B05: ONE key per logical operation, minted when the dialog opens and
		// pinned until the dialog closes -- for the base issue AND for the
		// confirmed extra issue alike. The base call in the already-active
		// flow creates nothing, so it never consumes the key; every retry of
		// an uncertain (timed-out) request therefore reuses it and the server
		// returns the same card instead of issuing a second one.
		operationKey.value = mintKey()
		students.reload()
		if (props.homework) homeworkDoc.reload()
	}
)

const mintKey = () =>
	crypto.randomUUID ? crypto.randomUUID() : `hw-${Date.now()}-${Math.random()}`

const operationKey = ref('')

watch([student, days], () => {
	if (props.open && student.value) precheck.reload()
})

const assign = async (force) => {
	if (assigning.value) return
	assigning.value = true
	// B05: the pinned operation key. `force` is not a new operation -- it is the
	// confirmation step of this same dialog's issue, so it reuses the key; a
	// retry after a timeout reuses it too. The server verifies the key's
	// parameters and refuses loudly if the request no longer matches.
	const key = operationKey.value || (operationKey.value = mintKey())
	try {
		const result = await assignCall(force, key)
		if (result && result.already_active && !force) {
			confirmExtra.value = true
			toast.info(
				__(
					'This student already has this homework. Confirm to assign an extra copy.'
				)
			)
			assigning.value = false
			return
		}
		toast.success(__('Homework assigned'))
		emit('done', result)
	} catch (err) {
		toast.error(resourceErrorMessage(err, __('Error')))
		console.error(err)
	}
	assigning.value = false
}

const assignCall = (force, key) =>
	new Promise((resolve, reject) => {
		createResource({
			url: 'lms.lms.homework_api.assign_homework',
			params: {
				homework: props.homework,
				student: student.value,
				days: Number(days.value),
				idempotency_key: key,
				force,
			},
			auto: true,
			onSuccess: resolve,
			onError: reject,
		})
	})
</script>
