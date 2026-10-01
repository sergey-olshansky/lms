<template>
	<div
		v-if="quiz.loading && !quiz.data"
		class="flex items-center justify-center py-12"
	>
		<LoadingIndicator class="size-4 text-ink-gray-5" />
	</div>
	<div v-else-if="quiz.data">
		<div
			class="bg-surface-blue-2 text-ink-blue-6 space-y-2 p-3 mb-4 rounded-lg leading-5"
		>
			<div class="font-medium">
				{{
					__(
						'Please read the following instructions carefully before starting the quiz',
					)
				}}
			</div>
			<ol class="list-decimal list-inside space-y-2">
				<li v-if="inVideo">
					{{ __('You will have to complete the quiz to continue the video') }}
				</li>
				<li>
					{{
						__(
							'Your answers are saved automatically on this device. You can return to this quiz later.',
						)
					}}
				</li>
				<li>
					{{
						__('This quiz consists of {0} questions.').format(questions.length)
					}}
				</li>
				<li v-if="quiz.data?.duration">
					{{
						__(
							'Please ensure that you complete all the questions in {0} minutes.',
						).format(quiz.data.duration)
					}}
				</li>
				<li v-if="quiz.data?.duration">
					{{
						__(
							'If you fail to do so, the quiz will be automatically submitted when the timer ends.',
						)
					}}
				</li>
				<li v-if="quiz.data.passing_percentage">
					{{
						__(
							'You will have to get {0}% correct answers in order to pass the quiz.',
						).format(quiz.data.passing_percentage)
					}}
				</li>
				<li v-if="quiz.data.max_attempts">
					{{
						__('You can attempt this quiz {0}.').format(
							quiz.data.max_attempts == 1
								? '1 time'
								: `${quiz.data.max_attempts} times`,
						)
					}}
				</li>
				<li v-if="quiz.data.enable_negative_marking">
					{{
						__(
							'If you answer incorrectly, {0} {1} will be deducted from your score for each incorrect answer.',
						).format(
							quiz.data.marks_to_cut,
							quiz.data.marks_to_cut == 1 ? 'mark' : 'marks',
						)
					}}
				</li>
			</ol>
		</div>

		<div v-if="quiz.data.duration" class="flex flex-col gap-x-1 my-4 px-2">
			<div class="mb-2">
				<span class="text-ink-gray-9"> {{ __('Time') }}: </span>
				<span class="font-semibold text-ink-gray-9">
					{{ formatTimer(timer) }}
				</span>
			</div>
			<ProgressBar :progress="timerProgress" />
		</div>

		<div v-if="activeQuestion == 0">
			<div class="border text-center p-6 sm:p-20 rounded-md">
				<div class="text-lg-semibold text-ink-gray-9">
					{{ quiz.data.title }}
				</div>
				<template v-if="questions.length">
					<div class="flex items-center justify-center gap-x-2 mt-4">
						<Button
							v-if="
								!quiz.data.max_attempts ||
								attempts.data?.length < quiz.data.max_attempts
							"
							variant="solid"
							class="text-p-base-medium"
							@click="startQuiz"
						>
							<span>
								{{ inVideo ? __('Start the Quiz') : __('Start') }}
							</span>
						</Button>
						<Button
							v-if="inVideo"
							class="text-p-base-medium"
							@click="props.backToVideo()"
						>
							{{ __('Resume Video') }}
						</Button>
					</div>
					<div
						v-if="
							quiz.data.max_attempts &&
							attempts.data?.length >= quiz.data.max_attempts
						"
						class="leading-5 text-ink-gray-7"
					>
						{{
							__(
								'You have already exceeded the maximum number of attempts allowed for this quiz.',
							)
						}}
					</div>
				</template>
				<div v-else class="mt-4 leading-5 text-ink-gray-7">
					{{ __('This quiz has no questions available yet.') }}
					<div v-if="inVideo" class="flex justify-center mt-3">
						<Button @click="props.backToVideo()">
							{{ __('Resume Video') }}
						</Button>
					</div>
				</div>
			</div>
		</div>
		<div v-else-if="!quizSubmission.data">
			<div v-for="(question, qtidx) in questions" :key="question.name">
				<div
					v-if="qtidx == activeQuestion - 1 && questionDetails.data"
					class="border rounded-lg p-5"
				>
					<div class="flex flex-wrap items-baseline justify-between gap-x-4">
						<div class="min-w-0 text-sm text-ink-gray-5">
							{{ __('Question {0}').format(activeQuestion) }} -
							{{ getInstructions(questionDetails.data) }}
						</div>
						<div class="shrink-0 text-ink-gray-9 text-sm-semibold">
							{{ question.marks }}
							{{ question.marks == 1 ? __('Mark') : __('Marks') }}
						</div>
					</div>
					<div
						class="text-ink-gray-9 font-semibold mt-2 leading-5 break-words [&_img]:h-auto [&_img]:max-w-full"
						v-html="sanitizeRichHTML(questionDetails.data.question)"
					></div>
					<div
						v-if="questionDetails.data.type == 'Choices'"
						v-for="index in MAX_OPTIONS"
						:key="index"
					>
						<label
							v-if="questionDetails.data[`option_${index}`]"
							class="flex items-center bg-surface-gray-3 rounded-md p-3 mt-4 w-full min-w-0 cursor-pointer focus:border-blue-600"
						>
							<input
								v-if="!showAnswers.length && !questionDetails.data.multiple"
								type="radio"
								:name="encodeURIComponent(questionDetails.data.question)"
								class="w-3.5 h-3.5 shrink-0 text-ink-gray-9 focus:ring-outline-elevation-2"
								@change="markAnswer(index)"
								:checked="selectedOptions[index - 1]"
							/>

							<input
								v-else-if="!showAnswers.length && questionDetails.data.multiple"
								type="checkbox"
								:name="encodeURIComponent(questionDetails.data.question)"
								class="w-3.5 h-3.5 shrink-0 text-ink-gray-9 rounded-sm focus:ring-outline-elevation-2"
								@change="markAnswer(index)"
								:checked="selectedOptions[index - 1]"
							/>
							<div
								v-else-if="quiz.data.show_answers"
								v-for="(answer, idx) in showAnswers"
								:key="idx"
								class="shrink-0"
							>
								<div v-if="index - 1 == idx">
									<span
										v-if="answer == 1"
										class="lucide-check-circle w-4 h-4 text-ink-green-5"
									/>
									<span
										v-else-if="answer == 2"
										class="lucide-minus-circle w-4 h-4 text-ink-green-5"
									/>
									<span
										v-else-if="answer == 0"
										class="lucide-x-circle w-4 h-4 text-ink-red-6"
									/>
									<span v-else class="lucide-minus-circle w-4 h-4" />
								</div>
							</div>
							<span
								class="ms-2 min-w-0 flex-1 break-words text-ink-gray-9 [&_img]:h-auto [&_img]:max-w-full"
								v-html="
									sanitizeRichHTML(questionDetails.data[`option_${index}`])
								"
							>
							</span>
						</label>
						<div
							v-if="questionDetails.data[`explanation_${index}`]"
							class="mt-2 break-words text-xs text-ink-gray-7"
							v-show="showAnswers.length"
						>
							{{ questionDetails.data[`explanation_${index}`] }}
						</div>
					</div>
					<div v-else-if="questionDetails.data.type == 'User Input'">
						<FormControl
							v-model="possibleAnswer"
							type="textarea"
							:disabled="showAnswers.length ? true : false"
							class="my-2"
						/>
						<div v-if="showAnswers.length">
							<Badge v-if="showAnswers[0]" :label="__('Correct')" theme="green">
								<template #prefix>
									<span
										class="lucide-check-circle w-4 h-4 text-ink-green-5 me-1"
									/>
								</template>
							</Badge>
							<Badge v-else theme="red" :label="__('Incorrect')">
								<template #prefix>
									<span class="lucide-x-circle w-4 h-4 text-ink-red-6 me-1" />
								</template>
							</Badge>
						</div>
					</div>
					<div v-else>
						<RichTextEditor
							class="mt-4"
							:content="possibleAnswer"
							@change="(val) => (possibleAnswer = val)"
							:editable="true"
							:fixedMenu="true"
							editorClass="prose-sm max-w-none border-b border-x border-outline-elevation-2 bg-surface-gray-2 rounded-b-md py-1 px-2 min-h-[7rem]"
						/>
					</div>
					<div class="flex flex-wrap items-center justify-between gap-3 mt-8">
						<Checkbox
							v-if="!quiz.data.show_answers"
							:label="__('Mark for review')"
							:model-value="reviewQuestions.includes(activeQuestion) ? 1 : 0"
							@change="markForReview($event, activeQuestion)"
						/>
						<div
							v-if="!quiz.data.show_answers"
							class="flex flex-wrap items-center gap-2"
						>
							<Button
								:label="__('Previous question')"
								@click="switchQuestion(activeQuestion - 1)"
								:disabled="activeQuestion == 1"
								class="rounded-full"
							>
								<template #icon>
									<span class="lucide-chevron-left size-4" />
								</template>
							</Button>
							<component
								:is="item === '...' ? 'span' : 'button'"
								v-for="(item, pidx) in paginationWindow"
								:key="pidx"
								:type="item === '...' ? null : 'button'"
								class="w-6 h-6 rounded-full flex items-center justify-center text-sm"
								:class="{
									'cursor-pointer': item !== '...',
									'bg-surface-gray-4 border border-outline-gray-7 font-medium':
										activeQuestion == item,
									'text-ink-gray-5': item === '...',
									'bg-surface-blue-3 text-ink-base':
										attemptedQuestions.includes(item) && activeQuestion != item,
									'bg-surface-gray-3 text-ink-gray-6':
										activeQuestion != item &&
										item !== '...' &&
										!attemptedQuestions.includes(item),
								}"
								@click="item !== '...' && switchQuestion(item)"
							>
								{{ item }}
							</component>
						</div>
						<Button
							v-if="
								quiz.data.show_answers &&
								!showAnswers.length &&
								questionDetails.data.type != 'Open Ended'
							"
							class="ms-auto"
							@click="checkAnswer()"
						>
							<span>
								{{ __('Check') }}
							</span>
						</Button>
						<Button
							v-else-if="
								activeQuestion != questions.length && quiz.data.show_answers
							"
							@click="nextQuestion()"
							class="ms-auto"
						>
							<span>
								{{ __('Next') }}
							</span>
						</Button>
						<div v-else class="ms-auto flex items-center gap-2">
							<Button
								:label="__('Next question')"
								@click="switchQuestion(activeQuestion + 1)"
								:disabled="activeQuestion == questions.length"
							>
								<template #icon>
									<span class="lucide-chevron-right size-4" />
								</template>
							</Button>
							<Button variant="solid" @click="handleSubmitClick()">
								<span>{{ __('Finish Quiz') }}</span>
							</Button>
						</div>
					</div>
				</div>
			</div>
			<div v-if="reviewQuestions.length" class="border rounded-lg p-4 mt-4">
				<div class="font-semibold">
					{{ __('Questions marked for review') }}
				</div>
				<div class="flex flex-wrap items-center gap-2 mt-2">
					<button
						v-for="index in reviewQuestions"
						:key="index"
						type="button"
						@click="switchQuestion(index)"
						class="w-6 h-6 rounded-full flex items-center justify-center text-sm cursor-pointer bg-surface-gray-3"
					>
						{{ index }}
					</button>
				</div>
			</div>
		</div>
		<div v-else class="border rounded-lg p-6 sm:p-20 space-y-2 text-center">
			<div class="text-lg-semibold text-ink-gray-9">
				{{ __('Quiz Summary') }}
			</div>
			<div
				v-if="quizSubmission.data.is_open_ended"
				class="leading-5 text-ink-gray-7"
			>
				{{
					__(
						"Your submission has been successfully saved. The instructor will review and grade it shortly, and you'll be notified of your final result.",
					)
				}}
			</div>
			<div v-else class="text-ink-gray-7">
				{{
					__(
						'You got {0}% correct answers with a score of {1} out of {2}',
					).format(
						Math.ceil(quizSubmission.data.percentage),
						quizSubmission.data.score,
						quizSubmission.data.score_out_of,
					)
				}}
			</div>
			<div class="flex items-center justify-center gap-x-2">
				<Button
					@click="resetQuiz()"
					v-if="
						!quiz.data.max_attempts ||
						attempts?.data.length < quiz.data.max_attempts
					"
				>
					<span>
						{{ __('Try Again') }}
					</span>
				</Button>
				<Button v-if="inVideo" @click="props.backToVideo()">
					{{ __('Resume Video') }}
				</Button>
			</div>
		</div>
		<div
			v-if="
				quiz.data.show_submission_history &&
				attempts?.data &&
				attempts.data.length > 0
			"
			class="mt-10"
		>
			<ResponsiveListView
				:columns="getSubmissionColumns()"
				:rows="attempts?.data"
				row-key="name"
				title-key="creation"
				:options="getSubmissionOptions()"
			/>
		</div>
	</div>
	<Dialog
		v-model:open="showSubmissionConfirmation"
		:title="__('Are you sure you want to submit the quiz?')"
		:actions="[
			{
				size: 'sm',
				label: __('Submit'),
				variant: 'solid',
				onClick() {
					submitQuiz()
					showSubmissionConfirmation = false
				},
			},
		]"
	>
		<template #default>
			<div class="border border-outline-elevation-2 rounded-lg text-base">
				<div class="divide-y divide-outline-elevation-2">
					<div
						class="grid grid-cols-2 divide-x rtl:divide-x-reverse divide-outline-elevation-2"
					>
						<div class="p-2">
							{{ __('Total Questions') }}
						</div>
						<div class="p-2">
							{{ questions.length }}
						</div>
					</div>
					<div
						class="grid grid-cols-2 divide-x rtl:divide-x-reverse divide-outline-elevation-2"
					>
						<div class="p-2">
							{{ __('Attempted Questions') }}
						</div>
						<div class="p-2">
							{{ attemptedQuestions.length }}
						</div>
					</div>
					<div
						class="grid grid-cols-2 divide-x rtl:divide-x-reverse divide-outline-elevation-2"
					>
						<div class="p-2">
							{{ __('Unattempted Questions') }}
						</div>
						<div class="p-2">
							{{ questions.length - attemptedQuestions.length }}
						</div>
					</div>
				</div>
			</div>
		</template>
	</Dialog>
