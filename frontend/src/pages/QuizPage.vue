<template>
	<PageHeader v-if="!fromLesson" :breadcrumbs="breadcrumbs" />
	<!-- Task #35 (R10): a standalone quiz reached through ?hw= carries the
	homework context: the way back, live progress, and the card's start. A
	?submission= link (B11) opens one specific attempt's report -- the proof a
	homework requirement was earned -- right on this page. -->
	<HomeworkContextBanner
		v-if="homeworkContext"
		ref="homeworkBanner"
		:assignment-id="homeworkContext"
		start
		data-testid="homework-back-banner"
	/>
	<div
		class="md:w-7/12 md:mx-auto mx-4 py-10"
		:class="{ 'pt-4 md:w-full': fromLesson }"
	>
		<Quiz
			:quizName="quizID"
			:report-submission="reportSubmission"
			@submitted="onQuizSubmitted"
		/>
	</div>
</template>
<script setup>
import Quiz from '@/components/Quiz.vue'
import { createResource, usePageMeta } from 'frappe-ui'
import PageHeader from '@/components/Layouts/pages/PageHeader.vue'
import HomeworkContextBanner from '@/components/HomeworkContextBanner.vue'
import { computed, inject, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { sessionStore } from '../stores/session'

const { brand } = sessionStore()
const user = inject('$user')
const route = useRoute()
const router = useRouter()
const fromLesson = ref(false)

const homeworkContext = computed(() =>
	typeof route.query.hw === 'string' ? route.query.hw : ''
)

// B11: the addressed attempt whose report should open on arrival (the
// homework checklist's proof link). Empty for a plain visit.
const reportSubmission = computed(() =>
	typeof route.query.submission === 'string' ? route.query.submission : ''
)

const homeworkBanner = ref(null)

// B11: the banner's progress updates the moment the attempt is in, not on the
// next tab switch.
const onQuizSubmitted = () => {
	homeworkBanner.value?.refresh()
}

onMounted(() => {
	if (!user.data) {
		router.push({ name: 'Courses' })
	}

	if (new URLSearchParams(window.location.search).get('fromLesson')) {
		fromLesson.value = true
	}
})

const props = defineProps({
	quizID: {
		type: String,
		required: true,
	},
})

const title = createResource({
	url: 'frappe.client.get_value',
	params: {
		doctype: 'LMS Quiz',
		fieldname: 'title',
		filters: {
			name: props.quizID,
		},
	},
	auto: true,
})

const breadcrumbs = computed(() => {
	return [
		{
			label: __('Quizzes'),
			route: { name: 'Quizzes' },
		},
		{
			label: title.data?.title,
			route: { name: 'QuizForm', params: { quizID: props.quizID } },
		},
		{ label: __('Test Quiz') },
	]
})

usePageMeta(() => {
	return {
		title: `${title.data?.title}`,
		icon: brand.favicon,
	}
})
</script>
