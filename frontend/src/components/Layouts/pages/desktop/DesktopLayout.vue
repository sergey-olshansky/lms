<template>
	<div class="flex h-dvh w-screen">
		<a
			href="#main-content"
			@click.prevent="skipToContent('main-content')"
			class="sr-only focus:not-sr-only focus:absolute focus:start-4 focus:top-4 focus:z-50 focus:rounded-4 focus:bg-surface-base focus:px-4 focus:py-2 focus:text-ink-gray-9 focus:shadow-md focus:focus-ring"
		>
			{{ __('Skip to main content') }}
		</a>
		<div
			class="h-full border-e bg-surface-sidebar lms-sidebar-edge"
			aria-hidden="false"
		>
			<AppSidebar />
			<span ref="divider" class="lms-ai-divider" aria-hidden="true">
				<span class="lms-ai-stream-third" />
			</span>
		</div>
		<main
			id="main-content"
			tabindex="-1"
			class="flex-1 min-w-0 flex flex-col h-full overflow-auto bg-surface-base focus:outline-none"
		>
			<slot />
		</main>
	</div>
</template>
<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import '../../../../../../lms/public/js/mytutor-divider-motion.js'
import { skipToContent } from '@/utils/a11y'
import AppSidebar from '@/components/Sidebar/AppSidebar.vue'
const divider = ref(null)
let stopMotion
onMounted(() => {
	stopMotion = window.lmsDividerMotion.start(divider.value)
})
onBeforeUnmount(() => stopMotion?.())
</script>