</template>
<script setup>
import { sanitizeRichHTML } from '@/utils/sanitizeRichHTML'
import {
	Badge,
	Button,
	call,
	Checkbox,
	createResource,
	Dialog,
	LoadingIndicator,
	FormControl,
	toast,
} from 'frappe-ui'
import {
	computed,
	inject,
	onMounted,
	onUnmounted,
	reactive,
	ref,
	watch,
} from 'vue'
import { timeAgo } from '@/utils/format'
import ProgressBar from '@/components/ProgressBar.vue'
import ResponsiveListView from '@/components/ResponsiveListView.vue'
import RichTextEditor from '@/components/RichTextEditor.vue'

const user = inject('$user')
const activeQuestion = ref(0)
const currentQuestion = ref('')
const MAX_OPTIONS = 10
const selectedOptions = ref(Array(MAX_OPTIONS).fill(0))
const showAnswers = reactive([])
const questions = ref([])
const attemptedQuestions = ref([])
const reviewQuestions = ref([])
const showSubmissionConfirmation = ref(false)
const possibleAnswer = ref(null)
const timer = ref(0)
const savedAnswers = ref([])
const deadline = ref(null)
let restoringAnswer = false
let timerInterval = null
let submitTimeout = null

const props = defineProps({
	quizName: {
		type: String,
		required: true,
	},
	inVideo: {
		type: Boolean,
		default: false,
	},
	backToVideo: {
		type: Function,
		default: () => {},
	},
})

