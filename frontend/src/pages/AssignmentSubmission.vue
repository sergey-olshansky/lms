<template>
	<PageHeader v-if="!fromLesson" :breadcrumbs="breadcrumbs" />
	<!-- Task #35 (R10/B10/C04): a written assignment opened through the
	     homework carries its context; the confirmed opening is the agreed
	     condition for it. The opening is recorded after the material actually
	     loaded and rendered (the child's `displayed` event) for EVERY visitor
	     of the material's own page -- ?hw= or not: working the course directly
	     counts just as much (A22), and the server itself finds only this
	     student's applicable assignments and refuses everyone else's events. -->
	<HomeworkContextBanner
		v-if="homeworkContext"
		ref="homeworkBanner"
		:assignment-id="homeworkContext"
		data-testid="homework-back-banner"
	/>
	<div class="overflow-hidden h-[calc(100vh-3.2rem)]">
		<Assignment
			:key="`${assignmentID}-${submissionName}`"
			:assignmentID="assignmentID"
			:submissionName="submissionName"
			:showTitle="!fromLesson"
			@displayed="onAssignmentDisplayed"
		/>
	</div>
</template>
<script setup lang="ts">
import { call, createResource, usePageMeta } from 'frappe-ui'
import PageHeader from '@/components/Layouts/pages/PageHeader.vue'
import HomeworkContextBanner from '@/components/HomeworkContextBanner.vue'
import { computed, inject, onMounted, ref, watch } from 'vue'
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

const homeworkBanner = ref<InstanceType<typeof HomeworkContextBanner> | null>(
	null
)

// C04: the recorded fact is "this material was really shown to this visitor".
// It needs no homework UI context -- the banner is for the way back and the
// live progress, never the right to send the event. The server authorizes:
// the student's own active assignments are updated, a teacher's preview
// touches nothing (no assignment of the teacher as student), and an
// unauthorized viewer is refused there.
const assignmentDisplayed = ref(false)
const openingRecorded = ref(false)

watch(
	() => props.assignmentID,
	() => {
		assignmentDisplayed.value = false
		openingRecorded.value = false
	}
)

const onAssignmentDisplayed = () => {
	assignmentDisplayed.value = true
	maybeRecordAssignmentOpen()
}

const maybeRecordAssignmentOpen = () => {
	if (openingRecorded.value || !assignmentDisplayed.value) return
	openingRecorded.value = true
	call('lms.lms.homework_api.record_assignment_material_opened', {
		assignment: props.assignmentID,
	})
		.then(() => homeworkBanner.value?.refresh())
		.catch(() => {
			// The server remains the authority; a refused event simply means no
			// requirement needed it.
			openingRecorded.value = false
		})
}

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
