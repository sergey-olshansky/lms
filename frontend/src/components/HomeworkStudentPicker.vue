<template>
	<div class="min-w-0 space-y-1.5" data-testid="homework-student-picker">
		<FormControl
			v-if="knownRows.length > 8"
			v-model="search"
			type="text"
			:placeholder="__('Search students')"
			:aria-label="__('Search students')"
		/>
		<Select
			:model-value="modelValue"
			:options="options"
			:label="label"
			:placeholder="__(emptyLabel)"
			@update:model-value="emit('update:modelValue', $event || '')"
		/>
		<button
			type="button"
			class="text-xs text-ink-gray-6 underline"
			@click="lookupOpen = !lookupOpen"
		>
			{{ __('Find another student by email') }}
		</button>
		<div
			v-if="lookupOpen"
			class="space-y-2 rounded-5 border border-outline-gray-2 bg-surface-gray-1 p-3"
		>
			<p class="text-xs text-ink-gray-6">
				{{
					__(
						'Enter the email the student uses to sign in. A new student needs to register on this site first.'
					)
				}}
			</p>
			<div class="flex flex-wrap gap-2">
				<FormControl
					v-model="email"
					type="email"
					class="min-w-0 flex-1"
					:placeholder="__('Student email')"
					:aria-label="__('Student email')"
					@keydown.enter.prevent="findStudent"
				/>
				<Button
					size="sm"
					:loading="finding"
					:disabled="!email.trim()"
					@click="findStudent"
					>{{ __('Select student') }}</Button
				>
			</div>
		</div>
	</div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Button, FormControl, call, createResource, toast } from 'frappe-ui'
import Select from '@/components/Controls/Select.vue'
import { resourceErrorMessage } from '@/utils/resource'

const props = defineProps({
	modelValue: { type: String, default: '' },
	label: { type: String, default: 'Student' },
	emptyLabel: { type: String, default: 'Choose a student' },
})
const emit = defineEmits(['update:modelValue'])
const lookupOpen = ref(false)
const email = ref('')
const finding = ref(false)
const search = ref('')
const extra = ref([])
const students = createResource({
	url: 'lms.lms.homework_api.get_homework_students',
	auto: true,
	onError: (error) => toast.error(resourceErrorMessage(error, __('Error'))),
})
const knownRows = computed(() =>
	Array.from(
		new Map(
			[...(students.data || []), ...extra.value].map((row) => [row.name, row])
		).values()
	)
)
const options = computed(() => [
	{ label: __(props.emptyLabel), value: '' },
	...knownRows.value
		.filter(
			(row) =>
				row.name === props.modelValue ||
				`${row.full_name || ''} ${row.name}`
					.toLowerCase()
					.includes(search.value.trim().toLowerCase())
		)
		.map((row) => ({
			label: `${row.full_name || row.name} · ${row.name}`,
			value: row.name,
		})),
])
const resolveStudent = async (address) => {
	const row = await call('lms.lms.homework_api.find_homework_student', {
		email: address,
	})
	extra.value = [...extra.value.filter((item) => item.name !== row.name), row]
	return row
}
const findStudent = async () => {
	if (finding.value || !email.value.trim()) return
	finding.value = true
	try {
		const row = await resolveStudent(email.value.trim())
		emit('update:modelValue', row.name)
		lookupOpen.value = false
		email.value = ''
	} catch (error) {
		toast.error(resourceErrorMessage(error, __('Error')))
	} finally {
		finding.value = false
	}
}
// A student selected outside this picker may not be in the teacher's roster
// until the first assignment creates that relation. Resolve that exact email.
watch(
	() => props.modelValue,
	async (value) => {
		if (!value || options.value.some((option) => option.value === value)) return
		try {
			await resolveStudent(value)
		} catch {
			/* the assigning API validates again */
		}
	},
	{ immediate: true }
)
</script>
