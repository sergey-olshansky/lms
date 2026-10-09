import { readFileSync } from 'node:fs'
import { describe, expect, it, vi, afterEach } from 'vitest'

const script = readFileSync(
	`${process.cwd()}/../lms/public/js/mytutor-login.js`,
	'utf8'
)

afterEach(() => {
	document.body.innerHTML = ''
	delete document.body.dataset.path
})

describe('native login presentation enhancement', () => {
	it('adds a non-submit keyboard toggle without replacing native field/handler; is idempotent', () => {
		vi.stubGlobal('__', (text: string) => text)
		document.body.dataset.path = 'login'
		document.body.innerHTML = `<div id="page-login"><div class="page_content"><div><section class="for-login"><div class="page-card-head"><h4>Login</h4></div><form class="form-login"><div class="password-field"><input id="login_password" type="password" autocomplete="current-password"><svg class="toggle-password" toggle="#login_password"><use href="#icon-eye"></use></svg></div></form></section></div></div></div>`
		const input = document.querySelector<HTMLInputElement>('#login_password')!
		const glyph = document.querySelector<SVGElement>('.toggle-password')!
		const handler = vi.fn(() => {
			input.type = input.type === 'password' ? 'text' : 'password'
		})
		glyph.addEventListener('click', handler)
		const run = () => {
			new Function(script)()
			document.dispatchEvent(new Event('DOMContentLoaded'))
		}
		run()
		const button = document.querySelector<HTMLButtonElement>(
			'.lms-password-toggle'
		)!
		expect(button.type).toBe('button')
		expect(button.getAttribute('aria-label')).toBe('Show password')
		button.click()
		expect(input.type).toBe('text')
		expect(button.getAttribute('aria-pressed')).toBe('true')
		expect(handler).toHaveBeenCalledTimes(1)
		glyph.dispatchEvent(new MouseEvent('click', { bubbles: true }))
		expect(input.type).toBe('password')
		expect(handler).toHaveBeenCalledTimes(2)
		expect(document.querySelector('#login_password')).toBe(input)
		expect(input.autocomplete).toBe('current-password')
		run()
		expect(document.querySelectorAll('.lms-password-toggle')).toHaveLength(1)
		expect(document.querySelectorAll('.lms-ai-divider')).toHaveLength(1)
		expect(
			document.querySelector('.lms-ai-divider')!.getAttribute('aria-hidden')
		).toBe('true')
	})
	it('does not alter other website pages', () => {
		document.body.innerHTML = '<main>Other app</main>'
		new Function(script)()
		document.dispatchEvent(new Event('DOMContentLoaded'))
		expect(document.body.innerHTML).toBe('<main>Other app</main>')
	})
})
