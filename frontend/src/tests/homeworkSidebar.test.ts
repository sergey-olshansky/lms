/** One role-aware homework workspace, preserving issued-work deep links. */
import { beforeEach, describe, expect, it, vi } from 'vitest'

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

beforeEach(() => {
	userResource.data = {
		name: 'student@example.com',
		is_instructor: 0,
		is_moderator: 0,
	}
})

const homeworkLinks = (mobile = false) =>
	getSidebarLinks(mobile)
		.flatMap((group) => group.items)
		.filter((item) => item.label === 'Homework workspace')

describe('one homework workspace for each role', () => {
	it('gives a student one entrance to their own board and no groups', () => {
		expect(homeworkLinks()).toHaveLength(1)
		expect(homeworkLinks()[0].to).toBe('HomeworkExecution')
		expect(labels()).not.toContain('Batches')
	})

	it('gives the teacher one entrance spanning templates, issue and execution', () => {
		userResource.data.is_instructor = 1
		expect(homeworkLinks()).toHaveLength(1)
		expect(homeworkLinks()[0].to).toBe('HomeworkLibrary')
		expect(homeworkLinks()[0].activeFor).toEqual(
			expect.arrayContaining([
				'HomeworkNew',
				'HomeworkEdit',
				'HomeworkExecution',
				'HomeworkDetail',
			])
		)
		expect(labels()).not.toContain('Batches')
	})

	it('has the same single entrance on mobile', () => {
		userResource.data.is_instructor = 1
		expect(homeworkLinks(true)).toHaveLength(1)
		expect(homeworkLinks(true)[0].to).toBe('HomeworkLibrary')
	})

	it('preserves direct links to existing homework pages', () => {
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
		expect(routes.find((route) => route.name === 'HomeworkDetail')?.path).toBe(
			'/homework/assignment/:assignmentID'
		)
	})

	it('does not duplicate the teacher workspace in the phone overflow', async () => {
		userResource.data.is_instructor = 1
		await ensureMobileNavLinks({
			isSignedIn: true,
			isModerator: false,
			isInstructor: true,
			isEvaluator: false,
			hasUserInfo: true,
		})
		const combined = [...sidebarLinks.value, ...otherLinks.value]
		expect(
			combined.filter((link) => link.label === 'Homework workspace')
		).toHaveLength(1)
		expect(combined.some((link) => link.label === 'Homework')).toBe(false)
	})
})
