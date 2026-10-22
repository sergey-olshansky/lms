/**
 * Task #35 navigation (spec 1): the two homework tabs ride the app's one
 * sidebar mechanism. "Homework Execution" belongs to every signed-in user (all
 * are at least LMS Students); the teacher's "Homework" library appears only
 * for staff, mirroring Quizzes/Assignments. The routes they name must exist in
 * the real route table, which is importable without frappe-ui.
 *
 * R17: the library also has an authorised phone entrance -- mobileNavLinks adds
 * it to the You page's staff lists for instructors and never for students.
 */
import { describe, expect, it, vi } from 'vitest'

vi.hoisted(() => {
	// @/utils pulls in plyr, which touches matchMedia at import time, and
	// imports hoist above a plain stub assignment.
	window.matchMedia ??= (() => ({
		matches: false,
		addEventListener: () => {},
		removeEventListener: () => {},
	})) as unknown as typeof window.matchMedia
})

vi.stubGlobal('__', (text: string) => text)

const { userResource, settingsStore } = vi.hoisted(() => ({
	userResource: {
		data: { name: 'user@example.com', is_instructor: 0, is_moderator: 0 },
	},
	// The app destructures both `settings` and `programs` out of this store.
	settingsStore: {
		settings: { data: {} },
		programs: { data: { enrolled: [], published: [] } },
		sidebarSettings: { data: null },
		loadSidebarSettings: async () => {
			settingsStore.sidebarSettings.data = { sidebar_rows: [] }
		},
	},
}))

vi.mock('@/stores/user', () => ({
	usersStore: () => ({ userResource }),
}))
vi.mock('@/stores/settings', () => ({ useSettings: () => settingsStore }))
// mobileNavLinks asks the server about Programs for non-staff viewers; without
// this the student run rejects and the phone lists keep the previous viewer's
// rows -- exactly the staleness the store's memo guards against.
vi.mock('frappe-ui', () => ({
	call: async () => ({ enrolled: [], published: [] }),
}))

import { getSidebarLinks } from '@/utils/index'
import { routes } from '@/routes'
import {
	ensureMobileNavLinks,
	otherLinks,
	sidebarLinks,
} from '@/stores/mobileNavLinks'

const labels = (forMobile = false) =>
	getSidebarLinks(forMobile)
		.flatMap((group) => group.items)
		.map((item) => item.label)

describe('homework navigation', () => {
	it('shows the execution board to a plain student', () => {
		const all = labels()
		expect(all).toContain('Homework Execution')
		expect(all).not.toContain('Homework')
	})

	it('shows the library to an instructor', () => {
		userResource.data = {
			name: 't@example.com',
			is_instructor: 1,
			is_moderator: 0,
		}
		const all = labels()
		expect(all).toContain('Homework')
		expect(all).toContain('Homework Execution')
	})

	it('keeps the library off the mobile bar itself, like Quizzes', () => {
		userResource.data = {
			name: 't@example.com',
			is_instructor: 1,
			is_moderator: 0,
		}
		const mobile = labels(true)
		expect(mobile).not.toContain('Homework')
		expect(mobile).toContain('Homework Execution')
	})

	it('registers the homework routes in the real route table', () => {
		// Child routes (the create/edit forms) live nested under the library.
		const names = routes.flatMap((route) => [
			route.name,
			...(route.children || []).map((child) => child.name),
		])
		for (const name of [
			'HomeworkLibrary',
			'HomeworkNew',
			'HomeworkEdit',
			'HomeworkExecution',
			'HomeworkDetail',
		]) {
			expect(names).toContain(name)
		}
		const detail = routes.find((route) => route.name === 'HomeworkDetail')
		expect(detail?.path).toBe('/homework/assignment/:assignmentID')
	})
})

describe('homework on the phone (R17)', () => {
	it('lists the library on the You page for an instructor', async () => {
		await ensureMobileNavLinks({
			isSignedIn: true,
			isModerator: false,
			isInstructor: true,
			isEvaluator: false,
			hasUserInfo: true,
		})
		const other = otherLinks.value.map((link) => link.label)
		expect(other).toContain('Quizzes')
		expect(other).toContain('Homework')
		expect(sidebarLinks.value.map((link) => link.label)).not.toContain(
			'Homework'
		)
	})

	it('never lists the library for a plain student', async () => {
		await ensureMobileNavLinks({
			isSignedIn: true,
			isModerator: false,
			isInstructor: false,
			isEvaluator: false,
			hasUserInfo: true,
		})
		expect(otherLinks.value.map((link) => link.label)).not.toContain('Homework')
	})
})