onMounted(() => {
	window.addEventListener('pagehide', handlePageHide)
})

onUnmounted(() => {
	window.removeEventListener('pagehide', handlePageHide)
	handlePageHide()
	stopTimer()
})

const handlePageHide = () => {
	if (activeQuestion.value > 0 && !quizSubmission.data) saveCurrentAnswer()
}

// Quiz doc + every question's content in one round trip. The lesson-side
// quiz used to fetch the quiz, then fire one get_question_details per
// question as the learner advanced. Pulling them all up front lets the
// activeQuestion watcher read from a local map instead of round-tripping.
const questionsByName = ref({})
const quiz = createResource({
	url: 'lms.lms.utils.get_quiz_with_questions',
	makeParams() {
		return { quiz: props.quizName }
	},
	// Keep this resource instance-local: its callbacks update component-local
	// question and timer state on every mount.
	auto: true,
	transform(data) {
		const quizDoc = data?.quiz || {}
		quizDoc.duration = parseInt(quizDoc.duration)
		questionsByName.value = data?.questions_by_name || {}
		return quizDoc
	},
	onSuccess() {
		populateQuestions()
		setupTimer()
		restoreDraft()
		if (quiz.data?.max_attempts) attempts.reload()
	},
})

const populateQuestions = () => {
	const data = quiz.data
	const rawQuestions = Array.isArray(data?.questions) ? data.questions : []
	// Drop rows whose linked question no longer resolves (e.g. the question
	// was deleted while still referenced by the quiz). Keeping a phantom row
	// lets questionDetails.data go null mid-quiz and crash getAnswers and the
	// unload handlers, which, since the quiz now mounts inline in the lesson,
	// blanks the whole lesson view.
	const resolvable = rawQuestions.filter(
		(row) => row?.question && questionsByName.value[row.question],
	)
	if (data?.shuffle_questions) {
		let next = shuffleArray([...resolvable])
		if (data.limit_questions_to) {
			next = next.slice(0, data.limit_questions_to)
		}
		questions.value = next
	} else {
		questions.value = resolvable
	}
}

