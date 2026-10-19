<template>
	<article
		class="lesson-video-article not-prose space-y-6"
		contenteditable="false"
	>
		<div ref="videoRoot" class="overflow-hidden rounded-7">
			<iframe
				v-if="playerSource"
				:src="safeUrl(playerSource) || undefined"
				:title="manifest?.lecture_title || 'Видео урока'"
				class="block aspect-video w-full border-0"
				allow="autoplay; encrypted-media; fullscreen; picture-in-picture; screen-wake-lock"
				allowfullscreen
			/>
		</div>
		<template v-if="manifest">
			<header class="space-y-4">
				<h2 class="text-2xl font-semibold text-ink-gray-9">
					{{ manifest.lecture_title }}
				</h2>
				<p class="text-sm text-ink-gray-5">
					{{ lessonTimecode(manifest.source.duration_sec) }} ·
					{{ manifest.sections.length }} разделов · {{ frameCount }} кадров
				</p>
				<p class="leading-7 text-ink-gray-7">{{ manifest.summary }}</p>
				<div class="flex flex-wrap gap-2">
					<span
						v-for="tag in manifest.top_tags"
						:key="tag"
						class="rounded bg-surface-gray-2 px-2 py-1 text-xs text-ink-gray-6"
						>{{ tag }}</span
					>
				</div>
			</header>
			<details class="rounded-6 bg-surface-gray-2 p-4">
				<summary class="cursor-pointer text-sm font-medium">
					Содержание занятия
				</summary>
				<nav class="mt-3 space-y-2" aria-label="Содержание занятия">
					<button
						v-for="section in manifest.sections"
						:key="section.id"
						type="button"
						class="flex w-full gap-3 text-left text-sm text-ink-gray-7 hover:underline"
						@click="scrollToSection(section.id)"
					>
						<span class="shrink-0 tabular-nums">{{
							lessonTimecode(section.start_sec)
						}}</span
						><span>{{ section.title }}</span>
					</button>
				</nav>
			</details>
			<section
				v-for="section in manifest.sections"
				:key="section.id"
				:ref="(node) => rememberSection(section.id, node)"
				class="space-y-4 border-t border-outline-gray-2 pt-6"
			>
				<div class="flex flex-wrap items-start justify-between gap-3">
					<h3 class="min-w-0 flex-1 text-xl font-medium text-ink-gray-9">
						{{ section.id }}. {{ section.title }}
					</h3>
					<button
						type="button"
						class="rounded bg-surface-gray-2 px-2 py-1 text-sm tabular-nums text-ink-gray-7"
						:aria-label="`Открыть видео на ${lessonTimecode(
							section.start_sec
						)}`"
						@click="seek(section.start_sec)"
					>
						▷ {{ lessonTimecode(section.start_sec) }}
					</button>
				</div>
				<div class="flex flex-wrap gap-2 text-xs text-ink-gray-5">
					<span v-for="tag in section.tags" :key="tag">{{ tag }}</span>
				</div>
				<ul
					v-if="section.bullets.length"
					class="list-disc space-y-2 ps-5 leading-7 text-ink-gray-7"
				>
					<li v-for="(bullet, i) in section.bullets" :key="i">{{ bullet }}</li>
				</ul>
				<div
					v-if="section.equations.length"
					class="space-y-2 rounded-6 bg-surface-gray-2 p-4 leading-7 text-ink-gray-8"
				>
					<p
						v-for="(equation, i) in section.equations"
						:key="i"
						class="break-words"
					>
						{{ equation }}
					</p>
				</div>
				<figure
					v-for="frame in section.frames"
					:key="frame.file"
					class="space-y-3"
				>
					<button
						type="button"
						class="block w-full overflow-hidden rounded-7"
						:aria-label="`Увеличить кадр ${lessonTimecode(
							frame.timestamp_sec
						)}`"
						@click="selectedFrame = frame"
					>
						<img
							:src="safeUrl(frame.image_url) || undefined"
							:alt="frame.caption"
							loading="lazy"
							class="block h-auto w-full"
						/>
					</button>
					<figcaption class="flex items-start gap-3 text-sm text-ink-gray-5">
						<button
							type="button"
							class="shrink-0 rounded bg-surface-gray-2 px-2 py-1 tabular-nums text-ink-gray-7"
							@click="seek(frame.timestamp_sec)"
						>
							▷ {{ lessonTimecode(frame.timestamp_sec) }}</button
						><span>{{ frame.caption }}</span>
					</figcaption>
					<details v-if="frame.board_text" class="text-sm text-ink-gray-5">
						<summary class="cursor-pointer">Текст с доски</summary>
						<p class="mt-2 whitespace-pre-wrap rounded-6 bg-surface-gray-2 p-3">
							{{ frame.board_text }}
						</p>
					</details>
				</figure>
			</section>
		</template>
		<Dialog
			:open="Boolean(selectedFrame)"
			title="Кадр из видео"
			size="4xl"
			@update:open="(open: boolean) => { if (!open) selectedFrame = null }"
		>
			<template #default
				><div v-if="selectedFrame" class="space-y-3">
					<img
						:src="safeUrl(selectedFrame.image_url) || undefined"
						:alt="selectedFrame.caption"
						class="h-auto w-full rounded-6"
					/>
					<p class="text-sm text-ink-gray-6">{{ selectedFrame.caption }}</p>
					<Button
						:label="`Открыть видео на ${lessonTimecode(
							selectedFrame.timestamp_sec
						)}`"
						@click="seekFromImage"
					/></div
			></template>
		</Dialog>
	</article>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Button, Dialog } from 'frappe-ui'
import type { LessonFrame, LessonManifest } from '@/utils/lessonArchive'
import {
	lessonTimecode,
	videoAtTime,
	vkVideoSource,
} from '@/utils/lessonArchive'
import { safeUrl } from '@/utils/safeUrl'

const props = defineProps<{ videoSource: string; manifest?: LessonManifest }>()
const videoRoot = ref<HTMLElement | null>(null)
const playerSource = ref(vkVideoSource(props.videoSource))
const selectedFrame = ref<LessonFrame | null>(null)
const sectionNodes = new Map<number, HTMLElement>()
const frameCount = computed(
	() => props.manifest?.sections.reduce((n, s) => n + s.frames.length, 0) || 0
)
watch(
	() => props.videoSource,
	(source) => {
		playerSource.value = vkVideoSource(source)
	}
)
function rememberSection(id: number, node: unknown) {
	if (node instanceof HTMLElement) sectionNodes.set(id, node)
	else sectionNodes.delete(id)
}
function scrollToSection(id: number) {
	sectionNodes.get(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function seekFromImage() {
	if (selectedFrame.value) seek(selectedFrame.value.timestamp_sec)
	selectedFrame.value = null
}
function seek(seconds: number) {
	playerSource.value = videoAtTime(props.videoSource, seconds)
	videoRoot.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>
<style scoped>
.lesson-video-article section,
.lesson-video-article > div:first-child {
	scroll-margin-top: 1.5rem;
}
</style>
