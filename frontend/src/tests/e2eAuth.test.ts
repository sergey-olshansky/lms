import { describe, expect, it, vi } from 'vitest'
import type { Page } from '@playwright/test'
import { authenticate } from '../../../e2e/auth'

function fixture() {
	const response = (
		ok: boolean,
		status = 200,
		message = 'frappe@example.com'
	) => ({
		ok: () => ok,
		status: () => status,
		json: async () => ({ message }),
	})
	const storageState = vi.fn().mockResolvedValue({ cookies: [{ name: 'sid' }] })
	const page = {
		request: {
			post: vi
				.fn()
				.mockResolvedValueOnce(response(true))
				.mockResolvedValueOnce(response(true)),
		},
		goto: vi.fn().mockResolvedValue(response(true)),
		evaluate: vi.fn().mockResolvedValue('server-session-token'),
		context: () => ({ storageState }),
	}
	return {
		page,
		storageState,
		response,
		run: () =>
			authenticate(
				page as unknown as Page,
				'frappe@example.com',
				'admin',
				'auth.json'
			),
	}
}

describe('e2e authenticated bootstrap', () => {
	it('uses the page session token without requiring a CSRF cookie', async () => {
		const { page, storageState, run } = fixture()
		await run()
		expect(page.request.post).toHaveBeenNthCalledWith(
			2,
			'/api/method/frappe.auth.get_logged_user',
			{
				headers: { 'X-Frappe-CSRF-Token': 'server-session-token' },
			}
		)
		expect(storageState).toHaveBeenCalledWith({ path: 'auth.json' })
	})

	it('does not save an unauthenticated login', async () => {
		const { page, storageState, response, run } = fixture()
		page.request.post.mockReset().mockResolvedValue(response(false, 401))
		await expect(run()).rejects.toThrow(
			'Login as frappe@example.com failed: 401'
		)
		expect(page.goto).not.toHaveBeenCalled()
		expect(storageState).not.toHaveBeenCalled()
	})

	it('fails bootstrap errors before saving authentication', async () => {
		const { page, storageState, response, run } = fixture()
		page.goto.mockResolvedValue(response(false, 500))
		await expect(run()).rejects.toThrow(
			'Authenticated app bootstrap failed: 500'
		)
		expect(storageState).not.toHaveBeenCalled()
	})

	it.each([undefined, '', ' ', 'None'])(
		'rejects missing session token %s',
		async (token) => {
			const { page, storageState, run } = fixture()
			page.evaluate.mockResolvedValue(token)
			await expect(run()).rejects.toThrow('did not expose a CSRF token')
			expect(page.request.post).toHaveBeenCalledTimes(1)
			expect(storageState).not.toHaveBeenCalled()
		}
	)

	it('retains the server rejection when the token does not match the session', async () => {
		const { page, storageState, response, run } = fixture()
		page.request.post
			.mockReset()
			.mockResolvedValueOnce(response(true))
			.mockResolvedValueOnce(response(false, 400))
		await expect(run()).rejects.toThrow('Authenticated CSRF probe failed: 400')
		expect(storageState).not.toHaveBeenCalled()
	})

	it('rejects an expired or wrong user session', async () => {
		const { page, storageState, response, run } = fixture()
		page.request.post
			.mockReset()
			.mockResolvedValueOnce(response(true))
			.mockResolvedValueOnce(response(true, 200, 'Guest'))
		await expect(run()).rejects.toThrow('did not retain the expected user')
		expect(storageState).not.toHaveBeenCalled()
	})
})
