// Task #35: pure selection maths for the homework material picker (spec 3.4).
//
// Everything here works on the server resolver's tree shape
// (lms.lms.homework_sources.get_course_source_tree): chapters carry `children`,
// lessons carry `quizzes` and live inside a chapter, standalone quiz/assignment
// nodes sit at the course root. Selection is a Set of stable leaf keys held by
// the picker across course switches, searches and pagination -- the confirmed
// selection only ever changes through "Add selected" (A08).
//
// Pure on purpose: dedup, tri-state and path building are unit-tested without a
// Frappe site, mirroring how courseOutline.ts and lessonProgress.ts work.

export interface TreeNode {
	key: string
	type: 'chapter' | 'lesson' | 'quiz' | 'assignment'
	name: string
	title: string
	children?: TreeNode[]
	quizzes?: { name: string; title: string }[]
	chapter?: string
	assignable?: boolean
}

export interface SelectionEntry {
	source_type: 'Lesson' | 'Quiz' | 'Assignment'
	name: string
	course: string
	title: string
	chapter: string
	path: string
}

export const nodeKey = (node: TreeNode): string => node.key

// A container's selectable leaves: every assignable lesson/quiz/assignment node
// in its subtree. Chapters with no assignable content are not homework work and
// contribute nothing (spec 3.4.5) -- an empty chapter shows, but selects nothing.
export function collectLeafKeys(node: TreeNode): string[] {
	if (isLeaf(node)) {
		return node.assignable === false ? [] : [nodeKey(node)]
	}
	const keys: string[] = []
	for (const child of node.children || []) {
		keys.push(...collectLeafKeys(child))
	}
	return keys
}

export function isLeaf(node: TreeNode): boolean {
	return node.type !== 'chapter'
}

export type CheckState = 'checked' | 'unchecked' | 'indeterminate'

export function checkState(node: TreeNode, selected: Set<string>): CheckState {
	const leaves = collectLeafKeys(node)
	if (leaves.length === 0) return 'unchecked'
	const picked = leaves.filter((key) => selected.has(key)).length
	if (picked === 0) return 'unchecked'
	if (picked === leaves.length) return 'checked'
	// A partially picked container is visibly indeterminate (spec 3.4.2).
	return 'indeterminate'
}

export function toggleNode(
	node: TreeNode,
	selected: Set<string>,
	checked: boolean
): Set<string> {
	const next = new Set(selected)
	for (const key of collectLeafKeys(node)) {
		if (checked) next.add(key)
		else next.delete(key)
	}
	return next
}

// The whole subtree under every node, flattened, with the human path carried in.
// Paths use " / " separators exactly like the server snapshots, so a picker row
// and the stored requirement row read the same way.
export function flattenWithPaths(
	nodes: TreeNode[],
	prefix: string[] = []
): Map<string, { node: TreeNode; path: string; chapter: string }> {
	const index = new Map<
		string,
		{ node: TreeNode; path: string; chapter: string }
	>()
	for (const node of nodes) {
		const path = [...prefix, node.title].join(' / ')
		if (isLeaf(node)) {
			index.set(nodeKey(node), {
				node,
				path,
				chapter: prefix[prefix.length - 1] || '',
			})
		}
		if (node.children) {
			for (const [key, value] of flattenWithPaths(node.children, [
				...prefix,
				node.title,
			])) {
				index.set(key, value)
			}
		}
	}
	return index
}

// Selected keys -> normalized entries for save_homework. The server dedupes on
// (type, name) again, so parent-and-child both picked stays one row (A07), and
// entries survive across courses because every tree keeps its own index.
export function selectionToEntries(
	selected: Set<string>,
	courses: Map<
		string,
		Map<string, { node: TreeNode; path: string; chapter: string }>
	>
): SelectionEntry[] {
	const entries: SelectionEntry[] = []
	const seen = new Set<string>()
	for (const [courseName, index] of courses) {
		for (const key of selected) {
			const found = index.get(key)
			if (!found) continue
			const source_type =
				found.node.type === 'chapter' ? 'Lesson' : capitalise(found.node.type)
			const dedupeKey = `${source_type}:${found.node.name}`
			if (seen.has(dedupeKey)) continue
			seen.add(dedupeKey)
			entries.push({
				source_type,
				name: found.node.name,
				course: courseName,
				title: found.node.title,
				chapter: found.chapter,
				path: found.path,
			})
		}
	}
	return entries
}

function capitalise(value: string): string {
	return value.charAt(0).toUpperCase() + value.slice(1)
}

// Case-insensitive title match for the picker's search, container included so a
// matching chapter keeps its whole subtree reachable.
export function matchesSearch(node: TreeNode, query: string): boolean {
	if (!query.trim()) return true
	const needle = query.trim().toLowerCase()
	if (node.title.toLowerCase().includes(needle)) return true
	return (node.children || []).some((child) => matchesSearch(child, needle))
}

// The board's «3 / 5 · 1 / 2» progress line, from requirement counters
// (spec 5.2). Quiz progress rides along when the work has quizzes; the labels
// themselves are the component's business, translated there.
export function progressLine(counters: {
	completed_requirements: number
	total_requirements: number
	quizzes_completed: number
	quizzes_total: number
}): string {
	const base = `${counters.completed_requirements} / ${counters.total_requirements}`
	if (counters.quizzes_total > 0) {
		return `${base} · ${counters.quizzes_completed} / ${counters.quizzes_total}`
	}
	return base
}

// An outline lesson number is "path-…-lesson" (task #28: a lesson in section 2,
// subsection 1 is "2-1-3"). The SPA route takes the section path as
// chapterNumber and the last segment as lessonNumber -- the same split
// SidebarSection performs for the course's own navigation.
export function lessonRouteParams(number: string): {
	chapterNumber: string
	lessonNumber: string
} {
	const segments = String(number).split('-')
	const lessonNumber = segments.pop() || '1'
	return { chapterNumber: segments.join('-') || '1', lessonNumber }
}
