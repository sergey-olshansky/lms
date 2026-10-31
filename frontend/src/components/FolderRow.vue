<template>
	<div
		class="outline-row outline-folder-row flex w-full min-w-0 items-start gap-2 rounded-4 px-2 py-2 text-ink-gray-9 transition-colors hover:bg-surface-gray-1"
		data-testid="outline-folder"
	>
		<OutlineActionButton
			v-if="allowEdit"
			:label="__('Move folder up')"
			:disabled="position <= 1"
			@click.prevent.stop="emit('move-folder', 'up')"
		>
			<span class="lucide-chevron-up size-4" aria-hidden="true" />
		</OutlineActionButton>
		<OutlineActionButton
			v-if="allowEdit"
			:label="__('Move folder down')"
			:disabled="position >= siblingCount"
			@click.prevent.stop="emit('move-folder', 'down')"
		>
			<span class="lucide-chevron-down size-4" aria-hidden="true" />
		</OutlineActionButton>
		<router-link
			:to="folderRoute"
			class="flex min-w-0 flex-1 cursor-pointer items-start gap-2 py-1.5 text-start text-sm leading-5"
			:title="folder.title"
			data-testid="open-folder"
		>
			<span class="lucide-folder mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
			<span class="min-w-0 flex-1 whitespace-normal break-words">{{
				folder.title
			}}</span>
			<span
				class="ms-2 inline whitespace-nowrap align-baseline text-sm font-normal leading-5 text-ink-gray-5"
			>
				{{ imagesLabel }}
			</span>
		</router-link>
		<div
			v-if="allowEdit"
			class="outline-actions ms-auto flex shrink-0 items-center justify-end gap-1"
		>
			<OutlineActionButton
				:label="__('Rename folder')"
				@click.prevent.stop="emit('rename-folder', folder)"
			>
				<span class="lucide-pencil-line size-4" aria-hidden="true" />
			</OutlineActionButton>
			<OutlineActionButton
				:label="__('Delete folder')"
				@click.prevent.stop="emit('delete-folder', folder)"
			>
				<span class="lucide-trash-2 size-4" aria-hidden="true" />
			</OutlineActionButton>
		</div>
	</div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { RouteLocationRaw } from 'vue-router'
import OutlineActionButton from '@/components/OutlineActionButton.vue'
import type { OutlineFolder } from '@/types'

// An image folder as a child row of a section: a plain material row next to
// lessons and nested sections. Reorder stays in the section's single mixed
// order (up/down buttons — folders are deliberately outside the lesson/section
// drag group), and opening NAVIGATES to the folder's own page, the way a
// lesson row navigates to its lesson (task #39 UI correction: the gallery is
// no longer an overlay over the course overview).
const props = withDefaults(
	defineProps<{
		folder: OutlineFolder
		courseName?: string
		allowEdit?: boolean
		/** 1-based position among ALL child rows of the parent section. */
		position?: number
		siblingCount?: number
	}>(),
	{
		courseName: '',
		allowEdit: false,
		position: 1,
		siblingCount: 1,
	}
)

const emit = defineEmits<{
	'rename-folder': [OutlineFolder]
	'delete-folder': [OutlineFolder]
	'move-folder': ['up' | 'down']
}>()

const folderRoute = computed<RouteLocationRaw>(() => ({
	name: 'CourseFolder',
	params: { courseName: props.courseName, folderName: props.folder.name },
}))

const imagesLabel = computed<string>(() => {
	const count = props.folder.image_count ?? props.folder.images?.length ?? 0
	return `${count} ${count === 1 ? __('image') : __('images')}`
})
</script>

<style scoped>
.outline-actions {
	opacity: 0;
	pointer-events: none;
	transition:
		opacity 140ms ease,
		background-color 140ms ease;
}

.outline-row:hover .outline-actions,
.outline-row:focus-within .outline-actions {
	opacity: 1;
	pointer-events: auto;
}

@media (hover: none) {
	.outline-actions {
		opacity: 1;
		pointer-events: auto;
	}
}
</style>
