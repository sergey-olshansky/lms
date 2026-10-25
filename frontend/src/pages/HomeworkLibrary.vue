<template>
	<ListPage
		:breadcrumbs="breadcrumbs"
		:title="__('Homework templates ({0})').format(String(total))"
		layout="list"
		:columns="columns"
		:rows="rows"
		:total-count="total"
		:loading="library.loading"
		:has-next-page="hasMore"
		v-model:page-length="pageLength"
		empty-name="Homework"
		empty-icon="lucide-book-marked"
		@load-more="loadMore"
	>
		<template #actions>
			<Button variant="solid" @click="openForm('new')">
				<template #prefix>
					<span class="lucide-plus size-4" />
				</template>
				{{ __('Create homework') }}
			</Button>
		</template>
		<template #after-header>
			<HomeworkWorkspaceTabs
				active="HomeworkLibrary"
				:student="selectedStudent"
			/>
			<div class="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
				<p class="max-w-xl text-sm text-ink-gray-6">
					{{
						__(
							'Collect materials from courses, then assign the homework to a student. You can reuse the same template for different students.'
						)
					}}
				</p>
				<HomeworkStudentPicker
					v-model="selectedStudent"
					label="Student for assignment"
					class="w-full sm:w-80"
					data-testid="library-student-select"
				/>
			</div>
		</template>

		<template #filters>
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
			<BooleanSwitch v-model="archivedOnly" size="sm" :label="__('Archived')" />
		</template>
		<template #empty>
			<div class="px-5 py-10 text-center text-sm text-ink-gray-6">
				<p>
					{{
						search || archivedOnly
							? __('No homework matches these filters.')
							: __(
									'Create your first template: choose materials from courses, then assign the homework to a student.'
								)
					}}
				</p>
				<Button
					v-if="!search && !archivedOnly"
					class="mt-3"
					variant="solid"
					@click="openForm('new')"
					>{{ __('Create homework') }}</Button
				>
			</div>
		</template>

		<template #cell="{ column, row }">
			<div v-if="column.key == 'title'" class="min-w-0">
				<button
					type="button"
					class="block max-w-full whitespace-normal break-words text-left text-sm leading-5 text-ink-gray-9 underline-offset-2 hover:underline"
					:title="row.title"
					@click="openForm(row.name)"
				>
					{{ row.title }}
				</button>
				<p v-if="row.has_materials" class="mt-1 text-xs text-ink-gray-5">
					{{ compositionLabel(row) }}
				</p>
				<span
					v-if="!row.has_materials"
					class="mt-0.5 inline-block rounded-4 bg-surface-gray-2 px-1.5 py-0.5 text-xs text-ink-gray-6"
				>
					{{ __('No materials') }}
				</span>
			</div>
			<div v-else-if="column.key == 'days'" class="text-sm text-ink-gray-7">
				{{ __('{0} d.').format(String(row.days)) }}
			</div>
			<div
				v-else-if="column.key == 'actions'"
				class="flex items-center justify-end gap-1"
			>
				<Button
					variant="subtle"
					size="sm"
					:disabled="!row.has_materials || row.archived"
					:label="__('Assign to student')"
					data-testid="assign-button"
					@click="assignTarget = row"
				/>
				<Dropdown :options="rowMenu(row)">
					<template #default="{ open }">
						<Button variant="ghost" size="sm" :aria-expanded="open">
							<template #icon>
								<span
									class="lucide-more-horizontal size-4"
									aria-hidden="true"
								/>
							</template>
						</Button>
					</template>
				</Dropdown>
			</div>
		</template>
	</ListPage>

	<router-view @created="resetAndReload" />

	<HomeworkAssignDialog
		:open="Boolean(assignTarget)"
		:homework="assignTarget ? assignTarget.name : ''"
		:preset-days="assignTarget ? assignTarget.days : 7"
		:preset-student="selectedStudent"
		@done="onAssigned"
		@cancel="assignTarget = null"
	/>
</template>

<script setup>
import {
	Button,
	Dropdown,
	FormControl,
	createResource,
	toast,
	usePageMeta,
} from 'frappe-ui'
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import ListPage from '@/components/Layouts/pages/ListPage.vue'
import BooleanSwitch from '@/components/Controls/BooleanSwitch.vue'
import HomeworkAssignDialog from '@/components/Modals/HomeworkAssignDialog.vue'
import HomeworkWorkspaceTabs from '@/components/HomeworkWorkspaceTabs.vue'
import HomeworkStudentPicker from '@/components/HomeworkStudentPicker.vue'
import { openFormRoute } from '@/composables/useFormRoute'
import { resourceErrorMessage } from '@/utils/resource'
import { downloadViaAnchor } from '@/utils/download'

const router = useRouter()
const user = inject('$user')

const search = ref('')
const archivedOnly = ref(false)
const rows = ref([])
const total = ref(0)
const offset = ref(0)
const pageLength = ref(25)
const assignTarget = ref(null)
const selectedStudent = ref('')

