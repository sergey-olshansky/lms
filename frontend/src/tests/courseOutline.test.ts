import { describe, expect, it } from 'vitest'
import {
	findLessonNameByNumber,
	flattenLessons,
	flattenSections,
	forEachLesson,
	lessonAncestors,
	lessonExistsByNumber,
	lessonExistsByName,
	isSelectionStale,
	isLessonInChapter,
	parseLessonNumber,
} from '@/utils/courseOutline'

// Two lessons in one chapter. `number` is positional ("chapterIdx-lessonIdx")
// and shifts when references resequence on delete; `name` is the stable docname.
const outline = [
	{
		name: 'CH-1',
		title: 'Chapter 1',
		idx: 1,
		lessons: [
			{ name: 'LESSON-A', title: 'Intro', number: '1-1' },
			{ name: 'LESSON-B', title: 'Deep dive', number: '1-2' },
		],
	},
]

describe('findLessonNameByNumber', () => {
	it('resolves the stable docname from a positional number', () => {
		expect(findLessonNameByNumber(outline, '1-2')).toBe('LESSON-B')
	})

	it('returns null for an unknown number or empty outline', () => {
		expect(findLessonNameByNumber(outline, '9-9')).toBeNull()
		expect(findLessonNameByNumber(null, '1-1')).toBeNull()
	})
})

describe('lessonExistsByNumber / lessonExistsByName', () => {
	it('detects presence by number and by name', () => {
		expect(lessonExistsByNumber(outline, '1-1')).toBe(true)
		expect(lessonExistsByNumber(outline, '1-9')).toBe(false)
		expect(lessonExistsByName(outline, 'LESSON-B')).toBe(true)
		expect(lessonExistsByName(outline, 'LESSON-Z')).toBe(false)
	})
})

describe('isSelectionStale (delete clears the editor)', () => {
	it('is not stale while the selected lesson is still in the outline', () => {
		const selected = { number: '1-1', name: 'LESSON-A' }
		expect(isSelectionStale(selected, outline)).toBe(false)
	})

	it('is stale once the selected lesson is deleted from the outline', () => {
		// LESSON-A was deleted; LESSON-B resequenced into its old number "1-1".
		const afterDelete = [
			{
				name: 'CH-1',
				title: 'Chapter 1',
				idx: 1,
				lessons: [{ name: 'LESSON-B', title: 'Deep dive', number: '1-1' }],
			},
		]
		// The open lesson was LESSON-A at number 1-1. Tracking by number alone
		// would wrongly match LESSON-B's new 1-1; tracking by name catches it.
		const selected = { number: '1-1', name: 'LESSON-A' }
		expect(isSelectionStale(selected, afterDelete)).toBe(true)
	})

	it('does not flag a surviving lesson whose number shifted after a delete', () => {
		const afterDelete = [
			{
				name: 'CH-1',
				title: 'Chapter 1',
				idx: 1,
				lessons: [{ name: 'LESSON-B', title: 'Deep dive', number: '1-1' }],
			},
		]
		// LESSON-B is still open; only its number changed from 1-2 to 1-1.
		const selected = { number: '1-2', name: 'LESSON-B' }
		expect(isSelectionStale(selected, afterDelete)).toBe(false)
	})

	it('falls back to the number when no name was resolved', () => {
		expect(isSelectionStale({ number: '1-2' }, outline)).toBe(false)
		expect(isSelectionStale({ number: '9-9' }, outline)).toBe(true)
	})

	it('is never stale with no selection or no outline', () => {
		expect(isSelectionStale(null, outline)).toBe(false)
		expect(isSelectionStale({ name: 'LESSON-A' }, null)).toBe(false)
	})
})

describe('isLessonInChapter (chapter delete takes its lessons)', () => {
	it('is true when the lesson belongs to the named chapter', () => {
		expect(isLessonInChapter(outline, 'CH-1', 'LESSON-B')).toBe(true)
	})

	it('is false when the lesson is in a different chapter', () => {
		const twoChapters = [
			...outline,
			{
				name: 'CH-2',
				title: 'Chapter 2',
				idx: 2,
				lessons: [{ name: 'LESSON-C', title: 'Outro', number: '2-1' }],
			},
		]
		expect(isLessonInChapter(twoChapters, 'CH-2', 'LESSON-A')).toBe(false)
		expect(isLessonInChapter(twoChapters, 'CH-2', 'LESSON-C')).toBe(true)
	})

	it('is false for an unknown chapter, missing lesson, or empty outline', () => {
		expect(isLessonInChapter(outline, 'CH-9', 'LESSON-A')).toBe(false)
		expect(isLessonInChapter(outline, 'CH-1', null)).toBe(false)
		expect(isLessonInChapter(outline, 'CH-1', undefined)).toBe(false)
		expect(isLessonInChapter(null, 'CH-1', 'LESSON-A')).toBe(false)
	})
})

