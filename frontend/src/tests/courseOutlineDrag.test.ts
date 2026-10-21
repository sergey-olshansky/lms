import { afterEach, describe, expect, it, vi } from 'vitest'
import {
	canDropIntoSection,
	createCourseOutlineDrag,
} from '@/composables/courseOutlineDrag'
import type { OutlineChapter, OutlineLesson } from '@/types'

const section = (
	name: string,
	level = 1,
	sections: OutlineChapter[] = []
): OutlineChapter => ({
	name,
	title: name,
	idx: 1,
	level,
	sections,
	lessons: [],
	is_scorm_package: 0,
})
const lesson: OutlineLesson = {
	name: 'LESSON',
	title: 'Lesson',
	number: '1-1',
	position: 1,
}
const start = (element: unknown) => ({
	item: { __draggable_context: { element } },
})

afterEach(() => vi.restoreAllMocks())

describe('dropping outline items into section titles', () => {
	it('rejects cycles, SCORM and subtrees exceeding four levels', () => {
		const child = section('CHILD', 2)
		const root = section('ROOT', 1, [child])
		const item = { kind: 'section' as const, node: root }
		expect(canDropIntoSection(item, root)).toBe(false)
		expect(canDropIntoSection(item, child)).toBe(false)
		expect(canDropIntoSection(item, section('DEEP', 3))).toBe(false)
		expect(canDropIntoSection(item, section('OTHER', 2))).toBe(true)
		expect(
			canDropIntoSection(item, { ...section('SCORM'), is_scorm_package: 1 })
		).toBe(false)
		expect(
			canDropIntoSection(
				{ kind: 'section', node: { ...root, is_scorm_package: 1 } },
				section('OTHER')
			)
		).toBe(false)
		expect(
			canDropIntoSection({ kind: 'lesson', lesson }, section('DEEP', 4))
		).toBe(true)
	})
	it.each(['root', 'nested', 'lesson'])(
		'normalizes the %s source and submits only once',
		(source) => {
			const onDrop = vi.fn()
			const drag = createCourseOutlineDrag({
				getOutline: () => [],
				onDrop,
				onCancel: vi.fn(),
			})
			const node = section('SOURCE')
			const element =
				source === 'root'
					? node
					: source === 'nested'
					? { kind: 'section', node }
					: { kind: 'lesson', lesson }
			drag.start(start(element), source === 'root' ? null : 'PARENT')
			const target = {
				...section('TARGET'),
				lessons: [lesson],
				sections: [section('CHILD', 2)],
			}
			drag.over(new Event('dragover') as DragEvent, target)
			expect(drag.state.hoveredTarget).toBe('TARGET')
			drag.drop(new Event('drop'), target)
			drag.drop(new Event('drop'), target)
			expect(onDrop).toHaveBeenCalledTimes(1)
			expect(onDrop).toHaveBeenCalledWith({
				item:
					source === 'lesson'
						? { kind: 'lesson', lesson }
						: { kind: 'section', node },
				sourceParent: source === 'root' ? null : 'PARENT',
				targetParent: 'TARGET',
				idx: 2,
			})
			expect(drag.finish({})).toBe(true)
			expect(drag.state.item).toBeNull()
		}
	)
	it.each(['mouse', 'touch'])(
		'resolves %s fallback releases over a collapsed title',
		(input) => {
			const target = section('TARGET')
			const title = document.createElement('div')
			title.dataset.sectionDrop = target.name
			Object.defineProperty(document, 'elementFromPoint', {
				configurable: true,
				value: vi.fn(() => title),
			})
			const onDrop = vi.fn()
			const drag = createCourseOutlineDrag({
				getOutline: () => [target],
				onDrop,
				onCancel: vi.fn(),
			})
			drag.start(start({ kind: 'lesson', lesson }), 'SOURCE')
			const originalEvent =
				input === 'mouse'
					? new MouseEvent('mouseup', { clientX: 10, clientY: 20 })
					: Object.assign(new Event('touchend'), {
							changedTouches: [{ clientX: 10, clientY: 20 }],
					  })
			expect(drag.finish({ originalEvent })).toBe(true)
			expect(onDrop).toHaveBeenCalledWith({
				item: { kind: 'lesson', lesson },
				sourceParent: 'SOURCE',
				targetParent: 'TARGET',
				idx: 0,
			})
		}
	)
	it('restores the outline instead of reordering when a forbidden title is targeted', () => {
		const node = section('SOURCE')
		const title = document.createElement('div')
		title.dataset.sectionDrop = node.name
		Object.defineProperty(document, 'elementFromPoint', {
			configurable: true,
			value: vi.fn(() => title),
		})
		const onCancel = vi.fn()
		const onDrop = vi.fn()
		const drag = createCourseOutlineDrag({
			getOutline: () => [node],
			onDrop,
			onCancel,
		})
		drag.start(start(node), null)
		expect(
			drag.finish({
				originalEvent: new MouseEvent('mouseup', { clientX: 10, clientY: 20 }),
			})
		).toBe(true)
		expect(onCancel).toHaveBeenCalledOnce()
		expect(onDrop).not.toHaveBeenCalled()
	})
})
