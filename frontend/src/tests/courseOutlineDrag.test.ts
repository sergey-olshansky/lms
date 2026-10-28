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

afterEach(() => { vi.restoreAllMocks(); document.body.replaceChildren() })

describe('outline insertion position', () => {
	function listFixture(parent = 'TARGET') {
		const wrapper = document.createElement('div')
		wrapper.dataset.sectionDrop = parent
		const list = document.createElement('div')
		list.dataset.outlineList = parent
		wrapper.append(list)
		document.body.append(wrapper)
		const rows = ['lesson-A', 'section-B', 'lesson-C'].map((key, index) => {
			const row = document.createElement('div')
			row.dataset.outlineKey = key
			vi.spyOn(row, 'getBoundingClientRect').mockReturnValue({ top: 100 + index * 100, height: 60 } as DOMRect)
			list.append(row)
			return row
		})
		return { wrapper, list, rows }
	}

	it('inserts before the hovered lesson instead of appending', () => {
		const target = { ...section('TARGET'), lessons: [lesson, { ...lesson, name: 'C' }], sections: [section('B', 2)] }
		const { rows } = listFixture()
		Object.defineProperty(document, 'elementFromPoint', { configurable: true, value: vi.fn(() => rows[1]) })
		const onDrop = vi.fn()
		const drag = createCourseOutlineDrag({ getOutline: () => [target], onDrop, onCancel: vi.fn() })
		drag.start(start(section('SOURCE')), null)
		drag.drop(new MouseEvent('drop', { clientX: 50, clientY: 201 }), target)
		expect(onDrop).toHaveBeenCalledWith(expect.objectContaining({ targetParent: 'TARGET', idx: 1 }))
	})

	it('uses release coordinates when dragend.target still points to the source', () => {
		const target = section('TARGET')
		const { rows } = listFixture()
		Object.defineProperty(document, 'elementFromPoint', { configurable: true, value: vi.fn(() => rows[1]) })
		const source = document.createElement('div')
		source.dataset.sectionDrop = 'SOURCE'
		const onDrop = vi.fn()
		const drag = createCourseOutlineDrag({ getOutline: () => [target], onDrop, onCancel: vi.fn() })
		drag.start(start(section('SOURCE')), null)
		source.addEventListener('dragend', (originalEvent) => drag.finish({ originalEvent }))
		source.dispatchEvent(new MouseEvent('dragend', { clientX: 50, clientY: 201 }))
		expect(onDrop).toHaveBeenCalledWith(expect.objectContaining({ targetParent: 'TARGET', idx: 1 }))
	})

	it('calculates same-parent slots after removing the dragged item', () => {
		const target = section('TARGET')
		const { rows } = listFixture()
		Object.defineProperty(document, 'elementFromPoint', { configurable: true, value: vi.fn(() => rows[2]) })
		const onDrop = vi.fn()
		const drag = createCourseOutlineDrag({ getOutline: () => [target], onDrop, onCancel: vi.fn() })
		drag.start(start({ kind: 'lesson', lesson: { ...lesson, name: 'A' } }), 'TARGET')
		drag.drop(new MouseEvent('drop', { clientX: 50, clientY: 301 }), target)
		expect(onDrop).toHaveBeenCalledWith(expect.objectContaining({ targetParent: 'TARGET', idx: 1 }))
	})

	it('treats the top edge of a section header as a sibling insertion', () => {
		const target = section('TARGET')
		const root = document.createElement('div')
		root.dataset.outlineRootDrop = ''
		const list = document.createElement('div')
		list.dataset.outlineList = ''
		const row = document.createElement('div')
		row.dataset.outlineKey = 'section-TARGET'
		const header = document.createElement('div')
		header.className = 'outline-section-header'
		header.dataset.sectionDrop = 'TARGET'
		row.append(header); list.append(row); root.append(list); document.body.append(root)
		vi.spyOn(header, 'getBoundingClientRect').mockReturnValue({ top: 100, bottom: 160, height: 60 } as DOMRect)
		vi.spyOn(row, 'getBoundingClientRect').mockReturnValue({ top: 100, bottom: 160, height: 60 } as DOMRect)
		Object.defineProperty(document, 'elementFromPoint', { configurable: true, value: vi.fn(() => header) })
		const onDrop = vi.fn()
		const drag = createCourseOutlineDrag({ getOutline: () => [target], onDrop, onCancel: vi.fn() })
		drag.start(start(section('SOURCE')), null)
		drag.finish({ originalEvent: new MouseEvent('mouseup', { clientX: 50, clientY: 102 }) })
		expect(onDrop).toHaveBeenCalledWith(expect.objectContaining({ targetParent: null, idx: 0 }))
	})
})

