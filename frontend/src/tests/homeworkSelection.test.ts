/**
 * The pure selection maths of the homework material picker (task #35, spec 3.4):
 * tri-state containers, subtree toggles, empty-container exclusion, readable
 * paths, dedup of a parent-and-child double pick (A07) and the progress line.
 * These run without a Frappe site by design -- the picker UI layer stays thin.
 */
import { describe, expect, it } from 'vitest'
import {
	checkState,
	collectLeafKeys,
	flattenWithPaths,
	progressLine,
	selectionToEntries,
	toggleNode,
	type TreeNode,
} from '@/utils/homeworkSelection'

const lesson = (name: string, title = name): TreeNode => ({
	key: `lesson:${name}`,
	type: 'lesson',
	name,
	title,
	quizzes: [],
	assignable: true,
})

const chapter = (
	name: string,
	children: TreeNode[],
	assignable = true
): TreeNode => ({
	key: `chapter:${name}`,
	type: 'chapter',
	name,
	title: name,
	children,
	assignable,
})

describe('homework selection', () => {
	it('collects only assignable leaves from a subtree', () => {
		const tree = chapter('Block 1', [lesson('Atom'), lesson('Isotopes')])
		expect(collectLeafKeys(tree)).toEqual(['lesson:Atom', 'lesson:Isotopes'])
	})

	it('treats an empty chapter as no work at all', () => {
		const empty = chapter('Empty', [], false)
		expect(collectLeafKeys(empty)).toEqual([])
		expect(checkState(empty, new Set())).toBe('unchecked')
	})

	it('reports checked, unchecked and indeterminate containers', () => {
		const tree = chapter('Block', [lesson('A'), lesson('B')])
		expect(checkState(tree, new Set())).toBe('unchecked')
		expect(checkState(tree, new Set(['lesson:A']))).toBe('indeterminate')
		expect(checkState(tree, new Set(['lesson:A', 'lesson:B']))).toBe('checked')
	})

	it('toggling a container selects and clears its whole subtree', () => {
		const tree = chapter('Block', [lesson('A'), lesson('B')])
		const picked = toggleNode(tree, new Set(), true)
		expect(picked.has('lesson:A')).toBe(true)
		expect(picked.has('lesson:B')).toBe(true)
		const cleared = toggleNode(tree, picked, false)
		expect(cleared.size).toBe(0)
	})

	it('builds readable paths with the chapter for grouping', () => {
		const index = flattenWithPaths([chapter('Block 1', [lesson('Atom')])])
		const row = index.get('lesson:Atom')
		expect(row?.path).toBe('Block 1 / Atom')
		expect(row?.chapter).toBe('Block 1')
	})

	it('keeps one entry for a parent-and-child double pick (A07)', () => {
		const nodes = [chapter('Block', [lesson('Atom')]), lesson('Atom')]
		const index = flattenWithPaths(nodes)
		const courses = new Map([['chemistry', index]])
		// Both the chapter and the lesson row resolve to the same leaf key.
		const picked = toggleNode(nodes[0], new Set(), true)
		const entries = selectionToEntries(picked, courses)
		expect(entries).toHaveLength(1)
		expect(entries[0].source_type).toBe('Lesson')
		expect(entries[0].name).toBe('Atom')
	})

	it('formats the progress line with quiz counts when present', () => {
		expect(
			progressLine({
				completed_requirements: 3,
				total_requirements: 5,
				quizzes_completed: 1,
				quizzes_total: 2,
			})
		).toBe('3 / 5 · 1 / 2')
		expect(
			progressLine({
				completed_requirements: 1,
				total_requirements: 4,
				quizzes_completed: 0,
				quizzes_total: 0,
			})
		).toBe('1 / 4')
	})
})
