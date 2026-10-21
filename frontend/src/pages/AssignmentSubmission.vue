<template>
	<PageHeader v-if="!fromLesson" :breadcrumbs="breadcrumbs" />
	<!-- Task #35 (R10): a written assignment opened through the homework carries
	its context; the confirmed opening is the agreed condition for it. -->
	<HomeworkContextBanner
		v-if="homeworkContext"
		:assignment-id="homeworkContext"
		data-testid="homework-back-banner"
	/>
	<div class="overflow-hidden h-[calc(100vh-3.2rem)]">
		<Assignment
			:key="`${assignmentID}-${submissionName}`"
			:assignmentID="assignmentID"
			:submissionName="submissionName"
			:showTitle="!fromLesson"
		/>
	</div>
</template>
<script setup lang="ts">
import { call, createResource, usePageMeta } from 'frappe-ui'
import PageHeader from '@/components/Layouts/pages/PageHeader.vue'
import HomeworkContextBanner from '@/components/HomeworkContextBanner.vue'
import { computed, inject, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { sessionStore } from '../stores/session'
import Assignment from '@/components/Assignment.vue'
import { provideStudentView } from '@/composables/useStudentView'
import type { UserResource } from '@/composables/useStudentView'

const user = inject<UserResource>('$user')!
const route = useRoute()
const fromLesson = ref(false)
const { brand } = sessionStore()

// Old lesson-iframe links carry Student View in the URL. Honoured so a moderator
// on such a link never sees the Grading panel for their own submission.
const studentView = ref(
	new URLSearchParams(window.location.search).get('studentView') === '1'
)
provideStudentView(user, () => studentView.value)

const props = withDefaults(
	defineProps<{
		assignmentID: string
		submissionName?: string
	}>(),
	{ submissionName: 'new' }
)

const homeworkContext = computed(() =>
	typeof route.query.hw === 'string' ? route.query.hw : ''
)

const title = createResource<{ title: string }>({
	url: 'frappe.client.get_value',
	params: {
		doctype: 'LMS Assignment',
		fieldname: 'title',
		filters: {
			name: props.assignmentID,
		},
	},
	auto: true,
})

onMounted(() => {
	if (!user.data) {
		window.location.href = '/login'
	}

	if (new URLSearchParams(window.location.search).get('fromLesson')) {
		fromLesson.value = true
	}

	// R10: the student has the assignment's own page open -- a confirmed
	// opening of the material, credited wherever it is required. The server
	// re-checks the viewer's right to see it.
	call('lms.lms.homework_api.record_assignment_material_opened', {
		assignment: props.assignmentID,
	}).catch(() => {})
})

const breadcrumbs = computed(() => {
	const crumbs = [
		{
			label: __('Assignments'),
			route: { name: 'Assignments' },
		},
		{
			label: __('Submissions'),
			route: { name: 'AssignmentSubmissions' },
		},
		{
			label: title.data?.title ?? '',
			route: {
				name: 'AssignmentSubmission',
				params: {
					assignmentID: props.assignmentID,
				},
			},
		},
	]
	return crumbs
})

usePageMeta(() => {
	return {
		title: title.data?.title,
		icon: brand.favicon,
	}
})
</script>
