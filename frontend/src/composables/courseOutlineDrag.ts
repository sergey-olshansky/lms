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
	targetParent: string | null
	idx: number
}

type DropLocation = { parent: OutlineChapter | null; idx: number; before: string | null }

export function canDropIntoSection(item: OutlineDragItem, target: OutlineChapter): boolean {
	if (target.is_scorm_package) return false
	if (item.kind === 'lesson') return true
	if (item.node.is_scorm_package) return false
	if (flattenSections([item.node]).some((section) => section.name === target.name)) return false
	const height = (node: OutlineChapter): number => 1 + Math.max(0, ...(node.sections ?? []).map(height))
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
		hoveredBefore: null as string | null,
		handled: false,
	})

	function start(event: OutlineDragEvent, parent: string | null) {
		const child = event.item.__draggable_context.element as OutlineDragItem | OutlineChapter
		state.item = 'kind' in child ? child : { kind: 'section', node: child }
		state.sourceParent = parent
		state.handled = false
		clearHover()
	}

	function pointer(event?: Event) {
		const original = event as (MouseEvent & Partial<TouchEvent>) | undefined
		return original?.touches?.[0] ?? original?.changedTouches?.[0] ?? original
	}

	function hitAtPoint(event?: Event): Element | null {
		const point = pointer(event)
		if (point && Number.isFinite(point.clientX)) {
			const hit = document.elementFromPoint?.(point.clientX, point.clientY)
			if (hit) return hit
		}
		return event?.target instanceof Element ? event.target : null
	}

	function insertionSlot(event: Event | undefined, parent: OutlineChapter | null, hit: Element | null) {
		const fallback = parent
			? (parent.lessons?.length ?? 0) + (parent.sections?.length ?? 0)
			: options.getOutline()?.length ?? 0
		const point = pointer(event)
		const lists = Array.from(document.querySelectorAll<HTMLElement>('[data-outline-list]'))
			.filter((element) => element.dataset.outlineList === (parent?.name ?? ''))
		const list = lists.find((element) => hit && element.contains(hit)) ?? lists[0]
		if (!list || !point || !Number.isFinite(point.clientY)) return { idx: fallback, before: null }
		const sourceKey = state.item?.kind === 'section'
			? `section-${state.item.node.name}`
			: state.item?.kind === 'lesson' ? `lesson-${state.item.lesson.name}` : null
		// Indexes refer to the destination after removing the dragged row.
		const rows = Array.from(list.children).filter((element): element is HTMLElement =>
			element instanceof HTMLElement && !!element.dataset.outlineKey && element.dataset.outlineKey !== sourceKey)
		const idx = rows.findIndex((row) => {
			const bounds = (row.querySelector<HTMLElement>('.outline-section-header') ?? row).getBoundingClientRect()
			return point.clientY < bounds.top + bounds.height / 2
		})
		return idx < 0 ? { idx: rows.length, before: null } : { idx, before: rows[idx].dataset.outlineKey! }
	}

	function location(event?: Event, fallbackTarget?: OutlineChapter): DropLocation | undefined {
		const hit = hitAtPoint(event)
		const sections = flattenSections(options.getOutline())
		const targetName = hit?.closest<HTMLElement>('[data-section-drop]')?.dataset.sectionDrop
		let parent = sections.find((section) => section.name === targetName) ?? fallbackTarget
		const point = pointer(event)
		const header = hit?.closest<HTMLElement>('.outline-section-header')
		const row = header?.closest<HTMLElement>('[data-outline-key]')
		const list = row?.parentElement
		if (header && list?.hasAttribute('data-outline-list') && point && Number.isFinite(point.clientY)) {
			const bounds = header.getBoundingClientRect()
			const edge = Math.min(12, bounds.height / 4)
			// The header edges insert beside the section; its centre nests inside.
			if (edge > 0 && (point.clientY < bounds.top + edge || point.clientY > bounds.bottom - edge)) {
				parent = sections.find((section) => section.name === list.dataset.outlineList)
				if (!list.dataset.outlineList) return { parent: null, ...insertionSlot(event, null, hit) }
			}
		}
		if (parent) return { parent, ...insertionSlot(event, parent, hit) }
		if (hit?.closest('[data-outline-root-drop]')) return { parent: null, ...insertionSlot(event, null, hit) }
	}

	function allowed(target: DropLocation) {
		if (!state.item) return false
		return target.parent ? canDropIntoSection(state.item, target.parent)
			: state.item.kind === 'section' && !state.item.node.is_scorm_package
	}

	function clearHover() {
		state.hoveredTarget = null
		state.hoveredBefore = null
	}

	function hover(event: DragEvent, target: DropLocation | undefined) {
		if (!target || !allowed(target)) return
		event.preventDefault()
		if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
		state.hoveredTarget = target.parent?.name ?? null
		state.hoveredBefore = target.before
	}

	function over(event: DragEvent, target: OutlineChapter) {
		const destination = location(event, target)
		if (destination?.parent?.name === target.name) hover(event, destination)
	}

	function leave(target: OutlineChapter) {
		if (state.hoveredTarget === target.name) clearHover()
	}

	function overRoot(event: DragEvent) {
		const destination = location(event)
		if (destination && !destination.parent) hover(event, destination)
	}

	function commit(event: Event | undefined, destination: DropLocation) {
		if (state.handled || !state.item || !allowed(destination)) return
		event?.preventDefault()
		state.handled = true
		options.onDrop({ item: state.item, sourceParent: state.sourceParent,
			targetParent: destination.parent?.name ?? null, idx: destination.idx })
	}

	function drop(event: Event, target: OutlineChapter) {
		const destination = location(event, target)
		if (destination?.parent?.name === target.name) commit(event, destination)
	}

	function dropRoot(event: Event) {
		const destination = location(event)
		if (destination && !destination.parent) commit(event, destination)
	}

	function move(event: { to?: { el?: HTMLElement } }, originalEvent: Event): boolean {
		const destination = location(originalEvent)
		if (destination && state.item) {
			if (allowed(destination)) {
				state.hoveredTarget = destination.parent?.name ?? null
				state.hoveredBefore = destination.before
			} else clearHover()
			// Keep both differently shaped Vue lists intact. The guarded drop
			// commits the move once, including exact insertion position.
			return false
		}
		clearHover()
		return !(state.item?.kind === 'section' && state.sourceParent !== (event.to?.el?.dataset.chapter ?? null))
	}

	function finish(event: { originalEvent?: Event; to?: { dataset?: { chapter?: string } } }): boolean {
		if (!state.handled && state.item) {
			// dragend.target can remain the source; the release coordinates decide.
			const destination = location(event.originalEvent)
			if (destination) {
				if (allowed(destination)) commit(event.originalEvent, destination)
				else { state.handled = true; options.onCancel() }
			} else if (state.item.kind === 'section' && state.sourceParent !== (event.to?.dataset?.chapter ?? null)) {
				state.handled = true
				options.onCancel()
			}
		}
		const handled = state.handled
		state.item = null
		state.handled = false
		clearHover()
		return handled
	}

	return { state, start, over, leave, drop, overRoot, dropRoot, move, finish }
}

export const courseOutlineDragKey: InjectionKey<ReturnType<typeof createCourseOutlineDrag>> = Symbol('courseOutlineDrag')
