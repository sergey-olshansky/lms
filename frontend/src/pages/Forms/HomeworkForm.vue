<template>
	<FormShell :title="formTitle" size="lg" @close="close">
		<template #default>
			<div v-if="!canManage" class="p-4 text-base text-ink-gray-6">
				{{ __('You are not permitted to manage homework.') }}
			</div>
			<div v-else data-testid="homework-fields" class="space-y-4 text-base">
				<!-- U03: the server's Data cap, shown and enforced in the input, so a
				     141st character can never be typed and lost on save. -->
				<FormControl
					v-model="form.title"
					:label="__('Title')"
					:required="true"
					maxlength="140"
				/>
				<FormControl
					type="number"
					v-model="form.days"
					:min="1"
					:label="__('For how many days')"
					:required="true"
				/>
				<!-- E05: rich details -- paragraphs, lists, links, images -- the
				     project editor with private uploads; the server sanitizes
				     whatever is stored. A legacy plain-text draft re-opens as
				     text and keeps saving as text. -->
				<div>
					<p class="mb-1 text-sm text-ink-gray-7">{{ __('Homework details') }}</p>
					<RichTextEditor
						v-if="richDetails"
						:content="form.details"
						:editable="true"
						:fixedMenu="true"
						:uploadArgs="{ private: true }"
						@change="(value) => (form.details = value)"
					/>
					<FormControl
						v-else
						type="textarea"
						v-model="form.details"
						rows="5"
						:placeholder="__('Optional. Line breaks are preserved.')"
					/>
					<button
						type="button"
						class="mt-1 text-xs text-ink-gray-5 underline"
						data-testid="details-mode-toggle"
						@click="richDetails = !richDetails"
					>
						{{
							richDetails
								? __('Switch to plain text')
								: __('Format with the rich text editor')
						}}
					</button>
				</div>
				<!-- E06: with this on, finishing the materials only readies the
				     work -- the student must attach a solution file and press
				     Send for review. Default off: the automatic Review flow of
				     an ordinary compilation is untouched. -->
				<FormControl
					type="checkbox"
					v-model="form.require_solution"
					:label="__('Requires a file solution')"
				/>
				<Select
					v-model="form.group"
					:options="groupOptions"
					:placeholder="__('Group')"
				/>

				<!-- E05: the teacher's own files of this SAVED template. -->
				<HomeworkTeacherMaterials v-if="savedName" :homework="savedName" />

				<div class="rounded-4 border border-outline-gray-2">
					<div
						class="flex items-center justify-between gap-2 border-b border-outline-gray-2 px-4 py-2"
					>
						<span class="text-ink-gray-8">{{ __('Attached materials') }}</span>
						<Button variant="subtle" size="sm" @click="openPicker">
							<template #prefix>
								<span class="lucide-plus size-4" />
							</template>
							{{ __('Add from courses') }}
						</Button>
					</div>
					<div class="divide-y divide-outline-gray-1">
						<p
							v-if="!form.items.length"
							class="px-4 py-6 text-sm text-ink-gray-5"
							data-testid="homework-no-materials"
						>
							{{ __('No materials') }}
							{{
								__(
									'An empty homework is saved as a draft and cannot be assigned.'
								)
							}}
						</p>
						<div
							v-for="(item, index) in form.items"
							:key="`${item.source_type}:${item.name}`"
							class="flex items-start gap-3 px-4 py-2"
						>
							<span class="mt-0.5 shrink-0 text-ink-gray-5">
								<span
									class="block size-4"
									:class="typeIcon(item.source_type)"
									aria-hidden="true"
								/>
							</span>
							<span class="min-w-0 flex-1">
								<span
									class="block truncate text-sm text-ink-gray-9"
									:title="item.path"
								>
									{{ item.title }}
								</span>
								<span
									class="block truncate text-xs text-ink-gray-5"
									:title="item.path"
								>
									{{ item.path }}
								</span>
							</span>
							<router-link
								v-if="item.route"
								:to="itemRoute(item.route)"
								class="shrink-0 text-xs text-ink-gray-5 underline"
								:data-testid="`preview-${item.name}`"
								v-external
							>
								{{ __('Open') }}
							</router-link>
							<button
								type="button"
								class="rounded-4 p-1 text-ink-gray-5 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-7"
								:aria-label="__('Remove')"
								@click="removeItem(index)"
							>
								<span class="block size-4 lucide-x" />
							</button>
						</div>
					</div>
				</div>
			</div>
		</template>
		<template #actions>
			<div v-if="canManage" class="flex items-center justify-end gap-2">
				<HeaderButton :label="__('Cancel')" @click="close" />
				<HeaderButton
					data-testid="homework-save"
					:label="__('Save')"
					:loading="saving"
					@click="saveHomework(false)"
				/>
				<HeaderButton
					data-testid="homework-save-assign"
					:label="__('Save and assign')"
					:disabled="!form.items.length"
					:loading="saving"
					@click="saveHomework(true)"
				/>
			</div>
		</template>
	</FormShell>

	<HomeworkMaterialPicker
		:open="pickerOpen"
		:courses="courses.data || []"
		:initial-items="form.items"
		@confirm="onPickerConfirm"
		@cancel="pickerOpen = false"
	/>

	<HomeworkAssignDialog
		:open="assignDialogOpen"
		:homework="savedName"
		:preset-days="Number(form.days)"
		@done="onAssigned"
		@cancel="assignDialogOpen = false"
	/>
