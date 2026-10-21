<template>
	<Tooltip :text="label" side="bottom">
		<button
			v-bind="$attrs"
			type="button"
			class="inline-flex size-8 shrink-0 items-center justify-center rounded-4 hover:bg-surface-gray-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 disabled:cursor-not-allowed disabled:opacity-40"
			:class="danger ? 'text-ink-red-5' : 'text-ink-gray-7'"
			:aria-label="label"
			:aria-disabled="disabled ? 'true' : undefined"
			:aria-busy="busy || undefined"
			:disabled="disabled"
			@click="emit('click', $event)"
		>
			<slot />
		</button>
	</Tooltip>
</template>

<script setup lang="ts">
import { Tooltip } from 'frappe-ui'
defineOptions({ inheritAttrs: false })
defineProps<{
	label: string
	disabled?: boolean
	busy?: boolean
	danger?: boolean
}>()
const emit = defineEmits<{ click: [MouseEvent] }>()
</script>
