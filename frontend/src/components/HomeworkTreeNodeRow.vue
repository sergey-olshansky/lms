<template>
	<div>
		<div
			class="flex items-center gap-2 rounded-4 px-2 py-1.5 hover:bg-surface-gray-1"
			:style="{ paddingInlineStart: `${depth * 16 + 8}px` }"
		>
			<button
				v-if="node.type === 'chapter'"
				type="button"
				class="rounded-4 p-0.5 text-ink-gray-6 hover:bg-surface-gray-2"
				:aria-expanded="isExpanded"
				:aria-label="isExpanded ? __('Collapse') : __('Expand')"
				@click="emit('toggle-expand', node.key)"
			>
				<span
					class="block size-4 transition-transform"
					:class="isExpanded ? 'lucide-chevron-down' : 'lucide-chevron-right'"
				/>
			</button>
			<span v-else class="inline-block size-4 shrink-0 text-ink-gray-5">
				<span :class="iconClass" class="block size-4" aria-hidden="true" />
			</span>

			<Checkbox
				size="sm"
				:model-value="state === 'checked'"
				:indeterminate="state === 'indeterminate'"
				:disabled="leafCount === 0"
				:data-testid="`tree-check-${node.key}`"
				:aria-label="node.title"
				@update:model-value="
					(value) => emit('toggle', { node, checked: value })
				"
			/>

			<button
				type="button"
				class="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-start disabled:cursor-not-allowed"
				:disabled="leafCount === 0"
				:title="node.title"
				@click="emit('toggle', { node, checked: state !== 'checked' })"
			>
				<span class="min-w-0 flex-1 truncate text-sm text-ink-gray-9">
					{{ node.title }}
				</span>
				<span
					v-if="node.type === 'lesson' && (node.quizzes || []).length"
					class="shrink-0 rounded-4 bg-surface-gray-2 px-1.5 py-0.5 text-xs text-ink-gray-6"
				>
					{{ __('{0} quizzes').format(String((node.quizzes || []).length)) }}
				</span>
				<span
					v-else-if="node.type === 'quiz'"
					class="shrink-0 rounded-4 bg-surface-gray-2 px-1.5 py-0.5 text-xs text-ink-gray-6"
				>
					{{ __('Quiz') }}
				</span>
				<span
					v-else-if="node.type === 'assignment'"
					class="shrink-0 rounded-4 bg-surface-gray-2 px-1.5 py-0.5 text-xs text-ink-gray-6"
				>
					{{ __('Assignment') }}
				</span>
			</button>
		</div>

		<div v-if="node.type === 'chapter' && isExpanded">
			<HomeworkTreeNodeRow
				v-for="child in node.children || []"
				:key="child.key"
				:node="child"
				:depth="depth + 1"
				:selected="selected"
				:expanded="expanded"
				@toggle="(payload) => emit('toggle', payload)"
				@toggle-expand="(key) => emit('toggle-expand', key)"
			/>
		</div>
	</div>
</template>

<script setup>
// One recursive row of the homework material tree: a tri-state Checkbox (the
// intermediate state is a DOM property the frappe-ui control owns), an expand
// toggle for chapters, and the embedded-quiz count that makes "quizzes ride
// with the lesson" visible before selecting (spec 3.4). The self-reference is
// named so both the SFC compiler and the unresolved-tag guard resolve it.
import { computed } from 'vue'
import { Checkbox } from 'frappe-ui'
import { checkState, collectLeafKeys } from '@/utils/homeworkSelection'

defineOptions({ name: 'HomeworkTreeNodeRow' })

const props = defineProps({
	node: { type: Object, required: true },
	depth: { type: Number, default: 0 },
	selected: { type: Object, required: true },
	expanded: { type: Object, required: true },
})
const emit = defineEmits(['toggle', 'toggle-expand'])

const leafCount = computed(() => collectLeafKeys(props.node).length)
const state = computed(() => checkState(props.node, props.selected))
const isExpanded = computed(() => props.expanded.has(props.node.key))

const iconClass = computed(() => {
	if (props.node.type === 'lesson') return 'lucide-file-text'
	if (props.node.type === 'quiz') return 'lucide-circle-help'
	if (props.node.type === 'assignment') return 'lucide-pencil'
	return 'lucide-folder'
})
</script>
