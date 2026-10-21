<template>
	<Dialog
		:open="open"
		:title="__('Add from courses')"
		size="7xl"
		@update:open="(value) => (value ? null : emit('cancel'))"
	>
		<template #default>
			<div
				v-if="open"
				class="flex h-[65vh] flex-col gap-4 md:flex-row"
				data-testid="homework-material-picker"
			>
				<!-- Course list -->
				<div class="flex w-full shrink-0 flex-col gap-2 md:w-64">
					<FormControl
						type="text"
						v-model="courseSearch"
						:placeholder="__('Search courses')"
						:aria-label="__('Search courses')"
					/>
					<div
						class="flex-1 overflow-y-auto rounded-4 border border-outline-gray-2"
					>
						<button
							v-for="course in filteredCourses"
							:key="course.name"
							type="button"
							class="block w-full px-3 py-2 text-left text-sm transition-colors"
							:class="
								course.name === activeCourse
									? 'bg-surface-gray-3 text-ink-gray-9'
									: 'text-ink-gray-7 hover:bg-surface-gray-1'
							"
							:aria-current="course.name === activeCourse"
							@click="selectCourse(course.name)"
						>
							{{ course.title }}
						</button>
						<p
							v-if="!filteredCourses.length"
							class="px-3 py-4 text-sm text-ink-gray-5"
						>
							{{ __('No courses found') }}
						</p>
					</div>
				</div>

				<!-- Tree -->
				<div class="flex min-w-0 flex-1 flex-col gap-2">
					<div class="flex items-center gap-2">
						<FormControl
							type="text"
							v-model="materialSearch"
							:placeholder="__('Search materials')"
							:aria-label="__('Search materials')"
							class="flex-1"
						>
							<template #prefix>
								<span class="lucide-search size-4 text-ink-gray-5" />
							</template>
						</FormControl>
						<!-- Spec 3.4.1: an entire course is selectable as one action. -->
						<Checkbox
							size="sm"
							:label="__('Entire course')"
							:model-value="wholeCourseState === 'checked'"
							:indeterminate="wholeCourseState === 'indeterminate'"
							:disabled="!activeCourseLeaves.length"
							data-testid="picker-select-all"
							@update:model-value="toggleWholeCourse"
						/>
					</div>
					<div
						class="flex-1 overflow-y-auto rounded-4 border border-outline-gray-2 p-2"
					>
						<div v-if="treeLoading" class="p-4 text-sm text-ink-gray-5">
							{{ __('Loading…') }}
						</div>
						<template v-else-if="materialSearch.trim()">
							<button
								v-for="hit in searchHits"
								:key="hit.key"
								type="button"
								class="flex w-full cursor-pointer items-start gap-2 rounded-4 px-2 py-1.5 text-start hover:bg-surface-gray-1"
								@click="toggleKey(hit.key, !selected.has(hit.key))"
							>
								<Checkbox
									size="sm"
									class="mt-0.5"
									:model-value="selected.has(hit.key)"
									:aria-label="hit.node.title"
									@update:model-value="(value) => toggleKey(hit.key, value)"
									@click.stop
								/>
								<span class="min-w-0">
									<span class="block truncate text-sm text-ink-gray-9">{{
										hit.node.title
									}}</span>
									<span class="block truncate text-xs text-ink-gray-5">{{
										hit.path
									}}</span>
								</span>
							</button>
							<p
								v-if="!searchHits.length"
								class="px-2 py-4 text-sm text-ink-gray-5"
							>
								{{ __('Nothing found') }}
							</p>
						</template>
						<template v-else>
							<TreeNodeRow
								v-for="node in visibleNodes"
								:key="node.key"
								:node="node"
								:depth="0"
								:selected="selected"
								:expanded="expanded"
								@toggle="(payload) => onNodeToggle(payload)"
								@toggle-expand="onToggleExpand"
							/>
							<p
								v-if="!visibleNodes.length"
								class="px-2 py-4 text-sm text-ink-gray-5"
							>
								{{ __('This course has no materials yet') }}
							</p>
						</template>
					</div>
				</div>
			</div>
		</template>
		<template #actions>
			<div class="flex w-full items-center justify-between gap-2">
				<span
					class="text-sm text-ink-gray-6"
					data-testid="picker-selection-count"
				>
					{{ __('{0} selected').format(String(selected.size)) }}
				</span>
				<div class="flex items-center gap-2">
					<Button variant="subtle" @click="emit('cancel')">
						{{ __('Cancel') }}
					</Button>
					<!-- U03: an empty confirmation is how the last material is
					     removed from a draft -- the assignment-time ban is the
					     server's business, not the picker's. -->
					<Button
						variant="solid"
						@click="confirmSelection"
						data-testid="picker-confirm"
					>
						{{
							selected.size
								? __('Add selected ({0})').format(String(selected.size))
								: __('Save empty selection')
						}}
					</Button>
				</div>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { Button, Checkbox, Dialog, FormControl, call } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import TreeNodeRow from '@/components/HomeworkTreeNodeRow.vue'
