// Tutor-specific navigation preferences. Features and routes stay available;
// only their entry points are hidden from the sidebar and mobile navigation.
export const HIDDEN_SIDEBAR_ITEMS: readonly string[] = [
	'Certifications',
	'Jobs',
	'Programming Exercises',
]

export const SHOW_SIDEBAR_HELP = false
export const SHOW_FRAPPE_ATTRIBUTION = false

export function isSidebarItemHidden(label: string): boolean {
	return HIDDEN_SIDEBAR_ITEMS.includes(label)
}