describe('dropping outline items into section titles', () => {
	it('keeps a title target stationary so sibling sorting cannot replace it before drop', () => {
		const target = section('TARGET')
		const title = document.createElement('div')
		title.dataset.sectionDrop = target.name
		const elementFromPoint = vi.fn((): Element | null => title)
		Object.defineProperty(document, 'elementFromPoint', {
			configurable: true,
			value: elementFromPoint,
		})
		const drag = createCourseOutlineDrag({
			getOutline: () => [target],
			onDrop: vi.fn(),
			onCancel: vi.fn(),
		})
		drag.start(start(section('SOURCE')), null)
		expect(
			drag.move({}, new MouseEvent('dragover', { clientX: 20, clientY: 30 }))
		).toBe(false)
		expect(drag.state.hoveredTarget).toBe(target.name)
		elementFromPoint.mockReturnValue(null)
		expect(
			drag.move({}, new MouseEvent('dragover', { clientX: 0, clientY: 0 }))
		).toBe(true)
		expect(drag.state.hoveredTarget).toBeNull()
	})
	it('rejects cycles, SCORM and subtrees exceeding two levels', () => {
		const child = section('CHILD', 2)
		const root = section('ROOT', 1, [child])
		const item = { kind: 'section' as const, node: root }
		expect(canDropIntoSection(item, root)).toBe(false)
		expect(canDropIntoSection(item, child)).toBe(false)
		expect(canDropIntoSection(item, section('DEEP', 2))).toBe(false)
		expect(
			canDropIntoSection(
				{ kind: 'section', node: child },
				section('OTHER', 1)
			)
		).toBe(true)
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
			canDropIntoSection({ kind: 'lesson', lesson }, section('DEEP', 2))
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

	it('moves a nested section to the course root when dropped on empty root space', () => {
		const node = section('SOURCE', 2)
		const root = document.createElement('div')
		root.dataset.outlineRootDrop = ''
		Object.defineProperty(document, 'elementFromPoint', {
			configurable: true,
			value: vi.fn(() => root),
		})
		const onDrop = vi.fn()
		const drag = createCourseOutlineDrag({
			getOutline: () => [section('ROOT')],
			onDrop,
			onCancel: vi.fn(),
		})
		drag.start(start({ kind: 'section', node }), 'PARENT')

		expect(
			drag.finish({
				originalEvent: new MouseEvent('mouseup', {
					clientX: 30,
					clientY: 40,
				}),
				to: { dataset: {} },
			})
		).toBe(true)
		expect(onDrop).toHaveBeenCalledWith({
			item: { kind: 'section', node },
			sourceParent: 'PARENT',
			targetParent: null,
			idx: 1,
		})
	})

	it('cancels a section transfer between parent lists when no section target is hit', () => {
		Object.defineProperty(document, 'elementFromPoint', {
			configurable: true,
			value: vi.fn(() => null),
		})
		const onCancel = vi.fn()
		const drag = createCourseOutlineDrag({
			getOutline: () => [],
			onDrop: vi.fn(),
			onCancel,
		})
		drag.start(start({ kind: 'section', node: section('SOURCE', 2) }), 'PARENT-1')
		const destination = document.createElement('div')
		destination.dataset.chapter = 'PARENT-2'

		expect(
			drag.move(
				{ to: { el: destination } },
				new MouseEvent('dragover', { clientX: 10, clientY: 20 })
			)
		).toBe(false)
		expect(
			drag.finish({
				to: { dataset: { chapter: 'PARENT-2' } },
				originalEvent: new MouseEvent('mouseup'),
			})
		).toBe(true)
		expect(onCancel).toHaveBeenCalledOnce()
	})
})
