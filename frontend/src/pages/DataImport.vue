<template>
	<PageHeader :breadcrumbs="breadcrumbs" />
	<div class="data-import-host">
		<DataImportWizard
			:dataImport="dataImport"
			@open-list="openList"
			@open-record="openRecord"
			@open-imports="openImports"
			@new-import="newImport"
		/>
	</div>
</template>
<script setup lang="ts">
import { usePageMeta } from 'frappe-ui'
import {
	DataImportWizard,
	useDataImport,
} from '@framework/ui/components/DataImport/index'
import PageHeader from '@/components/Layouts/pages/PageHeader.vue'
import type { Breadcrumb } from '@/types'
import { sessionStore } from '../stores/session'
import { useRoute, useRouter } from 'vue-router'
import { computed, inject, onMounted, ref, watch } from 'vue'

const { brand } = sessionStore()
const route = useRoute()
const router = useRouter()
const user = inject<any>('$user')

// Both route segments are single dynamic params (routes.js), never repeated —
// narrowed here because vue-router types every param as `string | string[]`
// while `useDataImport` takes a `string | null` name (and a plain `string`
// doctype) back.
const doctypeParam = computed(() =>
	Array.isArray(route.params.doctype)
		? route.params.doctype[0]
		: route.params.doctype
)
const importNameParam = computed(() =>
	Array.isArray(route.params.importName)
		? route.params.importName[0]
		: route.params.importName
)

// The app owns the import's name now: null starts a new import, the wizard
// fills the name in on the first save, and the URL is brought back in step.
const importName = ref<string | null>(importNameParam.value ?? null)
watch(importNameParam, (next) => {
	importName.value = next ?? null
})
watch(importName, (next) => {
	if (!next || route.params.importName === next) return
	router.replace({ name: 'DataImport', params: { importName: next } })
})

const dataImport = useDataImport(importName, { doctype: doctypeParam })

onMounted(() => {
	if (!user.data?.is_moderator) {
		router.push({
			name: 'Courses',
		})
	}
})

// The old `DataImport` component took a `doctypeMap` and navigated itself:
// its Done button went to the doctype's list route and imported rows to its
// page route. `DataImportWizard` asks the app instead, so the same mapping
// answers here.
type ImportRoutes = { listRoute?: string; pageRoute?: string }

const doctypeMap: Record<string, ImportRoutes> = {
	'LMS Course': {
		listRoute: '/courses',
		pageRoute: `/courses/docname`,
	},
	'LMS Batch': {
		listRoute: '/batches',
	},
	'LMS Category': {
		listRoute: '/lms',
	},
}

const openList = (doctype: string) => {
	const listRoute = doctypeMap[doctype]?.listRoute
	if (listRoute) window.location.href = listRoute
}

const openRecord = (doctype: string, docname: string) => {
	const pageRoute = doctypeMap[doctype]?.pageRoute
	if (pageRoute) window.location.href = pageRoute.replace('docname', docname)
}

// The built-in list of past imports went away with the old component; the
// closest LMS page for "Review pending imports" is the import home.
const openImports = () => {
	router.push({ name: 'DataImportList' })
}

const newImport = (doctype: string) => {
	router.push({ name: 'NewDataImport', params: { doctype } })
}

// Named here rather than taken from the imported component: its own trail is
// internal state we cannot reach, and the page still needs a back link on a
// phone.
const breadcrumbs = computed<Breadcrumb[]>(() => {
	const crumbs: Breadcrumb[] = [
		{ label: __('Data Import'), route: { name: 'DataImportList' } },
	]
	if (route.params.importName) crumbs.push({ label: __('Import') })
	else if (route.params.doctype)
		crumbs.push({ label: String(route.params.doctype) })
	return crumbs
})

usePageMeta(() => {
	return {
		title: __('Data Import'),
		icon: brand.favicon,
	}
})
</script>

<style scoped>
/* The wizard fills its parent's height, and the desktop layout's main column
   is a flex column, so the host takes the space left under the page header.
   On layouts without such a column the host simply grows with the wizard. */
.data-import-host {
	flex: 1;
	min-height: 0;
}
</style>