import { createDialog } from '@/utils/dialogs'
import {
	checkState,
	collectLeafKeys,
	flattenWithPaths,
	toggleNode,
} from '@/utils/homeworkSelection'

// The spacious material picker (spec 3.4). It holds ONE selection Set across
// course switches, searches and reloads; only "Add selected" hands it to the
// form, and Cancel changes nothing (A08).
//
// R13: the confirm hands over the WHOLE edited set -- unchecking an attached
// material removes it. The trees of every course an attached item lives in are
// preloaded on open, so their indexes exist even if the teacher never browsed
// them; a selected key whose tree still failed to load keeps its stored item
// rather than silently dropping.
const props = defineProps({
	open: { type: Boolean, default: false },
	courses: { type: Array, default: () => [] },
	// Already attached items, pre-checked: switching chapters off and on keeps
	// the earlier choice (A06/A07).
	initialItems: { type: Array, default: () => [] },
})
const emit = defineEmits(['confirm', 'cancel'])

const courseSearch = ref('')
const materialSearch = ref('')
const activeCourse = ref('')
const selected = ref(new Set())
const expanded = ref(new Set())
const treeNodes = ref([])
const treeLoading = ref(false)

// Per-course leaf indexes (key -> node + readable path), built from each loaded
// tree and kept for the whole picker session: the confirmed selection may span
// several courses and must not be lost on switch (spec 3.4.3).
const indexesByCourse = ref(new Map())

// R11: trees load through real promises with a generation counter; the index is
// stored under the REQUESTED course -- a slow answer for course A arriving while
// course B is open can neither relabel A's materials as B's nor repaint B's tree.
let treeGeneration = 0

const filteredCourses = computed(() => {
	if (!courseSearch.value.trim()) return props.courses
	const needle = courseSearch.value.trim().toLowerCase()
	return props.courses.filter((course) =>
		course.title.toLowerCase().includes(needle)
	)
})

const loadTree = (course) => {
	const generation = ++treeGeneration
	treeLoading.value = true
	return call('lms.lms.homework_api.get_homework_course_tree', { course })
		.then((data) => {
			indexesByCourse.value.set(course, flattenWithPaths(data.nodes || []))
			treesByCourse.set(course, data.nodes || [])
			if (generation === treeGeneration && course === activeCourse.value) {
				paintCourseTree(course)
			}
		})
		.finally(() => {
			if (generation === treeGeneration) treeLoading.value = false
		})
}

const paintCourseTree = (course) => {
	const nodes = treesByCourse.get(course) || []
	treeNodes.value = nodes
	expanded.value = new Set(nodes.map((node) => node.key))
}

const visibleNodes = computed(() =>
	treeNodes.value.filter(
		(node) => node.assignable !== false || (node.children || []).length > 0
	)
)

const activeCourseLeaves = computed(() => {
	const nodes = visibleNodes.value.flatMap((node) => collectLeafKeys(node))
	return [...new Set(nodes)]
})

const wholeCourseState = computed(() => {
	const leaves = activeCourseLeaves.value
	if (!leaves.length) return 'unchecked'
	const picked = leaves.filter((key) => selected.value.has(key)).length
	if (picked === 0) return 'unchecked'
	if (picked === leaves.length) return 'checked'
	return 'indeterminate'
})

const toggleWholeCourse = (checked) => {
	const next = new Set(selected.value)
	for (const key of activeCourseLeaves.value) {
		if (checked) next.add(key)
		else next.delete(key)
	}
	selected.value = next
}

const searchHits = computed(() => {
	const index = indexesByCourse.value.get(activeCourse.value)
	if (!index || !materialSearch.value.trim()) return []
	const needle = materialSearch.value.trim().toLowerCase()
	const hits = []
	for (const [key, entry] of index) {
		if (entry.path.toLowerCase().includes(needle)) hits.push({ key, ...entry })
	}
	return hits.slice(0, 100)
})