const setupTimer = () => {
	// resetQuiz() reaches here from the quizName watcher, which fires before the
	// new quiz has loaded — and on the very first navigation quiz.data is still
	// null. Throwing here would abort the watcher before it can reload.
	timer.value = quiz.data?.duration ? quiz.data.duration * 60 : 0
}

const stopTimer = () => {
	clearInterval(timerInterval)
	timerInterval = null
	// submitQuiz() defers createSubmission() by 500ms. Left pending, it fires against an unmounted
	// or already-switched component and marks progress on the wrong lesson.
	clearTimeout(submitTimeout)
	submitTimeout = null
}

const startTimer = () => {
	// The same instance can start a quiz more than once — a retake, or the
	// component reused for another quiz. Without this, each start leaves the
	// previous interval running and every one of them submits on expiry.
	stopTimer()
	const updateTimer = () => {
		timer.value = Math.max(0, Math.ceil((deadline.value - Date.now()) / 1000))
		if (timer.value === 0) {
			stopTimer()
			submitQuiz()
		}
	}
	updateTimer()
	if (timer.value === 0) return
	timerInterval = setInterval(() => {
		updateTimer()
	}, 1000)
}

const formatTimer = (seconds) => {
	const hrs = Math.floor(seconds / 3600)
		.toString()
		.padStart(2, '0')
	const mins = Math.floor((seconds % 3600) / 60)
		.toString()
		.padStart(2, '0')
	const secs = (seconds % 60).toString().padStart(2, '0')
	return hrs != '00' ? `${hrs}:${mins}:${secs}` : `${mins}:${secs}`
}

