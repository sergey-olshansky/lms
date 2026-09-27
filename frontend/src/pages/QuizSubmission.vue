<template>
	<PageHeader :breadcrumbs="breadcrumbs">
		<template #actions>
			<Badge
				v-if="submissionDetails.isDirty"
				:label="__('Not Saved')"
				variant="subtle"
				theme="orange"
			/>
			<ShortcutTooltip :label="__('Save')" combo="Mod+S">
				<HeaderButton
					:label="__('Save')"
					icon="lucide-check"
					variant="solid"
					@click="saveSubmission()"
				/>
			</ShortcutTooltip>
		</template>
	</PageHeader>
	<PageBody>
		<div
			v-if="submissionDetails.doc"
			class="mx-auto w-full pb-5 sm:w-2/3 sm:border-x"
		>
			<div class="space-y-4 border-b pb-5 px-10">
				<div class="grid grid-cols-2 gap-5">
					<FormControl
						v-model="submissionDetails.doc.quiz_title"
						:label="__('Quiz')"
						:disabled="true"
					/>
					<FormControl
						v-model="submissionDetails.doc.member_name"
						:label="__('Member')"
						:disabled="true"
					/>
				</div>

				<div class="grid grid-cols-2 gap-5">
					<FormControl
						v-model="submissionDetails.doc.score"
						:label="__('Score')"
						:disabled="true"
					/>
					<FormControl
						v-model="submissionDetails.doc.percentage"
						:label="__('Percentage')"
						:disabled="true"
					/>
				</div>
			</div>

			<div class="divide-y">
				<div
					v-for="(row, index) in submissionDetails.doc.result"
					:key="row.name"
					class="py-5 px-10 space-y-4"
				>
					<div class="text-ink-gray-9">
						<span class="font-semibold"> {{ __('Question') }}: </span>
						<span class="leading-5" v-html="sanitizeRichHTML(row.question)">
						</span>
					</div>
					<div class="text-ink-gray-9">
						<span class="font-semibold"> {{ __('Answered') }}: </span>
						<span
							class="leading-5"
							v-html="sanitizeRichHTML(row.answer)"
						></span>
					</div>
					<div class="text-ink-gray-9">
						<span class="font-semibold">{{ __('Correct Answer') }}: </span>
						<span class="leading-5" v-if="correctAnswers.loading">…</span>
						<span v-else-if="correctAnswers.error" class="text-ink-red-5">
							{{ __('Could not load correct answers') }}
						</span>
						<span
							v-else
							class="leading-5"
							v-html="sanitizeRichHTML(correctAnswer(row.question_name))"
						></span>
					</div>
					<div class="grid grid-cols-2 gap-5">
						<FormControl v-model="row.marks" :label="__('Marks')" />
						<FormControl
							v-model="row.marks_out_of"
							:label="__('Marks out of')"
							:disabled="true"
						/>
					</div>
				</div>
			</div>
		</div>
	</PageBody>
</template>
<script setup>
import { sanitizeRichHTML } from '@/utils/sanitizeRichHTML'
import {
	createResource,
	createDocumentResource,
	FormControl,
	Button,
	Badge,
	usePageMeta,
	toast,
} from 'frappe-ui'
import { computed, onMounted, inject } from 'vue'
import PageHeader from '@/components/Layouts/PageHeader.vue'
import PageBody from '@/components/Layouts/PageBody.vue'
import HeaderButton from '@/components/HeaderButton.vue'
import ShortcutTooltip from '@/components/ShortcutTooltip.vue'
import {
	useKeyboardShortcuts,
	saveShortcut,
} from '@/composables/useKeyboardShortcuts'
import { useRouter } from 'vue-router'
import { sessionStore } from '@/stores/session'

const { brand } = sessionStore()
const router = useRouter()
const user = inject('$user')

onMounted(() => {
	if (
		!user.data?.is_instructor &&
		!user.data?.is_moderator &&
		!user.data?.is_system_manager
	)
		router.push({ name: 'Courses' })
})

useKeyboardShortcuts({
	ignoreTyping: false,
	shortcuts: [
		{
			...saveShortcut(() => saveSubmission()),
			guard: (e) => !e.target?.classList?.contains('ProseMirror'),
		},
	],
})

const props = defineProps({
	submission: {
		type: String,
		required: true,
	},
})

const submissionDetails = createDocumentResource({
	doctype: 'LMS Quiz Submission',
	name: props.submission,
	auto: true,
})

const correctAnswers = createResource({
	url: 'lms.lms.doctype.lms_quiz.lms_quiz.get_submission_correct_answers',
	makeParams() {
		return { submission: props.submission }
	},
	auto: true,
})

const correctAnswer = (questionName) => {
	const answers = correctAnswers.data?.[questionName] || []
	return answers.length ? answers.join(', ') : '—'
}

// The header renders before the doc lands. It used to be guarded by a `v-if`
// on Breadcrumbs itself, and reading `.quiz` off an undefined doc threw during
// render once the shared header took that guard away.
const breadcrumbs = computed(() => {
	const doc = submissionDetails.doc
	if (!doc) return [{ label: __('Quiz Submissions') }]
	return [
		{
			label: __('Quiz Submissions'),
			route: {
				name: 'QuizSubmissionList',
				params: { quizID: doc.quiz },
			},
		},
		{ label: doc.member_name || doc.name },
	]
})

const saveSubmission = () => {
	submissionDetails.save.submit(
		{},
		{
			onError(err) {
				toast.error(err.messages?.[0] || err)
			},
		},
	)
}

usePageMeta(() => {
	return {
		title: `${submissionDetails.doc?.quiz_title}`,
		icon: brand.favicon,
	}
})
</script>
