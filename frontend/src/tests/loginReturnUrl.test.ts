import { beforeEach, describe, expect, it, vi } from 'vitest'

// Task #35 (E01): a guest hitting a deep SPA link is sent to the login with
// the FULL address (base path + route + query + hash) as redirect-to, so the
// post-login landing is the very page they opened — not the home screen.
// The redirect value is router-relative, so the base path must be re-attached
// by the guard, not read from the URL bar.
vi.mock('@/stores/user', () => ({
	usersStore: () => ({
		userResource: { promise: Promise.resolve({}), data: {}, reload: () => {} },
	}),
}))
vi.mock('@/stores/session', () => ({
	sessionStore: () => ({ isLoggedIn: false, user: null, brand: {} }),
}))
vi.mock('@/stores/settings', () => ({
	useSettings: () => ({
		settings: { promise: Promise.resolve({}), data: { allow_guest_access: false } },
	}),
}))
vi.mock('frappe-ui', () => ({ call: vi.fn() }))

import { guardNavigation } from '@/router'

describe('guardNavigation login redirect (E01)', () => {
	beforeEach(() => {
		vi.clearAllMocks()
	})

	it('carries the full deep address through redirect-to', async () => {
		const hrefSetter = vi.fn()
		Object.defineProperty(window, 'location', {
			writable: true,
			value: { href: '', assign: hrefSetter },
		})
		window.lms_path = 'lms'

		const next = vi.fn()
		await guardNavigation(
			{
				name: 'HomeworkDetail',
				path: '/homework/assignment/HW-0001',
				fullPath: '/homework/assignment/HW-0001?tab=checklist#next',
			},
			{ name: 'Courses', path: '/courses' },
			next
		)

		expect(window.location.href).toContain('/login?redirect-to=')
		const encoded = encodeURIComponent(
			'/lms/homework/assignment/HW-0001?tab=checklist#next'
		)
		expect(window.location.href).toContain(encoded)
		expect(next).not.toHaveBeenCalled()
	})

	it('keeps the app base path when it is customized', async () => {
		Object.defineProperty(window, 'location', {
			writable: true,
			value: { href: '', assign: vi.fn() },
		})
		window.lms_path = 'study'

		const next = vi.fn()
		await guardNavigation(
			{
				name: 'Lesson',
				path: '/courses/COURSE-1/learn/2-1-3',
				fullPath: '/courses/COURSE-1/learn/2-1-3?hw=HW-0001',
			},
			{ name: 'Courses', path: '/courses' },
			next
		)

		const encoded = encodeURIComponent(
			'/study/courses/COURSE-1/learn/2-1-3?hw=HW-0001'
		)
		expect(window.location.href).toContain(encoded)
	})
})
