<template>
	<Dialog
		:open="open"
		:title="__('Homework groups')"
		size="lg"
		@update:open="(value) => (value ? null : emit('close'))"
	>
		<template #default>
			<div v-if="open" class="space-y-4 text-base">
				<div class="flex items-end gap-2">
					<FormControl
						type="text"
						v-model="newTitle"
						:placeholder="__('New group title')"
						:aria-label="__('New group title')"
						class="flex-1"
					/>
					<Select
						v-model="newParent"
						:options="parentOptions"
						:placeholder="__('No parent')"
					/>
					<Button variant="solid" :disabled="!newTitle.trim()" @click="create">
						{{ __('Create') }}
					</Button>
				</div>
				<p class="text-sm text-ink-gray-5">
					{{
						__(
							'Groups nest two levels deep: a subgroup cannot contain another group.'
						)
					}}
				</p>

				<div
					class="max-h-72 divide-y divide-outline-gray-1 overflow-y-auto rounded-4 border border-outline-gray-2"
				>
					<p
						v-if="!groups.data || !groups.data.length"
						class="px-3 py-4 text-sm text-ink-gray-5"
					>
						{{ __('No groups yet') }}
					</p>
					<div
						v-for="group in groups.data || []"
						:key="group.name"
						class="flex items-center gap-2 px-3 py-2"
					>
						<template v-if="editing === group.name">
							<FormControl
								type="text"
								v-model="editTitle"
								class="flex-1"
								:aria-label="__('Title')"
							/>
							<Select
								v-model="editParent"
								:options="parentOptionsFor(group)"
								:placeholder="__('No parent')"
							/>
							<Button size="sm" variant="solid" @click="save(group)">{{
								__('Save')
							}}</Button>
							<Button size="sm" variant="subtle" @click="editing = ''">{{
								__('Cancel')
							}}</Button>
						</template>
						<template v-else>
							<span
								class="min-w-0 flex-1 truncate text-sm text-ink-gray-9"
								:title="group.path"
							>
								{{ group.path }}
							</span>
							<Button size="sm" variant="ghost" @click="startEdit(group)">
								<template #icon>
									<span class="lucide-pencil size-4" aria-hidden="true" />
								</template>
							</Button>
							<Button size="sm" variant="ghost" @click="remove(group)">
								<template #icon>
									<span class="lucide-trash-2 size-4" aria-hidden="true" />
								</template>
							</Button>
						</template>
					</div>
				</div>
			</div>
		</template>
		<template #actions>
			<Button variant="subtle" @click="emit('close')">{{ __('Close') }}</Button>
		</template>
	</Dialog>
</template>

<script setup>
// Group management (spec 3.2): create, rename, move between root groups, delete
// an empty one. Depth, cycles and ownership are enforced server-side; the
// dialog only surfaces their refusals.
import { Button, Dialog, FormControl, createResource, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import Select from '@/components/Controls/Select.vue'
import { resourceErrorMessage } from '@/utils/resource'

const props = defineProps({ open: { type: Boolean, default: false } })
const emit = defineEmits(['close', 'changed'])

const groups = createResource({
	url: 'lms.lms.homework_api.list_homework_groups',
})
watch(
	() => props.open,
	(isOpen) => {
		if (isOpen) groups.reload()
	}
)

const newTitle = ref('')
const newParent = ref('')
const editing = ref('')
const editTitle = ref('')
const editParent = ref('')

// A subgroup can only be filed under a first-level group; root groups are the
// only valid parents, and the select for editing excludes the group itself.
const rootGroups = computed(() =>
	(groups.data || []).filter((group) => !group.parent_group)
)

const parentOptions = computed(() => [
	{ label: __('No parent'), value: '' },
	...rootGroups.value.map((group) => ({
		label: group.title,
		value: group.name,
	})),
])

const parentOptionsFor = (group) =>
	parentOptions.value.filter((option) => option.value !== group.name)

const create = async () => {
	try {
		await call('lms.lms.homework_api.save_homework_group', {
			title: newTitle.value,
			parent_group: newParent.value || null,
		})
		newTitle.value = ''
		newParent.value = ''
		toast.success(__('Group created'))
		groups.reload()
		emit('changed')
	} catch (err) {
		toast.error(resourceErrorMessage(err, __('Error')))
	}
}

const startEdit = (group) => {
	editing.value = group.name
	editTitle.value = group.title
	editParent.value = group.parent_group || ''
}

const save = async (group) => {
	try {
		await call('lms.lms.homework_api.save_homework_group', {
			name: group.name,
			title: editTitle.value,
			parent_group: editParent.value || null,
		})
		editing.value = ''
		toast.success(__('Group saved'))
		groups.reload()
		emit('changed')
	} catch (err) {
		toast.error(resourceErrorMessage(err, __('Error')))
	}
}

const remove = async (group) => {
	if (!window.confirm(__('Delete the group {0}?').format(group.title))) return
	try {
		await call('lms.lms.homework_api.delete_homework_group', {
			name: group.name,
		})
		toast.success(__('Group deleted'))
		groups.reload()
		emit('changed')
	} catch (err) {
		toast.error(resourceErrorMessage(err, __('Error')))
	}
}

const call = (url, params) =>
	new Promise((resolve, reject) => {
		createResource({
			url,
			params,
			auto: true,
			onSuccess: resolve,
			onError: reject,
		})
	})
</script>
