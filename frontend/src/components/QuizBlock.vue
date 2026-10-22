<template>
	<Quiz
		v-if="user.data"
		:quizName="quiz"
		@submitted="$emit('submitted')"
	/>
	<div v-else class="border rounded-5 text-center py-20">
		<div>
			{{ __('Please login to access the quiz.') }}
		</div>
		<Button @click="redirectToLogin()" class="mt-2">
			<span>
				{{ __('Login') }}
			</span>
		</Button>
	</div>
</template>
<script setup lang="ts">
import { inject } from 'vue'
import { Button } from 'frappe-ui'
import Quiz from '@/components/Quiz.vue'
import type { SessionUser } from '@/types'
import { redirectToLogin } from '@/utils/loginReturn'

const user = inject<SessionUser>('$user')!

// B11/C5 follow-up: an attempt submitted inside the lesson travels up to the
// page, so the homework banner's live progress refreshes right away -- not on
// the next tab focus.
defineEmits<{ submitted: [] }>()

defineProps<{
	quiz: string
}>()

</script>