</template>

<script setup>
import { Button, FormControl, createResource, toast } from 'frappe-ui'
import { computed, inject, nextTick, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import FormShell from '@/components/FormShell.vue'
import HeaderButton from '@/components/HeaderButton.vue'
import Select from '@/components/Controls/Select.vue'
import HomeworkMaterialPicker from '@/components/Modals/HomeworkMaterialPicker.vue'
import HomeworkTeacherMaterials from '@/components/HomeworkTeacherMaterials.vue'
import RichTextEditor from '@/components/RichTextEditor.vue'
import HomeworkAssignDialog from '@/components/Modals/HomeworkAssignDialog.vue'
import { useFormRoute } from '@/composables/useFormRoute'
import { lessonRouteParams } from '@/utils/homeworkSelection'
import { resourceErrorMessage } from '@/utils/resource'

const props = defineProps({ homeworkID: { type: String, default: 'new' } })
const emit = defineEmits(['created'])

const user = inject('$user')
const { close, saveAndReplace } = useFormRoute({ name: 'HomeworkLibrary' })

const isNew = computed(() => !props.homeworkID || props.homeworkID === 'new')
const formTitle = computed(() =>
	isNew.value ? __('Create homework') : __('Edit homework')
)

const canManage = computed(() =>
	Boolean(user.data?.is_moderator || user.data?.is_instructor)
)

const form = reactive({
	title: '',
	days: 7,
	details: '',
	group: '',
	items: [],
	require_solution: false,
})

// E05: an existing rich-text description opens in the editor; a plain-text
// draft keeps the textarea until the teacher opts into formatting.
const richDetails = ref(false)

const groups = createResource({
	url: 'lms.lms.homework_api.list_homework_groups',
})
groups.reload()
const groupOptions = computed(() => {
	const rows = [
		{ label: '', value: '' },
		...(groups.data || []).map((group) => ({
			label: group.path,
			value: group.name,
		})),
	]
	return rows
})

const courses = createResource({
	url: 'lms.lms.homework_api.get_homework_courses',
})

const existing = createResource({
	url: 'lms.lms.homework_api.get_homework',
	makeParams: () => ({ name: props.homeworkID }),
	onSuccess(data) {
		hydrating.value = true
		form.title = data.title
		form.days = data.days
		form.details = data.details || ''
		form.group = data.group || ''
		form.require_solution = Boolean(data.require_solution)
		richDetails.value = /<[a-z][\s\S]*>/i.test(form.details)
		form.items = data.items.map((item) => ({
			source_type: item.source_type,
			name: item.name,
			course: item.course,
			title: item.label,
			chapter: '',
			path: item.path,
			route: item.route || null,
		}))
		nextTick(() => {
			hydrating.value = false
			dirty.value = false
		})
	},
})
if (!isNew.value) existing.reload()

// Hydration itself must not read as edits: the dirty flag is raised by user
// input only, so opening an existing compilation and leaving is silent.
const hydrating = ref(!isNew.value)
const dirty = ref(false)
watch(
	form,
	() => {
		if (!hydrating.value) dirty.value = true
	},
	{ deep: true }
)

// The app-level "unsaved changes" warning for this form: leaving with edits in
// flight asks once, and a completed save clears the flag (spec 3.3).
onBeforeRouteLeave(() => {
	if (dirty.value && !suppressLeaveGuard.value) {
		return window.confirm(__('You have unsaved changes. Leave anyway?'))
	}
	return true
})
const suppressLeaveGuard = ref(false)

const pickerOpen = ref(false)
const openPicker = () => {
	if (!courses.data) courses.reload()
	pickerOpen.value = true
}

// Only "Add selected" mutates the composition, and it REPLACES the whole set
// (R13): unchecking an attached material removes it. A cancelled picker changes
// nothing (A08). Parent-and-child picks arrive deduped by key (A07).
const onPickerConfirm = (entries) => {
	const seen = new Set()
	form.items = entries.filter((entry) => {
		const key = `${entry.source_type}:${entry.name}`
		if (seen.has(key)) return false
		seen.add(key)
		return true
	})
	pickerOpen.value = false
}

const removeItem = (index) => {
	form.items.splice(index, 1)
}

const typeIcon = (type) => {
	if (type === 'Quiz') return 'lucide-circle-help'
	if (type === 'Assignment') return 'lucide-pencil'
	return 'lucide-file-text'
}

// The teacher can view a source before issuing (R18): lesson numbers, quiz and
// assignment pages come from the server-provided route of each stored item.
const itemRoute = (route) => {
	if (!route) return null
	if (route.type === 'lesson' && route.number) {
		return {
			name: 'Lesson',
			params: {
				courseName: route.course,
				...lessonRouteParams(route.number),
			},
		}
	}
	if (route.type === 'quiz') {
		return { name: 'QuizPage', params: { quizID: route.quiz } }
	}
	if (route.type === 'assignment') {
		return {
			name: 'AssignmentSubmission',
			params: { assignmentID: route.assignment, submissionName: 'new' },
		}
	}
	return null
}

const save = createResource({
	url: 'lms.lms.homework_api.save_homework',
	makeParams: () => ({
		// R14: after the first save of a new compilation, this form edits the
		// created record -- cancelling the assign dialog and saving again must
		// update the same template, never spawn a second one.
		name:
			props.homeworkID && props.homeworkID !== 'new'
				? props.homeworkID
				: savedName.value || null,
		title: form.title,
		days: Number(form.days),
		details: form.details,
		group: form.group || null,
		items: form.items,
		require_solution: Boolean(form.require_solution),
	}),
	onSuccess(data) {
		savedName.value = data.name
		dirty.value = false
		toast.success(__('Homework saved'))
		emit('created')
		if (pendingAssign.value) {
			assignDialogOpen.value = true
		} else {
			suppressLeaveGuard.value = true
			saveAndReplace({ name: 'HomeworkLibrary' })
		}
	},
	onError(err) {
		toast.error(resourceErrorMessage(err, __('Error')))
		console.error(err)
	},
})

const saving = computed(() => Boolean(save.loading))
const pendingAssign = ref(false)
const savedName = ref('')
const assignDialogOpen = ref(false)

const saveHomework = (andAssign) => {
	if (!canManage.value) return
	if (!String(form.title || '').trim()) {
		toast.error(__('Title is required'))
		return
	}
	// U03: the input caps typing at 140, this caps paste/drag the same way the
	// server's Data field does -- both must agree on one limit.
	if (String(form.title || '').length > 140) {
		toast.error(__('Title cannot exceed 140 characters'))
		return
	}
	const days = Number(form.days)
	if (!Number.isInteger(days) || days < 1) {
		toast.error(__('Number of days must be a whole number of at least 1'))
		return
	}
	pendingAssign.value = andAssign
	save.submit()
}

const onAssigned = () => {
	assignDialogOpen.value = false
	suppressLeaveGuard.value = true
	saveAndReplace({ name: 'HomeworkLibrary' })
}
</script>