const timerProgress = computed(() => {
	return (timer.value / (quiz.data.duration * 60)) * 100
})

const shuffleArray = (array) => {
	for (let i = array.length - 1; i > 0; i--) {
		const j = Math.floor(Math.random() * (i + 1))
		;[array[i], array[j]] = [array[j], array[i]]
	}
	return array
}

const attempts = createResource({
	url: 'frappe.client.get_list',
	makeParams(values) {
		return {
			doctype: 'LMS Quiz Submission',
			filters: {
				member: user.data?.name,
				quiz: quiz.data?.name,
			},
			fields: [
				'name',
				'creation',
				'score',
				'score_out_of',
				'percentage',
				'passing_percentage',
			],
			order_by: 'creation desc',
		}
	},
	transform(data) {
		data.forEach((submission, index) => {
			submission.creation = timeAgo(submission.creation)
			submission.idx = index + 1
		})
	},
})

const quizSubmission = createResource({
	url: 'lms.lms.doctype.lms_quiz.lms_quiz.submit_quiz',
	makeParams(values) {
		return {
			quiz: quiz.data.name,
			results: JSON.stringify(savedAnswers.value),
		}
	},
})

// Mirror the previous createResource shape ({ data: ... }) so existing
// template refs (questionDetails.data.option_X, etc.) keep working. We
// just pull the row from the pre-fetched map instead of an API call.
const questionDetails = reactive({ data: null })

