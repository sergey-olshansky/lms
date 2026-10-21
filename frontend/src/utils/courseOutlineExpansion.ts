/** Keep disclosure state by stable section ID, separately for each user/course. */
export function courseOutlineExpansionKey(
	course: string,
	user: string
): string {
	return `lms:outline-expansion:${encodeURIComponent(
		user
	)}:${encodeURIComponent(course)}`
}

function read(key: string): Record<string, boolean> {
	try {
		const value: unknown = JSON.parse(localStorage.getItem(key) ?? '{}')
		return value && typeof value === 'object' && !Array.isArray(value)
			? (value as Record<string, boolean>)
			: {}
	} catch {
		return {}
	}
}

export function isSectionExpanded(key: string, section: string): boolean {
	return read(key)[section] === true
}

export function rememberSectionExpansion(
	key: string,
	section: string,
	open: boolean
): void {
	try {
		localStorage.setItem(key, JSON.stringify({ ...read(key), [section]: open }))
	} catch {
		// Disclosure still works when browser storage is unavailable.
	}
}
