<template>
	<nav
		class="flex gap-1 border-b border-outline-gray-2 px-4 py-2 md:px-6"
		:aria-label="__('Homework sections')"
	>
		<router-link
			v-for="tab in tabs"
			:key="tab.route"
			:to="{ name: tab.route, query: { student: student || undefined } }"
			:aria-current="active === tab.route ? 'page' : undefined"
			class="rounded-5 px-3 py-2 text-sm font-medium transition-colors"
			:class="
				active === tab.route
					? 'bg-surface-gray-3 text-ink-gray-9'
					: 'text-ink-gray-6 hover:bg-surface-gray-2'
			"
			>{{ __(tab.label) }}</router-link
		>
	</nav>
</template>

<script setup>
defineProps({
	active: { type: String, required: true },
	student: { type: String, default: '' },
})
const tabs = [
	{ route: 'HomeworkLibrary', label: 'Homework templates' },
	{ route: 'HomeworkExecution', label: 'Assigned homework' },
]
</script>
