import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const css = readFileSync('src/styles/mytutor.css', 'utf8')
const sidebar = readFileSync('src/components/Sidebar/AppSidebar.vue', 'utf8')

describe('compact sidebar and accessible quiz palette', () => {
	it('keeps compact desktop controls and generous coarse-pointer targets', () => {
		expect(css).toMatch(/sidebar-item'\] \{\s*min-height: 32px/)
		expect(css).toMatch(/sidebar-header'\] \{\s*height: 40px/)
		expect(css).toMatch(/sidebar-item'\] svg \{\s*width: 16px;\s*height: 16px/)
		expect(css).toMatch(/@media \(pointer: coarse\)[\s\S]*min-height: 44px/)
		expect(css).toContain('outline: 2px solid var(--lms-action)')
		expect(sidebar).toContain('overflow-y-auto px-2 pt-1')
		expect(sidebar).toContain('flex flex-col gap-0.5')
	})
	it('keeps solid quiz actions secondary/primary even under native disabled utilities', () => {
		expect(css).toMatch(
			/\.lms-quiz-secondary:disabled \{\s*background: var\(--lms-secondary\);\s*color: var\(--lms-secondary-text\)/
		)
		expect(css).toMatch(
			/\.lms-quiz-primary:disabled \{\s*background: var\(--lms-action\);\s*color: var\(--lms-surface\)/
		)
	})
	it('keeps secondary quiz text accessible without changing the primary palette', () => {
		expect(css).toContain('--lms-secondary: #d8eff1')
		expect(css).toContain('--lms-secondary-text: #077581')
		expect(css).toContain('--lms-action: #087985')
		expect(css).toMatch(
			/\.lms-quiz-secondary \{\s*background: var\(--lms-secondary\);\s*color: var\(--lms-secondary-text\)/
		)
		const luminance = (hex: string) => {
			const channels = hex.match(/[a-f\d]{2}/gi)!.map((channel) => {
				const value = parseInt(channel, 16) / 255
				return value <= 0.04045
					? value / 12.92
					: ((value + 0.055) / 1.055) ** 2.4
			})
			return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
		}
		expect(css).toMatch(
			/\.lms-quiz-secondary:hover:not\(:disabled\) \{\s*background: var\(--lms-secondary-hover\);\s*color: var\(--lms-action-hover\)/
		)
		expect(css).toMatch(
			/\.lms-quiz-secondary:active:not\(:disabled\) \{\s*background: var\(--lms-pressed\);\s*color: var\(--lms-action-pressed\)/
		)
		for (const [background, foreground] of [
			['d8eff1', '077581'],
			['c9e7ea', '066a75'],
			['cde3e8', '055c66'],
		]) {
			expect(
				(luminance(background) + 0.05) / (luminance(foreground) + 0.05)
			).toBeGreaterThanOrEqual(4.5)
		}
	})
})
