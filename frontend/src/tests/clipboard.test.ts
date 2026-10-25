import { afterEach, describe, expect, it, vi } from 'vitest'
import { copyText } from '@/utils/clipboard'

afterEach(() => {
	vi.restoreAllMocks()
	vi.unstubAllGlobals()
	document.body.innerHTML = ''
})

describe('sharing homework on HTTPS and HTTP', () => {
	it('uses the browser clipboard when available', async () => {
		const writeText = vi.fn().mockResolvedValue(undefined)
		vi.stubGlobal('navigator', { clipboard: { writeText } })
		await copyText('https://example.com/lms/homework/assignment/one')
		expect(writeText).toHaveBeenCalledWith(
			'https://example.com/lms/homework/assignment/one'
		)
	})

	it('copies on HTTP and restores focus without leaving a hidden field', async () => {
		vi.stubGlobal('navigator', {})
		const button = document.createElement('button')
		document.body.appendChild(button)
		button.focus()
		const exec = vi.fn(() => true)
		Object.defineProperty(document, 'execCommand', {
			configurable: true,
			value: exec,
		})
		await copyText('http://example.com/homework')
		expect(exec).toHaveBeenCalledWith('copy')
		expect(document.querySelector('textarea')).toBeNull()
		expect(document.activeElement).toBe(button)
	})

	it('surfaces failure if neither browser method is available', async () => {
		vi.stubGlobal('navigator', {
			clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
		})
		Object.defineProperty(document, 'execCommand', {
			configurable: true,
			value: () => false,
		})
		await expect(copyText('link')).rejects.toThrow('Clipboard unavailable')
		expect(document.querySelector('textarea')).toBeNull()
	})
})
