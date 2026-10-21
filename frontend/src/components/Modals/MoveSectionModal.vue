<template>
	<Dialog
		v-model:open="show"
		:title="__('Move to…')"
		size="md"
		:actions="[
			{
				label: __('Move'),
				variant: 'solid',
				loading: saving,
				disabled: selectedTarget === null,
				onClick: () => submit(),
			},
		]"
	>
		<template #default>
			<div class="space-y-3" data-testid="move-section-dialog">
				<div
					class="text-sm text-ink-gray-6 whitespace-normal break-words"
					:title="sectionTitle"
				>
					{{ sectionTitle }}
				</div>
				<div class="text-sm text-ink-gray-5">
					{{ __('Current branch depth: {0}').format(subtreeHeight) }}
				</div>
				<FormControl
					v-model="search"
					:placeholder="__('Search')"
					autocomplete="off"
					type="text"
				/>
				<div class="max-h-72 overflow-y-auto rounded-4 border divide-y">
					<button
						v-if="matches(courseLabel)"
						type="button"
						class="flex w-full items-start justify-between gap-2 px-3 py-2 text-start text-sm hover:bg-surface-gray-2"
						:class="selectedTarget === '' ? 'bg-surface-gray-2' : ''"
						:data-testid="`move-target-root`"
						@click="selectTarget('')"
					>
						<span
							class="min-w-0 flex-1 whitespace-normal break-words text-base-medium"
							:title="courseLabel"
							>{{ courseLabel }}</span
						>
					</button>
					<template
						v-for="candidate in filteredCandidates"
						:key="candidate.name"
					>
						<Tooltip
							:text="candidate.blockedReason ?? __('Move to…')"
							side="bottom"
							class="w-full"
						>
							<button
								type="button"
								class="flex w-full items-start justify-between gap-2 px-3 py-2 text-start text-sm"
								:style="{
									paddingInlineStart: `${Math.min(
										candidate.level * 8 + 12,
										36
									)}px`,
								}"
								:class="[
									candidate.blockedReason
										? 'cursor-not-allowed opacity-50'
										: 'hover:bg-surface-gray-2',
									selectedTarget === candidate.name ? 'bg-surface-gray-2' : '',
								]"
								:disabled="!!candidate.blockedReason"
								:aria-disabled="candidate.blockedReason ? 'true' : undefined"
								:data-testid="`move-target-${candidate.name}`"
								@click="selectTarget(candidate.name)"
							>
								<span
									class="min-w-0 flex-1 whitespace-normal break-words leading-5"
									:title="candidate.title"
									>{{ candidate.title }}</span
								>
								<span class="flex shrink-0 items-center gap-2 pt-0.5">
									<span class="text-ink-gray-5">
										{{ __('Level {0}').format(candidate.level) }}
									</span>
								</span>
							</button>
						</Tooltip>
						<span v-if="candidate.blockedReason" class="sr-only">
							{{ candidate.blockedReason }}
						</span>
					</template>
				</div>
			</div>
		</template>
	</Dialog>
</template>

<script setup lang="ts">
import { createResource, Dialog, FormControl, toast, Tooltip } from 'frappe-ui'
import { computed, ref } from 'vue'
import type { FrappeResourceError } from 'frappe-ui'
import { resourceErrorMessage } from '@/utils/resource'
import type { OutlineChapter, Resource } from '@/types'
import { flattenSections } from '@/utils/courseOutline'

// Authoring maximum, mirrored from the server contract in SectionRow.
const MAX_SECTION_DEPTH = 4

interface MoveCandidate {
	name: string
	title: string
	level: number
	blockedReason: string | null
}

/**
 * Reparents a section via an explicit target picker (design §4.5): a compact
 * tree of the course with a search field. Candidates that would push the
 * moved subtree past 4 levels — and SCORM sections, which are leaves — are
 * disabled with the reason.
 */
const props = defineProps<{
	courseName: string
	courseTitle?: string
	outline: Resource<OutlineChapter[] | null>
}>()

const show = ref(false)
const saving = ref(false)
const search = ref('')
const selectedTarget = ref<string | null>(null)
const movedSection = ref<OutlineChapter | null>(null)

const sectionTitle = computed<string>(() => movedSection.value?.title ?? '')

const courseLabel = computed<string>(
	() => props.courseTitle || props.courseName
)

// Height of the moved subtree counting itself: a leaf section is 1.
const subtreeHeight = computed<number>(() => {
	const node = movedSection.value
	if (!node) return 1
	const heightOf = (section: OutlineChapter): number =>
		1 + Math.max(0, ...(section.sections ?? []).map(heightOf))
	return heightOf(node)
})

const candidates = computed<MoveCandidate[]>(() => {
	if (!movedSection.value) return []
	const forbidden = new Set(
		flattenSections([movedSection.value]).map((s) => s.name)
	)
	const list: MoveCandidate[] = []
	for (const section of flattenSections(props.outline.data ?? [])) {
		if (forbidden.has(section.name)) continue
		if (section.is_scorm_package) continue
		const level = section.level ?? 1
		let blockedReason: string | null = null
		if (level + subtreeHeight.value > MAX_SECTION_DEPTH) {
			blockedReason = __('Maximum depth reached — 4 section levels')
		}
		list.push({
			name: section.name,
			title: section.title,
			level,
			blockedReason,
		})
	}
	return list
})

const filteredCandidates = computed<MoveCandidate[]>(() => {
	const query = search.value.trim().toLowerCase()
	if (!query) return candidates.value
	return candidates.value.filter((candidate) =>
		candidate.title.toLowerCase().includes(query)
	)
})

function matches(label: string): boolean {
	const query = search.value.trim().toLowerCase()
	return !query || label.toLowerCase().includes(query)
}

const moveSection = createResource({
	url: 'lms.lms.api.move_section',
	makeParams(values: { section: string; target_parent: string | null }) {
		return values
	},
	onSuccess() {
		saving.value = false
		toast.success(__('Section moved'))
		show.value = false
		props.outline.reload()
	},
	onError(err: FrappeResourceError) {
		saving.value = false
		toast.error(resourceErrorMessage(err, __('Error')))
	},
})

function open(section: OutlineChapter) {
	movedSection.value = section
	search.value = ''
	selectedTarget.value = null
	show.value = true
}

function selectTarget(target: string) {
	selectedTarget.value = target
}

function submit() {
	if (!movedSection.value || selectedTarget.value === null || saving.value)
		return
	saving.value = true
	moveSection.submit({
		section: movedSection.value.name,
		target_parent: selectedTarget.value || null,
	})
}

defineExpose({ open })
</script>