watch(activeQuestion, (value) => {
	if (value <= 0) return
	// Read from the local `questions` array. That's the shuffled / limited
	// copy populateQuestions built. `quiz.data.questions` is the raw,
	// un-shuffled list and can be a different length when limit_questions_to
	// is set.
	const row = questions.value[value - 1]
	if (!row?.question) return
	currentQuestion.value = row.question
	questionDetails.data = questionsByName.value[currentQuestion.value] || null
	loadSavedAnswers()
	saveDraft()
})

const switchQuestion = (questionNumber) => {
	if (questionNumber < 1 || questionNumber > questions.value.length) return
	saveCurrentAnswer()
	clearQuestionAnswer()
	activeQuestion.value = questionNumber
}

const loadSavedAnswers = () => {
	clearQuestionAnswer()
	restoringAnswer = true
	let quizData = savedAnswers.value
	if (quizData) {
		let localQuestion = quizData.find(
			(q) => q.question_name == currentQuestion.value,
		)
		if (localQuestion) {
			let localAnswers = localQuestion.answer
			if (localAnswers.length) {
				if (questionDetails.data.type == 'Choices') {
					localAnswers.forEach((answer) => {
						for (let i = 1; i <= MAX_OPTIONS; i++) {
							if (questionDetails.data[`option_${i}`] == answer) {
								selectedOptions.value[i - 1] = 1
							}
						}
					})
				} else {
					possibleAnswer.value = localAnswers[0]
				}
			}
		}
	}
	restoringAnswer = false
}

watch(
	() => props.quizName,
	(newName) => {
		if (newName) {
			// The lesson-level quiz is not keyed at its mount site, so moving
			// between two lessons that both carry a quiz reuses this instance
			// instead of remounting it. Reloading alone leaves the previous
			// quiz's answers, flagged questions and submission on screen.
			if (activeQuestion.value > 0 && !quizSubmission.data) saveCurrentAnswer()
			stopTimer()
			resetQuiz()
			// Only on a genuine quiz switch, never from resetQuiz() itself — that is
			// also the "Try Again" handler, and nulling attempts there leaves the
			// start card with neither a Start button nor the exceeded-attempts
			// message, both of which read attempts.data?.length.
			attempts.reset()
			// A submission already in flight is NOT aborted: the POST has reached the
			// server and the attempt is spent either way, so cancelling the client
			// would only hide the result. It is ignored instead, by submittedQuiz.
			quiz.reload()
		}
	},
)

const startQuiz = () => {
	if (quizSubmission.data) quizSubmission.reset()
	savedAnswers.value = []
	attemptedQuestions.value = []
	reviewQuestions.value = []
	deadline.value = quiz.data.duration
		? Date.now() + quiz.data.duration * 60 * 1000
		: null
	activeQuestion.value = 1
	saveDraft()
	if (quiz.data.duration) startTimer()
}

const markAnswer = (index) => {
	if (!questionDetails.data.multiple)
		selectedOptions.value.splice(
			0,
			selectedOptions.value.length,
			...Array(MAX_OPTIONS).fill(0),
		)
	selectedOptions.value[index - 1] = selectedOptions.value[index - 1] ? 0 : 1
	saveCurrentAnswer()
}

watch(
	possibleAnswer,
	() => {
		if (!restoringAnswer && activeQuestion.value > 0) saveCurrentAnswer()
	},
	{ flush: 'sync' },
)

const getAnswers = () => {
	let answers = []
	if (!questionDetails.data) return answers
	const type = questionDetails.data.type
	if (type == 'Choices') {
		selectedOptions.value.forEach((value, index) => {
			if (selectedOptions.value[index])
				answers.push(questionDetails.data[`option_${index + 1}`])
		})
	} else {
		answers.push(possibleAnswer.value)
	}

	return answers
}

const checkAnswer = () => {
	let answers = getAnswers()
	if (!answers.length) {
		toast.warning(__('Please select an option'))
		return
	}

	createResource({
		url: 'lms.lms.doctype.lms_quiz.lms_quiz.check_answer',
		params: {
			quiz: quiz.data.name,
			question: currentQuestion.value,
			question_type: questionDetails.data.type,
			answers: JSON.stringify(answers),
		},
		auto: true,
		onSuccess(data) {
			let type = questionDetails.data.type
			if (type == 'Choices') {
				selectedOptions.value.forEach((option, index) => {
					if (option) {
						showAnswers[index] = option && data[index]
					} else if (data[index] == 2) {
						showAnswers[index] = 2
					} else {
						showAnswers[index] = undefined
					}
				})
			} else {
				showAnswers.push(data)
			}
			saveCurrentAnswer()
			if (!quiz.data.show_answers) {
				resetQuestion()
			}
		},
	})
}

