import { reactive, type InjectionKey } from 'vue'
import { flattenSections } from '@/utils/courseOutline'
import type { OutlineChapter, OutlineLesson } from '@/types'

const MAX_SECTION_DEPTH = 2

export type OutlineDragItem =
	| { kind: 'section'; node: OutlineChapter }
	| { kind: 'lesson'; lesson: OutlineLesson }

export interface OutlineDragEvent {
	item: { __draggable_context: { element: unknown } }
	originalEvent?: Event
}

export interface OutlineDrop {
	item: OutlineDragItem
	sourceParent: string | null
	targetParent: string
	idx: number
}

export function canDropIntoSection(
	item: OutlineDragItem,
	target: OutlineChapter
): boolean {
	if (target.is_scorm_package) return false
	if (item.kind === 'lesson') return true
	if (item.node.is_scorm_package) return false
	if (
		flattenSections([item.node]).some((section) => section.name === target.name)
	)
		return false
	const height = (node: OutlineChapter): number =>
		1 + Math.max(0, ...(node.sections ?? []).map(height))
	return (target.level ?? 1) + height(item.node) <= MAX_SECTION_DEPTH
}

export function createCourseOutlineDrag(options: {
	getOutline: () => OutlineChapter[] | null
	onDrop: (drop: OutlineDrop) => void
	onCancel: () => void
}) {
	const state = reactive({
		item: null as OutlineDragItem | null,
		sourceParent: null as string | null,
		hoveredTarget: null as string | null,
		handled: false,
	})

	function start(event: OutlineDragEvent, parent: string | null) {
		const child = event.item.__draggable_context.element as
			| OutlineDragItem
			| OutlineChapter
		state.item = 'kind' in child ? child : { kind: 'section', node: child }
		state.sourceParent = parent
		state.hoveredTarget = null
		state.handled = false
	}

	function over(event: DragEvent, target: OutlineChapter) {
		if (!state.item || !canDropIntoSection(state.item, target)) return
		event.preventDefault()
		if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
		state.hoveredTarget = target.name
	}

	function drop(event: Event, target: OutlineChapter) {
		if (state.handled || !state.item || !canDropIntoSection(state.item, target))
			return
		event.preventDefault()
		state.handled = true
		options.onDrop({
			item: state.item,
			sourceParent: state.sourceParent,
			targetParent: target.name,
			idx: (target.lessons?.length ?? 0) + (target.sections?.length ?? 0),
		})
	}

	function sectionAtPoint(event?: Event): OutlineChapter | undefined {
		const original = event as (MouseEvent & Partial<TouchEvent>) | undefined
		const point =
			original?.touches?.[0] ?? original?.changedTouches?.[0] ?? original
		if (!point || !Number.isFinite(point.clientX)) return
		const element = document.elementFromPoint(point.clientX, point.clientY)
		const name = element?.closest<HTMLElement>('[data-section-drop]')?.dataset
			.sectionDrop
		return flattenSections(options.getOutline()).find(
			(section) => section.name === name
		)
	}

	function move(_event: unknown, originalEvent: Event): boolean {
		const target = sectionAtPoint(originalEvent)
		if (!target || !state.item) {
			state.hoveredTarget = null
			return true
		}
		state.hoveredTarget = canDropIntoSection(state.item, target)
			? target.name
			: null
		// Keep a title target in place. Sortable otherwise swaps the source into
		// that row before mouseup, so the eventual drop lands on the source itself.
		return false
	}

	function finish(event: { originalEvent?: Event }): boolean {
		// Sortable's touch fallback has no native drop event. Resolve the release
		// point against the same title targets used by mouse/HTML drag-and-drop.
		if (!state.handled && state.item) {
			const target = sectionAtPoint(event.originalEvent)
			if (target) {
				if (canDropIntoSection(state.item, target))
					drop(event.originalEvent!, target)
				else {
					state.handled = true
					options.onCancel()
				}
			}
		}
		const handled = state.handled
		state.item = null
		state.hoveredTarget = null
		state.handled = false
		return handled
	}

	return { state, start, over, drop, move, finish }
}

export const courseOutlineDragKey: InjectionKey<
	ReturnType<typeof createCourseOutlineDrag>
> = Symbol('courseOutlineDrag')
