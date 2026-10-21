import { reactive, type InjectionKey } from 'vue'
import { flattenSections } from '@/utils/courseOutline'
import type { OutlineChapter, OutlineLesson } from '@/types'

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
	return (target.level ?? 1) + height(item.node) <= 4
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

	function finish(event: { originalEvent?: Event }): boolean {
		// Sortable's touch fallback has no native drop event. Resolve the release
		// point against the same title targets used by mouse/HTML drag-and-drop.
		const original = event.originalEvent as
			| (MouseEvent & Partial<TouchEvent>)
			| undefined
		const point = original?.changedTouches?.[0] ?? original
		if (
			!state.handled &&
			state.item &&
			point &&
			Number.isFinite(point.clientX)
		) {
			const element = document.elementFromPoint(point.clientX, point.clientY)
			const name = element?.closest<HTMLElement>('[data-section-drop]')?.dataset
				.sectionDrop
			const target = flattenSections(options.getOutline()).find(
				(section) => section.name === name
			)
			if (target) {
				if (canDropIntoSection(state.item, target)) drop(original!, target)
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

	return { state, start, over, drop, finish }
}

export const courseOutlineDragKey: InjectionKey<
	ReturnType<typeof createCourseOutlineDrag>
> = Symbol('courseOutlineDrag')