const draftKey = () =>
	`lms-quiz-draft:${user.data?.name || 'Guest'}:${quiz.data?.name}`

const saveDraft = () => {
	if (!quiz.data || activeQuestion.value < 1 || quizSubmission.data) return
	try {
		localStorage.setItem(
			draftKey(),
			JSON.stringify({
				version: 1,
				questions: questions.value.map((q) => q.question),
				answers: savedAnswers.value,
				activeQuestion: currentQuestion.value,
				reviewQuestions: reviewQuestions.value.map(
					(index) => questions.value[index - 1]?.question,
				),
				deadline: deadline.value,
			}),
		)
	} catch {
		toast.error(__('Could not save quiz progress on this device.'))
	}
}

const saveCurrentAnswer = () => {
	if (!quiz.data || !currentQuestion.value || activeQuestion.value < 1) return
	const answers = getAnswers()
	const hasAnswer = answers.some(
		(answer) => typeof answer === 'string' && answer.trim() !== '',
	)
	savedAnswers.value = savedAnswers.value.filter(
		(q) => q.question_name !== currentQuestion.value,
	)
	if (hasAnswer) {
		savedAnswers.value.push({
			question_name: currentQuestion.value,
			answer: answers,
		})
	}
	attemptedQuestions.value = questions.value.flatMap((q, index) =>
		savedAnswers.value.some((answer) => answer.question_name === q.question)
			? [index + 1]
			: [],
	)
	saveDraft()
}

const restoreDraft = () => {
	if (!quiz.data) return
	let draft
	try {
		draft = JSON.parse(localStorage.getItem(draftKey()))
	} catch {
		return
	}
	if (draft?.version !== 1 || !Array.isArray(draft.questions)) return
	const byName = new Map(questions.value.map((row) => [row.question, row]))
	if (
		draft.questions.length === questions.value.length &&
		draft.questions.every((name) => byName.has(name))
	) {
		questions.value = draft.questions.map((name) => byName.get(name))
	}
	const validNames = new Set(questions.value.map((q) => q.question))
	savedAnswers.value = Array.isArray(draft.answers)
		? draft.answers.filter(
				(answer) =>
					validNames.has(answer?.question_name) &&
					Array.isArray(answer.answer) &&
					answer.answer.every((value) => typeof value === 'string'),
			)
		: []
	attemptedQuestions.value = questions.value.flatMap((q, index) =>
		savedAnswers.value.some((answer) => answer.question_name === q.question)
			? [index + 1]
			: [],
	)
	reviewQuestions.value = Array.isArray(draft.reviewQuestions)
		? draft.reviewQuestions.flatMap((name) => {
				const index = questions.value.findIndex((q) => q.question === name)
				return index < 0 ? [] : [index + 1]
			})
		: []
	deadline.value =
		quiz.data.duration && Number.isFinite(draft.deadline)
			? draft.deadline
			: null
	const index = questions.value.findIndex(
		(q) => q.question === draft.activeQuestion,
	)
	activeQuestion.value = index < 0 ? 1 : index + 1
	if (quiz.data.duration) {
		if (!deadline.value)
			deadline.value = Date.now() + quiz.data.duration * 60 * 1000
		startTimer()
	}
}

const nextQuestion = () => {
	if (!quiz.data.show_answers) return
	if (questionDetails.data?.type == 'Open Ended') saveCurrentAnswer()
	resetQuestion()
}

const resetQuestion = () => {
	// Compare against the local `questions` array. `quiz.data.questions` is
	// the raw list and can be longer than what populateQuestions trimmed via
	// limit_questions_to.
	if (activeQuestion.value == questions.value.length) return
	clearQuestionAnswer()
	activeQuestion.value = activeQuestion.value + 1
	showAnswers.length = 0
}

const clearQuestionAnswer = () => {
	restoringAnswer = true
	selectedOptions.value.splice(
		0,
		selectedOptions.value.length,
		...Array(MAX_OPTIONS).fill(0),
	)
	possibleAnswer.value = null
	restoringAnswer = false
}

