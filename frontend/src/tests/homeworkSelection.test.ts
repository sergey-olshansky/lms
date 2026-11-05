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
	lessonRouteParams,
	matchesSearch,
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

// Task #41: a Folder leaf exactly as the server tree emits it -- assignable
// only while it holds images (Sergey #1527).
const folder = (name: string, image_count: number): TreeNode => ({
	key: `folder:${name}`,
	type: 'folder',
	name,
	title: name,
	image_count,
	assignable: image_count > 0,
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

describe('homework folder selection (task #41)', () => {
	it('collects folders as leaves and skips empty folders', () => {
		const tree = chapter('Media block', [
			folder('Photos', 12),
			folder('Empty', 0),
		])
		expect(collectLeafKeys(tree)).toEqual(['folder:Photos'])
		expect(checkState(tree, new Set())).toBe('unchecked')
	})

	it('makes a folder-only section selectable (the #1445 scenario)', () => {
		const tree = chapter('Photos section', [folder('Photos', 12)])
		const picked = toggleNode(tree, new Set(), true)
		expect(picked.has('folder:Photos')).toBe(true)
		expect(checkState(tree, picked)).toBe('checked')
	})

	it('keeps a section of only empty folders unselectable (spec 3.4.5)', () => {
		const tree = chapter('Empty folders', [folder('A', 0), folder('B', 0)])
		expect(collectLeafKeys(tree)).toEqual([])
	})

	it('treats a mixed section as indeterminate on a partial folder pick', () => {
		const tree = chapter('Mixed', [lesson('Theory'), folder('Photos', 12)])
		expect(checkState(tree, new Set(['lesson:Theory']))).toBe('indeterminate')
		expect(
			checkState(tree, new Set(['lesson:Theory', 'folder:Photos']))
		).toBe('checked')
	})

	it('maps a folder leaf to the Folder source type with its path', () => {
		const nodes = [chapter('Section', [folder('Photos', 12)])]
		const index = flattenWithPaths(nodes)
		const courses = new Map([['course-a', index]])
		const entries = selectionToEntries(new Set(['folder:Photos']), courses)
		expect(entries).toHaveLength(1)
		expect(entries[0]).toMatchObject({
			source_type: 'Folder',
			name: 'Photos',
			course: 'course-a',
			path: 'Section / Photos',
		})
	})

	it('finds folders by title and keeps their section reachable', () => {
		const tree = chapter('Lecture notes', [folder('Screenshots', 12)])
		expect(matchesSearch(tree, 'screenshots')).toBe(true)
		expect(matchesSearch(tree, 'nothing')).toBe(false)
	})
})

describe('lesson route params', () => {
	it('splits a flat number into chapter and lesson', () => {
		expect(lessonRouteParams('2-3')).toEqual({
			chapterNumber: '2',
			lessonNumber: '3',
		})
	})

	it('keeps the whole section path as the chapter for deep numbers', () => {
		// Task #28: section path 1-1-1, first lesson of that section.
		expect(lessonRouteParams('1-1-1-1')).toEqual({
			chapterNumber: '1-1-1',
			lessonNumber: '1',
		})
	})
})
