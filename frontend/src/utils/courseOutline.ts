import type { OutlineChapter, OutlineLesson } from '@/types'

type Chapters = OutlineChapter[] | null | undefined

/**
 * A lesson number is a dash-joined section path plus the lesson's position
 * inside its own section: "2" legacy, "2-1-3" nested. The lesson is always the
 * LAST segment, everything before it is the section path.
 */
export function parseLessonNumber(
	number: string
): { chapterNumber: string; lessonNumber: string } {
	const segments = (number || '').split('-')
	const lessonNumber = segments.pop() ?? ''
	return {
		chapterNumber: segments.join('-'),
		lessonNumber,
	}
}

/** Every lesson of the tree, in document (depth-first) order. */
export function flattenLessons(chapters: Chapters): OutlineLesson[] {
	const lessons: OutlineLesson[] = []
	forEachLesson(chapters, (lesson) => lessons.push(lesson))
	return lessons
}

/** Walk every lesson of the tree in document (depth-first) order.
 *
 * Children interleave by the child-table position each carries, so a nested
 * section's lessons sit exactly where the author placed them among the
 * section's own lessons — the same single order the server numbers from.
 */
export function forEachLesson(
	chapters: Chapters,
	fn: (lesson: OutlineLesson, section: OutlineChapter) => void
): void {
	for (const chapter of chapters ?? []) {
		const children: Array<{
			position: number
			lesson?: OutlineLesson
			node?: OutlineChapter
		}> = [
			...(chapter.lessons ?? []).map((lesson) => ({
				position: lesson.position ?? Number.MAX_SAFE_INTEGER,
				lesson,
			})),
			...(chapter.sections ?? []).map((node) => ({
				position: node.position ?? Number.MAX_SAFE_INTEGER,
				node,
			})),
		].sort((a, b) => a.position - b.position)
		for (const child of children) {
			if (child.lesson) fn(child.lesson, chapter)
			else if (child.node) forEachLesson([child.node], fn)
		}
	}
}

/** Every section of the tree (all levels), in document order. */
export function flattenSections(chapters: Chapters): OutlineChapter[] {
	const sections: OutlineChapter[] = []
	const walk = (nodes: Chapters) => {
		for (const chapter of nodes ?? []) {
			sections.push(chapter)
			if (chapter.sections?.length) walk(chapter.sections)
		}
	}
	walk(chapters)
	return sections
}

/** The sections from a level-1 section down to the one holding the lesson. */
export function lessonAncestors(
	chapters: Chapters,
	number: string
): OutlineChapter[] {
	const find = (nodes: Chapters, path: OutlineChapter[]): OutlineChapter[] | null => {
		for (const chapter of nodes ?? []) {
			const nextPath = [...path, chapter]
			if (chapter.lessons?.some((l) => l.number === number)) return nextPath
			const nested = find(chapter.sections, nextPath)
			if (nested) return nested
		}
		return null
	}
	return find(chapters, []) ?? []
}

export function findLessonNameByNumber(
	chapters: Chapters,
	number: string
): string | null {
	for (const chapter of chapters ?? []) {
		const lesson = chapter.lessons?.find((l) => l.number === number)
		if (lesson) return lesson.name
		if (chapter.sections?.length) {
			const nested = findLessonNameByNumber(chapter.sections, number)
			if (nested) return nested
		}
	}
	return null
}

export function lessonExistsByNumber(
	chapters: Chapters,
	number: string
): boolean {
	return !!(
		number &&
		flattenLessons(chapters).some((l) => l.number === number)
	)
}

export function lessonExistsByName(chapters: Chapters, name: string): boolean {
	return !!(name && flattenLessons(chapters).some((l) => l.name === name))
}

export interface LessonSelection {
	number?: string
	name?: string | null
}

/**
 * A lesson selection is stale once the lesson it points at has left the outline
 * (e.g. it was deleted). Prefer the stable docname: the positional `number`
 * shifts when lesson references resequence on delete/reorder, so it's only a
 * fallback when a name wasn't resolved.
 */
export function isSelectionStale(
	selected: LessonSelection | null | undefined,
	chapters: Chapters
): boolean {
	if (!selected || !chapters) return false
	return selected.name
		? !lessonExistsByName(chapters, selected.name)
		: !lessonExistsByNumber(chapters, selected.number ?? '')
}

/**
 * Whether `lessonName` lives in the section `chapterName`. Used when a section is
 * deleted to decide whether the open lesson went with it, resolved against the
 * still-current outline (the delete's reload hasn't landed yet) so the editor can
 * suppress that lesson's teardown flush before it writes to the deleted document.
 *
 * Generalized to "ancestor of": a lesson anywhere inside the deleted subtree is
 * going with it, however deep the nesting.
 */
export function isLessonInChapter(
	chapters: Chapters,
	chapterName: string,
	lessonName: string | null | undefined
): boolean {
	if (!lessonName) return false
	const section = flattenSections(chapters).find((c) => c.name === chapterName)
	if (!section) return false
	return flattenLessons([section]).some((l) => l.name === lessonName)
}
