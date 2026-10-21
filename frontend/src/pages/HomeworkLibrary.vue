<template>
	<ListPage
		:breadcrumbs="breadcrumbs"
		:title="__('{0} Homework').format(String(total))"
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
			<HeaderButton
				:label="__('Groups')"
				icon="lucide-folder"
				@click="groupsOpen = true"
			/>
			<Button variant="solid" @click="openForm('new')">
				<template #prefix>
					<span class="lucide-plus size-4" />
				</template>
				{{ __('Create homework') }}
			</Button>
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
			<Select
				v-model="groupFilter"
				:options="groupFilterOptions"
				:placeholder="__('Group')"
			/>
			<BooleanSwitch v-model="archivedOnly" size="sm" :label="__('Archived')" />
		</template>

		<template #cell="{ column, row }">
			<div v-if="column.key == 'title'" class="min-w-0">
				<button
					type="button"
					class="block max-w-full truncate text-left text-sm text-ink-gray-9 underline-offset-2 hover:underline"
					:title="row.title"
					@click="openForm(row.name)"
				>
					{{ row.title }}
				</button>
				<span
					v-if="!row.has_materials"
					class="mt-0.5 inline-block rounded-4 bg-surface-gray-2 px-1.5 py-0.5 text-xs text-ink-gray-6"
				>
					{{ __('No materials') }}
				</span>
			</div>
			<div
				v-else-if="column.key == 'composition'"
				class="text-sm text-ink-gray-7"
			>
				{{ compositionLabel(row) }}
			</div>
			<div v-else-if="column.key == 'days'" class="text-sm text-ink-gray-7">
				{{ __('{0} days').format(String(row.days)) }}
			</div>
			<div
				v-else-if="column.key == 'group_title'"
				class="text-sm text-ink-gray-7"
			>
				{{ row.group_title || '—' }}
			</div>
			<div v-else-if="column.key == 'modified'" class="text-sm text-ink-gray-5">
				{{ formatDate(row.modified) }}
			</div>
			<div
				v-else-if="column.key == 'actions'"
				class="flex items-center justify-end gap-1"
			>
				<Button
					variant="subtle"
					size="sm"
					:disabled="!row.has_materials || row.archived"
					:label="__('Assign')"
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

	<HomeworkGroupsDialog
		:open="groupsOpen"
		@changed="reloadGroupsAndRows"
		@close="groupsOpen = false"
	/>

	<HomeworkAssignDialog
		:open="Boolean(assignTarget)"
		:homework="assignTarget ? assignTarget.name : ''"
		:preset-days="assignTarget ? assignTarget.days : 7"
		@done="onAssigned"
		@cancel="assignTarget = null"
	/>
</template>

<script setup>
import { Button, Dropdown, FormControl, createResource, toast } from 'frappe-ui'
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import ListPage from '@/components/Layouts/pages/ListPage.vue'
import HeaderButton from '@/components/HeaderButton.vue'
import Select from '@/components/Controls/Select.vue'
import BooleanSwitch from '@/components/Controls/BooleanSwitch.vue'
import HomeworkGroupsDialog from '@/components/Modals/HomeworkGroupsDialog.vue'
import HomeworkAssignDialog from '@/components/Modals/HomeworkAssignDialog.vue'
import { openFormRoute } from '@/composables/useFormRoute'
import { resourceErrorMessage } from '@/utils/resource'
import { openExternal } from '@/utils/openExternal'

const router = useRouter()
const user = inject('$user')
const dayjs = inject('$dayjs')

const search = ref('')
const groupFilter = ref('')
const archivedOnly = ref(false)
const rows = ref([])
const total = ref(0)
const offset = ref(0)
const pageLength = ref(25)
const groupsOpen = ref(false)
const assignTarget = ref(null)

onMounted(() => {
	// The tab itself is staff-only in the sidebar; this guards a typed URL.
	if (!user.data?.is_moderator && !user.data?.is_instructor) {
		router.push({ name: 'Courses' })
		return
	}
	search.value = router.currentRoute.value.query.title || ''
	reload()
})

watch([search, groupFilter, archivedOnly], () => {
	router.replace({
		query: {
			title: search.value || undefined,
			group: groupFilter.value || undefined,
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
		group: groupFilter.value || null,
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

const groups = createResource({
	url: 'lms.lms.homework_api.list_homework_groups',
})
groups.reload()
const groupFilterOptions = computed(() => [
	{ label: '', value: '' },
	...(groups.data || []).map((group) => ({
		label: group.path,
		value: group.name,
	})),
])

const reloadGroupsAndRows = () => {
	groups.reload()
	resetAndReload()
}

const columns = computed(() => [
	{ label: __('Title'), key: 'title', width: 2, icon: 'lucide-book-marked' },
	{ label: __('Group'), key: 'group_title', width: 1, icon: 'lucide-folder' },
	{
		label: __('Composition'),
		key: 'composition',
		width: 1,
		icon: 'lucide-list-checks',
	},
	{
		label: __('Due in days'),
		key: 'days',
		width: '100px',
		icon: 'lucide-clock',
	},
	{
		label: __('Updated On'),
		key: 'modified',
		width: 1,
		icon: 'lucide-history',
	},
	{ label: '', key: 'actions', width: '150px', align: 'right' },
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

const formatDate = (value) => (value ? dayjs(value).format('DD MMM YYYY') : '')

const openForm = (homeworkID) => {
	openFormRoute(
		router,
		homeworkID === 'new'
			? { name: 'HomeworkNew' }
			: { name: 'HomeworkEdit', params: { homeworkID } }
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

// E02: a plain navigational download -- the server sets Content-Disposition,
// so opening the method URL hands the browser the file. The shared opener
// adds the noopener guard and the scheme allowlist every window of the app
// clears.
const downloadTemplatePdf = (row) => {
	openExternal(
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

const onAssigned = () => {
	assignTarget.value = null
}

const breadcrumbs = computed(() => [
	{ label: __('Homework'), route: { name: 'HomeworkLibrary' } },
])
</script>
