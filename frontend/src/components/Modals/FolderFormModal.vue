<template>
	<Dialog
		v-model:open="show"
		:title="mode === 'create' ? __('New folder') : __('Rename folder')"
		size="sm"
		:actions="[
			{
				label: mode === 'create' ? __('Create') : __('Save'),
				variant: 'solid',
				loading: saving,
				onClick: () => submit(),
			},
		]"
	>
		<template #default>
			<div class="space-y-3">
				<div
					v-if="mode === 'create' && contextTitles.length"
					class="text-sm text-ink-gray-6 truncate"
					:title="contextTitles.join(' › ')"
				>
					{{ __('Inside: {0}').format(contextTitles.join(' › ')) }}
				</div>
				<div v-if="mode === 'create'" class="text-sm text-ink-gray-5">
					{{
						__('A folder holds a set of images for this section.')
					}}
				</div>
				<FormControl
					ref="titleInput"
					v-model="title"
					:label="__('Folder title')"
					:placeholder="__('Materials')"
					autocomplete="off"
					:required="true"
					@keyup.enter="submit()"
					@keyup.esc="show = false"
				/>
				<div
					v-if="errorText"
					class="text-sm text-ink-red-5"
					data-testid="folder-form-error"
				>
					{{ errorText }}
				</div>
			</div>
		</template>
	</Dialog>
</template>

<script setup lang="ts">
import { Dialog, FormControl, createResource, toast } from 'frappe-ui'
import { nextTick, ref } from 'vue'
import type { FrappeResourceError } from 'frappe-ui'
import { resourceErrorMessage } from '@/utils/resource'
import type { OutlineChapter, OutlineFolder, Resource } from '@/types'

/** Create or rename an image folder of a section: one title field, Enter
 * submits, Esc cancels. Mirrors SectionFormModal's open/submit contract. */
const props = defineProps<{
	courseName: string
	outline: Resource<unknown>
}>()

const emit = defineEmits<{
	created: [folderName: string]
}>()

const show = ref(false)
const saving = ref(false)
const mode = ref<'create' | 'rename'>('create')
const title = ref('')
const errorText = ref('')
const chapter = ref<OutlineChapter | null>(null)
const folder = ref<OutlineFolder | null>(null)
const contextTitles = ref<string[]>([])
const titleInput = ref<{ el?: HTMLInputElement } | null>(null)

const createFolder = createResource({
	url: 'lms.lms.api.create_folder',
	makeParams(values: { title: string; chapter: string }) {
		return values
	},
	onSuccess(folderName: string) {
		saving.value = false
		toast.success(__('Folder created'))
		show.value = false
		props.outline.reload()
		emit('created', folderName)
	},
	onError(err: FrappeResourceError) {
		saving.value = false
		errorText.value = resourceErrorMessage(err, __('Error'))
	},
})

const renameFolder = createResource({
	url: 'lms.lms.api.rename_folder',
	makeParams(values: { folder: string; title: string }) {
		return values
	},
	onSuccess() {
		saving.value = false
		toast.success(__('Folder renamed'))
		show.value = false
		props.outline.reload()
	},
	onError(err: FrappeResourceError) {
		saving.value = false
		errorText.value = resourceErrorMessage(err, __('Error'))
	},
})

function openCreate(parentChapter: OutlineChapter, pathTitles: string[]) {
	mode.value = 'create'
	chapter.value = parentChapter
	folder.value = null
	contextTitles.value = pathTitles ?? []
	title.value = ''
	errorText.value = ''
	show.value = true
	focusTitle()
}

function openRename(target: OutlineFolder) {
	mode.value = 'rename'
	chapter.value = null
	folder.value = target
	contextTitles.value = []
	title.value = target.title
	errorText.value = ''
	show.value = true
	focusTitle()
}

function focusTitle() {
	nextTick(() => {
		const el = titleInput.value?.$el?.querySelector('input')
		if (el instanceof HTMLInputElement) el.focus()
	})
}

function submit() {
	const value = title.value.trim()
	if (!value || saving.value) return
	saving.value = true
	errorText.value = ''
	if (mode.value === 'create' && chapter.value) {
		createFolder.submit({ title: value, chapter: chapter.value.name })
	} else if (folder.value) {
		renameFolder.submit({ folder: folder.value.name, title: value })
	} else {
		saving.value = false
	}
}

defineExpose({ openCreate, openRename })
</script>