onMounted(() => {
	// The tab itself is staff-only in the sidebar; this guards a typed URL.
	if (!user.data?.is_moderator && !user.data?.is_instructor) {
		router.push({ name: 'Courses' })
		return
	}
	search.value = router.currentRoute.value.query.title || ''
	selectedStudent.value = String(router.currentRoute.value.query.student || '')
	reload()
})

watch([search, archivedOnly], () => {
	router.replace({
		query: {
			title: search.value || undefined,
			archived: archivedOnly.value ? 1 : undefined,
		},
	})
	resetAndReload()
})

// A page-size change re-reads from the top: the already loaded page and the
// requested size would otherwise disagree (R12).
watch(pageLength, () => {
	resetAndReload()
})

const library = createResource({
	url: 'lms.lms.homework_api.get_homework_library',
	makeParams: () => ({
		search: search.value,
		group: null,
		archived: archivedOnly.value,
		limit: pageLength.value,
		offset: rows.value.length,
	}),
	onSuccess(data) {
		if (offset.value === 0) rows.value = data.rows
		else rows.value.push(...data.rows)
		total.value = data.total
	},
	onError(err) {
		toast.error(resourceErrorMessage(err, __('Error')))
		console.error(err)
	},
})

const resetAndReload = () => {
	rows.value = []
	offset.value = 0
	library.reload()
}

const reload = () => {
	offset.value = rows.value.length
	library.reload()
}
const loadMore = () => {
	offset.value = rows.value.length
	library.reload()
}
// R12: "how much is loaded" is rows.length alone -- offset double-counted it,
// hiding the last page of a 60-row library at 25 per page.
const hasMore = computed(() => rows.value.length < total.value)

const columns = computed(() => [
	{
		label: __('Title'),
		key: 'title',
		width: 1,
		wrap: true,
		icon: 'lucide-book-marked',
	},
	{
		label: __('Homework duration'),
		key: 'days',
		width: '80px',
		icon: 'lucide-clock',
	},
	{ label: '', key: 'actions', width: '190px', align: 'right' },
])

const compositionLabel = (row) => {
	if (!row.has_materials) return '—'
	const parts = []
	if (row.lessons_count)
		parts.push(__('{0} lessons').format(String(row.lessons_count)))
	if (row.quizzes_count)
		parts.push(__('{0} quizzes').format(String(row.quizzes_count)))
	return parts.join(' · ') || '—'
}

const openForm = (homeworkID) => {
	openFormRoute(
		router,
		homeworkID === 'new'
			? {
					name: 'HomeworkNew',
					query: { student: selectedStudent.value || undefined },
				}
			: {
					name: 'HomeworkEdit',
					params: { homeworkID },
					query: { student: selectedStudent.value || undefined },
				}
	)
}

const rowMenu = (row) =>
	[
		{
			label: __('Edit'),
			icon: 'lucide-pencil',
			onClick: () => openForm(row.name),
		},
		{
			// E02: the composition as a PDF with real links to every material.
			label: __('Download PDF'),
			icon: 'lucide-file-down',
			onClick: () => downloadTemplatePdf(row),
		},
		{
			label: __('Create copy'),
			icon: 'lucide-copy',
			onClick: () => copyRow(row),
		},
		{
			label: row.archived ? __('Restore from archive') : __('Archive'),
			icon: 'lucide-archive',
			onClick: () => archiveRow(row),
		},
		{
			label: __('Delete'),
			icon: 'lucide-trash-2',
			condition: () => !row.has_assignments,
			onClick: () => deleteRow(row),
		},
	].filter((item) => (item.condition ? item.condition() : true))

// E02/F04: a real download -- a programmatic anchor with the server's
// Content-Disposition, not a new window a popup blocker can swallow.
const downloadTemplatePdf = (row) => {
	downloadViaAnchor(
		`/api/method/lms.lms.homework_pdf.download_homework_template_pdf?name=${encodeURIComponent(
			row.name
		)}`
	)
}

const copyRow = async (row) => {
	try {
		await callAction('lms.lms.homework_api.copy_homework', { name: row.name })
		toast.success(__('Copy created'))
		resetAndReload()
	} catch (err) {
		toast.error(resourceErrorMessage(err, __('Error')))
	}
}

const archiveRow = async (row) => {
	try {
		await callAction('lms.lms.homework_api.archive_homework', {
			name: row.name,
			archived: !row.archived,
		})
		toast.success(row.archived ? __('Restored from archive') : __('Archived'))
		resetAndReload()
	} catch (err) {
		toast.error(resourceErrorMessage(err, __('Error')))
	}
}

const deleteRow = async (row) => {
	if (!window.confirm(__('Delete this homework?'))) return
	try {
		await callAction('lms.lms.homework_api.delete_homework', { name: row.name })
		toast.success(__('Homework deleted'))
		resetAndReload()
	} catch (err) {
		toast.error(resourceErrorMessage(err, __('Error')))
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

const onAssigned = (result) => {
	assignTarget.value = null
	if (result?.name)
		router.push({
			name: 'HomeworkDetail',
			params: { assignmentID: result.name },
		})
}

const breadcrumbs = computed(() => [
	{ label: __('Homework workspace'), route: { name: 'HomeworkLibrary' } },
])
usePageMeta(() => ({ title: __('Homework workspace') }))
</script>
