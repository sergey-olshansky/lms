<template>
	<DataImport
		:doctype="doctype"
		:import-name="importName"
		:doctype-map="doctypeMap"
	/>
</template>

<script setup lang="ts">
import { computed, inject, onMounted } from 'vue'
import { usePageMeta } from 'frappe-ui'
import { DataImport } from '@framework/ui/components/DataImport/index'
import { useRoute, useRouter } from 'vue-router'
import { sessionStore } from '../stores/session'

const { brand } = sessionStore()
const route = useRoute()
const router = useRouter()
const user = inject<any>('$user')

const doctype = computed(() => {
	const value = route.params.doctype
	return Array.isArray(value) ? value[0] : value
})
const importName = computed(() => {
	const value = route.params.importName
	return Array.isArray(value) ? value[0] : value
})

const doctypeMap: Record<
	string,
	{ title: string; listRoute?: string; pageRoute?: string }
> = {
	'LMS Course': {
		title: __('Course'),
		listRoute: '/courses',
		pageRoute: '/courses/docname',
	},
	'LMS Batch': {
		title: __('Batch'),
		listRoute: '/batches',
	},
	'LMS Category': {
		title: __('Category'),
		listRoute: '/lms',
	},
}

onMounted(() => {
	if (!user?.data?.is_moderator) {
		router.push({ name: 'Courses' })
	}
})

usePageMeta(() => ({
	title: __('Data Import'),
	icon: brand.favicon,
}))
</script>