// Task 28: a lesson number is a dash-joined section path plus the lesson's
// position inside its own section — "2" legacy, "2-1-3" nested — and the tree
// helpers walk nested sections exactly like the flat ones walked chapters.
describe('parseLessonNumber', () => {
	it('splits a legacy number into chapter and lesson', () => {
		expect(parseLessonNumber('3-2')).toEqual({
			chapterNumber: '3',
			lessonNumber: '2',
		})
	})

	it('keeps the whole section path in the chapter segment', () => {
		expect(parseLessonNumber('2-1-3-2')).toEqual({
			chapterNumber: '2-1-3',
			lessonNumber: '2',
		})
	})

	it('tolerates an empty string', () => {
		expect(parseLessonNumber('')).toEqual({ chapterNumber: '', lessonNumber: '' })
	})
})

// A mixed section: children interleave by the child-table row each carries
// (positions 1..3), so document order is lesson, section, lesson — the single
// manual order the author edits.
const tree = [
	{
		name: 'CH-1',
		title: 'Chapter 1',
		idx: 1,
		level: 1,
		lessons: [
			{ name: 'LESSON-A', title: 'First', number: '1-1', position: 1 },
			{ name: 'LESSON-B', title: 'Second', number: '1-2', position: 3 },
		],
		sections: [
			{
				name: 'SUB-1',
				title: 'Nested',
				idx: 1,
				level: 2,
				position: 2,
				lessons: [
					{ name: 'LESSON-C', title: 'Nested lesson', number: '1-1-1', position: 1 },
				],
				sections: [],
			},
		],
	},
	{
		name: 'CH-2',
		title: 'Chapter 2',
		idx: 2,
		level: 1,
		lessons: [
			{ name: 'LESSON-D', title: 'Other chapter', number: '2-1', position: 1 },
		],
	},
]

describe('flattenLessons / forEachLesson (document order)', () => {
	it('walks lessons depth-first in the mixed child order', () => {
		expect(flattenLessons(tree).map((l) => l.name)).toEqual([
			'LESSON-A',
			'LESSON-C',
			'LESSON-B',
			'LESSON-D',
		])
	})

	it('visits the owning section alongside each lesson', () => {
		const visited: Array<[string, string]> = []
		forEachLesson(tree, (lesson, section) => visited.push([lesson.name, section.name]))
		expect(visited).toContainEqual(['LESSON-C', 'SUB-1'])
	})
})

describe('flattenSections', () => {
	it('collects sections of every level in document order', () => {
		expect(flattenSections(tree).map((s) => s.name)).toEqual(['CH-1', 'SUB-1', 'CH-2'])
	})
})

describe('lessonAncestors', () => {
	it('returns the section path down to the lesson holding the number', () => {
		expect(lessonAncestors(tree, '1-1-1').map((s) => s.name)).toEqual(['CH-1', 'SUB-1'])
	})

	it('returns a single ancestor for a legacy lesson', () => {
		expect(lessonAncestors(tree, '2-1').map((s) => s.name)).toEqual(['CH-2'])
	})

	it('returns an empty path for an unknown number', () => {
		expect(lessonAncestors(tree, '9-9')).toEqual([])
	})
})

describe('tree-aware lookups (task 28)', () => {
	it('finds nested lessons by number and by name', () => {
		expect(findLessonNameByNumber(tree, '1-1-1')).toBe('LESSON-C')
		expect(lessonExistsByName(tree, 'LESSON-C')).toBe(true)
		expect(lessonExistsByNumber(tree, '1-1-1')).toBe(true)
		expect(lessonExistsByNumber(tree, '1-2-1')).toBe(false)
	})

	it('treats a nested lesson as inside its ancestor section', () => {
		expect(isLessonInChapter(tree, 'SUB-1', 'LESSON-C')).toBe(true)
		expect(isLessonInChapter(tree, 'CH-1', 'LESSON-C')).toBe(true)
		expect(isLessonInChapter(tree, 'CH-2', 'LESSON-C')).toBe(false)
	})
})