const submitQuiz = () => {
	if (submitTimeout || quizSubmission.loading || quizSubmission.data) return
	if (!quiz.data.show_answers) {
		saveCurrentAnswer()
		submitTimeout = setTimeout(() => {
			submitTimeout = null
			createSubmission()
		}, 500)
		return
	}
	createSubmission()
}

const createSubmission = () => {
	// Which quiz this submission belongs to. The component is reused across
	// lessons, so by the time the response lands props.quizName may have moved
	// on — and markLessonProgress() reads window.location.pathname at that
	// moment, which would credit whatever lesson is open by then.
	const submittedQuiz = props.quizName
	const submittedDraftKey = draftKey()
	quizSubmission.submit(
		{},
		{
			onSuccess(data) {
				localStorage.removeItem(submittedDraftKey)
				if (props.quizName !== submittedQuiz) return
				markLessonProgress()
				if (quiz.data && quiz.data.max_attempts) attempts.reload()
				stopTimer()
			},
			onError(err) {
				const errorTitle = err?.message || ''
				if (errorTitle.includes('MaximumAttemptsExceededError')) {
					const errorMessage = err.messages?.[0] || err
					toast.error(__(errorMessage))
					setTimeout(() => {
						window.location.reload()
					}, 3000)
				}
			},
		},
	)
}

const resetQuiz = () => {
	stopTimer()
	activeQuestion.value = 0
	clearQuestionAnswer()
	currentQuestion.value = ''
	questionDetails.data = null
	showAnswers.length = 0
	attemptedQuestions.value = []
	reviewQuestions.value = []
	savedAnswers.value = []
	deadline.value = null
	quizSubmission.reset()
	populateQuestions()
	setupTimer()
}

const getInstructions = (question) => {
	if (question.type == 'Choices')
		if (question.multiple) return __('Choose all answers that apply')
		else return __('Choose one answer')
	else return __('Type your answer')
}

const markLessonProgress = () => {
	let pathname = window.location.pathname.split('/')
	if (!pathname.includes('courses'))
		pathname = window.parent.location.pathname.split('/')
	if (pathname[2] != 'courses') return
	let lessonIndex = pathname.pop().split('-')

	if (lessonIndex.length == 2) {
		call('lms.lms.api.mark_lesson_progress', {
			course: pathname[3],
			chapter_number: lessonIndex[0],
			lesson_number: lessonIndex[1],
		})
	}
}

const handleSubmitClick = () => {
	if (!quiz.data.show_answers) {
		recordCurrentAttempt()
		showSubmissionConfirmation.value = true
	} else {
		submitQuiz()
	}
}

const recordCurrentAttempt = () => {
	saveCurrentAnswer()
}

const paginationWindow = computed(() => {
	const total = questions.value.length
	const current = activeQuestion.value
	const pages = []
	const size = 5

	let start = Math.floor((current - 1) / size) * size + 1
	let end = Math.min(start + size - 1, total)

	if (start > 1) {
		pages.push('...')
	}

	for (let i = start; i <= end; i++) {
		pages.push(i)
	}

	if (end < total) {
		pages.push('...')
	}

	return pages
})

const markForReview = (event, questionNumber) => {
	if (event.target.checked) {
		if (!reviewQuestions.value.includes(questionNumber)) {
			reviewQuestions.value.push(questionNumber)
		}
	} else {
		reviewQuestions.value = reviewQuestions.value.filter(
			(num) => num !== questionNumber,
		)
	}
	saveDraft()
}

const getSubmissionColumns = () => {
	return [
		{
			label: __('No.'),
			key: 'idx',
			width: 1,
		},
		{
			label: __('Date'),
			key: 'creation',
			width: 2,
		},
		{
			label: __('Score'),
			key: 'score',
			align: 'left',
			width: 1,
		},
		{
			label: __('Score out of'),
			key: 'score_out_of',
			align: 'left',
			width: 1,
		},
		{
			label: __('Percentage'),
			key: 'percentage',
			align: 'left',
			width: 1,
		},
	]
}

const getSubmissionOptions = () => {
	return {
		selectable: false,
		showTooltip: false,
		emptyState: { title: __('No Quiz submissions found') },
	}
}
</script>
