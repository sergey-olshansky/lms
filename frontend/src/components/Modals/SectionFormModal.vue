<template>
	<Dialog
		v-model:open="show"
		:title="__('New section')"
		size="sm"
		:actions="[
			{
				label: __('Add'),
				variant: 'solid',
				loading: saving,
				onClick: () => submit(),
			},
		]"
	>
		<template #default>
			<div class="space-y-3">
				<div
					v-if="contextTitles.length"
					class="text-sm text-ink-gray-6 truncate"
					:title="contextTitles.join(' › ')"
				>
					{{ __('Inside: {0}').format(contextTitles.join(' › ')) }}
				</div>
				<div class="text-sm text-ink-gray-5">
					{{ __('Level {0} of 2').format(levelOfNew) }}
				</div>
				<FormControl
					ref="titleInput"
					v-model="title"
					:label="__('Title')"
					:placeholder="__('Section')"
					autocomplete="off"
					:required="true"
					@keyup.enter="submit()"
					@keyup.esc="show = false"
				/>
				<div v-if="errorText" class="text-sm text-ink-red-5" data-testid="add-section-error">
					{{ errorText }}
				</div>
			</div>
		</template>
	</Dialog>
</template>

<script setup lang="ts">
import { Dialog, FormControl, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import type { FrappeResourceError } from 'frappe-ui'
import { createResource } from 'frappe-ui'
import { resourceErrorMessage } from '@/utils/resource'
import type { OutlineChapter, Resource } from '@/types'

/**
 * Creates a nested section under a given parent (design §4.3): a small dialog
 * with the "Inside: …" context line, the "Level N of 2" helper and a title
 * field. The level-2 ceiling is enforced by the caller not offering the
 * dialog, and again server-side on save.
 */
const props = defineProps<{
	courseName: string
	outline: Resource<OutlineChapter[] | null>
}>()

const emit = defineEmits<{
	created: [sectionName: string]
}>()

const show = ref(false)
const saving = ref(false)
const title = ref('')
const errorText = ref('')
const parent = ref<OutlineChapter | null>(null)
const parentPathTitles = ref<string[]>([])
const titleInput = ref<{ el?: HTMLInputElement } | null>(null)

const levelOfNew = computed<number>(() => (parent.value?.level ?? 0) + 1)

const contextTitles = computed<string[]>(() => parentPathTitles.value)

const createSection = createResource({
	url: 'lms.lms.api.upsert_chapter',
	makeParams(values: { title: string; parent_section: string }) {
		return {
			title: values.title,
			course: props.courseName,
			is_scorm_package: false,
			parent_section: values.parent_section,
		}
	},
	onSuccess(section: OutlineChapter) {
		saving.value = false
		toast.success(__('Section created'))
		show.value = false
		props.outline.reload()
		emit('created', section.name)
	},
	onError(err: FrappeResourceError) {
		saving.value = false
		// The dialog stays open with the reason: a depth or permission refusal
		// never closes into a silent error (design §4.4).
		errorText.value = resourceErrorMessage(err, __('Error'))
	},
})

function open(parentSection: OutlineChapter, pathTitles: string[]) {
	parent.value = parentSection
	parentPathTitles.value = pathTitles ?? []
	title.value = ''
	errorText.value = ''
	show.value = true
}

function submit() {
	if (!parent.value || !title.value.trim() || saving.value) return
	saving.value = true
	errorText.value = ''
	createSection.submit({
		title: title.value.trim(),
		parent_section: parent.value.name,
	})
}

watch(show, (openNow) => {
	if (openNow) {
		// Autofocus mirrors the chapterTitleAutofocus pattern: Enter submits,
		// Esc cancels.
		requestAnimationFrame(() => {
			const el = titleInput.value?.$el?.querySelector('input')
			if (el instanceof HTMLInputElement) el.focus()
		})
	}
})

defineExpose({ open })
</script>