// Whole node trees per course, for repainting a cached course without a fetch.
const treesByCourse = new Map()

watch(
	() => props.open,
	async (isOpen) => {
		if (!isOpen) return
		// Restore the attached items as checked leaves; keys are stable across
		// sessions (lesson:/quiz:/assignment: + docname).
		selected.value = new Set(props.initialItems.map(itemToKey))
		if (!activeCourse.value && props.courses.length) {
			activeCourse.value = props.courses[0].name
		}
		// R13: preload the trees of every course an attached item lives in, so
		// the confirm can rebuild the whole set -- including removing an
		// unchecked item from a course the teacher never opened this round.
		const initialCourses = [
			...new Set(props.initialItems.map((item) => item.course).filter(Boolean)),
		]
		const missing = initialCourses.filter(
			(course) => !treesByCourse.has(course)
		)
		if (missing.length)
			await Promise.allSettled(missing.map((course) => loadTree(course)))
		if (activeCourse.value && !treesByCourse.has(activeCourse.value)) {
			await loadTree(activeCourse.value)
		} else if (activeCourse.value) {
			paintCourseTree(activeCourse.value)
		}
	}
)

const itemToKey = (item) => {
	const type = String(item.source_type || 'Lesson').toLowerCase()
	return `${
		type === 'quiz' ? 'quiz' : type === 'assignment' ? 'assignment' : 'lesson'
	}:${item.name}`
}

watch(activeCourse, async (course) => {
	if (!course) return
	if (treesByCourse.has(course)) {
		paintCourseTree(course)
		return
	}
	await loadTree(course)
})

const selectCourse = (name) => {
	activeCourse.value = name
}

const toggleKey = (key, checked) => {
	const next = new Set(selected.value)
	if (checked) next.add(key)
	else next.delete(key)
	selected.value = next
}

const onNodeToggle = ({ node, checked }) => {
	// U03: unchecking a whole section drops every material under it in one
	// click (spec 3.3: show how many selected items this removes); Cancel
	// leaves the confirmed set untouched. Only an UNCHECK of a checked
	// container with selected leaves asks -- checking adds, leaf edits are
	// single items, and neither needs a dialog.
	if (
		!checked &&
		node.type === 'chapter' &&
		checkState(node, selected.value) === 'checked'
	) {
		const leaving = collectLeafKeys(node).filter((key) =>
			selected.value.has(key)
		).length
		if (leaving > 0) {
			createDialog({
				title: __('Remove materials'),
				message: __(
					'Unchecking "{0}" will remove {1} selected materials from the composition.'
				).format(node.title, String(leaving)),
				actions: [
					{
						label: __('Cancel'),
						variant: 'subtle',
					},
					{
						label: __('Remove'),
						variant: 'solid',
						onClick: () => {
							selected.value = toggleNode(node, selected.value, false)
						},
					},
				],
			})
			return
		}
	}
	selected.value = toggleNode(node, selected.value, checked)
}

const onToggleExpand = (key) => {
	const next = new Set(expanded.value)
	if (next.has(key)) next.delete(key)
	else next.add(key)
	expanded.value = next
}

const confirmSelection = () => {
	// The whole edited set: every selected key resolved through its loaded
	// index, plus any still-selected item whose tree never loaded (kept as it
	// was stored -- never silently dropped). Each resolved entry carries the
	// tree's own working link (B11), so the form can offer a preview before
	// anything is saved -- and a re-confirmed item never loses the route an
	// earlier load had attached.
	const entries = []
	const seen = new Set()
	for (const [courseName, index] of indexesByCourse.value) {
		for (const key of selected.value) {
			const found = index.get(key)
			if (!found) continue
			const type =
				found.node.type === 'chapter'
					? 'Lesson'
					: found.node.type.charAt(0).toUpperCase() + found.node.type.slice(1)
			const dedupeKey = `${type}:${found.node.name}`
			if (seen.has(dedupeKey)) continue
			seen.add(dedupeKey)
			entries.push({
				source_type: type,
				name: found.node.name,
				course: courseName,
				title: found.node.title,
				chapter: found.chapter,
				path: found.path,
				route: found.node.route || null,
			})
		}
	}
	for (const item of props.initialItems) {
		const key = itemToKey(item)
		if (!selected.value.has(key)) continue
		const dedupeKey = `${item.source_type}:${item.name}`
		if (seen.has(dedupeKey)) continue
		seen.add(dedupeKey)
		entries.push(item)
	}
	emit('confirm', entries)
}
</script>
