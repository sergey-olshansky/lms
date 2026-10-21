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
					<FormControl
						type="text"
						v-model="materialSearch"
						:placeholder="__('Search materials')"
						:aria-label="__('Search materials')"
					>
						<template #prefix>
							<span class="lucide-search size-4 text-ink-gray-5" />
						</template>
					</FormControl>
					<div
						class="flex-1 overflow-y-auto rounded-4 border border-outline-gray-2 p-2"
					>
						<div v-if="tree.loading" class="p-4 text-sm text-ink-gray-5">
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
					<Button
						variant="solid"
						:disabled="selected.size === 0"
						@click="confirmSelection"
						data-testid="picker-confirm"
					>
						{{ __('Add selected ({0})').format(String(selected.size)) }}
					</Button>
				</div>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import {
	Button,
	Checkbox,
	Dialog,
	FormControl,
	createResource,
} from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import TreeNodeRow from '@/components/HomeworkTreeNodeRow.vue'
import { flattenWithPaths, toggleNode } from '@/utils/homeworkSelection'

// The spacious material picker (spec 3.4). It holds ONE selection Set across
// course switches, searches and reloads; only "Add selected" hands it to the
// form, and Cancel changes nothing (A08).
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

// Per-course leaf indexes (key -> node + readable path), built from each loaded
// tree and kept for the whole picker session: the confirmed selection may span
// several courses and must not be lost on switch (spec 3.4.3).
const indexesByCourse = ref(new Map())

const filteredCourses = computed(() => {
	if (!courseSearch.value.trim()) return props.courses
	const needle = courseSearch.value.trim().toLowerCase()
	return props.courses.filter((course) =>
		course.title.toLowerCase().includes(needle)
	)
})

const tree = createResource({
	url: 'lms.lms.homework_api.get_homework_course_tree',
	makeParams() {
		return { course: activeCourse.value }
	},
	onSuccess(data) {
		const index = flattenWithPaths(data.nodes || [])
		indexesByCourse.value.set(activeCourse.value, index)
		// The chosen course opens expanded to its first level.
		expanded.value = new Set((data.nodes || []).map((node) => node.key))
	},
})

const visibleNodes = computed(() =>
	(tree.data?.nodes || []).filter(
		(node) => node.assignable !== false || (node.children || []).length > 0
	)
)

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

watch(
	() => props.open,
	(isOpen) => {
		if (!isOpen) return
		// Restore the attached items as checked leaves once their trees load;
		// keys are stable across sessions (lesson:/quiz:/assignment: + docname).
		selected.value = new Set(props.initialItems.map(itemToKey))
		if (!activeCourse.value && props.courses.length) {
			activeCourse.value = props.courses[0].name
		}
		if (activeCourse.value) tree.reload()
	}
)

const itemToKey = (item) => {
	const type = String(item.source_type || 'Lesson').toLowerCase()
	return `${
		type === 'quiz' ? 'quiz' : type === 'assignment' ? 'assignment' : 'lesson'
	}:${item.name}`
}

watch(activeCourse, () => {
	if (activeCourse.value) tree.reload()
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
	selected.value = toggleNode(node, selected.value, checked)
}

const onToggleExpand = (key) => {
	const next = new Set(expanded.value)
	if (next.has(key)) next.delete(key)
	else next.add(key)
	expanded.value = next
}

const confirmSelection = () => {
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
			})
		}
	}
	emit('confirm', entries)
}
</script>
